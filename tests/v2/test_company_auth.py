"""验证真实公司接口适配边界、本机 Cookie 与插件/任务凭据生命周期。"""

from __future__ import annotations

import importlib.util
import json
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opentest.adapters import company_auth
from opentest.application.auth import AuthSettings, CompanyAuthService, current_employee
from opentest.application.auth_http import COOKIE_NAME, install_auth_routes
from opentest.domain.auth import AuthenticationError, EmployeeIdentity, TaskAccessGrant


class EmployeeDatabase:
    """只记录员工 upsert 的测试数据库，避免测试连接真实公司或共享库。"""

    def __init__(self):
        """初始化空 upsert 记录；不创建实际数据库。"""

        self.writes = []

    def execute(self, sql, parameters=()):
        """记录 SQL 和参数供归属断言；返回一条已写入记录，不接受其他业务操作。"""

        self.writes.append((sql, parameters))
        return 1


class CompanyBoundary:
    """模拟公司网络边界，浏览器仍必须经过完整一次性回调与 Cookie 轮换。"""

    def __init__(self):
        """准备两项公开员工字段及待回调地址，不保存真实公司 token。"""

        self.callback = ""
        self.employee = EmployeeIdentity(user_id="10001", name="员工甲")

    def authorization_url(self, callback_url):
        """记录服务生成的一次性 callback_url，并返回模拟公司授权页。"""

        self.callback = callback_url
        return "https://tccommon.17usoft.com/test-authorize"

    def verify_employee(self, access_token):
        """只接受测试网络令牌，返回公司边界中的员工；错误不建立会话。"""

        if access_token != "test-company-token":
            raise AuthenticationError("COMPANY_AUTH_REJECTED", "公司未接受本次验证。")
        return self.employee


def auth_app(tmp_path):
    """创建隔离的已安装认证 API；返回 app/service/公司边界供浏览器与任务测试。"""

    service = CompanyAuthService(EmployeeDatabase(), AuthSettings(credential_file=tmp_path / "credentials.json"), CompanyBoundary())
    app = FastAPI()

    @app.get("/api/v2/private")
    @app.post("/api/v2/private")
    def private_employee():
        """返回请求线程内已认证员工，证明前端不能自报归属且上下文完成传递。"""

        return current_employee().model_dump()

    install_auth_routes(app, service)
    return app, service, service.company


def login(client, company):
    """通过浏览器匿名会话、CSRF、公司回调登录，返回轮换后的当前会话公开信息。"""

    session = client.get("/api/v2/auth/session").json()
    headers = {"Origin": "http://127.0.0.1:8788", "X-CSRF-Token": session["csrf_token"]}
    started = client.post("/api/v2/auth/login", headers=headers)
    assert started.status_code == 200
    callback = urlsplit(company.callback).path
    finished = client.get(callback + "?access_token=test-company-token&refresh_token=discarded", follow_redirects=False)
    assert finished.status_code == 303 and finished.headers["location"] == "/"
    return client.get("/api/v2/auth/session").json()


def test_cookie_identity_requires_login_origin_and_csrf(tmp_path):
    """匿名、伪造来源和 CSRF 均拒绝；正常登录建立 name-newWorkId，业务归属只读公司身份。"""

    app, service, company = auth_app(tmp_path)
    with TestClient(app, base_url=service.settings.origin) as client:
        assert client.get("/api/v2/private").status_code == 401
        session = login(client, company)
        assert client.get("/api/v2/private").json()["display_name"] == "员工甲-10001"
        assert client.post("/api/v2/private").status_code == 403
        assert client.post("/api/v2/private", headers={"Origin": service.settings.origin, "X-CSRF-Token": "wrong"}).status_code == 403
        valid_headers = {"Origin": service.settings.origin, "X-CSRF-Token": session["csrf_token"]}
        assert client.post("/api/v2/private", headers=valid_headers).status_code == 200
        assert client.post("/api/v2/private", headers={**valid_headers, "Origin": "https://foreign.invalid"}).status_code == 403
        assert client.get("/api/v2/private", headers={"Host": "evil.invalid"}).status_code == 403
    # 线程/请求上下文离开 API 后必须恢复，不能把最后一个员工留给后续调用。
    with pytest.raises(AuthenticationError):
        current_employee()
    assert service.metadata.writes[0][1] == ("10001", "员工甲")
    assert stat.S_IMODE(service.settings.credential_file.stat().st_mode) == 0o600


@pytest.mark.parametrize("terminal", ["COMPLETED", "PARTIAL", "BLOCKED"])
def test_completed_web_generation_replay_returns_projection_without_dispatch(tmp_path, terminal):
    """真实HTTP路由收到终态安全投影时直接重放，不把字典当TaskRecord或重新运行Agent。"""

    from types import SimpleNamespace
    from unittest.mock import Mock
    from opentest.api import create_app

    _, service, company = auth_app(tmp_path)
    prepared = {"task": {"task_id": "task-finished", "status": "completed"}, "task_id": "task-finished",
        "status": terminal, "handoff": None, "cases": []}
    application = Mock()
    application.store = SimpleNamespace(root=tmp_path, metadata=None)
    application.auth = service
    application.start_case_template_generation_v4.return_value = prepared
    app = create_app(application)
    # 登录仍经过真实认证中间件；只有业务准备边界返回已完成的固定回执。
    with TestClient(app, base_url=service.settings.origin) as client:
        session = login(client, company)
        response = client.post("/api/v2/systems/orders/case-generations",
            headers={"Origin": service.settings.origin, "X-CSRF-Token": session["csrf_token"]},
            json={"request_id": "generation-replay", "operation_id": "query-order", "baseline_id": "baseline-one",
                  "environment_id": "uat", "interaction_mode": "web"})
    assert response.status_code == 202
    assert response.json() == prepared
    application.web_generation.start.assert_not_called()


def test_callback_is_browser_bound_one_time_and_rotates_session(tmp_path):
    """回调必须匹配原 Cookie；消费后不可重放，登录轮换旧 Cookie 且不把 token 带到首页。"""

    app, service, company = auth_app(tmp_path)
    with TestClient(app, base_url=service.settings.origin) as first, TestClient(app, base_url=service.settings.origin) as second:
        session = first.get("/api/v2/auth/session").json()
        old_cookie = first.cookies.get(COOKIE_NAME)
        first.post("/api/v2/auth/login", headers={"Origin": service.settings.origin, "X-CSRF-Token": session["csrf_token"]})
        callback = urlsplit(company.callback).path + "?access_token=test-company-token"
        denied = second.get(callback, follow_redirects=False)
        assert denied.headers["location"].startswith("/?login_error=")
        accepted = first.get(callback, follow_redirects=False)
        assert accepted.headers["location"] == "/"
        assert first.cookies.get(COOKIE_NAME) != old_cookie
        replay = first.get(callback, follow_redirects=False)
        assert replay.headers["location"].startswith("/?login_error=")
        assert "test-company-token" not in accepted.text


def test_user_bearer_expires_rotates_and_cannot_fall_back_to_cookie(tmp_path):
    """用户 bearer 与 Cookie 同期且账号切换立即失效；错误 bearer 不借有效 Cookie 降级通过。"""

    app, service, company = auth_app(tmp_path)
    with TestClient(app, base_url=service.settings.origin) as client:
        login(client, company)
        first = json.loads(service.settings.credential_file.read_text())["bearer"]
        assert client.post("/api/v2/private", headers={"Authorization": "Bearer " + first}).status_code == 200
        assert client.get("/api/v2/private", headers={"Authorization": "Bearer invalid"}).status_code == 401
        company.employee = EmployeeIdentity(user_id="10002", name="员工乙")
        login(client, company)
        assert client.get("/api/v2/private", headers={"Authorization": "Bearer " + first}).status_code == 401
        current = json.loads(service.settings.credential_file.read_text())["bearer"]
        session = service.browser_session(client.cookies.get(COOKIE_NAME))
        session.expires_at = time.time() - 1
        assert client.get("/api/v2/private", headers={"Authorization": "Bearer " + current}).status_code == 401
        assert service.settings.credential_file.exists()


def test_task_grant_survives_logout_but_not_scope_exit_completion_or_restart(tmp_path):
    """已授权任务不随人工退出失效；只能访问冻结工具，结束和服务重启后旧凭据失效。"""

    app, service, company = auth_app(tmp_path)
    with TestClient(app, base_url=service.settings.origin) as client:
        session = login(client, company)
        grant = TaskAccessGrant(company.employee, "task-authorized", time.time() + 100, frozenset({("GET", "/api/v2/private")}))
        bearer = service.issue_task_credential(grant)
        headers = {"Authorization": "Bearer " + bearer}
        logout_headers = {"Origin": service.settings.origin, "X-CSRF-Token": session["csrf_token"]}
        assert client.post("/api/v2/auth/logout", headers=logout_headers).status_code == 200
        assert client.get("/api/v2/private", headers=headers).json()["user_id"] == "10001"
        assert client.post("/api/v2/private", headers=headers).status_code == 403
        assert client.get("/api/v2/auth/me", headers=headers).status_code == 403
        assert not service.settings.credential_file.exists()
        restarted = CompanyAuthService(service.metadata, service.settings, company)
        with pytest.raises(AuthenticationError):
            restarted.authenticate("", bearer, ("GET", "/api/v2/private"))
        service.revoke_task_credentials("task-authorized")
        assert client.get("/api/v2/private", headers=headers).status_code == 401


@pytest.mark.parametrize("profile", [
    {"provider": "sso", "is_active": True, "id": "old-id", "name": "姓名"},
    {"provider": "sso", "is_active": True, "newWorkId": "10001", "name": " "},
    {"provider": "sso", "is_active": False, "newWorkId": "10001", "name": "姓名"},
])
def test_company_adapter_rejects_incomplete_or_inactive_identity(monkeypatch, profile):
    """公司响应没有稳定 newWorkId、姓名或有效 SSO 时拒绝，不能降级成旧 workId。"""

    def company_json(request):
        """提供测试公司响应并确认身份请求仅发往固定 HTTPS 接口。"""

        assert request.full_url == company_auth.USER_INFO_URL
        return profile

    monkeypatch.setattr(company_auth, "_company_json", company_json)
    with pytest.raises(AuthenticationError):
        company_auth.CompanyAuthClient().verify_employee("test-token")


@pytest.mark.parametrize("script_name", ["opentest_operations_mcp.py", "opentest_handoff_mcp.py"])
def test_plugins_reread_local_employee_bearer_and_reject_other_service(tmp_path, monkeypatch, script_name):
    """两个插件每次读取当前员工凭据，重新登录无需重建聊天，其他服务凭据不能误发送。"""

    script = Path(__file__).resolve().parents[2] / "opentest-plugin-marketplace/plugins/open-test-knowledge/scripts" / script_name
    specification = importlib.util.spec_from_file_location("auth_test_plugin", script)
    plugin = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(plugin)
    credential_file = tmp_path / "credentials.json"
    monkeypatch.setenv("OPENTEST_CREDENTIAL_FILE", str(credential_file))
    with pytest.raises(ValueError, match="重新登录"):
        plugin._local_user_bearer(plugin.DEFAULT_API_ROOT)
    for token in ("first-bearer", "second-bearer"):
        credential_file.write_text(json.dumps({"origin": "http://127.0.0.1:8788", "bearer": token, "expires_at": time.time() + 60}))
        assert plugin._local_user_bearer(plugin.DEFAULT_API_ROOT) == token
    with pytest.raises(ValueError, match="重新登录"):
        plugin._local_user_bearer("http://127.0.0.1:8789/api/v2")


@pytest.mark.parametrize("path", ["/api/v2/tasks/task-private/agent/context", "/api/v2/case-handoffs/private/status", "/api/v2/systems/system/operation-executions/private"])
def test_private_tool_routes_reject_other_employee_and_unknown_owner(tmp_path, monkeypatch, path):
    """登录不是任务授权；任务、handoff、执行必须有同一持久员工，NULL历史归属不能公开。"""

    from opentest.domain.auth import AuthenticatedIdentity

    _, service, company = auth_app(tmp_path)
    identity = AuthenticatedIdentity(company.employee, "user_bearer")
    # 所有私有详情走同一归属规则，即使调用者是已登录员工也不能跨人读取。
    monkeypatch.setattr(service.metadata, "fetch_one", lambda *args: {"owner_user_id": "10001"}, raising=False)
    service.authorize_private_route(identity, path)
    for owner in ("10002", None):
        monkeypatch.setattr(service.metadata, "fetch_one", lambda *args: {"owner_user_id": owner})
        with pytest.raises(AuthenticationError) as denied:
            service.authorize_private_route(identity, path)
        assert denied.value.status_code == 404


def test_task_worker_restores_persisted_employee_and_clears_context(tmp_path, monkeypatch):
    """线程任务读取持久归属，不能继承新登录员工；异常退出后恢复调用线程原上下文。"""

    from types import SimpleNamespace
    from opentest.application.auth import bind_authenticated_identity
    from opentest.application.mysql_tasks import MySqlTaskManager
    from opentest.domain.auth import AuthenticatedIdentity

    manager = MySqlTaskManager.__new__(MySqlTaskManager)
    manager.metadata = EmployeeDatabase()
    monkeypatch.setattr(manager, "get", lambda task_id: SimpleNamespace(owner_user_id="10001"))
    monkeypatch.setattr(manager.metadata, "fetch_one", lambda *args: {"user_id": "10001", "name": "员工甲"}, raising=False)
    caller = AuthenticatedIdentity(EmployeeIdentity(user_id="10002", name="员工乙"), "cookie")
    with bind_authenticated_identity(caller):
        with pytest.raises(RuntimeError):
            with manager.employee_scope("task-frozen"):
                assert current_employee().user_id == "10001"
                raise RuntimeError("isolated task failure")
        assert current_employee().user_id == "10002"
    with pytest.raises(AuthenticationError):
        current_employee()
