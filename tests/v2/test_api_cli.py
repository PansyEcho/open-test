"""验证V2 FastAPI和CLI确实共享同一套基础应用服务。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication


def test_fastapi_registers_single_system_and_maps_scope_error(tmp_path: Path) -> None:
    """HTTP接口应注册首个系统并把第二系统冲突映射为409。"""

    first_source = tmp_path / "first"
    second_source = tmp_path / "second"
    first_source.mkdir()
    second_source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")

    with TestClient(create_app(application)) as client:
        assert client.get("/api/v2/health").json()["status"] == "ok"
        first_response = client.post(
            "/api/v2/systems",
            json={"system_id": "train-booking-core", "name": "火车票预订", "source_path": str(first_source)},
        )
        second_response = client.post(
            "/api/v2/systems",
            json={"system_id": "settlement-core", "name": "结算", "source_path": str(second_source)},
        )

    assert first_response.status_code == 201
    assert first_response.json()["system"]["system_id"] == "train-booking-core"
    assert second_response.status_code == 409
    assert second_response.json()["error"]["code"] == "scope_violation"


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
        "/api/v2/systems/{system_id}/scenarios/generations",
        "/api/v2/systems/{system_id}/scenarios/compile",
        "/api/v2/systems/{system_id}/snapshots",
        "/api/v2/systems/{system_id}/resources",
        "/api/v2/systems/{system_id}/resource-probes",
        "/api/v2/systems/{system_id}/oracle-operations",
        "/api/v2/systems/{system_id}/regression-suites/{suite_id}/runs",
        "/api/v2/systems/{system_id}/regression-suites/{suite_id}/reports",
        "/api/v2/systems/{system_id}/runs",
        "/api/v2/runs/{run_id}",
    } <= paths


def test_fastapi_missing_run_uses_safe_not_found_response(tmp_path: Path) -> None:
    """未知运行报告应返回统一404且不得泄露Python堆栈。"""

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        response = client.get("/api/v2/runs/run-unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "traceback" not in response.text.lower()
