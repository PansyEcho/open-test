"""验证接口级覆盖增强的HTTP路由绑定和错误映射。"""

from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opentest.application.shared_workspace_api import create_shared_workspace_router
from opentest.domain.errors import KnowledgeValidationError


def _client(service: Mock) -> TestClient:
    """挂载真实共享工作区路由，并注入已登录员工供_scope读取。"""

    app = FastAPI()
    app.include_router(create_shared_workspace_router(SimpleNamespace(
        coverage_assistance=service, publications=Mock())))

    @app.middleware("http")
    async def identity(request, call_next):
        """模拟统一登录中间件写入的员工身份。"""

        request.state.employee = SimpleNamespace(user_id="employee-a")
        return await call_next(request)

    return TestClient(app)


def test_coverage_route_passes_interface_scope_and_environment() -> None:
    """覆盖摘要按接口和冻结环境读取，不要求case_id。"""

    service = Mock()
    service.interface_projection.return_value = {"coverage": {"status": "COMPLETED"}}
    response = _client(service).get(
        "/api/v2/systems/refund/baselines/baseline-a/coverage",
        params={"operation_id": "facade:Refund#billSupplement", "environment_id": "qa",
                "view": "mine"})
    assert response.status_code == 200
    assert response.json()["coverage"]["status"] == "COMPLETED"
    assert service.interface_projection.call_args.args == (
        "refund", "baseline-a", "employee-a", "facade:Refund#billSupplement", "qa", "mine")


def test_coverage_source_route_maps_invalid_material_to_conflict() -> None:
    """源码读取错误使用安全409返回，不泄露内部异常或路径。"""

    service = Mock()
    service.source_snippet.side_effect = KnowledgeValidationError("请求的源码位置不属于本次覆盖缺口")
    response = _client(service).get(
        "/api/v2/systems/refund/baselines/baseline-a/coverage/source",
        params={"enhancement_id": "coverage-a", "environment_id": "qa",
                "path": "src/Other.java", "start_line": 1, "end_line": 10})
    assert response.status_code == 409
    assert "不属于本次覆盖缺口" in response.json()["detail"]
    assert service.source_snippet.call_args.args == (
        "refund", "baseline-a", "employee-a", "qa", "coverage-a", "src/Other.java", 1, 10)
