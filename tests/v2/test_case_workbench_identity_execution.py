"""验证Case来源区分、真实时间和逐项结果持久化，不访问真实业务或修改旧测试。"""

from __future__ import annotations

from types import SimpleNamespace
import zlib
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from opentest.adapters.case_template_v4_store import CaseGenerationExecutionStoreV4, CaseTemplateGenerationStoreV4
from opentest.adapters.mysql_metadata import decode_json
from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4
from opentest.application.case_template_v4 import CaseTemplateV4Service
from opentest.domain.case_template_v4 import (
    CaseExecutionProgressV4, CaseGenerationExecutionV4, CaseVariantExecutionV4,
    CaseTemplateDraftRevisionRequest, CaseTemplatePublicationRequest, CaseTemplateValidationIssue,
    DslValueSource, RuntimeFunctionRegistry,
)
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError, MetadataConnectionError, ScopeViolationError
from opentest.domain.models import utc_now
from opentest.domain.shared_workspace import CaseItemBinding, CaseSelection, CoverageCaseSeedBinding
from test_case_template_v4 import _create_order_generation, _CreateOrderCleanupOperationService
from test_case_template_v4_revision import _compiled, _handoff, _service
from test_mysql_metadata import shared_workspace_pair


def coverage_scenario(tmp_path):
    """建立有固定三键来源的单个覆盖种子，返回服务、handoff、原产物和新Variant供隔离测试。"""

    # 使用现有严格DSL夹具，只有服务端映射是本次新增契约，不模拟真实发布写入。
    original = _create_order_generation()
    original_variant = original.variants[0]
    original = original.model_copy(update={"case_bindings": [CaseItemBinding(
        case_id="case-original", variant_id=original_variant.variant_id)]})
    source = CaseSelection(case_id="case-original", generation_id=original.generation_id,
                           variant_id=original_variant.variant_id)
    template = original.submission.case_templates[0].model_copy(update={"template_id": "coverage-base-1"})
    submission = original.submission.model_copy(update={"case_templates": [template]})
    variant = original_variant.model_copy(update={"template_id": template.template_id,
        "variant_id": "case-variant-v4-" + "1" * 20})
    handoff = _handoff(tmp_path).model_copy(update={"system_id": original.system_id,
        "entry_id": original.operation_id, "baseline_id": "baseline-one", "owner_user_id": "employee-a",
        "draft_submission": submission, "draft_variants": [variant], "seeded_case_selection": [source],
        "coverage_seed_bindings": [CoverageCaseSeedBinding(template_id=template.template_id, source_case=source)]})
    service = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    service.generations = SimpleNamespace(get=Mock(return_value=original))
    service._runtime_capabilities = Mock(return_value=[])
    service.handoffs = SimpleNamespace(write=Mock())
    service.store = Mock()
    return service, handoff, original, variant


def execution_record(system_id="refund-core"):
    """构造两条精确选择的新执行；system_id只控制测试归属，起止时间保持未发生。"""

    generation_id = "case-template-generation-" + "5" * 20
    selections = [CaseSelection(case_id=f"case-{index}", generation_id=generation_id,
                  variant_id="case-variant-v4-" + str(index) * 20) for index in (1, 2)]
    return CaseGenerationExecutionV4(execution_id="case-generation-execution-" + "4" * 20,
        generation_id=generation_id, system_id=system_id, environment_id="qa", status="RUNNING",
        selected_cases=selections)


def test_old_binding_and_execution_keep_unknown_origin_and_times():
    """旧记录可读且不以登记时间冒充执行时间，不将历史同名Case推断为基础生成。"""

    binding = CaseItemBinding(case_id="case-old", variant_id="variant-old")
    record = execution_record()
    assert binding.origin_kind == "UNKNOWN" and binding.source_case is None
    assert record.started_at is None and record.ended_at is None
    assert record.variant_summaries == []


@pytest.mark.parametrize("edit", ["title", "assertion", "request"])
def test_seed_origin_uses_runtime_content_and_keeps_source(tmp_path, edit):
    """标题变化仍为复测；断言或请求变化明确为调整，三键来源始终不追随标题。"""

    service, handoff, original, variant = coverage_scenario(tmp_path)
    template = handoff.draft_submission.case_templates[0].model_copy(deep=True)
    template.title = "相同业务名称的显示修订"
    if edit == "assertion":
        template.oracles[0].assertions[0].expected = DslValueSource(kind="literal", value=False)
    elif edit == "request":
        template.request_bindings[0].source = DslValueSource(kind="literal", value="DIFFERENT-REQUEST")
        variant = variant.model_copy(update={"request_values": {"clientRequestId": "DIFFERENT-REQUEST"}})
    submission = handoff.draft_submission.model_copy(update={"case_templates": [template]})
    origins, issues = service._coverage_seed_origins(handoff, submission, [variant])
    assert issues == []
    assert origins[variant.variant_id][0] == ("COVERAGE_REUSED" if edit == "title" else "COVERAGE_ADJUSTED")
    assert origins[variant.variant_id][1].generation_id == original.generation_id


def test_parameter_expansion_preserves_only_one_original_scenario(tmp_path):
    """同模板参数展开只把唯一原参数归为复测，其他参数保留为覆盖新增身份。"""

    service, handoff, _original, variant = coverage_scenario(tmp_path)
    template = handoff.draft_submission.case_templates[0].model_copy(deep=True)
    template.request_bindings[0].source = DslValueSource(kind="parameter", name="request_key")
    submission = handoff.draft_submission.model_copy(update={"case_templates": [template]})
    base = variant.model_copy(update={"parameter_values": {"request_key": "OPENTEST-CREATE-1"}})
    extra = base.model_copy(update={"variant_id": "case-variant-v4-" + "2" * 20,
        "parameter_values": {"request_key": "EXTRA"}, "request_values": {"clientRequestId": "EXTRA"}})
    origins, issues = service._coverage_seed_origins(handoff, submission, [base, extra])
    assert issues == []
    assert list(origins) == [base.variant_id]
    assert origins[base.variant_id][0] == "COVERAGE_REUSED"


@pytest.mark.parametrize("change", ["deleted", "renamed", "ambiguous", "multiple_adjustments"])
def test_missing_or_ambiguous_seed_requires_draft_correction(tmp_path, change):
    """删除改名或不能唯一定位原参数时不准以完整/部分发布绕过基础复测集合。"""

    service, handoff, _original, variant = coverage_scenario(tmp_path)
    candidates = [variant]
    if change == "deleted":
        candidates = []
    elif change == "renamed":
        candidates = [variant.model_copy(update={"template_id": "renamed-seed"})]
    else:
        candidates.append(variant.model_copy(update={"variant_id": "case-variant-v4-" + "2" * 20}))
        if change == "multiple_adjustments":
            candidates = [item.model_copy(update={"request_values": {"clientRequestId": "CHANGED"}}) for item in candidates]
    _origins, issues = service._coverage_seed_origins(handoff, handoff.draft_submission, candidates)
    assert [item.code for item in issues] == ["COVERAGE_SEED_IDENTITY_LOST"]
    invalid = handoff.model_copy(update={"validation_issues": issues, "draft_variants": candidates})
    assert service._allowed_publication_modes(invalid) == []


def test_freezing_keeps_independent_same_titles_and_old_unknown_sources(tmp_path, monkeypatch):
    """同名独立生成不合并；覆盖复测保留独立ID；旧映射缺失不按coverage前缀猜来源。"""

    service, seeded, _original, variant = coverage_scenario(tmp_path)
    monkeypatch.setattr("opentest.application.case_template_v4.PublicationService", Mock())
    service._used_case_operations = Mock(return_value={(seeded.system_id, seeded.entry_id)})
    independent = seeded.model_copy(update={"seeded_case_selection": [], "coverage_seed_bindings": []})
    first = service._freeze_case_bindings(independent, [variant]).case_bindings[0]
    second = service._freeze_case_bindings(independent, [variant]).case_bindings[0]
    assert first.case_id != second.case_id
    assert first.origin_kind == second.origin_kind == "GENERATED"
    covered = service._freeze_case_bindings(seeded, [variant]).case_bindings[0]
    assert covered.case_id != "case-original" and covered.origin_kind == "COVERAGE_REUSED"
    assert covered.source_case == seeded.seeded_case_selection[0]
    historical = seeded.model_copy(update={"coverage_seed_bindings": []})
    old = service._freeze_case_bindings(historical, [variant]).case_bindings[0]
    assert old.origin_kind == "UNKNOWN" and old.source_case is None
    # 旧预留身份恢复时不补造来源，避免升级前已写Generation的内容比较出现漂移。
    reserved = independent.model_copy(update={"case_bindings": [CaseItemBinding(
        case_id="case-reserved", variant_id=variant.variant_id)]})
    recovered = service._freeze_case_bindings(reserved, [variant]).case_bindings[0]
    assert recovered.case_id == "case-reserved" and recovered.origin_kind == "UNKNOWN"


@pytest.mark.parametrize("shared", [False, True])
def test_execution_updates_merge_completed_facts_and_never_revive_terminal(tmp_path, shared):
    """旧RUNNING副本及异常收尾不能抹掉先前Case；终态后迟到结果也不能改变结论或时间。"""

    metadata = shared_workspace_pair(tmp_path)[0].metadata if shared else None
    store = CaseGenerationExecutionStoreV4(tmp_path, metadata)
    pending = store.create(execution_record())
    started = store.update(pending.model_copy(update={"started_at": utc_now()}))
    first = CaseVariantExecutionV4(variant_id=started.selected_cases[0].variant_id, status="COMPLETED",
        started_at=utc_now(), ended_at=utc_now())
    store.update(started.model_copy(update={"variant_results": [first]}))
    second = CaseVariantExecutionV4(variant_id=started.selected_cases[1].variant_id,
        status="PARTIAL", failure_kind="BEHAVIOR_DIFF", started_at=utc_now(), ended_at=utc_now())
    incremental = store.update(started.model_copy(update={"variant_results": [second]}))
    assert incremental.variant_results == [first, second]
    assert [item.outcome for item in incremental.variant_summaries] == ["PASSED", "ASSERTION_FAILED"]
    failed = store.update(started.model_copy(update={"status": "FAILED", "safe_error": "interrupted"}))
    assert failed.variant_results == [first, second] and failed.ended_at is not None
    late = store.update(started.model_copy(update={"status": "PASSED", "variant_results": []}))
    assert late == failed
    assert store.update_progress(started, CaseExecutionProgressV4(
        variant_id=first.variant_id, phase="TARGET")) is False


def test_shared_phase_writes_only_summary_and_checks_owner(tmp_path):
    """真实阶段更新不重压报告，详情能看新阶段；不同工作台和员工不能写入该执行。"""

    first, second = shared_workspace_pair(tmp_path)
    store = CaseGenerationExecutionStoreV4(tmp_path, first.metadata)
    running = store.create(execution_record())
    query = "SELECT payload_gzip,summary_json FROM ot_execution WHERE execution_id=%s"
    before = first.metadata.fetch_one(query, (running.execution_id,))
    event = CaseExecutionProgressV4(variant_id=running.selected_cases[0].variant_id,
                                  phase="DATA", started_at=utc_now())
    assert store.update_progress(running, event) is True
    after = first.metadata.fetch_one(query, (running.execution_id,))
    assert before["payload_gzip"] == after["payload_gzip"]
    assert decode_json(after["summary_json"])["current_phase"] == "DATA"
    detail = store.get(running.system_id, running.execution_id)
    assert detail.current_variant_id == event.variant_id and detail.current_variant_started_at == event.started_at
    foreign = CaseGenerationExecutionStoreV4(tmp_path, second.metadata)
    with pytest.raises(ScopeViolationError):
        foreign.update_progress(running, event)
    with pytest.raises(ScopeViolationError):
        store.update_progress(running.model_copy(update={"owner_user_id": "someone-else"}), event)
    with pytest.raises(ScopeViolationError):
        store.update(running.model_copy(update={"selected_cases": []}))


def test_executor_persists_first_case_before_starting_second(tmp_path):
    """实际执行器串行回调先保存首项，再派发第二项；每项有真实起止且不启用历史Cleanup。"""

    generation = _create_order_generation()
    second = generation.variants[0].model_copy(update={"variant_id": "case-variant-v4-" + "e" * 20, "ordinal": 2})
    generation = generation.model_copy(update={"variants": [generation.variants[0], second]})
    running = execution_record(generation.system_id).model_copy(update={"generation_id": generation.generation_id,
        "selected_cases": [CaseSelection(case_id=f"case-{index}", generation_id=generation.generation_id,
                           variant_id=item.variant_id) for index, item in enumerate(generation.variants)]})
    service = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    service.executions = CaseGenerationExecutionStoreV4(tmp_path)
    service.executions.create(running)
    events = []

    def record_progress(event):
        """检查第二项开始时第一项已可读取，然后调用真实服务回调保存该阶段或结果。"""

        if event.variant_id == second.variant_id and event.phase == "DATA":
            saved = service.executions.get(running.system_id, running.execution_id)
            assert len(saved.variant_results) == 1
        service._record_execution_progress(running, event)
        events.append(event)

    operations = _CreateOrderCleanupOperationService()
    results = CaseTemplateExecutorV4(operations).execute(running.execution_id, generation,
        RuntimeFunctionRegistry(functions=[]), "qa", record_progress)
    assert len(results) == 2 and all(item.started_at <= item.ended_at for item in results)
    assert [event.phase for event in events] == ["DATA", "TARGET", "ORACLE", ""] * 2
    assert all(operation.phase != "CLEANUP" for item in results for operation in item.operations)


def test_phase_persistence_failure_stops_before_target():
    """无法保存TARGET阶段时停止后续业务调用，不能吞掉存储故障继续第二条Case。"""

    operations = _CreateOrderCleanupOperationService()

    def unavailable_progress(event):
        """模拟阶段存储故障，只在目标调用前失败，不接触真实数据库。"""

        if event.phase == "TARGET":
            raise OSError("unavailable")

    with pytest.raises(Exception, match="progress could not be persisted"):
        CaseTemplateExecutorV4(operations).execute("case-generation-execution-" + "f" * 20,
            _create_order_generation(), RuntimeFunctionRegistry(functions=[]), "qa", unavailable_progress)
    assert operations.calls == []


def test_workflow_exception_keeps_persisted_case_result(tmp_path, monkeypatch):
    """执行器在首项保存后异常时，工作流读取最新记录收尾，不能覆盖为初始空结果。"""

    generation = _create_order_generation()
    running = execution_record(generation.system_id).model_copy(update={"generation_id": generation.generation_id,
        "selected_cases": [CaseSelection(case_id="case-one", generation_id=generation.generation_id,
                                         variant_id=generation.variants[0].variant_id)]})
    service = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    service.executions = CaseGenerationExecutionStoreV4(tmp_path)
    service.executions.create(running)
    service.handoffs = SimpleNamespace(get=Mock(return_value=_handoff(tmp_path)))
    service._generation_scope_selection = Mock(side_effect=lambda handoff, _generation: handoff)
    service._runtime_capabilities = Mock(return_value=[])
    service.runtime = SimpleNamespace(operation_service=Mock(), environment_provider=None)
    service.data_capabilities = None

    def fail_after_first(execution_id, selected, registry, environment, on_progress):
        """模拟已完成首项之后执行器异常；兼容原执行器五参数边界，回调仍用真实存储。"""

        on_progress(CaseExecutionProgressV4(variant_id=selected.variants[0].variant_id,
            result=CaseVariantExecutionV4(variant_id=selected.variants[0].variant_id,
                status="COMPLETED", started_at=utc_now(), ended_at=utc_now())))
        raise RuntimeError("worker interrupted")

    monkeypatch.setattr("opentest.application.case_template_v4.CaseTemplateExecutorV4",
                        Mock(return_value=SimpleNamespace(execute=fail_after_first)))
    with pytest.raises(RuntimeError, match="worker interrupted"):
        service._run_execution(running, generation, RuntimeFunctionRegistry(functions=[]), "trace-test")
    saved = service.executions.get(running.system_id, running.execution_id)
    assert saved.status == "FAILED" and len(saved.variant_results) == 1
    assert saved.started_at is not None and saved.ended_at >= saved.started_at


def test_task_progress_is_reported_only_after_case_persistence(tmp_path):
    """任务细进度沿用已有reporter；发布完成数量前，权威执行记录必须已有该条事实。"""

    service = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    service.executions = CaseGenerationExecutionStoreV4(tmp_path)
    running = service.executions.create(execution_record())

    def inspect_saved_progress(update):
        """检查reporter被调用时的真实存储，返回输入作为测试进度投影。"""

        saved = service.executions.get(running.system_id, running.execution_id)
        if update.completed_units:
            assert len(saved.variant_results) == 1
        else:
            assert saved.current_phase == "DATA"
        return update

    reporter = SimpleNamespace(update=Mock(side_effect=inspect_saved_progress))
    variant_id = running.selected_cases[0].variant_id
    service._record_execution_progress(running, CaseExecutionProgressV4(
        variant_id=variant_id, phase="DATA", started_at=utc_now(), total_units=2), reporter)
    service._record_execution_progress(running, CaseExecutionProgressV4(
        variant_id=variant_id, completed_units=1, total_units=2,
        result=CaseVariantExecutionV4(variant_id=variant_id, status="COMPLETED")), reporter)
    assert reporter.update.call_args.args[0].completed_units == 1
    assert reporter.update.call_args.args[0].total_units == 2


def generation_reader(tmp_path, payloads):
    """用payloads模拟MySQL逐次返回的JSON或缺失行，返回真实Generation读取器验证实际解析异常。"""

    rows = []
    for payload in payloads:
        # 使用生产读取器识别的MySQL COMPRESS格式，结构验证仍由真实Pydantic模型执行。
        raw = payload.encode("utf-8") if payload is not None else None
        rows.append({"generation_json": len(raw).to_bytes(4, "little") + zlib.compress(raw)} if raw is not None else None)
    reader = CaseTemplateGenerationStoreV4.__new__(CaseTemplateGenerationStoreV4)
    reader.metadata = SimpleNamespace(fetch_one=Mock(side_effect=rows))
    reader.knowledge_store = SimpleNamespace(root=tmp_path)
    return reader


@pytest.mark.parametrize("failure", ["missing", "invalid"])
def test_unavailable_seed_returns_issue_and_draft_can_be_saved(tmp_path, failure):
    """真实MySQL读取的缺失或Pydantic结构错误成为来源校验问题，草稿仍可保存且不能发布。"""

    service, handoff, original, variant = coverage_scenario(tmp_path)
    payload = None if failure == "missing" else "{}"
    service.generations = generation_reader(tmp_path, [payload, payload])
    # 先证明实际get的异常类型，避免用人工构造异常掩盖存储边界和权限异常的区别。
    expected = KnowledgeNotFoundError if failure == "missing" else ValidationError
    with pytest.raises(expected):
        service.generations.get(handoff.system_id, original.generation_id)
    origins, issues = service._coverage_seed_origins(handoff, handoff.draft_submission, [variant])
    assert origins == {} and [item.code for item in issues] == ["COVERAGE_SEED_IDENTITY_LOST"]
    draft_service, handoffs, _generations = _service(tmp_path / "draft", _compiled([variant], issues))
    handoffs.write(handoff)
    response = draft_service.revise_draft(handoff.handoff_id, CaseTemplateDraftRevisionRequest(
        request_id="request-source-unavailable", expected_revision=handoff.revision, submission=handoff.draft_submission))
    saved = handoffs.get(handoff.handoff_id)
    assert saved.draft_submission == handoff.draft_submission and saved.validation_issues == issues
    assert saved.status == "WAITING_FOR_AGENT" and saved.recoverable
    assert response.allowed_publication_modes == []


@pytest.mark.parametrize("failure", ["missing", "invalid"])
@pytest.mark.parametrize("stage", ["classification", "freeze"])
def test_freeze_rejects_source_loss_before_any_identity_reservation(tmp_path, monkeypatch, failure, stage):
    """任一冻结读取阶段缺失或损坏均拒绝发布，不写预留身份、不改写原有草稿问题。"""

    service, handoff, original, variant = coverage_scenario(tmp_path)
    payload = None if failure == "missing" else "{}"
    rows = [original.model_dump_json(exclude_unset=True), payload] if stage == "freeze" else [payload]
    service.generations = generation_reader(tmp_path, rows)
    monkeypatch.setattr("opentest.application.case_template_v4.PublicationService", Mock())
    service._used_case_operations = Mock(return_value={(handoff.system_id, handoff.entry_id)})
    prior_issue = CaseTemplateValidationIssue(code="EXISTING_DRAFT_PROBLEM", message="仍需修订原草稿")
    extra = variant.model_copy(update={"variant_id": "case-variant-v4-" + "9" * 20, "template_id": "coverage-extra"})
    extra_template = handoff.draft_submission.case_templates[0].model_copy(update={"template_id": extra.template_id})
    submission = handoff.draft_submission.model_copy(update={
        "case_templates": [*handoff.draft_submission.case_templates, extra_template]})
    handoff = handoff.model_copy(update={"validation_issues": [prior_issue], "draft_submission": submission})
    # 新增候选先进入循环；后续种子失效时，之前暂算的身份也不能被保存。
    with pytest.raises(KnowledgeValidationError, match="COVERAGE_SEED_IDENTITY_LOST"):
        service._freeze_case_bindings(handoff, [extra, variant])
    assert handoff.validation_issues == [prior_issue]
    assert handoff.case_bindings == []
    service.handoffs.write.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "invalid"])
def test_publication_rejects_source_loss_during_freeze_without_writes(tmp_path, monkeypatch, failure):
    """编译已通过但冻结时来源失效直接拒绝，不写正式产物或声称失败诊断已在回滚事务保存。"""

    service, handoff, original, variant = coverage_scenario(tmp_path)
    payload = None if failure == "missing" else "{}"
    service.generations = generation_reader(tmp_path, [original.model_dump_json(exclude_unset=True), payload])
    monkeypatch.setattr("opentest.application.case_template_v4.PublicationService", Mock())
    service._used_case_operations = Mock(return_value={(handoff.system_id, handoff.entry_id)})
    service.handoffs.get = Mock(return_value=handoff)
    service._require_current_source_scopes = Mock()
    # 让编译先报告通过，保留真实冻结路径，专门验证后一次来源读取失效的发布竞态。
    service._compile_draft = Mock(return_value=_compiled([variant]))
    service._write_or_recover_generation = Mock()
    request = CaseTemplatePublicationRequest(request_id="request-source-lost-publish", expected_revision=handoff.revision, mode="complete")
    with pytest.raises(KnowledgeValidationError, match="COVERAGE_SEED_IDENTITY_LOST"):
        service._publish_exclusive(handoff.handoff_id, request, {})
    service._write_or_recover_generation.assert_not_called()
    service.handoffs.write.assert_not_called()


@pytest.mark.parametrize("error", [MetadataConnectionError("database unavailable"), ScopeViolationError("scope denied"),
                                    KnowledgeValidationError("invalid local binding"), OSError("storage unavailable")])
@pytest.mark.parametrize("stage", ["classification", "freeze"])
def test_source_lookup_propagates_storage_and_permission_errors(tmp_path, monkeypatch, error, stage):
    """数据库、网络、权限及其他知识校验故障原样传播；不能伪装来源未知并保存误导诊断。"""

    service, handoff, original, variant = coverage_scenario(tmp_path)
    monkeypatch.setattr("opentest.application.case_template_v4.PublicationService", Mock())
    service._used_case_operations = Mock(return_value={(handoff.system_id, handoff.entry_id)})
    # 两个读取边界都必须保留原异常，防止把短暂服务故障或权限拒绝写成资产缺失。
    service.generations.get.side_effect = [original, error] if stage == "freeze" else error
    with pytest.raises(type(error)) as raised:
        if stage == "freeze":
            service._freeze_case_bindings(handoff, [variant])
        else:
            service._coverage_seed_origins(handoff, handoff.draft_submission, [variant])
    assert raised.value is error
    service.handoffs.write.assert_not_called()
