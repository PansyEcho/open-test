"""验证共享事务的线程边界、异常回滚和DSL序列化约束，不连接真实数据库。"""

from __future__ import annotations

import threading
import sqlite3
import json
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from opentest.adapters.knowledge_interview import KnowledgeInterviewStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.case_template_v4_store import CaseTemplateGenerationStoreV4, CaseTemplateHandoffStoreV4
from opentest.adapters.data_capability_store import DataCapabilityStore
from opentest.adapters.mysql_knowledge import MySqlKnowledgeStore
from opentest.adapters.mysql_migration import StandaloneAssetMigrator
from opentest.adapters.mysql_metadata import MySqlMetadataStore, decode_json, encode_json, load_metadata_store, pack_json, portable_scope_payload, unpack_json
from opentest.adapters.system_archive import SystemArchiveStore
from opentest.adapters.published_capability_store import PublishedCapabilityStore
from opentest.domain.case_template_v4 import CaseTemplateGenerationV4, CaseTemplateHandoffV4, CaseTemplateSourceScope, CaseTemplateSubmission, DslValueSource
from opentest.domain.data_capabilities import DataCapabilityHandoff, DataCapabilityVersion, DataExecution
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    CandidateRef, KnowledgeInterview, KnowledgeNode, KnowledgeNodeKind, KnowledgeRevisionPlan, OperationInputKnowledgeContract, OperationMutability,
    ProviderOperationRef, PublishedOperationCapability, SourceBaseline, SystemDefinition,
)


class RecordingConnection:
    """记录事务结果，禁止测试依赖网络、服务器或隐式驱动重试。"""

    def __init__(self, **configuration):
        """接受驱动关键字并初始化本连接的提交、回滚和关闭计数。"""

        self.configuration = configuration
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def commit(self):
        """记录由最外层事务执行的一次提交。"""

        self.commits += 1

    def rollback(self):
        """记录失败事务回滚，供异常隔离断言使用。"""

        self.rollbacks += 1

    def close(self):
        """记录连接释放，验证异常不会泄漏驱动资源。"""

        self.closed += 1


def metadata_store() -> MySqlMetadataStore:
    """创建使用记录驱动的存储，所有连接参数都是测试字面值。"""

    return MySqlMetadataStore({"host": "unused", "user": "test", "database": "test"}, "workspace-test", RecordingConnection)


def test_nested_transaction_commits_once_and_releases_connection():
    """业务Store嵌套事务必须复用同一连接并只提交一次。"""

    store = metadata_store()
    with store.transaction():
        connection = store._local.connection
        with store.transaction():
            assert store._local.connection is connection
        # 内层退出不发布半份业务数据。
        assert connection.commits == 0
    assert (connection.commits, connection.rollbacks, connection.closed) == (1, 0, 1)
    assert store._local.connection is None


def test_caught_inner_error_still_rolls_back_outer_transaction():
    """调用者捕获内层异常也不能把部分规则或Case当作完整发布提交。"""

    store = metadata_store()
    with pytest.raises(KnowledgeValidationError, match="marked for rollback"):
        with store.transaction():
            connection = store._local.connection
            try:
                with store.transaction():
                    raise ValueError("invalid contract")
            except ValueError:
                pass
    assert (connection.commits, connection.rollbacks, connection.closed) == (0, 1, 1)


def test_closed_connection_rollback_does_not_hide_original_interrupt(monkeypatch, caplog):
    """连接在写入中断时已关闭，回滚失败不得覆盖原KeyboardInterrupt且仍释放线程上下文。"""

    store = metadata_store()
    original = KeyboardInterrupt("migration stopped")

    def fail_rollback():
        """模拟驱动已关闭连接的清理异常，禁止恢复为一次新的业务写入。"""

        raise RuntimeError("sensitive driver detail")

    with pytest.raises(KeyboardInterrupt) as interrupted:
        with store.transaction():
            connection = store._local.connection
            monkeypatch.setattr(connection, "rollback", fail_rollback)
            raise original
    assert interrupted.value is original
    assert connection.closed == 1 and store._local.connection is None
    assert "RuntimeError" in caplog.text and "sensitive driver detail" not in caplog.text


def test_concurrent_workflows_do_not_share_driver_connections():
    """并行工作流各持有自己的事务，不能交叉提交其他线程的写入。"""

    store = metadata_store()
    barrier = threading.Barrier(2)

    def hold_transaction():
        """同步持有本线程事务，使错误的共享连接实现可以被确定性检出。"""

        with store.transaction():
            connection = store._local.connection
            barrier.wait(timeout=5)
            assert store._local.connection is connection
        return connection

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_transaction)
        second = executor.submit(hold_transaction)
        connections = [first.result(), second.result()]
    assert connections[0] is not connections[1]
    assert all(item.commits == 1 and item.closed == 1 for item in connections)


def test_compressed_payload_preserves_explicit_null_and_dynamic_sources():
    """执行详情压缩不得把动态来源误补为literal=null，或删除显式空值。"""

    dynamic = DslValueSource(kind="parameter", name="order_id")
    literal = DslValueSource(kind="literal", value=None)
    payload = {"dynamic": dynamic.model_dump(mode="json"), "literal": literal.model_dump(mode="json")}
    restored = unpack_json(pack_json(payload))
    assert "value" not in restored["dynamic"]
    assert "value" in restored["literal"] and restored["literal"]["value"] is None
    assert DslValueSource.model_validate(restored["dynamic"]) == dynamic


def test_invalid_configuration_does_not_fall_back_to_local_truth(tmp_path):
    """只有配置缺失才使用文件模式，损坏配置必须阻止分叉写入。"""

    knowledge_root = tmp_path / "knowledge"
    assert load_metadata_store(knowledge_root) is None
    configuration_root = tmp_path / ".opentest"
    configuration_root.mkdir()
    (configuration_root / "metadata-mysql.yaml").write_text("- invalid\n", encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="mapping"):
        load_metadata_store(knowledge_root)


def mysql_compress(payload):
    """在SQLite驱动中模拟MySQL COMPRESS；NULL继续保留，中文按UTF-8字节计长。"""

    if payload is None:
        return None
    raw = payload.encode("utf-8")
    return len(raw).to_bytes(4, "little") + zlib.compress(raw)


class SqliteConnection:
    """仅适配驱动语法，业务SQL和MySQL事务边界继续使用生产实现。"""

    def __init__(self, path):
        """打开同一个测试数据库，使两套工作台连接可观察相同已提交状态。"""

        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        # SQLite仅模拟MySQL传输压缩格式，仍由生产解码器验证完整JSON。
        self.connection.create_function("COMPRESS", 1, mysql_compress)

    def autocommit(self, enabled):
        """将测试连接映射为SQLite自动提交，模拟池中无空闲事务的读会话。"""

        self.connection.isolation_level = None if enabled else ""

    def cursor(self):
        """返回支持DictCursor形状和with语法的测试游标。"""

        return SqliteCursor(self.connection.cursor())

    def commit(self):
        """提交生产事务边界内的真实SQL变更。"""

        self.connection.commit()

    def rollback(self):
        """回滚真实变更，用于验证失败不遗留半份发布。"""

        self.connection.rollback()

    def close(self):
        """释放本次短事务独占的测试连接。"""

        self.connection.close()


class SqliteCursor:
    """把MySQL占位符和时间函数转换为SQLite，其余SQL原样执行。"""

    def __init__(self, cursor):
        """保存底层游标，不生成或猜测业务查询结果。"""

        self.delegate = cursor

    def __enter__(self):
        """允许生产查询代码使用同一游标作用域。"""

        return self

    def __exit__(self, *exception):
        """离开查询作用域时关闭底层游标，不吞异常。"""

        self.delegate.close()

    def execute(self, sql, parameters=()):
        """转换驱动占位符和只读会话设置，其余业务SQL在SQLite实际执行。"""

        if sql == "SET SESSION TRANSACTION READ ONLY":
            self.delegate.execute("PRAGMA query_only=ON")
            return

        translated = sql.replace("%s", "?").replace(" FOR UPDATE", "").replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP")
        self.delegate.execute(translated, parameters)

    @property
    def rowcount(self):
        """返回实际数据库受影响行数，供生产写入检查使用。"""

        return self.delegate.rowcount

    def fetchone(self):
        """取一行并转换为生产DictCursor形状。"""

        row = self.delegate.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        """把完整查询结果转换为生产DictCursor形状。"""

        return [dict(row) for row in self.delegate.fetchall()]


def shared_workspace_pair(tmp_path):
    """创建两个本地知识根，共享最小真实SQL表；不会读取本机MySQL配置。"""

    path = tmp_path / "shared.sqlite"
    with sqlite3.connect(path) as connection:
        # 测试只创建此场景消费的列，SQL约束和载荷读写由生产实现负责。
        connection.executescript("""
            CREATE TABLE ot_system(system_id TEXT PRIMARY KEY,name TEXT,system_json TEXT,interview_json TEXT,
                context_json TEXT,questions_json TEXT,created_at TEXT,is_archived INTEGER DEFAULT 0,workspace_revision INTEGER DEFAULT 0);
            CREATE TABLE ot_workflow_record(record_kind TEXT,record_id TEXT,system_id TEXT,
                parent_record_id TEXT,target_id TEXT,status TEXT,revision INTEGER,
                owner_workspace_id TEXT,payload_json TEXT,created_at TEXT,updated_at TEXT,
                PRIMARY KEY(record_kind,record_id));
            CREATE TABLE ot_execution(execution_id TEXT PRIMARY KEY,execution_kind TEXT,
                system_id TEXT,request_namespace TEXT,request_id TEXT,owner_workspace_id TEXT,
                generation_id TEXT,environment_id TEXT,status TEXT,summary_json TEXT,
                payload_gzip BLOB,created_at TEXT,updated_at TEXT,
                UNIQUE(execution_kind,request_namespace,request_id));
            CREATE TABLE ot_case_generation(generation_id TEXT PRIMARY KEY,system_id TEXT,
                operation_id TEXT,source_scan_id TEXT,status TEXT,generation_json TEXT,created_at TEXT);
            CREATE TABLE ot_data_capability_version(system_id TEXT,capability_id TEXT,
                version INTEGER,definition_json TEXT,created_at TEXT,
                PRIMARY KEY(system_id,capability_id,version));
            CREATE TABLE ot_published_capability(system_id TEXT,capability_id TEXT,
                publication_request_id TEXT,contract_version TEXT,capability_json TEXT,published_at TEXT,
                UNIQUE(system_id,publication_request_id));
            CREATE TABLE ot_knowledge_node(system_id TEXT,node_id TEXT,kind TEXT,title TEXT,
                summary TEXT,node_json TEXT,body TEXT,updated_at TEXT,PRIMARY KEY(system_id,node_id));
            CREATE TABLE ot_knowledge_edge(system_id TEXT,edge_id TEXT,source_node_id TEXT,
                target_node_id TEXT,kind TEXT,edge_json TEXT,PRIMARY KEY(system_id,edge_id));
        """)

    def connect(**configuration):
        """为每次生产事务提供独立连接，配置是虚构测试参数。"""

        return SqliteConnection(path)

    first = MySqlMetadataStore({"host": "unused", "user": "test", "database": "test"}, "first", connect)
    second = MySqlMetadataStore({"host": "unused", "user": "test", "database": "test"}, "second", connect)
    system = SystemDefinition(system_id="refund-core", name="退款", source_path="")
    first.execute("INSERT INTO ot_system(system_id,system_json) VALUES(%s,%s)", (system.system_id, encode_json(system.model_dump(mode="json"))))
    return MySqlKnowledgeStore(tmp_path / "first", first), MySqlKnowledgeStore(tmp_path / "second", second)


def test_interview_and_revision_are_shared_without_local_mirrors(tmp_path):
    """另一工作台立即读取访谈和修订，未知修订及跨系统身份仍明确拒绝。"""

    first, second = shared_workspace_pair(tmp_path)
    writer = KnowledgeInterviewStore(first.root / ".opentest", first.metadata)
    reader = KnowledgeInterviewStore(second.root / ".opentest", second.metadata)
    interview = KnowledgeInterview(system_id="refund-core", system_purpose="退款回归")
    writer.write_interview(interview)
    assert reader.read_interview("refund-core") == interview
    plan = KnowledgeRevisionPlan(revision_id="revision-abc123", system_id="refund-core", feedback="补充退款原因")
    writer.write_revision(plan)
    assert reader.read_revision("refund-core", plan.revision_id) == plan
    assert reader.list_revisions("refund-core") == [plan]
    with pytest.raises(ScopeViolationError):
        reader.read_revision("another-core", plan.revision_id)
    with pytest.raises(KnowledgeNotFoundError):
        reader.read_revision("refund-core", "revision-missing")
    assert not first.root.exists() and not second.root.exists()


def test_shared_archive_restores_from_another_workspace_without_moving_files(tmp_path):
    """共享归档只改变活动路由，另一工作台恢复不会覆盖原机源码绑定或配置。"""

    first, second = shared_workspace_pair(tmp_path)
    first.root.mkdir()
    local_config = first.root / "keep-local.yaml"
    local_config.write_text("local: untouched\n")
    archive = SystemArchiveStore(first).archive("refund-core", "暂时停用")
    assert archive.files == [] and archive.system.source_path == ""
    with pytest.raises(KnowledgeNotFoundError):
        second.get_system("refund-core")
    reader = SystemArchiveStore(second)
    assert reader.list_archives() == [archive]
    restored = reader.restore(archive.archive_id)
    assert restored.integrity_status == "restored"
    assert first.get_system("refund-core").name == "退款"
    assert local_config.read_text() == "local: untouched\n"
    assert not second.root.exists()
    with pytest.raises(ScopeViolationError):
        reader.restore(archive.archive_id)


def test_shared_archive_failure_rolls_back_record_and_active_flag(tmp_path, monkeypatch):
    """归档中途失败时活动系统和归档记录必须一起回滚。"""

    first, second = shared_workspace_pair(tmp_path)
    original = first.unregister_system

    def fail_after_unregister(system_id):
        """在真实标记更新后注入故障，验证外层事务不会提交半次归档。"""

        original(system_id)
        raise RuntimeError("test interruption")

    monkeypatch.setattr(first, "unregister_system", fail_after_unregister)
    with pytest.raises(RuntimeError, match="test interruption"):
        SystemArchiveStore(first).archive("refund-core", "暂时停用")
    assert second.get_system("refund-core").name == "退款"
    assert SystemArchiveStore(second).list_archives() == []


def test_shared_workflow_rejects_foreign_updates_and_cross_system_identity(tmp_path):
    """他机可以读任务，但不能修改已有所有者或复用同一个ID覆盖其他系统。"""

    first, second = shared_workspace_pair(tmp_path)
    payload = {"system_id": "refund-core", "status": "COMPLETED", "revision": 1}
    first.metadata.put_workflow("task", "task-one", payload)
    assert second.metadata.get_workflow("task", "task-one") == payload
    with pytest.raises(ScopeViolationError, match="workspace"):
        second.metadata.put_workflow("task", "task-one", {**payload, "status": "RUNNING"})
    with pytest.raises(ScopeViolationError, match="system"):
        first.metadata.put_workflow("task", "task-one", {**payload, "system_id": "another-core"})
    assert first.metadata.get_workflow("task", "task-one") == payload


def test_execution_summary_excludes_evidence_and_identity_remains_immutable(tmp_path):
    """列表投影不携带大证据，详情完整回读；状态更新不得漂移到另一请求身份。"""

    first, second = shared_workspace_pair(tmp_path)
    execution = DataExecution(execution_id="data-execution-" + "a" * 20, system_id="refund-core",
        capability_id="data-refund", capability_version=1, environment_id="qa", inputs={},
        request_id="request-data-one", status="COMPLETED", outputs={"order_id": "test-only"})
    payload = execution.model_dump(mode="json")
    first.metadata.save_execution("data", payload)
    assert second.metadata.read_execution("data", execution.execution_id) == payload
    summary = first.metadata.fetch_one("SELECT summary_json FROM ot_execution WHERE execution_id=%s", (execution.execution_id,))
    assert "outputs" not in summary["summary_json"] and "step_results" not in summary["summary_json"]
    with pytest.raises(ScopeViolationError, match="workspace"):
        second.metadata.save_execution("data", payload)
    with pytest.raises(ScopeViolationError, match="identity"):
        first.metadata.save_execution("data", {**payload, "request_id": "request-changed"})
    # 相同Data请求在另一个发起系统独立去重，不能误用Operation的全局命名空间。
    second_payload = {**payload, "execution_id": "data-execution-" + "b" * 20, "system_id": "another-core"}
    first.metadata.save_execution("data", second_payload)
    assert first.metadata.read_execution("data", execution.execution_id) == payload


def test_migration_preserves_repeated_historical_data_requests(tmp_path):
    """旧文件同请求的两次真实试跑都保留，索引由最近记录持有且重复迁移不丢证据。"""

    shared, _ = shared_workspace_pair(tmp_path)
    local = GitKnowledgeStore(tmp_path / "legacy")
    directory = local.root / ".opentest" / "data-capabilities" / "executions"
    directory.mkdir(parents=True)
    records = []
    for suffix, timestamp in (("a", "2026-09-19T09:40:00Z"), ("b", "2026-09-19T09:55:00Z")):
        record = DataExecution(execution_id="data-execution-" + suffix * 20, system_id="refund-core",
            capability_id="data-refund", capability_version=1, environment_id="qa", inputs={},
            request_id="old-case-variant", status="COMPLETED", outputs={"order_id": suffix}, created_at=timestamp)
        (directory / f"{record.execution_id}.json").write_text(record.model_dump_json())
        records.append(record)
    # 模拟较早一次被中断迁移先写入，恢复导入必须先释放其索引而不删除历史。
    shared.metadata.save_execution("data", records[0].model_dump(mode="json"))
    migration = StandaloneAssetMigrator(local, shared)
    migration._executions()
    migration._executions()
    for record in records:
        assert shared.metadata.read_execution("data", record.execution_id) == record.model_dump(mode="json")
    rows = shared.metadata.fetch_all("SELECT execution_id,request_id FROM ot_execution ORDER BY execution_id")
    assert [row["request_id"] for row in rows] == [None, "old-case-variant"]


def fixed_source_scope(system_id="refund-core"):
    """构造发布机器的固定commit范围，供跨工作台读取检验机器路径投影。"""

    baseline = SourceBaseline(source_path="/publisher/source", snapshot_path="/publisher/snapshot", commit="a" * 40)
    return CaseTemplateSourceScope(source_system_id=system_id, source_scan_id="scan-fixed",
        source_baseline=baseline, selected_operation_ids=["facade:refund"])


def test_case_generation_and_handoff_use_reader_source_bindings(tmp_path):
    """两类Case聚合仅共享commit，无绑定读者不会得到旧机器路径。"""

    first, second = shared_workspace_pair(tmp_path)
    scope = fixed_source_scope()
    generation = CaseTemplateGenerationV4(generation_id="case-template-generation-" + "a" * 20,
        system_id="refund-core", operation_id="facade:refund", source_scan_id="scan-fixed",
        source_scopes=[scope], coverage_id="coverage-fixed",
        runtime_registry_version="runtime/v1", value_registry_version="value-functions/v1", status="BLOCKED",
        input_contract=OperationInputKnowledgeContract(target_id="facade:refund", source_scan_id="scan-fixed",
            status="BLOCKED", request_schema={}, blocked_reason="test contract unavailable"),
        submission=CaseTemplateSubmission(data_functions=[], case_templates=[], unresolved=[]))
    CaseTemplateGenerationStoreV4(first).write(generation)
    handoff = CaseTemplateHandoffV4(handoff_id="case-template-handoff-" + "a" * 20,
        system_id="refund-core", entry_id="facade:refund", source_scan_id="scan-fixed",
        source_scopes=[scope], status="WAITING_FOR_AGENT")
    CaseTemplateHandoffStoreV4(first.root / ".opentest", first.metadata).write(handoff)
    reader = CaseTemplateGenerationStoreV4(second)
    handoffs = CaseTemplateHandoffStoreV4(second.root / ".opentest", second.metadata)
    unbound = reader.get("refund-core", generation.generation_id)
    assert unbound.source_scopes[0].source_baseline.readable_source_path == ""
    assert handoffs.get(handoff.handoff_id).source_scopes[0].source_baseline.readable_source_path == ""
    # 工作台后来绑定本机源码后，固定版本保持不变，所有读取路径都改用本机commit缓存。
    local_source = tmp_path / "second-source"
    local_source.mkdir()
    second.bind_source_path("refund-core", str(local_source))
    expected_snapshot = str(second.root / ".opentest" / "source-snapshots" / "refund-core" / scope.source_baseline.commit)
    rebound = reader.list("refund-core")[0]
    assert rebound.source_scopes[0].source_baseline.source_path == str(local_source)
    assert handoffs.list()[0].source_scopes[0].source_baseline.snapshot_path == expected_snapshot
    assert portable_scope_payload(rebound) == portable_scope_payload(generation)
    row = first.metadata.fetch_one("SELECT generation_json FROM ot_case_generation WHERE generation_id=%s", (generation.generation_id,))
    assert "/publisher" not in row["generation_json"]
    assert "/publisher" not in encode_json(first.metadata.get_workflow("case_handoff", handoff.handoff_id))
    assert scope.source_baseline.source_path == "/publisher/source"


def test_data_versions_and_handoffs_hydrate_each_scope_without_rewriting_business_paths(tmp_path):
    """共享Data定义和草稿按各自来源系统投影，业务literal中的同名路径字段原样保留。"""

    first, second = shared_workspace_pair(tmp_path)
    fixture_path = Path(__file__).parents[1] / "fixtures" / "data-capabilities" / "refund-supplement-report.json"
    definition = json.loads(fixture_path.read_text())
    business_literal = {"source_path": "/business/source", "source_scopes": [{
        "source_system_id": "refund-core", "source_baseline": {"source_path": "/business/nested", "snapshot_path": "/business/snapshot", "commit": "literal-commit"}}]}
    definition["query_steps"][0]["arguments"]["business_path"] = {"kind": "literal", "value": business_literal}
    scopes = [fixed_source_scope(), fixed_source_scope("provider-core")]
    version = DataCapabilityVersion(**definition, owner_system_id="refund-core", version=1, source_scopes=scopes)
    writer, reader = DataCapabilityStore(first), DataCapabilityStore(second)
    writer.publish(version)
    handoff = DataCapabilityHandoff(task_id="task-" + "a" * 16, system_id="refund-core",
        kind="data_capability", goal="prepare test data", source_scopes=scopes)
    writer.save_handoff(handoff)
    unbound = reader.get("refund-core", version.capability_id, 1)
    assert all(scope.source_baseline.readable_source_path == "" for scope in unbound.source_scopes)
    local_source = tmp_path / "provider-source"
    local_source.mkdir()
    second.bind_source_path("provider-core", str(local_source))
    rebound = reader.list_versions("refund-core")[0]
    assert rebound.source_scopes[0].source_baseline.source_path == ""
    assert rebound.source_scopes[1].source_baseline.source_path == str(local_source)
    assert reader.get_handoff(handoff.task_id).source_scopes[1].source_baseline.source_path == str(local_source)
    assert rebound.query_steps[0].arguments["business_path"].value == business_literal
    assert portable_scope_payload(rebound) == portable_scope_payload(version)
    row = first.metadata.fetch_one("SELECT definition_json FROM ot_data_capability_version WHERE system_id=%s", ("refund-core",))
    stored = decode_json(row["definition_json"])
    assert stored["source_scopes"][0]["source_baseline"]["source_path"] == ""
    assert stored["query_steps"][0]["arguments"]["business_path"]["value"] == business_literal


def test_data_version_agent_summary_omits_steps_and_frozen_scopes():
    """Agent检索摘要只含选择所需字段，完整步骤与冻结范围留给精确版本读取。"""

    fixture_path = Path(__file__).parents[1] / "fixtures" / "data-capabilities" / "refund-supplement-report.json"
    definition = json.loads(fixture_path.read_text())
    version = DataCapabilityVersion(**definition, owner_system_id="refund-core", version=3,
                                    source_scopes=[fixed_source_scope()])

    summary = version.agent_summary()

    assert set(summary) == {"owner_system_id", "capability_id", "version", "name", "purpose", "inputs", "outputs"}
    assert (summary["owner_system_id"], summary["capability_id"], summary["version"]) == (
        "refund-core", definition["capability_id"], 3)
    assert len(summary["outputs"]) == len(definition["outputs"])


def test_published_capability_keeps_portable_candidate_baseline_and_idempotence(tmp_path):
    """Published内嵌Candidate同样去机器路径，跨机重试按版本语义去重且拒绝业务内容改变。"""

    first, second = shared_workspace_pair(tmp_path)
    scope = fixed_source_scope()
    capability = PublishedOperationCapability(capability_id="published-refund", publication_request_id="publish-refund-one",
        draft_id="capability-draft:refund-one", system_id="refund-core", business_name="退款查询",
        business_purpose="取得退款状态", input_schema={}, output_fact_schema={}, mutability=OperationMutability.READ_ONLY,
        candidate_ref=CandidateRef(source_system_id="refund-core", candidate_id="candidate-refund", source_scan_id="scan-fixed",
            source_baseline=scope.source_baseline, candidate_signature="Refund#query"),
        provider_operation_ref=ProviderOperationRef(source_system_id="refund-core", operation_id="facade:refund", source_scan_id="scan-fixed"))
    PublishedCapabilityStore(first).publish(capability)
    reader = PublishedCapabilityStore(second)
    assert reader.get("refund-core", capability.capability_id).candidate_ref.source_baseline.readable_source_path == ""
    local_source = tmp_path / "second-published-source"
    local_source.mkdir()
    second.bind_source_path("refund-core", str(local_source))
    rebound = reader.get("refund-core", capability.capability_id)
    assert rebound.candidate_ref.source_baseline.source_path == str(local_source)
    assert reader.publish(rebound) == rebound
    with pytest.raises(KnowledgeValidationError, match="request identity"):
        reader.publish(rebound.model_copy(update={"business_purpose": "改变业务语义"}))
    row = first.metadata.fetch_one("SELECT capability_json FROM ot_published_capability WHERE system_id=%s", ("refund-core",))
    assert "/publisher" not in row["capability_json"] and str(local_source) not in row["capability_json"]


def test_old_archive_imports_compatible_knowledge_and_blocks_incomplete_shared_restore(tmp_path):
    """退役旧系统保留可查询知识，旧Case摘要损坏不隐藏历史，也不能伪装为完整共享恢复。"""

    shared, second = shared_workspace_pair(tmp_path)
    local = GitKnowledgeStore(tmp_path / "legacy")
    local.initialize()
    source = tmp_path / "old-source"
    source.mkdir()
    local.register_system(SystemDefinition(system_id="train-core", name="旧列车系统", source_path=str(source)))
    node = KnowledgeNode(node_id="flow:old-order", system_id="train-core", kind=KnowledgeNodeKind.COMMON_LOGIC,
        title="旧订单逻辑", summary="保留原知识")
    local.write_node(node, "原人工知识和自动内容仍保留。")
    legacy_case = local.system_root("train-core") / "cases" / "retired.yaml"
    legacy_case.parent.mkdir(parents=True, exist_ok=True)
    legacy_case.write_text("legacy_case: preserved\n")
    archive = SystemArchiveStore(local).archive("train-core", "旧系统接入错误")
    archived_case = local.root / "archives" / archive.archive_id / "knowledge" / "systems" / "train-core" / "cases" / "retired.yaml"
    archived_case.write_text("legacy_case: changed-before-migration\n")
    # 仅知识目录通过原清单验证，已退役Case继续原地保留并明确需要本机完整性处理。
    migration = StandaloneAssetMigrator(local, shared)
    migration._archives()
    migration._archives()
    row = second.metadata.fetch_one("SELECT system_json,is_archived FROM ot_system WHERE system_id=%s", ("train-core",))
    assert row["is_archived"] == 1
    assert decode_json(row["system_json"])["source_path"] == ""
    stored_node = second.metadata.fetch_one("SELECT node_json,body FROM ot_knowledge_node WHERE system_id=%s", ("train-core",))
    assert decode_json(stored_node["node_json"])["node_id"] == node.node_id
    assert "原人工知识和自动内容仍保留" in stored_node["body"]
    reader = SystemArchiveStore(second)
    record = reader.list_archives()[0]
    assert record.restore_scope == "local_only" and record.integrity_status == "damaged"
    assert "文件模式" in record.restore_blocked_reason and "完整性问题" in record.restore_blocked_reason
    with pytest.raises(KnowledgeValidationError, match="文件模式"):
        reader.restore(record.archive_id)
    assert archived_case.read_text() == "legacy_case: changed-before-migration\n"
    assert reader.active_codex_client_handoff_count(record.archive_id) == 0
    with pytest.raises(KnowledgeNotFoundError):
        second.get_system("train-core")
