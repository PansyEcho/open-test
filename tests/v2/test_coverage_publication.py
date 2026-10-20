"""用隔离MySQL验证自动发布的精确覆盖绑定与提交后派发，业务执行使用替身。"""

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.mysql_metadata import MySqlMetadataStore
from opentest.application.case_template_v4 import PreparedCaseExecution
from opentest.application.foundation import OpenTestApplication
from opentest.domain.case_template_v4 import (
    CaseGenerationExecutionRequestV4, CaseGenerationExecutionV4, CaseTemplateGenerationV4,
    CaseTemplatePublicationRequest,
)
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import CoverageAssistancePolicy, SystemDefinition, TaskRecord, TaskStatus, utc_now
from test_case_template_v4_revision import OPERATION_ID, SCAN_ID, SYSTEM_ID, _contract, _handoff, _submission


@pytest.fixture
def publication(tmp_path):
    """构造真实元数据库发布边界，替换模型编译和QA派发，避免业务网络操作。

    Args:
        tmp_path: 测试框架为临时MySQL库派生的独立工作台目录。
    Yields:
        应用、Generation、发布请求及独立读取连接。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    observer = MySqlMetadataStore(application.store.metadata.configuration, application.store.metadata.workspace_id)
    try:
        application.store.register_system(SystemDefinition(system_id=SYSTEM_ID, name="覆盖发布测试",
            source_path=str(tmp_path), coverage_assistance=CoverageAssistancePolicy(enabled=True)))
        task = application.tasks.create_business_record(TaskRecord(task_id="task-" + "a" * 16,
            system_id=SYSTEM_ID, operation="case-generation", trace_id="publication-test",
            target_id=OPERATION_ID, status=TaskStatus.WAITING_FOR_CLIENT, ended_at=utc_now(),
            result={"request_id": "coverage-publication-start"}))
        handoff = _handoff(tmp_path, status="COMPLETED").model_copy(update={"task_id": task.task_id,
            "root_task_id": task.task_id})
        handoff.source_scopes[0].source_baseline.commit = "d" * 40
        application.case_template_v4.handoffs.write(handoff)
        generation = CaseTemplateGenerationV4(generation_id=handoff.generation_id, handoff_id=handoff.handoff_id,
            system_id=SYSTEM_ID, operation_id=OPERATION_ID, source_scan_id=SCAN_ID, source_scopes=handoff.source_scopes,
            status="READY", coverage_id="coverage:fixture", runtime_registry_version="runtime/v1",
            value_registry_version="values/v1", input_contract=_contract(), submission=_submission())
        application.native_task_instruction = Mock(return_value="继续测试任务")
        application.case_template_v4.publish = Mock(return_value=generation)
        application.continue_case_task = Mock(return_value={"task": task})

        def prepare(system_id, generation_id, request):
            """在真实事务内登记RUNNING执行，不触发运行目录或QA。"""
            assert getattr(application.store.metadata._local, "connection", None) is not None
            execution = application.case_template_v4.executions.create(CaseGenerationExecutionV4(
                execution_id="case-generation-execution-" + uuid.uuid4().hex[:20], generation_id=generation_id,
                system_id=system_id, environment_id=request.environment_id, status="RUNNING"))
            return PreparedCaseExecution(execution, generation, None, "publication-test")

        def dispatch(prepared):
            """通过独立连接确认事务已提交后才允许派发替身接管。"""
            assert getattr(application.store.metadata._local, "connection", None) is None
            stored = observer.read_execution("case", prepared.running.execution_id)
            assert stored is not None and stored["generation_id"] == generation.generation_id
            workflow = application.coverage_assistance.records.for_generation(SYSTEM_ID, generation.generation_id)
            if workflow is not None:
                assert observer.get_workflow("coverage_enhancement", workflow.enhancement_id) is not None
                owner = observer.get_workflow("task", workflow.task_id)
                assert owner["owner_pid"] == application.tasks._owner_pid
                assert owner["owner_instance_id"] == application.tasks._owner_instance_id
            return prepared.running

        application.case_template_v4.prepare_execution = Mock(side_effect=prepare)
        application.case_template_v4.dispatch_execution = Mock(side_effect=dispatch)
        yield SimpleNamespace(app=application, generation=generation, handoff=handoff, observer=observer,
            request=CaseTemplatePublicationRequest(request_id="coverage-publication-publish", expected_revision=0, mode="complete"))
    finally:
        observer.close()
        application.close()


def _publish(fixture):
    """使用原发布请求重放真实Foundation编排，返回持久身份的响应。"""

    return fixture.app.publish_case_template_v4(fixture.handoff.handoff_id, fixture.request)


def test_publish_commits_binding_and_owner_before_dispatch(publication):
    """独立连接能读到同事务执行、覆盖绑定和派发owner后，才允许后台接手。"""

    response = _publish(publication)
    workflow = publication.app.coverage_assistance.records.for_generation(SYSTEM_ID, publication.generation.generation_id)
    assert workflow.baseline_case_execution_id == response["execution"].execution_id
    assert workflow.baseline.case_execution_id == response["execution"].execution_id
    assert workflow.stage == "BASELINE_EXECUTING"
    publication.app.case_template_v4.dispatch_execution.assert_called_once()


def test_publication_retry_keeps_exact_binding_after_manual_execution_and_disabled_policy(publication):
    """较新的人工执行和关闭开关都不能替换原发布的精确自动执行。"""

    app = publication.app
    first = _publish(publication)["execution"]
    app.case_template_v4.executions.update(first.model_copy(update={"status": "PASSED"}))
    manual = app.case_template_v4.executions.create(first.model_copy(update={
        "execution_id": "case-generation-execution-" + "e" * 20, "created_at": utc_now(), "updated_at": utc_now(),
    }))
    app.case_template_v4.executions.update(manual.model_copy(update={"status": "PASSED"}))
    system = app.store.get_system(SYSTEM_ID)
    app.store.update_system(SYSTEM_ID, system.model_copy(update={"coverage_assistance": CoverageAssistancePolicy(enabled=False)}))
    repeated = _publish(publication)
    assert repeated["execution"].execution_id == first.execution_id
    assert app.coverage_assistance.records.for_execution(manual.execution_id) is None
    app.case_template_v4.prepare_execution.assert_called_once()
    app.case_template_v4.dispatch_execution.assert_called_once()


def test_nonempty_missing_binding_is_error_not_latest_execution_fallback(publication):
    """非空绑定损坏必须暴露关联错误，不能查最近执行或重派QA。"""

    app = publication.app
    _publish(publication)
    workflow = app.coverage_assistance.records.for_generation(SYSTEM_ID, publication.generation.generation_id)
    app.coverage_assistance.records.save(workflow.model_copy(update={
        "baseline_case_execution_id": "case-generation-execution-" + "f" * 20,
    }))
    with pytest.raises(KnowledgeValidationError, match="绑定"):
        _publish(publication)
    app.case_template_v4.prepare_execution.assert_called_once()
    app.case_template_v4.dispatch_execution.assert_called_once()


def test_partial_base_skips_measurement_but_retains_original_execution_and_successor(publication):
    """PARTIAL仍执行原验证及后继，覆盖工作流直接跳过且不认领该执行。"""

    app = publication.app
    publication.generation.status = "PARTIAL"
    publication.request.mode = "available"
    response = _publish(publication)
    workflow = app.coverage_assistance.records.for_generation(SYSTEM_ID, publication.generation.generation_id)
    assert workflow.status == "SKIPPED" and workflow.reason_codes == ["BASE_GENERATION_PARTIAL"]
    assert not workflow.baseline_case_execution_id
    assert app.coverage_assistance.records.for_execution(response["execution"].execution_id) is None
    app.continue_case_task.assert_called_once()
    app.case_template_v4.dispatch_execution.assert_called_once()


def test_generate_only_does_not_register_or_execute_coverage(publication):
    """明确只生成时不登记自动执行，也不建立需要reset的覆盖绑定。"""

    publication.generation.execution_mode = "generate_only"
    response = _publish(publication)
    assert "execution" not in response and response["coverage_assistance"] is None
    publication.app.case_template_v4.prepare_execution.assert_not_called()
    publication.app.case_template_v4.dispatch_execution.assert_not_called()


def test_registration_failure_rolls_back_execution_and_never_dispatches(publication):
    """增强关联写入失败时同一事务回滚新执行，不把未提交身份交给后台。"""

    app = publication.app
    original_register = app.coverage_assistance.register

    def fail_after_register(generation, execution):
        """模拟已写覆盖/owner但事务尚未提交时发生故障。"""
        original_register(generation, execution)
        raise RuntimeError("registration interrupted")

    app.coverage_assistance.register = Mock(side_effect=fail_after_register)
    with pytest.raises(RuntimeError, match="registration interrupted"):
        _publish(publication)
    assert app.case_template_v4.list_executions(SYSTEM_ID, publication.generation.generation_id) == []
    assert app.coverage_assistance.records.for_generation(SYSTEM_ID, publication.generation.generation_id) is None
    app.case_template_v4.dispatch_execution.assert_not_called()


def test_manual_execution_is_not_registered_as_coverage_baseline(publication):
    """手动执行沿用Case入口，但没有自动绑定就不能发现实例、reset或采集。"""

    app = publication.app
    execution = app.case_template_v4.executions.create(CaseGenerationExecutionV4(
        execution_id="case-generation-execution-" + "f" * 20, generation_id=publication.generation.generation_id,
        system_id=SYSTEM_ID, environment_id="qa", status="RUNNING"))
    app.case_template_v4.prepare_execution = Mock(return_value=PreparedCaseExecution(
        execution, publication.generation, None, "manual-test"))
    app.coverage_assistance.discovery.discover = Mock(side_effect=AssertionError("manual must not discover"))
    # 仅替换QA派发，直接经过原手动执行方法，不能通过发布register建立增强身份。
    dispatched = app.case_template_v4.execute_generation(SYSTEM_ID, publication.generation.generation_id,
        CaseGenerationExecutionRequestV4(environment_id="qa"), background=True)
    assert dispatched.execution_id == execution.execution_id
    assert app.coverage_assistance.execution_starting(execution) is None
    assert app.coverage_assistance.records.for_execution(execution.execution_id) is None
    app.coverage_assistance.discovery.discover.assert_not_called()
