"""验证共享数据的查询、授权写准备、关联回查及固定Case执行语义。"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

from opentest.adapters.data_capability_store import DataCapabilityStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_execution_store import OperationExecutionStore
from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4
from opentest.application.log_context import current_log_context
from opentest.application.operations import OperationExecutionService
from opentest.domain.case_template_v4 import (
    CaseTemplateGenerationV4, DataFunctionDraft, DslValueSource, RuntimeFunctionDescriptor,
    RuntimeFunctionRegistry,
)
from opentest.domain.data_capabilities import DataExecution
from opentest.domain.models import (
    OperationCapability, OperationKind, OperationMutability, SystemDefinition,
    SystemDependencyBindingSubmission, SystemDependencyPurpose, SystemDependencyRole,
)

REPORT_QUERY = "facade:ReportFacade#queryReportByUniqueKey"
REPORT_SAVE = "facade:ReportFacade#saveReport"
REPORT_ADJUST = "facade:ReportFacade#updateReportState"
BOOKING_QUERY = "facade:TradeFacade#queryOrder"
TARGET = "facade:RefundFacade#billSupplement"
OBSERVER = "facade:RefundFacade#queryDetailByRefundNo"


class _Provider:
    """只替换QA网络边界，Operation授权、幂等和运行存储使用真实实现。"""

    def __init__(self):
        """建立测试系统返回的关联订单/报表，记录实际派发供断言。

        Side Effects:
            只创建内存业务状态，不访问生产或测试服务。
        """

        self.order = {"id": "ORDER-REAL-1", "owner": "BUYER-1", "ticket": "TICKET-REAL-1"}
        self.report = self._matching_report()
        self.calls = []
        self.save_persists = True
        self.fail_operation = ""
        self.response_success = True

    def _matching_report(self) -> dict:
        """从Provider现有订单构造关联测试响应，不让DSL自行生成身份。

        Returns:
            带ARC文本和当前主体/原单关系的报表。
        """

        return {"id": 171, "owner": self.order["owner"], "orderId": self.order["id"], "state": "READY",
                "ext": json.dumps({"arcRefundAccount": {"ticket": self.order["ticket"]}})}

    def execute_facade(self, capability: OperationCapability, request: object) -> dict:
        """处理单次固定Operation，并保留真实目标环境、扫描与参数。

        Args:
            capability: 固定扫描的已解析能力。
            request: 通过实时权限及环境映射的请求。
        Returns:
            DSF业务响应；指定失败边界时抛出依赖异常。
        """

        self.calls.append((capability, request))
        if capability.operation_id == self.fail_operation:
            raise RuntimeError("QA provider unavailable")
        # 查询返回副本，后续写入不会追溯改变第一次查询已持久化的事实。
        if capability.operation_id == REPORT_QUERY:
            business = {"report": deepcopy(self.report)}
        elif capability.operation_id == BOOKING_QUERY:
            business = {"order": deepcopy(self.order)}
        elif capability.operation_id == REPORT_SAVE:
            if self.save_persists:
                self.report = self._matching_report()
            business = {"success": True}
        elif capability.operation_id == REPORT_ADJUST:
            self.report["state"] = "READY"
            business = {"success": True}
        elif capability.operation_id == TARGET:
            business = {"success": self.response_success, "refundSerialNo": "REFUND-REAL-1"}
        elif capability.operation_id == OBSERVER:
            business = {"reportId": self.report["id"], "orderId": self.order["id"]}
        else:
            raise AssertionError("unexpected provider operation")
        return {"status": "success", "output": business}


def _function() -> DataFunctionDraft:
    """定义同一查询/创建/验证方法，模拟Agent已从源码补充的有限DSL。

    Returns:
        输出报表ID、ARC数据与订单号；主体条件从调用者输入，事实只从QA响应取得。
    """

    owner = {"kind": "function_input", "name": "owner"}
    query = {"kind": "step_output", "step_id": "report_query"}
    booking = {"kind": "step_output", "step_id": "booking_query"}
    # 先验证主体及跨系统关系，再验证可调整状态；返回成功不替代后续查询。
    return DataFunctionDraft.model_validate({
        "name": "refund_report", "description": "取得指定主体的真实ARC报表与出票原单",
        "inputs": [{"name": "owner", "schema": {"type": "string"}}],
        "steps": [
            {"step_id": "report_query", "operation": "runtime_call", "function_id": REPORT_QUERY,
             "arguments": {"owner": owner}},
            {"step_id": "booking_query", "operation": "runtime_call", "function_id": BOOKING_QUERY,
             "arguments": {"owner": owner}},
        ],
        "match_source": {**query, "path": "report"},
        "create_steps": [{"step_id": "report_create", "operation": "runtime_call", "function_id": REPORT_SAVE,
                          "arguments": {"owner": {**booking, "path": "order.owner"}}}],
        "adjust_steps": [{"step_id": "report_adjust", "operation": "runtime_call", "function_id": REPORT_ADJUST,
                          "arguments": {"id": {**query, "path": "report.id"}}}],
        "verify_steps": [
            {"step_id": "arc_decode", "operation": "json_decode", "input_source": {**query, "path": "report.ext"},
             "output_schema": {"type": "object", "required": ["arcRefundAccount"], "properties": {
                 "arcRefundAccount": {"type": "object", "required": ["ticket"],
                                      "properties": {"ticket": {"type": "string"}}}}}},
            {"step_id": "identity_check", "operation": "assert", "check_kind": "identity", "predicates": [
                {"left": {**query, "path": "report.owner"}, "operator": "eq", "right": owner},
                {"left": {**booking, "path": "order.owner"}, "operator": "eq", "right": owner},
                {"left": {**query, "path": "report.orderId"}, "operator": "eq", "right": {**booking, "path": "order.id"}},
                {"left": {"kind": "step_output", "step_id": "arc_decode", "path": "arcRefundAccount.ticket"},
                 "operator": "eq", "right": {**booking, "path": "order.ticket"}},
            ]},
            {"step_id": "state_check", "operation": "assert", "check_kind": "state", "predicates": [
                {"left": {**query, "path": "report.state"}, "operator": "eq", "right": {"kind": "literal", "value": "READY"}},
            ]},
        ],
        "outputs": [{"output_name": "report_id", "step_id": "report_query", "path": "report.id"},
                    {"output_name": "arc_bill", "step_id": "arc_decode", "path": "arcRefundAccount"},
                    {"output_name": "order_id", "step_id": "booking_query", "path": "order.id"}],
        "evidence": [{"source_system_id": "supplement", "path": "ReportFacade.java", "symbol": "ReportFacade#query", "line": 1}],
        "shared_source": {"owner_system_id": "refund", "capability_id": "refund_report", "version": 1},
    })


@pytest.fixture
def workflow(tmp_path: Path) -> SimpleNamespace:
    """组装真实跨系统授权与持久层，仅QA访问用内存Provider替换。

    Args:
        tmp_path: pytest隔离文件目录。
    Returns:
        可独立或被Case调用的同一共享数据执行器。
    """

    knowledge = GitKnowledgeStore(tmp_path / "knowledge")
    knowledge.initialize()
    for identity in ("refund", "supplement", "booking"):
        source = tmp_path / identity
        source.mkdir()
        knowledge.register_system(SystemDefinition(system_id=identity, name=identity, source_path=str(source)))
    capabilities = []
    descriptors = []
    # 每个实际操作同时带有固定scan和系统归属，后续派发不得重选当前目录。
    for operation_id, system_id, writable in (
        (REPORT_QUERY, "supplement", False), (REPORT_SAVE, "supplement", True),
        (REPORT_ADJUST, "supplement", True), (BOOKING_QUERY, "booking", False),
        (TARGET, "refund", True), (OBSERVER, "refund", False),
    ):
        schema = {"type": "object", "additionalProperties": True}
        capability = OperationCapability(
            operation_id=operation_id, system_id=system_id, business_name=operation_id,
            kind=OperationKind.FACADE, mutability=OperationMutability.WRITE if writable else OperationMutability.READ_ONLY,
            source_scan_id="scan-baseline-a", executable=True, input_schema=schema,
        )
        capabilities.append(capability)
        descriptors.append(RuntimeFunctionDescriptor(
            function_id=operation_id, kind="dsf", description=operation_id, input_schema=schema,
            output_schema={}, read_only=not writable, allowed_phases=["DATA", "ORACLE"] if not writable else ["DATA"],
            source_system_id=system_id, provider_ref=operation_id,
        ))
    provider = _Provider()
    catalog = SimpleNamespace(store=knowledge, derive=Mock(side_effect=AssertionError("latest forbidden")))
    operations = OperationExecutionService(catalog, Mock(), OperationExecutionStore(tmp_path / "operations"), Mock(), provider)
    operations.get = Mock(side_effect=AssertionError("latest forbidden"))
    data_store = DataCapabilityStore(knowledge)
    executor = CaseTemplateExecutorV4(operations, consumer_system_id="refund", capabilities=capabilities, data_store=data_store)
    return SimpleNamespace(executor=executor, provider=provider, data_store=data_store, knowledge=knowledge,
                           operations=operations, capabilities=capabilities,
                           registry=RuntimeFunctionRegistry(functions=descriptors), function=_function())


def _execution(allow_writes: bool = False) -> DataExecution:
    """建立独立数据任务，调用条件尚未被当作已验证事实。

    Args:
        allow_writes: 该次任务是否授权定义中的有限写操作。
    Returns:
        全新的运行身份，定义版本固定为1。
    """

    return DataExecution(execution_id=f"data-execution-{uuid.uuid4().hex[:20]}", system_id="refund",
                         owner_system_id="refund", capability_id="refund_report", capability_version=1,
                         environment_id="qa", inputs={"owner": "BUYER-1"}, allow_writes=allow_writes)


def _generation(function: DataFunctionDraft) -> CaseTemplateGenerationV4:
    """冻结A的数据定义和预期为G1，目标只在显式execute后执行。

    Args:
        function: G1选择的完整共享版本。
    Returns:
        不含内部知识长文或清理配置的可运行Case计划。
    """

    call = {"call_id": "prepare", "function_name": function.name,
            "arguments": {"owner": {"kind": "literal", "value": "BUYER-1"}}}
    oracles = [{"oracle_id": "response.success", "channel": "response", "assertions": [
        {"actual_path": "success", "operator": "eq", "expected": {"kind": "literal", "value": True}}]},
        {"oracle_id": "order.relationship", "channel": "operation", "function_id": OBSERVER,
         "arguments": {"refundSerialNo": {"kind": "target_response", "path": "refundSerialNo"}},
         "assertions": [{"actual_path": "reportId", "operator": "eq", "expected": {
             "kind": "data_output", "call_id": "prepare", "output_name": "report_id"}}]}]
    # 预期固定为规则“观察到的报表ID等于本次准备报表ID”，不会写死业务身份。
    return CaseTemplateGenerationV4.model_validate({
        "generation_id": "case-template-generation-" + "a" * 20, "system_id": "refund", "operation_id": TARGET,
        "source_scan_id": "scan-baseline-a", "coverage_id": "coverage:refund", "runtime_registry_version": "runtime-functions/v1",
        "value_registry_version": "value-functions/v1", "status": "READY",
        "input_contract": {"contract_version": "operation-contract/v2", "target_id": TARGET,
                           "source_scan_id": "scan-baseline-a", "status": "READY", "request_schema": {"type": "object"}},
        "submission": {"data_functions": [function.model_dump(mode="json")], "unresolved": [], "case_templates": [{
            "template_id": "refund.supplement", "title": "ARC关联补单", "coverage_kind": "business", "combination": "each",
            "data_calls": [call], "request_bindings": [
                {"field": "id", "source": {"kind": "data_output", "call_id": "prepare", "output_name": "report_id"}},
                {"field": "arcBillVO", "source": {"kind": "data_output", "call_id": "prepare", "output_name": "arc_bill"}},
            ], "oracles": oracles, "evidence": [function.evidence[0].model_dump(mode="json")],
        }]},
        "variants": [{"variant_id": "case-variant-v4-" + "b" * 20, "template_id": "refund.supplement", "ordinal": 1,
                      "parameter_values": {}, "request_values": {}, "data_calls": [call], "oracles": oracles}],
    })


def test_query_reuse_saves_verified_results_separate_from_definition(workflow: SimpleNamespace) -> None:
    """两个独立任务复用同一定义但保留各自真实结果和来源。

    Args:
        workflow: 真实授权、持久化和冻结目录测试范围。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 同一定义两次执行不能共享可变运行状态或把第一次得到的ID写回定义。
    fixed = workflow.function.model_dump(mode="json")
    first = workflow.executor.execute_data(_execution(), workflow.function, workflow.registry)
    second = workflow.executor.execute_data(_execution(), workflow.function, workflow.registry)
    assert first.status == second.status == "COMPLETED"
    assert first.execution_id != second.execution_id
    assert first.outputs == {"report_id": 171, "arc_bill": {"ticket": "TICKET-REAL-1"}, "order_id": "ORDER-REAL-1"}
    assert all(check.passed for check in first.checks)
    assert workflow.data_store.get_execution("refund", first.execution_id) == first
    assert all(step.environment_id == "qa" and step.source_scan_id == "scan-baseline-a" for step in first.step_results)
    assert workflow.function.model_dump(mode="json") == fixed
    assert current_log_context().trace_id == ""


def test_missing_report_creates_once_then_performs_fresh_query(workflow: SimpleNamespace) -> None:
    """成功创建后必须发出新查询请求，不能复用写入前的幂等空结果。

    Args:
        workflow: Provider初始无报表的跨系统范围。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 原始查询结果已被幂等存储缓存；创建后的新查询必须使用独立阶段身份。
    workflow.provider.report = None
    execution = workflow.executor.execute_data(_execution(True), workflow.function, workflow.registry)
    calls = [cap.operation_id for cap, _request in workflow.provider.calls]
    assert execution.status == "COMPLETED"
    assert calls == [REPORT_QUERY, BOOKING_QUERY, REPORT_SAVE, REPORT_QUERY, BOOKING_QUERY]
    query_requests = [request.request_id for cap, request in workflow.provider.calls if cap.operation_id == REPORT_QUERY]
    assert len(set(query_requests)) == 2
    assert execution.outputs["report_id"] == 171
    assert all(check.passed for check in execution.checks)


@pytest.mark.parametrize("mode", ["no_write", "success_without_result"])
def test_create_gaps_never_produce_unverified_output(workflow: SimpleNamespace, mode: str) -> None:
    """缺权限或接口成功但回查为空都要保留具体失败，不能编造输出。

    Args:
        workflow: 授权及持久运行范围。
        mode: 本次制造的权限或实际创建失败。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 分别移除本次运行写授权或实际落库效果，都不能靠接口success绕过。
    workflow.provider.report = None
    if mode == "success_without_result":
        workflow.provider.save_persists = False
    execution = workflow.executor.execute_data(_execution(mode != "no_write"), workflow.function, workflow.registry)
    assert execution.status == "FAILED" and execution.outputs == {}
    assert execution.failure_kind == "DATA_PREPARATION_FAILED"
    assert workflow.data_store.get_execution("refund", execution.execution_id).status == "FAILED"
    assert sum(cap.operation_id == REPORT_SAVE for cap, _request in workflow.provider.calls) <= 1


def test_only_verified_identity_allows_state_adjustment(workflow: SimpleNamespace) -> None:
    """身份全部匹配才可调整有限状态，调整后的状态必须回查验证。

    Args:
        workflow: 初始报表身份正确但状态不满足的Provider。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 状态错误在首次验证中可见，只有后续回查证明变更才允许输出。
    workflow.provider.report["state"] = "PENDING"
    execution = workflow.executor.execute_data(_execution(True), workflow.function, workflow.registry)
    assert execution.status == "COMPLETED"
    assert [cap.operation_id for cap, _request in workflow.provider.calls].count(REPORT_ADJUST) == 1
    state_checks = [check for check in execution.checks if check.kind == "state"]
    assert [check.passed for check in state_checks] == [False, True]
    assert state_checks[0].actual == "PENDING" and state_checks[1].actual == "READY"


@pytest.mark.parametrize("mismatch", ["owner", "orderId", "ext"])
def test_wrong_relationship_never_adjusts_or_replaces_user_condition(workflow: SimpleNamespace, mismatch: str) -> None:
    """真实ID属于错误主体或不同原单时，不能借状态调整让任务假成功。

    Args:
        workflow: 已授权有限写操作的执行范围。
        mismatch: 被替换成其他真实记录值的关联维度。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 同时制造状态错误，证明身份失败会阻止原本可用的调整分支。
    workflow.provider.report["state"] = "PENDING"
    workflow.provider.report[mismatch] = json.dumps({"arcRefundAccount": {"ticket": "OTHER-TICKET"}}) if mismatch == "ext" else "OTHER"
    execution = workflow.executor.execute_data(_execution(True), workflow.function, workflow.registry)
    assert execution.status == "FAILED" and execution.failure_kind == "DATA_PREPARATION_FAILED"
    assert execution.inputs == {"owner": "BUYER-1"}
    assert all(cap.operation_id not in {REPORT_SAVE, REPORT_ADJUST} for cap, _request in workflow.provider.calls)


@pytest.mark.parametrize("encoded", ["not-json", "[]", '{"arcRefundAccount": {}}'])
def test_invalid_actual_json_is_data_failure(workflow: SimpleNamespace, encoded: str) -> None:
    """真实ext缺失或结构错误时停止流程，不运行目标或把未知当成功。

    Args:
        workflow: 带真实Operation记录的准备范围。
        encoded: 解析或结构不足的实际业务文本。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 保留两个成功查询，验证失败仍应保留前序真实取数轨迹。
    workflow.provider.report["ext"] = encoded
    execution = workflow.executor.execute_data(_execution(), workflow.function, workflow.registry)
    assert execution.status == "FAILED" and execution.failure_kind == "DATA_PREPARATION_FAILED"
    assert len(execution.step_results) == 2


@pytest.mark.parametrize('actual,expected', [
    ('2026-10-08 01:20:00.000', '2026-10-08 01:20:00'),
    ('1900-01-01 00:00:00.000', '1900-01-01 00:00:00'),
    ('2026-02-30 01:20:00.000', None),
    (None, None),
])
def test_date_conversion_preserves_actual_value_or_stops_before_target(workflow, actual, expected):
    """查询日期按固定格式映射；非法日期或空值保留失败记录并禁止目标派发。"""

    from opentest.domain.case_template_v4 import DataFunctionStep, DataFunctionOutput, CaseRequestBinding

    workflow.provider.order['departure'] = actual
    workflow.function.verify_steps.insert(0, DataFunctionStep(step_id='departure_format', operation='format_datetime',
        input_source=DslValueSource(kind='step_output', step_id='booking_query', path='order.departure'),
        input_format='%Y-%m-%d %H:%M:%S.%f', output_format='%Y-%m-%d %H:%M:%S'))
    workflow.function.outputs.append(DataFunctionOutput(output_name='departure', step_id='departure_format'))
    generation = _generation(workflow.function)
    generation.submission.case_templates[0].request_bindings.append(CaseRequestBinding(field='departure',
        source=DslValueSource(kind='data_output', call_id='prepare', output_name='departure')))
    case = workflow.executor.execute('case-generation-execution-' + 'e' * 20, generation, workflow.registry)[0]
    dispatched = [request for capability, request in workflow.provider.calls if capability.operation_id == TARGET]
    if expected is None:
        assert case.status == 'BLOCKED' and not dispatched
        prepared = workflow.data_store.get_execution('refund', case.data_execution_ids[0])
        assert prepared.status == 'FAILED' and '固定格式' in prepared.error
    else:
        assert case.status == 'COMPLETED'
        assert dispatched[0].arguments['departure'] == expected


def test_date_compilation_keeps_string_type_and_runtime_provenance():
    """编译日期步骤时保持字符串类型与真实查询来源，数值输入产生精确类型问题。"""

    from opentest.application.case_template_compiler_v4 import CaseTemplateValidatorV4
    from opentest.domain.case_template_v4 import DataFunctionValidationInput, DataFunctionCall

    function = DataFunctionDraft.model_validate({
        'name': 'booking_date', 'description': '映射订票日期到退票输入格式',
        'steps': [
            {'step_id': 'query_date', 'operation': 'runtime_call', 'function_id': BOOKING_QUERY},
            {'step_id': 'format_date', 'operation': 'format_datetime',
             'input_source': {'kind': 'step_output', 'step_id': 'query_date', 'path': 'date'},
             'input_format': '%Y-%m-%d %H:%M:%S.%f', 'output_format': '%Y-%m-%d %H:%M:%S'}],
        'outputs': [{'output_name': 'departure', 'step_id': 'format_date'}],
        'evidence': [{'source_system_id': 'booking', 'path': 'Booking.java', 'symbol': 'Booking#query', 'line': 1}],
    })
    descriptor = RuntimeFunctionDescriptor(function_id=BOOKING_QUERY, kind='dsf', description='查询真实日期',
        input_schema={'type': 'object'}, output_schema={'type': 'object', 'properties': {'date': {'type': 'string'}}},
        read_only=True, allowed_phases=['DATA'], source_system_id='booking', provider_ref=BOOKING_QUERY)
    validation = DataFunctionValidationInput(runtime_registry=RuntimeFunctionRegistry(functions=[descriptor]), allowed_system_ids={'booking'})
    compiler = CaseTemplateValidatorV4()
    assert compiler._validate_data_function(validation, function, {BOOKING_QUERY: descriptor}) == []
    assert compiler._step_is_runtime_derived(function, 'format_date')
    source = DslValueSource(kind='data_output', call_id='prepare', output_name='departure')
    assert compiler._data_output_schema(source, {'prepare': DataFunctionCall(call_id='prepare', function_name='booking_date')},
        {'booking_date': function}, {BOOKING_QUERY: descriptor}) == {'type': 'string'}
    # 日期表达与数字不是兼容契约，编译时必须明确指出而不是运行时自动猜测。
    descriptor.output_schema['properties']['date'] = {'type': 'integer'}
    assert any(issue.code == 'DATETIME_FORMAT_INPUT' for issue in compiler._validate_data_function(validation, function, {BOOKING_QUERY: descriptor}))


def test_case_reuses_same_data_and_fixed_baseline_without_cleanup(workflow: SimpleNamespace) -> None:
    """G1内嵌定义在共享新版改变后仍被两个Case执行复用，且没有cleanup前置。

    Args:
        workflow: 固定A目录及同一独立数据执行器。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 先固定G1，再把共享定义的业务状态规则改为不兼容值以检查执行不会偷读新版。
    generation = _generation(workflow.function)
    frozen = generation.model_dump(mode="json")
    independent = workflow.executor.execute_data(_execution(), workflow.function, workflow.registry)
    workflow.function.verify_steps[-1].predicates[0].right.value = "NEW_VERSION_STATE"
    workflow.operations.execute_resolved = Mock(wraps=workflow.operations.execute_resolved)
    for identity in ("c", "d"):
        case = workflow.executor.execute("case-generation-execution-" + identity * 20, generation, workflow.registry)[0]
        assert case.status == "COMPLETED" and case.failure_kind == ""
        assert [step.phase for step in case.operations] == ["DATA", "DATA", "TARGET", "ORACLE"]
        prepared = workflow.data_store.get_execution("refund", case.data_execution_ids[0])
        assert prepared.outputs == independent.outputs and prepared.capability_version == 1
        target = next(step for step in case.operations if step.phase == "TARGET")
        assert target.actual_request["id"] == prepared.outputs["report_id"]
    assert generation.model_dump(mode="json") == frozen
    workflow.operations.get.assert_not_called()
    assert [call.args[3] for call in workflow.operations.execute_resolved.call_args_list] == [
        SystemDependencyPurpose.SETUP, SystemDependencyPurpose.SETUP,
        SystemDependencyPurpose.ACTION, SystemDependencyPurpose.ORACLE,
    ] * 2


@pytest.mark.parametrize("failure", ["data", "provider", "behavior", "observer"])
def test_case_distinguishes_four_failure_sources(workflow: SimpleNamespace, failure: str) -> None:
    """报告必须区分数据不足、环境依赖、业务差异和观察失败。

    Args:
        workflow: 同一Case及真实Operation分类边界。
        failure: 本次注入的唯一失败阶段。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 相同Case只改变失败阶段，避免把所有失败都统计为行为回归。
    if failure == "data":
        workflow.provider.report["owner"] = "OTHER"
    elif failure == "provider":
        workflow.provider.fail_operation = REPORT_QUERY
    elif failure == "behavior":
        workflow.provider.response_success = False
    else:
        workflow.provider.fail_operation = OBSERVER
    case = workflow.executor.execute("case-generation-execution-" + "e" * 20, _generation(workflow.function), workflow.registry)[0]
    assert case.failure_kind == {"data": "DATA_PREPARATION_FAILED", "provider": "ENVIRONMENT_DEPENDENCY",
                                 "behavior": "BEHAVIOR_DIFF", "observer": "OBSERVATION_FAILED"}[failure]
    if failure in {"data", "provider"}:
        assert all(step.phase != "TARGET" for step in case.operations)


@pytest.mark.parametrize("missing", ["identity_verification", "write_permission"])
def test_state_adjustment_requires_both_verified_identity_and_current_write_permission(
    workflow: SimpleNamespace, missing: str,
) -> None:
    """合法状态修改也必须同时满足主体证据与本次写授权。

    Args:
        workflow: 状态不匹配但可调整的测试范围。
        missing: 被明确撤掉的必要条件。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 即使写Operation已在系统绑定中授权，运行授权和真实身份仍各自不可缺少。
    workflow.provider.report["state"] = "PENDING"
    function = workflow.function
    if missing == "identity_verification":
        function = function.model_copy(update={"verify_steps": [function.verify_steps[-1]]})
    execution = workflow.executor.execute_data(_execution(missing != "write_permission"), function, workflow.registry)
    assert execution.status == "FAILED" and execution.failure_kind == "DATA_PREPARATION_FAILED"
    assert all(cap.operation_id != REPORT_ADJUST for cap, _request in workflow.provider.calls)


def test_readonly_database_descriptor_cannot_execute_write_sql(workflow: SimpleNamespace) -> None:
    """数据库Operation的可写属性不能让只读DATA包装执行UPDATE。

    Args:
        workflow: 服务端固定目录及真实Operation入口。
    Returns:
        None；满足上述业务断言时通过。
    """

    descriptor = workflow.registry.functions[0].model_copy(update={"kind": "mysql", "read_only": True})
    query = workflow.function.steps[0].model_copy(update={"arguments": {
        "statement": {"kind": "literal", "value": "UPDATE reports SET state = ?"},
    }})
    # model_copy模拟历史草稿越过编译器，执行末端仍必须拒绝SQL动作与描述不一致。
    query.arguments = {name: DslValueSource.model_validate(value) for name, value in query.arguments.items()}
    function = workflow.function.model_copy(update={"steps": [query, workflow.function.steps[1]]})
    registry = workflow.registry.model_copy(update={"functions": [descriptor, *workflow.registry.functions[1:]]})
    execution = workflow.executor.execute_data(_execution(True), function, registry)
    assert execution.status == "FAILED" and "SELECT" in execution.error
    assert workflow.provider.calls == []


def test_missing_frozen_operation_does_not_select_latest(workflow: SimpleNamespace) -> None:
    """旧计划缺少固定Operation时报告环境依赖缺口，不能读取latest换版本。

    Args:
        workflow: 有真实统一服务但故意缺一个固定能力的执行器。
    Returns:
        None；满足上述业务断言时通过。
    """

    # 让真实OperationService的最新目录仍可调用，缺失固定能力也不得触发该路径。
    del workflow.executor.capabilities[("supplement", REPORT_QUERY)]
    execution = workflow.executor.execute_data(_execution(), workflow.function, workflow.registry)
    assert execution.status == "FAILED" and execution.failure_kind == "ENVIRONMENT_DEPENDENCY"
    assert execution.step_results[0].status == "BLOCKED"
    assert workflow.provider.calls == []
    workflow.operations.get.assert_not_called()


def test_nested_array_bindings_preserve_real_passenger_values() -> None:
    """真实取数叶子应组成JSON乘客数组，容器冲突和失控索引必须阻断目标。"""

    executor = object.__new__(CaseTemplateExecutorV4)
    request = {}
    executor._write_path(request, 'refund.items.0.passenger.name', 'observed-name')
    executor._write_path(request, 'refund.items.0.segments.0.id', 'observed-segment')
    assert request == {'refund': {'items': [{'passenger': {'name': 'observed-name'},
                                           'segments': [{'id': 'observed-segment'}]}]}}
    # 同一字段不能先当数组再当对象；异常发生在发起业务调用之前。
    with pytest.raises(Exception, match='冲突'):
        executor._write_path(request, 'refund.items.name', 'conflict')
    with pytest.raises(Exception, match='索引非法'):
        executor._write_path({}, 'items.1000.id', 'too-far')
