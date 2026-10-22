"""验证同commit去重、背景独立、草稿阶段续跑及固定依赖，不连接真实服务。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tarfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.java_dependencies import JavaDependencyCatalog, MavenArtifact, bind_frozen_dependencies
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.adapters.shared_workspace_store import SharedWorkspaceStore
from opentest.adapters.shared_history_migration import SharedHistoryMigration
from opentest.application.shared_baselines import SharedBaselineService
from opentest.application.shared_interface_knowledge import SharedInterfaceKnowledgeService
from opentest.application.publication import equivalent_knowledge
from opentest.application.resources import ResourceInventoryService
from opentest.domain.errors import IdempotencyConflictError, ScopeViolationError, TaskCancelledError, TaskPartialFailureError
from opentest.domain.models import EntryPoint, KnowledgeContextProfile, KnowledgeInterview, KnowledgeQuestion, OperationInputKnowledgeContract, ScanManifest, SourceBaseline, TaskRecord, utc_now
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


def test_large_baseline_history_lists_complete_content_without_database_filesort(monkeypatch):
    """大历史正文避开MySQL宽行排序，完整保留内容及创建时间降序、同时间ID升序。"""

    database = BaselineDatabase()
    store = SharedWorkspaceStore(database)
    history_body = "已确认的历史业务说明" * 40_000
    context = KnowledgeContextProfile(system_id="refund-core", interview_answers={"history": history_body})
    interview = KnowledgeInterview(system_id="refund-core", system_purpose=history_body)
    question = KnowledgeQuestion(question_id="history-question", system_id="refund-core", title="历史问题",
        detail="已核对业务边界", status="answered", answer=history_body)
    # 插入顺序和ID顺序都不代表创建时间；同一时间下必须保持原来的ID升序。
    for digit, baseline_id, created_at in (
        ("a", "baseline-z-new", "2026-10-22 00:00:00.000001"),
        ("b", "baseline-b-same", "2026-10-21 00:00:00.000000"),
        ("c", "baseline-a-same", "2026-10-21 00:00:00.000000"),
        ("d", "baseline-first-old", "2026-10-20 00:00:00.000000"),
    ):
        baseline = store.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit=digit * 40,
            selected_revision="main", user_id="employee-a"))
        database.execute("UPDATE ot_code_baseline SET baseline_id=%s,created_at=%s,context_json=%s,interview_json=%s,questions_json=%s WHERE baseline_id=%s",
            (baseline_id, created_at, context.model_dump_json(), interview.model_dump_json(),
             json.dumps([question.model_dump(mode="json")]), baseline.baseline_id))
    fetch_all = database.fetch_all

    def reject_large_json_filesort(sql, parameters=()):
        """重现大JSON行参与filesort时的1038故障，其余查询仍由真实SQLite过滤。"""

        # 限定已复现的宽行排序故障，允许轻量列排序等其他有效查询方案。
        if "SELECT *" in sql and "ORDER BY" in sql:
            from pymysql.err import OperationalError

            raise OperationalError(1038, "Out of sort memory")
        return fetch_all(sql, parameters)

    monkeypatch.setattr(database, "fetch_all", reject_large_json_filesort)
    listed = store.list_baselines("refund-core", "employee-a")
    assert [item.baseline_id for item in listed] == [
        "baseline-z-new", "baseline-a-same", "baseline-b-same", "baseline-first-old",
    ]
    assert all(item.context == context and item.interview == interview and item.questions == [question] for item in listed)
    # 排序调整不能让其他员工读取尚未上传源码的新基准。
    assert store.list_baselines("refund-core", "employee-b") == []


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


def test_saving_background_preserves_existing_interview_and_questions():
    """背景表单只传context时保留原访谈和已答问题；SQL不得以模型默认值清空其他列。"""

    database = BaselineDatabase()
    store = SharedWorkspaceStore(database)
    baseline = store.create_baseline(CreateCodeBaseline(system_id="refund-core", source_commit="a" * 40,
        selected_revision="main", user_id="employee-a"))
    interview = KnowledgeInterview(system_id="refund-core", system_purpose="原访谈", business_terms={"退票": "旅客取消行程"})
    question = KnowledgeQuestion(question_id="question-one", system_id="refund-core", source="interview",
        title="退款边界", detail="是否允许部分退款", status="answered", answer="允许")
    database.execute("UPDATE ot_code_baseline SET interview_json=%s,questions_json=%s WHERE baseline_id=%s",
        (interview.model_dump_json(), json.dumps([question.model_dump(mode="json")]), baseline.baseline_id))
    saved = store.update_context(BaselineContextUpdate(baseline_id=baseline.baseline_id, user_id="employee-a", expected_revision=0,
        context=KnowledgeContextProfile(system_id="refund-core", system_purpose="编辑后的背景")))
    assert saved.interview == interview and saved.questions == [question]
    assert store.get_baseline(baseline.baseline_id).interview == interview
    assert store.get_baseline(baseline.baseline_id).questions == [question]


class CreationWorkflows:
    """创建流程的内存持久边界，真实执行提交与阶段逻辑并验证revision，禁止外部服务访问。"""

    workspace_id = "test-machine"

    def __init__(self):
        """初始化可跨Service实例复用的流程记录及串行系统事务锁。"""

        self.records = {}
        self.lock = RLock()

    @contextmanager
    def system_transaction(self, system_id):
        """串行当前测试系统的提交和阶段写入，异常由测试直接检查，不模拟业务结论。"""

        with self.lock:
            yield

    def put_workflow(self, kind, identity, payload, **options):
        """保存独立载荷副本并检查乐观修订，防止服务重用内存对象掩盖过期写入。"""

        previous = self.records.get((kind, identity))
        if options.get("create_only"):
            assert previous is None
        if "expected_revision" in options:
            assert previous["revision"] == options["expected_revision"]
        self.records[kind, identity] = deepcopy(payload)

    def get_workflow(self, kind, identity):
        """读取持久副本，复用旧Service对象不能改变已保存的状态。"""

        return deepcopy(self.records.get((kind, identity)))

    def list_workflows(self, kind, system_id, workspace):
        """按实际查询范围读取任务，防止恢复路径误取另一系统或工作台任务。"""

        return [deepcopy(payload) for (record_kind, _), payload in self.records.items() if record_kind == kind
            and payload.get("system_id") == system_id and payload.get("owner_workspace_id") == workspace]


def creation_service():
    """创建隔离服务和待提交流程；替换网络材料组件，保留原提交、续跑及checkpoint逻辑。"""

    metadata = CreationWorkflows()
    service = object.__new__(SharedBaselineService)
    service.metadata = metadata
    service.store = SimpleNamespace(get_baseline=Mock(return_value="baseline"), get_artifact=Mock(return_value="dependency"))
    service.storage = SimpleNamespace(materialize_archive=Mock(return_value=Path("/unused-cache")))
    service.artifacts = SimpleNamespace(materialize_shared_source=Mock(return_value=Path("/unused-source")))
    tasks = SimpleNamespace(_owner_pid=912345, _owner_started_at="original-process", _process_start_marker=Mock(return_value="original-process"))
    service.application = SimpleNamespace(store=metadata, tasks=tasks, knowledge_root=Path("/unused-knowledge"))
    run = BaselineCreationRun(run_id="run-one", request_id="request-one", system_id="refund-core", baseline_id="baseline-one",
        owner_user_id="employee-a", owner_workspace_id=metadata.workspace_id, environment_id="uat", source_commit="a" * 40)
    return service, run


@pytest.mark.parametrize("worker_ran", [False, True])
def test_submitted_creation_persists_task_identity_without_overwriting_worker_progress(worker_ran):
    """排队任务立即关联task_id；后台先保存阶段时提交方不得覆盖其最新revision或完成点。"""

    service, run = creation_service()
    task = TaskRecord(task_id="task-" + "a" * 16, operation="baseline-create", system_id=run.system_id, trace_id="trace")

    def submit(operation, system_id, job, **options):
        """模拟已保存但暂未执行任务，或worker已在submit返回前推进阶段这两种真实时序。"""

        assert options["initial_progress"].current_item == run.run_id
        if worker_ran:
            current = service.get_run(run.run_id, run.owner_user_id)
            current.task_id = task.task_id
            current.scan_id = "completed-scan"
            current.status = "RUNNING"
            service._checkpoint(current)
        return task

    service.application.tasks.submit = submit
    service._submit(run, {"request_id": run.request_id})
    saved = service.get_run(run.run_id, run.owner_user_id)
    assert saved.task_id == task.task_id
    assert saved.scan_id == ("completed-scan" if worker_ran else "")
    assert saved.revision == 1


@pytest.mark.parametrize("submitted", [False, True])
def test_creation_recovers_interrupted_submission_before_or_after_task_was_saved(submitted, monkeypatch):
    """重启后能区分已提交任务与提交前崩溃，不因PENDING缺task_id永远锁死或重复运行。"""

    service, run = creation_service()
    service.metadata.put_workflow("baseline_creation", run.run_id, run.model_dump(mode="json"))
    service.metadata.put_workflow("baseline_create_request", run.request_id, {"submission_owner": {"pid": 912345, "started_at": "old"}})
    if submitted:
        service.metadata.put_workflow("task", "task-old", {"task_id": "task-old", "operation": "baseline-create", "system_id": run.system_id,
            "owner_user_id": run.owner_user_id, "owner_workspace_id": run.owner_workspace_id, "progress": {"current_item": run.run_id}})
    service.application.tasks.get = Mock(return_value=SimpleNamespace(status="interrupted"))
    service._submit = Mock(side_effect=lambda resumed, identity: resumed)
    monkeypatch.setattr("opentest.application.shared_baselines.os.kill", Mock(side_effect=ProcessLookupError))
    resumed = service.continue_creation(run.run_id, "request-resumed", run.owner_user_id)
    assert resumed.predecessor_run_id == run.run_id and resumed.task_id == ""
    saved = service.get_run(run.run_id, run.owner_user_id)
    assert saved.task_id == ("task-old" if submitted else "")
    assert saved.status == ("PENDING" if submitted else "FAILED")


@pytest.mark.parametrize("other_workspace", [False, True])
def test_creation_never_recovers_live_or_other_machine_submission(other_workspace, monkeypatch):
    """提交仍可能发生或来自另一机器时拒绝续跑，不能仅凭无task_id断言旧任务已消失。"""

    service, run = creation_service()
    if other_workspace:
        run.owner_workspace_id = "other-machine"
    service.metadata.put_workflow("baseline_creation", run.run_id, run.model_dump(mode="json"))
    service.metadata.put_workflow("baseline_create_request", run.request_id, {"submission_owner": {"pid": 912345, "started_at": "original-process"}})
    monkeypatch.setattr("opentest.application.shared_baselines.os.kill", Mock(return_value=None))
    with pytest.raises(IdempotencyConflictError):
        service.continue_creation(run.run_id, "request-resumed", run.owner_user_id)


def test_creation_refresh_exposes_resumable_state_after_submitter_exit(monkeypatch):
    """刷新基准列表可恢复提交前崩溃的续跑按钮，不要求用户先知道隐藏的continue API。"""

    service, run = creation_service()
    service.metadata.put_workflow("baseline_creation", run.run_id, run.model_dump(mode="json"))
    service.metadata.put_workflow("baseline_create_request", run.request_id,
        {"submission_owner": {"pid": 912345, "started_at": "old"}})
    monkeypatch.setattr("opentest.application.shared_baselines.os.kill", Mock(side_effect=ProcessLookupError))
    progress = service._creation_progress(run, SimpleNamespace(source_artifact_id=None))
    assert progress["status"] == "FAILED" and progress["run_id"] == run.run_id


def test_resource_exception_keeps_knowledge_stage_and_partial_outcome(monkeypatch):
    """资源连接异常保存失败结论仍继续知识生成；最终为PARTIAL而不是反复卡在资源阶段。"""

    service, run = creation_service()
    run.scan_id = "scan-one"
    run.dependency_artifact_id = "dependency-one"
    service.metadata.put_workflow("baseline_creation", run.run_id, run.model_dump(mode="json"))
    service._prepare_source = Mock()
    service._prepare_dependencies = Mock()
    service._scan = Mock()
    service._generate_knowledge = Mock()
    service.application.probe_shared_baseline_resources = Mock(side_effect=ConnectionError("private endpoint secret"))
    monkeypatch.setattr("opentest.application.shared_baselines.read_frozen_dependencies", Mock(return_value=([], [])))
    with pytest.raises(TaskPartialFailureError):
        service._execute(run.run_id, run.owner_user_id)
    saved = service.get_run(run.run_id, run.owner_user_id)
    assert saved.status == "PARTIAL" and saved.resource_result["failure_count"] == 1
    assert saved.resource_result["error_type"] == "ConnectionError"
    assert "private endpoint" not in json.dumps(saved.resource_result)
    service._generate_knowledge.assert_called_once()


def test_resource_probe_cancellation_is_not_treated_as_environment_failure():
    """用户取消必须停止工作流，不能被资源异常容错吞掉后继续产生接口知识。"""

    service, run = creation_service()
    service.application.probe_shared_baseline_resources = Mock(side_effect=TaskCancelledError("cancelled"))
    with pytest.raises(TaskCancelledError):
        service._probe_resources(run)
    assert run.resource_result is None


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
