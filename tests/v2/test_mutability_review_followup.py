"""分类评审收尾：真实事务、候选隔离、依赖诊断及单次保存的版本选择。"""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.mysql_knowledge import MySqlKnowledgeStore
from opentest.adapters.mysql_metadata import MySqlMetadataStore
from opentest.application.case_template_v4 import CaseTemplateV4Service, case_generation_blocker_message
from opentest.application.operation_contracts import OperationContractSupplement
from opentest.application.operations import OperationCapabilityCatalog
from opentest.application.publication import PublicationService
from opentest.application.web_generation import WebGenerationService
from opentest.domain.case_template_v4 import CaseTemplateSourceScope, CaseTemplateSubmission
from opentest.domain.data_capabilities import DataCapabilityDefinition, DataCapabilityPrepareRequest
from opentest.domain.errors import IdempotencyConflictError, KnowledgeValidationError, KnowledgeNotFoundError
from opentest.domain.models import DsfOperationDefinition, OperationKind, OperationMutability
from opentest.domain.publication import InterfaceDraftUpdate, PublicationScope
from tests.v2.test_interface_mutability import shared_contract, _task_service, _evidence
from tests.v2.test_operation_contracts import _service, SYSTEM_ID, SCAN_ID, OPERATION_ID
from tests.v2.test_shared_publication import PublicationDatabase
from tests.v2.test_mysql_metadata import SqliteConnection, SqliteCursor
from tests.v2.test_downstream_interfaces import _search_fixture
from tests.v2.test_case_template_v4_revision import _handoff


class PublicationCursor(SqliteCursor):
    """沿用生产事务与连接管理，仅适配共享发布SQL的SQLite传输语法。"""

    def execute(self, sql, parameters=()):
        """执行同一SQL和参数；会话设置交给已有驱动适配器，发布语句只换方言。"""

        if sql == "SET SESSION TRANSACTION READ ONLY":
            return super().execute(sql, parameters)
        # 复用已有测试方言转换，CAS、版本追加和回滚均由真实SQL及生产服务决定。
        translated = PublicationDatabase._sql(self, sql)
        self.delegate.execute(translated, parameters)


class PublicationConnection(SqliteConnection):
    """为生产MySQL元数据适配器提供隔离的真实SQL连接。"""

    def cursor(self):
        """返回发布SQL游标，提交、回滚、关闭继续由生产元数据事务调用。"""

        return PublicationCursor(self.connection.cursor())


@pytest.mark.parametrize("conflict", [False, True])
def test_contract_tool_production_transaction_is_atomic(shared_contract, tmp_path, conflict):
    """真实工具入口用生产系统/元数据事务提交；CAS冲突不遗留契约、latest或半份草稿。"""

    service, _, seed = shared_contract
    path = tmp_path / "contracts.sqlite"
    # 只替换数据库驱动，系统行锁调用、嵌套事务和所有业务保存走生产实现。
    with sqlite3.connect(path) as destination:
        seed.connection.backup(destination)
        for column in ("parent_record_id TEXT", "target_id TEXT", "environment_id TEXT"):
            destination.execute(f"ALTER TABLE ot_workflow_record ADD {column}")
        destination.execute("CREATE TABLE ot_data_capability_version(system_id TEXT,capability_id TEXT,version INTEGER,definition_json TEXT,created_at TEXT)")

    def connect(**configuration):
        """为生产连接池创建独立测试连接，不读取本机数据库配置。"""

        return PublicationConnection(path)

    metadata = MySqlMetadataStore({"host": "unused", "user": "test", "database": "test"}, "review", connect)
    store = MySqlKnowledgeStore(service.store.root, metadata)
    store.get_system = service.store.get_system
    service.store = store
    service.artifacts.metadata = service.contracts.metadata = metadata
    data, tasks = _task_service(service, tmp_path)
    try:
        task = data.prepare(SYSTEM_ID, DataCapabilityPrepareRequest(kind="contract", goal="分类分析",
            operation_id=OPERATION_ID, baseline_id="base-contract", scan_id=SCAN_ID, contract_revision=0,
            interaction_mode="native", execution_mode="generate_only"))
        handoff = data._handoff(task.task_id)
        if conflict:
            # 同一员工在分析期间另存草稿；不修改任务所冻结的预期CAS版本。
            metadata.execute("UPDATE ot_interface_contract_version SET author_user_id='employee-a' WHERE revision=0")
            PublicationService(store).save_interface_draft(handoff.publication_scope, handoff.contract_draft)
        before = metadata.fetch_all("SELECT * FROM ot_interface_draft")
        tool_args = {"expected_revision": 0, "supplement": {"mutability": "UNKNOWN", "mutability_reason": "外部语义不可见"}}
        if conflict:
            with pytest.raises(IdempotencyConflictError):
                data.call_agent_tool(task.task_id, "supplement_contract", tool_args)
        else:
            data.call_agent_tool(task.task_id, "supplement_contract", tool_args)
        # 从另一只读连接检查三个共享事实，不能以工具异常或Mock调用次数代替原子性证据。
        assert metadata.fetch_one("SELECT latest_contract_revision FROM ot_interface")["latest_contract_revision"] == (0 if conflict else 1)
        versions = metadata.fetch_all("SELECT revision FROM ot_interface_contract_version ORDER BY revision")
        assert [item["revision"] for item in versions] == ([0] if conflict else [0, 1])
        after = metadata.fetch_all("SELECT * FROM ot_interface_draft")
        if conflict:
            assert after == before
            assert data._handoff(task.task_id).contract_version is None
        else:
            assert after[0]["contract_revision"] == 1
    finally:
        tasks._executor.shutdown(wait=True)
        metadata.close()


@pytest.mark.parametrize("revision", [0, 99])
def test_missing_candidate_contract_is_display_only_and_frozen_missing_fails(shared_contract, revision):
    """未选候选缺契约可被发现但不显示只读；相同缺失发生于冻结接口则严格拒绝。"""

    service, data, database = shared_contract
    operation = service.catalog.derive.return_value[0]
    operation.mutability = OperationMutability.READ_ONLY
    scope = PublicationScope(system_id=SYSTEM_ID, baseline_id="base-contract", user_id="employee-a")
    visible = PublicationService(data.store).list_interface_summaries(scope)
    visible[0]["contract_revision"] = revision
    database.execute("DELETE FROM ot_interface_contract_version WHERE revision=%s", (revision,))
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store, engine.operation_contracts = service.store, service
    engine.runtime = SimpleNamespace(operation_catalog=service.catalog)
    handoff = SimpleNamespace(system_id=SYSTEM_ID, source_scopes=[])
    engine._runtime_capabilities = Mock(side_effect=AssertionError("目录已提供冻结能力，不应重复派生"))
    classified, details = engine._classify_visible_candidates(handoff, [operation], visible, [])
    # 索引合并的最终展示值必须覆盖扫描READ_ONLY，领域能力及执行范围保持原样。
    entry = {"mutability": classified[0].mutability.value, **details[operation.operation_id]}
    assert entry["mutability"] is None and entry["contract_available"] is False
    assert f"revision={revision}" in entry["contract_unavailable_reason"]
    assert operation.mutability == OperationMutability.READ_ONLY and handoff.source_scopes == []
    source_scope = CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
        source_baseline=service.artifacts.read(SYSTEM_ID, SCAN_ID).baseline,
        selected_operation_ids=[OPERATION_ID], contract_revisions={OPERATION_ID: revision})
    handoff.source_scopes = [source_scope]
    with pytest.raises((KnowledgeValidationError, KnowledgeNotFoundError)):
        CaseTemplateV4Service._runtime_capabilities(engine, handoff)


def test_catalog_survives_an_unrelated_missing_contract(shared_contract, tmp_path):
    """完整目录仍返回健康目标，坏候选显示为空分类且不会进入Runtime；不重复派生已选能力。"""

    service, _, database = shared_contract
    data, tasks = _task_service(service, tmp_path)
    try:
        operation = service.catalog.derive.return_value[0]
        candidate = operation.model_copy(update={"operation_id": "facade:demo.RefundFacade#query", "mutability": OperationMutability.READ_ONLY})
        service.catalog.derive.return_value.append(candidate)
        database.execute("INSERT INTO ot_interface(interface_id,system_id,scan_id,operation_id) VALUES(2,%s,%s,%s)", (SYSTEM_ID, SCAN_ID, candidate.operation_id))
        database.execute("INSERT INTO ot_baseline_interface(baseline_interface_id,baseline_id,operation_id,current_interface_id,current_contract_revision,availability) VALUES(2,'base-contract',%s,2,99,'AVAILABLE')", (candidate.operation_id,))
        source_scope = CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
            source_baseline=service.artifacts.read(SYSTEM_ID, SCAN_ID).baseline,
            selected_operation_ids=[OPERATION_ID], contract_revisions={OPERATION_ID: 0})
        handoff = _handoff(tmp_path).model_copy(update={"system_id": SYSTEM_ID, "entry_id": OPERATION_ID,
            "source_scan_id": SCAN_ID, "source_scopes": [source_scope], "baseline_id": "base-contract", "owner_user_id": "employee-a"})
        engine = data.cases
        engine.handoffs = SimpleNamespace(get=Mock(return_value=handoff))
        engine.data_capabilities = None
        engine._handoff_contract = Mock(return_value=service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 0))
        service.catalog.derive.reset_mock()
        catalog = engine.catalog(handoff.handoff_id)
        # 全链路验证最终序列化字段；候选不能因展示容错获得函数描述或冻结修订。
        unavailable = next(item for item in catalog["related_interface_index"] if item["operation_id"] == candidate.operation_id)
        assert unavailable["mutability"] is None and unavailable["contract_available"] is False
        assert catalog["target"]["operation_id"] == OPERATION_ID
        assert all(item["provider_ref"] != candidate.operation_id for item in catalog["runtime_function_registry"]["functions"])
        assert service.catalog.derive.call_count == 2  # 一次运行范围、一次完整发现目录。
    finally:
        tasks._executor.shutdown(wait=True)


@pytest.mark.parametrize("warm", [False, True])
def test_legacy_eligibility_survives_cache_write_failure(tmp_path, monkeypatch, caplog, warm):
    """冷热目录缓存写失败仍返回核验结果；不能把真实contract_gap清掉或写回共享事实。"""

    # 旧UNKNOWN原因曾遮住真实缺口；缓存故障不能使重算丢掉该缺口。
    service = _service(tmp_path)
    manifest = service.artifacts.read(SYSTEM_ID, SCAN_ID)
    manifest.entries[0].metadata["contract_gap"] = "真实输入缺口"
    manifest.dsf_operations = [DsfOperationDefinition(operation_id="dsf:demo.refund.billSupplement",
        provider_system_id=SYSTEM_ID, gs_name="demo", service_name="refund", version="1", action="billSupplement", source_refs=[_evidence()])]
    old = service.catalog.derive.return_value[0].model_copy(update={"executable": False,
        "mutability": OperationMutability.UNKNOWN, "blocked_reason": "Facade操作的读写属性尚未确定。"})
    database = Mock()
    database.fetch_all.return_value = [{"operation_json": old.model_dump_json()}]
    service.artifacts.metadata = database
    service.artifacts.read = Mock(return_value=manifest)
    if warm:
        service.artifacts.cache_interface_operations(SYSTEM_ID, SCAN_ID, [old])
    monkeypatch.setattr(service.artifacts, "_write_json_atomic", Mock(side_effect=PermissionError("isolated cache")))
    effective = OperationCapabilityCatalog(service.store, service.artifacts).derive(SYSTEM_ID, SCAN_ID, include_registered=False)[0]
    assert not effective.executable and effective.blocked_reason == "真实输入缺口"
    assert "接口投影缓存写入失败" in caplog.text
    database.execute.assert_not_called()


def test_draft_batches_visible_revisions_per_scope(shared_contract, monkeypatch):
    """多个新数据操作一次读取scope索引，下次保存重新读取，旧冻结修订不被刷新。"""

    # 两个同扫描操作共享一次可见性读取；使用真实SQL指针保留发布优先级的语义。
    service, data, database = shared_contract
    operation = service.catalog.derive.return_value[0]
    operation.executable = True
    second = operation.model_copy(update={"operation_id": "facade:demo.RefundFacade#query"})
    service.catalog.derive.return_value.append(second)
    base = service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 0)
    database.execute("INSERT INTO ot_interface(interface_id,system_id,scan_id,operation_id) VALUES(2,%s,%s,%s)", (SYSTEM_ID, SCAN_ID, second.operation_id))
    database.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json) VALUES(2,0,%s)", (base.model_copy(update={"target_id": second.operation_id}).model_dump_json(),))
    database.execute("INSERT INTO ot_baseline_interface(baseline_interface_id,baseline_id,operation_id,current_interface_id,current_contract_revision,availability) VALUES(2,'base-contract',%s,2,0,'AVAILABLE')", (second.operation_id,))
    task_data, tasks = _task_service(service, Path(service.store.root).parent)
    try:
        source_scope = CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
            source_baseline=service.artifacts.read(SYSTEM_ID, SCAN_ID).baseline)
        handoff = SimpleNamespace(source_scopes=[source_scope], system_id=SYSTEM_ID,
            model_copy=lambda *, update: SimpleNamespace(**update))
        payload = json.loads((Path(__file__).parents[1] / "fixtures/data-capabilities/refund-supplement-report.json").read_text())
        steps = [step for group in ("query_steps", "create_steps", "verify_steps") for step in payload[group] if step["operation"] == "runtime_call"]
        for index, step in enumerate(steps):
            step["function_id"] = operation.operation_id if index % 2 == 0 else second.operation_id
        definition = DataCapabilityDefinition.model_validate(payload)
        original = PublicationService.list_interface_summaries
        read = Mock(side_effect=original)
        monkeypatch.setattr(PublicationService, "list_interface_summaries", lambda self, *args: read(self, *args))
        first = task_data._select_draft_operations(handoff, definition)
        assert first.source_scopes[0].contract_revisions == {operation.operation_id: 0, second.operation_id: 0}
        assert read.call_count == 2
        task_data._select_draft_operations(handoff, definition)
        assert read.call_count == 4
    finally:
        tasks._executor.shutdown(wait=True)


@pytest.mark.parametrize("operation,tool", [("case-generation", "read_outer_api_info"), ("data-capability-generation", "read_contract")])
def test_resolved_only_execution_error_names_supported_selection_tool(operation, tool):
    """解析定义未选中时，真实执行入口给出任务实际支持的选择工具，不重复提示解析。"""

    # 冻结目录为空即可复现“只解析未选中”，此测试不会派发任何QA请求。
    service = WebGenerationService.__new__(WebGenerationService)
    cases = SimpleNamespace(_runtime_capabilities=Mock(return_value=[]))
    service.application = SimpleNamespace(case_template_v4=cases)
    service._offline_handoff = Mock(return_value=SimpleNamespace(execution_mode="generate_and_verify"))
    task = SimpleNamespace(operation=operation, system_id=SYSTEM_ID, task_id="task-review", trace_id="review")
    with pytest.raises(KnowledgeValidationError, match=tool) as failure:
        service._offline_tool(task, "execute_operation", {"operation_id": OPERATION_ID})
    assert OPERATION_ID in str(failure.value)


def test_required_enum_gap_is_in_blocker_summary_without_questions():
    """已保存的枚举缺口直接进入失败摘要；不要求问题投影成功，也不猜测业务code。"""

    # 模拟草稿已保存但问题投影未同步，失败摘要仍必须保留可恢复的根因。
    submission = CaseTemplateSubmission.model_validate({"data_functions": [], "case_templates": [], "unresolved": [{
        "unresolved_id": "enum-code", "owner_type": "generation", "owner_name": "", "field_path": "source",
        "reason": "demo.ReportSourceEnum.getCode映射无固定证据，demo:api:1 sources.jar缺失"}]})
    handoff = SimpleNamespace(draft_submission=submission, questions=[], validation_issues=[], safe_error="")
    assert "ReportSourceEnum.getCode" in case_generation_blocker_message(handoff)


def test_provider_visibility_error_identifies_recovery_scope(shared_contract):
    """不可见provider契约保留边界，错误给出系统、基准和接口及重新选择步骤。"""

    service, _, database = shared_contract
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store = service.store
    # 隐藏当前发布指针，不以删除底层契约模拟权限变化。
    database.execute("UPDATE ot_baseline_interface SET availability='REMOVED'")
    handoff = SimpleNamespace(knowledge_dependencies=[], system_id=SYSTEM_ID, baseline_id="base-contract",
        owner_user_id="employee-a", knowledge_view="published")
    with pytest.raises(KnowledgeValidationError) as failure:
        engine._visible_dependency_knowledge(handoff, service.catalog.derive.return_value[0])
    assert all(text in str(failure.value) for text in (SYSTEM_ID, OPERATION_ID, "base-contract", "read_outer_api_info", "发布"))


def test_provider_ambiguity_returns_actual_baseline_choices(shared_contract):
    """有多个已可见provider时返回真实基准选项，不擅自选第一个。"""

    service, _, database = shared_contract
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store = service.store
    operation = service.catalog.derive.return_value[0]
    second = operation.model_copy(update={"source_scan_id": "scan-other"})
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id) VALUES('scan-other','base-other',%s)", (SYSTEM_ID,))
    # 只替代关系发现；歧义分支仍从SQL扫描表提取真实的基准参数。
    engine._shared_provider_candidates = Mock(return_value=[operation, second])
    external = operation.model_copy(update={"kind": OperationKind.EXTERNAL_DSF,
        "provider_definition": DsfOperationDefinition(operation_id="dsf:demo:query", provider_system_id=SYSTEM_ID, gs_name="demo", service_name="refund", action="query", version="1", source_refs=[_evidence()])})
    with pytest.raises(KnowledgeValidationError) as failure:
        engine._shared_related_operation(SimpleNamespace(), OPERATION_ID, [external], "")
    assert "provider_baseline_id=base-contract" in str(failure.value)
    assert "provider_baseline_id=base-other" in str(failure.value)


@pytest.mark.parametrize("missing_error", [KnowledgeValidationError, KnowledgeNotFoundError])
def test_source_recovery_distinguishes_legacy_worktree_and_snapshot(tmp_path, monkeypatch, missing_error):
    """旧无快照任务提示恢复原内容；有快照时不检查工作树且失败指向固定材料。"""

    service, scope, _ = _search_fixture(tmp_path)
    # 同一个工作树变动对旧任务应拒绝，对有固定快照的任务不构成重新校验理由。
    (Path(scope.source_baseline.source_path) / "changed.java").write_text("changed")
    with pytest.raises(KnowledgeValidationError, match="重新扫描并新建任务"):
        service._source_root(scope)
    fixed = scope.model_copy(update={"source_baseline": scope.source_baseline.model_copy(update={"snapshot_path": str(tmp_path / "snapshot")})})
    monkeypatch.setattr(service.artifacts, "require_source_snapshot", Mock(return_value=tmp_path / "snapshot"))
    assert service._source_root(fixed) == tmp_path / "snapshot"
    service.artifacts.require_source_snapshot.side_effect = missing_error("材料缺失")
    with pytest.raises(KnowledgeValidationError, match="恢复该基准的固定源码材料"):
        service._source_root(fixed)


def test_actual_interface_list_and_detail_expose_missing_contract(shared_contract):
    """页面实际使用的列表与详情都给出不可用原因；健康项不携带伪造缺失状态。"""

    service, _, database = shared_contract
    publications = PublicationService(service.store)
    scope = PublicationScope(system_id=SYSTEM_ID, baseline_id="base-contract", user_id="employee-a")
    healthy = publications.list_interface_summaries(scope)[0]
    assert healthy["contract_available"] is True and healthy["contract_unavailable_reason"] == ""
    # 模拟共享指针内容缺失，列表仍返回接口，详情保留同一缺口而不读取latest。
    database.execute("DELETE FROM ot_interface_contract_version WHERE revision=0")
    summary = publications.list_interface_summaries(scope)[0]
    detail = publications.get_interface(scope, 1)
    for item in (summary, detail):
        assert item["contract_available"] is False and item["mutability"] is None
        assert "revision=0" in item["contract_unavailable_reason"]


def test_frozen_zero_contract_read_and_supplement_do_not_rebuild(shared_contract, tmp_path):
    """共享任务已冻结零版后，读取和补充都不得用扫描重建丢失的内容起点。"""

    service, _, database = shared_contract
    data, tasks = _task_service(service, tmp_path)
    try:
        task = data.prepare(SYSTEM_ID, DataCapabilityPrepareRequest(kind="contract", goal="分类分析",
            operation_id=OPERATION_ID, baseline_id="base-contract", scan_id=SCAN_ID, contract_revision=0,
            interaction_mode="native", execution_mode="generate_only"))
        database.execute("DELETE FROM ot_interface_contract_version WHERE revision=0")
        # 两个真实工具入口都必须在任何副本构建或写入前拒绝冻结材料缺失。
        with pytest.raises(KnowledgeValidationError, match="冻结的接口契约版本不存在"):
            data.call_agent_tool(task.task_id, "read_contract", {"source_system_id": SYSTEM_ID, "operation_id": OPERATION_ID})
        with pytest.raises(KnowledgeValidationError, match="冻结的接口契约版本不存在"):
            data.call_agent_tool(task.task_id, "supplement_contract", {"expected_revision": 0,
                "supplement": {"mutability": "UNKNOWN", "mutability_reason": "语义不足"}})
        assert database.fetch_all("SELECT revision FROM ot_interface_contract_version") == []
    finally:
        tasks._executor.shutdown(wait=True)
