"""验证依赖系统权限的 canonical 归并、精确接口授权和调用前校验。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.dependency_access import DependencyAccessService
from opentest.domain.dependency_access import DependencyAccessUpdate, DependencyPolicyInput
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import OperationCapability, OperationKind, OperationMutability
from opentest.domain.system_relations import (
    DiscoveredExternalSystem,
    InterfaceRelation,
    ReferencedExternalInterface,
    RelatedSystem,
    SystemRelationCatalog,
)


def _op(operation_id: str, system_id: str, mutability: OperationMutability,
        kind: OperationKind = OperationKind.FACADE) -> OperationCapability:
    """构造最小固定操作，避免测试依赖真实扫描或源码。"""

    return OperationCapability(
        operation_id=operation_id, system_id=system_id, business_name=operation_id,
        kind=kind, mutability=mutability, source_scan_id=f"scan-{system_id}",
        executable=True,
    )


class _Metadata:
    """保存权限工作流的最小内存替身。"""

    def __init__(self):
        """创建独立权限存储，避免测试间串用授权。"""
        self.records = {}

    def get_workflow(self, kind, record_id):
        """按类型及记录键返回副本，模拟存储隔离。"""
        return deepcopy(self.records.get((kind, record_id)))

    def put_workflow(self, kind, record_id, payload, expected_revision=None):
        """保存权限副本；测试通过服务入口验证revision。"""
        self.records[(kind, record_id)] = deepcopy(payload)
        return payload


def _service(catalog: SystemRelationCatalog, operations: list[OperationCapability]):
    """用明确关系和接口构造服务；不读取磁盘源码或业务连接。"""
    store = SimpleNamespace(root=Path("/tmp"), get_system=Mock(return_value=SimpleNamespace(
        system_id="booking", name="SaaS出票核心")))
    artifacts = SimpleNamespace(resolve_scan_id=Mock(return_value="scan-refund"))
    service = DependencyAccessService(store, artifacts, _Metadata())
    service.relations.discovery_catalog = Mock(return_value=catalog)
    service.operations = SimpleNamespace(derive=Mock(return_value=operations))
    return service


def _booking_relation(registered: bool = True) -> SystemRelationCatalog:
    """同一 booking 同时作为上下游，并带一个引用读接口和一条写边。"""

    external = DiscoveredExternalSystem(
        gs_name="dsf.booking", system_id="booking",
        registered_system_id="booking" if registered else None,
        interfaces=[ReferencedExternalInterface(
            operation_id="op.read", interface_name="BookingFacade", method_name="queryOrder",
            service_name="trade", action="queryOrder", version="1.0")],
    )
    edge = InterfaceRelation(
        source_system_id="refund", source_scan_id="scan-refund", source_operation_id="target",
        target_system_id="booking" if registered else "", target_scan_id="scan-booking",
        callee_operation_id="op.write", target_operation_id="op.write",
        relation_type="DSF", relation_kind="CALL", resolution_status="resolved",
    )
    return SystemRelationCatalog(
        system_id="refund",
        upstream=[RelatedSystem(system_id="booking", depth=1)],
        downstream=[RelatedSystem(system_id="booking", depth=1)],
        external_systems=[external], interface_relations=[edge],
    )


def test_same_provider_upstream_downstream_is_one_canonical_card():
    """通道名只作为别名，不能把同一 provider 拆成两份权限。"""

    operations = [
        _op("op.read", "booking", OperationMutability.READ_ONLY),
        _op("op.write", "booking", OperationMutability.WRITE),
    ]
    service = _service(_booking_relation(), operations)
    catalog = service.catalog("refund", "employee-a", "qa")
    service.operations.derive.assert_not_called()
    assert len(catalog.systems) == 1
    system = catalog.systems[0]
    assert system.system_key == "booking"
    assert system.roles == ["upstream", "downstream"]
    assert system.channels == ["dsf.booking"]
    assert system.referenced_count == 2
    detail = service.interfaces("refund", "employee-a", "qa", "booking")
    assert {item.operation_id for item in detail.interfaces} == {"op.read", "op.write"}
    assert detail.policy.read_enabled is False
    assert not any(item.read_allowed for item in detail.interfaces if item.mutability == "READ_ONLY")
    assert not any(item.write_allowed for item in detail.interfaces if item.mutability == "WRITE")


def test_provider_card_only_lists_its_own_facades_with_legacy_grants():
    """混合目录和旧误授权不能使外部同名方法、MQ或数据库进入提供方接口卡片。"""

    operations = [
        _op("op.read", "booking", OperationMutability.READ_ONLY),
        _op("op.write", "booking", OperationMutability.WRITE),
        _op("dsf:third:BookingFacade:queryOrder", "booking", OperationMutability.READ_ONLY, OperationKind.EXTERNAL_DSF),
        _op("mq:booking:consumer", "booking", OperationMutability.WRITE, OperationKind.MQ),
        _op("job:booking:legacy", "booking", OperationMutability.JOB, OperationKind.JOB),
        _op("database:booking:orders", "booking", OperationMutability.WRITE, OperationKind.DATABASE),
        _op("facade:third.BookingFacade#queryOrder", "third", OperationMutability.READ_ONLY),
    ]
    service = _service(_booking_relation(), operations)
    # 模拟修复前已保存的完整目录授权；读取不迁移或删除用户原记录。
    stored = service._load("refund", "employee-a", "qa")
    policy = service._default_policy("booking", "booking")
    policy.read_enabled = True
    policy.allowed_write_operation_ids = [item.operation_id for item in operations]
    policy.db_create = True
    policy.db_tables = ["orders"]
    stored.systems["booking"] = policy
    service.metadata.put_workflow(service.RECORD_KIND, service._record_id("refund", "qa", "employee-a"),
                                  stored.model_dump(mode="json"))

    detail = service.interfaces("refund", "employee-a", "qa", "booking")
    assert {item.operation_id for item in detail.interfaces} == {"op.read", "op.write"}
    assert all(item.referenced and item.authorizable for item in detail.interfaces)
    assert all(item.read_allowed or item.write_allowed for item in detail.interfaces)
    # 数据库权限仍独立有效；接口检查不得复用旧误存的第三方或基础设施ID。
    assert detail.policy.db_create and detail.policy.db_tables == ["orders"]
    assert service.allows_operation("refund", "employee-a", "qa", "booking", "database:booking:orders")
    for operation in operations[2:5] + operations[6:]:
        assert not service.allows_operation("refund", "employee-a", "qa", "booking", operation.operation_id)
    filtered = service.filter_capabilities("refund", "employee-a", "qa", operations)
    assert {item.operation_id for item in filtered} == {"op.read", "op.write", "database:booking:orders"}
    assert service._load("refund", "employee-a", "qa").systems["booking"] == policy


@pytest.mark.parametrize("kind", [OperationKind.EXTERNAL_DSF, OperationKind.MQ, OperationKind.JOB, OperationKind.DATABASE])
@pytest.mark.parametrize("mutability", [OperationMutability.READ_ONLY, OperationMutability.WRITE])
def test_non_facade_operations_cannot_be_saved_as_provider_interface_grants(kind, mutability):
    """旧页面或直接请求提交混合目录ID时，读写授权均被服务端拒绝且原权限不变。"""

    service = _service(_booking_relation(), [_op("other.operation", "booking", mutability, kind)])
    field = "allowed_read_operation_ids" if mutability == OperationMutability.READ_ONLY else "allowed_write_operation_ids"
    # 后端使用与接口展示相同的提供方范围，不依赖前端隐藏错误项目。
    with pytest.raises(KnowledgeValidationError, match="授权项不是该系统"):
        service.update("refund", "employee-a", "qa", "booking", DependencyAccessUpdate(
            expected_revision=0, policy=DependencyPolicyInput(**{field: ["other.operation"]})))
    assert service._load("refund", "employee-a", "qa").revision == 0


def test_legacy_outbound_grant_cannot_replace_actual_provider_facade_permission(monkeypatch):
    """旧调用方卡片中的外部ID不授权第三方，明确提供方Facade授权才允许固定DSF调用。"""

    from opentest.domain.errors import ScopeViolationError
    from opentest.domain.models import OperationExecutionRequest

    monkeypatch.setattr("opentest.application.dependency_access.current_employee",
                        lambda: SimpleNamespace(user_id="employee-a"))
    external = _op("dsf:third:BookingFacade:queryOrder", "booking", OperationMutability.READ_ONLY, OperationKind.EXTERNAL_DSF)
    third_facade = _op("facade:third.BookingFacade#queryOrder", "third", OperationMutability.READ_ONLY)
    catalog = _booking_relation()
    catalog.interface_relations.append(catalog.interface_relations[0].model_copy(update={
        "source_system_id": "booking", "target_system_id": "third",
        "callee_operation_id": external.operation_id, "target_operation_id": third_facade.operation_id}))
    service = _service(catalog, [external, third_facade])
    stored = service._load("refund", "employee-a", "qa")
    wrong_policy = service._default_policy("booking", "booking")
    wrong_policy.allowed_read_operation_ids = [external.operation_id]
    stored.systems["booking"] = wrong_policy
    service.metadata.put_workflow(service.RECORD_KIND, service._record_id("refund", "qa", "employee-a"),
                                  stored.model_dump(mode="json"))
    request = OperationExecutionRequest(operation_id=external.operation_id, arguments={},
                                        request_id="provider-scope-check", environment="qa")
    # 编译和运行均按已确认关系找到third，不能借用booking上的外部ID或只读兜底。
    assert not service.filter_capabilities("refund", "employee-a", "qa", [external])
    with pytest.raises(ScopeViolationError, match="未授权"):
        service.require_request("refund", external, request)
    service.update("refund", "employee-a", "qa", "third", DependencyAccessUpdate(
        expected_revision=0, policy=DependencyPolicyInput(allowed_read_operation_ids=[third_facade.operation_id])))
    assert service.filter_capabilities("refund", "employee-a", "qa", [external]) == [external]
    service.require_request("refund", external, request)


def test_legacy_mq_grant_is_rejected_at_dispatch(monkeypatch):
    """旧页面误存MQ接口授权后，实际调用边界也拒绝该ID，不能只从页面移除。"""

    from opentest.domain.errors import ScopeViolationError
    from opentest.domain.models import OperationExecutionRequest

    monkeypatch.setattr("opentest.application.dependency_access.current_employee",
                        lambda: SimpleNamespace(user_id="employee-a"))
    capability = _op("mq:booking:consumer", "booking", OperationMutability.WRITE, OperationKind.MQ)
    service = _service(_booking_relation(), [capability])
    stored = service._load("refund", "employee-a", "qa")
    policy = service._default_policy("booking", "booking")
    policy.allowed_write_operation_ids = [capability.operation_id]
    stored.systems["booking"] = policy
    service.metadata.put_workflow(service.RECORD_KIND, service._record_id("refund", "qa", "employee-a"),
                                  stored.model_dump(mode="json"))
    # 校验发生于业务派发之前；这里不连接或发送任何MQ消息。
    with pytest.raises(ScopeViolationError, match="未授权"):
        service.require_request("refund", capability, OperationExecutionRequest(
            operation_id=capability.operation_id, arguments={}, request_id="legacy-mq-check", environment="qa"))


def test_write_requires_explicit_grant_and_read_can_be_excluded():
    """写接口默认不可用；保存授权后才放行，只读排除项立即生效。"""

    operations = [
        _op("op.read", "booking", OperationMutability.READ_ONLY),
        _op("op.write", "booking", OperationMutability.WRITE),
    ]
    service = _service(_booking_relation(), operations)
    assert service.allows_source("refund", "employee-a", "qa", "booking")
    assert not service.allows_operation("refund", "employee-a", "qa", "booking", "op.read")
    assert not service.allows_operation("refund", "employee-a", "qa", "booking", "op.write")
    catalog = service.catalog("refund", "employee-a", "qa")
    summary = service.update("refund", "employee-a", "qa", "booking", DependencyAccessUpdate(
        expected_revision=catalog.revision,
        policy=DependencyPolicyInput(read_enabled=True,
            denied_read_operation_ids=["op.read"],
            allowed_write_operation_ids=["op.write"],
            source_scan_allowed=False),
    ))
    assert summary.policy.allowed_write_operation_ids == ["op.write"]
    assert not service.allows_source("refund", "employee-a", "qa", "booking")
    assert not service.allows_operation("refund", "employee-a", "qa", "booking", "op.read")
    assert service.allows_operation("refund", "employee-a", "qa", "booking", "op.write")
    filtered = service.filter_capabilities("refund", "employee-a", "qa", operations, "refund")
    assert {item.operation_id for item in filtered} == {"op.write"}


def test_unresolved_external_system_has_no_grant_switch():
    """无法明确映射的外部引用只能展示，不能保存调用授权。"""

    operations = [_op("op.read", "booking", OperationMutability.READ_ONLY)]
    service = _service(_booking_relation(registered=False), operations)
    catalog = service.catalog("refund", "employee-a", "qa")
    external = next(item for item in catalog.systems if item.system_key.startswith("external:"))
    assert external.unresolved is True
    assert external.interface_count == 1
    detail = service.interfaces("refund", "employee-a", "qa", external.system_key)
    assert all(not item.executable and not item.read_allowed for item in detail.interfaces)
    with pytest.raises(KnowledgeValidationError, match="外部引用"):
        service.update("refund", "employee-a", "qa", external.system_key, DependencyAccessUpdate(
            expected_revision=catalog.revision, policy=DependencyPolicyInput()))


def test_stale_revision_and_unknown_operation_are_rejected():
    """过期保存和错误接口授权不能静默覆盖。"""

    operations = [_op("op.read", "booking", OperationMutability.READ_ONLY)]
    service = _service(_booking_relation(), operations)
    catalog = service.catalog("refund", "employee-a", "qa")
    with pytest.raises(KnowledgeValidationError, match="已变化"):
        service.update("refund", "employee-a", "qa", "booking", DependencyAccessUpdate(
            expected_revision=catalog.revision + 1, policy=DependencyPolicyInput()))
    with pytest.raises(KnowledgeValidationError, match="写授权项"):
        service.update("refund", "employee-a", "qa", "booking", DependencyAccessUpdate(
            expected_revision=catalog.revision,
            policy=DependencyPolicyInput(allowed_write_operation_ids=["op.missing"])))


def test_precise_read_grants_do_not_allow_future_interfaces_or_other_environments():
    """保存一次全量选择后新增接口仍关闭，且员工和环境互不继承授权。"""
    operations = [_op("op.read", "booking", OperationMutability.READ_ONLY)]
    service = _service(_booking_relation(), operations)
    service.update("refund", "employee-a", "qa", "booking", DependencyAccessUpdate(
        expected_revision=0, policy=DependencyPolicyInput(allowed_read_operation_ids=["op.read"])))
    # 目录变更不会扩展已保存的精确授权。
    operations.append(_op("op.new", "booking", OperationMutability.READ_ONLY))
    assert service.allows_operation("refund", "employee-a", "qa", "booking", "op.read")
    assert not service.allows_operation("refund", "employee-a", "qa", "booking", "op.new")
    assert not service.allows_operation("refund", "employee-a", "uat", "booking", "op.read")
    assert not service.allows_operation("refund", "employee-b", "qa", "booking", "op.read")


@pytest.mark.parametrize("statement", [
    "DELETE FROM orders WHERE id = ? LIMIT 1",
    "UPDATE orders SET status = ? WHERE id = ? LIMIT 1",
    "INSERT INTO other_orders (id) VALUES (?)",
    "INSERT INTO orders (id) VALUES (?) ON DUPLICATE KEY UPDATE id = ?",
])
def test_database_create_grant_cannot_authorize_other_actions_or_tables(statement):
    """创建许可不能被目录WRITE标签扩大为修改、删除或其他表。"""
    from opentest.domain.dependency_access import DependencyAccessPolicy
    from opentest.domain.errors import ScopeViolationError
    policy = DependencyAccessPolicy(system_key="booking", db_create=True, db_tables=["orders"])
    with pytest.raises(ScopeViolationError):
        DependencyAccessService._require_database_request(policy, {"statement": statement})


@pytest.mark.parametrize("permission,statement", [
    ("db_read", "SELECT id FROM orders WHERE id = ?"),
    ("db_create", "INSERT INTO orders (id, status) VALUES (?, ?)"),
    ("db_update", "UPDATE orders SET status = ? WHERE id = ? LIMIT 1"),
    ("db_delete", "DELETE FROM orders WHERE id = ? LIMIT 1"),
])
def test_database_actions_use_their_own_grant(permission, statement):
    """合法单表有界请求只需自己的动作权限，不联动其他动作。"""
    from opentest.domain.dependency_access import DependencyAccessPolicy
    policy = DependencyAccessPolicy(system_key="booking", db_tables=["orders"], **{permission: True})
    DependencyAccessService._require_database_request(policy, {"statement": statement})


@pytest.mark.parametrize("statement", [
    "DELETE FROM orders LIMIT 1", "DELETE FROM orders WHERE id = ?",
    "DELETE FROM orders WHERE id = ? LIMIT 101", "DELETE FROM orders WHERE id = ? LIMIT 0",
    "DELETE FROM orders WHERE id = ? LIMIT 1; DELETE FROM orders",
])
def test_database_writes_require_bounded_conditions(statement):
    """有删除权限也不能执行无条件、无限量或多语句删除。"""
    from opentest.domain.dependency_access import DependencyAccessPolicy
    from opentest.domain.errors import ScopeViolationError
    policy = DependencyAccessPolicy(system_key="booking", db_delete=True, db_tables=["orders"])
    with pytest.raises(ScopeViolationError):
        DependencyAccessService._require_database_request(policy, {"statement": statement})


def test_external_operation_stored_in_consumer_cannot_bypass_provider_grant(monkeypatch):
    """外部接口目录归属调用方，仍按精确提供方检查；撤销后实际调用被阻止。"""
    from opentest.domain.errors import ScopeViolationError
    from opentest.domain.models import OperationExecutionRequest
    monkeypatch.setattr("opentest.application.dependency_access.current_employee",
                        lambda: SimpleNamespace(user_id="employee-a"))
    capability = _op("op.write", "refund", OperationMutability.WRITE, OperationKind.EXTERNAL_DSF)
    local = _op("local.target", "refund", OperationMutability.WRITE)
    service = _service(_booking_relation(), [_op("op.write", "booking", OperationMutability.WRITE)])
    request = OperationExecutionRequest(operation_id="op.write", arguments={}, request_id="permission-check", environment="qa")
    assert service.filter_capabilities("refund", "employee-a", "qa", [capability, local]) == [local]
    with pytest.raises(ScopeViolationError, match="未授权"):
        service.require_request("refund", capability, request)
    # 同一个固定操作经历允许、撤销，权限不能冻结在旧Case中。
    for revision, writes in [(0, ["op.write"]), (1, [])]:
        service.update("refund", "employee-a", "qa", "booking", DependencyAccessUpdate(
            expected_revision=revision, policy=DependencyPolicyInput(allowed_write_operation_ids=writes)))
        if writes:
            service.require_request("refund", capability, request)
    with pytest.raises(ScopeViolationError, match="未授权"):
        service.require_request("refund", capability, request)


def test_reference_ids_are_deduplicated_using_exact_mapping():
    """同一引用的调用方ID和提供方ID计为一个，不通过名称前缀推断。"""
    catalog = _booking_relation()
    catalog.external_systems[0].interfaces[0].operation_id = "dsf:caller.read"
    catalog.interface_relations.append(catalog.interface_relations[0].model_copy(update={
        "callee_operation_id": "dsf:caller.read", "target_operation_id": "op.read"}))
    service = _service(catalog, [_op("op.read", "booking", OperationMutability.READ_ONLY),
                                  _op("op.write", "booking", OperationMutability.WRITE)])
    summary = service.catalog("refund", "employee-a", "qa").systems[0]
    assert summary.referenced_count == 2
    detail = service.interfaces("refund", "employee-a", "qa", "booking")
    assert len(detail.interfaces) == 2
    assert all(item.referenced for item in detail.interfaces)


def test_existing_task_cannot_read_source_after_permission_is_revoked(monkeypatch):
    """已存在的来源scope不能绕过源码撤权，拒绝时不得建立读取器。"""
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.domain.errors import ScopeViolationError
    service = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    service.handoffs = SimpleNamespace(get=Mock(return_value=SimpleNamespace(
        system_id="refund", owner_user_id="employee-a", environment_id="qa",
        source_scopes=[SimpleNamespace(source_system_id="booking")])) )
    service._require_current_source_scopes = Mock()
    service.dependency_access = SimpleNamespace(allows_source=Mock(return_value=False))
    reader = Mock()
    monkeypatch.setattr("opentest.application.case_template_v4.RegisteredSourceReader", reader)
    with pytest.raises(ScopeViolationError, match="未授权扫描源码"):
        service.call_source_tool("task-a", "booking", "read_source", {"relative_path": "Facade.java"})
    reader.assert_not_called()
    service.dependency_access.allows_source.assert_called_once_with("refund", "employee-a", "qa", "booking")


def test_explicit_grant_survives_contract_mutability_refinement():
    """扫描UNKNOWN接口已开启后，契约补为READ_ONLY仍是同一接口授权。"""
    from opentest.domain.dependency_access import DependencyAccessPolicy
    policy = DependencyAccessPolicy(system_key="booking", allowed_write_operation_ids=["op.read"])
    assert DependencyAccessService._allows_capability(policy, _op("op.read", "booking", OperationMutability.READ_ONLY))
    policy = DependencyAccessPolicy(system_key="booking", allowed_read_operation_ids=["op.read"])
    assert DependencyAccessService._allows_capability(policy, _op("op.read", "booking", OperationMutability.UNKNOWN))


def test_legacy_case_without_owner_uses_authenticated_employee(monkeypatch):
    """旧任务owner为空时沿用已认证身份，不能创建匿名权限或阻塞本系统目标。"""
    monkeypatch.setattr("opentest.application.dependency_access.current_employee",
                        lambda: SimpleNamespace(user_id="employee-a"))
    service = _service(_booking_relation(), [])
    target = _op("target", "refund", OperationMutability.WRITE)
    assert service.filter_capabilities("refund", None, "qa", [target]) == [target]
    assert service._load("refund", None, "qa").owner_user_id == "employee-a"


def test_execution_permissions_use_current_employee_and_environment(monkeypatch):
    """同一固定能力可由员工B在UAT执行，不继承原作者A的QA授权。"""
    from opentest.domain.models import OperationExecutionRequest
    from opentest.domain.errors import ScopeViolationError
    monkeypatch.setattr("opentest.application.dependency_access.current_employee",
                        lambda: SimpleNamespace(user_id="employee-b"))
    operation = _op("op.write", "booking", OperationMutability.WRITE)
    service = _service(_booking_relation(), [operation])
    service.update("refund", "employee-b", "uat", "booking", DependencyAccessUpdate(
        expected_revision=0, policy=DependencyPolicyInput(allowed_write_operation_ids=["op.write"])))
    request = OperationExecutionRequest(operation_id="op.write", request_id="current-execution", arguments={}, environment="uat")
    service.require_request("refund", operation, request)
    with pytest.raises(ScopeViolationError, match="未授权"):
        service.require_request("refund", operation, request.model_copy(update={"environment": "qa"}))


@pytest.mark.parametrize("statement", [
    "UPDATE orders SET note = 'WHERE', status = ? LIMIT 1",
    "UPDATE orders SET `WHERE` = ? LIMIT 1",
])
def test_where_inside_literal_or_identifier_is_not_a_condition(statement):
    """有修改权限也不接受把字符串/列名WHERE冒充SQL条件的语句。"""
    from opentest.domain.dependency_access import DependencyAccessPolicy
    from opentest.domain.errors import ScopeViolationError
    policy = DependencyAccessPolicy(system_key="booking", db_update=True, db_tables=["orders"])
    with pytest.raises(ScopeViolationError):
        DependencyAccessService._require_database_request(policy, {"statement": statement})


def test_data_task_source_tool_checks_its_creation_environment(monkeypatch):
    """独立数据任务读取固定来源前也按创建环境检查源码撤权，不打开读取器。"""
    from opentest.application.data_capabilities import DataCapabilityService
    from opentest.domain.data_capabilities import DataCapabilityHandoff
    from opentest.domain.errors import ScopeViolationError
    monkeypatch.setattr("opentest.application.data_capabilities.current_employee",
                        lambda: SimpleNamespace(user_id="employee-b"))
    service = DataCapabilityService.__new__(DataCapabilityService)
    policy = SimpleNamespace(allows_source=Mock(return_value=False))
    service.cases = SimpleNamespace(dependency_access=policy)
    handoff = DataCapabilityHandoff(task_id="task-a", system_id="refund", environment_id="uat",
                                    kind="data_capability", goal="test", source_scopes=[])
    with pytest.raises(ScopeViolationError, match="未授权扫描源码"):
        service._source_tool(handoff, "read_source", {"source_system_id": "booking", "relative_path": "Facade.java"})
    policy.allows_source.assert_called_once_with("refund", "employee-b", "uat", "booking")


def test_data_registry_uses_fixed_capabilities_without_case_only_fields():
    """数据任务没有Case owner，目录仍可建立；实际授权留给带环境的调用入口。"""
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.domain.data_capabilities import DataCapabilityHandoff
    service = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    service.runtime = SimpleNamespace(operation_catalog=Mock())
    service.dependency_access = SimpleNamespace(filter_capabilities=Mock(side_effect=AssertionError("不应读取Case字段")))
    handoff = DataCapabilityHandoff(task_id="task-a", system_id="refund", kind="data_capability", goal="test", source_scopes=[])
    assert service._runtime_capabilities(handoff, enforce_permissions=False) == []
