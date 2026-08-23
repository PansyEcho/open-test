"""验证V2 FastAPI和CLI确实共享同一套基础应用服务。"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import report_task_progress
from opentest.domain.models import AgentRunEvent, TaskProgressUpdate, TaskStatus


def test_fastapi_registers_multiple_systems_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    """HTTP接口应注册两个隔离系统，且第二次注册不覆盖首个系统。

    Args:
        tmp_path: Pytest提供的隔离源码和知识目录。
        monkeypatch: 替换扫描提交与运行诊断，避免契约测试启动外部工具。
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
        assert client.get("/api/v2/health").json()["status"] == "ok"
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


def test_v2_console_is_served_and_only_references_v2_api(tmp_path: Path) -> None:
    """FastAPI应托管V2控制台，静态客户端不得回退调用legacy项目路由。"""

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        console_response = client.get("/console")
        script_response = client.get("/assets/app.js")

    assert console_response.status_code == 200
    assert "OpenTest V2 Console" in console_response.text
    assert script_response.status_code == 200
    assert 'const API_ROOT = "/api/v2"' in script_response.text
    assert "/api/projects" not in script_response.text


def test_v2_openapi_contains_complete_single_system_workflow(tmp_path: Path) -> None:
    """OpenAPI契约应暴露扫描、知识、Case、Snapshot和执行闭环入口。

    Args:
        tmp_path: pytest隔离的知识根目录。

    Returns:
        None；通过路径集合断言验证周期接口和既有V2契约。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert {
        "/api/v2/systems/{system_id}/scans",
        "/api/v2/systems/{system_id}/knowledge/generations",
        "/api/v2/systems/{system_id}/knowledge/catalog",
        "/api/v2/systems/{system_id}/knowledge/context",
        "/api/v2/systems/{system_id}/knowledge/context/narrative",
        "/api/v2/systems/{system_id}/knowledge/context/candidates",
        "/api/v2/systems/{system_id}/knowledge/context/candidates/{candidate_id}",
        "/api/v2/systems/{system_id}/knowledge/discoveries",
        "/api/v2/systems/{system_id}/knowledge/questions",
        "/api/v2/systems/{system_id}/knowledge/question-cycle",
        "/api/v2/systems/{system_id}/knowledge/question-cycles/{cycle_id}/answers/{question_id}",
        "/api/v2/systems/{system_id}/knowledge/question-cycles/{cycle_id}/complete",
        "/api/v2/systems/{system_id}/knowledge/questions/{question_id}/answers",
        "/api/v2/systems/{system_id}/knowledge/targets/{target_id}",
        "/api/v2/systems/{system_id}/knowledge/nodes/{node_id}",
        "/api/v2/systems/{system_id}/knowledge/generation-batches",
        "/api/v2/systems/{system_id}/knowledge/generation-batches/{batch_id}/continuations",
        "/api/v2/systems/{system_id}/knowledge/generation-batches/{batch_id}/questions/{question_id}/answers",
        "/api/v2/systems/{system_id}/knowledge/generation-batches/{batch_id}/confirmations",
        "/api/v2/systems/{system_id}/scenarios/generations",
        "/api/v2/systems/{system_id}/scenarios/compile",
        "/api/v2/systems/{system_id}/case-generations",
        "/api/v2/systems/{system_id}/case-generation-tasks",
        "/api/v2/systems/{system_id}/case-generations/{generation_id}/confirmations",
        "/api/v2/systems/{system_id}/case-generations/{generation_id}/confirmation-tasks",
        "/api/v2/systems/{system_id}/cases/catalog",
        "/api/v2/systems/{system_id}/natural-language-tests/previews",
        "/api/v2/systems/{system_id}/natural-language-tests/previews/{preview_id}",
        "/api/v2/systems/{system_id}/natural-language-tests/previews/{preview_id}/runs",
        "/api/v2/systems/{system_id}/natural-language-tests/previews/{preview_id}/run-tasks",
        "/api/v2/systems/{system_id}/snapshots",
        "/api/v2/systems/{system_id}/resources",
        "/api/v2/systems/{system_id}/resource-probes",
        "/api/v2/systems/{system_id}/oracle-operations",
        "/api/v2/systems/{system_id}/validation-capabilities",
        "/api/v2/systems/{system_id}/local-settings",
        "/api/v2/systems/{system_id}/scans/{scan_id}/catalog",
        "/api/v2/systems/{system_id}/regression-suites/{suite_id}/runs",
        "/api/v2/systems/{system_id}/regression-suites/{suite_id}/reports",
        "/api/v2/systems/{system_id}/runs",
        "/api/v2/runs/{run_id}",
        "/api/v2/tasks/{task_id}/progress",
        "/api/v2/tasks/{task_id}/events",
        "/api/v2/tasks/{task_id}/cancel-agent",
        "/api/v2/console/activity",
    } <= paths


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


def test_fastapi_missing_run_uses_safe_not_found_response(tmp_path: Path) -> None:
    """未知运行报告应返回统一404且不得泄露Python堆栈。"""

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        response = client.get("/api/v2/runs/run-unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "traceback" not in response.text.lower()
