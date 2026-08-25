"""验证DSF源码发现、本地确认和Worker文件边界。"""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opentest.adapters.dsf_operations import DsfCanaryFixtureStore, DsfOperationBindingStore, DsfSourceDiscoverer
from opentest.adapters.dsf_proxy_worker import DsfProxyWorkerLauncher
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    DsfCanaryExecutionRequest,
    DsfCanaryFixture,
    DsfClientProfile,
    DsfExecutionRequest,
    DsfOperationDefinition,
    DsfOperationMutability,
    DsfOperationConfirmation,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticCallEdge,
    SemanticResolutionStatus,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
)


SYSTEM_ID = "demo-booking-core"


def _write_dsf_project(source_root: Path) -> None:
    """创建包含QA filter、发布XML和Facade接口的最小Java项目。

    Args:
        source_root: 测试专用源码根。

    Side Effects:
        写入仅位于pytest临时目录的DSF源码样本。
    """

    filter_path = source_root / "conf/filter/application.qa"
    xml_path = source_root / "app/src/main/resources/services.xml"
    facade_path = source_root / "api/src/main/java/com/example/OrderFacade.java"
    filter_path.parent.mkdir(parents=True)
    xml_path.parent.mkdir(parents=True)
    facade_path.parent.mkdir(parents=True)
    filter_path.write_text(
        "\n".join(
            (
                "dsf.service.config.registryhost=qa-registry.invalid",
                "dsf.service.config.name=demo-client",
                "dsf.service.config.env=qa",
                "dsf.service.config.targetenv=test",
                "provider.gs.name=dsf.demo.booking",
                "provider.version=1.2.3",
            )
        ),
        encoding="utf-8",
    )
    xml_path.write_text(
        """<beans xmlns:dubbo="urn:test">
        <bean class="com.ly.spat.dsf.server.DsfServiceGroup">
          <constructor-arg name="gsName" value="${provider.gs.name}"/>
          <constructor-arg name="version" value="${provider.version}"/>
        </bean>
        <dubbo:service interface="com.example.OrderFacade"/>
        </beans>""",
        encoding="utf-8",
    )
    facade_path.write_text(
        """package com.example;
        import javax.ws.rs.Path;
        @Path("order")
        public interface OrderFacade {
            @Path("orderDetail")
            OrderDetailResponse detail(OrderDetailRequest request);
            @Path("createOrder")
            CreateOrderResponse create(CreateOrderRequest request);
        }
        """,
        encoding="utf-8",
    )


def _operation(action: str = "orderDetail") -> DsfOperationDefinition:
    """构造Worker与绑定测试共用的固定只读操作。

    Args:
        action: 需要写入operation ID和目录的动作名。

    Returns:
        带最小源码证据的操作定义。
    """

    return DsfOperationDefinition(
        operation_id=f"dsf:{SYSTEM_ID}:order:{action}",
        provider_system_id=SYSTEM_ID,
        gs_name="dsf.demo.booking",
        service_name="order",
        version="1.2.3",
        action=action,
        request_type="OrderDetailRequest",
        response_type="OrderDetailResponse",
        mutability=DsfOperationMutability.READ_ONLY,
        source_refs=[SourceReference(path="OrderFacade.java", symbol=f"OrderFacade#{action}", line=1)],
    )


def test_dsf_source_discovery_builds_profile_and_fixed_operations(tmp_path: Path) -> None:
    """源码发现应解析Profile、provider坐标、类型和保守读写标记。"""

    source_root = tmp_path / "project"
    _write_dsf_project(source_root)

    profile, operations, warnings = DsfSourceDiscoverer().discover(SYSTEM_ID, source_root)

    assert profile.registry_host == "qa-registry.invalid"
    assert profile.client_name == "demo-client"
    assert profile.routing_environment == "qa"
    assert profile.target_environment == "test"
    assert warnings == []
    by_action = {operation.action: operation for operation in operations}
    assert by_action["orderDetail"].mutability == DsfOperationMutability.READ_ONLY
    assert by_action["createOrder"].mutability == DsfOperationMutability.WRITE
    assert by_action["orderDetail"].operation_id == f"dsf:{SYSTEM_ID}:order:orderDetail"


def test_dsf_source_discovery_builds_fixed_external_reference_operations(tmp_path: Path) -> None:
    """调用方sof:reference应按XML方法白名单生成外部DSF操作和源码证据。"""

    source_root = tmp_path / "project"
    _write_dsf_project(source_root)
    filter_path = source_root / "conf/filter/application.qa"
    filter_path.write_text(
        filter_path.read_text(encoding="utf-8")
        + "\nbooking.gs=dsf.iflightchainsaas.booking.core\nbooking.version=latest\n",
        encoding="utf-8",
    )
    reference_path = source_root / "app/src/main/resources/external.xml"
    reference_path.write_text(
        """<beans xmlns:sof="urn:test">
        <sof:reference id="tradeFacade" serviceName="trade" gsName="${booking.gs}"
            interface="com.ly.flight.chainsaas.booking.facade.TradeFacade"
            version="${booking.version}">
          <sof:method name="queryList" paramType="bodyParam"/>
        </sof:reference>
        </beans>""",
        encoding="utf-8",
    )

    _, operations, warnings = DsfSourceDiscoverer().discover(SYSTEM_ID, source_root)

    external = next(operation for operation in operations if operation.action == "queryList")
    assert external.operation_id == "dsf:iflightchainsaas.booking.core:trade:queryList"
    assert external.provider_system_id == "iflightchainsaas.booking.core"
    assert external.mutability == DsfOperationMutability.READ_ONLY
    assert external.source_refs[0].symbol == "com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList"
    assert not any("外部引用" in warning for warning in warnings)


def test_dsf_revision_materialization_rejects_parent_path(tmp_path: Path) -> None:
    """Git revision配置路径不得通过父级跳转逃出临时根。

    Args:
        tmp_path: Pytest隔离的revision临时根。

    Side Effects:
        不创建逃逸文件，也不调用Git或QA。
    """

    discoverer = DsfSourceDiscoverer()

    # 直接验证最终写入边界，异常必须发生在任何目录或文件创建之前。
    with pytest.raises(KnowledgeValidationError, match="path is unsafe"):
        discoverer._safe_materialization_path(tmp_path / "revision", Path("../escape.qa"))

    assert not (tmp_path / "escape.qa").exists()


def test_dsf_source_discovery_resolves_main_properties_and_rejects_non_qa_environment(tmp_path: Path) -> None:
    """主DSF properties占位映射应生效，生产或未知targetenv必须硬阻断。

    Args:
        tmp_path: pytest隔离Java项目根。

    Side Effects:
        仅创建本地源码配置样本，不访问任何注册中心。
    """

    source_root = tmp_path / "project"
    _write_dsf_project(source_root)
    filter_path = source_root / "conf/filter/application.qa"
    filter_path.write_text(
        "registry.host=qa-registry.invalid\nclient.identity=demo-client\ntarget.environment=prod\n"
        "provider.gs.name=dsf.demo.booking\nprovider.version=1.2.3\n",
        encoding="utf-8",
    )
    properties_path = source_root / "app/src/main/resources/dsf_application.properties"
    properties_path.write_text(
        "dsf.service.config.registryhost=${registry.host}\n"
        "dsf.service.config.name=${client.identity}\n"
        "dsf.service.config.env=qa\n"
        "dsf.service.config.targetenv=${target.environment}\n",
        encoding="utf-8",
    )

    profile, _, _ = DsfSourceDiscoverer().discover(SYSTEM_ID, source_root)

    assert profile.registry_host == "qa-registry.invalid"
    assert profile.client_name == "demo-client"
    assert profile.target_environment == "prod"
    assert profile.status == "BLOCKED"
    assert any("允许的QA集合" in warning for warning in profile.warnings)


def test_dsf_source_discovery_treats_mixed_read_write_verbs_as_write(tmp_path: Path) -> None:
    """queryAndUpdate与getAndDelete等混合动词不得被读前缀降级为只读。"""

    source_root = tmp_path / "project"
    _write_dsf_project(source_root)
    facade_path = source_root / "api/src/main/java/com/example/OrderFacade.java"
    facade_path.write_text(
        """package com.example;
        import javax.ws.rs.Path;
        @Path("order") public interface OrderFacade {
            @Path("queryAndUpdate") Object queryAndUpdate(Object request);
            @Path("getAndDelete") Object getAndDelete(Object request);
        }
        """,
        encoding="utf-8",
    )

    _, operations, _ = DsfSourceDiscoverer().discover(SYSTEM_ID, source_root)

    assert {operation.mutability for operation in operations} == {DsfOperationMutability.WRITE}


def test_dsf_binding_store_replaces_selection_with_private_file(tmp_path: Path) -> None:
    """项目确认应绑定Profile、扫描和操作定义摘要并保存为0600。"""

    store = DsfOperationBindingStore(tmp_path / "local")
    operation_id = _operation().operation_id
    profile_digest = "a" * 64
    operation_digest = "b" * 64

    bindings = store.write(
        SYSTEM_ID,
        profile_digest,
        {operation_id: operation_digest},
        "scan-confirmed",
    )

    binding_path = tmp_path / "local/dsf-bindings" / f"{SYSTEM_ID}.json"
    assert [binding.operation_id for binding in bindings] == [operation_id]
    assert store.profile_confirmed(SYSTEM_ID, profile_digest, "scan-confirmed") is True
    assert store.profile_confirmed(SYSTEM_ID, "c" * 64, "scan-confirmed") is False
    assert bindings[0].definition_digest == operation_digest
    assert binding_path.stat().st_mode & 0o777 == 0o600
    assert [binding.operation_id for binding in store.read(SYSTEM_ID)] == [operation_id]


def test_dsf_binding_store_rejects_invalid_digest_and_cross_system_content(tmp_path: Path) -> None:
    """本地允许列表不能接受非法摘要或伪造其他调用系统的绑定。"""

    store = DsfOperationBindingStore(tmp_path / "local")
    operation_id = _operation().operation_id
    with pytest.raises(KnowledgeValidationError, match="version digests"):
        store.write(SYSTEM_ID, "invalid", {operation_id: "b" * 64}, "scan-confirmed")
    with pytest.raises(KnowledgeValidationError, match="definition digest"):
        store.write(SYSTEM_ID, "a" * 64, {operation_id: "invalid"}, "scan-confirmed")

    binding_path = tmp_path / "local/dsf-bindings" / f"{SYSTEM_ID}.json"
    binding_path.parent.mkdir(parents=True)
    binding_path.write_text(
        json.dumps(
            {
                "bindings": [
                    {
                        "caller_system_id": "another-system",
                        "operation_id": operation_id,
                        "enabled": True,
                        "confirmed_at": "2026-08-20T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    os.chmod(binding_path, 0o600)
    with pytest.raises(ScopeViolationError, match="another system"):
        store.read(SYSTEM_ID)


def test_dsf_canary_fixture_store_keeps_payload_private_and_file_mode_0600(tmp_path: Path) -> None:
    """只读金丝雀Fixture摘要和权限都不得暴露原始订单标识。"""

    store = DsfCanaryFixtureStore(tmp_path / "local")
    operation_id = _operation().operation_id
    fixture = DsfCanaryFixture(
        caller_system_id=SYSTEM_ID,
        payload_by_operation_id={operation_id: {"orderNo": "sensitive-local-order"}},
    )

    summary = store.write(fixture)

    fixture_path = tmp_path / "local/dsf-canary-fixtures" / f"{SYSTEM_ID}.json"
    assert fixture_path.stat().st_mode & 0o777 == 0o600
    assert summary.configured_operation_ids == [operation_id]
    assert "sensitive-local-order" not in summary.model_dump_json()
    assert store.read(SYSTEM_ID).payload_by_operation_id[operation_id]["orderNo"] == "sensitive-local-order"


def test_dsf_canary_fixture_merge_preserves_concurrent_operation_updates(tmp_path: Path) -> None:
    """两个并发增量保存必须在同一排他锁内合并，不能发生后写覆盖。

    Args:
        tmp_path: pytest隔离的本地Fixture目录。

    Side Effects:
        两个线程并发写入测试专用0600文件。
    """

    store = DsfCanaryFixtureStore(tmp_path / "local")
    first_id = _operation("orderDetail").operation_id
    second_id = _operation("queryList").operation_id
    fixtures = [
        DsfCanaryFixture(caller_system_id=SYSTEM_ID, payload_by_operation_id={first_id: {"key": "one"}}),
        DsfCanaryFixture(caller_system_id=SYSTEM_ID, payload_by_operation_id={second_id: {"key": "two"}}),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        summaries = list(executor.map(store.merge, fixtures))

    assert summaries
    assert set(store.read(SYSTEM_ID).payload_by_operation_id) == {first_id, second_id}


class SuccessfulProtocolLauncher(DsfProxyWorkerLauncher):
    """不访问QA，仅模拟Worker正确写入0600成功响应。"""

    def __init__(self, worker_jar: Path, expected_target_environment: str = "qa"):
        """配置假Worker需要验证的独立targetenv。

        Args:
            worker_jar: 满足启动器存在性门禁的测试Jar路径。
            expected_target_environment: 本次协议请求应写入的targetenv值。
        """

        super().__init__(worker_jar)
        self.expected_target_environment = expected_target_environment

    def _run_worker(
        self,
        temporary_root: Path,
        response_path: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        """读取随机请求身份并写入严格响应，模拟Java文件协议。

        Args:
            temporary_root: 启动器创建的0700临时根。
            response_path: 测试替身应创建的响应文件。
            timeout_seconds: 已验证的调用超时，本替身不等待。

        Returns:
            表示Worker成功退出的完成结果。

        Side Effects:
            只在pytest临时目录创建一个0600响应文件。
        """

        del timeout_seconds
        request = json.loads((temporary_root / "request.json").read_text(encoding="utf-8"))
        properties = (temporary_root / "dsf_application.properties").read_text(encoding="utf-8")
        # DSF Client 2.5.11依赖env选择QA服务组，不能只写targetenv。
        assert "dsf.service.config.env=qa\n" in properties
        assert f"dsf.service.config.targetenv={self.expected_target_environment}\n" in properties
        response_path.write_text(
            json.dumps(
                {
                    "request_id": request["request_id"],
                    "operation_id": request["operation_id"],
                    "status": "success",
                    "output": {"found": True},
                    "error_code": "",
                    "message": "",
                    "elapsed_ms": 4,
                }
            ),
            encoding="utf-8",
        )
        os.chmod(response_path, 0o600)
        return subprocess.CompletedProcess([], 0, "", "")


def test_worker_launcher_uses_operation_id_protocol_without_exposing_service_fields(tmp_path: Path) -> None:
    """Python启动器应验证身份并只接收operation ID与payload作为请求。"""

    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-placeholder")
    profile = DsfClientProfile(
        system_id=SYSTEM_ID,
        registry_host="qa-registry.invalid",
        client_name="demo-client",
        routing_environment="qa",
        target_environment="test",
    )
    operation = _operation()
    request = DsfExecutionRequest(operation_id=operation.operation_id, payload={"orderNo": "local-fixture"})

    response = SuccessfulProtocolLauncher(worker_jar, "test").execute(SYSTEM_ID, profile, operation, request)

    assert response.status == "success"
    assert response.output == {"found": True}


def test_worker_launcher_rejects_request_operation_identity_mismatch(tmp_path: Path) -> None:
    """请求不能借由payload或错误ID绕过应用层解析的固定目录操作。"""

    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-placeholder")
    profile = DsfClientProfile(
        system_id=SYSTEM_ID,
        registry_host="qa-registry.invalid",
        client_name="demo-client",
        routing_environment="qa",
        target_environment="qa",
    )
    request = DsfExecutionRequest(
        operation_id=f"dsf:{SYSTEM_ID}:order:otherAction",
        payload={"gsName": "attacker-controlled"},
    )

    with pytest.raises(ScopeViolationError, match="does not match"):
        SuccessfulProtocolLauncher(worker_jar).execute(SYSTEM_ID, profile, _operation(), request)


def test_worker_launcher_rejects_non_qa_profile_before_process_start(tmp_path: Path) -> None:
    """即使绕过应用层，Worker启动器也必须在启动Java前拒绝非qa/test固定组合。"""

    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-placeholder")
    profile = DsfClientProfile(
        system_id=SYSTEM_ID,
        registry_host="qa-registry.invalid",
        client_name="demo-client",
        routing_environment="qa",
        target_environment="qa",
    )
    operation = _operation()
    request = DsfExecutionRequest(operation_id=operation.operation_id, payload={})

    with pytest.raises(ScopeViolationError, match="env=qa and targetenv=test"):
        SuccessfulProtocolLauncher(worker_jar).execute(SYSTEM_ID, profile, operation, request)


def test_indexed_execution_derives_legacy_routing_environment_without_rewriting_scan(tmp_path: Path) -> None:
    """旧扫描缺少env字段时应从一致源码派生QA路由且保持Manifest不可变。

    Args:
        tmp_path: Pytest隔离知识仓库、Java配置和假Worker根。

    Side Effects:
        仅调用本地协议替身并写入临时执行文件，不访问QA。
    """

    source_root = tmp_path / "source"
    _write_dsf_project(source_root)
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="DSF系统", source_path=str(source_root)))
    manifest = ScanManifest(
        scan_id="scan-dsf-legacy-routing-profile",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            registry_host="qa-registry.invalid",
            client_name="demo-client",
            target_environment="test",
        ),
        dsf_operations=[_operation()],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest_path = artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    original_bytes = manifest_path.read_bytes()
    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-placeholder")
    application.dsf_operations.launcher = SuccessfulProtocolLauncher(worker_jar, "test")

    response = application.dsf_operations.execute_indexed(
        SYSTEM_ID,
        manifest.scan_id,
        DsfExecutionRequest(operation_id=_operation().operation_id, payload={"orderNo": "local-only"}),
    )

    assert response.status == "success"
    assert manifest_path.read_bytes() == original_bytes


def test_indexed_execution_reads_clean_legacy_profile_from_recorded_commit(tmp_path: Path) -> None:
    """干净Git扫描应从记录提交补导env，不受当前工作树单独修改env影响。

    Args:
        tmp_path: Pytest隔离Git源码、知识仓库和假Worker根。

    Side Effects:
        创建本地Git提交和未提交配置差异，仅调用协议替身，不访问QA。
    """

    source_root = tmp_path / "source"
    _write_dsf_project(source_root)
    # 先固化一个不含工作区差异的扫描提交，模拟真实历史Manifest的可重放基线。
    subprocess.run(["git", "init", "-q", str(source_root)], check=True)
    subprocess.run(["git", "-C", str(source_root), "config", "user.email", "opentest@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(source_root), "config", "user.name", "OpenTest"], check=True)
    subprocess.run(["git", "-C", str(source_root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source_root), "commit", "-q", "-m", "baseline"], check=True)
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="DSF系统", source_path=str(source_root)))
    baseline = application.knowledge.git_repository.capture(source_root)
    # 历史Profile故意缺少env，补导只能读取上一步记录的Git提交。
    manifest = ScanManifest(
        scan_id="scan-dsf-clean-git-legacy-profile",
        system_id=SYSTEM_ID,
        baseline=baseline,
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            registry_host="qa-registry.invalid",
            client_name="demo-client",
            target_environment="test",
        ),
        dsf_operations=[_operation()],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest_path = artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    original_bytes = manifest_path.read_bytes()
    filter_path = source_root / "conf/filter/application.qa"
    original_filter = filter_path.read_text(encoding="utf-8")
    changed_filter = original_filter.replace("dsf.service.config.env=qa", "dsf.service.config.env=test")
    # 当前工作树只改变路由环境，用于证明执行不会把新env拼到旧provider坐标上。
    filter_path.write_text(
        changed_filter,
        encoding="utf-8",
    )
    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-placeholder")
    application.dsf_operations.launcher = SuccessfulProtocolLauncher(worker_jar, "test")

    # 假Worker要求env=qa；若错误读取当前工作树的test值，本次调用会立即失败。
    response = application.dsf_operations.execute_indexed(
        SYSTEM_ID,
        manifest.scan_id,
        DsfExecutionRequest(operation_id=_operation().operation_id, payload={"orderNo": "local-only"}),
    )

    assert response.status == "success"
    assert manifest_path.read_bytes() == original_bytes


def test_indexed_execution_rejects_changed_dirty_legacy_profile(tmp_path: Path) -> None:
    """带差异的历史扫描在env单独变化后必须拒绝拼接当前配置。

    Args:
        tmp_path: Pytest隔离的非Git源码、知识仓库和Manifest根。

    Side Effects:
        修改测试专用环境配置，不启动Worker或访问QA。
    """

    source_root = tmp_path / "source"
    _write_dsf_project(source_root)
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="DSF系统", source_path=str(source_root)))
    # 非Git扫描依赖dirty_digest重放，后续任何配置变化都必须触发拒绝。
    manifest = ScanManifest(
        scan_id="scan-dsf-dirty-legacy-profile",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            registry_host="qa-registry.invalid",
            client_name="demo-client",
            target_environment="test",
        ),
        dsf_operations=[_operation()],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest_path = artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    original_bytes = manifest_path.read_bytes()
    filter_path = source_root / "conf/filter/application.qa"
    original_filter = filter_path.read_text(encoding="utf-8")
    changed_filter = original_filter.replace("dsf.service.config.env=qa", "dsf.service.config.env=test")
    filter_path.write_text(
        changed_filter,
        encoding="utf-8",
    )

    # 基线门禁应在Worker启动前拒绝，且不能以兼容为由改写历史Manifest。
    with pytest.raises(KnowledgeValidationError, match="source baseline changed"):
        application.dsf_operations.execute_indexed(
            SYSTEM_ID,
            manifest.scan_id,
            DsfExecutionRequest(operation_id=_operation().operation_id, payload={"orderNo": "local-only"}),
        )

    assert manifest_path.read_bytes() == original_bytes


def test_application_fixture_execution_uses_confirmed_operation_and_consumer_evidence(tmp_path: Path) -> None:
    """验证部分解析consumer证据可关联操作且执行仍只读取已确认本地Fixture。

    Args:
        tmp_path: Pytest提供的隔离知识、源码、绑定和Worker目录。

    Side Effects:
        仅写入测试临时目录并调用不访问QA的Worker替身。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="DSF系统", source_path=str(source_root)))
    operation = _operation()
    caller_ref = SourceReference(path="src/OrderClient.java", symbol="demo.OrderClient#load()", line=18)
    operation = operation.model_copy(
        update={
            "source_refs": [
                SourceReference(path="OrderFacade.java", symbol="com.example.OrderFacade#orderDetail", line=1)
            ]
        }
    )
    manifest = ScanManifest(
        scan_id="scan-dsf-fixture",
        system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path=str(source_root), dirty=True, dirty_digest="digest"),
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            registry_host="qa-registry.invalid",
            client_name="demo-client",
            routing_environment="qa",
            target_environment="test",
        ),
        dsf_operations=[operation],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            call_edges=[
                SemanticCallEdge(
                    caller_symbol_id="demo.OrderClient#load()",
                    callee_symbol_id="com.example.OrderFacade#orderDetail(com.example.OrderRequest)",
                    callee_expression="orderDetail",
                    source_ref=caller_ref,
                    resolution_status=SemanticResolutionStatus.PARTIAL,
                    unresolved_reason="dependency_method_signature_unavailable",
                    confidence=0.75,
                )
            ],
        ),
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-placeholder")
    application.dsf_operations.launcher = SuccessfulProtocolLauncher(worker_jar, "test")

    catalog = application.get_dsf_operation_catalog(SYSTEM_ID)
    assert catalog.consumer_source_refs_by_operation_id[operation.operation_id] == [caller_ref]
    application.confirm_dsf_operations(
        SYSTEM_ID,
        DsfOperationConfirmation(operation_ids=[operation.operation_id]),
    )
    summary = application.save_dsf_canary_fixture(
        SYSTEM_ID,
        DsfCanaryFixture(
            caller_system_id=SYSTEM_ID,
            payload_by_operation_id={operation.operation_id: {"orderNo": "local-only"}},
        ),
    )

    response = application.execute_dsf_canary_fixture(
        SYSTEM_ID,
        DsfCanaryExecutionRequest(operation_id=operation.operation_id),
    )

    assert summary.configured_operation_ids == [operation.operation_id]
    assert response.output == {"found": True}


def test_dsf_confirmation_is_invalidated_by_scan_or_operation_definition_drift(tmp_path: Path) -> None:
    """调用方重扫或provider坐标变化后旧Profile和allowlist确认必须失效。

    Args:
        tmp_path: pytest隔离的系统、Manifest和绑定根。

    Side Effects:
        只发布本地Manifest并写入本地确认文件，不执行Worker或访问QA。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="DSF系统", source_path=str(source_root)))
    baseline = application.knowledge.git_repository.capture(source_root)
    profile = DsfClientProfile(
        system_id=SYSTEM_ID,
        registry_host="qa-registry.invalid",
        client_name="demo-client",
        routing_environment="qa",
        target_environment="qa",
    )
    operation = _operation()
    first = ScanManifest(
        scan_id="scan-dsf-confirmed",
        system_id=SYSTEM_ID,
        baseline=baseline,
        dsf_profile=profile,
        dsf_operations=[operation],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(first)
    artifacts.publish_latest(SYSTEM_ID, first.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.confirm_dsf_operations(
        SYSTEM_ID,
        DsfOperationConfirmation(operation_ids=[operation.operation_id]),
    )
    confirmed = application.get_dsf_operation_catalog(SYSTEM_ID)
    confirmed_digest = application.dsf_operations.execution_contract_digest(SYSTEM_ID)

    assert confirmed.profile is not None and confirmed.profile.status == "CONFIRMED"
    assert [binding.operation_id for binding in confirmed.bindings] == [operation.operation_id]

    # operation ID保持不变但version与调用方scan发生漂移，旧确认不得自动批准新路由。
    changed = first.model_copy(
        update={
            "scan_id": "scan-dsf-drifted",
            "dsf_operations": [operation.model_copy(update={"version": "2.0.0"})],
        }
    )
    artifacts.write_manifest(changed)
    artifacts.publish_latest(SYSTEM_ID, changed.scan_id)
    drifted = application.get_dsf_operation_catalog(SYSTEM_ID)

    assert drifted.profile is not None and drifted.profile.status == "CANDIDATE"
    assert drifted.bindings == []
    assert application.dsf_operations.execution_contract_digest(SYSTEM_ID) != confirmed_digest


def test_dsf_confirmation_rejects_duplicate_operation_ids(tmp_path: Path) -> None:
    """批量确认中的重复operation ID必须在写本地allowlist前拒绝。"""

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="DSF系统", source_path=str(source_root)))
    operation = _operation()
    manifest = ScanManifest(
        scan_id="scan-dsf-duplicates",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            registry_host="qa-registry.invalid",
            client_name="demo-client",
            routing_environment="qa",
            target_environment="qa",
        ),
        dsf_operations=[operation],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)

    with pytest.raises(KnowledgeValidationError, match="duplicates"):
        application.confirm_dsf_operations(
            SYSTEM_ID,
            DsfOperationConfirmation(operation_ids=[operation.operation_id, operation.operation_id]),
        )


def test_dsf_canary_fixture_api_never_echoes_sensitive_payload(tmp_path: Path) -> None:
    """回环Fixture API应手工校验原始JSON且响应只包含安全摘要。"""

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="DSF系统", source_path=str(source_root)))
    operation = _operation()
    manifest = ScanManifest(
        scan_id="scan-dsf-api",
        system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path=str(source_root), dirty=True, dirty_digest="digest"),
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            registry_host="qa-registry.invalid",
            client_name="demo-client",
            routing_environment="qa",
            target_environment="qa",
        ),
        dsf_operations=[operation],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.put(
            f"/api/v2/systems/{SYSTEM_ID}/dsf-operations/canary-fixture",
            json={
                "caller_system_id": SYSTEM_ID,
                "payload_by_operation_id": {operation.operation_id: {"orderNo": "never-echo-this"}},
            },
        )
        summary = client.get(f"/api/v2/systems/{SYSTEM_ID}/dsf-operations/canary-fixture")

    assert response.status_code == 200
    assert summary.status_code == 200
    assert "never-echo-this" not in response.text
    assert "never-echo-this" not in summary.text
    assert summary.json()["fixture"]["configured_operation_ids"] == [operation.operation_id]


def test_generic_dsf_execution_api_rejects_non_loopback_client(tmp_path: Path) -> None:
    """通用Agent执行入口不得通过非回环HTTP连接携带payload调用DSF。"""

    application = OpenTestApplication(tmp_path / "knowledge-base")
    with TestClient(create_app(application), client=("10.20.30.40", 50000)) as client:
        response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/dsf-operations/executions",
            json={"operation_id": _operation().operation_id, "payload": {"orderNo": "must-not-echo"}},
        )

    assert response.status_code == 409
    assert "must-not-echo" not in response.text


def test_dsf_binding_store_maps_non_object_json_to_stable_validation_error(tmp_path: Path) -> None:
    """合法但非对象的绑定JSON应返回稳定领域错误而不是AttributeError 500。"""

    store = DsfOperationBindingStore(tmp_path / "local")
    binding_path = tmp_path / "local/dsf-bindings" / f"{SYSTEM_ID}.json"
    binding_path.parent.mkdir(parents=True)
    binding_path.write_text("[]", encoding="utf-8")
    os.chmod(binding_path, 0o600)

    with pytest.raises(KnowledgeValidationError, match="invalid local DSF operation bindings"):
        store.read(SYSTEM_ID)
