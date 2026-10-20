"""验证系统天网设置的真实 HTTP 边界和元信息编辑的覆盖策略保留。"""

from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.models import CoverageAssistancePolicy, SystemDefinition


@pytest.fixture
def skyeye_client(tmp_path: Path) -> Iterator[tuple[OpenTestApplication, TestClient]]:
    """建立两个临时系统用于验证配置隔离，结束时关闭应用资源。

    Args:
        tmp_path: 测试隔离目录；仅使用虚构凭据。
    Yields:
        真实应用与回环 HTTP 客户端，不发起业务请求或扫描。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    for system_id in ("refund", "other"):
        source = tmp_path / system_id
        source.mkdir()
        application.register_system(SystemDefinition(system_id=system_id, name=system_id, source_path=str(source)))
    # TestClient 走真实请求校验与持久化；清理由应用生命周期与最终关闭共同保证。
    try:
        with TestClient(create_app(application), client=("127.0.0.1", 51000)) as client:
            yield application, client
    finally:
        application.close()


def test_skyeye_api_never_returns_token_and_respects_partial_updates(skyeye_client, caplog) -> None:
    """GET/PUT 只回显 AppId 和状态，省略保留、清除生效且两个系统互不影响。

    Args:
        skyeye_client: 隔离应用和真实 HTTP 客户端。
        caplog: 检查保存日志不包含虚构凭据。
    """

    application, client = skyeye_client
    url = "/api/v2/systems/refund/skyeye-settings"
    assert client.get(url).json() == {"skyeye_settings": {"skyeye_app_id": "", "token_configured": False}}
    response = client.put(url, json={"skyeye_app_id": "101", "skyeye_api_token": "fake-private-token"})
    assert response.status_code == 200
    assert response.json() == {"skyeye_settings": {"skyeye_app_id": "101", "token_configured": True}}
    assert "fake-private-token" not in client.get(url).text
    # 改 AppId 不能清除未提交的凭据，空字符串才是明确的清除操作。
    assert client.put(url, json={"skyeye_app_id": "102"}).status_code == 200
    assert application.get_skyeye_settings("refund").skyeye_api_token == "fake-private-token"
    assert client.get("/api/v2/systems/other/skyeye-settings").json()["skyeye_settings"]["token_configured"] is False
    assert client.put(url, json={"skyeye_api_token": ""}).json()["skyeye_settings"]["token_configured"] is False
    assert "fake-private-token" not in caplog.text


def test_skyeye_api_sanitizes_validation_and_restricts_loopback(skyeye_client) -> None:
    """错误输入与非本机调用不能泄漏 Token，设置接口不接受环境覆盖字段。

    Args:
        skyeye_client: 隔离应用和真实 HTTP 客户端。
    """

    application, client = skyeye_client
    url = "/api/v2/systems/refund/skyeye-settings"
    # 框架通常回显验证失败的 input；私有设置须固定为不含原文的错误。
    for payload in ({"skyeye_api_token": {"secret": "fake-private-token"}}, {"environment": "qa", "skyeye_api_token": "fake-private-token"}):
        response = client.put(url, json=payload)
        assert response.status_code == 422
        assert "fake-private-token" not in response.text
    invalid_json = client.put(url, content='{"skyeye_api_token": "fake-private-token"', headers={"Content-Type": "application/json"})
    assert invalid_json.status_code == 422 and "fake-private-token" not in invalid_json.text
    assert client.get("/api/v2/systems/absent/skyeye-settings").status_code == 404
    with TestClient(create_app(application), client=("192.0.2.1", 51000)) as remote:
        assert remote.get(url).status_code == 409
        response = remote.put(url, json={"skyeye_api_token": "fake-private-token"})
        assert response.status_code == 409
        assert "fake-private-token" not in response.text


def test_ordinary_system_edit_preserves_coverage_assistance(skyeye_client) -> None:
    """普通名称编辑不能把未出现在表单中的覆盖策略恢复为空。

    Args:
        skyeye_client: 隔离应用和真实 HTTP 客户端。
    """

    application, client = skyeye_client
    system = application.store.get_system("refund")
    system.coverage_assistance = CoverageAssistancePolicy(enabled=True)
    application.update_system("refund", system)
    # 仅提交元信息；返回与持久化模型都应保留原策略。
    response = client.put("/api/v2/systems/refund", json={"name": "renamed", "source_path": system.source_path})
    assert response.status_code == 200
    assert response.json()["system"]["coverage_assistance"]["enabled"] is True
    assert application.store.get_system("refund").coverage_assistance.enabled is True


def test_system_policy_can_change_without_private_skyeye_settings(skyeye_client) -> None:
    """策略与凭据独立保存，开关和保留粒度可提前选择且不隐式生成天网配置。

    Args:
        skyeye_client: 隔离应用和真实 HTTP 客户端。
    """

    application, client = skyeye_client
    system = application.store.get_system("refund")
    payload = {"name": system.name, "source_path": system.source_path,
               "coverage_assistance": {"enabled": True, "report_retention_scope": "OPERATION"}}
    response = client.put("/api/v2/systems/refund", json=payload)
    assert response.status_code == 200
    policy = response.json()["system"]["coverage_assistance"]
    assert policy["enabled"] is True and policy["report_retention_scope"] == "OPERATION"
    # 凭据就绪由运行时判断；提前保存开关不应创建或读取环境文件。
    assert not (application.knowledge_root / ".opentest" / "environments" / "refund" / "system.yaml").exists()
    payload["coverage_assistance"]["enabled"] = False
    assert client.put("/api/v2/systems/refund", json=payload).json()["system"]["coverage_assistance"]["enabled"] is False


def test_runtime_coverage_tools_round_trip_and_omission_preserves_values(skyeye_client) -> None:
    """工具设置有独立公开输入与响应，旧客户端只改扫描器时不清除覆盖配置。

    Args:
        skyeye_client: 隔离应用和真实 HTTP 客户端。
    """

    application, client = skyeye_client
    url = "/api/v2/local-settings/runtime"
    response = client.put(url, json={"jacoco_cli_path": "/fixture/jacoco.jar", "jacoco_java_command": "/fixture/java", "coverage_review_model": "fixture-review"})
    assert response.status_code == 200
    assert response.json()["settings"]["jacoco_cli_path"] == "/fixture/jacoco.jar"
    assert response.json()["settings"]["coverage_review_model"] == "fixture-review"
    # 省略与空字符串不同；前者不改现值，后者可清除可选审查模型。
    assert client.put(url, json={"scriptgen_pythonpath": ""}).status_code == 200
    assert client.get(url).json()["settings"]["jacoco_java_command"] == "/fixture/java"
    assert application.runtime_settings.read().coverage_review_model == "fixture-review"
    assert client.put(url, json={"coverage_review_model": ""}).json()["settings"]["coverage_review_model"] == ""
