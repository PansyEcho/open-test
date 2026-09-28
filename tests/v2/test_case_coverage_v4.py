"""验证扫描覆盖分母进入真实V4编译与执行，不以AI自报或间接观察替代证据。"""

from copy import deepcopy
from typing import Any

import pytest

from opentest.application.case_template_compiler_v4 import CaseTemplateCompilerV4
from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4
from opentest.application.case_template_registries import CaseTemplateRegistryLoader
from opentest.domain.case_template_v4 import (
    CaseCoverageBinding, CaseOracle, CaseTemplateCompilationInput, CaseTemplateGenerationV4,
    CaseTemplateSubmission, RuntimeFunctionDescriptor, RuntimeFunctionRegistry,
)
from opentest.domain.models import (
    DecisionObligation, DecisionPredicate, EffectObligation, OperationExecutionRecord,
    OperationExecutionStatus, OperationInputKnowledgeContract, OperationKind,
    ProgramCaseAnalysisArtifact, SemanticCaseEvidence, SourceBaseline, SourceReference,
)

SYSTEM = "coverage-system"
ENTRY = "facade:sample.OrderFacade#submit"
SCAN = "scan-coverage-frozen"
OBLIGATION = "obligation:program:0001:0001"


def _compilation(obligation: Any = None) -> CaseTemplateCompilationInput:
    """构造保留完整编译器校验的单请求样本，可附加服务端冻结覆盖义务。

    Args:
        obligation: 程序产生的精确覆盖项，不经AI提交字段传递。
    Returns:
        带真实目录、输入契约、响应断言和可选覆盖资产的编译输入。
    """

    submission = CaseTemplateSubmission.model_validate({"data_functions": [], "unresolved": [], "case_templates": [{
        "template_id": "order.normal", "title": "提交订单", "coverage_kind": "business",
        "combination": "each", "evidence": [{"source_system_id": SYSTEM, "path": "OrderFacade.java", "line": 10}],
        "request_bindings": [{"field": "mode", "source": {"kind": "literal", "value": "A"}}],
        "oracles": [{"oracle_id": "response.success", "channel": "response", "assertions": [{
            "actual_path": "success", "operator": "eq", "expected": {"kind": "literal", "value": True},
        }]}],
    }]})
    # 分母由扫描资产注入，与模型提交的coverage_bindings保持不同信任边界。
    analysis = ProgramCaseAnalysisArtifact(
        artifact_id="program-analysis:coverage:0001", system_id=SYSTEM, source_scan_id=SCAN,
        source_baseline=SourceBaseline(source_path="/frozen-production-source", commit="a" * 40),
        entry_id=ENTRY, status="ANALYZED", core_obligations=[obligation] if obligation else [],
    )
    return CaseTemplateCompilationInput(
        submission=submission,
        input_contract=OperationInputKnowledgeContract(
            target_id=ENTRY, request_type="SubmitRequest", source_scan_id=SCAN, status="READY",
            request_schema={"type": "object", "properties": {"mode": {"type": "string"}}},
            fields=[{"path": "mode", "field_name": "mode", "schema": {"type": "string"}}],
        ),
        target_output_schema={"type": "object", "properties": {"success": {"type": "boolean"}}},
        runtime_registry=RuntimeFunctionRegistry(functions=[]),
        value_registry=CaseTemplateRegistryLoader().value_registry(), allowed_system_ids={SYSTEM},
        program_analysis=analysis,
    )


def _effect(kind: str) -> EffectObligation:
    """构造扫描确认的副作用责任，允许测试其缺观察源时的固定失败语义。

    Args:
        kind: database、redis、mq或rpc通道。
    Returns:
        固定到本接口和扫描分母的程序义务。
    """

    return EffectObligation(
        obligation_id=OBLIGATION, system_id=SYSTEM, entry_id=ENTRY, title="验证真实副作用", origin="program",
        effect_kind=kind, effect_target="orders", observation="观察真实操作结果",
        resource_id="resource:orders-db" if kind == "database" else "",
        resource_target="orders", effect_fields=["state"] if kind == "database" else [],
    )


def _generation(compilation: CaseTemplateCompilationInput, variants: list[Any]) -> CaseTemplateGenerationV4:
    """把编译结果保存为生产源码基线固定的Generation，供测试执行器消费。

    Args:
        compilation: 固定契约、覆盖资产与DSL；variants: 已完成校验的编译变体。
    Returns:
        可序列化且再次执行不会改写预期的Generation。
    """

    return CaseTemplateGenerationV4(
        generation_id="case-template-generation-" + "1" * 20,
        handoff_id="case-template-handoff-" + "2" * 20,
        system_id=SYSTEM, operation_id=ENTRY, source_scan_id=SCAN, coverage_id=f"coverage:{ENTRY}",
        runtime_registry_version="runtime-functions/v1", value_registry_version="value-functions/v1",
        status="READY", input_contract=compilation.input_contract, submission=compilation.submission,
        program_analysis=compilation.program_analysis, variants=variants,
    )


class _ObservedOperations:
    """模拟真实独立查询与目标写入，调用记录可以证明前值/目标/后值顺序。"""

    def __init__(self, fail_before: bool = False):
        """创建隔离业务状态；fail_before仅让第一次观察读取失败。

        Args:
            fail_before: 注入观察异常而不影响目标和后续观察。
        """

        self.state = 0
        self.calls: list[str] = []
        self.fail_before = fail_before

    def execute(self, system_id: str, request: Any) -> OperationExecutionRecord:
        """按实际调用推进业务状态并返回独立Operation记录。

        Args:
            system_id: 被调用系统；request: 受控Operation请求。
        Returns:
            目标成功响应或当时的真实查询状态。
        Raises:
            RuntimeError: 故障注入的首次观察不可用。
        """

        self.calls.append(request.operation_id)
        # 目标调用改变状态；观察只读，不能通过测试夹具改目标预期使其通过。
        if request.operation_id == ENTRY:
            self.state += 1
        elif self.fail_before and len(self.calls) == 1:
            raise RuntimeError("observer unavailable")
        return OperationExecutionRecord(
            execution_id=f"operation-execution-{len(self.calls):020d}", request_id=request.request_id,
            request_digest="f" * 64, system_id=system_id, operation_id=request.operation_id,
            kind=OperationKind.FACADE, status=OperationExecutionStatus.COMPLETED,
            result={"status": "success", "output": {"success": True, "state": self.state}},
        )


def _with_observers(compilation: CaseTemplateCompilationInput) -> CaseTemplateCompilationInput:
    """加入相同业务对象的前后只读观察，后值必须与真实前值不同。

    Args:
        compilation: 已构建的测试编译输入。
    Returns:
        使用扫描目录证明输出结构的完整编译输入。
    """

    descriptor = RuntimeFunctionDescriptor(
        function_id="facade:sample.OrderFacade#detail", source_system_id=SYSTEM, kind="dsf",
        description="读取当前订单状态", provider_ref="facade:sample.OrderFacade#detail", read_only=True,
        allowed_phases=["ORACLE"], input_schema={"type": "object"},
        output_schema={"type": "object", "properties": {"state": {"type": "integer"}}},
    )
    template = compilation.submission.case_templates[0]
    before = CaseOracle.model_validate({
        "oracle_id": "state.before", "phase": "before", "channel": "operation",
        "function_id": descriptor.function_id, "assertions": [{"actual_path": "state", "operator": "exists"}],
    })
    after = CaseOracle.model_validate({
        "oracle_id": "state.after", "channel": "operation", "function_id": descriptor.function_id,
        "assertions": [{"actual_path": "state", "operator": "ne", "expected": {
            "kind": "observation", "name": "state.before", "path": "state",
        }}],
    })
    # DSL序列刻意把前置观察放最后，执行阶段仍必须先完成所有before。
    template = template.model_copy(update={"oracles": [*template.oracles, after, before]})
    return compilation.model_copy(update={
        "submission": compilation.submission.model_copy(update={"case_templates": [template]}),
        "runtime_registry": RuntimeFunctionRegistry(functions=[descriptor]),
    })


def test_forged_decision_outcome_cannot_replace_actual_input_partition() -> None:
    """AI宣称覆盖FALSE但实际输入仍命中TRUE时，编译必须指出缺少的业务分区。

    Returns:
        None；真实谓词求值发现缺口，完全未绑定时产生独立遗漏错误。
    """

    decision = DecisionObligation(
        obligation_id=OBLIGATION, system_id=SYSTEM, entry_id=ENTRY, title="mode控制分支", origin="program",
        condition="mode == A", outcomes=["TRUE", "FALSE"],
        predicate=DecisionPredicate(operator="eq", input_path="mode", expected="A"),
        outcome_expectations={"TRUE": True, "FALSE": False},
    )
    compilation = _compilation(decision)
    template = compilation.submission.case_templates[0]
    template.coverage_bindings = [CaseCoverageBinding(obligation_id=OBLIGATION, outcome="FALSE")]
    _, issues = CaseTemplateCompilerV4().compile(compilation)
    assert "DECISION_OUTCOME_UNCOVERED" in {issue.code for issue in issues}
    # 删除自报绑定不得删除程序分母。
    template.coverage_bindings = []
    _, issues = CaseTemplateCompilerV4().compile(compilation)
    assert "MISSING_PROGRAM_COVERAGE" in {issue.code for issue in issues}


@pytest.mark.parametrize("kind", ["mq", "rpc", "redis"])
def test_missing_required_observer_fails_after_successful_target(kind: str) -> None:
    """必要事件/命令缺少观察源时仍保留目标结果，但产生OBSERVATION_FAILED。

    Args:
        kind: 无直接事件观察源的副作用类型。
    Returns:
        None；目标成功不能掩盖观察失败，实际证据仍为null。
    """

    compilation = _compilation(_effect(kind))
    variants, issues = CaseTemplateCompilerV4().compile(compilation)
    assert issues == []
    operations = _ObservedOperations()
    outcome = CaseTemplateExecutorV4(operations).execute(
        "case-generation-execution-" + "3" * 20, _generation(compilation, variants), compilation.runtime_registry,
    )[0]
    assert operations.calls == [ENTRY]
    assert outcome.operations[0].status == "COMPLETED"
    assert outcome.assertions[0].passed
    assert outcome.status == "FAILED"
    assert outcome.failure_kind == "OBSERVATION_FAILED"
    assert outcome.assertions[-1].actual_value is None
    assert not outcome.assertions[-1].passed


def test_unknown_activation_cannot_remove_required_effect() -> None:
    """未证明helper输入或控制流时，即使同名根字段为false也不能删除副作用责任。

    Returns:
        None；activation_complete为false的伪FALSE谓词不会规避观察失败。
    """

    effect = _effect("mq").model_copy(update={"effect_evidence_id": "evidence:helper:send"})
    compilation = _compilation(effect)
    fact = SemanticCaseEvidence(
        evidence_id=effect.effect_evidence_id, method_symbol_id="helper#send(Request)", kind="effect",
        effect_kind="mq", effect_target="orders", binding_kind="method_parameter",
        activation_predicate=DecisionPredicate(operator="constant", expected=False), activation_complete=False,
        source_ref=SourceReference(path="Helper.java", line=10),
    )
    compilation.program_analysis = compilation.program_analysis.model_copy(update={"evidence": [fact]})
    variants, issues = CaseTemplateCompilerV4().compile(compilation)
    assert issues == []
    assert variants[0].observation_failures[0].obligation_id == OBLIGATION


def test_before_after_observations_preserve_values_and_frozen_generation() -> None:
    """后置断言使用真实前值，执行保存差异而不改写生产基线Generation。

    Returns:
        None；调用顺序、实际值、预期值和再次序列化后的固定资产均保持正确。
    """

    compilation = _with_observers(_compilation())
    variants, issues = CaseTemplateCompilerV4().compile(compilation)
    assert issues == []
    generation = _generation(compilation, variants)
    frozen = deepcopy(generation.model_dump(mode="json"))
    operations = _ObservedOperations()
    outcome = CaseTemplateExecutorV4(operations).execute(
        "case-generation-execution-" + "4" * 20, generation, compilation.runtime_registry,
    )[0]
    observer = compilation.runtime_registry.functions[0].function_id
    assert operations.calls == [observer, ENTRY, observer]
    assert outcome.status == "COMPLETED"
    after = next(item for item in outcome.assertions if item.oracle_id == "state.after")
    assert after.expected_value == 0
    assert after.actual_value == 1
    assert after.passed
    assert generation.model_dump(mode="json") == frozen
    assert CaseTemplateGenerationV4.model_validate(frozen).program_analysis.source_scan_id == SCAN


def test_failed_before_observation_does_not_hide_later_results() -> None:
    """一次观察异常不能中止目标和其他观察，无法取得的前值继续形成失败断言。

    Returns:
        None；前后两处观察缺口均保留且最终观察分类失败。
    """

    compilation = _with_observers(_compilation())
    variants, issues = CaseTemplateCompilerV4().compile(compilation)
    assert issues == []
    operations = _ObservedOperations(fail_before=True)
    outcome = CaseTemplateExecutorV4(operations).execute(
        "case-generation-execution-" + "5" * 20, _generation(compilation, variants), compilation.runtime_registry,
    )[0]
    assert len(operations.calls) == 3
    assert outcome.status == "FAILED"
    assert outcome.failure_kind == "OBSERVATION_FAILED"
    assert sum(not item.passed for item in outcome.assertions) == 2
    assert next(item for item in outcome.assertions if item.oracle_id == "response.success").passed


def test_observation_reference_requires_existing_before_output_path() -> None:
    """已命名前置观察也不能放宽输出路径，避免把空值比较伪装为前后验证。

    Returns:
        None；不存在的前值字段在调用业务接口前被编译器拒绝。
    """

    compilation = _with_observers(_compilation())
    after = next(item for item in compilation.submission.case_templates[0].oracles if item.phase == "after" and item.channel == "operation")
    after.assertions[0].expected.path = "unscannedField"
    _, issues = CaseTemplateCompilerV4().compile(compilation)
    assert "INVALID_OBSERVATION_SOURCE" in {issue.code for issue in issues}


@pytest.mark.parametrize("observed_table,asserted_field,assertion_operator,identity_kind", [
    ("other_orders", "state", "eq", "request_field"),
    ("orders", "id", "eq", "request_field"),
    ("orders", "state", "eq", "request_field"),
    ("orders", "state", "exists", "literal"),
    ("orders", "state", "eq", "literal"),
])
def test_mysql_effect_requires_exact_table_and_changed_field(
    observed_table: str, asserted_field: str, assertion_operator: str, identity_kind: str,
) -> None:
    """同表字段存在或另一业务行的预期状态，均不能证明本次请求完成了写入。

    Args:
        observed_table: Oracle实际查询表；asserted_field: Oracle实际断言字段。
        assertion_operator: 值比较或仅检查存在；identity_kind: 来自请求或无关字面量的查询条件。
    Returns:
        None；错误观察拒绝编译，匹配表列的观察仍保留目标行关联未证明的失败项。
    """

    compilation = _compilation(_effect("database"))
    descriptor = RuntimeFunctionDescriptor(
        function_id="database:coverage-system:orders", source_system_id=SYSTEM, kind="mysql",
        description="订单数据库只读观察", provider_ref="database:coverage-system:orders", read_only=True,
        resource_id="resource:orders-db", allowed_phases=["ORACLE"], input_schema={}, output_schema={},
    )
    identity = {"kind": "request_field", "path": "mode"} if identity_kind == "request_field" else {"kind": "literal", "value": "unrelated-order"}
    assertion = {"actual_path": f"rows.0.{asserted_field}", "operator": assertion_operator}
    if assertion_operator != "exists":
        assertion["expected"] = {"kind": "literal", "value": "DONE"}
    oracle = CaseOracle.model_validate({
        "oracle_id": "database.state", "channel": "mysql", "function_id": descriptor.function_id,
        "statement": f"SELECT id, state FROM {observed_table} WHERE id = :id LIMIT 1",
        "arguments": {"id": identity},
        "observer_output_schema": {"type": "object", "properties": {"rows": {"type": "array", "items": {
            "type": "object", "properties": {"state": {"type": "string"}, "id": {"type": "string"}},
        }}}},
        "assertions": [assertion],
        "evidence": [{"source_system_id": SYSTEM, "path": "OrderMapper.xml", "line": 10}],
    })
    template = compilation.submission.case_templates[0]
    # 绑定正确ID也必须对照实际SQL与断言，不接受AI自行声明已覆盖。
    template.oracles.append(oracle)
    template.coverage_bindings = [CaseCoverageBinding(obligation_id=OBLIGATION, oracle_id=oracle.oracle_id)]
    compilation.runtime_registry = RuntimeFunctionRegistry(functions=[descriptor])
    variants, issues = CaseTemplateCompilerV4().compile(compilation)
    if observed_table == "orders" and asserted_field == "state" and assertion_operator == "eq":
        assert issues == []
        assert variants[0].observation_failures[0].obligation_id == OBLIGATION
        assert "目标行定位" in variants[0].observation_failures[0].reason
    else:
        assert "MISSING_EFFECT_OBSERVER" in {issue.code for issue in issues}
