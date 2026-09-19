"""验证项目独立逻辑环境与扫描关系的真实HTTP兼容边界，不访问业务系统。"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.system_relations import SystemRelationService
from opentest.domain.models import SourceReference, SystemDefinition, SystemDependencyBindingSubmission
from opentest.domain.system_relations import (
    RelatedSystem,
    SystemRelation,
    SystemRelationCatalog,
    SystemRelationEvidence,
    SystemRelationGap,
)


SYSTEM_ID = "refund-system"
PROVIDER_ID = "billing-system"


@pytest.fixture
def project_client(tmp_path: Path) -> Iterator[tuple[OpenTestApplication, TestClient]]:
    """建立两个隔离项目与真实FastAPI客户端，结束时释放应用任务资源。

    Args:
        tmp_path: 不含真实凭据、QA连接或源码扫描的临时目录。
    Yields:
        应用及以本机身份连接的HTTP测试客户端。
    Side Effects:
        只写临时项目注册文件，不启动扫描、Agent或Worker。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    for system_id in (SYSTEM_ID, PROVIDER_ID):
        source = tmp_path / system_id
        source.mkdir()
        application.register_system(SystemDefinition(system_id=system_id, name=system_id, source_path=str(source)))
    # ASGI请求仍经过真实请求校验、回环检查、Foundation及文件存储。
    try:
        with TestClient(create_app(application), client=("127.0.0.1", 51000)) as client:
            yield application, client
    finally:
        application.close()


def test_local_settings_profiles_are_isolated_and_missing_uat_stays_uncreated(
    project_client: tuple[OpenTestApplication, TestClient],
) -> None:
    """QA/UAT按各自query/body身份读写，空UAT读取不创建文件或复制QA。

    Args:
        project_client: 具有真实本地文件存储的隔离应用和HTTP客户端。
    Returns:
        None；两份设置、默认QA兼容及无隐式UAT写入均通过时结束。
    """

    application, client = project_client
    url = f"/api/v2/systems/{SYSTEM_ID}/local-settings"
    environment_root = application.knowledge_root / ".opentest" / "environments" / SYSTEM_ID
    qa_path = environment_root / "qa.yaml"
    uat_path = environment_root / "uat.yaml"
    qa = {"environment": "qa", "resource_config_environment": "test"}
    assert client.put(url, json=qa).status_code == 200
    qa_before = qa_path.read_bytes()

    # 缺失UAT只能返回空默认值，GET不能创建Profile；旧HTTP Job字段不再公开。
    missing_uat = client.get(url, params={"environment": "uat"})
    assert missing_uat.status_code == 200
    empty_settings = missing_uat.json()["local_settings"]
    assert empty_settings["environment"] == "uat"
    assert empty_settings["resource_config_environment"] == "auto"
    assert "qa_labrador_token" not in empty_settings
    assert "qa_gateway_prefix" not in empty_settings
    assert "token_source" not in empty_settings
    assert not uat_path.exists()
    assert qa_path.read_bytes() == qa_before

    uat = {"environment": "uat", "resource_config_environment": "dev"}
    assert client.put(url, json=uat).status_code == 200
    assert qa_path.read_bytes() == qa_before
    for environment, expected in (("qa", qa), ("uat", uat)):
        response = client.get(url, params={"environment": environment})
        assert response.status_code == 200
        actual = response.json()["local_settings"]
        assert all(actual[key] == value for key, value in expected.items())
    assert client.get(url).json()["local_settings"]["environment"] == "qa"
    assert "qa_labrador_token" not in client.get(url).json()["local_settings"]
    assert client.put(url, json={**qa, "qa_labrador_token": "retired"}).status_code == 422
    assert {item["environment"] for item in client.get(f"/api/v2/systems/{SYSTEM_ID}/environments").json()["environments"]} == {"qa", "uat"}


def test_legacy_test_environment_is_rejected_without_execution_or_file_rewrite(
    project_client: tuple[OpenTestApplication, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧test文件可保留，但settings与新执行API不得将test猜测为qa。

    Args:
        project_client: 隔离应用及真实HTTP客户端。
        monkeypatch: 为执行终端安插不可调用的观察替身。
    Returns:
        None；非法逻辑环境在业务执行前拒绝，历史文件保持原样时通过。
    """

    application, client = project_client
    url = f"/api/v2/systems/{SYSTEM_ID}/local-settings"
    environment_root = application.knowledge_root / ".opentest" / "environments" / SYSTEM_ID
    environment_root.mkdir(parents=True, exist_ok=True)
    legacy = environment_root / "test.yaml"
    legacy.write_text("system_id: refund-system\nenvironment: test\nvariables: {}\n", encoding="utf-8")
    legacy_before = legacy.read_bytes()
    dispatch = Mock()
    monkeypatch.setattr(application, "execute_operation", dispatch)
    monkeypatch.setattr(application.data_capabilities, "execute", dispatch)

    # 实际filter仍可以是test；被拒绝的是调用方提交的逻辑环境test。
    assert client.get(url, params={"environment": "test"}).status_code == 422
    assert client.put(url, json={"environment": "test", "resource_config_environment": "test"}).status_code == 422
    operation = client.post(f"/api/v2/systems/{SYSTEM_ID}/operation-executions", json={
        "operation_id": "facade:demo.RefundFacade#billSupplement", "environment": "test",
        "arguments": {}, "request_id": "legacy-environment-001",
    })
    assert operation.status_code == 400
    assert "qa or uat" in operation.text
    data = client.post(f"/api/v2/systems/{SYSTEM_ID}/data-capabilities/report/executions", json={
        "version": 1, "environment_id": "test", "inputs": {}, "request_id": "legacy-data-environment-001",
    })
    assert data.status_code == 422
    dispatch.assert_not_called()
    assert legacy.read_bytes() == legacy_before
    assert not (environment_root / "qa.yaml").exists()
    assert not (environment_root / "uat.yaml").exists()
    assert client.get(f"/api/v2/systems/{SYSTEM_ID}/environments").json()["environments"] == []


def test_retired_dependency_mutations_preserve_historical_binding_files(
    project_client: tuple[OpenTestApplication, TestClient],
) -> None:
    """旧PUT/DELETE关系接口返回410，不更改已有绑定和版本历史。

    Args:
        project_client: 临时应用及真实HTTP客户端。
    Returns:
        None；退役响应与所有历史绑定文件的字节均符合保护契约时通过。
    """

    application, client = project_client
    # 通过保留的存储实现建立历史夹具；产品关系写入口仍必须永久退役。
    application.store.put_system_dependency_binding(SYSTEM_ID, SystemDependencyBindingSubmission(
        provider_system_id=PROVIDER_ID, role="DOWNSTREAM", purposes=["SETUP"],
    ))
    system_root = application.store.system_root(SYSTEM_ID)
    binding_paths = [system_root / "dependencies.yaml", *(system_root / "dependencies").rglob("*.yaml")]
    before = {path: path.read_bytes() for path in binding_paths}
    url = f"/api/v2/systems/{SYSTEM_ID}/dependency-bindings/{PROVIDER_ID}"
    updated = client.put(url, json={"provider_system_id": PROVIDER_ID, "role": "UPSTREAM", "purposes": ["ACTION"]})
    deleted = client.delete(url)
    assert updated.status_code == deleted.status_code == 410
    assert "扫描" in updated.json()["detail"]
    assert {path: path.read_bytes() for path in binding_paths} == before
    assert set((system_root / "dependencies").rglob("*.yaml")) == set(binding_paths[1:])


def test_relations_http_returns_direct_scan_catalog_with_depth_and_evidence(
    project_client: tuple[OpenTestApplication, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只读关系HTTP响应使用页面约定的直接目录，保留深度、源码证据及缺口。

    Args:
        project_client: 隔离应用及真实HTTP客户端。
        monkeypatch: 仅替换耗时扫描聚合，关系算法由独立服务测试覆盖。
    Returns:
        None；HTTP响应没有旧bindings包装或遗漏证据字段时通过。
    """

    application, client = project_client
    catalog = SystemRelationCatalog(system_id=SYSTEM_ID,
        upstream=[RelatedSystem(system_id="booking-system", depth=1)],
        downstream=[RelatedSystem(system_id=PROVIDER_ID, depth=2)],
        relations=[SystemRelation(source_system_id="booking-system", target_system_id=SYSTEM_ID, relation_type="DSF",
            evidence=[SystemRelationEvidence(system_id="booking-system", source_scan_id="scan-booking-a",
                source_ref=SourceReference(path="src/RefundClient.java", line=12, symbol="billSupplement"), detail="匹配已发布DSF接口")])],
        gaps=[SystemRelationGap(system_id=PROVIDER_ID, code="MISSING_TOPIC", message="缺少MQ Topic配置")])
    projected = Mock(return_value=catalog)
    monkeypatch.setattr(SystemRelationService, "discovery_catalog", projected)
    historical_binding = application.store.system_root(SYSTEM_ID) / "dependencies.yaml"
    before = historical_binding.read_bytes()
    # 使用真实FastAPI序列化入口，保证模型字段与浏览器协商结果一致。
    response = client.get(f"/api/v2/systems/{SYSTEM_ID}/relations")
    assert response.status_code == 200
    assert response.json() == catalog.model_dump(mode="json")
    projected.assert_called_once_with(SYSTEM_ID)
    assert "catalog" not in response.json()
    assert historical_binding.read_bytes() == before
