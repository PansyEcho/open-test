"""覆盖恢复仅收尾确认退出的精确执行，不用心跳失效重放业务。"""

from concurrent.futures import Future
from contextlib import contextmanager, nullcontext
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.mysql_metadata import MySqlMetadataStore
from opentest.application.coverage_recovery import CoverageRecovery
from opentest.application.foundation import OpenTestApplication
from opentest.domain.case_template_v4 import CaseGenerationExecutionV4, CaseVariantExecutionV4
from opentest.domain.coverage import ArtifactFileIdentity, CoverageArtifactSelection, FrozenCoverageArtifact
from opentest.domain.coverage_workflow import CoverageEnhancement, CoverageMeasurement, CoverageRawCapture, CoverageReport
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import SystemDefinition, TaskRecord, TaskStatus, utc_now


def _service(phase="baseline", workflow_status="RUNNING", stage=None):
    """组装有CAS语义的内存存储和记录调用的协调器，不连接数据库或操作系统进程。

    Args:
        phase: 测试当前基线还是复测。
        workflow_status: 可模拟已经SKIPPED但Case尚未结束。
        stage: 可指定只读分析或补充阶段。
    Returns:
        带真实领域模型、精确执行字典和可观测依赖的隔离服务。
    """

    first = CaseGenerationExecutionV4(execution_id="case-generation-execution-" + "a" * 20,
        generation_id="case-template-generation-" + "a" * 20, system_id="refund-test", environment_id="qa",
        status="RUNNING", variant_results=[CaseVariantExecutionV4(variant_id="case-variant-v4-" + "c" * 20,
            status="COMPLETED", data_execution_ids=["existing-data-request"])])
    second = first.model_copy(update={"execution_id": "case-generation-execution-" + "b" * 20,
        "generation_id": "case-template-generation-" + "b" * 20})
    workflow = CoverageEnhancement(enhancement_id="coverage-" + "a" * 20, task_id="task-" + "a" * 16,
        system_id="refund-test", operation_id="facade:Example#cancel", base_generation_id=first.generation_id,
        source_scan_id="scan-fixed", source_commit="d" * 40, status=workflow_status,
        stage=stage or phase.upper() + "_EXECUTING", baseline_case_execution_id=first.execution_id,
        baseline=CoverageMeasurement(case_execution_id=first.execution_id))
    executions = {first.execution_id: first}
    if phase == "verification":
        first.status = "PASSED"
        workflow.enhanced_generation_id = second.generation_id
        workflow.verification_case_execution_id = second.execution_id
        workflow.verification.case_execution_id = second.execution_id
        executions[second.execution_id] = second
    task = TaskRecord(task_id=workflow.task_id, operation="coverage-enhancement", system_id=workflow.system_id,
        trace_id="recovery-test", status=TaskStatus.RUNNING, owner_workspace_id="workspace-test",
        owner_pid=999999, owner_started_at="old-start", owner_instance_id="old-instance")
    state = SimpleNamespace(workflow=workflow, task=task, executions=executions, report=None)

    def get_workflow(enhancement_id):
        """返回独立副本，使未保存的模型修改不能伪装成持久化成功。"""
        assert enhancement_id == state.workflow.enhancement_id
        return state.workflow.model_copy(deep=True)

    def save_workflow(updated):
        """模拟生产CAS；并发修订不得被恢复覆盖。"""
        if updated.revision != state.workflow.revision:
            raise KnowledgeValidationError("revision changed")
        state.workflow = updated.model_copy(update={"revision": updated.revision + 1}, deep=True)
        return state.workflow.model_copy(deep=True)

    def get_execution(system_id, execution_id):
        """只按明确身份读已有Case，拒绝跨系统测试数据。"""
        execution = state.executions[execution_id]
        assert execution.system_id == system_id
        return execution.model_copy(deep=True)

    def save_execution(execution):
        """模拟原执行存储，只更新相同ID并保留未覆盖字段。"""
        state.executions[execution.execution_id] = execution.model_copy(deep=True)
        return execution

    def finish(updated, status, reason):
        """模拟主服务的阶段收尾；测试读取实际保存结果。"""
        return save_workflow(updated.model_copy(update={"status": status, "stage": "FINISHED",
            "reason_codes": [*updated.reason_codes, reason]}))

    records = SimpleNamespace(metadata=SimpleNamespace(workspace_id="workspace-test"),
        get=Mock(side_effect=get_workflow), save=Mock(side_effect=save_workflow),
        candidates=Mock(return_value=[workflow]), report=Mock(side_effect=lambda identity: state.report))
    def save_task(updated):
        """保存独立owner副本，断言接管失败者不会把原owner写回。"""
        state.task = updated.model_copy(deep=True)
        return state.task.model_copy(deep=True)

    tasks = SimpleNamespace(get=Mock(side_effect=lambda identity: state.task.model_copy(deep=True)),
        save_business_record=Mock(side_effect=save_task), _owner_is_alive=Mock(return_value=False),
        _owner_pid=12345, _owner_started_at="current-start", _owner_instance_id="current-instance", _process_start_marker=Mock(return_value="old-start"),
        register_maintenance_callback=Mock(), _executor=Mock())
    app = SimpleNamespace(store=SimpleNamespace(system_transaction=Mock(return_value=nullcontext())),
        case_template_v4=SimpleNamespace(executions=SimpleNamespace(get=Mock(side_effect=get_execution), update=Mock(side_effect=save_execution))))
    return SimpleNamespace(app=app, records=records, tasks=tasks, sync_task=Mock(), finish=Mock(side_effect=finish),
        analyze=Mock(), schedule_analysis=Mock(), advance=Mock(), state=state)


def _valid_dump(service, phase):
    """为业务已结束的测试阶段保存有效窗口及制品引用，不生成真实覆盖文件。"""

    workflow = service.state.workflow
    measurement = getattr(workflow, phase)
    measurement.status, measurement.reset_at, measurement.dump_at = "VALID", utc_now(), utc_now()
    execution_id = getattr(workflow, phase + "_case_execution_id")
    service.state.executions[execution_id].status = "PASSED"
    artifact = FrozenCoverageArtifact(selection=CoverageArtifactSelection(app_uk="example"), commit=workflow.source_commit,
        transport="LOCAL", artifact=ArtifactFileIdentity(path="/tmp/app.war", size=1, modified="1"),
        source=ArtifactFileIdentity(path="/tmp/source.zip", size=1, modified="1"))
    service.state.report = CoverageReport(execution_id=workflow.enhancement_id, system_id=workflow.system_id,
        generation_id=workflow.base_generation_id, operation_id=workflow.operation_id,
        result={phase: CoverageRawCapture(exec_base64="YQ==", artifact=artifact)})


def test_maintenance_only_submits_one_future_and_reads_no_metadata_inline():
    """启动和重复心跳只投递一次，数据库读取必须在原线程池作业里。"""

    service = _service()
    pending = Future()
    service.tasks._executor.submit.return_value = pending
    recovery = CoverageRecovery(service)
    recovery.start_observing()
    recovery.start_observing()
    recovery.request()
    service.tasks.register_maintenance_callback.assert_called_once()
    service.tasks._executor.submit.assert_called_once_with(recovery._run)
    service.records.candidates.assert_not_called()
    service.tasks._process_start_marker.assert_not_called()
    # 原作业完成后才允许后续维护投递，不添加额外计时器。
    pending.set_result(None)
    recovery.request()
    assert service.tasks._executor.submit.call_count == 2


@pytest.mark.parametrize("phase,workflow_status,expected", [
    ("baseline", "RUNNING", "FAILED"), ("verification", "RUNNING", "PARTIAL"), ("baseline", "SKIPPED", "SKIPPED"),
])
def test_confirmed_dead_owner_closes_exact_running_case_and_preserves_results(monkeypatch, phase, workflow_status, expected):
    """确认旧PID退出后收尾绑定Case；复测保留增强版，SKIPPED保留原结论。"""

    service = _service(phase, workflow_status)
    kill = Mock(side_effect=ProcessLookupError)
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", kill)
    before = service.state.executions[getattr(service.state.workflow, phase + "_case_execution_id")].model_copy(deep=True)
    recovery = CoverageRecovery(service)
    recovery._run()
    saved = service.state.executions[before.execution_id]
    assert saved.status == "FAILED" and "可能未知" in saved.safe_error
    assert saved.variant_results == before.variant_results
    assert service.state.workflow.status == expected
    assert getattr(service.state.workflow, phase).status == "INVALID"
    if phase == "verification":
        assert service.state.executions[service.state.workflow.baseline_case_execution_id].status == "PASSED"
        assert service.state.workflow.enhanced_generation_id == before.generation_id
    service.analyze.assert_not_called()
    service.advance.assert_not_called()
    service.sync_task.assert_called()
    service.records.candidates.assert_called_once_with(limit=20)


@pytest.mark.parametrize("kill_error,marker", [(None, "old-start"), (None, ""), (PermissionError, "new-start"), (OSError, "new-start")])
def test_heartbeat_or_interrupted_task_never_proves_process_death(monkeypatch, kill_error, marker):
    """活PID、空ps标识或权限失败保留RUNNING；重复观察只写一次未知原因。"""

    service = _service()
    service.state.task = service.state.task.model_copy(update={"status": TaskStatus.INTERRUPTED, "ended_at": utc_now()})
    service.tasks._owner_is_alive = Mock(return_value=False)
    service.tasks._process_start_marker.return_value = marker
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", Mock(side_effect=kill_error))
    recovery = CoverageRecovery(service)
    recovery._recover(service.state.workflow.model_copy(deep=True))
    first_revision = service.state.workflow.revision
    recovery._recover(service.state.workflow.model_copy(deep=True))
    assert service.state.workflow.revision == first_revision == 1
    assert service.state.workflow.reason_codes == ["EXECUTION_OWNER_UNCONFIRMED"]
    service.app.case_template_v4.executions.update.assert_not_called()
    service.tasks._owner_is_alive.assert_called()
    service.analyze.assert_not_called()
    service.advance.assert_not_called()


def test_changed_nonempty_start_marker_proves_pid_reuse_without_heartbeat(monkeypatch):
    """PID仍存在但可靠启动时间已变，旧执行进程已结束。"""

    service = _service()
    service.tasks._process_start_marker.return_value = "new-start"
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", Mock())
    CoverageRecovery(service)._recover(service.state.workflow)
    assert service.state.workflow.status == "FAILED"


@pytest.mark.parametrize("change", ["revision", "owner", "workspace"])
def test_transaction_rechecks_revision_and_owner_before_closing(monkeypatch, change):
    """进程核查后阶段/owner变化时，不把旧退出证明套到新执行。"""

    service = _service()
    snapshot = service.state.workflow.model_copy(deep=True)
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", Mock(side_effect=ProcessLookupError))

    @contextmanager
    def transaction(system_id):
        """模拟退出核查到写事务之间另一请求完成阶段或派发owner交接。"""
        if change == "revision":
            service.state.workflow.revision += 1
        elif change == "owner":
            service.state.task.owner_instance_id = "new-owner"
        else:
            service.state.task.owner_workspace_id = "other-workspace"
        yield

    service.app.store.system_transaction.side_effect = transaction
    CoverageRecovery(service)._recover(snapshot)
    service.app.case_template_v4.executions.update.assert_not_called()
    service.finish.assert_not_called()
    service.sync_task.assert_not_called()


@pytest.mark.parametrize("phase", ["baseline", "verification"])
def test_saved_dump_and_terminal_business_resume_only_analysis(monkeypatch, phase):
    """已有有效dump和业务终态时继续只读分析，不改业务结果且异常仍同步任务。"""

    service = _service(phase, stage=phase.upper() + "_ANALYZING")
    _valid_dump(service, phase)
    service.schedule_analysis.side_effect = RuntimeError("analysis unavailable")
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", Mock(side_effect=ProcessLookupError))
    CoverageRecovery(service)._run()
    service.schedule_analysis.assert_called_once_with(service.state.workflow.enhancement_id, phase)
    service.app.case_template_v4.executions.update.assert_not_called()
    service.sync_task.assert_called_once()


def test_terminal_case_without_saved_dump_does_not_trigger_measurement_or_replay(monkeypatch):
    """业务已终态但未保存有效窗口时终止增强，不能再次reset或重跑Case。"""

    service = _service(stage="BASELINE_ANALYZING")
    service.state.executions[service.state.workflow.baseline_case_execution_id].status = "PASSED"
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", Mock(side_effect=ProcessLookupError))
    CoverageRecovery(service)._recover(service.state.workflow)
    assert service.state.workflow.status == "FAILED"
    service.app.case_template_v4.executions.update.assert_not_called()
    service.analyze.assert_not_called()


@pytest.mark.parametrize("stage,should_advance", [("SUPPLEMENT_PENDING", True), ("SUPPLEMENT_RUNNING", True), ("BASELINE_ANALYZING", False)])
def test_current_owner_retries_only_pending_supplement_after_gate_release(stage, should_advance):
    """当前进程交原协调器观察补充；没有有效窗口时不提交分析或重测业务。"""

    service = _service(stage=stage)
    service.state.task.owner_pid = service.tasks._owner_pid
    service.state.task.owner_instance_id = service.tasks._owner_instance_id
    service.state.executions[service.state.workflow.baseline_case_execution_id].status = "PASSED"
    CoverageRecovery(service)._recover(service.state.workflow)
    assert service.advance.call_count == int(should_advance)
    service.analyze.assert_not_called()
    service.tasks._process_start_marker.assert_not_called()


def test_foreign_workspace_is_never_probed_or_changed(monkeypatch):
    """他机PID没有本机含义，即使候选存储误返回也不得读取进程或修改数据。"""

    service = _service()
    service.state.task.owner_workspace_id = "other-workspace"
    kill = Mock(side_effect=AssertionError("must not inspect another workspace"))
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", kill)
    CoverageRecovery(service)._recover(service.state.workflow)
    kill.assert_not_called()
    service.records.save.assert_not_called()
    service.sync_task.assert_not_called()


@pytest.mark.parametrize("phase,expected", [("baseline", "FAILED"), ("verification", "PARTIAL")])
def test_real_owner_termination_releases_only_bound_mysql_execution(tmp_path, phase: str, expected: str):
    """以真实子进程退出证据收尾 MySQL 绑定执行，不接管手动任务或重放业务。

    Args:
        tmp_path: 自动测试夹具分配的独立工作台和随机 MySQL 库。
        phase: 当前被中断的是基线还是复测。
        expected: 增强应保存的终态，复测需保留增强版。
    Side Effects:
        只启动并终止本测试的睡眠子进程；不启动 HTTP 服务，不调用 QA。
    """

    app = OpenTestApplication(tmp_path / "knowledge")
    observer = MySqlMetadataStore(app.store.metadata.configuration, app.store.metadata.workspace_id)
    child = None
    try:
        # 复用已有严格领域样本，实际执行、任务和增强都写入真实随机库。
        template = _service(phase).state
        workflow = template.workflow
        app.store.register_system(SystemDefinition(system_id=workflow.system_id, name="进程恢复验收", source_path=str(tmp_path)))
        executions = app.case_template_v4.executions
        for execution in template.executions.values():
            executions.create(execution.model_copy(update={"status": "RUNNING"}))
            if execution.status != "RUNNING":
                executions.update(execution)
        bound = template.executions[getattr(workflow, phase + "_case_execution_id")]
        manual = executions.create(bound.model_copy(update={
            "execution_id": "case-generation-execution-" + "e" * 20,
            "generation_id": "case-template-generation-" + "e" * 20, "variant_results": [],
        }))
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        marker = app.tasks._process_start_marker(child.pid)
        assert marker and child.poll() is None
        owner = template.task.model_copy(update={
            "status": TaskStatus.WAITING_FOR_COMPLETION,
            "owner_workspace_id": app.store.metadata.workspace_id, "owner_pid": child.pid,
            "owner_started_at": marker, "owner_instance_id": "real-child-owner",
            "ended_at": utc_now(),
            "result": {"request_id": workflow.enhancement_id, "enhancement_id": workflow.enhancement_id},
        })
        app.tasks.create_business_record(owner)
        app.tasks.save_business_record(owner.model_copy(update={"status": TaskStatus.RUNNING, "started_at": utc_now(), "ended_at": None}))
        service = app.coverage_assistance
        service.records.create(workflow)
        app.case_template_v4.dispatch_execution = Mock(side_effect=AssertionError("recovery must not dispatch business"))
        app.case_template_v4.execute_generation = Mock(side_effect=AssertionError("recovery must not replay business"))
        service.analyze = Mock(side_effect=AssertionError("interrupted window has no saved dump"))
        service.advance = Mock(side_effect=AssertionError("interrupted window must not supplement"))
        service.discovery.discover = Mock(side_effect=AssertionError("recovery must not reopen measurement"))

        # 即使没有 owner 心跳，真实 PID 仍存活时也不能解除运行占用。
        service.recovery._run()
        assert executions.active_for(bound.system_id, bound.generation_id, "qa").execution_id == bound.execution_id
        assert executions.get(bound.system_id, bound.execution_id).status == "RUNNING"
        child.terminate()
        child.wait(timeout=5)
        assert child.returncode is not None

        # terminate + wait 后不替换 os.kill/ps；恢复依据操作系统真实退出证据及数据库精确绑定。
        service.recovery._run()
        saved = executions.get(bound.system_id, bound.execution_id)
        assert saved.status == "FAILED" and "可能未知" in saved.safe_error
        assert saved.variant_results == bound.variant_results
        assert executions.active_for(bound.system_id, bound.generation_id, "qa") is None
        assert executions.active_for(manual.system_id, manual.generation_id, "qa").execution_id == manual.execution_id
        assert service.records.for_execution(manual.execution_id) is None
        stored = observer.get_workflow("coverage_enhancement", workflow.enhancement_id)
        assert stored["status"] == expected and stored[phase]["status"] == "INVALID"
        assert observer.read_execution("case", bound.execution_id)["status"] == "FAILED"
        assert observer.read_execution("case", manual.execution_id)["status"] == "RUNNING"
        saved_task = app.tasks.get(workflow.task_id)
        assert saved_task.status == (TaskStatus.FAILED if phase == "baseline" else TaskStatus.PARTIAL)
        assert saved_task.ended_at is not None
        if phase == "verification":
            assert executions.get(bound.system_id, workflow.baseline_case_execution_id).status == "PASSED"
            assert stored["enhanced_generation_id"] == bound.generation_id
        # 再次观察不新增执行，不重新占用业务门禁，也不会接管普通手动 Case。
        service.recovery._run()
        assert len(executions.list(bound.system_id)) == len(template.executions) + 1
        app.case_template_v4.dispatch_execution.assert_not_called()
        app.case_template_v4.execute_generation.assert_not_called()
        service.analyze.assert_not_called()
        service.advance.assert_not_called()
        service.discovery.discover.assert_not_called()
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        observer.close()
        app.close()


def test_healthy_other_process_is_observed_without_error_or_write(monkeypatch):
    """同工作台另一健康服务不写UNCONFIRMED，也不反复执行ps或进入系统事务。"""

    service = _service()
    service.tasks._owner_is_alive.return_value = True
    kill = Mock(side_effect=AssertionError("healthy owner must not be probed again"))
    monkeypatch.setattr("opentest.application.coverage_recovery.os.kill", kill)
    CoverageRecovery(service)._recover(service.state.workflow)
    assert service.state.workflow.reason_codes == []
    service.records.save.assert_not_called()
    service.app.store.system_transaction.assert_not_called()
    service.tasks._process_start_marker.assert_not_called()


def test_current_owner_valid_analysis_uses_shared_dispatch_entry():
    """分析投递失败后的同进程维护使用共享Future入口，不能等待进程退出才继续。"""

    service = _service(stage="BASELINE_ANALYZING")
    _valid_dump(service, "baseline")
    service.state.task.owner_pid = service.tasks._owner_pid
    service.state.task.owner_instance_id = service.tasks._owner_instance_id
    recovery = CoverageRecovery(service)
    recovery._recover(service.state.workflow)
    service.schedule_analysis.assert_called_once_with(service.state.workflow.enhancement_id, "baseline")
    service.analyze.assert_not_called()
    service.tasks._owner_is_alive.assert_not_called()


def test_terminal_workflow_still_retries_idempotent_finish():
    """工作流终态但报告、专属任务或裁剪未完成时仍进入幂等收尾。"""

    service = _service(workflow_status="PARTIAL", stage="FINISHED")
    service.state.task.owner_pid = service.tasks._owner_pid
    service.state.task.owner_instance_id = service.tasks._owner_instance_id
    CoverageRecovery(service)._recover(service.state.workflow)
    service.finish.assert_called_once_with(service.state.workflow.model_copy(update={"revision": 0, "reason_codes": []}), "PARTIAL", "")
    service.schedule_analysis.assert_not_called()


def test_owner_claim_without_interrupted_case_has_one_winner(monkeypatch):
    """业务早已终态时也原子更新owner/revision，两个恢复者不能同时提交分析。"""

    service = _service(stage="BASELINE_ANALYZING")
    _valid_dump(service, "baseline")
    original = service.state.workflow.model_copy(deep=True)
    old_owner = service.state.task.model_copy(deep=True)
    recovery = CoverageRecovery(service)
    first = recovery._close_interrupted(original, old_owner)
    second = recovery._close_interrupted(original, old_owner)
    assert first is not None and second is None
    assert service.state.workflow.revision == 1
    assert service.state.task.owner_pid == service.tasks._owner_pid
    assert service.state.task.owner_started_at == service.tasks._owner_started_at
    assert service.state.task.owner_instance_id == service.tasks._owner_instance_id
    service.tasks.save_business_record.assert_called_once()
    service.app.case_template_v4.executions.update.assert_not_called()


def test_supplement_claim_persists_original_owner_exit_before_observation():
    """claim后观察前再次退出时，仍能识别无回执的派发未知，不能永久停留RUNNING。"""

    from opentest.application.coverage_supplement import SUPPLEMENT_OWNER_EXITED

    service = _service(stage="SUPPLEMENT_RUNNING")
    service.state.executions[service.state.workflow.baseline_case_execution_id].status = "PASSED"
    recovered = CoverageRecovery(service)._close_interrupted(service.state.workflow, service.state.task)
    assert recovered is not None
    assert SUPPLEMENT_OWNER_EXITED in service.state.workflow.reason_codes
    assert service.state.task.owner_instance_id == service.tasks._owner_instance_id
    service.finish.assert_not_called()
