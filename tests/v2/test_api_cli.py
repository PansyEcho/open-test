"""验证V2 FastAPI和CLI确实共享同一套基础应用服务。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication


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
    """OpenAPI契约应暴露扫描、知识、Case、Snapshot和执行闭环入口。"""

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
        "/api/v2/systems/{system_id}/knowledge/questions/{question_id}/answers",
        "/api/v2/systems/{system_id}/knowledge/targets/{target_id}",
        "/api/v2/systems/{system_id}/knowledge/nodes/{node_id}",
        "/api/v2/systems/{system_id}/knowledge/generation-batches",
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
        "/api/v2/console/activity",
    } <= paths


def test_fastapi_missing_run_uses_safe_not_found_response(tmp_path: Path) -> None:
    """未知运行报告应返回统一404且不得泄露Python堆栈。"""

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        response = client.get("/api/v2/runs/run-unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "traceback" not in response.text.lower()
