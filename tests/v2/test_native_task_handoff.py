"""验证网页生成退出后同一Codex会话接续的HTTP及单执行者边界。"""

import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from opentest.adapters.agent_runner import AgentRunner
from opentest.api import create_app
from opentest.domain.models import TaskStatus
from test_web_generation import _application, _wait_settled, ControlledAgent, TASK_ID


SESSION_ID = "01a0ae74-0512-79c3-959a-aea3f2b88505"


def _save_run_evidence(application, **state_changes):
    """写入隔离Runner证据，以真实读取器验证交接而不启动Codex。

    Args:
        application: 使用临时知识根的应用。
        state_changes: 覆盖状态或进程ID，模拟活跃与停止边界。
    Returns:
        写入的运行状态路径，供后续断言使用。
    """

    task = application.tasks.get(TASK_ID)
    run_root = application.web_generation.evidence_root / task.web_run_id
    run_root.mkdir(parents=True, exist_ok=True)
    # 只有合法Codex身份和完整终态才允许生成可打开的会话链接。
    state = {"status": "completed", "session_id": SESSION_ID,
             "worker_pid": 900001, "agent_pid": 900002, **state_changes}
    (run_root / "worker-request.json").write_text(json.dumps({"agent": "codex"}))
    state_path = run_root / "state.json"
    state_path.write_text(json.dumps(state))
    return state_path


def test_native_handoff_preserves_question_and_does_not_restart_after_answer(tmp_path, monkeypatch):
    """同一任务在Codex回答后正常发布并由网页回显，期间不启动第二个网页执行者。

    Args:
        tmp_path: 隔离任务、handoff和Runner证据目录。
        monkeypatch: 将隔离的两个虚构PID标记为已退出。
    Returns:
        None；交接幂等、原问题被回答、正式产物可回读且网页启动次数仍为一时通过。
    """

    application, handoff = _application(tmp_path)
    runner = ControlledAgent(application)
    application.web_generation.runner = runner
    monkeypatch.setattr(AgentRunner, "_process_alive", Mock(return_value=False))
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        # 真实网页协调器先自动运行并保存问题，交接不替代首次启动。
        application.web_generation.start(TASK_ID, "native-handoff-start", 0)
        stopped = _wait_settled(application)
        _save_run_evidence(application)
        request = {"request_id": "native-handoff-request", "expected_revision": 1}
        first = client.post(f"/api/v2/tasks/{TASK_ID}/native-handoff", json=request)
        repeated = client.post(f"/api/v2/tasks/{TASK_ID}/native-handoff", json=request)
        assert first.status_code == repeated.status_code == 200
        payload = first.json()
        assert payload["deep_link"] == f"codex://threads/{SESSION_ID}"
        assert payload["task"]["interaction_mode"] == "native"
        assert payload["task"]["web_run_id"] == stopped.web_run_id
        assert payload["task"]["active_handoff_id"] == handoff.handoff_id
        assert application.get_task_context(TASK_ID)["revision"] == 1
        assert runner.calls == 1

        # Codex保存答案使用原HTTP/MCP契约，转native后不能再调用网页Runner。
        answered = client.post(f"/api/v2/tasks/{TASK_ID}/answers", json={
            "request_id": "native-handoff-answer", "expected_revision": 1,
            "question_id": "case-question-web", "answer": "允许取消", "outcome": "answered",
        })
        assert answered.status_code == 200
        assert application.get_task_context(TASK_ID)["revision"] == 2
        assert application.get_task_context(TASK_ID)["questions"][0].answer == "允许取消"
        assert application.tasks.get(TASK_ID).status == TaskStatus.WAITING_FOR_CONFIRMATION
        assert not application.tasks.get(TASK_ID).web_pending_answer_request
        assert runner.calls == 1
        assert client.post(f"/api/v2/tasks/{TASK_ID}/runs", json={
            "request_id": "native-handoff-forbidden-run", "expected_revision": 2,
        }).status_code == 409
        # 响应丢失重试仍返回最初交接，不能因用户已答题而改变原回执。
        assert client.post(f"/api/v2/tasks/{TASK_ID}/native-handoff", json=request).status_code == 200
        assert client.post(f"/api/v2/tasks/{TASK_ID}/native-handoff", json={
            **request, "expected_revision": 2,
        }).status_code == 409
        assert application.get_task_agent_diagnostics(TASK_ID).session_id == SESSION_ID
        assert application.get_task_agent_diagnostics(TASK_ID).resume_command == ""

        # native会话落实答案时直接使用原任务的修订/发布协议，不再次调用网页run。
        runner.publish()
        completed_response = client.get(f"/api/v2/tasks/{TASK_ID}")
        assert completed_response.status_code == 200
        completed_task = completed_response.json()["task"]
        assert completed_task["task_id"] == TASK_ID
        assert completed_task["active_handoff_id"] == handoff.handoff_id
        assert completed_task["status"] == "completed"
        assert completed_task["interaction_mode"] == "native"
        assert not completed_task["web_run_active"]
        generation_response = client.get(
            f"/api/v2/systems/{handoff.system_id}/case-generations/{completed_task['generation_id']}"
        )
        assert generation_response.status_code == 200
        generation = generation_response.json()["generation"]
        assert generation["generation_id"] == completed_task["generation_id"]
        assert generation["handoff_id"] == handoff.handoff_id
        assert generation["status"] == "READY"
        assert generation["variants"]
        assert runner.calls == 1
    finally:
        application.close()


@pytest.mark.parametrize("active_boundary", ["task", "observer", "worker", "agent", "missing_state", "running_state"])
def test_native_handoff_rejects_every_active_or_unproven_boundary(tmp_path, monkeypatch, active_boundary):
    """拒绝仍有执行者或缺少退出证据的移交，失败不泄露可打开的链接。

    Args:
        tmp_path: 隔离任务及运行证据。
        monkeypatch: 精确控制两个模拟进程的存活状态。
        active_boundary: 任务、观察者、worker、Agent或证据未就绪边界。
    Returns:
        None；HTTP为409且原任务仍归网页执行时通过。
    """

    application, _ = _application(tmp_path)
    task = application.tasks.get(TASK_ID)
    application.tasks.save_business_record(task.model_copy(update={
        "interaction_mode": "web", "web_run_id": "agent-1234567890abcdef",
        "web_run_active": active_boundary == "task",
    }))
    state_path = _save_run_evidence(application, status="running" if active_boundary == "running_state" else "completed")
    if active_boundary == "missing_state":
        state_path.unlink()
    if active_boundary == "observer":
        application.web_generation._observing.add(TASK_ID)
    alive_pid = 900001 if active_boundary == "worker" else 900002 if active_boundary == "agent" else 0
    monkeypatch.setattr(AgentRunner, "_process_alive", Mock(side_effect=alive_pid.__eq__))
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        # 检查只能读取证据；不得取消进程、启动桌面或修改原草稿。
        response = client.post(f"/api/v2/tasks/{TASK_ID}/native-handoff", json={
            "request_id": "native-handoff-rejected", "expected_revision": 0,
        })
        assert response.status_code == 409
        assert "deep_link" not in response.json()
        assert application.tasks.get(TASK_ID).interaction_mode == "web"
        assert "native_handoff" not in application.tasks.get(TASK_ID).result
    finally:
        application.web_generation._observing.discard(TASK_ID)
        application.close()


def test_native_handoff_checks_current_revision_and_session(tmp_path, monkeypatch):
    """过期页面和缺少真实会话身份的运行不能改变执行归属。

    Args:
        tmp_path: 隔离任务与证据目录。
        monkeypatch: 将模拟进程标记为退出。
    Returns:
        None；版本冲突和无会话均拒绝且保留web归属时通过。
    """

    application, _ = _application(tmp_path)
    task = application.tasks.get(TASK_ID)
    application.tasks.save_business_record(task.model_copy(update={
        "interaction_mode": "web", "web_run_id": "agent-1234567890abcdef",
    }))
    _save_run_evidence(application, session_id="agent-is-not-a-thread")
    monkeypatch.setattr(AgentRunner, "_process_alive", Mock(return_value=False))
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        # 页面revision必须先与权威草稿一致，合法版本也不能接受伪会话ID。
        for revision in [7, 0]:
            response = client.post(f"/api/v2/tasks/{TASK_ID}/native-handoff", json={
                "request_id": "native-handoff-stale", "expected_revision": revision,
            })
            assert response.status_code == 409
        assert application.tasks.get(TASK_ID).interaction_mode == "web"
    finally:
        application.close()


def test_native_answer_callback_cannot_reclaim_transferred_task(tmp_path):
    """即使旧HTTP处理器已判断为web，迟到答案回调仍按锁内native状态停止。

    Args:
        tmp_path: 隔离任务目录。
    Returns:
        None；不读取草稿、不启动运行且不记录唤醒请求时通过。
    """

    application, _ = _application(tmp_path)
    application.web_generation.start = Mock()
    application.get_task_context = Mock()
    try:
        # fixture初始为native，模拟API在接续前读取web后发生的陈旧分支。
        task = application.web_generation.after_answer(TASK_ID, "late-web-answer")
        assert task.interaction_mode == "native"
        application.web_generation.start.assert_not_called()
        application.get_task_context.assert_not_called()
    finally:
        application.close()
