"""通过真实任务/草稿存储和HTTP入口验证网页执行、问答和恢复。"""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from opentest.api import create_app
from opentest.adapters.case_template_v4_store import CaseTemplateGenerationStoreV4
from opentest.application.foundation import OpenTestApplication
from opentest.domain.case_template_v4 import CaseTemplateDraftRevisionRequest, CaseTemplatePublicationRequest
from opentest.domain.models import KnowledgeQuestion, SystemDefinition, TaskRecord, TaskStatus, utc_now
from test_case_template_v4_revision import _service, _compiled, _handoff, _submission, SYSTEM_ID, OPERATION_ID

TASK_ID = "task-1234567890abcdef"


def _application(tmp_path):
    """组装真实任务和handoff存储，只替换编译事实与耗费模型的运行边界。

    Args:
        tmp_path: 隔离任务和草稿根。
    Returns:
        应用与当前handoff，供HTTP端到端状态测试使用。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    application.store.register_system(SystemDefinition(system_id=SYSTEM_ID, name="退款测试", source_path=str(tmp_path)))
    service, handoffs, _ = _service(tmp_path / "handoffs", _compiled())
    # 正式产物也走真实磁盘回读，避免Mock把无法读取的发布错误伪装成成功。
    service.generations = CaseTemplateGenerationStoreV4(application.store)
    handoff = _handoff(tmp_path).model_copy(update={"task_id": TASK_ID, "root_task_id": TASK_ID})
    handoffs.write(handoff)
    application.case_template_v4 = service
    application.store.get_system = Mock(return_value=SimpleNamespace(source_path=str(tmp_path)))
    application.codex_system_skill_name = Mock(return_value="open-test-test-system")
    task = TaskRecord(task_id=TASK_ID, system_id=SYSTEM_ID, operation="case-generation",
                      target_id=OPERATION_ID, root_task_id=TASK_ID, active_handoff_id=handoff.handoff_id,
                      trace_id="web-test", status=TaskStatus.WAITING_FOR_CLIENT, ended_at=utc_now(),
                      result={"request_id": "web-test-prepare"})
    application.tasks.create_business_record(task)
    return application, handoff


def _wait_settled(application):
    """有界等待真实执行器落盘，返回终态任务；不会调用模型或QA。

    Args:
        application: 当前被测应用。
    Returns:
        web_run_active已清除的任务，否则断言失败。
    """

    deadline = monotonic() + 5
    while monotonic() < deadline:
        task = application.tasks.get(TASK_ID)
        if not task.web_run_active and TASK_ID not in application.web_generation._observing:
            return task
        sleep(0.01)
    raise AssertionError("web run did not settle")


class ControlledAgent:
    """产生可控问题和有效发布，验证业务协议而非Codex随机输出。"""

    def __init__(self, application, pause=False):
        """绑定应用并可在提交问题后暂停，用于模拟用户快速回答。"""
        self.application = application
        self.calls = 0
        self.attaches = 0
        self.question_saved = Event()
        self.release = Event()
        if not pause:
            self.release.set()

    def run(self, request, source_root, evidence_root):
        """首轮保存问题，次轮将答案落实到新草稿并发布。

        Args:
            request: 真实协调器生成的任务绑定请求。
            source_root: 当前系统注册源码根，测试不访问。
            evidence_root: Runner证据目录，测试不访问。
        Returns:
            None；业务效果通过正式服务持久化。
        """
        assert request.task_id == TASK_ID
        self.calls += 1
        if self.calls == 1:
            context = self.application.get_task_context(TASK_ID)
            question = KnowledgeQuestion(question_id="case-question-web", system_id=SYSTEM_ID,
                                         source="case_template", title="订单是否允许取消", detail="需要业务确认",
                                         affected_node_ids=[], affected_target_ids=["case.ready"])
            self.application.submit_case_template_v4(context["handoff"].handoff_id, CaseTemplateDraftRevisionRequest(
                request_id="web-agent-question", expected_revision=context["revision"],
                submission=_submission(), questions=[question],
            ))
            self.question_saved.set()
            assert self.release.wait(5)
        else:
            self.publish()

    def publish(self):
        """将已确认答案落实为新revision并通过核心发布协议写正式产物。"""
        context = self.application.get_task_context(TASK_ID)
        handoff_id = context["handoff"].handoff_id
        self.application.submit_case_template_v4(handoff_id, CaseTemplateDraftRevisionRequest(
            request_id="web-agent-revised", expected_revision=context["revision"], submission=_submission(),
        ))
        self.application.publish_case_template_v4(handoff_id, CaseTemplatePublicationRequest(
            request_id="web-agent-publish", expected_revision=context["revision"] + 1, mode="complete",
        ))

    def attach(self, run_id, evidence_root):
        """恢复原运行时只发布原任务，不发起新Agent请求。"""
        assert run_id.startswith("agent-")
        self.attaches += 1
        self.publish()

    def detach_observers(self):
        """释放测试等待，模拟服务正常分离观察者。"""
        self.release.set()


def test_web_question_unknown_answer_and_revisioned_publication(tmp_path):
    """HTTP提问与答案推进同一草稿，unknown不关闭且重复点击不重复运行。

    Args:
        tmp_path: 隔离状态根。
    Returns:
        None；正式产物发布且原生默认不受影响时通过。
    """
    application, handoff = _application(tmp_path)
    runner = ControlledAgent(application)
    application.web_generation.runner = runner
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        start = {"request_id": "web-start-001", "expected_revision": 0}
        assert client.post(f"/api/v2/tasks/{TASK_ID}/runs", json=start).status_code == 202
        task = _wait_settled(application)
        assert task.status == TaskStatus.WAITING_FOR_INPUT
        assert client.post(f"/api/v2/tasks/{TASK_ID}/runs", json=start).status_code == 202
        assert runner.calls == 1
        assert client.post(f"/api/v2/tasks/{TASK_ID}/runs", json={**start, "expected_revision": 1}).status_code == 409
        answer = {"request_id": "web-answer-unknown", "expected_revision": 1,
                  "question_id": "case-question-web", "answer": "不知道", "outcome": "unknown"}
        assert client.post(f"/api/v2/tasks/{TASK_ID}/answers", json=answer).status_code == 200
        assert application.get_task_context(TASK_ID)["questions"][0].status == "open"
        assert runner.calls == 1
        answer.update(request_id="web-answer-known", expected_revision=2, answer="允许取消", outcome="answered")
        assert client.post(f"/api/v2/tasks/{TASK_ID}/answers", json=answer).status_code == 200
        assert _wait_settled(application).status == TaskStatus.COMPLETED
        assert runner.calls == 2
        assert application.case_template_v4.handoffs.get(handoff.handoff_id).revision == 5
    finally:
        application.close()


def test_answer_before_agent_exit_is_not_lost(tmp_path):
    """问题工具返回后立即回答也必须续跑，不受Agent进程退出竞态影响。"""
    application, _ = _application(tmp_path)
    runner = ControlledAgent(application, pause=True)
    application.web_generation.runner = runner
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        application.web_generation.start(TASK_ID, "web-fast-answer-start", 0)
        assert runner.question_saved.wait(3)
        response = client.post(f"/api/v2/tasks/{TASK_ID}/answers", json={
            "request_id": "web-fast-answer", "expected_revision": 1,
            "question_id": "case-question-web", "answer": "可以", "outcome": "answered",
        })
        assert response.status_code == 200
        assert application.tasks.get(TASK_ID).web_pending_answer_request
        runner.release.set()
        deadline = monotonic() + 5
        while runner.calls < 2 and monotonic() < deadline:
            sleep(0.01)
        assert _wait_settled(application).status == TaskStatus.COMPLETED
        assert runner.calls == 2
    finally:
        runner.release.set()
        application.close()


def test_restart_attaches_existing_run_and_rejects_invalid_tool_submission(tmp_path):
    """恢复已有进程不重放模型请求；非法工具Schema不能破坏原草稿。"""
    application, handoff = _application(tmp_path)
    runner = ControlledAgent(application)
    application.web_generation.runner = runner
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        response = client.post(f"/api/v2/tasks/{TASK_ID}/agent-tools/revise_case_draft", json={
            "request_id": "invalid-submission", "expected_revision": 0,
            "submission": {"data_functions": [], "case_templates": "invalid", "unresolved": []},
        })
        assert response.status_code == 422
        assert response.json()["issues"][0]["location"] == ["submission", "case_templates"]
        assert application.get_task_context(TASK_ID)["revision"] == 0
        assert "case_templates" in application.tasks.get(TASK_ID).error
        task = application.tasks.get(TASK_ID).model_copy(update={
            "web_run_active": True, "web_run_id": "agent-1234567890abcdef", "interaction_mode": "web",
        })
        application.tasks.save_business_record(task)
        application.web_generation.recover()
        assert _wait_settled(application).status == TaskStatus.COMPLETED
        assert runner.attaches == 1 and runner.calls == 0
    finally:
        application.close()


def test_unreadable_publication_cannot_be_reported_as_complete(tmp_path):
    """正式Generation被移除后，网页必须显示工程失败并保留可读草稿。

    Args:
        tmp_path: 独立handoff和Generation存储。
    Returns:
        None；任务不能依赖旧COMPLETED状态虚报发布成功时通过。
    """
    application, handoff = _application(tmp_path)
    try:
        ControlledAgent(application).publish()
        published = application.case_template_v4.handoffs.get(handoff.handoff_id)
        root = application.case_template_v4.generations._root(SYSTEM_ID)
        (root / f"{published.generation_id}.json").unlink()
        # 丢失的是正式产物，任务上下文及原草稿仍应完整可读。
        application.web_generation._settle(TASK_ID, "")
        task = application.tasks.get(TASK_ID)
        assert task.status == TaskStatus.FAILED
        assert "不可读取" in task.error
        assert application.get_task_context(TASK_ID)["draft"] is not None
    finally:
        application.close()


def test_web_executor_shutdown_does_not_leave_task_running(tmp_path):
    """网页启动遇到线程池关闭时保留草稿并清除运行标志。

    Args:
        tmp_path: 隔离任务目录。
    Returns:
        None；失败可恢复且没有实际Agent请求时通过。
    """
    application, _ = _application(tmp_path)
    try:
        application.tasks._executor.shutdown(wait=True)
        with pytest.raises(RuntimeError):
            application.web_generation.start(TASK_ID, "web-closed-pool", 0)
        # 无进程被启动时不保留永久RUNNING或占用任务锁。
        task = application.tasks.get(TASK_ID)
        assert task.status == TaskStatus.FAILED
        assert not task.web_run_active
        assert "尚未启动" in task.error
        assert application.get_task_context(TASK_ID)["handoff"] is not None
    finally:
        application.close()


def test_task_runner_keeps_provider_but_exposes_only_bound_mcp(tmp_path, monkeypatch):
    """网页运行保留Provider配置，只批准当前任务桥并关闭其他扩展。

    Args:
        tmp_path: 隔离Codex配置目录，不含实际认证。
        monkeypatch: 将CODEX_HOME仅指向本测试目录。
    Returns:
        None；生成的真实CLI参数符合网页授权边界时通过。
    """
    from opentest.adapters.agent_runner import AgentRunner, AgentRunnerConfig
    from opentest.domain.models import AgentRunRequest

    (tmp_path / "config.toml").write_text('model_provider = "existing-provider"\n[mcp_servers.unrelated]\ncommand="example"\n')
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    request = AgentRunRequest(system_id=SYSTEM_ID, agent="codex", prompt="网页任务",
                              task_id=TASK_ID, api_root="http://127.0.0.1:8788/api/v2",
                              model="configured-model", reasoning_effort="low")
    command = AgentRunner(AgentRunnerConfig())._build_command(
        request, Path("/usr/local/bin/codex"), None, tmp_path / "output", tmp_path, tmp_path / "access",
    )
    # 不忽略用户Provider，但只批准具备固定task_id的MCP写入协议。
    assert "--ignore-user-config" not in command
    assert 'mcp_servers.opentest_source.default_tools_approval_mode="approve"' in command
    assert "mcp_servers.unrelated.enabled=false" in command
    assert "tool_output_token_limit=65536" in command
    assert "configured-model" in command
    assert any("task_agent_mcp.py" in item and TASK_ID in item for item in command)
    assert 'sandbox_mode="read-only"' in command


def test_only_serving_application_registers_web_recovery(tmp_path):
    """单纯构造应用不会观察真实任务，只有HTTP生命周期注册恢复。

    Args:
        tmp_path: 不含外部任务的隔离状态根。
    Returns:
        None；未启用的默认app无法通过心跳抢占其他服务任务时通过。
    """
    application, _ = _application(tmp_path)
    try:
        assert application.web_generation.recover not in application.tasks._maintenance_callbacks
        # 实际服务启动时才启用恢复，重复调用复用同一个回调。
        application.web_generation.start_observing()
        application.web_generation.start_observing()
        assert application.tasks._maintenance_callbacks.count(application.web_generation.recover) == 1
    finally:
        application.close()


def test_answer_during_settle_retains_pending_wakeup(tmp_path):
    """在收尾已读Task、尚未落盘时回答，续跑信号不能被旧Task覆盖。

    Args:
        tmp_path: 隔离持久任务目录。
    Returns:
        None；确定性线程交错后唤醒请求保留时通过。
    """
    application, _ = _application(tmp_path)
    entered, release = Event(), Event()
    context = application.get_task_context(TASK_ID)
    calls = 0

    def paused_context(task_id):
        """暂停首次收尾读取，让回答线程进入相同任务同步边界。"""
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(3)
        return context

    application.get_task_context = paused_context
    application.web_generation._observing.add(TASK_ID)
    task = application.tasks.get(TASK_ID)
    application.tasks.save_business_record(task.model_copy(update={"web_run_active": True}))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            settling = pool.submit(application.web_generation._settle, TASK_ID, "")
            assert entered.wait(2)
            answering = pool.submit(application.web_generation.after_answer, TASK_ID, "answer-during-settle")
            release.set()
            settling.result(timeout=3)
            answering.result(timeout=3)
        # 收尾状态已落盘但观察者还未释放锁，回答必须留给finally唤醒，而不是直接启动失败。
        assert application.tasks.get(TASK_ID).web_pending_answer_request == "answer-during-settle"
    finally:
        release.set()
        application.web_generation._observing.discard(TASK_ID)
        application.close()


@pytest.mark.parametrize("operation", ["knowledge", "case"])
def test_answer_projection_cannot_restore_finished_run(tmp_path, operation):
    """真实答案投影等待收尾锁后必须重读Task，不能恢复旧的运行标记。

    Args:
        tmp_path: 隔离任务和权威handoff。
        operation: 覆盖Case和知识两种答案投影入口。
    Returns:
        None；投影保留收尾后的run状态与已保存唤醒请求时通过。
    """
    from test_knowledge_case_continuation import _knowledge_task

    application, handoff = _application(tmp_path)
    task = (_knowledge_task(application) if operation == "knowledge"
            else application.tasks.get(TASK_ID))
    started, read_old = Event(), Event()
    answer_thread = []
    original_get = application.tasks.get

    def observed_get(task_id):
        """读取指定task_id并标记答案线程读点，返回真实Task副本供交错验证。

        Side Effects:
            仅答案线程会设置read_old事件；不改变持久任务。
        """
        record = original_get(task_id)
        if answer_thread and get_ident() == answer_thread[0]:
            read_old.set()
        return record

    def project_answer():
        """调用生产答案路径的Task投影，返回已持久化的知识或Case任务。

        Side Effects:
            标记线程开始后写入真实任务存储，使测试覆盖读旧副本再写入的竞态。
        """
        answer_thread.append(get_ident())
        started.set()
        if operation == "knowledge":
            return application.tasks.transition_waiting_task(
                task.task_id, TaskStatus.WAITING_FOR_COMPLETION, task.client_handoff,
            )
        return application._sync_case_task(handoff)

    application.tasks.get = observed_get
    application.tasks.save_business_record(task.model_copy(update={"web_run_active": True}))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            # 模拟_settle已持有相同任务锁；旧实现会在锁外读到True，再等待_write。
            with application.tasks._business_task_creation_scope(task.task_id):
                projected = pool.submit(project_answer)
                assert started.wait(2)
                read_old.wait(0.2)
                application.tasks.save_business_record(original_get(task.task_id).model_copy(update={
                    "web_run_active": False, "web_pending_answer_request": "answer-real-projection",
                }))
            projected.result(timeout=3)
        latest = original_get(task.task_id)
        assert not latest.web_run_active
        assert latest.web_pending_answer_request == "answer-real-projection"
    finally:
        application.close()


@pytest.mark.parametrize("operation", ["knowledge", "case"])
def test_prepare_response_loss_replays_original_run_revision(tmp_path, operation):
    """首个网页prepare响应丢失后，Agent推进版本仍应返回原运行回执。

    Args:
        tmp_path: 隔离任务存储。
        operation: 两个真实HTTP自动启动入口。
    Returns:
        None；重试不增加Agent调用、显式异参/runs仍拒绝时通过。
    """
    application, _ = _application(tmp_path)
    runner = ControlledAgent(application)
    application.web_generation.runner = runner
    prepared = {"task": application.tasks.get(TASK_ID)}
    application.prepare_native_knowledge_generation = Mock(return_value=prepared.copy())
    application.start_case_template_generation_v4 = Mock(return_value=prepared.copy())
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    suffix = "knowledge/generations" if operation == "knowledge" else "case-generations"
    body = {"request_id": "web-test-prepare", "interaction_mode": "web"}
    body.update({"system_id": SYSTEM_ID, "target_id": OPERATION_ID} if operation == "knowledge"
                else {"operation_id": OPERATION_ID})
    try:
        assert client.post(f"/api/v2/systems/{SYSTEM_ID}/{suffix}", json=body).status_code == 202
        _wait_settled(application)
        assert application.get_task_context(TASK_ID)["revision"] == 1
        assert client.post(f"/api/v2/systems/{SYSTEM_ID}/{suffix}", json=body).status_code == 202
        assert runner.calls == 1
        assert client.post(f"/api/v2/tasks/{TASK_ID}/runs", json={
            "request_id": "web-web-test-prepare", "expected_revision": 1,
        }).status_code == 409
    finally:
        application.close()
