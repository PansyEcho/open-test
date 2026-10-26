"""验证覆盖窗口不会改变 Case 结果，finally 与准确绑定覆盖异常和重试。"""

from contextlib import nullcontext
from pathlib import Path
import shutil
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from opentest.adapters.coverage import CoverageUnavailable
from opentest.adapters.case_template_v4_store import CaseGenerationExecutionStoreV4
from opentest.application.case_template_v4 import CaseTemplateV4Service, CaseTemplateV4RuntimeServices
from opentest.application.coverage_assistance import (
    ActiveCoverageMeasurement, COVERAGE_PREFLIGHT_SECONDS, CoverageAssistanceService,
)
from opentest.domain.case_template_v4 import CaseGenerationExecutionRequestV4, CaseGenerationExecutionV4
from opentest.domain.coverage import (
    ArtifactFileIdentity, CoverageArtifactSelection, CoverageAnalysisResult, CoverageCounts,
    DiscoveredCoverageInstance, FrozenCoverageArtifact, JacocoCapture,
)
from opentest.domain.coverage_workflow import CoverageEnhancement, CoverageReport
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import utc_now
from test_case_template_v4 import _create_order_generation


def case_service(tmp_path: Path) -> CaseTemplateV4Service:
    """组装真实 Execution store，替换业务执行和源码目录以隔离测量编排测试。"""

    generation = _create_order_generation()
    generations, handoffs = Mock(), Mock()
    generations.get.return_value = generation
    handoffs.get.return_value = SimpleNamespace(system_id=generation.system_id,
        generation_id=generation.generation_id, source_scopes=[], model_copy=Mock())
    runtime = CaseTemplateV4RuntimeServices(Mock(), Mock(), Mock(), Mock(), CaseGenerationExecutionStoreV4(tmp_path))
    service = CaseTemplateV4Service(Mock(), Mock(), generations, handoffs, runtime)
    # 测试关心提交/执行边界，固定目录解析不访问目标项目或业务环境。
    service._runtime_registry_for_execution = Mock(return_value=SimpleNamespace())
    service._generation_scope_selection = Mock(return_value=SimpleNamespace())
    service._runtime_capabilities = Mock(return_value=[])
    service.coverage_assistance = Mock()
    return service


def workflow() -> CoverageEnhancement:
    """构造具有精确 QA 基线绑定的增强，避免测试以最新执行冒充绑定。"""

    return CoverageEnhancement(enhancement_id="coverage-unit", task_id="task-" + "1" * 16,
        system_id="refund", operation_id="Api#query", base_generation_id="generation-base",
        source_scan_id="scan-fixture", source_commit="a" * 40, stage="BASELINE_EXECUTING",
        baseline_case_execution_id="case-bound")


def assistance() -> CoverageAssistanceService:
    """隔离覆盖服务外部依赖；每次读取返回同一持久模型的深拷贝。"""

    service = object.__new__(CoverageAssistanceService)
    service.app, service.records, service.tasks = Mock(), Mock(), Mock()
    # 本组旧材料编排测试显式不配置S3；共享材料读取由专门的跨机器测试覆盖。
    service.app.object_storage = None
    service._analysis_lock, service._analysis_futures = RLock(), {}
    service.tasks._owner_pid = 42
    service.tasks._owner_instance_id = "test-instance"
    service.tasks._owner_started_at = "test-start"
    service.tasks.get.return_value = SimpleNamespace(owner_pid=42, owner_instance_id="test-instance", owner_started_at="test-start")
    service.discovery, service.artifacts = Mock(), Mock()
    record = workflow()
    service.records.for_execution.return_value = record
    service.records.get.return_value = record
    service.records.save.side_effect = lambda item: item
    service.app.store.system_transaction.return_value = nullcontext()
    service.sync_task = Mock()
    service.finish = Mock(side_effect=lambda item, status, reason: item)
    return service


def active_window(tmp_path: Path) -> ActiveCoverageMeasurement:
    """构造一个已获 reset 成功确认的窗口，不使用真实实例或凭据。"""

    artifact = FrozenCoverageArtifact(selection=CoverageArtifactSelection(app_uk="fixture"),
        commit="a" * 40, transport="LOCAL", artifact=ArtifactFileIdentity(path="/fixture/app.war", size=1, modified="1"),
        source=ArtifactFileIdentity(path="/fixture/source.tar.gz", size=1, modified="1"))
    target = DiscoveredCoverageInstance(ip="127.0.0.1", port=6300, app_uk="fixture", log_time=utc_now())
    collector = Mock()
    path = tmp_path / "coverage.exec"
    path.write_bytes(b"fixture-exec")
    collector.dump.return_value = JacocoCapture(path=path, captured_at=utc_now())
    return ActiveCoverageMeasurement("coverage-unit", "baseline", target, artifact, collector, Mock())


def test_prepare_defers_submit_until_explicit_dispatch(tmp_path: Path) -> None:
    """登记执行不会提交线程，调用方可以先完成绑定事务再派发。"""

    service = case_service(tmp_path)
    generation = service.generations.get.return_value
    prepared = service.prepare_execution(generation.system_id, generation.generation_id,
        CaseGenerationExecutionRequestV4(environment_id="qa"))
    service.runtime.task_manager._executor.submit.assert_not_called()
    assert service.executions.get(generation.system_id, prepared.running.execution_id).status == "RUNNING"
    service.dispatch_execution(prepared)
    service.runtime.task_manager._executor.submit.assert_called_once()


@pytest.mark.parametrize("broken", [False, True])
def test_finish_always_syncs_coverage_and_preserves_case_outcome(tmp_path: Path, broken: bool) -> None:
    """真实执行出口在成功或业务异常时都进入覆盖 finally，业务失败仍向上抛出。"""

    service = case_service(tmp_path)
    generation = service.generations.get.return_value
    prepared = service.prepare_execution(generation.system_id, generation.generation_id,
        CaseGenerationExecutionRequestV4(environment_id="qa"))
    with patch("opentest.application.case_template_v4.CaseTemplateExecutorV4") as executor:
        executor.return_value.execute.return_value = []
        if broken:
            executor.return_value.execute.side_effect = ValueError("business failed")
            with pytest.raises(ValueError, match="business failed"):
                service._finish_execution(prepared.running, generation, prepared.runtime_registry, "trace")
        else:
            service._finish_execution(prepared.running, generation, prepared.runtime_registry, "trace")
    service.coverage_assistance.execution_starting.assert_called_once_with(prepared.running)
    service.coverage_assistance.execution_finished.assert_called_once()
    stored = service.executions.get(generation.system_id, prepared.running.execution_id)
    assert stored.status != "RUNNING"
    if broken:
        assert stored.status == "FAILED"


def test_setup_failure_still_finishes_dedicated_task(tmp_path: Path) -> None:
    """运行目录构建异常尚未 reset，也必须经过同一 finally 终结专属任务。"""

    service = case_service(tmp_path)
    generation = service.generations.get.return_value
    prepared = service.prepare_execution(generation.system_id, generation.generation_id,
        CaseGenerationExecutionRequestV4(environment_id="qa"))
    service._generation_scope_selection.side_effect = ValueError("catalog failed")
    with pytest.raises(ValueError, match="catalog failed"):
        service._finish_execution(prepared.running, generation, prepared.runtime_registry, "trace")
    service.coverage_assistance.execution_starting.assert_not_called()
    service.coverage_assistance.execution_finished.assert_called_once_with(prepared.running, None)


def test_closed_pool_settles_before_finish_entry(tmp_path: Path) -> None:
    """submit 失败没有进入执行器，但必须释放 RUNNING 身份并同步专属任务。"""

    service = case_service(tmp_path)
    generation = service.generations.get.return_value
    prepared = service.prepare_execution(generation.system_id, generation.generation_id,
        CaseGenerationExecutionRequestV4(environment_id="qa"))
    service.runtime.task_manager._executor.submit.side_effect = RuntimeError("closed")
    failed = service.dispatch_execution(prepared)
    assert failed.status == "FAILED"
    service.coverage_assistance.execution_finished.assert_called_once_with(prepared.running, None)


def test_unbound_manual_execution_never_discovers_or_resets() -> None:
    """相同系统/QA/后台属性不足以取得 reset 权限，必须存在精确执行绑定。"""

    service = assistance()
    service.records.for_execution.return_value = None
    assert service.execution_starting(SimpleNamespace(execution_id="manual", system_id="refund")) is None
    service.discovery.discover.assert_not_called()
    service.records.measurement_lock.assert_not_called()


def test_no_reset_permission_skips_only_coverage() -> None:
    """未授权 reset 时不访问日志或实例，降级原因不变成 Case 执行失败。"""

    service = assistance()
    service.app.local_settings.read_coverage_connection.return_value = None
    execution = SimpleNamespace(execution_id="case-bound", system_id="refund", generation_id="generation-base", environment_id="qa")
    assert service.execution_starting(execution) is None
    assert service.finish.call_args.args[1:] == ("SKIPPED", "RESET_NOT_AUTHORIZED")
    service.discovery.discover.assert_not_called()


def test_preflight_budget_is_temporarily_180_seconds(monkeypatch) -> None:
    """预检预算先临时放宽到 180 秒，避免发现和取材耗时叠加后无法进入测量。"""

    service = assistance()
    now = 1000.0
    service.app.local_settings.read_coverage_connection.return_value = SimpleNamespace(
        jacoco_reset_allowed=True, skyeye_endpoint="", jacoco_port=6300,
        skyeye_log_environment_override="")
    service.app.local_settings.read_skyeye_settings.return_value = SimpleNamespace(
        skyeye_app_id="fixture", skyeye_api_token="fixture")
    service.app.runtime_settings.read.return_value = SimpleNamespace(
        jacoco_java_command="java", jacoco_cli_path="/fixture/jacococli.jar")
    service.records.measurement_lock.side_effect = CoverageUnavailable("COVERAGE_LOCK_BUSY", "锁忙")
    monkeypatch.setattr("opentest.application.coverage_assistance.time.monotonic", lambda: now)
    execution = SimpleNamespace(execution_id="case-bound", system_id="refund",
                                generation_id="generation-base", environment_id="qa")
    assert service.execution_starting(execution) is None
    assert service.records.measurement_lock.call_args.args == ("refund", now + 180.0, "qa")
    assert COVERAGE_PREFLIGHT_SECONDS == 180.0


def test_dump_timeout_releases_lock_and_syncs_task(tmp_path: Path) -> None:
    """dump 异常与释放异常不能越过 finally 或修改已经保存的真实业务终态。"""

    service = assistance()
    active = active_window(tmp_path)
    active.collector.dump.side_effect = CoverageUnavailable("JACOCO_COMMAND_TIMEOUT", "timeout")
    active.lease.release.side_effect = OSError("connection lost")
    execution = SimpleNamespace(execution_id="case-bound", system_id="refund")
    service.execution_finished(execution, active)
    active.lease.release.assert_called_once()
    service.sync_task.assert_called_once()
    service.app.case_template_v4.executions.update.assert_not_called()
    service.tasks._executor.submit.assert_not_called()


def test_capture_persists_before_readonly_analysis_dispatch(tmp_path: Path) -> None:
    """成功 dump 先写压缩材料和阶段；分析提交只发生在锁释放和事务提交之后。"""

    service = assistance()
    active = active_window(tmp_path)
    service.records.report.return_value = None
    service.app.case_template_v4.executions.get.return_value = SimpleNamespace(status="PASSED")
    execution = SimpleNamespace(execution_id="case-bound", system_id="refund")
    service.execution_finished(execution, active)
    active.lease.release.assert_called_once()
    report = service.records.save_report.call_args.args[0]
    assert isinstance(report, CoverageReport) and report.result["baseline"].exec_base64
    assert service.records.save.call_args.args[0].stage == "BASELINE_ANALYZING"
    service.tasks._executor.submit.assert_called_once_with(service.analyze, "coverage-unit", "baseline")
    service.app.case_template_v4.executions.update.assert_not_called()


def test_report_write_failure_preserves_business_result_and_never_dispatches_analysis(tmp_path: Path) -> None:
    """报告写入失败只能结束覆盖测量，不能伪造有效分析或覆盖已保存的业务成功。

    Args:
        tmp_path: 虚构 dump 文件目录，不连接真实 JaCoCo 或业务环境。
    """

    service = assistance()
    active = active_window(tmp_path)
    service.records.report.return_value = None
    service.records.get.return_value.baseline.reset_at = utc_now()
    service.app.case_template_v4.executions.get.return_value = SimpleNamespace(status="PASSED")
    service.records.save_report.side_effect = OSError("simulated report storage unavailable")
    execution = SimpleNamespace(execution_id="case-bound", system_id="refund")
    service.execution_finished(execution, active)
    # dump 已完成仍需释放锁；报告未保存时不推进有效分析阶段或派发后续步骤。
    active.lease.release.assert_called_once()
    service.records.save.assert_not_called()
    service.tasks._executor.submit.assert_not_called()
    failed = service.finish.call_args.args[0]
    assert failed.baseline.status == "INVALID"
    assert failed.baseline.reason_codes == ["COVERAGE_CAPTURE_FAILED"]
    assert failed.baseline.dump_at is None
    assert service.finish.call_args.args[1:] == ("SKIPPED", "COVERAGE_CAPTURE_FAILED")
    service.app.case_template_v4.executions.update.assert_not_called()
    service.sync_task.assert_called_once()


def test_exact_retry_rejects_other_environment_even_if_generation_matches() -> None:
    """非空绑定指向 UAT 时报告关联错误，不能退回最新 QA 或手动执行。"""

    service = assistance()
    service.records.for_generation.return_value = workflow()
    generation = SimpleNamespace(system_id="refund", generation_id="generation-base")
    service.app.case_template_v4.executions.get.return_value = SimpleNamespace(system_id="refund", generation_id="generation-base", environment_id="uat")
    with pytest.raises(KnowledgeValidationError, match="不匹配"):
        service.bound_execution(generation)
    service.app.case_template_v4.list_executions.assert_not_called()


def test_analysis_model_roundtrips_without_temporary_paths(tmp_path: Path) -> None:
    """持久工作流必须能省略临时 XML/HTML 重新读取，浏览器不获得本机路径。"""

    counts = CoverageCounts(method={"covered": 0, "missed": 1}, line={"covered": 0, "missed": 1}, branch={"covered": 0, "missed": 0})
    analysis = CoverageAnalysisResult(raw_counts=counts, scope_counts=counts, matched_class_count=1,
        uncomparable_class_count=0, scope_reason="resolved only", candidate_gap_count=0, deferred_gap_count=0,
        xml_path=tmp_path / "coverage.xml", html_path=tmp_path / "index.html")
    record = workflow()
    record.baseline.analysis = analysis
    payload = record.model_dump(mode="json")
    assert "xml_path" not in payload["baseline"]["analysis"]
    assert CoverageEnhancement.model_validate(payload).baseline.analysis.class_match == "MATCHED"


def test_html_download_uses_valid_baseline_when_verification_is_invalid(tmp_path: Path) -> None:
    """失败复测不能隐藏有效基线，下载只重建已保存材料且不触发网络采集。"""

    service = assistance()
    record = workflow()
    record.baseline.status = "VALID"
    counts = CoverageCounts(method={"covered": 0, "missed": 1}, line={"covered": 0, "missed": 1}, branch={"covered": 0, "missed": 0})
    record.baseline.analysis = CoverageAnalysisResult(raw_counts=counts, scope_counts=counts,
        matched_class_count=1, uncomparable_class_count=0, scope_reason="resolved", candidate_gap_count=0, deferred_gap_count=0)
    record.verification.status = "INVALID"
    # 该测试只验证有效阶段选择，员工和当前Case可见性另有边界测试。
    service._visible_workflow = Mock(return_value=record)
    active = active_window(tmp_path)
    from opentest.domain.coverage_workflow import CoverageRawCapture
    raw = CoverageRawCapture(exec_base64="Zml4dHVyZQ==", artifact=active.artifact)
    service.records.for_generation.return_value = record
    service.records.report.return_value = CoverageReport(execution_id=record.enhancement_id, system_id="refund",
        generation_id=record.base_generation_id, operation_id=record.operation_id,
        result={"baseline": raw, "verification": raw})
    service.app.store.metadata.workspace_id = "test-owner"
    service.app.store.metadata.fetch_one.return_value = {"owner_workspace_id": "test-owner"}
    service.app.runtime_settings.read.return_value = SimpleNamespace(jacoco_java_command="java", jacoco_cli_path="fixture.jar")
    html = tmp_path / "html"
    html.mkdir()
    (html / "index.html").write_text("fixture HTML")
    with patch("opentest.application.coverage_assistance.scope_from_manifest"), patch("opentest.application.coverage_assistance.CoverageAnalyzer") as analyzer:
        analyzer.return_value.analyze.return_value = SimpleNamespace(html_path=html / "index.html")
        archive = service.html_report("refund", record.base_generation_id)
    try:
        assert archive.is_file()
        service.artifacts.materialize.assert_called_once()
        service.discovery.discover.assert_not_called()
    finally:
        # 清理下载测试自身的临时材料，避免覆盖报告写到开发工作台长期目录。
        shutil.rmtree(archive.parent)
