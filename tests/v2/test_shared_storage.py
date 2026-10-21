"""验证共享材料实际字节、固定Git版本和显式schema升级，不连接共享数据库或RustFS。"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from opentest.adapters.java_dependencies import MavenArtifact
from opentest.adapters.object_storage import (
    ObjectStorage, ObjectStorageConfiguration, archive_dependencies, archive_git_source, read_frozen_dependencies,
)
from opentest.adapters.shared_schema_upgrade import ADDED_COLUMNS, NEW_TABLES, SharedSchemaUpgrade, _schema_statements
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.shared_workspace import CodeBaseline


class MemoryS3:
    """只保存真实字节的SDK替身，避免材料测试依赖网络或真实凭据。"""

    def __init__(self):
        """初始化独立对象字节集合和下载故障开关。"""

        self.objects = {}
        self.truncate_download = False

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        """接受标准SDK上传参数并读取文件实际字节，禁止key被覆盖。"""

        assert (bucket, key) not in self.objects
        self.objects[bucket, key] = Path(filename).read_bytes()

    def head_object(self, *, Bucket, Key):
        """返回真实对象长度，供上传读后检查验证。"""

        return {"ContentLength": len(self.objects[Bucket, Key])}

    def get_object(self, *, Bucket, Key, Range=None):
        """实现测试所需标准Range或空文件读取，返回可关闭流。"""

        end = int(Range.split("-")[1]) if Range else len(self.objects[Bucket, Key])
        return {"Body": io.BytesIO(self.objects[Bucket, Key][:end + 1])}

    def download_file(self, bucket, key, filename):
        """下载真实对象；故障模式故意截断以验证目标文件不会被损坏覆盖。"""

        payload = self.objects[bucket, key]
        Path(filename).write_bytes(payload[:-1] if self.truncate_download else payload)


def object_store() -> ObjectStorage:
    """返回完全隔离的材料存储，配置值无真实凭据且不会创建生产SDK。"""

    return ObjectStorage(ObjectStorageConfiguration(endpoint_url="http://example.invalid:9000", access_key="test", secret_key="test"), MemoryS3())


def git(repository: Path, *arguments: str) -> str:
    """在隔离仓库执行明确Git命令；返回stdout，测试不接触用户仓库。"""

    completed = subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def test_shared_source_uses_fixed_commit_and_materializes_without_repository(tmp_path):
    """另一机器无Git仓库时仍可从共享实际包读取固定内容，未提交文件绝不能被上传。"""

    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init")
    (repository / "Main.java").write_text("committed source", encoding="utf-8")
    git(repository, "add", "Main.java")
    git(repository, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial")
    expected_commit = git(repository, "rev-parse", "HEAD")
    # 修改和未追踪源码留在原机；共享包只能来自解析出的固定commit。
    (repository / "Main.java").write_text("dirty source", encoding="utf-8")
    (repository / "secret.txt").write_text("untracked", encoding="utf-8")
    archive = tmp_path / "source.tar.gz"
    assert archive_git_source(repository, "HEAD", archive) == expected_commit
    storage = object_store()
    artifact = storage.upload_file(archive, "SOURCE", "employee-1")
    shutil.rmtree(repository)
    archive.unlink()
    materialized = storage.materialize_archive(artifact, tmp_path / "other-machine")
    assert (materialized / "Main.java").read_text() == "committed source"
    assert not (materialized / "secret.txt").exists()
    assert storage.materialize_archive(artifact, tmp_path / "other-machine") == materialized


def test_dependency_archive_preserves_actual_order_bytes_and_missing_items(tmp_path):
    """依赖包跨机器保留classpath顺序和缺失项，不能从另一机器的Maven缓存补造。"""

    first = tmp_path / "first.jar"
    first.write_bytes(b"exact binary one")
    second = tmp_path / "second.jar"
    second.write_bytes(b"exact binary two")
    source = tmp_path / "first-sources.jar"
    source.write_bytes(b"exact source")
    binary_link = tmp_path / "linked-first.jar"
    binary_link.symlink_to(first)
    artifacts = [MavenArtifact("a:first:1", binary_link, source), MavenArtifact("b:second:SNAPSHOT", second, tmp_path / "absent-sources.jar"),
                 MavenArtifact("c:missing:1", tmp_path / "absent.jar", tmp_path / "absent-sources.jar")]
    archive = tmp_path / "dependencies.tar.gz"
    manifest = archive_dependencies(artifacts, ["原始解析缺口"], archive)
    storage = object_store()
    ref = storage.upload_file(archive, "DEPENDENCIES", "employee-1")
    first.unlink()
    second.unlink()
    source.unlink()
    directory = storage.materialize_archive(ref, tmp_path / "other-machine")
    restored, gaps = read_frozen_dependencies(directory)
    assert [item.coordinate for item in restored] == [item.coordinate for item in artifacts]
    assert restored[0].binary.read_bytes() == b"exact binary one"
    assert restored[1].binary.read_bytes() == b"exact binary two"
    assert restored[0].sources.read_bytes() == b"exact source"
    assert not restored[2].binary.exists()
    assert gaps == ["原始解析缺口", "原扫描未取得二进制：c:missing:1"]
    assert str(tmp_path) not in manifest.model_dump_json()


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt"])
def test_materialization_rejects_escaping_archive_paths(tmp_path, name):
    """上传包即使来自其他工作台也不能把内容写到缓存目录之外。"""

    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        info = tarfile.TarInfo(name)
        info.size = 4
        output.addfile(info, io.BytesIO(b"oops"))
    storage = object_store()
    ref = storage.upload_file(archive, "SOURCE", "employee-1")
    with pytest.raises(KnowledgeValidationError, match="非法路径"):
        storage.materialize_archive(ref, tmp_path / "cache")
    assert not (tmp_path / "cache" / ref.artifact_id).exists()
    assert not (tmp_path / "escape.txt").exists()


def test_failed_download_keeps_existing_local_file(tmp_path):
    """半份远端材料不能覆盖已有完整文件，也不能留下可被误用的临时文件。"""

    source = tmp_path / "dump.exec"
    source.write_bytes(b"full exec bytes")
    storage = object_store()
    artifact = storage.upload_file(source, "COVERAGE_EXEC", "employee-1")
    target = tmp_path / "download.exec"
    target.write_bytes(b"previous complete material")
    storage.client.truncate_download = True
    with pytest.raises(KnowledgeValidationError, match="不完整"):
        storage.download_file(artifact, target)
    assert target.read_bytes() == b"previous complete material"
    assert not list(tmp_path.glob(".opentest-download-*"))


class SchemaCatalog:
    """记录显式升级器的读写，用现有13表目录验证dry-run不会执行DDL。"""

    def __init__(self):
        """初始化旧安装目录和空的已执行语句集合。"""

        self.tables = set(_schema_statements()) - NEW_TABLES
        self.executed = []

    def fetch_all(self, sql, parameters=()):
        """返回旧schema目录，只允许information_schema读取。"""

        assert "information_schema." in sql
        if "information_schema.TABLES" in sql:
            return [{"table_name": name} for name in self.tables]
        return []

    def execute(self, sql):
        """记录受控DDL，普通查询不能意外落入执行路径。"""

        assert sql.startswith(("CREATE TABLE IF NOT EXISTS", "ALTER TABLE"))
        self.executed.append(sql)


def test_schema_upgrade_is_explicit_and_uses_exact_install_definitions():
    """旧13表升级生成7新表和5表增量，dry-run无写入，只有显式apply才执行。"""

    catalog = SchemaCatalog()
    upgrade = SharedSchemaUpgrade(catalog)
    actions = upgrade.plan()
    assert not catalog.executed
    assert len([item for item in actions if item.kind == "CREATE_TABLE"]) == 7
    assert len([item for item in actions if item.kind == "ADD_COLUMN"]) == sum(map(len, ADDED_COLUMNS.values()))
    assert {item.table for item in actions if item.kind == "ADD_COLUMN"} == set(ADDED_COLUMNS)
    assert len([item for item in actions if item.kind == "ADD_INDEX"]) == 4
    assert not any("DROP " in item.sql or "DELETE " in item.sql for item in actions)
    assert upgrade.apply() == actions
    assert len(catalog.executed) == len(actions)


def test_schema_guard_rejects_old_database_without_writing(tmp_path):
    """启动检查只读拒绝旧结构，中文提示给出可操作迁移命令，不能在启动时偷偷升级。"""

    catalog = SchemaCatalog()
    with pytest.raises(KnowledgeValidationError, match="尚未升级（待处理23项）") as failure:
        SharedSchemaUpgrade(catalog).require_current(tmp_path / "knowledge")
    assert "shared_schema_upgrade --knowledge-root" in str(failure.value)
    assert "--apply" in str(failure.value)
    assert catalog.executed == []


def test_schema_guard_accepts_current_database_once(monkeypatch, tmp_path):
    """兼容数据库每次服务组装只检查一次，不把结构探测放进用户请求路径。"""

    calls = []

    def current_plan(self):
        """记录只读目录检查次数，以空计划模拟当前安装结构。"""

        calls.append(self.metadata)
        return []

    monkeypatch.setattr(SharedSchemaUpgrade, "plan", current_plan)
    catalog = SchemaCatalog()
    SharedSchemaUpgrade(catalog).require_current(tmp_path)
    assert calls == [catalog]
    assert catalog.executed == []


def test_service_startup_closes_old_database_before_constructing_stores(monkeypatch, tmp_path):
    """真实启动入口先校验结构并释放失败连接，避免登录时缺表500或旧任务恢复写入。"""

    from opentest.application import foundation

    class StartupCatalog(SchemaCatalog):
        """提供启动连接探测并记录连接释放，仍使用真实只读升级检查。"""

        def fetch_one(self, sql):
            """只允许启动连接探测，不返回伪造业务记录。"""

            assert sql == "SELECT 1 AS connected"
            return {"connected": 1}

        def close(self):
            """记录旧结构失败后的连接清理，供资源释放断言使用。"""

            self.closed = True

    catalog = StartupCatalog()

    def load_catalog(root):
        """仅替换连接配置入口，启动校验和组件装配顺序仍执行生产实现。"""

        assert root == tmp_path
        return catalog

    monkeypatch.setattr(foundation, "load_metadata_store", load_catalog)
    application = object.__new__(foundation.OpenTestApplication)
    application.knowledge_root = tmp_path
    # 不构造完整应用，因此失败前后的组件是否存在能够证明校验的实际调用顺序。
    with pytest.raises(KnowledgeValidationError, match="尚未升级"):
        application._initialize_persistence()
    assert catalog.closed
    assert not hasattr(application, "store")
    assert not hasattr(application, "tasks")
    assert catalog.executed == []


def test_legacy_baseline_never_fabricates_a_commit():
    """历史无法确认Git来源时必须保留独立LEGACY身份，不与某个当前commit合并。"""

    baseline = CodeBaseline(baseline_id="legacy-a", system_id="system", source_kind="LEGACY")
    assert baseline.source_commit is None
    with pytest.raises(ValueError, match="不能补造commit"):
        CodeBaseline(baseline_id="legacy-b", system_id="system", source_kind="LEGACY", source_commit="a" * 40)
