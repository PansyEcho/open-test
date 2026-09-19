"""验证固定Operation的项目接入、逻辑环境及历史关系兼容边界。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from opentest.adapters.dsf_proxy_worker import DsfProxyWorkerLauncher
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_execution_store import OperationExecutionStore
from opentest.adapters.qa_active_worker import QaActiveWorkerLauncher
from opentest.application.dsf_operations import DsfOperationService
from opentest.application.case_template_v4 import CaseTemplateV4Service
from opentest.application.operations import OperationExecutionService
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    DiscoveredResource,
    DsfClientProfile,
    DsfExecutionRequest,
    DsfOperationDefinition,
    DsfOperationMutability,
    OperationCapability,
    OperationExecutionRequest,
    OperationExecutionStatus,
    OperationKind,
    OperationMutability,
    ResourceKind,
    ResourceRole,
    SourceReference,
    SourceBaseline,
    SystemDefinition,
    SystemDependencyBindingSubmission,
    SystemDependencyPurpose,
    SystemDependencyRole,
)


@pytest.fixture
def execution_scope(tmp_path: Path) -> SimpleNamespace:
    """建立真实绑定/运行存储及不访问网络的provider边界。

    Args:
        tmp_path: pytest隔离目录。
    Returns:
        含服务、绑定存储、固定操作和请求的测试范围。
    """

    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.initialize()
    # 两个系统均须真实注册；这里只替换远端派发，授权与持久化仍运行产品实现。
    for system_id in ("consumer", "provider"):
        source = tmp_path / system_id
        source.mkdir()
        store.register_system(SystemDefinition(system_id=system_id, name=system_id, source_path=str(source)))
    provider = Mock()
    provider.execute_facade.return_value = {"reportId": 17}
    catalog = SimpleNamespace(store=store, derive=Mock())
    service = OperationExecutionService(
        catalog, Mock(), OperationExecutionStore(tmp_path / "runs"), Mock(), provider
    )
    capability = OperationCapability(
        operation_id="facade:example.ReportFacade#saveReport", system_id="provider",
        business_name="保存补单报表", kind=OperationKind.FACADE,
        mutability=OperationMutability.WRITE, executable=True, source_scan_id="scan-baseline-a",
        input_schema={"type": "object", "properties": {"ownerId": {"type": "string"}},
                      "required": ["ownerId"], "additionalProperties": False},
    )
    request = OperationExecutionRequest(
        operation_id=capability.operation_id, arguments={"ownerId": "owner-1"},
        request_id="cross-system-request-1", environment="qa",
    )
    return SimpleNamespace(store=store, service=service, provider=provider,
                           capability=capability, request=request, catalog=catalog)


def _authorize(scope: SimpleNamespace) -> None:
    """保存当前测试所需的精确SETUP授权及qa到test对应。

    Args:
        scope: 已注册consumer/provider的测试范围。
    Returns:
        None；测试绑定写入后返回。
    Side Effects:
        写入测试目录中的current直接系统绑定。
    """

    # 允许的只有当前固定操作；之后增加的其它操作不会自动进入权限范围。
    scope.store.put_system_dependency_binding("consumer", SystemDependencyBindingSubmission(
        provider_system_id="provider", role=SystemDependencyRole.UPSTREAM,
        purposes=[SystemDependencyPurpose.SETUP], allowed_operations=[scope.capability.operation_id],
        environment_mappings={"qa": "test"},
    ))


def test_fixed_operation_uses_logical_environment_without_latest(execution_scope: SimpleNamespace) -> None:
    """固定范围的跨项目操作使用同名逻辑环境，不要求关系映射或重新读取latest。

    Args:
        execution_scope: 已注册两项目与远端替身。
    Returns:
        None；操作归属、逻辑环境及固定scan均保持原样时通过。
    """

    execution_scope.service.get = Mock(side_effect=AssertionError("latest forbidden"))
    record = execution_scope.service.execute_resolved("consumer", execution_scope.capability, execution_scope.request)
    assert record.status == OperationExecutionStatus.COMPLETED
    assert record.system_id == "provider" and record.environment == "qa"
    assert record.source_scan_id == "scan-baseline-a"
    capability, request = execution_scope.provider.execute_facade.call_args.args
    assert capability.source_scan_id == "scan-baseline-a" and request.environment == "qa"
    execution_scope.catalog.derive.assert_not_called()


@pytest.mark.parametrize("mutability", [OperationMutability.READ_ONLY, OperationMutability.WRITE])
def test_registered_fixed_scope_needs_no_relationship_acl(
    execution_scope: SimpleNamespace, mutability: OperationMutability,
) -> None:
    """明确执行固定范围内操作无需逐关系读写白名单，仍由任务决定是否触发。

    Args:
        execution_scope: 服务端固定范围及模拟远端。
        mutability: 已知的读写性质。
    Returns:
        None；无任何人工关系仍可明确执行时通过。
    """

    capability = execution_scope.capability.model_copy(update={"mutability": mutability})
    record = execution_scope.service.execute_resolved("consumer", capability, execution_scope.request)
    assert record.status == OperationExecutionStatus.COMPLETED
    execution_scope.provider.execute_facade.assert_called_once()


def test_legacy_binding_changes_do_not_reinterpret_fixed_plan(execution_scope: SimpleNamespace) -> None:
    """旧关系用途和映射变化不能使固定计划换环境或破坏幂等结果。

    Args:
        execution_scope: 真实历史绑定存储及固定计划。
    Returns:
        None；不使用旧映射且撤销后返回同一记录时通过。
    """

    _authorize(execution_scope)
    first = execution_scope.service.execute_resolved(
        "consumer", execution_scope.capability, execution_scope.request, SystemDependencyPurpose.ACTION)
    execution_scope.store.delete_system_dependency_binding("consumer", "provider")
    replay = execution_scope.service.execute_resolved(
        "consumer", execution_scope.capability, execution_scope.request, SystemDependencyPurpose.SETUP)
    assert first.environment == "qa" and replay.execution_id == first.execution_id
    assert execution_scope.provider.execute_facade.call_count == 1


def test_changed_baseline_cannot_reuse_request_identity(execution_scope: SimpleNamespace) -> None:
    """操作名字相同不代表源码契约相同，幂等键不能把A记录用作B结果。

    Args:
        execution_scope: 固定操作与持久运行存储。
    Returns:
        None；契约变化被拒绝且不重复派发时通过。
    """

    execution_scope.service.execute_resolved("consumer", execution_scope.capability, execution_scope.request)
    with pytest.raises(ScopeViolationError, match="request"):
        execution_scope.service.execute_resolved("consumer",
            execution_scope.capability.model_copy(update={"source_scan_id": "scan-baseline-b"}), execution_scope.request)
    assert execution_scope.provider.execute_facade.call_count == 1


def test_test_selector_cannot_be_guessed_as_qa(execution_scope: SimpleNamespace) -> None:
    """旧test请求不能隐式解释为qa，模型及执行边界都要求明确逻辑环境。

    Args:
        execution_scope: 真实执行边界。
    Returns:
        None；所有变体都在业务调用前被拒绝时通过。
    """

    with pytest.raises(ValidationError):
        OperationExecutionRequest(operation_id=execution_scope.capability.operation_id,
                                  request_id="old-test-request", environment="test")
    with pytest.raises(KnowledgeValidationError, match="qa或uat"):
        execution_scope.service.execute_resolved("consumer", execution_scope.capability,
                                                execution_scope.request.model_copy(update={"environment": "test"}))
    execution_scope.provider.execute_facade.assert_not_called()


def test_fixed_runtime_scope_does_not_read_current_relations(execution_scope: SimpleNamespace) -> None:
    """旧G1按冻结来源派生操作，关系重扫不修改其数据方法的实际归属。

    Args:
        execution_scope: 真实项目注册和固定Operation。
    Returns:
        None；无人工关系且不读取latest仍可派生固定目录时通过。
    """

    operation_catalog = Mock()
    operation_catalog.derive.return_value = [execution_scope.capability]
    service = SimpleNamespace(store=execution_scope.store, runtime=SimpleNamespace(operation_catalog=operation_catalog))
    handoff = SimpleNamespace(system_id="consumer", source_scopes=[
        SimpleNamespace(source_system_id="provider", source_scan_id="scan-baseline-a", resolved_operations=[])])
    assert CaseTemplateV4Service._runtime_capabilities(service, handoff) == [execution_scope.capability]
    operation_catalog.derive.assert_called_once_with("provider", "scan-baseline-a", include_registered=False, resolved_operations=[])


def test_external_dsf_uses_proven_caller_contract_without_provider_registration(execution_scope: SimpleNamespace) -> None:
    """未注册下游可使用调用方已证明的固定契约；实际执行仍保留远端身份。"""

    operation = DsfOperationDefinition(operation_id="dsf:absent:report:query", provider_system_id="absent",
        gs_name="dsf.absent", service_name="report", version="1", action="query",
        mutability=DsfOperationMutability.READ_ONLY, request_schema={"type": "object"}, response_schema={"type": "object"},
        source_refs=[SourceReference(path="reference.xml", symbol="query", line=1)])
    execution_scope.catalog.artifacts = SimpleNamespace(read=Mock(return_value=SimpleNamespace(dsf_operations=[operation])))
    capability = execution_scope.capability.model_copy(update={"kind": OperationKind.EXTERNAL_DSF,
        "system_id": "consumer", "operation_id": operation.operation_id,
        "provider_operation_id": operation.operation_id, "provider_definition": operation})
    request = execution_scope.request.model_copy(update={"operation_id": operation.operation_id})
    execution_scope.provider.execute_external_dsf.return_value = {"success": True}
    execution = execution_scope.service.execute_resolved("consumer", capability, request)
    assert execution.status == OperationExecutionStatus.COMPLETED
    execution_scope.provider.execute_external_dsf.assert_called_once()
