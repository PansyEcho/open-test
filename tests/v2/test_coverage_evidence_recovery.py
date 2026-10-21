"""真实 MySQL 下验证覆盖有效证据、同进程恢复和幂等收尾；不调用 QA。"""

from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.coverage_assistance import ActiveCoverageMeasurement
from opentest.application.foundation import OpenTestApplication
from opentest.domain.coverage import CoverageAnalysisResult, CoverageCounts
from opentest.domain.coverage_workflow import INTERNAL_REPORT_RETENTION_PENDING
from opentest.domain.models import SystemDefinition, TaskStatus, utc_now
from tests.v2.test_coverage_assistance import active_window
from tests.v2.test_coverage_recovery import _service, _valid_dump


def _analysis() -> CoverageAnalysisResult:
    """返回已完成的本地解析结果，测试只替换计算边界而保留真实持久化流程。"""

    counts = CoverageCounts(method={"covered": 1, "missed": 0},
                            line={"covered": 1, "missed": 0}, branch={"covered": 0, "missed": 0})
    return CoverageAnalysisResult(raw_counts=counts, scope_counts=counts, matched_class_count=1,
        uncomparable_class_count=0, scope_reason="test resolved method", candidate_gap_count=0,
        deferred_gap_count=0)


@pytest.fixture
def evidence(tmp_path, request):
    """建立当前进程拥有的真实增强、任务、Case 终态及有效 dump，退出关闭应用资源。

    Args:
        tmp_path: 随机测试 MySQL 库对应的临时工作台。
        request: indirect 参数选择 baseline/verification，默认验证复测收尾。
    Yields:
        应用、服务、初始工作流和精确终态执行；不启动 HTTP 或模型观察。
    """

    phase = getattr(request, "param", "verification")
    template = _service(phase, stage=phase.upper() + "_ANALYZING")
    _valid_dump(template, phase)
    state = template.state
    app = OpenTestApplication(tmp_path / "knowledge")
    try:
        app.store.register_system(SystemDefinition(
            system_id=state.workflow.system_id, name="覆盖证据恢复测试", source_path=str(tmp_path)))
        for execution in state.executions.values():
            app.case_template_v4.executions.create(execution.model_copy(update={"status": "RUNNING"}))
            app.case_template_v4.executions.update(execution)
        waiting = state.task.model_copy(update={
            "status": TaskStatus.WAITING_FOR_COMPLETION, "ended_at": utc_now(),
            "owner_workspace_id": app.store.metadata.workspace_id,
            "owner_pid": app.tasks._owner_pid, "owner_started_at": app.tasks._owner_started_at,
            "owner_instance_id": app.tasks._owner_instance_id,
            "result": {"request_id": state.workflow.enhancement_id,
                       "enhancement_id": state.workflow.enhancement_id},
        })
        owner = app.tasks.create_business_record(waiting)
        app.tasks.save_business_record(owner.model_copy(update={
            "status": TaskStatus.RUNNING, "started_at": utc_now(), "ended_at": None,
        }))
        service = app.coverage_assistance
        current = service.records.create(state.workflow)
        service.records.save_report(state.report)
        # 一旦恢复错误地重放业务、发现实例或派发补充，就使测试明确失败。
        app.case_template_v4.dispatch_execution = Mock(side_effect=AssertionError("must not replay business"))
        app.case_template_v4.execute_generation = Mock(side_effect=AssertionError("must not rerun Case"))
        service.discovery.discover = Mock(side_effect=AssertionError("must not contact QA"))
        service.advance = Mock()
        execution = state.executions[getattr(current, phase + "_case_execution_id")]
        yield SimpleNamespace(app=app, service=service, workflow=current, execution=execution, phase=phase)
    finally:
        app.close()


@pytest.mark.parametrize("evidence", ["baseline"], indirect=True)
def test_saved_dump_survives_submit_failure_and_same_process_maintenance(evidence, tmp_path, monkeypatch):
    """dump 提交成功后线程池拒绝不能作废材料，同进程维护下一次仍能投递分析。"""

    service = evidence.service
    current = service.records.get(evidence.workflow.enhancement_id)
    current.stage = "BASELINE_EXECUTING"
    current.baseline.status = "PENDING"
    current.baseline.dump_at = None
    service.records.save(current)
    window = active_window(tmp_path)
    active = ActiveCoverageMeasurement(current.enhancement_id, "baseline", window.target,
                                      window.artifact, window.collector, window.lease)
    submit = Mock(side_effect=RuntimeError("executor closed"))
    monkeypatch.setattr(service.tasks._executor, "submit", submit)
    service.execution_finished(evidence.execution, active)
    saved = service.records.get(current.enhancement_id)
    assert (saved.status, saved.stage, saved.baseline.status) == ("RUNNING", "BASELINE_ANALYZING", "VALID")
    assert saved.baseline.dump_at is not None
    assert service.records.report(current.enhancement_id).result["baseline"].exec_base64
    assert service._analysis_futures == {}
    active.lease.release.assert_called_once()
    assert evidence.app.case_template_v4.executions.get(
        evidence.execution.system_id, evidence.execution.execution_id).status == "PASSED"

    # 模拟原线程池下一次可接受投递；维护仍使用同一进程 owner，不需要重启或重开测量。
    future = Future()
    submit.side_effect = None
    submit.return_value = future
    service.recovery._run()
    assert submit.call_count == 2
    assert service._analysis_futures[(current.enhancement_id, "baseline")] is future
    assert service.records.get(current.enhancement_id).baseline.status == "VALID"
    future.set_result(None)
    assert service._analysis_futures == {}


def test_saved_analysis_survives_finish_failure_and_is_not_recomputed(evidence, monkeypatch):
    """解析已保存后报告终态事务失败不改 INVALID；下一次只完成收尾而不再计算。"""

    service = evidence.service
    calculate = Mock(return_value=_analysis())
    monkeypatch.setattr(service, "_calculate_analysis", calculate)
    original = service.records.set_report_status
    status = Mock(side_effect=RuntimeError("injected report status failure"))
    monkeypatch.setattr(service.records, "set_report_status", status)
    service.analyze(evidence.workflow.enhancement_id, "verification")
    saved = service.records.get(evidence.workflow.enhancement_id)
    assert saved.stage == "VERIFICATION_ANALYZING" and saved.status == "RUNNING"
    assert saved.verification.status == "VALID" and saved.verification.analysis is not None
    assert service.records.report(saved.enhancement_id).status == "RUNNING"
    assert service.tasks.get(saved.task_id).status == TaskStatus.RUNNING

    monkeypatch.setattr(service.records, "set_report_status", original)
    service.analyze(saved.enhancement_id, "verification")
    finished = service.records.get(saved.enhancement_id)
    assert (finished.status, finished.stage, finished.verification.status) == ("COMPLETED", "FINISHED", "VALID")
    assert calculate.call_count == 1
    assert service.records.report(saved.enhancement_id).status == "COMPLETED"
    assert service.tasks.get(saved.task_id).status == TaskStatus.COMPLETED


@pytest.mark.parametrize("boundary", ["report", "task"])
def test_finish_failure_rolls_back_all_small_terminal_writes(evidence, monkeypatch, boundary):
    """在报告或任务已写后抛错，真实系统事务必须回滚 workflow/report/task 三方终态。"""

    service = evidence.service
    target = service.records if boundary == "report" else service.tasks
    method = "set_report_status" if boundary == "report" else "save_business_record"
    original = getattr(target, method)

    def fail_after_write(record):
        """完成目标实际 SQL 后模拟失败，验证外层事务而不是仅验证未执行分支。"""

        original(record)
        raise RuntimeError("injected terminal write failure")

    monkeypatch.setattr(target, method, fail_after_write)
    with pytest.raises(RuntimeError, match="injected terminal write failure"):
        service.finish(evidence.workflow, "COMPLETED", "")
    persisted = service.records.get(evidence.workflow.enhancement_id)
    assert persisted.status == "RUNNING" and persisted.stage == "VERIFICATION_ANALYZING"
    assert persisted.verification.status == "VALID"
    assert service.records.report(persisted.enhancement_id).status == "RUNNING"
    task = service.tasks.get(persisted.task_id)
    assert task.status == TaskStatus.RUNNING and task.ended_at is None


def test_repeat_finish_preserves_terminal_time_and_cannot_restore_pruned_materials(evidence):
    """重复收尾保持既定终态及结束时间，不因持有旧工作流再次写回已经裁剪的材料。"""

    service = evidence.service
    first = service.finish(evidence.workflow, "COMPLETED", "")
    ended_at = service.tasks.get(first.task_id).ended_at
    report = service.records.report(first.enhancement_id)
    # 新有效报告完成后，按现有保留规则真实裁剪原报告，而非直接模拟 result 为空。
    newer = first.model_copy(update={
        "enhancement_id": "coverage-" + "e" * 20, "task_id": "task-" + "e" * 16,
        "revision": 0, "created_at": utc_now() + timedelta(seconds=1),
    })
    service.records.create(newer)
    service.records.save_report(report.model_copy(update={
        "execution_id": newer.enhancement_id, "created_at": newer.created_at,
    }))
    service.records.prune(newer)
    assert service.records.report(first.enhancement_id).result == {}
    service.finish(evidence.workflow, "PARTIAL", "LATE_DECISION")
    service.finish(first, "COMPLETED", "")
    persisted = service.records.get(first.enhancement_id)
    assert persisted.status == "COMPLETED" and persisted.revision == first.revision
    assert "LATE_DECISION" not in persisted.reason_codes
    assert service.tasks.get(first.task_id).ended_at == ended_at
    assert service.records.report(first.enhancement_id).result == {}


def test_prune_failure_keeps_private_pending_marker_and_recovers(evidence, monkeypatch):
    """裁剪异常保留可恢复待办，公开投影和任务摘要不把内部标记展示为增强失败。"""

    service = evidence.service
    original = service.records.prune
    prune = Mock(side_effect=RuntimeError("injected prune failure"))
    monkeypatch.setattr(service.records, "prune", prune)
    first = service.finish(evidence.workflow, "COMPLETED", "")
    assert first.status == "COMPLETED"
    assert INTERNAL_REPORT_RETENTION_PENDING in first.reason_codes
    assert {item.enhancement_id for item in service.records.candidates()} == {first.enhancement_id}
    projection = service.projection(first.system_id, first.base_generation_id)
    task = service.tasks.get(first.task_id)
    ended_at = task.ended_at
    assert INTERNAL_REPORT_RETENTION_PENDING not in json.dumps(projection)
    assert INTERNAL_REPORT_RETENTION_PENDING not in task.model_dump_json()

    monkeypatch.setattr(service.records, "prune", original)
    service.recovery._run()
    finished = service.records.get(first.enhancement_id)
    assert finished.status == "COMPLETED"
    assert INTERNAL_REPORT_RETENTION_PENDING not in finished.reason_codes
    assert service.tasks.get(first.task_id).ended_at == ended_at
    assert service.records.candidates() == []
    service.advance.assert_not_called()


@pytest.mark.parametrize("prune_fails", [False, True])
def test_terminal_maintenance_does_not_repeat_prune_while_case_runs(evidence, monkeypatch, prune_fails):
    """复测准备失败后只恢复真正的裁剪待办，业务仍运行不应重复写入工作流。

    Args:
        evidence: 真实 MySQL 中的增强、专属任务与精确执行绑定。
        monkeypatch: 替换裁剪边界以计数并注入一次失败。
        prune_fails: 首次裁剪是否失败；失败必须沿原维护流程重试一次。
    """

    service = evidence.service
    current = service.records.get(evidence.workflow.enhancement_id)
    # 有效基线应保留；复测准备失败不能终止正在运行的原业务执行。
    current.baseline.status = "VALID"
    current.verification.status = "SKIPPED"
    current = service.records.save(current)
    execution = evidence.execution.model_copy(update={"status": "RUNNING"})
    evidence.app.case_template_v4.executions.update(execution)
    original = service.records.prune
    attempts = 0

    def prune_once_failed(workflow):
        """在首次调用可选失败，后续执行真实裁剪，不替换终态与维护逻辑。"""

        nonlocal attempts
        attempts += 1
        if prune_fails and attempts == 1:
            raise RuntimeError("injected first prune failure")
        return original(workflow)

    monkeypatch.setattr(service.records, "prune", prune_once_failed)
    finished = service.finish(current, "PARTIAL", "COVERAGE_PREFLIGHT_TIMEOUT")
    assert service.tasks.get(finished.task_id).status == TaskStatus.RUNNING
    assert (INTERNAL_REPORT_RETENTION_PENDING in finished.reason_codes) is prune_fails
    # 首轮维护补裁剪（如需要）；以后即使候选仍存在，也不再写工作流或重复解压报告。
    service.recovery._run()
    settled = service.records.get(finished.enhancement_id)
    assert INTERNAL_REPORT_RETENTION_PENDING not in settled.reason_codes
    for _ in range(3):
        service.recovery._run()
    assert attempts == (2 if prune_fails else 1)
    assert service.records.get(finished.enhancement_id).revision == settled.revision
    assert service.tasks.get(finished.task_id).status == TaskStatus.RUNNING

    # 业务最终结束后维护只补任务终态，不能再次触发裁剪或重放业务。
    evidence.app.case_template_v4.executions.update(execution.model_copy(update={"status": "PASSED"}))
    service.recovery._run()
    assert service.tasks.get(finished.task_id).status == TaskStatus.PARTIAL
    assert service.records.get(finished.enhancement_id).revision == settled.revision
    assert attempts == (2 if prune_fails else 1)
    assert service.records.candidates() == []
    service.advance.assert_not_called()


def test_concurrent_schedule_deduplicates_and_completed_or_rejected_future_releases_slot(evidence, monkeypatch):
    """多个请求共享活动 Future；完成和 submit 失败都会释放登记，后续维护可重新进入。"""

    service = evidence.service
    future = Future()
    submit = Mock(return_value=future)
    monkeypatch.setattr(service.tasks._executor, "submit", submit)
    identity = evidence.workflow.enhancement_id
    with ThreadPoolExecutor(max_workers=4) as callers:
        attempts = [callers.submit(service.schedule_analysis, identity, "verification") for _ in range(8)]
        assert sum(attempt.result(timeout=5) for attempt in attempts) == 1
    submit.assert_called_once()
    assert len(service._analysis_futures) == 1
    future.set_result(None)
    assert service._analysis_futures == {}

    # 提交被拒绝时没有 Future 可供回调，入口本身也必须清理，不能永久占住分析槽位。
    submit.side_effect = RuntimeError("pool closed")
    assert not service.schedule_analysis(identity, "verification")
    assert service._analysis_futures == {}
    submit.side_effect = None
    second = Future()
    submit.return_value = second
    assert service.schedule_analysis(identity, "verification")
    second.set_exception(RuntimeError("analysis worker failed"))
    assert service._analysis_futures == {}
    assert service.records.get(identity).verification.status == "VALID"


def test_stale_workflow_sync_keeps_claimed_owner_and_current_terminal_state(evidence):
    """旧调用只能提供身份，sync_task 必须锁内读取新 owner 和新终态，不能整条回写旧值。"""

    service = evidence.service
    stale = evidence.workflow.model_copy(deep=True)
    with evidence.app.store.system_transaction(stale.system_id):
        current = service.records.get(stale.enhancement_id)
        service.records.save(current.model_copy(update={"status": "COMPLETED", "stage": "FINISHED"}))
        task = service.tasks.get(stale.task_id)
        service.tasks.save_business_record(task.model_copy(update={
            "owner_pid": task.owner_pid + 1, "owner_started_at": "claimed-start",
            "owner_instance_id": "claimed-instance",
        }))
    service.sync_task(stale)
    saved = service.tasks.get(stale.task_id)
    assert saved.owner_instance_id == "claimed-instance" and saved.owner_started_at == "claimed-start"
    assert saved.owner_pid == task.owner_pid + 1
    assert saved.status == TaskStatus.COMPLETED
    assert saved.result["enhancement_status"] == "COMPLETED"
