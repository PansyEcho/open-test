"""验证逻辑QA/UAT、项目实际filter和一次运行固定的环境配置。"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from opentest.adapters.environment_config import LocalEnvironmentLoader, LocalSystemSettingsStore
from opentest.adapters.dsf_executor import DsfExecutor
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.dsf_proxy_worker import DsfProxyWorkerLauncher
from opentest.adapters.qa_active_worker import QaActiveWorkerLauncher
from opentest.application.dsf_operations import DsfOperationService
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    DiscoveredResource,
    DsfClientProfile,
    DsfExecutionRequest,
    DsfExecutionResponse,
    DsfOperationDefinition,
    DsfOperationMutability,
    OperationExecutionRequest,
    OperationKind,
    ResourceKind,
    ResourceRole,
    SourceReference,
    ToolDefinition,
    SystemDefinition,
)


def _write_profile(tmp_path: Path, logical: str = "qa", actual: str = "test") -> tuple[LocalEnvironmentLoader, Path]:
    """建立仅本地读取的项目Profile，真实filter可与逻辑环境不同。

    Args:
        tmp_path: pytest隔离目录。
        logical: QA或UAT入口。
        actual: 该入口实际使用的filter和资源环境。
    Returns:
        环境加载器与模拟源码根；不连接任何真实服务。
    """

    source = tmp_path / "source"
    filters = source / "conf/filter"
    filters.mkdir(parents=True, exist_ok=True)
    # 同一filter同时提供DSF身份和数据库分区，方便检验不同Worker使用相同配置。
    (filters / f"application.{actual}").write_text(
        f"dsf.service.config.registryhost={actual}.invalid\n"
        "dsf.service.config.name=provider-client\n"
        "dsf.service.config.env=qa\n"
        f"dsf.service.config.targetenv={actual}\n"
        "db.project=provider\n"
        f"db.environment={actual}\n"
        "db.password=private-test-config\n",
        encoding="utf-8",
    )
    settings = LocalSystemSettingsStore(tmp_path / "environments")
    settings.write("provider", "", resource_config_environment=actual, environment=logical)
    return LocalEnvironmentLoader(tmp_path / "environments"), source


def _operation() -> DsfOperationDefinition:
    """提供来自源码A的固定DSF调用坐标，用于证明Profile更新不会替换操作。

    Returns:
        补单报表只读操作定义。
    """

    return DsfOperationDefinition(
        operation_id="dsf:provider:report:query", provider_system_id="provider",
        gs_name="provider-baseline-a", service_name="report", version="version-a", action="query",
        mutability=DsfOperationMutability.READ_ONLY,
        source_refs=[SourceReference(path="Report.java", symbol="query")],
    )


def test_project_profiles_keep_qa_and_uat_settings_independent(tmp_path: Path) -> None:
    """修改UAT的实际dev配置不会改写QA、旧test文件或历史设置内容。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path)
    settings = LocalSystemSettingsStore(loader.environment_root)
    qa_path = loader.environment_root / "provider/qa.yaml"
    qa_before = qa_path.read_bytes()
    legacy_path = qa_path.with_name("test.yaml")
    legacy_path.write_text("environment: test\n", encoding="utf-8")
    # 同项目两个Profile独立保存，旧test文件不参与目录投影但仍保留。
    _write_profile(tmp_path, "uat", "dev")
    assert qa_path.read_bytes() == qa_before
    assert settings.read("provider", "qa").resource_config_environment == "test"
    assert settings.read("provider", "uat").resource_config_environment == "dev"
    assert [item.environment for item in loader.list_catalog("provider")] == ["qa", "uat"]
    assert legacy_path.read_text(encoding="utf-8") == "environment: test\n"
    assert loader.resolve_execution_profile("provider", "uat", source).dsf_profile.target_environment == "dev"


def test_old_test_selector_requires_explicit_logical_environment(tmp_path: Path) -> None:
    """旧test即使被写成QA别名，也不能静默解释成新的逻辑QA。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path)
    path = loader.environment_root / "provider/qa.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "aliases: [test]\n", encoding="utf-8")
    # 明确拒绝selector，防止实际test同时属于QA/UAT时走向错误项目环境。
    with pytest.raises(KnowledgeValidationError, match="select a logical environment explicitly"):
        loader.resolve_execution_profile("provider", "test", source)
    with pytest.raises(ValidationError):
        DsfExecutionRequest(operation_id=_operation().operation_id, environment="test")


def test_missing_uat_profile_does_not_fall_back_to_qa(tmp_path: Path) -> None:
    """未配置UAT时保留精确缺口，不借用已有QA Profile。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path)
    # 对尚未配置的逻辑环境，Worker应尚未有任何机会启动。
    with pytest.raises(KnowledgeValidationError, match="provider: uat"):
        loader.resolve_execution_profile("provider", "uat", source)


def test_job_credentials_are_only_resolved_when_job_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无关Job Token与旧连接ENV缺失不阻塞DSF，但执行Job时必须真实解析所需Token。

    Args:
        tmp_path: pytest隔离目录。
        monkeypatch: 设置或移除本测试专用环境变量。
    Returns:
        None；只有Job任务消费并固定其凭据时通过。
    """

    loader, source = _write_profile(tmp_path)
    settings_path = loader.environment_root / "provider/qa.yaml"
    settings_path.write_text(
        "system_id: provider\nenvironment: qa\nresource_config_environment: test\n"
        "qa_gateway_prefix: https://uat.example.invalid/gateway/provider/v2\n"
        "values:\n  limit: 3\n  tool_environment:\n    LABRADOR_TOKEN: '${ENV:OPENTEST_TEST_JOB_TOKEN}'\n"
        "connections:\n  old_db:\n    password: '${ENV:OPENTEST_TEST_UNNEEDED_PASSWORD}'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENTEST_TEST_JOB_TOKEN", raising=False)
    monkeypatch.delenv("OPENTEST_TEST_UNNEEDED_PASSWORD", raising=False)
    # 普通任务不触碰Job凭据，也不解析统一Worker不会消费的旧连接字典。
    regular = loader.resolve_execution_profile("provider", "qa", source)
    assert regular.definition.values == {"limit": 3}
    with pytest.raises(KnowledgeValidationError, match="OPENTEST_TEST_JOB_TOKEN"):
        loader.resolve_execution_profile("provider", "qa", source, include_job_settings=True)
    monkeypatch.setenv("OPENTEST_TEST_JOB_TOKEN", "current-private-token")
    job = loader.resolve_execution_profile("provider", "qa", source, include_job_settings=True)
    monkeypatch.setenv("OPENTEST_TEST_JOB_TOKEN", "next-private-token")
    assert job.definition.values["tool_environment"]["LABRADOR_TOKEN"] == "current-private-token"
    assert job.definition.qa_gateway_prefix == "https://uat.example.invalid/gateway/provider/v2"


def test_job_executor_passes_profile_url_without_changing_frozen_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Job进程使用已解析Profile URL，保留固定扫描脚本且报告不暴露部署地址。

    Args:
        tmp_path: pytest隔离目录。
        monkeypatch: 用进程替身截获命令，避免访问真实Job。
    Returns:
        None；明确URL覆盖和固定脚本同时保留时通过。
    """

    script = tmp_path / "job.sh"
    script.write_text("#!/bin/bash\n# frozen default: https://qa.example.invalid/job/retry\n", encoding="utf-8")
    tool = ToolDefinition(tool_id="job.retry", system_id="provider", display_name="重试Job",
                          script_path=str(script), source_id="job.retry", transport="generated_cli", metadata={"status": "ready"})
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, stdout='{"accepted":true}', stderr=""))
    monkeypatch.setattr("opentest.adapters.dsf_executor.subprocess.run", runner)
    executor = DsfExecutor({"LABRADOR_TOKEN": "private-token"})
    # 使用scriptgen已有的--url协议，接口path由主执行器从固定Job定义生成。
    outcome = executor.execute(tool, tmp_path, {}, 30, "https://uat.example.invalid/job/retry")
    command = runner.call_args.args[0]
    assert command[-2:] == ["--url", "https://uat.example.invalid/job/retry"]
    assert runner.call_args.kwargs["env"]["LABRADOR_TOKEN"] == "private-token"
    assert "frozen default: https://qa.example.invalid" in script.read_text(encoding="utf-8")
    assert "https://uat.example.invalid" not in " ".join(outcome.command)


def test_execution_profile_is_stable_after_local_filter_changes(tmp_path: Path) -> None:
    """运行开始后的配置变更仅影响下次运行，本次DSF和资源值保持绑定。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path)
    bound = loader.resolve_execution_profile("provider", "qa", source)
    filter_path = source / "conf/filter/application.test"
    filter_path.write_text(filter_path.read_text(encoding="utf-8").replace("=test", "=dev"), encoding="utf-8")
    # 同次结果为只读独立映射，不受底层文件内容和调用方后续赋值影响。
    assert bound.dsf_profile.environment == "qa"
    assert bound.dsf_profile.target_environment == "test"
    assert bound.require_resource_values(["db.environment"]) == {"db.environment": "test"}
    with pytest.raises(TypeError):
        bound.resource_values["db.environment"] = "dev"
    assert "private-test-config" not in repr(bound)
    assert loader.resolve_execution_profile("provider", "qa", source).dsf_profile.target_environment == "dev"


def test_missing_dsf_fields_do_not_block_database_profile_values(tmp_path: Path) -> None:
    """纯数据查询可使用已证明的DB配置，不因未消费的DSF字段阻塞。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path)
    (source / "conf/filter/application.test").write_text("db.environment=test\n", encoding="utf-8")
    bound = loader.resolve_execution_profile("provider", "qa", source)
    assert bound.require_resource_values(["db.environment"]) == {"db.environment": "test"}
    # 真正缺少当前操作所需的键时才失败，且错误不带其它配置值。
    with pytest.raises(KnowledgeValidationError, match="db.project"):
        bound.require_resource_values(["db.project"])


@pytest.mark.parametrize("missing_field", ["registry_host", "client_name", "routing_environment", "target_environment"])
def test_dsf_plan_preflight_rejects_missing_fields_without_calling_worker(tmp_path: Path, missing_field: str) -> None:
    """即使Profile仍标为CANDIDATE，缺少DSF实际必需键也必须在业务计划预检时报错。

    Args:
        tmp_path: pytest隔离Profile目录。
        missing_field: 本轮模拟缺失的DSF部署字段。
    Returns:
        None；缺键被准确报告且没有Worker调用时通过。
    """

    loader, source = _write_profile(tmp_path)
    bound = loader.resolve_execution_profile("provider", "qa", source)
    launcher = Mock()
    service = DsfOperationService(Mock(), Mock(), Mock(), Mock(), launcher)
    # 保留原状态只移除实际字段，避免仅检查status而漏过不完整的旧Profile。
    incomplete = bound.dsf_profile.model_copy(update={missing_field: ""})
    with pytest.raises(KnowledgeValidationError, match=missing_field):
        service.validate_execution_profile(incomplete, "provider", "qa")
    launcher.execute.assert_not_called()


def test_database_plan_preflight_does_not_require_dsf_or_start_worker(tmp_path: Path) -> None:
    """纯DB计划只检查其项目、数据库键和实际环境，不依赖DSF配置或启动Worker。

    Args:
        tmp_path: pytest隔离Profile与无Worker制品目录。
    Returns:
        None；DSF BLOCKED但DB所需键完整时预检成功。
    """

    loader, source = _write_profile(tmp_path)
    (source / "conf/filter/application.test").write_text("db.project=provider\ndb.environment=test\n", encoding="utf-8")
    bound = loader.resolve_execution_profile("provider", "qa", source)
    resource = DiscoveredResource(
        resource_id="resource:provider:database:main", system_id="provider", kind=ResourceKind.MYSQL,
        role=ResourceRole.DATABASE, logical_name="main", database_name="main",
        database_project_config_key="db.project", database_environment_config_key="db.environment",
        source_refs=[SourceReference(path="database.xml", symbol="main")],
    )
    launcher = QaActiveWorkerLauncher(tmp_path / "missing-worker.jar")
    launcher._run_worker = Mock(side_effect=AssertionError("preflight must not invoke Worker"))
    # 缺少DSF身份是无关能力的缺口，不能成为纯DB任务的全局前置。
    assert bound.dsf_profile.status == "BLOCKED"
    assert launcher.validate_execution_profile(bound, OperationKind.DATABASE, resource) == {
        "db.project": "provider", "db.environment": "test",
    }
    launcher._run_worker.assert_not_called()


def test_mq_plan_preflight_reports_missing_topic_before_worker(tmp_path: Path) -> None:
    """MQ计划预检发现缺少实际Topic时立即阻断，不能等其他步骤写完后再发现。

    Args:
        tmp_path: pytest隔离Profile目录。
    Returns:
        None；明确报告缺Topic且没有Worker调用时通过。
    """

    loader, source = _write_profile(tmp_path)
    with (source / "conf/filter/application.test").open("a", encoding="utf-8") as stream:
        stream.write("mq.nameserver=broker.invalid:9876\n")
    bound = loader.resolve_execution_profile("provider", "qa", source)
    resource = DiscoveredResource(
        resource_id="resource:provider:mq:consumer:report", system_id="provider", kind=ResourceKind.MQ,
        role=ResourceRole.CONSUMER, logical_name="report", nameserver_config_key="mq.nameserver",
        topic_config_key="mq.report.topic", source_refs=[SourceReference(path="mq.xml", symbol="report")],
    )
    launcher = QaActiveWorkerLauncher(tmp_path / "missing-worker.jar")
    launcher._run_worker = Mock(side_effect=AssertionError("preflight must not invoke Worker"))
    # 缺键在本地预检暴露，不依赖连接SDK后失败来识别问题。
    with pytest.raises(KnowledgeValidationError, match="mq.report.topic"):
        launcher.validate_execution_profile(bound, OperationKind.MQ, resource)
    launcher._run_worker.assert_not_called()


def test_dsf_runtime_profile_preserves_fixed_operation_contract(tmp_path: Path) -> None:
    """逻辑UAT使用自己的实际dev路由，调用坐标仍来自生产源码A。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path, "uat", "dev")
    bound = loader.resolve_execution_profile("provider", "uat", source)
    operation = _operation()
    artifacts = Mock()
    artifacts.read.return_value = SimpleNamespace(dsf_operations=[operation], dsf_profile=DsfClientProfile(system_id="provider"))
    launcher = Mock()
    launcher.execute.return_value = DsfExecutionResponse(request_id="fake-worker", operation_id=operation.operation_id, status="success")
    service = DsfOperationService(Mock(), artifacts, Mock(), Mock(), launcher)
    request = DsfExecutionRequest(operation_id=operation.operation_id, environment="uat")
    # 不执行真实DSF，只核对应用服务交给最终Worker的固定定义和部署配置。
    service.execute_indexed("provider", "scan-baseline-a", request, profile=bound.dsf_profile)
    artifacts.read.assert_called_once_with("provider", "scan-baseline-a")
    _, dispatched_profile, dispatched_operation, _ = launcher.execute.call_args.args
    assert dispatched_profile.target_environment == "dev"
    assert dispatched_operation.version == "version-a"
    assert dispatched_operation.gs_name == "provider-baseline-a"


@pytest.mark.parametrize("pass_bound_profile", [False, True])
def test_external_dsf_uses_registered_target_project_profile(tmp_path: Path, pass_bound_profile: bool) -> None:
    """外部调用使用目标项目UAT的实际dev配置，来源扫描只固定操作坐标。

    Args:
        tmp_path: pytest隔离项目、配置与扫描目录。
        pass_bound_profile: 覆盖运行预绑定与兼容直接调用两条入口。
    Returns:
        None；两条入口均使用目标项目真实Profile且拒绝来源项目Profile时通过。
    """

    loader, source = _write_profile(tmp_path, "uat", "dev")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.initialize()
    store.register_system(SystemDefinition(system_id="provider", name="目标项目", source_path=str(source)))
    settings = LocalSystemSettingsStore(store.root / ".opentest/environments")
    settings.write("provider", "", resource_config_environment="dev", environment="uat")
    operation = _operation()
    artifacts = Mock()
    artifacts.read.return_value = SimpleNamespace(dsf_operations=[operation])
    launcher = Mock()
    launcher.execute.return_value = DsfExecutionResponse(request_id="fake", operation_id=operation.operation_id, status="success")
    service = DsfOperationService(store, artifacts, Mock(), Mock(), launcher)
    bound = loader.resolve_execution_profile("provider", "uat", source)
    request = DsfExecutionRequest(operation_id=operation.operation_id, environment="uat")
    # 原调用方扫描A的坐标不替换，但最终Worker的身份和路由均属于目标项目。
    service.execute_external_indexed("caller", "scan-caller-a", request,
                                     profile=bound.dsf_profile if pass_bound_profile else None)
    artifacts.read.assert_called_once_with("caller", "scan-caller-a")
    actual_system, actual_profile, actual_operation, _ = launcher.execute.call_args.args
    assert actual_system == "provider"
    assert actual_profile.system_id == "provider"
    assert actual_profile.environment == "uat" and actual_profile.target_environment == "dev"
    assert actual_operation.version == "version-a"
    caller_profile = bound.dsf_profile.model_copy(update={"system_id": "caller"})
    with pytest.raises(ScopeViolationError, match="target project"):
        service.execute_external_indexed("caller", "scan-caller-a", request, profile=caller_profile)
    assert launcher.execute.call_count == 1


def test_external_dsf_unregistered_target_is_blocked_before_worker(tmp_path: Path) -> None:
    """外部引用或伪造已解析Profile不能代替目标项目接入。

    Args:
        tmp_path: pytest隔离知识目录。
    Returns:
        None；无目标项目时在读取本地配置和启动Worker前拒绝。
    """

    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.initialize()
    operation = _operation()
    artifacts = Mock()
    artifacts.read.return_value = SimpleNamespace(dsf_operations=[operation])
    launcher = Mock()
    service = DsfOperationService(store, artifacts, Mock(), Mock(), launcher)
    # 即使传入看似完整的远端Profile，也必须重新验证当前项目仍然接入。
    profile = DsfClientProfile(system_id="provider", routing_environment="qa", target_environment="test")
    with pytest.raises(KnowledgeNotFoundError, match="provider"):
        service.execute_external_indexed("caller", "scan-caller-a", DsfExecutionRequest(operation_id=operation.operation_id, environment="qa"), profile=profile)
    launcher.execute.assert_not_called()


def test_dsf_launcher_accepts_logical_qa_with_actual_test(tmp_path: Path) -> None:
    """最终进程边界接受QA到实际test，同时仍拒绝绑定错误的逻辑Profile。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path)
    bound = loader.resolve_execution_profile("provider", "qa", source)
    jar = tmp_path / "worker.jar"
    jar.write_bytes(b"placeholder")
    launcher = DsfProxyWorkerLauncher(jar)
    operation = _operation()

    def simulate_dsf_worker(root: Path, response_path: Path, timeout: int):
        """完成真实DSF文件协议，并断言SDK配置保持实际test目标。

        Args:
            root: 私有请求和SDK配置目录。
            response_path: 响应文件位置。
            timeout: 既有协议超时参数。
        Returns:
            成功进程结果；无网络调用。
        """

        payload = json.loads((root / "request.json").read_text(encoding="utf-8"))
        # 不将逻辑QA写成实际target，模拟Worker看到的是Profile解析后的真实配置。
        assert "dsf.service.config.targetenv=test" in (root / "dsf_application.properties").read_text(encoding="utf-8")
        response = DsfExecutionResponse(request_id=payload["request_id"], operation_id=operation.operation_id, status="success")
        response_path.write_text(response.model_dump_json(), encoding="utf-8")
        response_path.chmod(0o600)
        return subprocess.CompletedProcess([], 0)

    launcher._run_worker = Mock(side_effect=simulate_dsf_worker)
    request = DsfExecutionRequest(operation_id=operation.operation_id, environment="qa")
    # 文件协议正常构造，但Java由替身隔离，测试不访问QA。
    launcher.execute("provider", bound.dsf_profile, operation, request)
    launcher._run_worker.assert_called_once()
    with pytest.raises(ScopeViolationError, match="logical environment"):
        launcher.execute("provider", bound.dsf_profile, operation, request.model_copy(update={"environment": "uat"}))


def test_database_worker_uses_bound_actual_environment(tmp_path: Path) -> None:
    """共享执行器传入逻辑UAT时，DB Worker用Profile的实际dev及最小资源值。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        None；断言通过表示目标环境与配置边界符合要求。
    """

    loader, source = _write_profile(tmp_path, "uat", "dev")
    bound = loader.resolve_execution_profile("provider", "uat", source)
    resource = DiscoveredResource(
        resource_id="resource:provider:database:main", system_id="provider", kind=ResourceKind.MYSQL,
        role=ResourceRole.DATABASE, logical_name="main", database_name="main",
        database_project_config_key="db.project", database_environment_config_key="db.environment",
        source_refs=[SourceReference(path="database.xml", symbol="main")],
    )
    jar = tmp_path / "worker.jar"
    jar.write_bytes(b"placeholder")
    launcher = QaActiveWorkerLauncher(jar)
    observed: list[tuple[str, dict]] = []

    def simulate_worker(application: str, actual: str, request_path: Path, response_path: Path, timeout: int):
        """模拟私有Worker协议并捕获实际环境；五项参数是既有启动器协议。

        Args:
            application: 实际DAL项目身份。
            actual: 传给JVM的真实环境。
            request_path: Python生成的私有请求文件。
            response_path: 本测试写入的响应位置。
            timeout: 既有Worker超时参数。
        Returns:
            成功进程结果；无网络副作用。
        """

        payload = json.loads(request_path.read_text(encoding="utf-8"))
        observed.append((actual, payload))
        # 使用真实协议响应身份，确保执行完整读取与校验路径。
        response_path.write_text(json.dumps({"request_id": payload["request_id"], "status": "completed", "result": {"rows": []}}), encoding="utf-8")
        response_path.chmod(0o600)
        return subprocess.CompletedProcess([], 0)

    launcher._run_worker = simulate_worker
    request = OperationExecutionRequest(operation_id="database:provider:main", request_id="profile-database-001", environment="uat")
    # 删除原filter也不影响已绑定运行，证明Worker不会再次读取当前配置。
    (source / "conf/filter/application.dev").unlink()
    assert launcher.execute_resolved(bound, OperationKind.DATABASE, resource, request) == {"rows": []}
    assert observed[0][0] == "dev"
    assert observed[0][1]["resolved_config"] == {"db.project": "provider", "db.environment": "dev"}
    assert "db.password" not in observed[0][1]["resolved_config"]
