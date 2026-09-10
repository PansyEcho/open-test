"""验证V2 FastAPI和CLI确实共享同一套基础应用服务。"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from opentest.api import CONSOLE_PAGE_VERSION, create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import report_task_progress
from opentest.domain.case_template_v4 import CaseTemplateHandoffV4, CaseTemplateSourceScope
from opentest.domain.errors import (
    CaseExecutionConflictError,
    CaseGenerationStateConflictError,
    KnowledgeNotFoundError,
    KnowledgeValidationError,
)
from opentest.domain.models import (
    AgentRunEvent,
    RuntimeToolSettings,
    RuntimeToolStatus,
    SourceBaseline,
    SystemDefinition,
    TaskProgressUpdate,
    TaskStatus,
)


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
        # 页面健康版本应跟随本次资产发布，避免与HTML检查使用不同常量。
        assert health["page_version"] == CONSOLE_PAGE_VERSION
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


def test_source_version_api_registers_and_updates_pin_only_for_loopback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """HTTP注册和独立更新端点应返回持久pin，并拒绝远端Git配置写入。

    Args:
        tmp_path: pytest隔离的Git源码、知识目录和任务记录。
        monkeypatch: 跳过真实scriptgen并同步执行准备阶段。

    Returns:
        None；首次revision、显式切换和loopback边界正确时通过。

    Side Effects:
        在临时Git仓库创建提交和受管tag，并通过测试API写隔离系统配置。
    """

    source = tmp_path / "refund-source"
    source.mkdir()
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "opentest@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "OpenTest"],
        check=True,
    )
    source_file = source / "RefundFacade.java"
    source_file.write_text("interface RefundFacade { void cancel(); }\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "RefundFacade.java"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "first"], check=True)
    first_commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    application = OpenTestApplication(tmp_path / "knowledge")

    def submit_scan_without_execution(request, prepare):
        """同步发布配置并返回完成任务，避免端点测试运行源码扫描器。

        Args:
            request: API构造的固定系统扫描请求。
            prepare: 需要在任务记录返回前执行的配置发布函数。

        Returns:
            已提交到隔离任务管理器的最小扫描任务。
        """

        prepare()
        return application.tasks.submit("source-pin-contract", request.system_id, lambda: {})

    monkeypatch.setattr(application, "ensure_scanner_ready", lambda: None)
    monkeypatch.setattr(application, "submit_prepared_source_scan", submit_scan_without_execution)
    with TestClient(create_app(application), client=("127.0.0.1", 50100)) as client:
        registered = client.post(
            "/api/v2/systems",
            json={
                "system_id": "refund-core",
                "name": "退款核心",
                "source_path": str(source),
                "source_revision": first_commit,
            },
        )
        source_file.write_text("interface RefundFacade { void cancel(); void query(); }\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "RefundFacade.java"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "second"], check=True)
        second_commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        changed = client.post(
            "/api/v2/systems/refund-core/source-version",
            json={"revision": second_commit},
        )

    assert registered.status_code == 201
    assert registered.json()["system"]["source_version"]["commit"] == first_commit
    assert changed.status_code == 202
    assert changed.json()["system"]["source_version"]["commit"] == second_commit

    with TestClient(create_app(application), client=("198.51.100.8", 50101)) as remote_client:
        denied_version = remote_client.post(
            "/api/v2/systems/refund-core/source-version",
            json={"revision": first_commit},
        )
        denied_update = remote_client.put(
            "/api/v2/systems/refund-core",
            json={
                "name": "远端不得修改",
                "source_path": str(source),
            },
        )

    assert denied_version.status_code == 409
    assert denied_update.status_code == 409
    assert application.store.get_system("refund-core").source_version.commit == second_commit


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
    # 页面身份与服务端健康检查必须使用同一版本，静态资产随本次行为更新。
    assert f'<meta name="opentest-page-version" content="{CONSOLE_PAGE_VERSION}">' in console_response.text
    assert f'/assets/app.js?v={CONSOLE_PAGE_VERSION}' in console_response.text
    assert script_response.status_code == 200
    assert 'const API_ROOT = "/api/v2"' in script_response.text
    assert "API_V3_ROOT" not in script_response.text
    assert "API_V4_ROOT" not in script_response.text
    assert "/api/projects" not in script_response.text


def test_runtime_settings_put_hides_legacy_models_and_preserves_http_job_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """运行设置只暴露活动字段，并保留惰性模型键与独立HTTP Job配置。

    Args:
        tmp_path: Pytest提供的隔离运行设置、系统设置和源码目录。
        monkeypatch: 替换扫描器诊断，保证请求完全离线。

    Returns:
        None；只更新页面字段、拒绝旧模型输入且其他本地设置保持时通过。

    Side Effects:
        通过回环测试客户端更新临时0600设置文件；不启动Agent、Worker或QA调用。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.store.register_system(
        SystemDefinition(
            system_id="train-booking-core",
            name="火车票预订",
            source_path=str(source_root),
        )
    )
    application.runtime_settings.write(
        RuntimeToolSettings(
            knowledge_agent="claude",
            codex_model="gpt-5.6-sol",
            codex_reasoning_effort="medium",
            case_template_v4_model="company-case-model",
            case_template_v4_reasoning_effort="high",
            knowledge_agent_prompt_template="旧模板 {{target_id}}",
        )
    )
    application.save_local_settings(
        "train-booking-core",
        "job-token-must-remain",
        "https://jobs.qa.invalid/gateway/v2",
    )

    def diagnose_without_scanner() -> RuntimeToolStatus:
        """返回不会探测本机模块或启动子进程的固定扫描器状态。

        Returns:
            表示离线夹具未配置scriptgen的安全状态。
        """

        return RuntimeToolStatus(
            status="MODULE_UNAVAILABLE",
            source="unset",
            message="离线测试未配置扫描器",
        )

    monkeypatch.setattr(
        application.runtime_settings,
        "diagnose",
        diagnose_without_scanner,
    )
    # 应用组合根不再持有后台Codex进程或桌面跳转依赖。
    assert not hasattr(application, "codex_app_server")
    assert not hasattr(application, "codex_desktop")

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.put(
            "/api/v2/local-settings/runtime",
            json={
                "scriptgen_pythonpath": "",
                "knowledge_agent_prompt_template": "新模板 {{target_id}}",
            },
        )
        preserved_job_settings = client.get(
            "/api/v2/systems/train-booking-core/local-settings"
        ).json()["local_settings"]
        removed_field_response = client.put(
            "/api/v2/local-settings/runtime",
            json={"codex_model": "gpt-5.6-sol"},
        )

    assert response.status_code == 200
    saved = response.json()["settings"]
    assert set(saved) == {"scriptgen_pythonpath", "knowledge_agent_prompt_template"}
    assert saved["knowledge_agent_prompt_template"] == "新模板 {{target_id}}"
    assert removed_field_response.status_code == 422
    assert "codex_model" in removed_field_response.text
    # 历史本地键保持惰性可审计，但不再由公开设置接口读取或修改。
    legacy_settings = application.runtime_settings.read()
    assert legacy_settings.knowledge_agent == "claude"
    assert legacy_settings.case_template_v4_model == "company-case-model"
    assert preserved_job_settings["qa_labrador_token"] == "job-token-must-remain"
    assert preserved_job_settings["qa_gateway_prefix"] == "https://jobs.qa.invalid/gateway/v2"


def test_v2_openapi_contains_single_system_generation_and_execution_workflow(
    tmp_path: Path,
) -> None:
    """OpenAPI应只暴露统一V2 Case生命周期，并移除历史Case传输契约。

    Args:
        tmp_path: pytest隔离的知识根目录。

    Returns:
        None；活动接口集合正确且五类后台Agent写路径未进入OpenAPI时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    with TestClient(create_app(application)) as client:
        openapi_paths = client.get("/openapi.json").json()["paths"]
        paths = set(openapi_paths)

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
    retired_agent_paths = {
        "/api/v2/local-settings/codex-model-catalog",
        "/api/v2/systems/{system_id}/knowledge/prompt-preview",
        "/api/v2/knowledge/client-handoffs/{handoff_id}/turns",
        "/api/v2/tasks/{task_id}/cancel-agent",
    }
    # 这些路径会选择模型、构造后台Prompt、启动turn或取消后台进程，原生Agent主流程不得再广告。
    assert retired_agent_paths.isdisjoint(paths)
    generation_batch_path = "/api/v2/systems/{system_id}/knowledge/generation-batches"
    assert "get" in openapi_paths[generation_batch_path]
    assert "post" not in openapi_paths[generation_batch_path]


def test_case_generation_start_returns_prepare_task_without_background_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """确认Case入口先返回当前原生Agent可接手的业务任务和handoff。

    Args:
        tmp_path: Pytest隔离应用根。
        monkeypatch: 替换prepare-only应用入口，验证HTTP契约而不调用模型。

    Returns:
        None；响应不含后台thread/model且GET可读取同一handoff时通过。
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
    )
    task_id = "task-" + "c" * 16

    received_request = {}

    def start_v4(_system_id, request):
        """返回已绑定业务任务的prepare响应而不启动真实模型。

        Args:
            _system_id: 路由解析出的目标系统。
            request: 只含目标、幂等身份和可选任务关联的Case准备请求。

        Returns:
            页面和Agent共享的task/handoff准备结果。
        """

        received_request["value"] = request
        return {
            "task": {
                "task_id": task_id,
                "status": "waiting_for_client",
                "target_id": handoff.entry_id,
            },
            "task_id": task_id,
            "handoff": handoff.model_dump(mode="json"),
            "handoff_id": handoff_id,
            "generation_id": generation_id,
            "status": "WAITING_FOR_AGENT",
            "continuation_instruction": f"继续 {task_id}",
        }

    def poll_v4(_handoff_id):
        """返回同一handoff轮询投影。

        Args:
            _handoff_id: API路由解析出的handoff身份。

        Returns:
            不含线程占用信息的同一handoff快照。
        """

        return {"handoff": handoff.model_dump(mode="json"), "generation": None}

    monkeypatch.setattr(application, "start_case_template_generation_v4", start_v4)
    monkeypatch.setattr(application, "get_case_template_handoff_v4", poll_v4)
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v2/systems/sample.java.system/case-generations",
            json={
                "operation_id": "sample.RefundFacade#cancel",
                "request_id": "case-start-api-request-0001",
            },
        )
        polled = client.get(f"/api/v2/case-handoffs/{handoff_id}")

    assert response.status_code == 202
    assert response.json()["task_id"] == task_id
    assert response.json()["handoff_id"] == handoff_id
    assert response.json()["generation_id"] == generation_id
    assert response.json()["continuation_instruction"] == f"继续 {task_id}"
    assert "thread_id" not in response.json()
    assert "codex_model" not in response.json()
    assert polled.status_code == 200
    assert polled.json()["handoff"]["thread_id"] == ""
    assert received_request["value"].request_id == "case-start-api-request-0001"
    assert not hasattr(received_request["value"], "codex_model")
    assert not hasattr(received_request["value"], "reasoning_effort")
    assert not hasattr(received_request["value"], "execution_mode")


def test_case_generation_rejects_removed_background_model_fields(
    tmp_path: Path,
) -> None:
    """Case prepare不再接受只能控制后台Agent的模型选择字段。

    Args:
        tmp_path: pytest隔离应用根。

    Returns:
        None；旧字段在进入业务准备前被严格请求模型拒绝时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v2/systems/sample.java.system/case-generations",
            json={
                "operation_id": "sample.RefundFacade#cancel",
                "request_id": "case-removed-model-field-0001",
                "codex_model": "missing-model",
            },
        )

    assert response.status_code == 422
    assert "codex_model" in response.text
    assert "extra_forbidden" in response.text


def test_case_generation_exposes_short_target_ambiguity_without_creating_handoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """短Facade名不唯一时HTTP返回明确歧义并要求完整限定路径。

    Args:
        tmp_path: Pytest隔离应用根。
        monkeypatch: 注入核心服务已确认的latest完整扫描歧义。

    Returns:
        None；响应保留validation错误和补全限定名提示时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")

    def reject_ambiguous_target(_system_id, _request):
        """模拟核心解析发现两个同名Facade而不创建handoff。

        Args:
            _system_id: 路由解析出的目标系统。
            _request: 包含短Facade路径的Case准备请求。

        Raises:
            KnowledgeValidationError: latest完整扫描中的短名无法唯一解析。
        """

        raise KnowledgeValidationError(
            "CaseTemplate target is ambiguous in the latest complete scan: "
            "RefundFacade#cancel; use the fully qualified Facade#method"
        )

    monkeypatch.setattr(application, "start_case_template_generation_v4", reject_ambiguous_target)
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v2/systems/sample.java.system/case-generations",
            json={
                "operation_id": "RefundFacade#cancel",
                "request_id": "case-short-ambiguous-0001",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert "ambiguous" in response.json()["error"]["message"]
    assert "fully qualified Facade#method" in response.json()["error"]["message"]


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


def test_single_target_generation_rejects_legacy_request_without_target_and_request_id(tmp_path: Path) -> None:
    """原生Agent知识准备API拒绝旧entry字段和缺失的稳定幂等身份。

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
    assert "request_id" in response.text


def test_legacy_generation_batch_start_route_is_removed(tmp_path: Path) -> None:
    """旧批量后台Agent写入口必须保持下线，只保留批次只读查询。

    Args:
        tmp_path: pytest隔离的知识根和本地任务目录。

    Returns:
        None；POST不再匹配旧启动流程并返回405时通过。
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

    assert response.status_code == 405


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
