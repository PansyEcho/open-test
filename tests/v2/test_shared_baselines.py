"""验证同commit去重、背景独立、草稿阶段续跑及固定依赖，不连接真实服务。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tarfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from opentest.adapters.java_dependencies import JavaDependencyCatalog, MavenArtifact, bind_frozen_dependencies
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.adapters.shared_workspace_store import SharedWorkspaceStore
from opentest.adapters.shared_history_migration import SharedHistoryMigration
from opentest.application.shared_baselines import SharedBaselineService
from opentest.application.shared_interface_knowledge import SharedInterfaceKnowledgeService
from opentest.application.publication import equivalent_knowledge
from opentest.application.resources import ResourceInventoryService
from opentest.domain.errors import IdempotencyConflictError, ScopeViolationError
from opentest.domain.models import EntryPoint, KnowledgeContextProfile, OperationInputKnowledgeContract, ScanManifest, SourceBaseline, utc_now
from opentest.domain.shared_workspace import BaselineContextUpdate, BaselineCreationRun, CreateCodeBaseline, StoredArtifact


class BaselineDatabase:
    """用独立SQLite执行基准SQL业务约束；只转换占位符和行锁方言。"""

    def __init__(self):
        """建立实际唯一键和基准、材料表，所有数据限于测试进程。"""

        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE ot_system(system_id TEXT PRIMARY KEY);
        CREATE TABLE ot_scan(scan_id TEXT PRIMARY KEY,baseline_id TEXT,created_by_user_id TEXT);
        CREATE TABLE ot_code_baseline(baseline_id TEXT PRIMARY KEY,system_id TEXT,source_kind TEXT,source_commit TEXT,
          selected_revision TEXT,source_artifact_id TEXT,inherited_from_baseline_id TEXT,context_json TEXT,interview_json TEXT,
          questions_json TEXT,context_revision INTEGER DEFAULT 0,created_by_user_id TEXT,updated_by_user_id TEXT,
          created_at TEXT,updated_at TEXT,UNIQUE(system_id,source_commit));
        CREATE TABLE ot_artifact_object(artifact_id TEXT PRIMARY KEY,artifact_kind TEXT,bucket TEXT,object_key TEXT UNIQUE,
          byte_size INTEGER,content_type TEXT,created_by_user_id TEXT,created_at TEXT);
        INSERT INTO ot_system(system_id) VALUES('refund-core');
        """)

    def fetch_one(self, sql, parameters=()):
        """执行真实查询并返回字典，不用测试代码模拟SQL过滤。"""

        row = self.connection.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""), parameters).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql, parameters=()):
        """返回实际查询结果集合，验证本人及共享范围直接由SQL决定。"""

        return [dict(row) for row in self.connection.execute(sql.replace("%s", "?"), parameters)]

    def execute(self, sql, parameters=()):
        """执行同一业务SQL并返回行数；约束失败照常抛出。"""

        return self.connection.execute(sql.replace("%s", "?"), parameters).rowcount

    @contextmanager
    def transaction(self):
        """以实际提交和回滚验证短事务，不改变查询决策。"""

        with self.connection:
            yield self


def test_same_commit_reuses_first_source_and_other_employee_sees_only_shared_material():
    """branch/tag指向同commit只创建一份基准；源码上传前他人不能枚举新条目。"""

    store = SharedWorkspaceStore(BaselineDatabase())
    baseline = store.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit="a" * 40,
        selected_revision="release/first", user_id="employee-a"))
    same = store.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit="a" * 40,
        selected_revision="v1-tag", user_id="employee-b"))
    assert same.baseline_id == baseline.baseline_id
    assert same.selected_revision == "release/first"
    assert store.list_baselines("refund-core", "employee-b") == []
    artifact = StoredArtifact(artifact_id="source-a", artifact_kind="SOURCE", bucket="opentest", object_key="source/a.tar.gz",
        byte_size=12, content_type="application/gzip", created_by_user_id="employee-a")
    store.register_artifact(artifact)
    store.attach_source(baseline.baseline_id, artifact.artifact_id, "employee-a")
    assert store.list_baselines("refund-core", "employee-b")[0].baseline_id == baseline.baseline_id


def test_resource_probe_materializes_shared_source_before_resolving_uat(tmp_path, monkeypatch):
    """无仓库、无源码缓存的第二台电脑先下载固定包，再使用其内容解析UAT资源配置。"""

    database = BaselineDatabase()
    workspace = SharedWorkspaceStore(database)
    baseline = workspace.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit="a" * 40,
        selected_revision="release", user_id="employee-a"))
    original = tmp_path / "creator-repository"
    original.mkdir()
    (original / "uat.properties").write_text("environment=uat\n", encoding="utf-8")
    archive = tmp_path / "shared-source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(original / "uat.properties", arcname="uat.properties")
    artifact = StoredArtifact(artifact_id="shared-source", artifact_kind="SOURCE", bucket="test", object_key="source.tar.gz",
        byte_size=archive.stat().st_size, content_type="application/gzip", created_by_user_id="employee-a")
    workspace.register_artifact(artifact)
    workspace.attach_source(baseline.baseline_id, artifact.artifact_id, "employee-a")
    # 原创建人的目录已不可用；只把实际归档字节保留为对象存储测试替身。
    shutil.rmtree(original)
    root = tmp_path / "second-machine" / "knowledge"
    artifacts = SourceScanArtifactStore(root, database)
    manifest = ScanManifest(scan_id="shared-scan", system_id="refund-core", resource_inventory_captured=True,
        baseline=SourceBaseline(source_path=str(original), snapshot_path=str(original / "snapshot"), commit="a" * 40))
    observed = []

    def download_source(reference, destination):
        """下载原归档实际字节，不从本机仓库或临时目录补造源码。"""

        assert reference.artifact_id == artifact.artifact_id
        shutil.copyfile(archive, destination)
        return destination

    def read_manifest(system_id, scan_id):
        """返回共享扫描冻结的原始路径，用真实物化逻辑检验跨机器读取。"""

        assert (system_id, scan_id) == ("refund-core", "shared-scan")
        return manifest

    def get_system(system_id):
        """第二台电脑没有本机源码绑定，不能借此回退到作者目录。"""

        assert system_id == "refund-core"
        return SimpleNamespace(source_path="")

    def system_root(system_id):
        """返回本机尚未建立的知识目录，使资源目录读取遵循正常缺省路径。"""

        return root / system_id

    def resolve_uat(self, system_id, environment, source_root):
        """环境解析必须看到已完整物化的固定内容，而不是manifest中的失效路径。"""

        assert (system_id, environment) == ("refund-core", "uat")
        assert Path(source_root) == artifacts.source_snapshot_path(system_id, "a" * 40)
        assert (Path(source_root) / "uat.properties").read_text() == "environment=uat\n"
        observed.append(environment)
        return SimpleNamespace()

    artifacts.object_storage = SimpleNamespace(download_file=download_source)
    monkeypatch.setattr(artifacts, "read", read_manifest)
    monkeypatch.setattr("opentest.application.resources.LocalEnvironmentLoader.resolve_execution_profile", resolve_uat)
    service = ResourceInventoryService(SimpleNamespace(root=root, get_system=get_system, system_root=system_root), artifacts=artifacts)
    assert not artifacts.source_snapshot_root.exists()
    assert service.probe("refund-core", "uat", scan_id="shared-scan") == []
    assert observed == ["uat"]


def test_inherited_background_is_independent_and_update_checks_revision():
    """新基准复制业务背景一次，之后修改原背景不跟随；旧revision不能覆盖另一员工编辑。"""

    store = SharedWorkspaceStore(BaselineDatabase())
    first = store.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit="a" * 40,
        selected_revision="first", user_id="employee-a"))
    store.update_context(BaselineContextUpdate(baseline_id=first.baseline_id, user_id="employee-a", expected_revision=0,
        context=KnowledgeContextProfile(system_id="refund-core", system_purpose="退款服务", last_scan_id="scan-old")))
    second = store.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit="b" * 40,
        selected_revision="second", user_id="employee-a", inherited_from_baseline_id=first.baseline_id))
    assert second.context.system_purpose == "退款服务"
    assert second.context.last_scan_id == ""
    store.update_context(BaselineContextUpdate(baseline_id=first.baseline_id, user_id="employee-a", expected_revision=1,
        context=KnowledgeContextProfile(system_id="refund-core", system_purpose="更新背景")))
    assert store.get_baseline(second.baseline_id).context.system_purpose == "退款服务"
    with pytest.raises(IdempotencyConflictError):
        store.update_context(BaselineContextUpdate(baseline_id=first.baseline_id, user_id="employee-b", expected_revision=1,
            context=KnowledgeContextProfile(system_id="refund-core", system_purpose="过期编辑")))


def test_frozen_dependencies_are_used_without_local_maven_and_restored_after_failure(tmp_path, monkeypatch):
    """跨机器扫描必须消费原依赖；异常退出后下一扫描不能误用上个基准的包。"""

    binary = tmp_path / "original.jar"
    binary.write_bytes(b"old SNAPSHOT")
    artifacts = [MavenArtifact("a:library:SNAPSHOT", binary, tmp_path / "sources.jar")]
    catalog = JavaDependencyCatalog(tmp_path / "empty-m2")

    def local_resolution(root):
        """标记扫描离开冻结范围后才允许重新解析本机依赖。"""

        return [], ["local resolution"]

    monkeypatch.setattr(catalog, "_declared_artifacts", local_resolution)
    with pytest.raises(RuntimeError):
        with bind_frozen_dependencies(tmp_path, artifacts, ["original missing source"]):
            actual, gaps = catalog.resolved_artifacts(tmp_path)
            assert actual[0].binary.read_bytes() == b"old SNAPSHOT"
            assert gaps == ["original missing source"]
            raise RuntimeError("scan interrupted")
    assert catalog.resolved_artifacts(tmp_path) == ([], ["local resolution"])


def test_continuation_reuses_successful_stages_but_never_claims_other_employee():
    """续跑新建尝试并复用成功材料和接口，保留原终态；其他员工不能查看或续跑原过程。"""

    original = BaselineCreationRun(run_id="baseline-run-old", request_id="request-old", system_id="refund-core", baseline_id="baseline-a",
        owner_user_id="employee-a", environment_id="uat", source_commit="a" * 40, status="PARTIAL", task_id="task-old",
        dependency_artifact_id="dependency-a", scan_id="scan-a", knowledge_completed=["facade:a"], knowledge_failures={"facade:b": "missing"},
        resource_result={"failure_count": 1})
    service = object.__new__(SharedBaselineService)
    service.storage = object()
    service.metadata = SimpleNamespace(workspace_id="other-machine", get_workflow=lambda kind, identity: original.model_dump(mode="json") if kind == "baseline_creation" else None)
    service.application = SimpleNamespace(tasks=SimpleNamespace(get=lambda task_id: SimpleNamespace(status="partial")))
    service._submit = lambda run, identity: run
    continued = service.continue_creation(original.run_id, "request-new", "employee-a")
    assert continued.run_id != original.run_id
    assert continued.predecessor_run_id == original.run_id
    assert continued.scan_id == "scan-a" and continued.dependency_artifact_id == "dependency-a"
    assert continued.knowledge_completed == ["facade:a"] and not continued.knowledge_failures
    assert continued.resource_result is None and original.resource_result == {"failure_count": 1}
    assert original.status == "PARTIAL" and original.knowledge_failures
    with pytest.raises(ScopeViolationError):
        service.continue_creation(original.run_id, "request-other", "employee-b")


def test_historical_source_backfill_uses_original_commit_and_reuses_registered_object(tmp_path):
    """历史补传从精确Git提交恢复实际字节，工作树变化不得混入，重放只复用已登记材料。"""

    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    (repository / "Order.java").write_text("original committed source", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "Order.java"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "first"], check=True, capture_output=True)
    commit = subprocess.run(["git", "-C", str(repository), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    metadata = BaselineDatabase()
    store = SharedWorkspaceStore(metadata)
    baseline = store.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit=commit, selected_revision="original", user_id="historical-placeholder"))
    metadata.execute("UPDATE ot_code_baseline SET created_by_user_id=NULL WHERE baseline_id=%s", (baseline.baseline_id,))
    (repository / "Order.java").write_text("uncommitted current source", encoding="utf-8")
    uploaded = []

    def upload(path, kind, owner):
        """检查传给S3的实际归档，不依赖元数据路径就认定历史材料完整。"""

        with tarfile.open(path, "r:gz") as archive:
            assert archive.extractfile("Order.java").read() == b"original committed source"
        assert kind == "SOURCE" and owner is None
        uploaded.append(path.stat().st_size)
        return StoredArtifact(artifact_id="historical-source", artifact_kind="SOURCE", bucket="opentest", object_key="history/source.tar.gz",
            byte_size=path.stat().st_size, content_type="application/gzip")

    migration = SharedHistoryMigration(metadata)
    storage = SimpleNamespace(upload_file=upload)
    assert migration.backfill_source(baseline.baseline_id, repository, storage) == "historical-source"
    assert migration.backfill_source(baseline.baseline_id, repository, storage) == "historical-source"
    assert len(uploaded) == 1 and store.get_baseline(baseline.baseline_id).created_by_user_id is None


def test_native_interface_bundle_contains_real_business_branch_and_rescan_stays_equivalent(tmp_path):
    """Java真实方法的分支进入固定知识，同源码换scan身份时不误判为测试语义变化。"""

    facade = tmp_path / "OrderFacade.java"
    facade.write_text("package example; interface OrderFacade { String query(String orderId); }", encoding="utf-8")
    implementation = tmp_path / "OrderFacadeImpl.java"
    implementation.write_text('package example; class OrderFacadeImpl implements OrderFacade { public String query(String orderId) { if (orderId == null) { throw new IllegalArgumentException("missing order"); } return "order"; } }', encoding="utf-8")
    target = "facade:example.OrderFacade#query"
    manifest = ScanManifest(scan_id="scan-first", system_id="orders", baseline=SourceBaseline(source_path=str(tmp_path), commit="a" * 40),
        entries=[EntryPoint(entry_id=target, system_id="orders", kind="facade", display_name="订单查询", source_id="example.OrderFacade#query", source_path=str(facade))])
    contract = OperationInputKnowledgeContract(contract_version="operation-contract/v2", contract_revision=1, target_id=target,
        source_scan_id=manifest.scan_id, source_commit="a" * 40, status="READY", request_schema={"type": "object", "properties": {}})
    service = object.__new__(SharedInterfaceKnowledgeService)
    first = service._build_bundle(manifest, contract, {}, None)
    assert any("orderId == null" in body for body in first.bodies.values())
    assert any(reference.path == "OrderFacadeImpl.java" for reference in first.source_evidence)
    rescanned = manifest.model_copy(update={"scan_id": "scan-second"})
    new_contract = contract.model_copy(update={"source_scan_id": rescanned.scan_id})
    second = service._build_bundle(rescanned, new_contract, {}, None)
    assert equivalent_knowledge({"contract": contract.model_dump(mode="json"), "knowledge": first.model_dump(mode="json")},
        {"contract": new_contract.model_dump(mode="json"), "knowledge": second.model_dump(mode="json")})


def test_declared_interface_bundle_keeps_scope_limit_and_ignores_only_scan_provenance():
    """外部接口明确声明只有契约证据；同样字段重扫兼容，真实契约用途变化仍触发影响。"""

    manifest = ScanManifest(scan_id="scan-first", system_id="orders", baseline=SourceBaseline(source_path="", commit="a" * 40))
    contract = OperationInputKnowledgeContract(contract_version="operation-contract/v2", contract_revision=1, target_id="query-order",
        source_scan_id=manifest.scan_id, status="READY", request_schema={"type": "object", "properties": {}})
    definition = {"baseline_interface_id": 1, "operation": {"source_symbol_refs": [{"path": "Dependency.java"}]}}
    service = object.__new__(SharedInterfaceKnowledgeService)
    first = service._build_bundle(manifest, contract, definition, None)
    second_contract = contract.model_copy(update={"source_scan_id": "scan-second"})
    second = service._build_bundle(manifest.model_copy(update={"scan_id": "scan-second"}), second_contract, definition, None)
    assert "未取得服务端内部实现" in first.nodes[0].metadata["limitation"]
    assert equivalent_knowledge({"contract": contract.model_dump(mode="json"), "knowledge": first.model_dump(mode="json")},
        {"contract": second_contract.model_dump(mode="json"), "knowledge": second.model_dump(mode="json")})
    changed = second_contract.model_copy(update={"operation_summary": "不同业务用途"})
    assert not equivalent_knowledge({"contract": contract.model_dump(mode="json"), "knowledge": first.model_dump(mode="json")},
        {"contract": changed.model_dump(mode="json"), "knowledge": second.model_dump(mode="json")})
