"""离线验证Case知识准入与非交互失败，不连接共享数据库、模型或业务服务。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application import case_template_v4
from opentest.application.auth import bind_authenticated_identity
from opentest.application.foundation import OpenTestApplication
from opentest.application.publication import PublicationService
from opentest.application.tasks import LocalTaskManager
from opentest.application.web_generation import WebGenerationService
from opentest.domain.auth import AuthenticatedIdentity, EmployeeIdentity
from opentest.domain.case_template_v4 import CaseTemplateGenerationStartRequest
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import KnowledgeNode, KnowledgeNodeKind, KnowledgeQuestion, ScanManifest, TaskRecord, TaskStatus, utc_now
from opentest.domain.shared_workspace import InterfaceKnowledgeBundle, InterfaceKnowledgeRef
from test_case_template_v4_revision import OPERATION_ID, SYSTEM_ID, _compiled, _contract, _handoff, _service


def _fixed_knowledge(narrative="absent"):
    """返回固定READY契约，按narrative携带不同历史长文；长文不决定业务可用性。"""

    contract = _contract()
    contract.operation_summary = "取消退票订单"
    content = {"system_id": SYSTEM_ID, "operation_id": OPERATION_ID, "scan_id": "scan-case-revision",
        "contract": contract.model_dump(), "knowledge": None}
    # 同一契约覆盖缺失、空白、迁移占位及正常正文，防止重新把长文当成生成前提。
    if narrative != "absent":
        node = KnowledgeNode(node_id="interface:1", system_id=SYSTEM_ID, kind=KnowledgeNodeKind.FACADE,
            title="取消入口", metadata={"migration_requires_review": True} if narrative == "migrated" else {})
        bundle = InterfaceKnowledgeBundle(nodes=[node], bodies={node.node_id: "" if narrative == "empty" else "历史实现分析"})
        content["knowledge"] = bundle.model_dump()
    return content


def _install_publications(monkeypatch, narrative="absent"):
    """保留真实独立契约校验，只替换固定版本读取，返回可观察的存储。"""

    publications = object.__new__(PublicationService)
    publications.store = SimpleNamespace(contract=Mock(return_value=_fixed_knowledge(narrative)))
    monkeypatch.setattr("opentest.application.case_template_v4.PublicationService", Mock(return_value=publications))
    return publications.store


@pytest.mark.parametrize("narrative", ["absent", "empty", "migrated", "complete"])
@pytest.mark.parametrize("execution_mode", ["generate_only", "generate_and_verify"])
def test_shared_start_uses_independent_contract_without_legacy_narrative(tmp_path, monkeypatch, narrative, execution_mode):
    """两种生成方式都能仅凭固定READY契约准备任务，旧正文形态不改变准入。"""

    service, handoffs, _ = _service(tmp_path, _compiled())
    stored = _install_publications(monkeypatch, narrative)
    fixed = _handoff(tmp_path)
    manifest = ScanManifest(scan_id=fixed.source_scan_id, system_id=SYSTEM_ID, baseline=fixed.source_scopes[0].source_baseline)
    manifest.baseline.commit = "a" * 40
    service.artifacts.read = Mock(return_value=manifest)
    service._require_selected_scan_materials = Mock()
    service._resolve_entry = Mock(return_value=SimpleNamespace(entry_id=OPERATION_ID))
    service._input_contract = Mock(return_value=_contract())
    service._source_scopes = Mock(return_value=fixed.source_scopes)
    request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, baseline_id="baseline-current",
        source_revision=manifest.baseline.commit, request_id="start-independent-contract", execution_mode=execution_mode)
    reference = InterfaceKnowledgeRef(baseline_interface_id=1, interface_id=1, contract_revision=0)
    identity = AuthenticatedIdentity(EmployeeIdentity(user_id="employee-a", name="测试员工"), "user_bearer")

    # 真实start保存原固定引用，不启动额外知识访谈，也不改写历史正文。
    with bind_authenticated_identity(identity):
        handoff = service.start(SYSTEM_ID, request, manifest.scan_id, reference)
        assert handoffs.get(handoff.handoff_id).knowledge_dependencies == [reference]
        assert handoff.execution_mode == execution_mode
    stored.contract.assert_called_once_with(1, 0)


@pytest.mark.parametrize("narrative", ["absent", "empty", "migrated"])
@pytest.mark.parametrize("already_selected", [False, True])
def test_dependency_selection_accepts_independent_contract(tmp_path, monkeypatch, narrative, already_selected):
    """首次选择和旧任务依赖读取均不要求长文，仍固定可见契约及扫描。"""

    service, _, _ = _service(tmp_path, _compiled())
    stored = _install_publications(monkeypatch, narrative)
    reference = InterfaceKnowledgeRef(baseline_interface_id=1, interface_id=1, contract_revision=0)
    handoff = _handoff(tmp_path).model_copy(update={"baseline_id": "baseline-current", "owner_user_id": "employee-a",
        "knowledge_dependencies": [reference] if already_selected else []})
    provider = SimpleNamespace(system_id=SYSTEM_ID, operation_id=OPERATION_ID, source_scan_id="scan-case-revision")
    service.store.metadata = SimpleNamespace(fetch_one=Mock(return_value={"baseline_id": "baseline-current"}))
    publications = case_template_v4.PublicationService()
    publications.list_interface_summaries = Mock(return_value=[{"operation_id": OPERATION_ID,
        "baseline_interface_id": 1, "interface_id": 1, "contract_revision": 0, "status": "READY"}])

    # 真实选择逻辑返回同一provider与契约；跨员工/基准目录仍通过PublicationScope读取。
    selected, selected_reference, contract = service._visible_dependency_knowledge(handoff, provider)
    assert selected is provider and selected_reference == reference
    assert contract.operation_summary == "取消退票订单"
    assert stored.contract.call_count == 1
    if not already_selected:
        scope, view = publications.list_interface_summaries.call_args.args
        assert (scope.user_id, scope.baseline_id, view) == ("employee-a", "baseline-current", "published")


def _web_service(tmp_path, operation="case-generation"):
    """组合真实任务存储与Case模型，隔离执行器和网络，返回网页服务、任务及上下文。"""

    tasks = LocalTaskManager(tmp_path / "tasks")
    service, _, _ = _service(tmp_path / "handoffs", _compiled())
    handoff = _handoff(tmp_path).model_copy(update={"questions": [KnowledgeQuestion(
        question_id="dependency-missing", system_id=SYSTEM_ID, source="case_template", title="依赖缺口",
        detail="queryList 请求参数类型未解析", affected_node_ids=[], affected_target_ids=[OPERATION_ID])]})
    task = TaskRecord(task_id="task-1234567890abcdef", system_id=SYSTEM_ID, operation=operation,
        target_id=OPERATION_ID, trace_id="case-blocker-test", status=TaskStatus.WAITING_FOR_INPUT,
        ended_at=utc_now(), result={"request_id": "prepare-case-blocker"})
    tasks.create_business_record(task)
    context = {"handoff": handoff, "questions": handoff.questions, "revision": 0, "generation": None}
    application = SimpleNamespace(tasks=tasks, knowledge_root=tmp_path, agent_runner=Mock(),
        case_template_v4=service, get_task_context=Mock(return_value=context))
    # 不运行模型；任务幂等记录和锁仍走真实存储，检查启动之前的准入和错误持久化。
    tasks._executor.submit = Mock()
    tasks._reserve_exclusive = Mock()
    return WebGenerationService(application), task, context


@pytest.mark.parametrize("operation,expected", [("case-generation", TaskStatus.FAILED), ("knowledge-generation", TaskStatus.WAITING_FOR_INPUT)])
def test_case_blockers_fail_while_knowledge_interviews_keep_questions(tmp_path, operation, expected):
    """Case开放诊断落为失败并保存原因；非Case知识访谈继续保持原等待回答语义。"""

    service, task, context = _web_service(tmp_path, operation)
    try:
        # 同一问题模型仅按业务任务种类切换投影，保护知识访谈原有行为。
        service._settle(task.task_id, "")
        settled = service.tasks.get(task.task_id)
        assert settled.status == expected
        assert ("queryList" in settled.error) == (operation == "case-generation")
        assert context["questions"][0].status == "open"
    finally:
        service.tasks.close()


@pytest.mark.parametrize("has_artifact", [False, True])
def test_case_partial_requires_readable_formal_artifact(tmp_path, has_artifact):
    """仅Task自述PARTIAL不够，真实可回读成果存在时才能保留部分完成。"""

    service, task, context = _web_service(tmp_path)
    try:
        # 持久状态可能来自旧版本，必须结合当前可读取产物判断成功范围。
        service.tasks.save_business_record(task.model_copy(update={"status": TaskStatus.PARTIAL}))
        context["generation"] = SimpleNamespace(generation_id="published-generation") if has_artifact else None
        service._settle(task.task_id, "")
        assert service.tasks.get(task.task_id).status == (TaskStatus.PARTIAL if has_artifact else TaskStatus.FAILED)
    finally:
        service.tasks.close()


def test_old_waiting_case_can_retry_without_answer_and_same_request_is_not_replayed(tmp_path):
    """旧Case诊断不阻止显式重试；相同运行request只提交一次Agent，不自动重放业务调用。"""

    service, task, context = _web_service(tmp_path)
    try:
        # 用户显式重试允许保留开放诊断，但相同请求不能再次调度执行器。
        service.start(task.task_id, "retry-case-once", 0)
        service.start(task.task_id, "retry-case-once", 0)
        assert service.tasks.get(task.task_id).status == TaskStatus.RUNNING
        service.tasks._executor.submit.assert_called_once()
        assert context["questions"][0].status == "open"
    finally:
        service.tasks.close()


@pytest.mark.parametrize("narrative", ["absent", "migrated"])
def test_old_case_retry_accepts_fixed_contract_without_narrative(tmp_path, monkeypatch, narrative):
    """旧任务重试可使用原READY契约，不为补长文重扫、不替换引用。"""

    service, task, context = _web_service(tmp_path)
    _install_publications(monkeypatch, narrative)
    reference = InterfaceKnowledgeRef(baseline_interface_id=1, interface_id=1, contract_revision=0)
    context["handoff"].baseline_id = "baseline-current"
    context["handoff"].knowledge_dependencies = [reference]
    try:
        # 开放诊断不要求用户答复；重试仍进入已有执行器且保留原契约版本。
        service.start(task.task_id, "retry-independent-contract", 0)
        assert service.tasks.get(task.task_id).status == TaskStatus.RUNNING
        service.tasks._executor.submit.assert_called_once()
        assert context["handoff"].knowledge_dependencies == [reference]
    finally:
        service.tasks.close()


@pytest.mark.parametrize("invalid_contract", ["missing", "blocked", "wrong_operation", "wrong_scan"])
def test_old_case_retry_rejects_unusable_fixed_contract(tmp_path, monkeypatch, invalid_contract):
    """取消长文门禁不放宽真实契约缺失、阻断及身份错误；失败不启动Agent。"""

    service, task, context = _web_service(tmp_path)
    stored = _install_publications(monkeypatch)
    content = _fixed_knowledge()
    # 每个错误都属于实际契约身份或可用性，独立于旧知识材料。
    if invalid_contract == "missing":
        content = None
    elif invalid_contract == "blocked":
        content["contract"].update(status="BLOCKED", blocked_reason="请求类型未解析")
    elif invalid_contract == "wrong_operation":
        content["contract"]["target_id"] = "facade:Other#cancel"
    else:
        content["contract"]["source_scan_id"] = "another-scan"
    stored.contract.return_value = content
    context["handoff"].baseline_id = "baseline-current"
    context["handoff"].knowledge_dependencies = [InterfaceKnowledgeRef(baseline_interface_id=1, interface_id=1, contract_revision=0)]
    try:
        with pytest.raises(KnowledgeValidationError, match="固定接口契约不可用"):
            service.start(task.task_id, "retry-invalid-contract", 0)
        saved = service.tasks.get(task.task_id)
        assert saved.status == TaskStatus.FAILED and "固定接口契约不可用" in saved.error
        service.tasks._executor.submit.assert_not_called()
        service.tasks._reserve_exclusive.assert_not_called()
    finally:
        service.tasks.close()


@pytest.mark.parametrize("web_active", [False, True])
def test_case_task_preserves_active_run_or_projects_diagnostic_failure(tmp_path, web_active):
    """Case开放缺口保留诊断；后台仍运行时继续修正，否则失败而非等待用户。"""

    service, task, context = _web_service(tmp_path)
    application = object.__new__(OpenTestApplication)
    application.tasks = service.tasks
    application.native_task_instruction = Mock(return_value="继续当前Case")
    application.tasks.save_business_record(task.model_copy(update={"web_run_active": web_active}))
    handoff = context["handoff"].model_copy(update={"task_id": task.task_id, "status": "WAITING_FOR_INPUT"})
    try:
        # 兼容读取旧等待状态并保留诊断数量，不用用户答案伪造材料修复。
        projected = application._sync_case_task(handoff)
        assert projected.status == (TaskStatus.RUNNING if web_active else TaskStatus.FAILED)
        assert ("queryList" in projected.error) == (not web_active)
        assert (projected.ended_at is None) == web_active
        assert projected.result["open_question_count"] == 1
    finally:
        service.tasks.close()
