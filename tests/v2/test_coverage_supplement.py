"""覆盖补充的单轮、回执与非阻断复核边界，不调用业务或真实模型。"""

from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.coverage_supplement import CoverageSupplement, GATE_BUSY, SUPPLEMENT_OWNER_EXITED
from opentest.domain.coverage import CodeLocation, CoverageCounter
from opentest.domain.coverage_workflow import (
    CoverageDisposition, CoverageEnhancement, CoverageModelRun, CoverageReview, ReviewedCoverageGap,
)
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    EntryPoint, KnowledgeNodeKind, ScanManifest, SemanticAnalysisResult, SemanticCallEdge,
    SemanticMethodDefinition, SemanticResolutionStatus, SourceBaseline, SourceReference,
)


def _fixture(tmp_path: Path):
    """组装 CAS 内存记录、唯一后继与模型回执，返回测试可操控的服务和状态。"""

    workflow = CoverageEnhancement(enhancement_id="coverage-unit", task_id="task-" + "a" * 16,
        system_id="demo-system", operation_id="facade:com.example.Api#query", base_generation_id="generation-base",
        source_scan_id="scan-fixed", source_commit="b" * 40, baseline_case_execution_id="execution-base",
        stage="SUPPLEMENT_PENDING", gaps=[ReviewedCoverageGap(gap_id="gap-one", kind="METHOD",
            location=CodeLocation(class_name="com/example/Service", method_name="query", source_path="Service.java", line=1),
            scope_reason="已解析调用", before=CoverageCounter(covered=0, missed=1))])
    base = SimpleNamespace(task_id="task-base", handoff_id="handoff-base", successor_handoff_id="")
    child = SimpleNamespace(task_id="task-child", handoff_id="handoff-child", predecessor_handoff_id="handoff-base",
        generation_id="generation-child", system_id="demo-system", thread_id="", turn_id="", request_receipts=[], revision=1, status="READY_TO_PUBLISH", draft_variants=[SimpleNamespace(variant_id="variant-real")])
    base_task = SimpleNamespace(task_id="task-base", web_run_active=False)
    child_task = SimpleNamespace(task_id="task-child", active_handoff_id="handoff-child", web_run_active=False, web_run_id="", web_run_requests={}, result={}, status="PENDING")
    state = SimpleNamespace(workflow=workflow, child=child, child_task=child_task, base_task=base_task)

    def get_workflow(identity):
        """读取副本，让未保存修改不能影响后续断言。"""
        return state.workflow.model_copy(deep=True)

    def save_workflow(updated):
        """模拟真正 CAS，防止用过期模型覆盖异步状态。"""
        if updated.revision != state.workflow.revision:
            raise KnowledgeValidationError("stale workflow")
        state.workflow = updated.model_copy(update={"revision": updated.revision + 1}, deep=True)
        return get_workflow(updated.enhancement_id)

    def finish(updated, status, reason):
        """与主协调器一样保存终态和原因，不操作基础 Case。"""
        updated.status, updated.stage = status, "FINISHED"
        if reason:
            updated.reason_codes.append(reason)
        return save_workflow(updated)

    def task_get(identity):
        """只允许基础和补充两个指定任务，帮助发现错误绑定。"""
        return {"task-base": base_task, "task-child": child_task}[identity]

    def handoff_get(identity):
        """提供基础或已编译子草稿，不从调用方旧 handoff 取 Variant。"""
        return {"handoff-base": base, "handoff-child": child}[identity]

    def start(task_id, request_id, revision):
        """模拟 start 在派发前原子写回执和运行身份。"""
        assert task_id == child.task_id
        child_task.web_run_requests[request_id] = 1
        child_task.web_run_id = "agent-" + "c" * 16
        child_task.web_run_active = True
        child_task.status = "RUNNING"
        return child_task

    records = SimpleNamespace(get=Mock(side_effect=get_workflow), save=Mock(side_effect=save_workflow),
        for_generation=Mock(side_effect=lambda *args: get_workflow("coverage-unit")))
    tasks = SimpleNamespace(get=Mock(side_effect=task_get), _lock=nullcontext(), _exclusive_handles={},
        activity=Mock(return_value=SimpleNamespace(active=False)))
    generation = SimpleNamespace(handoff_id=base.handoff_id, submission=Mock())
    execution = SimpleNamespace(execution_id="execution-base", status="PASSED", variant_results=[])
    engine = SimpleNamespace(generations=SimpleNamespace(get=Mock(return_value=generation)),
        handoffs=SimpleNamespace(get=Mock(side_effect=handoff_get), processing_scope=Mock(side_effect=lambda identity: nullcontext()), find_successor=Mock(return_value=None)),
        executions=SimpleNamespace(get=Mock(return_value=execution)))
    settings = SimpleNamespace(case_template_v4_model="generator", codex_model="fallback", coverage_review_model="reviewer", coverage_review_timeout_seconds=180,
        case_template_v4_reasoning_effort="high", codex_reasoning_effort="medium")
    app = SimpleNamespace(case_template_v4=engine, runtime_settings=SimpleNamespace(read=Mock(return_value=settings)),
        store=SimpleNamespace(system_transaction=Mock(side_effect=lambda system_id: nullcontext())),
        continue_case_task=Mock(return_value={"handoff": child}), web_generation=SimpleNamespace(start=Mock(side_effect=start), recover=Mock()),
        agent_runner=SimpleNamespace(run=Mock(side_effect=RuntimeError("offline model")), start=Mock(), attach=Mock(), cancel=Mock(),
            list_events=Mock(return_value=[]), read_state=Mock(return_value={})), knowledge=Mock(), knowledge_root=tmp_path)
    service = SimpleNamespace(app=app, tasks=tasks, records=records, finish=Mock(side_effect=finish))
    state.execution, state.settings, state.base = execution, settings, base
    return CoverageSupplement(service), state


@pytest.mark.parametrize("busy", ["base", "local", "global"])
def test_busy_defers_without_consuming_round(tmp_path: Path, busy: str):
    """基础发布尚在退出或其他生成占门禁时不创建后继，不消耗唯一轮次。"""
    supplement, state = _fixture(tmp_path)
    if busy == "base":
        state.base_task.web_run_active = True
    elif busy == "local":
        supplement.tasks._exclusive_handles["other"] = object()
    else:
        supplement.tasks.activity.return_value.active = True
    supplement.advance("coverage-unit")
    assert state.workflow.stage == "SUPPLEMENT_PENDING" and state.workflow.round_used == 0
    supplement.app.continue_case_task.assert_not_called()


def test_existing_successor_skips_without_round(tmp_path: Path):
    """人工后继已经存在时不抢占，轮次仍为零。"""
    supplement, state = _fixture(tmp_path)
    supplement.app.case_template_v4.handoffs.find_successor.return_value = state.child
    supplement.advance("coverage-unit")
    assert state.workflow.status == "SKIPPED"
    assert state.workflow.reason_codes == ["SUCCESSOR_EXISTS"]
    assert state.workflow.round_used == 0
    supplement.app.web_generation.start.assert_not_called()


@pytest.mark.parametrize("has_target, expected", [(False, "SKIPPED"), (True, "RUNNING")])
def test_data_failure_requires_explicit_absent_target(tmp_path: Path, has_target: bool, expected: str):
    """准备失败只在没有任何 TARGET 证据时跳过；实际目标尝试仍允许补充。"""
    supplement, state = _fixture(tmp_path)
    state.execution.variant_results = [SimpleNamespace(failure_kind="DATA_PREPARATION_FAILED",
        operations=[SimpleNamespace(phase="TARGET")] if has_target else [])]
    supplement.advance("coverage-unit")
    assert state.workflow.status == expected
    assert ("TARGET_NOT_EXECUTED" in state.workflow.reason_codes) is (not has_target)


def test_empty_variant_records_do_not_prove_target_unexecuted(tmp_path: Path):
    """没有阶段记录不能编造准备失败，仍只派发一次原后继。"""
    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    supplement.advance("coverage-unit")
    assert state.workflow.round_used == 1
    assert state.workflow.model_runs[0].run_id == state.child_task.web_run_id
    supplement.app.continue_case_task.assert_called_once_with("task-base", "coverage-unit.supplement.continue", "continue")
    supplement.app.web_generation.start.assert_called_once_with("task-child", "coverage-unit.supplement.run", None)


def test_known_gate_race_retries_same_child_request_only(tmp_path: Path):
    """仅已知门禁拒绝且无回执可恢复；后继与稳定派发身份始终不变。"""
    supplement, state = _fixture(tmp_path)
    successful_start = supplement.app.web_generation.start.side_effect
    supplement.app.web_generation.start.side_effect = ScopeViolationError("another long task is active: other")
    supplement.advance("coverage-unit")
    assert state.workflow.status == "RUNNING" and GATE_BUSY in state.workflow.reason_codes
    supplement.app.web_generation.start.side_effect = successful_start
    supplement.advance("coverage-unit")
    assert state.workflow.round_used == 1 and GATE_BUSY not in state.workflow.reason_codes
    supplement.app.continue_case_task.assert_called_once()
    assert supplement.app.web_generation.start.call_args_list[0] == supplement.app.web_generation.start.call_args_list[1]


def test_unknown_dispatch_failure_never_retries(tmp_path: Path):
    """未知派发异常不能解释成门禁冲突，保留原后继并终结增强。"""
    supplement, state = _fixture(tmp_path)
    supplement.app.web_generation.start.side_effect = RuntimeError("unknown submit outcome")
    supplement.advance("coverage-unit")
    supplement.advance("coverage-unit")
    assert state.workflow.status == "PARTIAL"
    supplement.app.web_generation.start.assert_called_once()
    assert state.workflow.supplement_task_id == "task-child"


def test_pending_without_receipt_is_not_replayed_or_misclassified(tmp_path: Path):
    """首次提交与派发之间的窗口保持 PENDING，不能由维护线程误判失败或重复派发。"""
    supplement, state = _fixture(tmp_path)
    state.workflow.stage, state.workflow.round_used = "SUPPLEMENT_RUNNING", 1
    state.workflow.supplement_task_id = "task-child"
    state.workflow.model_runs = [CoverageModelRun(role="SUPPLEMENT", task_id="task-child")]
    supplement.advance("coverage-unit")
    assert state.workflow.status == "RUNNING"
    supplement.app.web_generation.start.assert_not_called()


def test_finished_model_without_publication_is_partial(tmp_path: Path):
    """模型结束没有生成正式产物时记录 PARTIAL，不消耗第二轮模型。"""
    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    state.child_task.web_run_active = False
    state.child_task.status = "FAILED"
    supplement.advance("coverage-unit")
    assert state.workflow.reason_codes == ["SUPPLEMENT_NOT_PUBLISHED"]
    assert state.workflow.status == "PARTIAL"


def test_review_unavailable_is_nonblocking_and_final_authoritative(tmp_path: Path):
    """独立复核故障保留 UNAVAILABLE，生成模型随后可以最终忽略，复核不重复调用。"""
    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    supplement.app.knowledge.artifacts.read.side_effect = RuntimeError("snapshot unavailable")
    first = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="原始理由")
    response = supplement.accept_dispositions(state.child, [first], SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision))
    assert response is not None
    assert state.workflow.gaps[0].review.verdict == "UNAVAILABLE"
    assert state.workflow.gaps[0].decision.action == "UNRESOLVED"
    final = first.model_copy(update={"reason": "生成模型复核后的决定", "final": True})
    supplement.accept_dispositions(state.child, [final], SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision))
    assert state.workflow.gaps[0].decision == final
    assert state.workflow.gaps[0].proposal.reason == "原始理由"
    assert len(state.workflow.model_runs) == 2
    assert state.workflow.model_runs[1].model == "reviewer"
    supplement.app.knowledge.artifacts.read.assert_called_once()


def test_rejected_ignore_can_be_confirmed_and_bad_variant_remains_unresolved(tmp_path: Path):
    """程序不强阻断拒绝意见，非法 Variant 引用却不能记录成已经补齐。"""
    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    state.workflow.gaps[0].review = CoverageReview(gap_id="gap-one", verdict="REJECT", reason="调用链仍可达")
    final = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="保留可用性，由人工后续确认", final=True)
    supplement.accept_dispositions(state.child, [final], SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision))
    assert state.workflow.gaps[0].decision == final
    bad = CoverageDisposition(gap_id="gap-one", action="ADD_CASE", reason="新增场景", case_variant_ids=["invented"], final=True)
    supplement.accept_dispositions(state.child, [bad], SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision))
    assert state.workflow.gaps[0].decision.action == "UNRESOLVED"
    supplement.app.agent_runner.run.assert_not_called()


def test_missing_disposition_is_explicitly_unresolved(tmp_path: Path):
    """空答复也把未处理项持久化，不能从报告中静默消失。"""
    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    supplement.accept_dispositions(state.child, [], SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision))
    assert state.workflow.gaps[0].decision.action == "UNRESOLVED"


@pytest.mark.parametrize("late_state", ["new_revision", "COMPLETED", "PARTIAL", "BLOCKED"])
def test_old_draft_receipt_never_overwrites_final_decision(tmp_path: Path, late_state: str):
    """旧请求回执、晚到答复和已发布草稿均只读，不能把最终忽略改回未处理。"""

    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    state.workflow.gaps[0].review = CoverageReview(gap_id="gap-one", verdict="ACCEPT", reason="已核实源码")
    proposal = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="初始理由")
    stale_receipt = SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision)
    # 模拟后续草稿已根据独立复核保存最终决定；重放最早回执不得触发新的复核或写入。
    state.child.revision += 1
    final = proposal.model_copy(update={"reason": "复核后确认", "final": True})
    supplement.accept_dispositions(state.child, [final], SimpleNamespace(
        handoff_id=state.child.handoff_id, revision=state.child.revision))
    if late_state != "new_revision":
        state.child.status = late_state
        stale_receipt.revision = state.child.revision
    saved_revision = state.workflow.revision
    supplement.accept_dispositions(state.child, [proposal], stale_receipt)
    assert state.workflow.revision == saved_revision
    assert state.workflow.gaps[0].decision == final
    supplement.app.agent_runner.run.assert_not_called()


def test_revision_is_rechecked_after_handoff_lock(tmp_path: Path):
    """答复等待锁期间草稿推进时，按锁内修订拒绝晚到答复。"""

    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    receipt = SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision)

    def acquire_after_new_draft(identity):
        """在真实核对前模拟另一提交先取得handoff锁并写入新草稿。"""
        state.child.revision += 1
        return nullcontext()

    supplement.app.case_template_v4.handoffs.processing_scope.side_effect = acquire_after_new_draft
    saved_revision = state.workflow.revision
    supplement.accept_dispositions(state.child,
        [CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="迟到理由")], receipt)
    assert state.workflow.revision == saved_revision
    assert state.workflow.gaps[0].proposal is None


def test_review_uses_fixed_snapshot_real_call_context_and_independent_runner(tmp_path: Path):
    """成功复核必须以固定 commit 快照和真实扫描类型传入调用证据，不继承生成会话。"""

    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "Service.java").write_text("package com.example; class Service { void query() {} }", encoding="utf-8")
    source_ref = SourceReference(path="Service.java", commit="b" * 40, line=1)
    caller = SemanticMethodDefinition(symbol_id="com.example.Api#query()", qualified_class_name="com.example.Api",
        method_name="query", has_executable_body=True, source_ref=source_ref)
    callee = SemanticMethodDefinition(symbol_id="com.example.Service#query()", qualified_class_name="com.example.Service",
        method_name="query", has_executable_body=True, source_ref=source_ref)
    edge = SemanticCallEdge(caller_symbol_id=caller.symbol_id, callee_symbol_id=callee.symbol_id,
        callee_expression="service.query", source_ref=source_ref, resolution_status=SemanticResolutionStatus.RESOLVED)
    baseline = SourceBaseline(source_path=str(tmp_path / "live-checkout"), snapshot_path=str(snapshot), commit="b" * 40)
    manifest = ScanManifest(scan_id="scan-fixed", system_id="demo-system", baseline=baseline,
        entries=[EntryPoint(entry_id=state.workflow.operation_id, system_id="demo-system", kind=KnowledgeNodeKind.FACADE,
            display_name="query", source_id=caller.symbol_id, source_path="Service.java")],
        semantic_analysis=SemanticAnalysisResult(system_id="demo-system", methods=[caller, callee], call_edges=[edge]))
    supplement.app.knowledge.artifacts.read.return_value = manifest
    # 保存请求只能验证已有本机快照，不进入 S3 下载/物化入口。
    supplement.app.knowledge.artifacts.source_snapshot_path.return_value = snapshot
    supplement.app.knowledge.git_repository.validate_materialized_revision.return_value = snapshot
    output = tmp_path / "review.json"
    output.write_text(json.dumps({"reviews": [{"gap_id": "gap-one", "verdict": "REJECT", "reason": "从入口可到达"}]}))
    supplement.app.agent_runner.attach.return_value = SimpleNamespace(exit_code=0, elapsed_seconds=2.5, output_path=str(output))
    response = supplement.accept_dispositions(state.child,
        [CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="认为无人调用")], SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision))
    request, source_root, evidence_root = supplement.app.agent_runner.start.call_args.args
    assert response["coverage_review"]["status"] == "running"
    supplement.app.agent_runner.attach.assert_not_called()
    # 后续维护只在 worker 终态后解析输出，核心保存已先返回。
    supplement.app.agent_runner.read_state.return_value = {"status": "completed"}
    supplement.observe_review(state.workflow.enhancement_id)
    assert source_root == snapshot and evidence_root == tmp_path / ".opentest" / "agent-runs"
    assert request.task_id == "" and request.resume_session_id == "" and request.model == "reviewer"
    assert "service.query" not in request.prompt
    assert caller.symbol_id in request.prompt and callee.symbol_id in request.prompt
    assert "class Service" in request.prompt and "不可信证据" in request.prompt
    supplement.app.knowledge.artifacts.require_source_snapshot.assert_not_called()
    supplement.app.knowledge.git_repository.validate_materialized_revision.assert_called_once_with(
        baseline, snapshot, supplement.app.knowledge.artifacts.source_snapshot_root)
    assert state.workflow.gaps[0].review.verdict == "REJECT"
    assert state.workflow.model_runs[1].elapsed_seconds == 2.5
    assert response["workflow"]["gaps"][0]["decision"]["action"] == "UNRESOLVED"


def test_late_dispatch_error_does_not_override_verification(tmp_path: Path):
    """派发响应迟到失败时，已经进入最终复测的增强必须继续原阶段。"""

    supplement, state = _fixture(tmp_path)

    def late_error(*args):
        """模拟发布钩子先完成阶段转换，派发调用随后才报错。"""
        state.workflow.stage = "VERIFICATION_EXECUTING"
        state.workflow.verification_case_execution_id = "execution-enhanced"
        raise RuntimeError("late response")

    supplement.app.web_generation.start.side_effect = late_error
    supplement.advance("coverage-unit")
    assert state.workflow.stage == "VERIFICATION_EXECUTING" and state.workflow.status == "RUNNING"
    supplement.service.finish.assert_not_called()


def test_valid_compiled_variant_is_recorded_without_claiming_coverage(tmp_path: Path):
    """新增 Case 声明只引用当前草稿编译身份，复测状态仍是未测量。"""
    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    proposal = CoverageDisposition(gap_id="gap-one", action="ADD_CASE", reason="增加缺失条件", case_variant_ids=["variant-real"], final=True)
    supplement.accept_dispositions(state.child, [proposal], SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision))
    assert state.workflow.gaps[0].decision == proposal
    assert state.workflow.gaps[0].verification == "NOT_MEASURED"


@pytest.mark.parametrize("available", [True, False])
def test_review_recovery_attaches_original_identity_without_new_run(tmp_path: Path, available: bool):
    """恢复读取原审查结果，原运行缺失则记录不可用，两个分支都不能另起模型。"""
    supplement, state = _fixture(tmp_path)
    supplement.advance("coverage-unit")
    proposal = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="待核实框架代码")
    state.workflow.gaps[0].proposal = proposal
    original = CoverageModelRun(role="REVIEW", run_id="agent-" + "d" * 16, status="RUNNING", provider="codex", model="original-model",
        handoff_id=state.child.handoff_id, handoff_revision=state.child.revision, gap_ids=["gap-one"])
    supplement.app.agent_runner.read_state.return_value = {"status": "completed"}
    state.workflow.model_runs.append(original)
    if available:
        output = tmp_path / "original-review.json"
        output.write_text(json.dumps({"reviews": [{"gap_id": "gap-one", "verdict": "ACCEPT", "reason": "确认为框架入口"}]}))
        supplement.app.agent_runner.attach.return_value = SimpleNamespace(exit_code=0, elapsed_seconds=3.0, output_path=str(output))
    else:
        supplement.app.agent_runner.attach.side_effect = KnowledgeValidationError("original run unavailable")
    supplement.advance("coverage-unit")
    supplement.app.agent_runner.attach.assert_called_once_with(original.run_id, tmp_path / ".opentest" / "agent-runs")
    supplement.app.agent_runner.run.assert_not_called()
    assert state.workflow.gaps[0].review.verdict == ("ACCEPT" if available else "UNAVAILABLE")
    assert state.workflow.model_runs[1].run_id == original.run_id
    assert state.workflow.model_runs[1].model == "original-model"


def test_usage_aggregates_existing_turn_events_without_defaulting_missing_to_zero(tmp_path: Path):
    """Token 来自已有公开逐轮事件，未提供的输出用量保留未知。"""
    supplement, state = _fixture(tmp_path)
    run = CoverageModelRun(role="REVIEW", run_id="agent-" + "d" * 16)
    supplement.app.agent_runner.list_events.return_value = [
        SimpleNamespace(event_type="usage", text='{"input_tokens": 12}'),
        SimpleNamespace(event_type="usage", text='{"input_tokens": 8, "cached_input_tokens": 2}'),
        SimpleNamespace(event_type="agent_message", text="not usage")]
    supplement._read_usage(run)
    assert run.input_tokens == 20 and run.output_tokens is None


def test_claimed_unknown_dispatch_ends_without_replaying_child(tmp_path):
    """原派发owner确认退出且无任何接续证据时结束未知派发，不再卡住或重开模型。"""

    supplement, state = _fixture(tmp_path)
    state.workflow.stage, state.workflow.round_used = "SUPPLEMENT_RUNNING", 1
    state.workflow.supplement_task_id = state.child.task_id
    state.workflow.model_runs = [CoverageModelRun(role="SUPPLEMENT", task_id=state.child.task_id)]
    state.workflow.reason_codes = [SUPPLEMENT_OWNER_EXITED]
    supplement.advance(state.workflow.enhancement_id)
    assert state.workflow.status == "PARTIAL"
    assert state.workflow.reason_codes == ["SUPPLEMENT_DISPATCH_UNKNOWN"]
    supplement.app.web_generation.start.assert_not_called()
    supplement.app.continue_case_task.assert_not_called()


@pytest.mark.parametrize("evidence", ["web", "native", "thread", "draft", "run"])
def test_owner_exit_does_not_cancel_existing_agent_or_human_evidence(tmp_path, evidence):
    """服务owner退出不代表补充模型结束，既有网页/Agent/原生草稿保持观察且不重派。"""

    supplement, state = _fixture(tmp_path)
    state.workflow.stage, state.workflow.round_used = "SUPPLEMENT_RUNNING", 1
    state.workflow.supplement_task_id = state.child.task_id
    state.workflow.model_runs = [CoverageModelRun(role="SUPPLEMENT", task_id=state.child.task_id)]
    state.workflow.reason_codes = [SUPPLEMENT_OWNER_EXITED]
    if evidence == "web":
        # 回执先落盘、submit尚未发生也由web recovery判定，覆盖层不能抢先结束。
        state.child_task.web_run_id = "agent-" + "d" * 16
        state.child_task.web_run_requests = {"coverage-unit.supplement.run": 1}
        state.child_task.web_run_active = True
    elif evidence == "native":
        state.child_task.result = {"native_handoff": {"session_id": "existing-session"}}
    elif evidence == "thread":
        state.child.thread_id = "existing-thread"
    elif evidence == "draft":
        state.child.request_receipts = [SimpleNamespace(action="revise")]
    else:
        state.workflow.model_runs[0].run_id = "agent-" + "d" * 16
        supplement.app.agent_runner.read_state.return_value = {"status": "running"}
    supplement.advance(state.workflow.enhancement_id)
    assert state.workflow.status == "RUNNING"
    supplement.app.web_generation.start.assert_not_called()
    supplement.service.finish.assert_not_called()
    if evidence == "web":
        supplement.app.web_generation.recover.assert_called_once()


def test_unchanged_running_model_does_not_lock_or_save(tmp_path):
    """模型长时间运行时维护只读；运行事实未变化不反复锁系统或增加revision。"""

    supplement, state = _fixture(tmp_path)
    supplement.advance(state.workflow.enhancement_id)
    previous_revision = state.workflow.revision
    supplement.app.store.system_transaction.reset_mock()
    supplement.records.save.reset_mock()
    for _ in range(3):
        supplement.advance(state.workflow.enhancement_id)
    assert state.workflow.revision == previous_revision
    supplement.app.store.system_transaction.assert_not_called()
    supplement.records.save.assert_not_called()


def test_optional_coverage_reads_never_revoke_core_draft_success(tmp_path):
    """历史覆盖记录损坏时prompt/草稿附加读取降级，异常消息与凭据不返回用户。"""

    supplement, state = _fixture(tmp_path)
    supplement.records.for_generation.side_effect = ValueError("private-token-in-bad-payload")
    assert supplement.context(state.child) is None
    response = supplement.accept_dispositions(state.child, [], SimpleNamespace(revision=1))
    assert response == {"reason_codes": ["COVERAGE_DISPOSITION_UNAVAILABLE"]}
    assert "private-token" not in str(response)


def test_corrected_disposition_clears_old_invalid_reason_and_hides_internal_state(tmp_path):
    """模型更正非法缺口身份后清除旧原因，内部恢复标记不进入模型上下文。"""

    supplement, state = _fixture(tmp_path)
    supplement.advance(state.workflow.enhancement_id)
    draft = SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision)
    invalid = CoverageDisposition(gap_id="not-a-gap", action="UNRESOLVED", reason="identity invalid")
    supplement.accept_dispositions(state.child, [invalid], draft)
    assert "INVALID_GAP_DISPOSITION" in state.workflow.reason_codes
    state.workflow.reason_codes.append(SUPPLEMENT_OWNER_EXITED)
    valid = CoverageDisposition(gap_id="gap-one", action="UNRESOLVED", reason="未找到补充方式")
    response = supplement.accept_dispositions(state.child, [valid], draft)
    assert "INVALID_GAP_DISPOSITION" not in state.workflow.reason_codes
    assert SUPPLEMENT_OWNER_EXITED not in response["workflow"]["reason_codes"]


def test_target_attempt_failure_before_operation_record_still_allows_supplement(tmp_path):
    """真实执行器已尝试目标后异常但尚无TARGET记录，仍按环境失败处理并允许补充。"""

    from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4
    from tests.v2.test_case_template_v4 import _create_order_generation
    from opentest.domain.case_template_v4 import RuntimeFunctionRegistry

    generation = _create_order_generation()
    executor = CaseTemplateExecutorV4(Mock())
    executor._with_environments = Mock(return_value=executor)
    executor._environment_values = Mock(return_value={"env": "qa"})
    executor._call_operation = Mock(side_effect=RuntimeError("request sent, record not saved"))
    # 调用真实Variant分类路径；异常发生在标记target_attempted之后、追加TARGET operation之前。
    results = executor.execute("case-generation-execution-" + "9" * 20, generation, RuntimeFunctionRegistry(functions=[]))
    assert len(results) == 1 and results[0].failure_kind == "ENVIRONMENT_DEPENDENCY"
    assert results[0].operations == []
    executor._call_operation.assert_called_once()
    supplement, state = _fixture(tmp_path)
    state.execution.variant_results = results
    supplement.advance(state.workflow.enhancement_id)
    assert state.workflow.status == "RUNNING" and "TARGET_NOT_EXECUTED" not in state.workflow.reason_codes
    supplement.app.web_generation.start.assert_called_once()


def test_known_run_without_worker_state_does_not_prove_run_finished(tmp_path):
    """持久run身份早于worker证据时不能把缺文件当作终态，等待原运行恢复。"""

    supplement, state = _fixture(tmp_path)
    state.workflow.stage, state.workflow.round_used = "SUPPLEMENT_RUNNING", 1
    state.workflow.supplement_task_id = state.child.task_id
    state.workflow.model_runs = [CoverageModelRun(role="SUPPLEMENT", task_id=state.child.task_id,
        run_id="agent-" + "d" * 16)]
    state.workflow.reason_codes = [SUPPLEMENT_OWNER_EXITED]
    supplement.advance(state.workflow.enhancement_id)
    assert state.workflow.status == "RUNNING"
    supplement.service.finish.assert_not_called()
    supplement.app.web_generation.start.assert_not_called()
