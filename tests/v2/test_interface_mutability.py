"""接口执行资格、分类证据、冻结修订及个人补充事务的回归。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.auth import bind_authenticated_identity
from opentest.application.case_template_v4 import CaseTemplateV4Service
from opentest.application.case_template_registries import CaseTemplateRegistryLoader
from opentest.application.data_capabilities import DataCapabilityService
from opentest.application.operation_contracts import OperationContractService, OperationContractSupplement
from opentest.application.operations import OperationCapabilityCatalog
from opentest.application.publication import PublicationService
from opentest.application.tasks import LocalTaskManager
from opentest.domain.auth import AuthenticatedIdentity, EmployeeIdentity
from opentest.domain.case_template_v4 import CaseTemplateSourceScope
from opentest.domain.data_capabilities import DataCapabilityPrepareRequest
from opentest.domain.errors import IdempotencyConflictError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import DsfOperationDefinition, OperationMutability, SourceReference
from opentest.domain.publication import InterfaceDraftUpdate, PublicationScope
from tests.v2.test_operation_contracts import _service, _supplement, SYSTEM_ID, SCAN_ID, OPERATION_ID
from tests.v2.test_shared_publication import KnowledgeTransactions, PublicationDatabase


def _evidence():
    """返回夹具中真实入口声明的源码位置，供分类证据校验使用。"""

    return SourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#billSupplement", line=3)


@pytest.mark.parametrize("warm_cache", [False, True])
@pytest.mark.parametrize("gap", ["", "缺少真实请求类型"])
def test_old_unknown_eligibility_preserves_scan_and_real_gaps(tmp_path, warm_cache, gap):
    """旧数据库/缓存都解除UNKNOWN误阻塞，但重新发现被旧分支遮住的契约缺口。"""

    service = _service(tmp_path)
    manifest = service.artifacts.read(SYSTEM_ID, SCAN_ID)
    manifest.entries[0].metadata["contract_gap"] = gap
    manifest.dsf_operations = [DsfOperationDefinition(operation_id="dsf:demo.refund.billSupplement",
        provider_system_id=SYSTEM_ID, gs_name="demo", service_name="refund", version="1",
        action="billSupplement", source_refs=[_evidence()])]
    service.artifacts.write_manifest(manifest)
    old = service.catalog.derive.return_value[0].model_copy(update={"mutability": OperationMutability.UNKNOWN,
        "executable": False, "blocked_reason": "Facade操作的读写属性尚未确定。"})
    original = old.model_dump(mode="json")
    database = Mock()
    database.fetch_all.return_value = [{"operation_json": json.dumps(original)}]
    service.artifacts.metadata = database
    # 只替换Manifest读取的共享传输；接口缓存仍走真实文件和生产冷/热读取路径。
    service.artifacts.read = Mock(return_value=manifest)
    if warm_cache:
        service.artifacts.cache_interface_operations(SYSTEM_ID, SCAN_ID, [old])
    catalog = OperationCapabilityCatalog(service.store, service.artifacts)
    first = catalog.derive(SYSTEM_ID, SCAN_ID, include_registered=False)[0]
    second = catalog.derive(SYSTEM_ID, SCAN_ID, include_registered=False)[0]
    assert first == second
    assert first.executable is (not gap)
    assert gap in first.blocked_reason if gap else first.blocked_reason == ""
    for key, value in original.items():
        if key not in {"executable", "blocked_reason"}:
            assert first.model_dump(mode="json")[key] == value
    assert database.fetch_all.call_count == (0 if warm_cache else 1)
    database.execute.assert_not_called()
    assert old.model_dump(mode="json") == original


def test_analyzed_unknown_revokes_read_only_without_changing_eligibility(tmp_path):
    """无法确定可以无证据提交，且实际撤销扫描只读，不改变执行资格或原契约。"""

    # 方法图不可获得时仍可提交UNKNOWN；同时断言扫描原值没有被原地覆盖。
    service = _service(tmp_path)
    operation = service.catalog.derive.return_value[0]
    operation.mutability = OperationMutability.READ_ONLY
    service._reachable_methods = Mock(side_effect=AssertionError("UNKNOWN不应要求可达图"))
    contract = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID,
        OperationContractSupplement(mutability="UNKNOWN", mutability_reason="外部调用实现不可见"), 0)
    effective = service.apply_mutability(operation, contract)
    assert contract.mutability_analyzed and effective.mutability == OperationMutability.UNKNOWN
    assert effective.executable == operation.executable and effective.blocked_reason == operation.blocked_reason
    assert operation.mutability == OperationMutability.READ_ONLY
    base = service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 0)
    assert service.apply_mutability(operation, base).mutability == OperationMutability.READ_ONLY


@pytest.mark.parametrize("classification", ["WRITE", "READ_ONLY"])
def test_classification_rejects_unreachable_evidence(tmp_path, classification):
    """确定分类不能引用其他入口或任意注释行，即便字段结构合法也拒绝。"""

    service = _service(tmp_path)
    request = OperationContractSupplement(mutability=classification,
        mutability_evidence_refs=[_evidence().model_copy(update={"line": 2})])
    with pytest.raises(KnowledgeValidationError, match="实际执行方法"):
        service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, request, 0)


def test_read_only_requires_all_reachable_methods_and_no_scan_write(tmp_path):
    """只读须覆盖全图且不得与扫描写入冲突；有效证据仍可确认写入。"""

    # 逐一去掉扫描冲突和图覆盖缺口，验证每一道独立证据门禁。
    service = _service(tmp_path)
    request = OperationContractSupplement(mutability="READ_ONLY", mutability_evidence_refs=[_evidence()])
    with pytest.raises(KnowledgeValidationError, match="扫描提示写"):
        service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, request, 0)
    service.catalog.derive.return_value[0].mutability = OperationMutability.UNKNOWN
    reachable = service._reachable_methods(service.artifacts.read(SYSTEM_ID, SCAN_ID), OPERATION_ID)
    service._reachable_methods = Mock(return_value={**reachable, "demo.Helper#query()":
        SourceReference(path="Helper.java", symbol="demo.Helper#query", line=1)})
    with pytest.raises(KnowledgeValidationError, match="全部可达方法"):
        service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, request, 0)
    service._reachable_methods = Mock(return_value=reachable)
    classified = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, request, 0)
    assert classified.mutability == "READ_ONLY" and classified.mutability_analyzed


def test_explicit_base_does_not_inherit_other_unpublished_fields(tmp_path):
    """追加序号可以越过他人版本，但补充内容必须从任务冻结零版开始。"""

    # 先制造内容不同的后来版本，再从零版提交，区分序号分配与内容继承。
    service = _service(tmp_path)
    other = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, _supplement("他人的私有业务描述"))
    mine = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID,
        OperationContractSupplement(mutability="WRITE", mutability_evidence_refs=[_evidence()]), 0)
    assert mine.contract_revision == other.contract_revision + 1
    assert "他人的私有业务描述" not in mine.model_dump_json()
    assert mine.mutability == "WRITE"
    assert service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 1) == other


def test_runtime_applies_each_frozen_revision_and_keeps_scan_unchanged(tmp_path):
    """相同扫描中不同依赖分别使用冻结修订，不静默追随后来的分类。"""

    # 两个接口分别冻结零版和已分析修订，不能以目标修订替代所有依赖。
    service = _service(tmp_path)
    operation = service.catalog.derive.return_value[0]
    operation.mutability = OperationMutability.READ_ONLY
    base = service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 0)
    service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID,
        OperationContractSupplement(mutability="UNKNOWN", mutability_reason="无法确认"), 0)
    second = operation.model_copy(update={"operation_id": "facade:demo.Other#query"})
    service.catalog.derive.return_value.append(second)
    service.contracts.save(SYSTEM_ID, base.model_copy(update={"target_id": second.operation_id,
        "contract_revision": 1, "mutability_analyzed": True, "mutability": "UNKNOWN", "mutability_reason": "未知"}))
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store, engine.operation_contracts = service.store, service
    engine.runtime = SimpleNamespace(operation_catalog=service.catalog)
    scope = CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
        source_baseline=service.artifacts.read(SYSTEM_ID, SCAN_ID).baseline,
        selected_operation_ids=[OPERATION_ID, second.operation_id], contract_revisions={OPERATION_ID: 0, second.operation_id: 1})
    handoff = SimpleNamespace(source_scopes=[scope], system_id=SYSTEM_ID)
    effective = {item.operation_id: item for item in engine._runtime_capabilities(handoff)}
    assert effective[OPERATION_ID].mutability == OperationMutability.READ_ONLY
    assert effective[second.operation_id].mutability == OperationMutability.UNKNOWN
    assert second.mutability == OperationMutability.READ_ONLY


@pytest.fixture
def shared_contract(tmp_path):
    """为契约和个人指针提供真实SQL事务，源码来自隔离目录，不连接业务环境。"""

    # SQLite只适配传输方言；作者、个人指针和事务回滚使用生产SQL服务。
    service = _service(tmp_path)
    base = service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 0)
    manifest = service.artifacts.read(SYSTEM_ID, SCAN_ID)
    database = PublicationDatabase()
    database.execute("ALTER TABLE ot_interface ADD latest_contract_revision INTEGER DEFAULT 0")
    database.execute("ALTER TABLE ot_scan ADD source_commit TEXT")
    database.execute("INSERT INTO ot_system(system_id) VALUES(%s)", (SYSTEM_ID,))
    database.execute("INSERT INTO ot_code_baseline(baseline_id,system_id) VALUES('base-contract',%s)", (SYSTEM_ID,))
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id,source_commit) VALUES(%s,'base-contract',%s,%s)", (SCAN_ID, SYSTEM_ID, base.source_commit))
    database.execute("INSERT INTO ot_interface(interface_id,system_id,scan_id,operation_id) VALUES(1,%s,%s,%s)", (SYSTEM_ID, SCAN_ID, OPERATION_ID))
    database.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json) VALUES(1,0,%s)", (base.model_dump_json(),))
    database.execute("INSERT INTO ot_baseline_interface(baseline_interface_id,baseline_id,operation_id,current_interface_id,current_contract_revision,availability) VALUES(1,'base-contract',%s,1,0,'AVAILABLE')", (OPERATION_ID,))
    store = KnowledgeTransactions(database)
    store.get_system = service.store.get_system
    store.root = tmp_path / "knowledge"
    service.store = store
    service.artifacts.metadata = database
    service.artifacts.read = Mock(return_value=manifest)
    service.contracts.metadata = database
    data = DataCapabilityService.__new__(DataCapabilityService)
    data.store, data.artifacts = store, service.artifacts
    data.cases = SimpleNamespace(operation_contracts=service)
    employee = AuthenticatedIdentity(EmployeeIdentity(user_id="employee-a", name="测试员工"), "cookie")
    with bind_authenticated_identity(employee):
        yield service, data, database
    database.connection.close()


@pytest.mark.parametrize("concurrent_change", [False, True])
def test_classification_draft_and_contract_commit_atomically(shared_contract, concurrent_change):
    """固定可见零版、作者和CAS；成功仅更新本人草稿，冲突回滚新契约与latest。"""

    service, data, database = shared_contract
    request = DataCapabilityPrepareRequest(kind="contract", goal="分析", operation_id=OPERATION_ID,
        baseline_id="base-contract", scan_id=SCAN_ID, contract_revision=0)
    scope, draft = data._contract_publication_start(SYSTEM_ID, request)
    publications = PublicationService(data.store)
    if concurrent_change:
        database.execute("UPDATE ot_interface_contract_version SET author_user_id='employee-a' WHERE revision=0")
        publications.save_interface_draft(scope, draft)
    try:
        with data.store.system_transaction(SYSTEM_ID):
            contract = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID,
                OperationContractSupplement(mutability="UNKNOWN", mutability_reason="无法确认外部副作用"), draft.contract_revision)
            publications.save_interface_draft(scope, draft.model_copy(update={"contract_revision": contract.contract_revision}))
    except IdempotencyConflictError:
        assert concurrent_change
    # 真正查询个人、他人和共享指针，而不以工具成功作为发布成功。
    latest = service.contracts.get_latest(SYSTEM_ID, SCAN_ID, OPERATION_ID)
    assert latest.contract_revision == (0 if concurrent_change else 1)
    assert publications.list_interfaces(scope)[0]["contract_revision"] == 0
    assert publications.list_interfaces(scope.model_copy(update={"user_id": "employee-b"}), "mine") == []
    if not concurrent_change:
        assert publications.list_interfaces(scope, "mine")[0]["contract_revision"] == 1
        assert database.fetch_one("SELECT author_user_id FROM ot_interface_contract_version WHERE revision=1")["author_user_id"] == scope.user_id


def _task_service(service, tmp_path):
    """将固定扫描契约装入真实数据任务服务，返回服务和由调用者关闭的任务池。"""

    # 只隔离扫描发现环节；任务保存、工具读写、分类注册表和草稿事务均走生产实现。
    tasks = LocalTaskManager(tmp_path / "tasks")
    service.catalog.derive.return_value[0].executable = True
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store, engine.artifacts, engine.operation_contracts = service.store, service.artifacts, service
    engine.runtime = SimpleNamespace(operation_catalog=service.catalog)
    engine.registries = CaseTemplateRegistryLoader()
    source_scope = CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
        source_baseline=service.artifacts.read(SYSTEM_ID, SCAN_ID).baseline, selected_operation_ids=[OPERATION_ID])
    engine._source_scopes = Mock(return_value=[source_scope])
    data = DataCapabilityService(service.store, service.artifacts, engine, tasks)
    return data, tasks


def test_native_contract_task_freezes_input_and_updates_personal_draft(shared_contract, tmp_path):
    """完整准备、读取、工具补充与结果回查固定同一版本，且其他员工不能复用请求进入任务。"""

    service, _, database = shared_contract
    data, tasks = _task_service(service, tmp_path)
    request = DataCapabilityPrepareRequest(kind="contract", goal="分析", operation_id=OPERATION_ID,
        baseline_id="base-contract", scan_id=SCAN_ID, contract_revision=0, request_id="native-classification-test",
        interaction_mode="native", execution_mode="generate_only")
    try:
        task = data.prepare(SYSTEM_ID, request)
        before = data.task_context(task.task_id)
        assert before["input_contract"]["contract_revision"] == 0 and before["contract"] is None
        assert data.prepare(SYSTEM_ID, request).task_id == task.task_id
        # 操作Schema由补充模型生成；工具的实际事务同时保存作者、个人引用和任务结果。
        tool = next(item for item in data.agent_tools(task.task_id) if item["name"] == "supplement_contract")
        assert "mutability" in tool["inputSchema"]["properties"]["supplement"]["properties"]
        after = data.call_agent_tool(task.task_id, "supplement_contract", {"expected_revision": 0,
            "supplement": {"mutability": "UNKNOWN", "mutability_reason": "下游实现不可见"}})
        assert after["contract"]["contract_revision"] == 1 and after["contract"]["mutability_analyzed"]
        assert after["runtime_function_registry"]["functions"][0]["read_only"] is False
        assert data._handoff(task.task_id).source_scopes[0].contract_revisions[OPERATION_ID] == 1
        assert database.fetch_one("SELECT current_contract_revision FROM ot_baseline_interface")["current_contract_revision"] == 0
        other = AuthenticatedIdentity(EmployeeIdentity(user_id="employee-b", name="另一测试员工"), "cookie")
        with bind_authenticated_identity(other), pytest.raises(ScopeViolationError, match="其他员工"):
            data.prepare(SYSTEM_ID, request)
    finally:
        tasks._executor.shutdown(wait=True)


def test_legacy_selected_contract_remains_zero_in_read_and_draft(shared_contract, tmp_path):
    """旧任务没有映射时，详情、运行目录和草稿保存均使用零版，不跟随后来发布的UNKNOWN。"""

    from opentest.domain.data_capabilities import DataCapabilityDefinition

    service, _, database = shared_contract
    data, tasks = _task_service(service, tmp_path)
    service.catalog.derive.return_value[0].mutability = OperationMutability.READ_ONLY
    request = DataCapabilityPrepareRequest(kind="contract", goal="分析", operation_id=OPERATION_ID,
        baseline_id="base-contract", scan_id=SCAN_ID, contract_revision=0, interaction_mode="native")
    try:
        task = data.prepare(SYSTEM_ID, request)
        legacy = data._handoff(task.task_id)
        legacy.source_scopes[0].contract_revisions = {}
        data.records.save_handoff(legacy)
        # 后来共享分类已经改变；旧任务缺映射的含义依然是原始扫描，而不是升级授权。
        service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID,
            OperationContractSupplement(mutability="UNKNOWN", mutability_reason="后来发现未知调用"), 0)
        database.execute("UPDATE ot_baseline_interface SET current_contract_revision=1")
        selected = data.call_agent_tool(task.task_id, "read_contract", {"source_system_id": SYSTEM_ID, "operation_id": OPERATION_ID})
        assert selected["contract"]["contract_revision"] == 0
        assert selected["runtime_function"]["read_only"]
        assert data._registry(data._handoff(task.task_id)).functions[0].read_only
        # 通过完整数据草稿引用该操作，覆盖另一条会为旧选项补建映射的路径。
        payload = json.loads((Path(__file__).parents[1] / "fixtures/data-capabilities/refund-supplement-report.json").read_text())
        for steps in (payload["query_steps"], payload["create_steps"], payload["verify_steps"]):
            for step in steps:
                if step["operation"] == "runtime_call":
                    step["function_id"] = OPERATION_ID
        definition = DataCapabilityDefinition.model_validate(payload)
        frozen = data._select_draft_operations(legacy, definition)
        assert frozen.source_scopes[0].contract_revisions[OPERATION_ID] == 0
    finally:
        tasks._executor.shutdown(wait=True)


def test_other_scan_personal_draft_does_not_hide_matching_published_revision(shared_contract):
    """个人旧扫描草稿保留时，固定扫描的数据任务仍能选择同扫描的共享契约。"""

    service, data, database = shared_contract
    base = service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 0)
    old = base.model_copy(update={"source_scan_id":"scan-older-source", "contract_revision":1})
    # 模拟同基准分批扫描留下的个人指针；测试不删除或改写该旧草稿。
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id,source_commit) VALUES('scan-older-source','base-contract',%s,%s)", (SYSTEM_ID, base.source_commit))
    database.execute("INSERT INTO ot_interface(interface_id,system_id,scan_id,operation_id) VALUES(2,%s,'scan-older-source',%s)", (SYSTEM_ID, OPERATION_ID))
    database.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json,author_user_id) VALUES(2,1,%s,'employee-a')", (old.model_dump_json(),))
    scope = PublicationScope(system_id=SYSTEM_ID, baseline_id="base-contract", user_id="employee-a")
    PublicationService(data.store).save_interface_draft(scope, InterfaceDraftUpdate(operation_id=OPERATION_ID,
        interface_id=2, contract_revision=1, expected_draft_revision=0, expected_publication_revision=0))
    source_scope = CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
        source_baseline=service.artifacts.read(SYSTEM_ID, SCAN_ID).baseline)
    assert data._visible_contract_revision(source_scope, OPERATION_ID) == 0
    assert database.fetch_one("SELECT interface_id FROM ot_interface_draft")["interface_id"] == 2


def test_candidate_index_uses_visible_revision_and_retains_unselected_entries(shared_contract):
    """未选接口仍可被发现，未发布分类不进入共享目录，已选接口保持原冻结修订。"""

    service, data, _ = shared_contract
    operation = service.catalog.derive.return_value[0]
    operation.executable = True
    scope = PublicationScope(system_id=SYSTEM_ID, baseline_id="base-contract", user_id="employee-a")
    publications = PublicationService(data.store)
    private = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID,
        OperationContractSupplement(mutability="UNKNOWN", mutability_reason="下游不可见"), 0)
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store, engine.operation_contracts = service.store, service
    engine.runtime = SimpleNamespace(operation_catalog=service.catalog)
    handoff = SimpleNamespace(system_id=SYSTEM_ID, source_scopes=[])
    # 存储latest已经是UNKNOWN，但可见指针仍为零版，不得提前撤销共享扫描分类。
    visible = publications.list_interface_summaries(scope)
    classified, _ = engine._classify_visible_candidates(handoff, [operation], visible)
    assert len(classified) == 1 and classified[0].mutability == OperationMutability.WRITE
    publications.save_interface_draft(scope, InterfaceDraftUpdate(operation_id=OPERATION_ID,
        interface_id=1, contract_revision=private.contract_revision, expected_draft_revision=0, expected_publication_revision=0))
    mine = visible + publications.list_interface_summaries(scope, "mine")
    classified, details = engine._classify_visible_candidates(handoff, [operation], mine)
    assert classified[0].mutability == OperationMutability.UNKNOWN
    assert details[OPERATION_ID]["mutability_analyzed"]
    handoff.source_scopes = [CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
        source_baseline=service.artifacts.read(SYSTEM_ID, SCAN_ID).baseline,
        selected_operation_ids=[OPERATION_ID], contract_revisions={OPERATION_ID: 0})]
    classified, _ = engine._classify_visible_candidates(handoff, [operation], mine)
    assert classified[0].mutability == OperationMutability.WRITE
