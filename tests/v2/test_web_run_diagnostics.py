"""验证网页Case和知识任务读取真实运行身份，不误用prepare阶段证据。"""

import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from opentest.api import create_app
from opentest.domain.models import TaskProgress
from test_web_generation import _application, TASK_ID


@pytest.mark.parametrize("operation", ["case-generation", "knowledge-codex-client-handoff"])
@pytest.mark.parametrize("session_id", ["", "01a07f9e-9714-7802-be33-10013769eb84"])
def test_web_diagnostics_uses_bound_run_without_resuming(tmp_path, operation, session_id):
    """HTTP诊断使用web run，兼容启动中无会话和已形成会话的状态。

    Args:
        tmp_path: 隔离任务与真实证据文件根。
        operation: Case或知识任务类型。
        session_id: 尚未建立或已建立的Codex聊天身份。
    Returns:
        None；旧run不被读取且诊断不启动或续跑Agent时通过。
    """

    application, _ = _application(tmp_path)
    run_id = "agent-1234567890abcdef"
    diagnostic_task_id = "task-2222222222222222"
    task = application.tasks.get(TASK_ID)
    application.tasks.create_business_record(task.model_copy(update={
        "task_id": diagnostic_task_id, "operation": operation,
        "interaction_mode": "web", "web_run_id": run_id,
        "progress": TaskProgress(task_id=diagnostic_task_id, operation=operation, status=task.status,
                                 agent_run_id="agent-0000000000000000"),
    }))
    # 只为真实网页run写证据，旧prepare run不存在，任何错误选择都会导致请求失败。
    root = application.knowledge_root / ".opentest" / "agent-runs" / run_id
    root.mkdir(parents=True)
    (root / "worker-request.json").write_text(json.dumps({"agent": "codex"}))
    (root / "state.json").write_text(json.dumps({"session_id": session_id, "status": "running"}))
    runner = Mock()
    application.agent_runner = runner
    with TestClient(create_app(application)) as client:
        response = client.get(f"/api/v2/tasks/{diagnostic_task_id}/agent-diagnostics")
    assert response.status_code == 200
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["run_id"] == run_id
    assert diagnostics["session_id"] == session_id
    assert diagnostics["resume_command"] == ""
    runner.run.assert_not_called()
    runner.attach.assert_not_called()


def test_missing_run_evidence_does_not_break_task_context(tmp_path):
    """诊断文件尚未落盘只影响诊断请求，Case草稿上下文仍可读取。

    Args:
        tmp_path: 隔离任务和草稿存储。
    Returns:
        None；上下文保持可读且不会返回假session时通过。
    """

    application, _ = _application(tmp_path)
    task = application.tasks.get(TASK_ID)
    application.tasks.save_business_record(task.model_copy(update={
        "interaction_mode": "web", "web_run_id": "agent-1234567890abcdef",
    }))
    # 无证据的预分配run不能被冒充为已建立的聊天；业务草稿不依赖诊断可用性。
    with TestClient(create_app(application)) as client:
        unavailable = client.get(f"/api/v2/tasks/{TASK_ID}/agent-diagnostics")
        context = client.get(f"/api/v2/tasks/{TASK_ID}/context")
    assert unavailable.status_code == 400
    assert context.status_code == 200
    assert context.json()["context"]["handoff"] is not None
