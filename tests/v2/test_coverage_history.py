"""验证覆盖补充有界读取真实存储中的成功历史，且不重放历史业务数据。"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.coverage_supplement import CoverageSupplement
from opentest.domain.case_template_v4 import (
    CaseCleanupAction, CaseGenerationExecutionV4, CaseTemplateSubmission, CaseVariantExecutionV4, CaseVariantV4,
    DataFunctionStep,
)
from opentest.domain.coverage_workflow import CoverageEnhancement
from opentest.domain.models import SystemDefinition
from test_coverage_publication import publication


def _historical_generation(base, identity: str, exceptional: bool = True):
    """构造同一提交、另一扫描下的动态取数场景，供存储边界测试。

    Args:
        base: 冻结源码及契约的基础版本。
        identity: 测试版本和 Variant 共用的唯一十六进制字符。
        exceptional: 场景是否期待业务错误响应。
    Returns:
        只包含可重复的数据函数定义、不固化真实订单的 Generation。
    """

    # 查询结果才提供目标身份；期望业务失败与执行器 PASSED 是不同概念。
    evidence = [{"source_system_id": base.system_id, "path": "Facade.java", "line": 1}]
    template_id = "case.exception" if exceptional else "case.normal"
    submission = CaseTemplateSubmission.model_validate({
        "data_functions": [{
            "name": "find_query_item", "description": "每次查询并回查符合场景的对象",
            "steps": [{"step_id": "find", "operation": "runtime_call", "function_id": "runtime.lookup"}],
            "verify_steps": [{"step_id": "verify", "operation": "assert", "predicates": [
                {"left": {"kind": "step_output", "step_id": "find", "path": "id"}, "operator": "not_null"},
            ]}],
            "outputs": [{"output_name": "item_id", "step_id": "find", "path": "id"}], "evidence": evidence,
        }],
        "case_templates": [{
            "template_id": template_id, "title": "异常输入响应" if exceptional else "正常查询响应",
            "coverage_kind": "business", "combination": "each",
            "data_calls": [{"call_id": "item", "function_name": "find_query_item"}],
            "request_bindings": [{"field": "refundSerialNo",
                "source": {"kind": "data_output", "call_id": "item", "output_name": "item_id"}}],
            "oracles": [{"oracle_id": "response.success", "channel": "response", "assertions": [
                {"actual_path": "success", "operator": "eq", "expected": {"kind": "literal", "value": not exceptional}},
            ]}], "evidence": evidence,
        }], "unresolved": [],
    })
    variant = CaseVariantV4(
        variant_id="case-variant-v4-" + identity * 20, template_id=template_id, ordinal=1,
        parameter_values={}, request_values={}, data_calls=submission.case_templates[0].data_calls,
        oracles=submission.case_templates[0].oracles,
    )
    generation = base.model_copy(deep=True, update={
        "generation_id": "case-template-generation-" + identity * 20,
        "source_scan_id": "scan-history-" + identity, "submission": submission, "variants": [variant],
    })
    generation.source_scopes[0].source_scan_id = generation.source_scan_id
    generation.input_contract.source_scan_id = generation.source_scan_id
    return generation


def _save_execution(fixture, generation, status: str = "PASSED", environment: str = "qa"):
    """保存带目标调用和机器断言的执行证据，不访问测试环境。

    Args:
        fixture: 每个测试独立的真实 MySQL 工作台。
        generation: 已存储的不可变版本。
        status: 最终执行状态。
        environment: 记录的实际执行环境。
    Returns:
        经原执行 store 严格回读的终态记录。
    """

    # 旧业务数据只出现在执行证据中，候选上下文必须把它们排除。
    execution = CaseGenerationExecutionV4(
        execution_id=generation.generation_id.replace("template-generation", "generation-execution"),
        generation_id=generation.generation_id, system_id=generation.system_id,
        environment_id=environment, status="RUNNING",
        variant_results=[CaseVariantExecutionV4(
            variant_id=variant.variant_id, status="COMPLETED",
            operations=[{
                "stage_id": "target", "phase": "TARGET", "function_id": generation.operation_id,
                "execution_id": "operation-real", "system_id": generation.system_id,
                "environment_id": environment, "status": "COMPLETED",
                "actual_request": {"order": "HISTORICAL_ORDER_MUST_NOT_COPY"},
                "actual_response": {"private": "HISTORICAL_RESPONSE_MUST_NOT_COPY"},
            }],
            assertions=[{"oracle_id": "response.success", "actual_path": "success",
                "operator": "eq", "passed": True, "actual_value": "HISTORICAL_ASSERTION_MUST_NOT_COPY"}],
        ) for variant in generation.variants],
    )
    fixture.app.case_template_v4.executions.create(execution)
    return fixture.app.case_template_v4.executions.update(execution.model_copy(update={"status": status}))


def _history_fixture(fixture):
    """登记正常基础版并绑定补充 handoff，返回可直接读取上下文的服务。

    Args:
        fixture: 真实隔离数据库的发布测试夹具。
    Returns:
        补充服务、工作流、基础版本及模拟的唯一补充 handoff。
    """

    base = _historical_generation(fixture.generation, "a", exceptional=False)
    base.source_scopes[0].contract_revisions = {"runtime.lookup": 1}
    fixture.app.case_template_v4.generations.write(base)
    execution = _save_execution(fixture, base)
    workflow = CoverageEnhancement(
        enhancement_id="coverage-history", task_id="task-" + "f" * 16,
        system_id=base.system_id, operation_id=base.operation_id, base_generation_id=base.generation_id,
        enhanced_generation_id="case-template-generation-" + "e" * 20,
        source_scan_id=base.source_scan_id, source_commit="d" * 40,
        baseline_case_execution_id=execution.execution_id, supplement_task_id="task-" + "b" * 16,
    )
    # 只替换已授权的工作流查找；版本和执行始终由真实 MySQL store 读取。
    records = SimpleNamespace(for_generation=Mock(return_value=workflow))
    supplement = CoverageSupplement(SimpleNamespace(app=fixture.app, tasks=fixture.app.tasks, records=records))
    handoff = SimpleNamespace(system_id=base.system_id, generation_id=workflow.enhanced_generation_id,
        task_id=workflow.supplement_task_id)
    return supplement, workflow, base, handoff


def test_context_includes_verified_exception_without_old_runtime_values(publication):
    """基础版正常场景不遮蔽另一扫描的异常历史，候选保留动态定义及准确引用。

    Args:
        publication: 隔离 MySQL 夹具，调用和断言为测试证据。
    Returns:
        None；上下文同时保留基础场景和兼容历史，且没有运行数据时通过。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    history = _historical_generation(base, "b")
    # 相同目标契约内容的 revision 可随新扫描增长，不能误当成版本不兼容。
    history.input_contract.contract_revision += 1
    history.source_scopes[0].contract_revisions = {
        **history.source_scopes[0].contract_revisions, history.operation_id: 2,
        "facade:com.example.Api#unusedSelection": 0,
    }
    publication.app.case_template_v4.generations.write(history)
    execution = _save_execution(publication, history)
    context = supplement.context(handoff)

    # 同 commit 的不同扫描可以复用；引用指向原版本/执行，绝不把旧结果变成本轮结果。
    candidate, = context["historical_verified_cases"]
    assert candidate["generation_id"] == history.generation_id
    assert candidate["execution_id"] == execution.execution_id
    assert candidate["verified_variant_ids"] == [history.variants[0].variant_id]
    assert candidate["case_templates"][0]["template_id"] == "case.exception"
    assert candidate["data_functions"][0]["name"] == "find_query_item"
    assert context["base_submission"]["case_templates"][0]["template_id"] == "case.normal"
    assert "HISTORICAL_" not in json.dumps(context, ensure_ascii=False)
    assert "REJECT" in context["instructions"] and "UNRESOLVED 前" in context["instructions"]
    assert workflow.round_used == 0


@pytest.mark.parametrize("mismatch", [
    "commit", "missing_commit", "dirty", "downstream", "contract", "contract_commit",
    "input_semantics", "target", "registry", "not_ready", "downstream_contract",
])
def test_incompatible_history_is_not_a_verified_candidate(publication, mismatch: str):
    """源码、依赖或契约变化必须排除历史，不能靠同接口名称声明适用。

    Args:
        publication: 隔离 MySQL 夹具。
        mismatch: 被修改的版本或契约维度。
    Returns:
        None；历史不进入候选但基础上下文仍然可用时通过。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    history = _historical_generation(base, "b")
    if mismatch in {"commit", "missing_commit"}:
        history.source_scopes[0].source_baseline.commit = "c" * 40 if mismatch == "commit" else ""
    elif mismatch == "dirty":
        history.source_scopes[0].source_baseline.dirty = True
    elif mismatch == "downstream":
        # 两边都有同一下游系统，仅其固定提交不同，防止只比较入口提交。
        dependency = base.source_scopes[0].model_copy(deep=True)
        dependency.source_system_id = "downstream-system"
        base.source_scopes.append(dependency)
        history.source_scopes.append(dependency.model_copy(deep=True))
        history.source_scopes[-1].source_baseline.commit = "c" * 40
        assert supplement._history_compatible(base, history) is False
        return
    elif mismatch == "contract":
        history.input_contract.response_schema = {"type": "string"}
    elif mismatch == "contract_commit":
        history.input_contract.source_commit = "c" * 40
    elif mismatch == "input_semantics":
        history.input_contract.fields[0].business_identity = False
    elif mismatch == "target":
        history.operation_id = "facade:com.example.Other#query"
    elif mismatch == "registry":
        history.runtime_registry_version = "runtime/v2"
    elif mismatch == "downstream_contract":
        history.source_scopes[0].contract_revisions = {"runtime.lookup": 2}
    else:
        history.status = "PARTIAL"
    publication.app.case_template_v4.generations.write(history)
    _save_execution(publication, history)
    context = supplement.context(handoff)
    assert context is not None and context["historical_verified_cases"] == []


@pytest.mark.parametrize("referencing_side", ["base", "history"])
@pytest.mark.parametrize("location, function_id", [
    ("steps", "dsf:example.lookup"),
    ("create_steps", "dsf:example.lookup"),
    ("adjust_steps", "dsf:example.lookup"),
    ("verify_steps", "dsf:example.lookup"),
    ("oracle", "dsf:example.lookup"),
    ("cleanup", "dsf:example.lookup"),
    ("steps", "database:example-system:orders:query"),
    ("steps", "database:example-system:orders:data"),
    ("steps", "database:example-system:orders:observe"),
])
def test_used_contract_missing_on_other_side_is_incompatible(
    publication, referencing_side: str, location: str, function_id: str,
):
    """任一方实际引用的额外契约不能忽略，包含所有准备阶段及数据库派生身份。

    Args:
        publication: 隔离 MySQL 夹具。
        referencing_side: 在基础版或历史版定义中引用依赖。
        location: 数据函数阶段、Oracle 或清理操作。
        function_id: Runtime 身份；数据库 query/data 需要还原契约键。
    Returns:
        None；另一方缺少实际依赖版本时不允许历史复用。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    history = _historical_generation(base, "b")
    contract_id = function_id.rsplit(":", 1)[0] if function_id.startswith("database:") else function_id
    history.source_scopes[0].contract_revisions = {"runtime.lookup": 1, contract_id: 0}
    referenced = base if referencing_side == "base" else history
    template = referenced.submission.case_templates[0]
    if location == "oracle":
        template.oracles[0] = template.oracles[0].model_copy(update={
            "channel": "operation", "function_id": function_id,
        })
    elif location == "cleanup":
        template.cleanup = CaseCleanupAction(
            cleanup_id="cleanup.item", operation_id=function_id, evidence=template.evidence,
        )
    else:
        # 所有可选准备分支都要核实，不能因为本次可能不执行就略过版本边界。
        steps = getattr(referenced.submission.data_functions[0], location)
        steps.append(DataFunctionStep(step_id="extra_call", operation="runtime_call", function_id=function_id))
    assert supplement._history_compatible(base, history) is False


def test_unused_extra_contracts_on_either_side_are_compatible(publication):
    """双方额外登记但定义均未使用的接口不应遮蔽已验证场景。

    Args:
        publication: 隔离 MySQL 夹具。
    Returns:
        None；仅选择范围有额外条目、实际契约和固定源码相同时允许复用。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    history = _historical_generation(base, "b")
    # 重现 handoff 选过查询接口但最终模板/函数未使用的情况，两边都可存在这类选择。
    base.source_scopes[0].contract_revisions = {"runtime.lookup": 1, "facade:com.example.Api#unusedBase": 0}
    history.source_scopes[0].contract_revisions = {"runtime.lookup": 1, "facade:com.example.Api#unusedHistory": 0}
    assert supplement._history_compatible(base, history) is True
    history.source_scopes[0].contract_revisions["facade:com.example.Api#unusedBase"] = 1
    assert supplement._history_compatible(base, history) is False


@pytest.mark.parametrize("invalid", [
    "failed", "environment", "wrong_system", "wrong_generation", "wrong_variant", "no_assertions",
    "failed_assertion", "no_target", "wrong_target", "base", "enhanced",
])
def test_unverified_or_current_execution_is_excluded(publication, invalid: str):
    """排除未通过、错误来源及本轮版本，并核实成功标签背后的逐 Variant 证据。

    Args:
        publication: 隔离 MySQL 夹具。
        invalid: 不具备历史成功证明的场景。
    Returns:
        None；补充上下文无候选且不影响基础版本时通过。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    if invalid == "base":
        assert supplement.context(handoff)["historical_verified_cases"] == []
        return
    identity = "e" if invalid == "enhanced" else "b"
    history = _historical_generation(base, identity)
    if invalid == "wrong_system":
        history.system_id = "other-system"
        publication.app.store.register_system(SystemDefinition(
            system_id=history.system_id, name="另一测试系统", source_path="/tmp"))
    publication.app.case_template_v4.generations.write(history)
    execution = _save_execution(publication, history,
        status="FAILED" if invalid == "failed" else "PASSED",
        environment="uat" if invalid == "environment" else "qa")
    if invalid in {"wrong_generation", "wrong_variant", "no_assertions", "failed_assertion", "no_target", "wrong_target"}:
        # 身份不可由正常 update 改写；模拟损坏历史详情来验证读取侧保守隔离。
        if invalid == "wrong_generation":
            execution.generation_id = base.generation_id
        elif invalid == "wrong_variant":
            execution.variant_results[0].variant_id = "case-variant-v4-" + "f" * 20
        elif invalid == "no_assertions":
            execution.variant_results[0].assertions = []
        elif invalid == "failed_assertion":
            execution.variant_results[0].assertions[0].passed = False
        elif invalid == "no_target":
            execution.variant_results[0].operations = []
        else:
            execution.variant_results[0].operations[0].function_id = "facade:com.example.Wrong#query"
        original_get = publication.app.case_template_v4.executions.get

        def read_execution(system_id, execution_id):
            """仅替换指定历史详情，其余读取继续走 MySQL 的系统隔离。"""
            if execution_id == execution.execution_id:
                return execution
            return original_get(system_id, execution_id)

        publication.app.case_template_v4.executions.get = Mock(side_effect=read_execution)
    assert supplement.context(handoff)["historical_verified_cases"] == []


def test_broken_history_does_not_hide_valid_candidate(publication):
    """一个损坏 Generation 不影响另一成功历史或当前基础上下文。

    Args:
        publication: 隔离 MySQL 夹具。
    Returns:
        None；保留有效候选，损坏条目未通过格式兼容包装被接受时通过。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    for identity in ("b", "c"):
        history = _historical_generation(base, identity)
        publication.app.case_template_v4.generations.write(history)
        _save_execution(publication, history)
    # 只破坏该临时库里的旧版本 JSON，模拟已有历史格式不再可读。
    publication.app.store.metadata.execute(
        "UPDATE ot_case_generation SET generation_json=JSON_SET(generation_json,'$.variants','invalid') WHERE generation_id=%s",
        ("case-template-generation-" + "c" * 20,))
    candidate, = supplement.context(handoff)["historical_verified_cases"]
    assert candidate["generation_id"] == "case-template-generation-" + "b" * 20


def test_history_query_failure_is_optional(publication):
    """历史查询故障不得丢失覆盖缺口或基础定义。

    Args:
        publication: 隔离 MySQL 夹具。
    Returns:
        None；失败只产生空历史候选时通过。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    publication.app.case_template_v4.executions.successful_qa_candidates = Mock(side_effect=RuntimeError("offline"))
    context = supplement.context(handoff)
    assert context["historical_verified_cases"] == []
    assert context["base_execution"]["status"] == "PASSED"
    assert context["workflow"]["enhancement_id"] == workflow.enhancement_id


def test_broken_execution_summary_does_not_hide_valid_candidate(publication):
    """摘要格式损坏只隔离该条，不能使整批历史查询失败。

    Args:
        publication: 隔离 MySQL 夹具。
    Returns:
        None；合法历史仍由原 store 回读并提供给补充上下文时通过。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    for identity in ("b", "c"):
        history = _historical_generation(base, identity)
        publication.app.case_template_v4.generations.write(history)
        execution = _save_execution(publication, history)
    # 数据库索引仍是 PASSED，只有最后一条摘要损坏，验证候选读取逐条容错。
    publication.app.store.metadata.execute(
        "UPDATE ot_execution SET summary_json=JSON_SET(summary_json,'$.execution_id','invalid') WHERE execution_id=%s",
        (execution.execution_id,))
    candidate, = supplement.context(handoff)["historical_verified_cases"]
    assert candidate["generation_id"] == "case-template-generation-" + "b" * 20


def test_history_queries_and_model_candidates_are_bounded(publication):
    """历史查询最多二十条小摘要，模型最多三版，不调用全量列表。

    Args:
        publication: 隔离 MySQL 夹具。
    Returns:
        None；真实 SQL 和补充候选各自遵守数量上限时通过。
    """

    supplement, workflow, base, handoff = _history_fixture(publication)
    for number in range(25):
        identity = f"{number + 1:020x}"
        history = _historical_generation(base, "b").model_copy(update={
            "generation_id": "case-template-generation-" + identity,
        })
        publication.app.case_template_v4.generations.write(history)
        _save_execution(publication, history)
    # 普通全量接口是哨兵；有界路径不能退回读取全系统的大 JSON。
    engine = publication.app.case_template_v4
    engine.generations.list = Mock(side_effect=AssertionError("unbounded generation list"))
    engine.executions.list = Mock(side_effect=AssertionError("unbounded execution list"))
    summaries = engine.executions.successful_qa_candidates(base, {base.generation_id, workflow.enhanced_generation_id})
    assert len(summaries) == 20 and all(not item.variant_results for item in summaries)
    assert len(supplement.context(handoff)["historical_verified_cases"]) == 3
