"""验证异步QA执行身份、真实DATA写步骤与只读断言边界。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.case_template_v4_store import CaseGenerationExecutionStoreV4
from opentest.application.case_template_v4 import CaseTemplateV4Service, CaseTemplateV4RuntimeServices
from opentest.application.case_template_registries import CaseTemplateRegistryLoader
from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4, _ExecutionScope
from opentest.domain.case_template_v4 import (
    CaseGenerationExecutionRequestV4, CaseVariantExecutionV4, RuntimeFunctionRegistry,
    CaseOracleAssertion, DslValueSource,
)
from opentest.domain.models import OperationCapability, OperationKind, OperationMutability
from opentest.domain.errors import CaseExecutionConflictError
from test_case_template_v4 import _create_order_generation, SYSTEM_ID


def _execution_service(tmp_path, pool):
    """组合真实Execution存储和指定线程池，固定不涉及QA的已发布Generation。

    Args:
        tmp_path: 报告隔离根。
        pool: 已存在的测试线程池，模拟应用共享池。
    Returns:
        服务和不可变Generation；只有远端执行边界由测试控制。
    """
    generation = _create_order_generation()
    generations = Mock()
    generations.get.return_value = generation
    handoffs = Mock()
    handoffs.get.return_value = SimpleNamespace(system_id=SYSTEM_ID, generation_id=generation.generation_id)
    executions = CaseGenerationExecutionStoreV4(tmp_path)
    runtime = CaseTemplateV4RuntimeServices(Mock(), Mock(), lambda _: {},
                                          task_manager=SimpleNamespace(_executor=pool), execution_store=executions)
    service = CaseTemplateV4Service(Mock(), Mock(), generations, handoffs, runtime)
    service._runtime_registry_for_execution = Mock(return_value=RuntimeFunctionRegistry(functions=[]))
    service.executor = Mock()
    return service, generation


def test_background_execution_returns_identity_and_blocks_duplicate_while_running(tmp_path):
    """远端调用仍在执行时立即返回可读身份，同Generation并发点击不能重放写请求。

    Args:
        tmp_path: Execution存储目录。
    Returns:
        None；真实线程同步、持久状态与并发门禁成立时通过。
    """
    entered, release = Event(), Event()
    pool = ThreadPoolExecutor(max_workers=1)
    service, generation = _execution_service(tmp_path, pool)

    def execute(execution_id, published, registry, environment_id):
        """暂停远端边界直至测试释放，返回同一个已发布Variant的结果。"""
        assert environment_id == "qa"
        entered.set()
        assert release.wait(5)
        return [CaseVariantExecutionV4(variant_id=published.variants[0].variant_id, status="COMPLETED")]

    service.executor.execute.side_effect = execute
    try:
        running = service.execute_generation(SYSTEM_ID, generation.generation_id,
                                             CaseGenerationExecutionRequestV4(), background=True)
        assert entered.wait(2)
        assert running.status == "RUNNING"
        assert service.get_execution(SYSTEM_ID, running.execution_id).status == "RUNNING"
        # 第二次显式执行被已有RUNNING报告阻止，不会向线程池提交第二个写操作。
        with pytest.raises(CaseExecutionConflictError):
            service.execute_generation(SYSTEM_ID, generation.generation_id,
                                       CaseGenerationExecutionRequestV4(), background=True)
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert service.get_execution(SYSTEM_ID, running.execution_id).status == "PASSED"
    assert service.executor.execute.call_count == 1


def test_closed_executor_records_failure_without_stuck_running_state(tmp_path):
    """服务关闭竞态导致无法提交时明确保存未执行失败，不永久锁死Generation。

    Args:
        tmp_path: Execution存储目录。
    Returns:
        None；失败报告可读且没有QA副作用时通过。
    """
    pool = ThreadPoolExecutor(max_workers=1)
    service, generation = _execution_service(tmp_path, pool)
    pool.shutdown(wait=True)
    failed = service.execute_generation(SYSTEM_ID, generation.generation_id,
                                        CaseGenerationExecutionRequestV4(), background=True)
    assert failed.status == "FAILED"
    assert "尚未开始" in service.get_execution(SYSTEM_ID, failed.execution_id).safe_error
    service.executor.execute.assert_not_called()


def test_data_writes_are_available_but_not_read_only_oracles():
    """写Facade及DB DATA能力可用于准备，ORACLE仍只接收只读描述。

    Returns:
        None；真实能力投影保持写入与观察边界时通过。
    """
    capabilities = [OperationCapability(
        operation_id="facade:sample.OrderFacade#create", system_id=SYSTEM_ID, business_name="准备订单",
        kind=OperationKind.FACADE, mutability=OperationMutability.WRITE, executable=True,
        source_scan_id="scan-qa", input_schema={},
    ), OperationCapability(
        operation_id="database:sample-orders", system_id=SYSTEM_ID, business_name="订单数据库",
        kind=OperationKind.DATABASE, mutability=OperationMutability.WRITE, executable=True,
        source_scan_id="scan-qa", input_schema={},
    )]
    registry = CaseTemplateRegistryLoader().runtime_registry(SYSTEM_ID, {SYSTEM_ID}, capabilities)
    # 同一DB Provider拥有独立的写准备描述与只读SELECT观察描述。
    writes = [item for item in registry.functions if not item.read_only]
    assert len(writes) == 2
    assert all(item.allowed_phases == ["DATA"] for item in writes)
    oracle = next(item for item in registry.functions if item.function_id == "database:sample-orders")
    assert oracle.read_only and oracle.allowed_phases == ["ORACLE"]


def test_assertion_evidence_preserves_business_values_and_redacts_scalar_credentials():
    """断言展示真实业务比较值，同时不泄漏从凭据路径提取的标量。

    Returns:
        None；比较按真实值执行、报告按字段上下文脱敏时通过。
    """
    executor = CaseTemplateExecutorV4(Mock())
    assertions = [CaseOracleAssertion(actual_path=path, operator="eq",
                    expected=DslValueSource(kind="literal", value=expected))
                  for path, expected in [("state", "REFUND_CANCEL"), ("auth.token", "secret-test-value")]]
    oracle = SimpleNamespace(oracle_id="qa-evidence", assertions=assertions)
    scope = _ExecutionScope(parameters={}, runtime_context={}, environment={"env": "qa"})
    results = executor._assertions(oracle, {"state": "REFUND_CANCEL", "auth": {"token": "secret-test-value"}}, scope)
    assert all(item.passed for item in results)
    assert results[0].actual_value == "REFUND_CANCEL"
    assert results[1].actual_value == results[1].expected_value == "<redacted>"
    assert "secret-test-value" not in results[1].model_dump_json()
