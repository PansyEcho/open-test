"""共享覆盖的环境隔离、员工可见性和未知业务结果不重放验收。"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time

import pytest

from opentest.adapters.coverage import CoverageArtifactReader, CoverageUnavailable, SkyeyeInstanceDiscovery
from opentest.adapters.coverage_store import CoverageMeasurementLease, CoverageStore
from opentest.application.auth import bind_authenticated_identity
from opentest.application.coverage_assistance import CoverageAssistanceService
from opentest.application.coverage_retry import CoverageRetryRequest, _require_settled_business, retry_coverage
from opentest.domain.auth import AuthenticatedIdentity, EmployeeIdentity
from opentest.domain.coverage import CoverageAnalysisResult, CoverageArtifactSelection, SkyeyeDiscoverySettings
from opentest.domain.coverage_workflow import CoverageEnhancement, CoverageMeasurement, CoverageRawCapture, CoverageReport, ReviewedCoverageGap, CoverageModelRun
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.publication import PublicationScope
from opentest.domain.shared_workspace import CaseSelection


def coverage_workflow() -> CoverageEnhancement:
    """构造属于员工甲、固定基准和UAT的失败增强，供可见性及重试共用。"""

    return CoverageEnhancement(enhancement_id="coverage-shared", task_id="task-" + "1" * 16,
        system_id="refund", operation_id="Api#query", base_generation_id="generation-fixed",
        source_scan_id="scan-fixed", source_commit="a" * 40, baseline_id="baseline-fixed",
        owner_user_id="employee-a", environment_id="uat", status="FAILED", stage="FINISHED",
        baseline_case_execution_id="execution-original",
        case_selection=[CaseSelection(case_id="case-fixed", generation_id="generation-fixed", variant_id="variant-fixed")])


def test_uat_discovery_requires_own_gateway_and_never_queries_qa() -> None:
    """UAT缺网关必须在任何网络调用前阻止，不能借用默认QA日志或实例。"""

    discovery = SkyeyeInstanceDiscovery()
    with patch.object(discovery, "_query") as query, pytest.raises(CoverageUnavailable) as error:
        discovery.discover(SkyeyeDiscoverySettings(app_id="same-system-app", token="test-only", environment="uat"), time.monotonic() + 10)
    assert error.value.reason_code == "SKYEYE_ENDPOINT_MISSING"
    query.assert_not_called()


def test_uat_archive_requires_explicit_environment_directory() -> None:
    """UAT归档缺配置返回独立原因，不能把war/qa当作UAT的实际包。"""

    config = CoverageArtifactSelection(app_uk="refund", environment="uat", archive_host="archive.invalid", archive_version="v1")
    with patch("opentest.adapters.coverage._read_network") as network, pytest.raises(CoverageUnavailable) as error:
        CoverageArtifactReader().prepare(config, "a" * 40, time.monotonic() + 10)
    assert error.value.reason_code == "ARCHIVE_ENVIRONMENT_MISSING"
    network.assert_not_called()


def test_measurement_lease_releases_exact_system_and_environment() -> None:
    """同一系统的QA/UAT使用不同锁身份，释放不会解开另一环境的窗口。"""

    connection, cursor = Mock(), Mock()
    connection.cursor.return_value = nullcontext(cursor)
    lease = CoverageMeasurementLease(connection, "refund", "uat")
    lease.release()
    assert cursor.execute.call_args.args[1] == ("refund", "uat")
    lease.release()
    connection.close.assert_called_once()


def test_retired_retention_entry_never_deletes_report_material() -> None:
    """旧维护入口还可能被调用，但永久保留规则不允许其删除材料或执行记录。"""

    metadata = Mock()
    CoverageStore(metadata).prune(coverage_workflow())
    metadata.execute.assert_not_called()


def test_cancelled_confirmation_creates_no_task_or_execution() -> None:
    """未确认部署的重试在读Case或创建任务之前停止，模拟用户取消弹框。"""

    app = Mock()
    scope = PublicationScope(system_id="refund", baseline_id="baseline-fixed", user_id="employee-a")
    request = CoverageRetryRequest(request_id="retry-00001", generation_id="generation-fixed", variant_id="variant-fixed", environment_id="uat")
    with pytest.raises(KnowledgeValidationError, match="先确认"):
        retry_coverage(app, scope, "case-fixed", request)
    app.tasks.create_business_record.assert_not_called()
    app.case_template_v4.prepare_execution.assert_not_called()
    app.store.system_transaction.assert_not_called()


def test_partial_result_with_unknown_write_is_not_replayed() -> None:
    """同批已有成功结果仍不能掩盖另一个超时请求；真实请求未完成则禁止重试。"""

    app = Mock()
    failed_write = SimpleNamespace(status="FAILED", execution_id="operation-timeout")
    app.case_template_v4.executions.get.return_value = SimpleNamespace(status="PARTIAL", variant_results=[
        SimpleNamespace(status="COMPLETED", operations=[]),
        SimpleNamespace(status="FAILED", operations=[failed_write])])
    app.operations.get_execution.return_value = SimpleNamespace(status="running")
    with pytest.raises(KnowledgeValidationError, match="结果未知"):
        _require_settled_business(app, coverage_workflow())
    app.operations.get_execution.assert_called_once_with("operation-timeout")


def test_assertion_failure_with_completed_calls_can_be_remeasured() -> None:
    """断言失败但业务调用已明确完成，可以在新部署确认后重新测量，不误判为未知写入。"""

    app = Mock()
    app.case_template_v4.executions.get.return_value = SimpleNamespace(status="PARTIAL", variant_results=[
        SimpleNamespace(status="PARTIAL", operations=[SimpleNamespace(status="COMPLETED")])])
    _require_settled_business(app, coverage_workflow())
    app.operations.get_execution.assert_not_called()


def test_retry_receipt_observes_existing_attempt_without_redispatch() -> None:
    """相同点击的网络重试只读取原attempt，即便已结束也不能重新执行业务。"""

    app = Mock()
    scope = PublicationScope(system_id="refund", baseline_id="baseline-fixed", user_id="employee-a")
    request = CoverageRetryRequest(request_id="retry-00001", generation_id="generation-fixed", variant_id="variant-fixed",
        environment_id="uat", deployment_confirmed=True)
    app.store.system_transaction.return_value = nullcontext()
    app.store.metadata.get_workflow.return_value = {"enhancement_id": "coverage-shared", "identity": {
        "scope": scope.model_dump(mode="json"), "case_id": "case-fixed", "request": request.model_dump(mode="json")}}
    app.coverage_assistance.records.get.return_value = coverage_workflow()
    assert retry_coverage(app, scope, "case-fixed", request).enhancement_id == "coverage-shared"
    app.case_template_v4.dispatch_execution.assert_not_called()
    app.coverage_assistance.schedule_analysis.assert_not_called()


def test_coverage_visibility_uses_employee_environment_and_every_measured_case() -> None:
    """作者也不能读取已被替代Case的聚合报告；未被替代时精确按员工和环境读取。"""

    service = object.__new__(CoverageAssistanceService)
    service.records, service.app = Mock(), Mock()
    workflow = coverage_workflow()
    service.records.for_generation.return_value = workflow
    service.app.publications.get_case.return_value = SimpleNamespace(generation_id="generation-fixed", variant=SimpleNamespace(variant_id="variant-fixed"))
    identity = AuthenticatedIdentity(EmployeeIdentity(user_id="employee-a", name="甲"), "cookie")
    with bind_authenticated_identity(identity):
        assert service._visible_workflow("refund", "generation-fixed", "uat") is workflow
        service.records.for_generation.assert_called_with("refund", "generation-fixed", "employee-a", "uat")
        # 当前指针已变化时，过去的owner身份不能使旧材料重新出现在页面。
        service.app.publications.get_case.side_effect = KnowledgeNotFoundError("replaced")
        assert service._visible_workflow("refund", "generation-fixed", "uat") is None


def test_coverage_query_cannot_display_sibling_case_measurement() -> None:
    """同Generation中的兄弟Case不能显示本项测量；关联筛选以后仍执行完整测量选集授权。"""

    service = object.__new__(CoverageAssistanceService)
    service.records, service.app = Mock(), Mock()
    measured = coverage_workflow()
    service.records.for_generation.return_value = measured
    service.app.publications.get_case.return_value = SimpleNamespace(generation_id="generation-fixed", variant=SimpleNamespace(variant_id="variant-fixed"))
    identity = AuthenticatedIdentity(EmployeeIdentity(user_id="employee-a", name="甲"), "cookie")
    with bind_authenticated_identity(identity):
        assert service._visible_workflow("refund", "generation-fixed", "uat", "case-sibling") is None
        service.records.for_generation.assert_called_with("refund", "generation-fixed", "employee-a", "uat", "case-sibling")
        assert service._visible_workflow("refund", "generation-fixed", "uat", "case-fixed") is measured


@pytest.mark.parametrize("creation_action", ["start", "continue"])
def test_created_supplement_without_dispatch_can_resume_after_busy_gate(creation_action) -> None:
    """创建回执不能冒充模型派发；排他任务结束后重试同child/request，真实草稿写回则只观察。"""

    from opentest.application.coverage_supplement import CoverageSupplement, GATE_BUSY

    supplement = object.__new__(CoverageSupplement)
    supplement.app, supplement.tasks = Mock(), Mock()
    task = SimpleNamespace(task_id="supplement-one", active_handoff_id="handoff-one", web_run_active=False,
        web_run_id="", web_run_requests=[], status="waiting_for_client", result={})
    supplement.tasks.get.return_value = task
    child = SimpleNamespace(thread_id="", turn_id="", request_receipts=[SimpleNamespace(action=creation_action)])
    supplement.app.case_template_v4.handoffs.get.return_value = child
    measured = coverage_workflow().model_copy(update={"supplement_task_id": task.task_id,
        "stage": "SUPPLEMENT_RUNNING", "status": "RUNNING", "reason_codes": [GATE_BUSY],
        "model_runs": [CoverageModelRun(role="SUPPLEMENT", task_id=task.task_id)]})
    supplement._busy, supplement._dispatch = Mock(return_value=False), Mock()
    supplement._observe(measured)
    supplement._dispatch.assert_called_once_with(measured)
    # 已有Agent修改的明确事实仍会阻止重复派发，不能把所有回执一律忽略。
    child.request_receipts.append(SimpleNamespace(action="revise"))
    assert supplement._has_dispatch_evidence(measured)


def retry_fixture() -> tuple[Mock, CoverageEnhancement, PublicationScope, CoverageRetryRequest]:
    """构造两条基线Case及已完成增强Case，原复测只选择增强产物中的一项，所有业务已明确终态。"""

    previous = coverage_workflow()
    previous.case_selection.append(CaseSelection(case_id="case-second", generation_id="generation-fixed", variant_id="variant-second"))
    previous.status = "PARTIAL"
    previous.enhanced_generation_id = "generation-enhanced"
    previous.verification_case_execution_id = "verification-original"
    previous.round_used = 1
    previous.supplement_task_id = "supplement-original"
    previous.model_runs = [CoverageModelRun(role="SUPPLEMENT", run_id="model-original", status="COMPLETED")]
    previous.gaps = [ReviewedCoverageGap(gap_id="gap-original", kind="METHOD", location={"class_name": "Order"},
        scope_reason="确定调用", before={"covered": 0, "missed": 1})]
    counts = {name: {"covered": 1, "missed": 1} for name in ("method", "line", "branch")}
    analysis = CoverageAnalysisResult(raw_counts=counts, scope_counts=counts, matched_class_count=1,
        uncomparable_class_count=0, scope_reason="固定方法范围", candidate_gap_count=1, deferred_gap_count=0)
    previous.baseline = CoverageMeasurement(case_execution_id=previous.baseline_case_execution_id, status="VALID", analysis=analysis)
    previous.verification = CoverageMeasurement(case_execution_id=previous.verification_case_execution_id, status="INVALID", reason_codes=["COVERAGE_ANALYSIS_FAILED"])
    enhanced_selection = CaseSelection(case_id="case-enhanced", generation_id="generation-enhanced", variant_id="variant-enhanced")
    scope = PublicationScope(system_id="refund", baseline_id="baseline-fixed", user_id="employee-a")
    request = CoverageRetryRequest(request_id="retry-current-1", generation_id="generation-enhanced", variant_id="variant-enhanced",
        environment_id="uat", view="mine", deployment_confirmed=True, retry_of=previous.enhancement_id)
    app = Mock()
    app.store.system_transaction.side_effect = lambda system_id: nullcontext()
    app.store.metadata.get_workflow.return_value = None
    app.store.metadata.fetch_one.return_value = None
    app.shared_baselines.store.get_baseline.return_value = SimpleNamespace(source_commit="a" * 40)
    visible = {("published", item.case_id): item for item in previous.case_selection}
    visible["mine", enhanced_selection.case_id] = enhanced_selection

    def require_case(current_scope, case_id, view):
        """仅返回被明确放入当前共享或个人视图的单项版本，其他ID模拟被替换。"""

        selected = visible.get((view, case_id))
        if selected is None:
            raise KnowledgeNotFoundError("当前视图不存在")
        return SimpleNamespace(generation_id=selected.generation_id, variant=SimpleNamespace(variant_id=selected.variant_id),
            source_scan_id="scan-fixed", operation_id="Api#query")

    app.publications.require_executable.side_effect = require_case
    app.publications.get_case.side_effect = require_case
    app.case_template_v4.generations.get.return_value = SimpleNamespace(generation_id="generation-enhanced", status="READY",
        owner_user_id="employee-a", baseline_id="baseline-fixed", system_id="refund", operation_id="Api#query", source_scan_id="scan-fixed", case_bindings=[
            SimpleNamespace(case_id="case-enhanced", variant_id="variant-enhanced"),
            SimpleNamespace(case_id="unselected-enhanced", variant_id="unselected-variant")])
    executions = {
        previous.baseline_case_execution_id: SimpleNamespace(status="COMPLETED", variant_results=[], generation_id="generation-fixed",
            environment_id="uat", selected_cases=previous.case_selection),
        previous.verification_case_execution_id: SimpleNamespace(status="COMPLETED", variant_results=[], generation_id="generation-enhanced",
            environment_id="uat", selected_cases=[enhanced_selection]),
    }
    app.case_template_v4.executions.get.side_effect = lambda system_id, execution_id: executions[execution_id]
    workflows = {previous.enhancement_id: previous}

    def create_workflow(workflow):
        """保存深拷贝模拟共享持久层，后续断言能发现重试是否意外修改原增强。"""

        workflows[workflow.enhancement_id] = workflow.model_copy(deep=True)
        return workflows[workflow.enhancement_id]

    app.coverage_assistance.records.get.side_effect = workflows.get
    app.coverage_assistance.records.create.side_effect = create_workflow
    app.coverage_assistance.records.save.side_effect = create_workflow
    raw = CoverageRawCapture(exec_artifact_id="exec-original", deployed_artifact_id="binary-original", source_artifact_id="source-original")
    app.coverage_assistance.records.report.return_value = CoverageReport(execution_id=previous.enhancement_id, system_id="refund",
        generation_id="generation-fixed", operation_id="Api#query", environment_id="uat", owner_user_id="employee-a",
        result={"baseline": raw, "verification": raw.model_copy(update={"exec_artifact_id": "verification-exec"})})
    app.case_template_v4.prepare_execution.return_value = SimpleNamespace(running=SimpleNamespace(execution_id="new-baseline-execution"))
    return app, previous, scope, request


def test_retry_partial_verification_reuses_both_materials_without_model_or_business() -> None:
    """基线有效、复测已有原始材料时只补复测分析，保留单轮增强和原多Case测量范围。"""

    app, previous, scope, request = retry_fixture()
    original = previous.model_dump(mode="json")
    resumed = retry_coverage(app, scope, "case-enhanced", request)
    assert resumed.stage == "VERIFICATION_ANALYZING"
    assert resumed.case_selection == previous.case_selection and len(resumed.case_selection) == 2
    assert resumed.enhanced_generation_id == "generation-enhanced" and resumed.round_used == 1
    assert resumed.gaps == previous.gaps and resumed.model_runs == previous.model_runs
    assert resumed.verification.analysis is None and resumed.verification.status == "VALID"
    app.coverage_assistance.schedule_analysis.assert_called_once_with(resumed.enhancement_id, "verification")
    app.coverage_assistance.resume_verification.assert_not_called()
    app.case_template_v4.prepare_execution.assert_not_called()
    assert previous.model_dump(mode="json") == original


def test_retry_missing_verification_material_only_resumes_exact_existing_enhanced_cases() -> None:
    """复测材料缺失时保留原复测执行ID供精确选择，只派发补验证，不再生成新的增强产物。"""

    app, previous, scope, request = retry_fixture()
    app.coverage_assistance.records.report.return_value.result.pop("verification")
    resumed = retry_coverage(app, scope, "case-enhanced", request)
    app.coverage_assistance.resume_verification.assert_called_once()
    assert app.coverage_assistance.resume_verification.call_args.args[0].verification_case_execution_id == "verification-original"
    assert resumed.enhanced_generation_id == previous.enhanced_generation_id and resumed.round_used == 1
    app.case_template_v4.prepare_execution.assert_not_called()
    app.coverage_assistance.schedule_analysis.assert_not_called()


def test_retry_missing_baseline_material_remeasures_original_full_selection() -> None:
    """即使从增强Case点击重试，缺失基线也必须重测原基线全集，再继续现有增强Case的复测。"""

    app, previous, scope, request = retry_fixture()
    app.coverage_assistance.records.report.return_value.result.pop("baseline")
    resumed = retry_coverage(app, scope, "case-enhanced", request)
    system_id, generation_id, command = app.case_template_v4.prepare_execution.call_args.args
    assert (system_id, generation_id) == ("refund", "generation-fixed")
    assert command.selected_cases == previous.case_selection and len(command.selected_cases) == 2
    assert resumed.stage == "BASELINE_EXECUTING" and resumed.enhanced_generation_id == "generation-enhanced"
    assert app.coverage_assistance.records.save_report.call_args.args[0].result.keys() == {"verification"}
    app.case_template_v4.dispatch_execution.assert_called_once()
    app.coverage_assistance.resume_verification.assert_not_called()


def test_retry_rejects_one_replaced_case_in_original_aggregate() -> None:
    """多Case原测量中任何一项被替换都会阻止复用，不能只检查点击的那个Case。"""

    app, _, scope, request = retry_fixture()
    original_lookup = app.publications.require_executable.side_effect

    def current_only(current_scope, case_id, view):
        """模拟第二条原Case已经发布新版本，其他点击和增强内容仍然可见。"""

        if case_id == "case-second":
            raise KnowledgeNotFoundError("被替换")
        return original_lookup(current_scope, case_id, view)

    app.publications.require_executable.side_effect = current_only
    with pytest.raises(KnowledgeValidationError, match="已被替换"):
        retry_coverage(app, scope, "case-enhanced", request)
    app.coverage_assistance.records.create.assert_not_called()
    app.case_template_v4.prepare_execution.assert_not_called()


@pytest.mark.parametrize("status", ["VALID", "PENDING"])
def test_partial_retry_requires_explicit_failed_verification(status) -> None:
    """一般PARTIAL不能被当成覆盖复测失败；只有明确INVALID/SKIPPED才能人工补验证。"""

    app, previous, scope, request = retry_fixture()
    previous.verification.status = status
    with pytest.raises(KnowledgeValidationError, match="只有失败或跳过"):
        retry_coverage(app, scope, "case-enhanced", request)
    app.coverage_assistance.records.create.assert_not_called()


def test_retry_same_root_allows_only_one_active_attempt() -> None:
    """原根已有活动重试时不另开第二次测量或模型任务，避免两次reset相互污染。"""

    app, _, scope, request = retry_fixture()
    app.store.metadata.fetch_one.return_value = {"record_id": "coverage-already-running"}
    with pytest.raises(KnowledgeValidationError, match="正在执行的重试"):
        retry_coverage(app, scope, "case-enhanced", request)
    app.case_template_v4.prepare_execution.assert_not_called()
    app.coverage_assistance.records.create.assert_not_called()


def test_retry_refuses_click_outside_original_base_and_verification_sets() -> None:
    """同一增强产物的另一个未测Case也不能冒充原集合的重试入口。"""

    app, _, scope, request = retry_fixture()
    original_lookup = app.publications.require_executable.side_effect

    def include_unrelated(current_scope, case_id, view):
        """给点击项提供当前可见版本，同时保留原集合中的正常Case。"""

        if case_id == "unselected-enhanced" and view == "mine":
            return SimpleNamespace(generation_id="generation-enhanced", variant=SimpleNamespace(variant_id="unselected-variant"),
                operation_id="Api#query", source_scan_id="scan-fixed")
        return original_lookup(current_scope, case_id, view)

    app.publications.require_executable.side_effect = include_unrelated
    request = request.model_copy(update={"variant_id": "unselected-variant"})
    with pytest.raises(ScopeViolationError, match="不属于原增强"):
        retry_coverage(app, scope, "unselected-enhanced", request)
    app.coverage_assistance.records.create.assert_not_called()


def test_resume_verification_dispatches_saved_subset_without_other_enhanced_variants() -> None:
    """接上实际复测服务后仍只执行原测量的一条增强Case，不扩大到整个Generation。"""

    app, _, scope, request = retry_fixture()
    app.coverage_assistance.records.report.return_value.result.pop("verification")
    service = object.__new__(CoverageAssistanceService)
    service.app, service.records = app, app.coverage_assistance.records
    service.finish, service.schedule_analysis = Mock(), Mock()
    app.coverage_assistance.resume_verification.side_effect = service.resume_verification
    resumed = retry_coverage(app, scope, "case-enhanced", request)
    _, generation_id, command = app.case_template_v4.prepare_execution.call_args.args
    assert generation_id == "generation-enhanced"
    assert [(item.case_id, item.variant_id) for item in command.selected_cases] == [("case-enhanced", "variant-enhanced")]
    assert resumed.stage == "VERIFICATION_EXECUTING"
    app.case_template_v4.dispatch_execution.assert_called_once()
    service.finish.assert_not_called()


def test_remeasured_baseline_continues_saved_verification_analysis_without_new_model() -> None:
    """基线重新测量完成后，实际分析服务继续原复测包分析，保留已有缺口处置和模型运行。"""

    app, previous, scope, request = retry_fixture()
    app.coverage_assistance.records.report.return_value.result.pop("baseline")
    resumed = retry_coverage(app, scope, "case-enhanced", request)
    resumed.stage = "BASELINE_ANALYZING"
    app.coverage_assistance.records.save(resumed)
    service = object.__new__(CoverageAssistanceService)
    service.app, service.records = app, app.coverage_assistance.records
    service._analysis_owner_current = Mock(return_value=True)
    service._calculate_analysis = Mock(return_value=previous.baseline.analysis)
    service.advance, service.schedule_analysis, service.finish = Mock(), Mock(), Mock()
    service._analyze(resumed.enhancement_id)
    saved = service.records.get(resumed.enhancement_id)
    assert saved.stage == "VERIFICATION_ANALYZING" and saved.gaps == previous.gaps and saved.model_runs == previous.model_runs
    service.schedule_analysis.assert_called_once_with(saved.enhancement_id, "verification")
    service.advance.assert_not_called()
    assert app.case_template_v4.dispatch_execution.call_count == 1
