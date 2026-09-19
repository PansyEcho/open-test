"""验证共享数据HTTP入口区分方法补充与显式执行，并复用统一任务接口。"""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.data_capabilities import DataExecution
from opentest.domain.models import TaskRecord, TaskStatus, utc_now


@dataclass
class PublishedCapability:
    """HTTP路由测试的最小已发布目录投影，避免伪造完整源码证据。"""

    capability_id: str
    name: str
    purpose: str
    version: int


def test_shared_data_http_prepare_does_not_execute_and_preserves_run_inputs(tmp_path: Path) -> None:
    """准备接口只生成任务，执行接口原样传条件并要求本机调用。

    Args:
        tmp_path: 隔离任务存储，测试不访问QA或真实模型。
    Returns:
        None；读目录、固定版本、原生准备和异步执行请求契约一致时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    task = TaskRecord(task_id="task-" + "a" * 16, system_id="refund", operation="data-capability-generation",
                      status=TaskStatus.WAITING_FOR_CLIENT, trace_id="api-shared", ended_at=utc_now(), result={"request_id":"api-prepare-001"})
    application.tasks.create_business_record(task)
    capability = PublishedCapability(capability_id="refund_report", name="退票报表", purpose="ARC退票补单", version=1)
    execution = DataExecution(execution_id="data-1", system_id="refund", capability_id="refund_report",
                              capability_version=1, task_id=task.task_id, environment_id="qa",
                              inputs={"ticket_no": "fixed", "owner_id": "owner"})
    service = SimpleNamespace(list_capabilities=Mock(return_value=[capability]), get_version=Mock(return_value=capability),
                              prepare=Mock(return_value=task), execute=Mock(return_value=execution),
                              list_executions=Mock(return_value=[execution]), get_execution=Mock(return_value=execution))
    application.data_capabilities = service
    application.web_generation.start = Mock(return_value=task)
    client = TestClient(create_app(application), client=("127.0.0.1", 51000))
    try:
        assert len(client.get("/api/v2/systems/refund/data-capabilities?query=ARC").json()["capabilities"]) == 1
        assert client.get("/api/v2/systems/refund/data-capabilities?query=missing").json()["capabilities"] == []
        assert client.get("/api/v2/systems/refund/data-capabilities/refund_report/versions/1?owner_system_id=refund").json()["capability"]["version"] == 1
        service.get_version.assert_called_once_with("refund", "refund_report", 1, "refund")
        prepared = client.post("/api/v2/systems/refund/data-capabilities/prepare", json={
            "goal": "准备指定票号数据", "interaction_mode": "native", "request_id": "prepare-001",
        })
        assert prepared.status_code == 201
        assert prepared.json()["task"]["task_id"] == task.task_id
        service.execute.assert_not_called()
        application.web_generation.start.assert_not_called()
        # 准备阶段不会访问QA；唯一执行请求显式携带原条件与禁止写的决策。
        request = {"version": 1, "environment_id": "qa", "inputs": execution.inputs,
                   "allow_writes": False, "request_id": "execution-001"}
        response = client.post("/api/v2/systems/refund/data-capabilities/refund_report/executions", json=request)
        assert response.status_code == 201
        assert response.json()["execution"]["inputs"] == execution.inputs
        assert service.execute.call_args.kwargs == {"background": True}
        passed_request = service.execute.call_args.args[2]
        assert passed_request.inputs == execution.inputs
        assert passed_request.allow_writes is False
        assert passed_request.version == 1
        assert passed_request.request_id == "execution-001"
        assert client.get("/api/v2/systems/refund/data-executions/data-1").json()["execution"]["execution_id"] == "data-1"
        assert len(client.get("/api/v2/systems/refund/data-executions").json()["executions"]) == 1
        invalid = client.post("/api/v2/systems/refund/data-capabilities/refund_report/executions", json={**request, "inputs": []})
        assert invalid.status_code == 422
        assert service.execute.call_count == 1
        remote = TestClient(create_app(application), client=("192.0.2.1", 51000))
        assert remote.post("/api/v2/systems/refund/data-capabilities/refund_report/executions", json=request).status_code == 409
        assert service.execute.call_count == 1
    finally:
        application.close()


@pytest.mark.parametrize("operation,kind", [("data-capability-generation", "data_capability"), ("contract-completion", "contract")])
def test_shared_runner_requires_readable_publication_and_uses_scoped_tools(tmp_path: Path, operation: str, kind: str) -> None:
    """共享任务只有权威产物可读才成功，且新工具不会回落到旧知识Schema。

    Args:
        tmp_path: 隔离任务目录。
        operation: 数据方法或契约补充任务操作。
        kind: 相应上下文类型与正式产物键。
    Returns:
        None；无产物的completed任务被纠正，有产物可完成且工具正确委托时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    task = TaskRecord(task_id="task-" + "b" * 16, system_id="refund", operation=operation,
                      status=TaskStatus.WAITING_FOR_CLIENT, trace_id="shared-settle", ended_at=utc_now(), result={"request_id":"runner-prepare-001"})
    application.tasks.create_business_record(task)
    application.tasks.save_business_record(task.model_copy(update={"status": TaskStatus.COMPLETED, "web_run_active": True}))
    context = {"kind": kind, "questions": [], "revision": 0, "handoff": {"goal": "补单"}}
    application.get_task_context = Mock(side_effect=lambda _: context)
    service = SimpleNamespace(agent_tools=Mock(return_value=[{"name": "read_context"}]),
                              call_agent_tool=Mock(return_value={"kind": kind}))
    application.data_capabilities = service
    try:
        application.web_generation._settle(task.task_id, "")
        failed = application.tasks.get(task.task_id)
        assert failed.status == TaskStatus.FAILED
        assert failed.web_run_active is False
        assert "尚未发布" in failed.error
        # 正式产物来自服务回读，Agent或Task单独自述completed不作为发布证据。
        context["capability" if kind == "data_capability" else "contract"] = {"version": 1}
        application.web_generation._settle(task.task_id, "")
        assert application.tasks.get(task.task_id).status == TaskStatus.COMPLETED
        assert application.web_generation.tool_definitions(task.task_id) == [{"name": "read_context"}]
        assert application.web_generation.call_tool(task.task_id, "read_context", {}) == {"kind": kind}
        service.agent_tools.assert_called_once_with(task.task_id)
        service.call_agent_tool.assert_called_once_with(task.task_id, "read_context", {})
        prompt = application.web_generation._analysis_prompt(task)
        assert "不调用QA" in prompt
        assert "正式产物保存成功" in prompt
        assert "八个业务章节" not in prompt
    finally:
        application.close()
