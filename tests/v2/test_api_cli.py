"""验证V2 FastAPI和CLI确实共享同一套基础应用服务。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import report_task_progress
from opentest.domain.case_template_v4 import CaseTemplateHandoffV4, CaseTemplateSourceScope
from opentest.domain.errors import (
    CaseExecutionConflictError,
    CaseGenerationStateConflictError,
    KnowledgeNotFoundError,
    ModelProfileValidationError,
    TaskPartialFailureError,
)
from opentest.domain.models import AgentRunEvent, SourceBaseline, TaskProgressUpdate, TaskStatus


def test_fastapi_registers_multiple_systems_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    """HTTP接口应返回页面版本并注册两个互不覆盖的隔离系统。

    Args:
        tmp_path: Pytest提供的隔离源码和知识目录。
        monkeypatch: 替换扫描提交与运行诊断，避免契约测试启动外部工具。

    Returns:
        None；健康版本正确且两个系统均保留时通过。
    """

    first_source = tmp_path / "first"
    second_source = tmp_path / "second"
    first_source.mkdir()
    second_source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")

    def submit_scan_without_execution(request, prepare):
        """执行接入准备并返回最小任务，验证注册路由而不启动scriptgen。"""

        prepare()
        return application.tasks.submit("source-scan-contract", request.system_id, lambda: {})

    monkeypatch.setattr(application, "ensure_scanner_ready", lambda: None)
    monkeypatch.setattr(application, "submit_prepared_source_scan", submit_scan_without_execution)

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        health = client.get("/api/v2/health").json()
        assert health["status"] == "ok"
        assert health["page_version"] == "20260903-06"
        first_response = client.post(
            "/api/v2/systems",
            json={
                "system_id": "train-booking-core",
                "name": "火车票预订",
                "source_path": str(first_source),
                "qa_labrador_token": "first-token",
                "qa_gateway_prefix": "http://servicegw.qa.example/first/v2",
            },
        )
        second_response = client.post(
            "/api/v2/systems",
            json={
                "system_id": "settlement-core",
                "name": "结算",
                "source_path": str(second_source),
                "qa_labrador_token": "second-token",
                "qa_gateway_prefix": "http://servicegw.qa.example/second/v2",
            },
        )

    assert first_response.status_code == 201
    assert first_response.json()["system"]["system_id"] == "train-booking-core"
    assert second_response.status_code == 201
    assert [item.system_id for item in application.store.list_systems()] == ["settlement-core", "train-booking-core"]


def test_console_is_served_and_references_only_versioned_api(tmp_path: Path) -> None:
    """FastAPI应托管版本化控制台，静态客户端不得回退调用legacy项目路由。

    Args:
        tmp_path: Pytest提供的隔离知识目录。

    Returns:
        None；HTML、版本化脚本和V2 API根契约均正确时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        console_response = client.get("/console")
        script_response = client.get("/assets/app.js")

    assert console_response.status_code == 200
    assert "<title>OpenTest Console</title>" in console_response.text
    assert '<meta name="opentest-page-version" content="20260903-06">' in console_response.text
    assert '/assets/app.js?v=20260903-06' in console_response.text
    assert script_response.status_code == 200
    assert 'const API_ROOT = "/api/v2"' in script_response.text
    assert "API_V3_ROOT" not in script_response.text
    assert "API_V4_ROOT" not in script_response.text
    assert "/api/projects" not in script_response.text


def test_v2_openapi_contains_single_system_generation_and_execution_workflow(
    tmp_path: Path,
) -> None:
    """OpenAPI应只暴露统一V2 Case生命周期，并移除历史Case传输契约。

    Args:
        tmp_path: pytest隔离的知识根目录。

    Returns:
        None；扫描、知识、Operation、资源与新Case接口集合正确时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    required_paths = {
        "/api/v2/systems/{system_id}/scans",
        "/api/v2/systems/{system_id}/scans/{scan_id}/catalog",
        "/api/v2/systems/{system_id}/knowledge/generations",
        "/api/v2/systems/{system_id}/knowledge/catalog",
        "/api/v2/systems/{system_id}/knowledge/context",
        "/api/v2/systems/{system_id}/operations",
        "/api/v2/systems/{system_id}/operation-executions",
        "/api/v2/operation-executions/{execution_id}",
        "/api/v2/systems/{system_id}/resources",
        "/api/v2/systems/{system_id}/resource-probes",
        "/api/v2/systems/{system_id}/case-generations",
        "/api/v2/case-handoffs/{handoff_id}",
        "/api/v2/case-handoffs/{handoff_id}/dsl",
        "/api/v2/systems/{system_id}/case-generations/{generation_id}",
        "/api/v2/systems/{system_id}/case-generations/{generation_id}/executions",
        "/api/v2/systems/{system_id}/case-executions",
        "/api/v2/systems/{system_id}/case-executions/{execution_id}",
        "/api/v2/tasks/{task_id}/progress",
        "/api/v2/tasks/{task_id}/events",
        "/api/v2/console/activity",
    }
    assert required_paths <= paths

    assert not any(
        path.startswith("/api/v3/") or path.startswith("/api/v4/")
        for path in paths
    )
    assert not any(
        fragment in path
        for path in paths
        for fragment in (
            "/scenarios/",
            "/snapshots",
            "/natural-language-tests/",
            "/regression-suites/",
            "/case-attempts",
            "/case-workspace",
            "/case-generation-tasks",
            "/execution-tasks",
            "/case-fixture-bindings",
            "/cases/catalog",
        )
    )
    assert "/api/v2/systems/{system_id}/runs" not in paths
    assert "/api/v2/runs/{run_id}" not in paths
    assert not any(
        "/case-generations/" in path and path.endswith("/confirmations")
        for path in paths
    )
def test_case_generation_start_returns_ids_thread_link_and_poll_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """确认统一入口只接收生成参数并返回Generation、Codex线程和轮询地址。

    Args:
        tmp_path: Pytest隔离应用根。
        monkeypatch: 替换真实Codex线程创建，验证HTTP契约而不调用模型。

    Returns:
        None；POST状态、深链和GET终态投影完整时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    handoff_id = f"case-template-handoff-{'a' * 20}"
    generation_id = f"case-template-generation-{'b' * 20}"
    handoff = CaseTemplateHandoffV4(
        handoff_id=handoff_id,
        system_id="sample.java.system",
        entry_id="facade:sample.RefundFacade#cancel",
        source_scan_id="scan-v4-api",
        status="WAITING_FOR_AGENT",
        generation_id=generation_id,
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id="sample.java.system",
                source_scan_id="scan-v4-api",
                source_baseline=SourceBaseline(source_path="/private/sample"),
            )
        ],
        thread_id="thread-v4-api",
        codex_deep_link="codex://threads/thread-v4-api",
        turn_id="turn-v4-api",
        turn_status="inProgress",
        model_provider="custom",
        codex_model="company-case-model",
        reasoning_effort="high",
    )

    received_request = {}

    def start_v4(_system_id, request):
        """返回已绑定Codex线程的V4 handoff而不启动真实模型。"""

        received_request["value"] = request
        return handoff

    def poll_v4(_handoff_id):
        """返回同一handoff轮询投影。"""

        return {"handoff": handoff.model_dump(mode="json"), "generation": None}

    monkeypatch.setattr(application, "start_case_template_generation_v4", start_v4)
    monkeypatch.setattr(application, "get_case_template_handoff_v4", poll_v4)
    monkeypatch.setattr(
        application,
        "get_codex_model_catalog",
        lambda: {
            "provider_id": "custom",
            "default_model": "company-case-model",
            "models": [
                {
                    "id": "company-case-model",
                    "display_name": "Company Case Model",
                    "is_default": True,
                    "default_reasoning_effort": "high",
                    "supported_reasoning_efforts": ["medium", "high"],
                }
            ],
        },
    )

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v2/systems/sample.java.system/case-generations",
            json={
                "operation_id": "sample.RefundFacade#cancel",
                "codex_model": "company-case-model",
                "reasoning_effort": "high",
            },
        )
        polled = client.get(f"/api/v2/case-handoffs/{handoff_id}")
        catalog = client.get("/api/v2/local-settings/codex-model-catalog")

    assert response.status_code == 202
    assert response.json() == {
        "handoff_id": handoff_id,
        "generation_id": generation_id,
        "status": "WAITING_FOR_AGENT",
        "thread_id": "thread-v4-api",
        "turn_id": "turn-v4-api",
        "turn_status": "inProgress",
        "model_provider": "custom",
        "codex_model": "company-case-model",
        "reasoning_effort": "high",
        "codex_deep_link": "codex://threads/thread-v4-api",
        "poll_url": f"/api/v2/case-handoffs/{handoff_id}",
    }
    assert polled.status_code == 200
    assert polled.json()["handoff"]["thread_id"] == "thread-v4-api"
    assert received_request["value"].codex_model == "company-case-model"
    assert received_request["value"].reasoning_effort == "high"
    assert not hasattr(received_request["value"], "execution_mode")
    assert catalog.status_code == 200
    assert catalog.json()["provider_id"] == "custom"
    assert catalog.json()["models"][0]["supported_reasoning_efforts"] == ["medium", "high"]


def test_case_generation_rejects_unavailable_user_model_before_thread_creation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Case模型或档位不在当前用户目录时应返回明确422。

    Args:
        tmp_path: pytest隔离应用根。
        monkeypatch: 令应用层模拟模型目录校验失败，不调用真实Codex。

    Returns:
        None；HTTP状态和稳定错误码可供配置页直接展示时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")

    def reject_profile(_system_id, _request):
        """模拟当前Provider没有用户提交的模型。"""

        raise ModelProfileValidationError("Codex模型不在当前用户目录中: missing-model")

    monkeypatch.setattr(application, "start_case_template_generation_v4", reject_profile)

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v2/systems/sample.java.system/case-generations",
            json={
                "operation_id": "sample.RefundFacade#cancel",
                "codex_model": "missing-model",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "model_profile_validation_error"


def test_case_execution_conflicts_are_exposed_as_http_409(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """不可执行 Generation 和并发 Execution 都应返回可恢复的 409 契约。

    Args:
        tmp_path: pytest 隔离的应用目录。
        monkeypatch: 注入两类应用层状态冲突，不访问 QA。

    Returns:
        None；状态码、错误码和当前执行身份均稳定时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")

    def reject_blocked(_system_id, _generation_id, _request):
        """模拟 BLOCKED Generation 在 QA 调用前拒绝执行。"""

        raise CaseGenerationStateConflictError("BLOCKED")

    monkeypatch.setattr(application, "execute_case_generation", reject_blocked)
    path = (
        "/api/v2/systems/sample.java.system/case-generations/"
        f"case-template-generation-{'c' * 20}/executions"
    )
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        blocked = client.post(path, json={"environment_id": "qa"})

        def reject_running(_system_id, _generation_id, _request):
            """模拟同 Generation 与环境已经存在 RUNNING Execution。"""

            raise CaseExecutionConflictError(
                f"case-generation-execution-{'d' * 20}"
            )

        monkeypatch.setattr(application, "execute_case_generation", reject_running)
        running = client.post(path, json={"environment_id": "qa"})

    assert blocked.status_code == 409
    assert blocked.json()["error"] == {
        "code": "CASE_GENERATION_NOT_EXECUTABLE",
        "message": "Generation状态为BLOCKED，不能启动执行",
        "generation_status": "BLOCKED",
    }
    assert running.status_code == 409
    assert running.json()["error"]["code"] == "CASE_EXECUTION_CONFLICT"
    assert running.json()["error"]["execution_id"] == (
        f"case-generation-execution-{'d' * 20}"
    )


def test_codex_client_handoff_bridge_is_loopback_only_and_preserves_tool_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """插件桥接只能由回环客户端调用且不得改写handoff或源码工具参数。

    Args:
        tmp_path: pytest隔离的知识根目录。
        monkeypatch: 用安全桩记录API到应用服务的精确委托参数。

    Returns:
        None；回环请求原样委托且非回环请求被拒绝时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    observed: list[tuple[str, str, dict[str, object]]] = []

    def get_handoff(handoff_id: str) -> dict[str, object]:
        """返回不含源码和凭据的最小handoff摘要。

        Args:
            handoff_id: 路由传入的一次性接管ID。

        Returns:
            用于验证路由委托的安全对象。
        """

        return {"handoff_id": handoff_id, "status": "waiting_for_client"}

    def call_source_tool(
        handoff_id: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        """记录回环路由绑定的handoff、允许工具和有界参数。

        Args:
            handoff_id: 当前客户端任务身份。
            tool_name: 当前三个受控源码工具之一。
            arguments: 未被传输层扩充的源码参数。

        Returns:
            不含源码正文的调用摘要。

        Side Effects:
            仅向测试内存列表追加一次委托记录。
        """

        observed.append((handoff_id, tool_name, arguments))
        return {"count": 0, "matches": []}

    monkeypatch.setattr(application, "get_knowledge_client_handoff", get_handoff)
    monkeypatch.setattr(application, "call_knowledge_client_source_tool", call_source_tool)

    with TestClient(create_app(application), client=("127.0.0.1", 50001)) as client:
        handoff = client.get("/api/v2/knowledge/client-handoffs/handoff-0123456789abcdef01234567")
        source = client.post(
            "/api/v2/knowledge/client-handoffs/handoff-0123456789abcdef01234567/tools/search_source",
            json={"arguments": {"pattern": "queryList", "path": "app"}},
        )
    with TestClient(create_app(application), client=("198.51.100.8", 50002)) as remote_client:
        denied = remote_client.get("/api/v2/knowledge/client-handoffs/handoff-0123456789abcdef01234567")

    assert handoff.status_code == 200
    assert handoff.json()["handoff_id"] == "handoff-0123456789abcdef01234567"
    assert source.status_code == 200
    assert observed == [
        (
            "handoff-0123456789abcdef01234567",
            "search_source",
            {"pattern": "queryList", "path": "app"},
        )
    ]
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "scope_violation"


def test_single_target_generation_rejects_legacy_request_without_agent_confirmation(tmp_path: Path) -> None:
    """单目标API不得接受缺少明确Agent和费用确认的旧请求。

    Args:
        tmp_path: pytest隔离的知识根与任务目录。

    Returns:
            None；旧请求在进入业务处理前被结构化契约拒绝时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        response = client.post(
            "/api/v2/systems/legacy-demo/knowledge/generations",
            json={"system_id": "legacy-demo", "entry_id": "facade:demo.Legacy#query"},
        )

    assert response.status_code == 422
    assert "target_id" in response.text
    assert "agent" in response.text


def test_compatible_generation_batch_route_requires_explicit_fee_confirmation(tmp_path: Path) -> None:
    """兼容批次路由也必须在业务查询前拒绝缺少费用确认的请求。

    Args:
        tmp_path: pytest隔离的知识根和本地任务目录。

    Returns:
        None；即使明确Agent和单目标都存在，缺少confirmed仍返回422时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        response = client.post(
            "/api/v2/systems/legacy-demo/knowledge/generation-batches",
            json={
                "system_id": "legacy-demo",
                "target_ids": ["facade:demo.LegacyFacade#query"],
                "agent": "codex",
            },
        )

    assert response.status_code == 422
    assert "confirmed" in response.text


def test_task_event_stream_replays_persisted_events_and_honors_last_event_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """SSE应重放已落盘公开事件，并从浏览器最后确认的序号继续。

    Args:
        tmp_path: pytest隔离的知识根、任务文件和Agent事件目录。
        monkeypatch: 禁止SSE退回每秒全量扫描的旧读取入口。

    Returns:
        None；首次读取包含事件且重连不会重复发送相同序号时通过。

    Side Effects:
        仅在临时知识根写入一条脱敏事件和一个本地完成任务，不启动真实Agent。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    run_id = "agent-1234567890abcdef"
    evidence_root = application.knowledge_root / ".opentest" / "agent-runs"
    run_root = evidence_root / run_id
    run_root.mkdir(parents=True)
    event = AgentRunEvent(
        run_id=run_id,
        sequence=1,
        agent="codex",
        target_id="facade:demo.QueryFacade#queryList",
        event_type="reasoning_summary",
        text="正在核对查询条件与返回分支。",
    )
    (run_root / "events.jsonl").write_text(event.model_dump_json() + "\n", encoding="utf-8")

    def completed_agent_job() -> dict[str, object]:
        """把隔离事件运行ID绑定到任务后完成，供终态SSE验证。

        Returns:
            不含业务正文的最小完成摘要。

        Side Effects:
            在线程内持久化当前任务的Agent运行游标和公开阶段。
        """

        # 任务进度是API从任务ID安全定位事件目录的唯一关联，不接受客户端直接传入运行路径。
        report_task_progress(
            TaskProgressUpdate(
                stage_code="agent_analysis",
                stage_name="AI分析",
                stage_index=2,
                stage_total=4,
                completed_units=1,
                total_units=1,
                current_item=event.target_id,
                agent="codex",
                agent_run_id=run_id,
                agent_event_cursor=1,
            )
        )
        return {"completed": True}

    task = application.tasks.submit("knowledge-target-generation", "demo", completed_agent_job)
    for _ in range(200):
        if application.get_task(task.task_id).status == TaskStatus.COMPLETED:
            break
        time.sleep(0.01)
    assert application.get_task(task.task_id).status == TaskStatus.COMPLETED

    def reject_full_event_scan(*_: object, **__: object) -> list[AgentRunEvent]:
        """若SSE仍调用旧全量读取入口则立即让契约测试失败。"""

        raise AssertionError("SSE must use per-connection event offsets")

    monkeypatch.setattr(application, "list_task_agent_events", reject_full_event_scan)

    with TestClient(create_app(application)) as client:
        initial = client.get(f"/api/v2/tasks/{task.task_id}/events")
        resumed = client.get(
            f"/api/v2/tasks/{task.task_id}/events",
            headers={"Last-Event-ID": "1"},
        )

    assert initial.status_code == 200
    assert initial.headers["content-type"].startswith("text/event-stream")
    assert "id: 1" in initial.text
    assert "reasoning_summary" in initial.text
    assert "正在核对查询条件与返回分支。" in initial.text
    assert resumed.status_code == 200
    assert resumed.text == ""


def test_agent_diagnostics_restore_prompt_public_session_and_source_access(tmp_path: Path) -> None:
    """终态知识任务应恢复Prompt、公开会话、源码轨迹和手动续接命令。

    Args:
        tmp_path: pytest隔离的知识根与Agent运行证据目录。

    Returns:
        None；诊断接口只读返回可公开材料且不启动新Runner时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    run_id = "agent-abcdefabcdefabcd"
    run_root = application.knowledge_root / ".opentest/agent-runs" / run_id
    run_root.mkdir(parents=True)
    event = AgentRunEvent(
        run_id=run_id,
        sequence=1,
        agent="codex",
        target_id="facade:demo.QueryFacade#queryList",
        event_type="reasoning_summary",
        text="正在沿服务枚举定位查询Invoker。",
    )
    (run_root / "worker-request.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "agent": "codex",
                "target_id": event.target_id,
            }
        ),
        encoding="utf-8",
    )
    (run_root / "state.json").write_text(
        json.dumps({"status": "completed", "session_id": "01a-session-diagnostics"}),
        encoding="utf-8",
    )
    (run_root / "prompt.txt").write_text("精确知识分析Prompt", encoding="utf-8")
    (run_root / "output.txt").write_text('{"status":"completed"}', encoding="utf-8")
    (run_root / "events.jsonl").write_text(event.model_dump_json() + "\n", encoding="utf-8")
    (run_root / "source-access.jsonl").write_text(
        json.dumps(
            {
                "sequence": 1,
                "tool": "read_source",
                "path": "src/main/java/demo/QueryInvoker.java",
                "start_line": 20,
                "end_line": 60,
                "result_count": 41,
                "created_at": "2026-08-23T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def completed_agent_job() -> dict[str, object]:
        """把固定运行ID绑定到可回看的知识任务。

        Returns:
            不含业务正文的完成摘要。

        Side Effects:
            在线程任务中持久化Agent运行身份。
        """

        report_task_progress(
            TaskProgressUpdate(
                stage_code="completed",
                stage_name="知识生成完成",
                stage_index=3,
                stage_total=3,
                completed_units=1,
                total_units=1,
                current_item=event.target_id,
                agent="codex",
                agent_run_id=run_id,
                agent_event_cursor=1,
            )
        )
        return {"completed": True}

    task = application.tasks.submit("knowledge-target-generation", "demo", completed_agent_job)
    for _ in range(200):
        if application.get_task(task.task_id).status == TaskStatus.COMPLETED:
            break
        time.sleep(0.01)

    with TestClient(create_app(application)) as client:
        response = client.get(f"/api/v2/tasks/{task.task_id}/agent-diagnostics")

    assert response.status_code == 200
    diagnostics = response.json()["diagnostics"]
    assert diagnostics["prompt"] == "精确知识分析Prompt"
    assert diagnostics["prompt_chars"] == len("精确知识分析Prompt")
    assert diagnostics["prompt_truncated"] is False
    assert diagnostics["final_output_truncated"] is False
    assert diagnostics["public_events"][0]["text"] == "正在沿服务枚举定位查询Invoker。"
    assert diagnostics["source_accesses"][0]["path"] == "src/main/java/demo/QueryInvoker.java"
    assert diagnostics["resume_command"] == "codex resume 01a-session-diagnostics"
    assert "隐藏思维链" in diagnostics["disclosure"]


def test_task_event_stream_closes_after_partial_terminal_status(tmp_path: Path) -> None:
    """Agent部分失败后SSE必须结束，刷新页面不得无限等待原连接。

    Args:
        tmp_path: pytest隔离的知识根和任务历史目录。

    Returns:
        None；partial任务可读取且无事件流会立即正常结束时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")

    def partial_agent_job() -> dict[str, object]:
        """模拟代码事实已保存但Agent失败的知识任务。

        Raises:
            TaskPartialFailureError: 携带页面应恢复的失败计数与安全摘要。
        """

        result = {
            "target_count": 1,
            "code_only_count": 1,
            "agent_failed_count": 1,
            "deterministic_failed_count": 0,
            "failed_count": 1,
            "outcomes": [],
        }
        raise TaskPartialFailureError(result, "Agent分析失败，已保留确定性代码事实")

    task = application.tasks.submit("knowledge-target-generation", "demo", partial_agent_job)
    for _ in range(200):
        if application.get_task(task.task_id).status == TaskStatus.PARTIAL:
            break
        time.sleep(0.01)
    assert application.get_task(task.task_id).status == TaskStatus.PARTIAL

    with TestClient(create_app(application)) as client:
        response = client.get(f"/api/v2/tasks/{task.task_id}/events")

    assert response.status_code == 200
    assert response.text == ""


def test_fastapi_missing_case_execution_uses_safe_not_found_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """未知Execution报告应返回统一404且不得泄露Python堆栈。

    Args:
        tmp_path: pytest隔离的知识根目录。
        monkeypatch: 令应用层稳定模拟Execution不存在。

    Returns:
        None；错误响应使用统一领域协议时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    missing_execution_id = f"case-generation-execution-{'f' * 20}"

    def reject_missing_execution(_system_id: str, execution_id: str) -> None:
        """模拟指定Execution不存在且不读取真实系统状态。

        Args:
            _system_id: API委托的系统身份，本桩不使用。
            execution_id: API委托的Execution身份。

        Raises:
            KnowledgeNotFoundError: 始终表示目标报告不存在。
        """

        raise KnowledgeNotFoundError(f"Case execution not found: {execution_id}")

    monkeypatch.setattr(
        application,
        "get_case_generation_execution",
        reject_missing_execution,
    )
    with TestClient(create_app(application)) as client:
        response = client.get(
            f"/api/v2/systems/sample.java.system/case-executions/{missing_execution_id}"
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "traceback" not in response.text.lower()
