"""覆盖异步复核和轻量进度的边界测试；不调用真实模型、业务或远端材料。"""

from contextlib import nullcontext
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.coverage_store import CoverageStore
from opentest.application.coverage_recovery import CoverageRecovery
from opentest.domain.coverage_workflow import CoverageDisposition, CoverageModelRun
from opentest.domain.errors import ExecutionFailure, KnowledgeValidationError
from opentest.domain.models import utc_now
from opentest.domain.publication import PublicationScope
from tests.v2.test_coverage_interface_projection import _service, _workflow
from tests.v2.test_coverage_recovery import _service as recovery_service
from tests.v2.test_coverage_supplement import _fixture


def _review(tmp_path: Path):
    """建立一个绑定明确修订、仍运行的独立复核，返回服务和可控状态。"""

    supplement, state = _fixture(tmp_path)
    supplement.advance(state.workflow.enhancement_id)
    # 原生成任务仍运行；reviewer 使用自己的固定身份，不能取消或重派父任务。
    state.workflow.gaps[0].proposal = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="需要源码核实")
    run = CoverageModelRun(role="REVIEW", run_id="agent-" + "f" * 16, status="RUNNING",
        handoff_id=state.child.handoff_id, handoff_revision=state.child.revision, gap_ids=["gap-one"],
        registered_at=utc_now(), started_at=utc_now(), deadline_at=utc_now() + timedelta(seconds=180))
    state.workflow.model_runs.append(run)
    return supplement, state


def _finish_output(supplement, tmp_path: Path) -> None:
    """提供已终态的固定 reviewer 输出；attach 若被提前调用将由测试断言发现。"""

    output = tmp_path / "review-output.json"
    output.write_text(json.dumps({"reviews": [{"gap_id": "gap-one", "verdict": "ACCEPT", "reason": "已核实调用路径"}]}), encoding="utf-8")
    supplement.app.agent_runner.read_state.return_value = {"status": "completed"}
    supplement.app.agent_runner.attach.return_value = SimpleNamespace(exit_code=0, elapsed_seconds=4.5, output_path=str(output))


def test_running_review_observation_never_waits_or_starts_another_run(tmp_path: Path) -> None:
    """维护观察存活 reviewer 时只读小状态，父任务和其他恢复仍可推进。"""

    supplement, state = _review(tmp_path)
    supplement.app.agent_runner.read_state.return_value = {"status": "running"}
    supplement.observe_review(state.workflow.enhancement_id)
    supplement.app.agent_runner.attach.assert_not_called()
    supplement.app.agent_runner.start.assert_not_called()
    assert state.workflow.model_runs[-1].status == "RUNNING"
    assert state.child_task.web_run_active


@pytest.mark.parametrize("late", ["revision", "published", "finished"])
def test_late_review_only_records_run_facts(tmp_path: Path, late: str) -> None:
    """修订变化或发布后的晚到结论只保留成本，不改决策、主阶段或已发布内容。"""

    supplement, state = _review(tmp_path)
    _finish_output(supplement, tmp_path)
    if late == "revision":
        state.child.revision += 1
    else:
        state.child.status = "COMPLETED"
        state.workflow.stage = "VERIFICATION_EXECUTING" if late == "published" else "FINISHED"
        if late == "finished":
            state.workflow.status = "COMPLETED"
    original_stage = state.workflow.stage
    supplement.observe_review(state.workflow.enhancement_id)
    assert state.workflow.model_runs[-1].status == "COMPLETED"
    assert state.workflow.model_runs[-1].elapsed_seconds == 4.5
    assert state.workflow.gaps[0].review is None
    assert state.workflow.gaps[0].decision is None
    assert state.workflow.stage == original_stage
    supplement.app.agent_runner.start.assert_not_called()


@pytest.mark.parametrize("submit_gap", [True, False])
def test_new_draft_clears_completed_review_including_omitted_gap(tmp_path: Path, submit_gap: bool) -> None:
    """R 已完成复核后接纳 R+1，旧结论必须从持久缺口和返回上下文一起移除。"""

    supplement, state = _review(tmp_path)
    _finish_output(supplement, tmp_path)
    supplement.observe_review(state.workflow.enhancement_id)
    assert state.workflow.gaps[0].review.verdict == "ACCEPT"
    previous = SimpleNamespace(**vars(state.child))
    state.child.revision += 1
    draft = SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision)
    proposal = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="新草稿需要重新判断")
    # 局部修订未包含该缺口时也必须失效，不能因保留旧 proposal 而保留旧 review。
    response = supplement.accept_dispositions(previous, [proposal] if submit_gap else [], draft)

    assert state.workflow.gaps[0].review is None
    assert response["coverage_review"]["status"] == "stale"
    assert response["workflow"]["gaps"][0]["review"] is None
    assert sum(run.role == "REVIEW" for run in state.workflow.model_runs) == 1
    assert state.workflow.model_runs[-1].status == "COMPLETED"
    supplement.app.agent_runner.start.assert_not_called()


def test_context_hides_persisted_stale_review_without_writing(tmp_path: Path) -> None:
    """历史残留结论即使尚未再次保存也不交给当前草稿，读取不改原运行或工作流。"""

    supplement, state = _review(tmp_path)
    _finish_output(supplement, tmp_path)
    supplement.observe_review(state.workflow.enhancement_id)
    state.child.revision += 1
    supplement.records.save.reset_mock()
    # 模拟修复前留下的旧 review；投影只脱离当前草稿，仍保留原运行成本和状态。
    response = supplement.context(state.child)
    assert response["coverage_review"]["status"] == "stale"
    assert response["workflow"]["gaps"][0]["review"] is None
    assert state.workflow.gaps[0].review.verdict == "ACCEPT"
    supplement.records.save.assert_not_called()
    supplement.app.agent_runner.start.assert_not_called()


@pytest.mark.parametrize("run_status", ["PENDING", "RUNNING"])
def test_first_final_submission_cannot_skip_pending_review_by_incrementing_revision(tmp_path: Path, run_status: str) -> None:
    """同修订复核未结束时首次 final 自增不能绕过等待，晚到结果也不能写入新修订。"""

    supplement, state = _review(tmp_path)
    state.workflow.model_runs[-1].status = run_status
    previous = SimpleNamespace(**vars(state.child))
    state.child.revision += 1
    draft = SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision)
    final = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="尚未收到复核就尝试最终决定", final=True)
    # 提交前 handoff 仍与 reviewer 相同；以保存后的 revision 比较会错误放行这次 final。
    supplement.accept_dispositions(previous, [final], draft)
    assert state.workflow.gaps[0].decision.action == "UNRESOLVED"
    assert state.workflow.gaps[0].review is None

    _finish_output(supplement, tmp_path)
    supplement.observe_review(state.workflow.enhancement_id)
    assert state.workflow.model_runs[-1].status == "COMPLETED"
    assert state.workflow.gaps[0].review is None
    assert state.workflow.gaps[0].decision.action == "UNRESOLVED"
    supplement.app.agent_runner.start.assert_not_called()


@pytest.mark.parametrize("unavailable", ["expired", "old_revision"])
@pytest.mark.parametrize("run_status", ["PENDING", "RUNNING"])
def test_expired_or_already_stale_review_does_not_block_final_decision(tmp_path: Path, unavailable: str, run_status: str) -> None:
    """已过期或提交前就已属旧修订的复核不阻断最终决定，仍只保留本轮唯一运行。"""

    supplement, state = _review(tmp_path)
    state.workflow.model_runs[-1].status = run_status
    if unavailable == "expired":
        state.workflow.model_runs[-1].deadline_at = utc_now() - timedelta(seconds=1)
    else:
        state.child.revision += 1
    previous = SimpleNamespace(**vars(state.child))
    state.child.revision += 1
    draft = SimpleNamespace(handoff_id=state.child.handoff_id, revision=state.child.revision)
    final = CoverageDisposition(gap_id="gap-one", action="IGNORE", reason="复核已不可用，由生成模型确认", final=True)
    # 是否不可用取决于提交前事实，而不是简单看到 PENDING/RUNNING 就无限等待。
    supplement.accept_dispositions(previous, [final], draft)
    assert state.workflow.gaps[0].decision == final
    assert state.workflow.gaps[0].review is None
    assert sum(run.role == "REVIEW" for run in state.workflow.model_runs) == 1
    supplement.app.agent_runner.start.assert_not_called()


def test_review_timeout_waits_for_original_worker_exit_and_keeps_parent_active(tmp_path: Path) -> None:
    """到期先请求原 reviewer 结束，核实终态后记不可用；不取消生成或重新付费。"""

    supplement, state = _review(tmp_path)
    state.workflow.model_runs[-1].deadline_at = utc_now() - timedelta(seconds=1)
    run_id = state.workflow.model_runs[-1].run_id
    supplement.app.agent_runner.read_state.return_value = {"status": "running"}
    supplement.observe_review(state.workflow.enhancement_id)
    assert state.workflow.model_runs[-1].status == "RUNNING"
    assert supplement.review_projection(state.workflow, state.child)["status"] == "unavailable"
    supplement.app.agent_runner.cancel.assert_called_once_with(run_id, tmp_path / ".opentest" / "agent-runs")
    supplement.app.agent_runner.attach.assert_not_called()
    # worker 确认退出后，只结束辅助步骤，保留生成任务与原工作流阶段。
    supplement.app.agent_runner.read_state.return_value = {"status": "failed", "timed_out": True}
    supplement.app.agent_runner.attach.side_effect = ExecutionFailure("review timed out")
    supplement.observe_review(state.workflow.enhancement_id)
    assert state.workflow.model_runs[-1].status == "FAILED"
    assert state.workflow.model_runs[-1].reason_code == "REVIEW_TIMEOUT"
    assert state.workflow.gaps[0].review.verdict == "UNAVAILABLE"
    assert state.workflow.stage == "SUPPLEMENT_RUNNING" and state.child_task.web_run_active
    supplement.app.agent_runner.start.assert_not_called()


def test_registered_but_missing_review_expires_without_relaunch(tmp_path: Path) -> None:
    """登记后没有启动证据不会无限 pending，也不会因恢复而新增一个运行。"""

    supplement, state = _review(tmp_path)
    state.workflow.model_runs[-1].status = "PENDING"
    supplement.observe_review(state.workflow.enhancement_id)
    assert state.workflow.model_runs[-1].status == "PENDING"
    state.workflow.model_runs[-1].deadline_at = utc_now() - timedelta(seconds=1)
    supplement.observe_review(state.workflow.enhancement_id)
    assert state.workflow.model_runs[-1].status == "FAILED"
    assert state.workflow.model_runs[-1].reason_code == "REVIEW_TIMEOUT"
    supplement.app.agent_runner.start.assert_not_called()
    supplement.app.agent_runner.attach.assert_not_called()


def test_recovery_observes_reviewer_during_verification() -> None:
    """主工作流进入复测时仍收尾原复核，不因主阶段改变丢掉观察入口。"""

    service = recovery_service(phase="verification", stage="VERIFICATION_EXECUTING")
    service.state.task.owner_pid = service.tasks._owner_pid
    service.state.task.owner_instance_id = service.tasks._owner_instance_id
    CoverageRecovery(service)._recover(service.state.workflow)
    service.supplement.observe_review.assert_called_once_with(service.state.workflow.enhancement_id)
    service.app.case_template_v4.executions.update.assert_not_called()


def _status_service():
    """给出两条固定基线和两条复测的小摘要，并禁止所有完整正文读取。"""

    workflow, report, cases, generations = _workflow([])
    workflow.status, workflow.stage = "RUNNING", "VERIFICATION_EXECUTING"
    service = _service(workflow, report, cases, generations)
    verification = service.app.case_template_v4.executions.get(workflow.system_id, workflow.verification_case_execution_id)
    ended_at = utc_now().isoformat()
    summary = {"selected_cases": [item.model_dump(mode="json") for item in verification.selected_cases],
        "variant_summaries": [{"variant_id": "variant-added-1", "outcome": "PASSED", "ended_at": ended_at}],
        "current_variant_id": "variant-added-2", "current_phase": "DATA", "updated_at": ended_at}
    service.records.latest_status_for_operation.return_value = workflow
    service.records.execution_summary.side_effect = lambda item, execution_id: summary if execution_id == "verification-exec" else {}
    # 轻量状态不允许为了展示进度再解压正文、扫描源码或重建覆盖报告。
    service.app.case_template_v4.executions.get = Mock(side_effect=AssertionError("full execution read"))
    service.app.case_template_v4.generations.get = Mock(side_effect=AssertionError("full generation read"))
    service.records.report.side_effect = AssertionError("coverage report read")
    return service, workflow, cases


def test_status_reads_only_summaries_and_exact_visible_selections() -> None:
    """进度按已保存结果计算，实际完成一条时可见1/2，不读取任何完整报告。"""

    service, workflow, _ = _status_service()
    scope = PublicationScope(system_id="refund", baseline_id="baseline-a", user_id="employee-a")
    response = service.status_projection(scope, workflow.operation_id, "qa")
    assert response["availability"] == "available"
    progress = response["coverage"]["progress"]
    assert progress["completed_units"] == 1 and progress["total_units"] == 2
    assert "第 2/2 条" in progress["current_item"] and "准备数据" in progress["current_item"]
    service.records.report.assert_not_called()
    service.app.case_template_v4.executions.get.assert_not_called()


def test_status_distinguishes_lost_visibility_from_read_failure() -> None:
    """本人旧选择失效与存储故障分别返回不可查看和暂时不可读，均不返回假零。"""

    service, workflow, cases = _status_service()
    scope = PublicationScope(system_id="refund", baseline_id="baseline-a", user_id="employee-a")
    cases.pop("case-added-1")
    response = service.status_projection(scope, workflow.operation_id, "qa")
    assert response["coverage"] is None and response["availability"] == "selection_unavailable"
    service.records.execution_summary.side_effect = RuntimeError("database unavailable")
    response = service.status_projection(scope, workflow.operation_id, "qa")
    assert response["coverage"] is None and response["availability"] == "coverage_unavailable"
    assert response["error"] == "coverage_unavailable"


def test_bound_verification_read_error_is_never_treated_as_absent() -> None:
    """有精确复测ID时读取异常必须向上报告，只有空ID才能返回None。"""

    service, workflow, _ = _status_service()
    service.app.case_template_v4.executions.get.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        service._verification_execution(workflow)
    workflow.verification_case_execution_id = ""
    assert service._verification_execution(workflow) is None


def test_terminal_reviewer_remains_in_recovery_candidate_query() -> None:
    """终态增强仍包含pending/running reviewer候选，查询有工作台隔离与上限。"""

    metadata = SimpleNamespace(workspace_id="workspace-a", fetch_all=Mock(return_value=[]))
    store = CoverageStore(metadata)
    assert store.candidates(limit=20) == []
    sql, parameters = metadata.fetch_all.call_args.args
    assert "'role','REVIEW','status','PENDING'" in sql and "'role','REVIEW','status','RUNNING'" in sql
    assert "w.owner_workspace_id=%s" in sql and "LIMIT %s" in sql
    assert parameters[1] == "workspace-a" and parameters[-1] == 20


def test_repeated_phase_end_preserves_original_time(tmp_path: Path) -> None:
    """阶段异常也落结束时间，重复收尾不推进既有时间或丢失其他测量状态。"""

    supplement, state = _fixture(tmp_path)
    from opentest.application.coverage_assistance import CoverageAssistanceService

    service = object.__new__(CoverageAssistanceService)
    service.records, service.app = supplement.records, supplement.app
    service._publish_phase_progress = Mock()
    with pytest.raises(ValueError):
        with service._timed_phase(state.workflow.enhancement_id, "baseline", "analysis"):
            raise ValueError("analyzer failed")
    timing = state.workflow.baseline.phase_timings[-1]
    assert timing.ended_at is not None and timing.elapsed_seconds is not None
    ended_at = timing.ended_at
    service._end_phase(state.workflow.enhancement_id, "baseline", timing)
    assert state.workflow.baseline.phase_timings[-1].ended_at == ended_at
