"""验证真实退款资产可在零QA、零Codex条件下确定性生成cancel Case。"""

from __future__ import annotations

import copy
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from opentest.application.case_execution_v3 import (
    FixedResourceInvocation,
    PublishedInvocationResult,
)
from opentest.adapters.codex_app_server import (
    CodexClientThread,
    CodexThreadCreationRequest,
)
from opentest.application.hybrid_case_handoffs import CaseDraftClosureEvidence
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import ExecutionFailure, KnowledgeValidationError
from opentest.domain.models import (
    CaseConditionType,
    CaseGenerationDraftBundle,
    DataSetupRecipeSubmission,
    HybridCaseGenerationRecord,
    HybridCaseGenerationStartRequest,
    PublishedCapabilityRef,
    PublishedCapabilityRegistry,
    PublishedOperationCapability,
    RecipeFactOutputSubmission,
    SetupContractRuleSet,
    SetupInputPolicy,
    utc_now,
)


SYSTEM_ID = "ifightchainsaas.java.refund.core"
CANCEL_ENTRY_ID = (
    "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel"
)


class QaInvocationProbe:
    """把Case生成期间的任何QA调用转换为立即失败的验收信号。"""

    def __init__(self) -> None:
        """初始化空调用记录；该记录在两次生成后必须仍为空。"""

        self.calls: list[str] = []

    def invoke(
        self,
        capability: PublishedOperationCapability,
        arguments: dict[str, Any],
        execution_key: str,
        environment: str,
        timeout_seconds: int,
    ) -> PublishedInvocationResult:
        """拒绝生成阶段触达任一Published QA能力。

        Args:
            capability: 被错误选择执行的正式能力。
            arguments: 不应离开生成边界的逻辑参数。
            execution_key: 不应创建的QA幂等键。
            environment: 不应触达的执行环境。
            timeout_seconds: 不应生效的调用超时。

        Raises:
            AssertionError: 生成阶段错误访问了QA。
        """

        del arguments, execution_key, environment, timeout_seconds
        self.calls.append(capability.capability_id)
        raise AssertionError("RefundFacade#cancel generation must not invoke QA")

    def invoke_resource(
        self,
        request: FixedResourceInvocation,
        execution_key: str,
        environment: str,
        timeout_seconds: int,
    ) -> PublishedInvocationResult:
        """拒绝生成阶段触达Cleanup或其他固定QA资源。

        Args:
            request: 被错误触发的固定资源请求。
            execution_key: 不应创建的QA幂等键。
            environment: 不应触达的执行环境。
            timeout_seconds: 不应生效的调用超时。

        Raises:
            AssertionError: 生成阶段错误访问了固定QA资源。
        """

        del execution_key, environment, timeout_seconds
        self.calls.append(request.resource_id)
        raise AssertionError("RefundFacade#cancel generation must not invoke QA resources")


def _generation_business_projection(
    generation: HybridCaseGenerationRecord,
) -> dict[str, Any]:
    """移除一次发布身份后返回可比较的完整冻结业务投影。

    Args:
        generation: 一次真实正式资产生成得到的不可变记录。

    Returns:
        保留条件、Scenario、Variant、DAG、能力证明和阻塞核算的稳定字典。
    """

    # Generation自身的随机发布ID和时间不属于冻结业务决策，其余字段必须完全确定。
    return generation.model_dump(
        mode="json",
        exclude={"generation_id", "generated_at", "handoff_id"},
    )


def _operation_execution_files(knowledge_root: Path) -> set[str]:
    """列出隔离知识副本中已有的OperationExecution运行记录文件。

    Args:
        knowledge_root: 当前测试复制出的完整知识根目录。

    Returns:
        相对运行目录的JSON文件集合，包含canonical记录和请求索引。
    """

    execution_root = knowledge_root / ".opentest" / "operation-executions"
    if not execution_root.exists():
        return set()
    # 同时覆盖主记录和请求去重索引，防止只写一半运行状态仍逃过验收。
    return {
        path.relative_to(execution_root).as_posix()
        for path in execution_root.rglob("*.json")
    }


def _typed_recipe_submission(recipe: Any) -> DataSetupRecipeSubmission:
    """把已发布真实Recipe投影回必须由正式服务重新派生Schema的typed草稿。

    Args:
        recipe: current正式DataSetupRecipe。

    Returns:
        不携带派生Fact Schema、来源策略或发布修订的Agent可提交草稿。
    """

    # Fact Schema和origin必须由DataSetupRecipeService从current Published能力重新派生。
    return DataSetupRecipeSubmission(
        recipe_id=recipe.recipe_id,
        entry_id=recipe.entry_id,
        entry_source_scan_id=recipe.entry_source_scan_id,
        name=recipe.name,
        description=recipe.description,
        fixture_schema=recipe.fixture_schema,
        steps=recipe.steps,
        fact_outputs=[
            RecipeFactOutputSubmission(
                **fact.model_dump(exclude={"fact_schema", "origin_policy"})
            )
            for fact in recipe.fact_outputs
        ],
        requires_facts=recipe.requires_facts,
        acquisition_policy=recipe.acquisition_policy,
        producer_scope=recipe.producer_scope,
        producer_entry_ref=recipe.producer_entry_ref,
        knowledge_assertion_ids=recipe.knowledge_assertion_ids,
        selection_priority=recipe.selection_priority,
    )


def test_current_query_only_assets_enable_stateful_recipe_agent_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """current Query、Published、availability与输入策略足够时应通过Codex门禁。

    Args:
        monkeypatch: 隔离缺Published、Candidate、availability和输入策略的负向证明。

    Returns:
        None；Query-only闭环独立通过且任一typed输入缺失都会关闭门禁时通过。

    Side Effects:
        仅读取仓库内正式知识和Published注册表，不写资产、不访问QA或Codex。
    """

    application = OpenTestApplication(Path(__file__).parents[2] / "open-test-knowledge")
    try:
        generation = next(
            item
            for item in application.list_hybrid_case_generations(SYSTEM_ID)
            if item.entry_id == CANCEL_ENTRY_ID and item.status == "BLOCKED"
        )
        query_node = application.get_knowledge_node(
            SYSTEM_ID,
            "entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList",
        )["node"]
        query_knowledge = query_node.entry_fact_knowledge
        assert query_knowledge is not None
        query_operation = query_knowledge.candidate_operations[0]
        rules = application.setup_contract_rules.read(SYSTEM_ID)
        policies = {
            (
                policy.capability_ref.system_id,
                policy.capability_ref.capability_id,
                policy.input_path,
            ): policy
            for policy in rules.input_policies
        }
        contracts = {
            contract.fact_contract_id: contract
            for contract in rules.fact_contracts
        }
        contract = contracts["refund-order/v3"]
        evidence = CaseDraftClosureEvidence(
            policies=policies,
            contracts=contracts,
            formal_knowledge=[query_knowledge],
        )

        assert application.hybrid_case_handoffs.has_legal_stateful_recipe_draft_input(
            generation
        )
        assert application.hybrid_case_handoffs._formal_query_closes_requirement(
            query_knowledge,
            contract,
            evidence,
        )
        assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
            query_knowledge,
            contract,
            CaseDraftClosureEvidence(
                policies={},
                contracts=contracts,
                formal_knowledge=[query_knowledge],
            ),
        )
        missing_availability = query_knowledge.model_copy(
            update={
                "candidate_operations": [
                    query_operation.model_copy(update={"query_availability": None})
                ]
            }
        )
        assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
            missing_availability,
            contract,
            evidence,
        )

        def empty_published_registry(*_args: Any, **_kwargs: Any) -> PublishedCapabilityRegistry:
            """模拟Query入口没有任何Published能力。

            Args:
                *_args: list原始位置参数。
                **_kwargs: list原始命名参数。

            Returns:
                同系统但不含能力的严格Published目录。
            """

            return PublishedCapabilityRegistry(system_id=SYSTEM_ID)

        with monkeypatch.context() as scoped:
            scoped.setattr(
                application.hybrid_case_handoffs.capabilities,
                "list",
                empty_published_registry,
            )
            assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
                query_knowledge,
                contract,
                evidence,
            )

        registry = application.hybrid_case_handoffs.capabilities.list(SYSTEM_ID)
        current_query = None
        for published in registry.capabilities:
            if (
                published.candidate_ref.candidate_id
                != query_operation.candidate_operation_id
            ):
                continue
            try:
                current_query = application.hybrid_case_handoffs.capabilities.get_current(
                    SYSTEM_ID,
                    published.capability_id,
                )
            except KnowledgeValidationError:
                continue
            break
        assert current_query is not None
        incomplete_output_schema = copy.deepcopy(current_query.output_fact_schema)
        # 保留集合availability形状，只从item移除Fact身份字段以隔离门禁完整度。
        response_schema = incomplete_output_schema["properties"]["refund_order_page"]
        page_list_schema = response_schema["properties"]["pageList"]
        item_schema = page_list_schema["items"]
        item_schema["properties"].pop("refundSerialNo")
        item_schema["required"].remove("refundSerialNo")
        incomplete_query = current_query.model_copy(
            update={"output_fact_schema": incomplete_output_schema}
        )

        def return_incomplete_query(*_args: Any, **_kwargs: Any) -> Any:
            """模拟Query集合item缺少目标Fact业务身份字段。

            Args:
                *_args: get_current原始位置参数。
                **_kwargs: get_current原始命名参数。

            Returns:
                保留availability数组但缺少refundSerialNo的Published能力。
            """

            return incomplete_query

        with monkeypatch.context() as scoped:
            scoped.setattr(
                application.hybrid_case_handoffs.capabilities,
                "get_current",
                return_incomplete_query,
            )
            assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
                query_knowledge,
                contract,
                evidence,
            )

        fact_only_policies = dict(policies)
        page_policy_key = (SYSTEM_ID, current_query.capability_id, "page")
        fact_only_policies[page_policy_key] = SetupInputPolicy(
            capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id=current_query.capability_id,
            ),
            input_path="page",
            allowed_sources=["fact"],
        )
        assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
            query_knowledge,
            contract,
            CaseDraftClosureEvidence(
                policies=fact_only_policies,
                contracts=contracts,
                formal_knowledge=[query_knowledge],
            ),
        )

        wrong_literal_policies = dict(policies)
        wrong_literal_policies[page_policy_key] = SetupInputPolicy(
            capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id=current_query.capability_id,
            ),
            input_path="page",
            allowed_sources=["literal"],
            allowed_literal_values=["ONE"],
        )
        # 白名单值本身也必须满足Published输入Schema，不能仅凭存在literal策略放行。
        assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
            query_knowledge,
            contract,
            CaseDraftClosureEvidence(
                policies=wrong_literal_policies,
                contracts=contracts,
                formal_knowledge=[query_knowledge],
            ),
        )

        cancel_node = application.get_knowledge_node(
            SYSTEM_ID,
            "entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel",
        )["node"]
        cancel_knowledge = cancel_node.entry_fact_knowledge
        assert cancel_knowledge is not None
        unclosed_ticket_requirement = cancel_knowledge.requires_facts[0].model_copy(
            update={
                "assertion_id": "entry-fact:refund-query-extra-ticket-requirement",
                "slot_id": "ticket_order_dependency",
                "fact_contract_id": "ticket-order/v2",
                "required_state": "ISSUED",
                "acquisition_policy": "QUERY_ONLY",
            }
        )
        query_with_unclosed_dependency = query_knowledge.model_copy(
            update={"requires_facts": [unclosed_ticket_requirement]}
        )
        # Recipe发布要求requires与Producer正式知识精确一致，未闭合的额外前置不能被忽略。
        assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
            query_with_unclosed_dependency,
            contract,
            CaseDraftClosureEvidence(
                policies=policies,
                contracts=contracts,
                formal_knowledge=[query_with_unclosed_dependency],
            ),
        )

        def reject_current_candidate(*_args: Any, **_kwargs: Any) -> Any:
            """模拟Published引用的current Candidate或Provider Schema已经缺失。

            Args:
                *_args: get_current原始位置参数。
                **_kwargs: get_current原始命名参数。

            Raises:
                KnowledgeValidationError: 强制current重证失败。
            """

            raise KnowledgeValidationError("candidate is not current")

        monkeypatch.setattr(
            application.hybrid_case_handoffs.capabilities,
            "get_current",
            reject_current_candidate,
        )
        assert not application.hybrid_case_handoffs._formal_query_closes_requirement(
            query_knowledge,
            contract,
            evidence,
        )
    finally:
        application.close()


def test_refund_cancel_generation_is_ready_without_qa_or_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实cancel资产必须零QA、零Codex地确定性生成Query-only Case。

    Args:
        tmp_path: 保存完整正式知识副本及本次不可变Generation的隔离目录。
        monkeypatch: 把Codex线程创建替换为一旦触发即失败的边界探针。

    Returns:
        None；两次生成均稳定结束、业务投影确定且无运行时副作用时通过。

    Side Effects:
        只复制知识并在临时副本追加两个Generation；不访问QA、Codex或业务系统。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    application = OpenTestApplication(knowledge_copy)
    qa_probe = QaInvocationProbe()
    codex_calls: list[str] = []
    application.case_execution_v3.invoker = qa_probe

    def reject_codex_thread_creation(*args: Any, **kwargs: Any) -> Any:
        """拒绝公开Case生成入口创建任何Codex Case线程。

        Args:
            *args: 不应出现的Codex线程位置参数。
            **kwargs: 不应出现的Codex线程命名参数。

        Raises:
            AssertionError: 公开生成门禁错误调用了Codex。
        """

        del args, kwargs
        codex_calls.append(CANCEL_ENTRY_ID)
        raise AssertionError("RefundFacade#cancel public generation must not invoke Codex")

    monkeypatch.setattr(
        application.codex_app_server,
        "create_scoped_thread",
        reject_codex_thread_creation,
    )

    try:
        # 生成前冻结运行记录分母，证明本验收没有借历史或新增执行结果变绿。
        before_attempts = application.list_hybrid_case_attempts(SYSTEM_ID)
        before_operation_files = _operation_execution_files(knowledge_copy)
        assert before_attempts == []

        request = HybridCaseGenerationStartRequest(
            entry_id=CANCEL_ENTRY_ID,
            codex_model="gpt-5.6-sol",
            reasoning_effort="medium",
        )
        # 通过页面/API使用的公开入口生成，确保不相关Published资产不会误触发Codex。
        first_result = application.generate_hybrid_cases(SYSTEM_ID, request)
        second_result = application.generate_hybrid_cases(SYSTEM_ID, request)
        first_generation = first_result.generation
        second_generation = second_result.generation

        assert first_result.status == second_result.status == "READY"
        assert first_result.handoff is second_result.handoff is None
        assert first_generation.status == second_generation.status == "READY"
        assert first_generation.handoff_id == second_generation.handoff_id == ""
        assert len(first_generation.scenarios) == len(second_generation.scenarios) == 1
        assert len(first_generation.variants) == len(second_generation.variants) == 1
        assert first_generation.coverage_manifest.blockers == []
        assert first_generation.blockers == second_generation.blockers == []

        # cancel必须从正式知识获得唯一的可取消退票单前置条件，而不是猜测输入字段。
        stateful_conditions = [
            condition
            for condition in first_generation.coverage_manifest.conditions
            if condition.condition_type
            == CaseConditionType.STATEFUL_ENTITY_PRECONDITION
        ]
        assert len(stateful_conditions) == 1
        requirement = stateful_conditions[0].stateful_requirement
        assert requirement is not None
        assert requirement.fact_contract_id == "refund-order/v3"
        assert requirement.required_state == "CANCELLABLE"
        assert requirement.acquisition_policy == "QUERY_THEN_CREATE"
        stateful_plan = first_generation.scenarios[0].template_key.stateful_setup_plan
        assert stateful_plan is not None
        assert len(stateful_plan.nodes) == 1
        assert stateful_plan.nodes[0].acquisition_policy == "QUERY_ONLY"
        assert (
            stateful_plan.nodes[0].recipe_ref.recipe_id
            == "setup:refund-query-list-pending-apply-v3-20260828"
        )
        assert first_generation.scenarios[0].template_key.cleanup_plan_ref is not None

        # current Query Recipe必须冻结为只读、白名单literal、单条确定性提取和正式状态Fact。
        recipe = application.get_data_setup_recipe(
            SYSTEM_ID,
            "setup:refund-query-list-pending-apply-v3-20260828",
        )
        assert recipe.acquisition_policy == "QUERY_ONLY"
        assert recipe.producer_entry_ref is not None
        assert recipe.producer_entry_ref.entry_id.endswith("RefundFacade#queryList")
        assert recipe.fixture_schema == {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        query_step = recipe.steps[0]
        query_capability = application.get_published_capability(
            query_step.capability_ref.system_id,
            query_step.capability_ref.capability_id,
        )
        assert query_capability.mutability.value == "READ_ONLY"
        assert {
            input_path: binding.value
            for input_path, binding in query_step.input_bindings.items()
        } == {"page": 1, "page_size": 1, "order_state": 0}
        assert {
            binding.source for binding in query_step.input_bindings.values()
        } == {"literal"}
        assert query_step.availability is not None
        assert query_step.availability.type == "COLLECTION_NOT_EMPTY"
        assert query_step.availability.path == "refund_order_page.pageList"
        assert query_step.entity_extraction is not None
        assert query_step.entity_extraction.type == "FIRST_ITEM"
        assert query_step.entity_extraction.max_cardinality == 1
        assert recipe.fact_outputs[0].fact_contract_id == "refund-order/v3"
        assert recipe.fact_outputs[0].produced_state == "PENDING_APPLY"
        assert recipe.fact_outputs[0].constraints[0].path == "refundState"
        assert recipe.fact_outputs[0].constraints[0].expected == "PENDING_APPLY"
        rules = application.setup_contract_rules.read(SYSTEM_ID)
        query_policies = {
            policy.input_path: policy
            for policy in rules.input_policies
            if policy.capability_ref == query_step.capability_ref
        }
        assert set(query_policies) == {"page", "page_size", "order_state"}
        assert all(
            policy.allowed_sources == ["literal"]
            and not policy.business_identity
            and not policy.controlled_test_scope
            for policy in query_policies.values()
        )
        assert query_policies["page"].allowed_literal_values == [1]
        assert query_policies["page_size"].allowed_literal_values == [1]
        assert query_policies["order_state"].allowed_literal_values == [0]

        # 正式知识保留查询、未来创建增强和Action绑定，当前闭环不要求用户提供业务ID。
        cancel_node = application.get_knowledge_node(
            SYSTEM_ID,
            "entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel",
        )["node"]
        cancel_knowledge = cancel_node.entry_fact_knowledge
        assert cancel_knowledge is not None
        assert [binding.request_path for binding in cancel_knowledge.binding_paths] == [
            "refund_serial_no"
        ]
        assert [binding.fact_path for binding in cancel_knowledge.binding_paths] == [
            "refundSerialNo"
        ]

        create_node = application.get_knowledge_node(
            SYSTEM_ID,
            "entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder",
        )["node"]
        create_knowledge = create_node.entry_fact_knowledge
        assert create_knowledge is not None
        assert create_knowledge.requires_facts == []
        assert [fact.produced_state for fact in create_knowledge.produces_facts] == [
            "PENDING_APPLY"
        ]
        assert {
            operation.operation_role for operation in create_knowledge.candidate_operations
        } == {"CREATE"}

        query_node = application.get_knowledge_node(
            SYSTEM_ID,
            "entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList",
        )["node"]
        query_knowledge = query_node.entry_fact_knowledge
        assert query_knowledge is not None
        query_operation = query_knowledge.candidate_operations[0]
        assert query_operation.operation_role == "QUERY"
        assert query_operation.query_availability is not None
        assert query_operation.query_availability.type == "COLLECTION_NOT_EMPTY"
        assert query_operation.query_availability.path == "refund_order_page.pageList"

        # 内部错误响应和框架影响只能作为诊断，不得扩大业务阻塞或强制AI解释。
        assert all(
            condition.condition_type
            in {
                CaseConditionType.INTERNAL_DIAGNOSTIC,
                CaseConditionType.STATEFUL_ENTITY_PRECONDITION,
            }
            for condition in first_generation.coverage_manifest.conditions
        )
        assert all(
            not condition.blocks_generation
            for condition in first_generation.coverage_manifest.conditions
            if condition.condition_type == CaseConditionType.INTERNAL_DIAGNOSTIC
        )

        # 同一正式输入重复生成必须得到完全相同的冻结业务决策。
        assert _generation_business_projection(first_generation) == (
            _generation_business_projection(second_generation)
        )
        assert application.list_hybrid_case_attempts(SYSTEM_ID) == before_attempts
        assert _operation_execution_files(knowledge_copy) == before_operation_files
        assert qa_probe.calls == []
        assert codex_calls == []
    finally:
        application.close()


def test_refund_cancel_missing_recipe_reuses_one_frozen_codex_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无Recipe时首次进入Codex，重复请求复用线程并冻结首次模型。

    Args:
        tmp_path: 保存移除正式Recipe后的完整隔离知识副本。
        monkeypatch: 替换Codex线程创建和turn启动，记录但不调用真实Codex。

    Returns:
        None；WAITING、同handoff/thread、单次create_thread和缺策略友好阻塞均通过。

    Side Effects:
        只在临时副本写Generation、handoff、任务和规则；不访问QA或Codex。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    recipe_path = (
        knowledge_copy
        / "systems"
        / SYSTEM_ID
        / "recipes"
        / "setup"
        / "setup--refund-query-list-pending-apply-v3-20260828.yaml"
    )
    recipe_path.unlink()
    handoff_root = knowledge_copy / ".opentest" / "case-generation-handoffs"
    if handoff_root.exists():
        # 隔离环境不能继承仓库本机历史handoff，否则无法证明本次find-or-create行为。
        shutil.rmtree(handoff_root)
    application = OpenTestApplication(knowledge_copy)
    create_calls: list[tuple[str, str]] = []
    formal_recipe = OpenTestApplication(project_root / "open-test-knowledge")
    try:
        recipe = formal_recipe.get_data_setup_recipe(
            SYSTEM_ID,
            "setup:refund-query-list-pending-apply-v3-20260828",
        )
    finally:
        formal_recipe.close()

    def create_fake_thread(
        request: CodexThreadCreationRequest,
    ) -> CodexClientThread:
        """记录一次Case线程创建并返回稳定本地线程身份。

        Args:
            request: 包含首次冻结模型、档位和Case-only机器工具范围的线程请求。

        Returns:
            不启动外部进程的固定Codex线程引用。

        Side Effects:
            仅向内存调用记录追加一次模型组合。
        """

        assert request.tool_scope == "case_only"
        create_calls.append((request.model, request.reasoning_effort))
        return CodexClientThread(
            thread_id="thread-refund-query-recipe",
            deep_link="codex://threads/thread-refund-query-recipe",
        )

    def do_not_start_turn(_handoff: Any) -> None:
        """阻止验收测试向假的Codex线程发送turn。

        Args:
            _handoff: 已完整绑定任务和线程的Case handoff。

        Returns:
            None；handoff保持WAITING供重复请求复用。
        """

    monkeypatch.setattr(
        application.codex_app_server,
        "create_scoped_thread",
        create_fake_thread,
    )
    monkeypatch.setattr(
        application,
        "_start_case_generation_turn_safely",
        do_not_start_turn,
    )

    try:
        first = application.generate_hybrid_cases(
            SYSTEM_ID,
            HybridCaseGenerationStartRequest(
                entry_id=CANCEL_ENTRY_ID,
                codex_model="gpt-5.6-luna",
                reasoning_effort="low",
            ),
        )
        second = application.generate_hybrid_cases(
            SYSTEM_ID,
            HybridCaseGenerationStartRequest(
                entry_id=CANCEL_ENTRY_ID,
                codex_model="gpt-5.6-sol",
                reasoning_effort="medium",
            ),
        )

        assert first.status == second.status == "WAITING_FOR_AGENT"
        assert first.handoff is not None and second.handoff is not None
        assert first.handoff.handoff_id == second.handoff.handoff_id
        assert first.handoff.thread_id == second.handoff.thread_id
        assert second.handoff.codex_model == "gpt-5.6-luna"
        assert second.handoff.reasoning_effort == "low"
        assert len(second.handoff.generation_ids) == 2
        assert create_calls == [("gpt-5.6-luna", "low")]

        current_rules = application.setup_contract_rules.read(SYSTEM_ID)
        application.setup_contract_rules.write(
            SetupContractRuleSet(
                system_id=SYSTEM_ID,
                fact_contracts=current_rules.fact_contracts,
                input_policies=[],
            )
        )
        missing_policy = application.generate_hybrid_cases(
            SYSTEM_ID,
            HybridCaseGenerationStartRequest(entry_id=CANCEL_ENTRY_ID),
        )
        assert missing_policy.status == "BLOCKED"
        assert missing_policy.handoff is None
        assert create_calls == [("gpt-5.6-luna", "low")]
        application.setup_contract_rules.write(current_rules)

        # Codex只能提交typed Draft；正式服务重验current资产并发布后，新Generation必须直接READY。
        recipe_submission = _typed_recipe_submission(recipe)
        publication = application.publish_data_setup_recipe(
            SYSTEM_ID,
            recipe_submission,
        )
        assert publication.status == "PUBLISHED"
        regenerated = application.generate_hybrid_cases(
            SYSTEM_ID,
            HybridCaseGenerationStartRequest(
                entry_id=CANCEL_ENTRY_ID,
                codex_model="gpt-5.6-sol",
                reasoning_effort="medium",
            ),
        )
        assert regenerated.status == "READY"
        assert regenerated.handoff is None
        assert len(regenerated.generation.scenarios) == 1
        assert len(regenerated.generation.variants) == 1
        assert regenerated.generation.blockers == []
        regenerated_requirement = next(
            condition.stateful_requirement
            for condition in regenerated.generation.coverage_manifest.conditions
            if condition.condition_type
            == CaseConditionType.STATEFUL_ENTITY_PRECONDITION
        )
        assert regenerated_requirement is not None
        assert regenerated_requirement.acquisition_policy == "QUERY_THEN_CREATE"
        regenerated_plan = (
            regenerated.generation.scenarios[0].template_key.stateful_setup_plan
        )
        assert regenerated_plan is not None
        assert regenerated_plan.nodes[0].acquisition_policy == "QUERY_ONLY"
        assert create_calls == [("gpt-5.6-luna", "low")]
    finally:
        application.close()


def test_case_handoff_find_or_create_covers_thread_unbound_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并发请求必须跨越handoff已写入但thread未绑定的窗口原子复用。

    Args:
        tmp_path: 保存正式知识和私有handoff的隔离副本。
        monkeypatch: 固定BLOCKED Generation并暂停首次thread创建以暴露竞态窗口。

    Returns:
        None；两个请求返回同一handoff/thread且create_thread只调用一次时通过。

    Side Effects:
        只在临时副本写一个handoff和任务；不访问QA或真实Codex。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    handoff_root = knowledge_copy / ".opentest" / "case-generation-handoffs"
    if handoff_root.exists():
        shutil.rmtree(handoff_root)
    application = OpenTestApplication(knowledge_copy)
    blocked_generation = next(
        item
        for item in application.list_hybrid_case_generations(SYSTEM_ID)
        if item.entry_id == CANCEL_ENTRY_ID and item.status == "BLOCKED"
    )
    create_entered = threading.Event()
    release_create = threading.Event()
    create_calls: list[tuple[str, str]] = []

    def reuse_blocked_generation(
        requested_system_id: str,
        request: Any,
    ) -> HybridCaseGenerationRecord:
        """让两个线程立即得到相同冻结作用域的BLOCKED Generation。

        Args:
            requested_system_id: 两个请求都必须保持正式退款系统。
            request: 底层确定性entry-only请求。

        Returns:
            已有历史BLOCKED记录，用于隔离find-or-create竞态本身。
        """

        assert requested_system_id == SYSTEM_ID
        assert request.entry_id == CANCEL_ENTRY_ID
        return blocked_generation

    def accept_agent_handoff(_generation: HybridCaseGenerationRecord) -> bool:
        """把测试范围固定在已由其他用例证明的合法AI门禁之后。

        Args:
            _generation: 相同冻结作用域的历史BLOCKED Generation。

        Returns:
            True，使两个请求都进入原子find-or-create区域。
        """

        return True

    def omit_provider_catalog(_provider_system_id: str) -> Any:
        """跳过与并发所有权无关的上游Candidate目录构建。

        Args:
            _provider_system_id: handoff冻结时枚举到的provider系统。

        Raises:
            KnowledgeValidationError: 按生产降级语义保留provider范围但不附目录快照。
        """

        raise KnowledgeValidationError("provider catalog omitted by concurrency boundary")

    def create_paused_thread(
        request: CodexThreadCreationRequest,
    ) -> CodexClientThread:
        """在首次handoff落盘后暂停，显式打开thread尚未绑定的竞态窗口。

        Args:
            request: 首次请求冻结模型、档位和Case-only机器工具范围。

        Returns:
            释放窗口后返回的固定本地线程引用。

        Side Effects:
            通知主测试窗口已经打开，并等待显式释放；不调用Codex。
        """

        assert request.tool_scope == "case_only"
        create_calls.append((request.model, request.reasoning_effort))
        create_entered.set()
        assert release_create.wait(timeout=30)
        return CodexClientThread(
            thread_id="thread-atomic-refund-recipe",
            deep_link="codex://threads/thread-atomic-refund-recipe",
        )

    def do_not_start_turn(_handoff: Any) -> None:
        """阻止绑定完成后的测试handoff启动真实Codex turn。

        Args:
            _handoff: 已完成线程绑定的首次handoff。

        Returns:
            None；测试仅验证find-or-create边界。
        """

    monkeypatch.setattr(
        application.hybrid_case_generation,
        "generate",
        reuse_blocked_generation,
    )
    monkeypatch.setattr(
        application,
        "_case_generation_handoff_needed",
        accept_agent_handoff,
    )
    monkeypatch.setattr(
        application.hybrid_case_handoffs.capabilities.candidates,
        "catalog",
        omit_provider_catalog,
    )
    monkeypatch.setattr(
        application.codex_app_server,
        "create_scoped_thread",
        create_paused_thread,
    )
    monkeypatch.setattr(
        application,
        "_start_case_generation_turn_safely",
        do_not_start_turn,
    )

    try:
        first_request = HybridCaseGenerationStartRequest(
            entry_id=CANCEL_ENTRY_ID,
            codex_model="gpt-5.6-luna",
            reasoning_effort="medium",
        )
        second_request = HybridCaseGenerationStartRequest(
            entry_id=CANCEL_ENTRY_ID,
            codex_model="gpt-5.6-sol",
            reasoning_effort="low",
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                application.generate_hybrid_cases,
                SYSTEM_ID,
                first_request,
            )
            assert create_entered.wait(timeout=30)
            second_future = executor.submit(
                application.generate_hybrid_cases,
                SYSTEM_ID,
                second_request,
            )
            # 第二个请求必须等首个线程绑定完成，不能观察并修补半成品handoff。
            time.sleep(0.1)
            assert not second_future.done()
            release_create.set()
            first = first_future.result(timeout=30)
            second = second_future.result(timeout=30)

        assert first.handoff is not None and second.handoff is not None
        assert first.handoff.handoff_id == second.handoff.handoff_id
        assert first.handoff.thread_id == second.handoff.thread_id
        assert second.handoff.codex_model == "gpt-5.6-luna"
        assert second.handoff.reasoning_effort == "medium"
        assert create_calls == [("gpt-5.6-luna", "medium")]
    finally:
        release_create.set()
        application.close()


def test_case_handoff_repeat_during_validation_does_not_change_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """草稿校验期间重复generate必须只读复用线程且不破坏最终READY写入。

    Args:
        tmp_path: 保存移除正式Recipe后的完整隔离知识副本。
        monkeypatch: 暂停真实Recipe发布并替换Codex线程边界。

    Returns:
        None；重复请求返回同一活动线程且原提交最终READY时通过。

    Side Effects:
        只在临时副本发布真实typed Recipe并写Generation/handoff，不访问QA或Codex。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    recipe_path = (
        knowledge_copy
        / "systems"
        / SYSTEM_ID
        / "recipes"
        / "setup"
        / "setup--refund-query-list-pending-apply-v3-20260828.yaml"
    )
    recipe_path.unlink()
    handoff_root = knowledge_copy / ".opentest" / "case-generation-handoffs"
    if handoff_root.exists():
        shutil.rmtree(handoff_root)
    application = OpenTestApplication(knowledge_copy)
    formal_application = OpenTestApplication(project_root / "open-test-knowledge")
    publish_entered = threading.Event()
    release_publish = threading.Event()
    create_calls: list[tuple[str, str]] = []
    ready_generation = next(
        item
        for item in application.list_hybrid_case_generations(SYSTEM_ID)
        if item.entry_id == CANCEL_ENTRY_ID and item.status == "READY"
    )
    try:
        recipe = formal_application.get_data_setup_recipe(
            SYSTEM_ID,
            "setup:refund-query-list-pending-apply-v3-20260828",
        )
    finally:
        formal_application.close()

    def create_fake_thread(
        request: CodexThreadCreationRequest,
    ) -> CodexClientThread:
        """记录首次模型并返回不启动真实Codex的固定线程。

        Args:
            request: 首次请求冻结模型、档位和Case-only机器工具范围。

        Returns:
            固定本地线程引用。

        Side Effects:
            只追加一次内存调用记录。
        """

        assert request.tool_scope == "case_only"
        create_calls.append((request.model, request.reasoning_effort))
        return CodexClientThread(
            thread_id="thread-validating-refund-recipe",
            deep_link="codex://threads/thread-validating-refund-recipe",
        )

    def do_not_start_turn(_handoff: Any) -> None:
        """阻止测试handoff向固定线程发送真实Codex turn。

        Args:
            _handoff: 已绑定任务和固定线程的handoff。

        Returns:
            None；测试直接提交typed Draft。
        """

    def keep_frozen_source_current(
        _handoff: Any,
        _submitted_scan_id: str,
    ) -> None:
        """隔离VALIDATING revision竞态时跳过已由独立测试覆盖的provider重证。

        Args:
            _handoff: 本测试刚创建且未发生源码变更的冻结handoff。
            _submitted_scan_id: typed Bundle提交的同一source scan身份。

        Returns:
            None，表示consumer/provider源码范围仍为current。
        """

        return None

    original_publish_stage = application.hybrid_case_handoffs._publish_recipes

    def pause_recipe_publish_stage(
        handoff: Any,
        bundle: CaseGenerationDraftBundle,
        accepted: list[str],
        issues: list[Any],
    ) -> None:
        """在Recipe发布阶段入口暂停以暴露VALIDATING重复请求窗口。

        Args:
            handoff: 已进入VALIDATING的冻结Case接管。
            bundle: 包含真实Query Recipe草稿的typed Bundle。
            accepted: 正式服务成功发布的资产身份累加器。
            issues: 正式服务拒绝草稿时的问题累加器。

        Returns:
            None；释放窗口后继续原始发布阶段。

        Side Effects:
            通知测试线程后等待显式释放，随后写临时正式Recipe资产。
        """

        publish_entered.set()
        assert release_publish.wait(timeout=60)
        original_publish_stage(handoff, bundle, accepted, issues)

    def return_ready_after_real_publication(
        system_id: str,
        request: Any,
        handoff_id: str = "",
    ) -> HybridCaseGenerationRecord:
        """隔离并发测试的重编译耗时，同时确认真实Recipe已经由正式服务发布。

        Args:
            system_id: 必须保持正式退款系统。
            request: 必须保持底层entry-only确定性请求。
            handoff_id: 恢复结果必须关联正在校验的同一handoff。

        Returns:
            复用已独立验收业务内容的READY投影并替换本轮不可变身份。

        Side Effects:
            读取刚发布的真实Recipe；不写Attempt、不访问QA或Codex。
        """

        assert system_id == SYSTEM_ID
        assert request.entry_id == CANCEL_ENTRY_ID
        published_recipe = application.get_data_setup_recipe(
            SYSTEM_ID,
            "setup:refund-query-list-pending-apply-v3-20260828",
        )
        assert published_recipe.acquisition_policy == "QUERY_ONLY"
        return ready_generation.model_copy(
            update={
                "generation_id": "hybrid-generation-ffffffffffffffffffff",
                "handoff_id": handoff_id,
                "generated_at": utc_now(),
            }
        )

    monkeypatch.setattr(
        application.codex_app_server,
        "create_scoped_thread",
        create_fake_thread,
    )
    monkeypatch.setattr(application, "_start_case_generation_turn_safely", do_not_start_turn)
    monkeypatch.setattr(
        application.hybrid_case_handoffs,
        "_source_stale",
        keep_frozen_source_current,
    )
    monkeypatch.setattr(
        application.hybrid_case_handoffs,
        "_publish_recipes",
        pause_recipe_publish_stage,
    )

    try:
        first = application.generate_hybrid_cases(
            SYSTEM_ID,
            HybridCaseGenerationStartRequest(entry_id=CANCEL_ENTRY_ID),
        )
        assert first.handoff is not None
        bundle = CaseGenerationDraftBundle(
            source_scan_id=first.handoff.source_scan_id,
            setup_recipe_drafts=[_typed_recipe_submission(recipe)],
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            submit_future = executor.submit(
                application.hybrid_case_handoffs.submit,
                first.handoff.handoff_id,
                bundle,
            )
            assert publish_entered.wait(timeout=10)
            repeated = application.generate_hybrid_cases(
                SYSTEM_ID,
                HybridCaseGenerationStartRequest(
                    entry_id=CANCEL_ENTRY_ID,
                    codex_model="gpt-5.6-sol",
                    reasoning_effort="medium",
                ),
            )
            assert repeated.status == "WAITING_FOR_AGENT"
            assert repeated.handoff is not None
            assert repeated.handoff.handoff_id == first.handoff.handoff_id
            assert repeated.handoff.thread_id == first.handoff.thread_id
            workspace_entry = application.get_case_workspace_entry_detail(
                SYSTEM_ID,
                CANCEL_ENTRY_ID,
            ).entry
            assert workspace_entry.generation_progress is not None
            assert workspace_entry.generation_progress.phase == "VALIDATING"
            assert workspace_entry.generation_progress.codex_model == "gpt-5.6-luna"
            assert workspace_entry.generation_progress.reasoning_effort == "low"
            monkeypatch.setattr(
                application.hybrid_case_handoffs.generator,
                "generate",
                return_ready_after_real_publication,
            )
            release_publish.set()
            submitted = submit_future.result(timeout=30)

        final_handoff = application.hybrid_case_handoffs.get(first.handoff.handoff_id)
        assert submitted.status == "ACCEPTED"
        assert submitted.generation is not None
        assert submitted.generation.status == "READY"
        assert final_handoff.status.value == "ready"
        assert create_calls == [("gpt-5.6-luna", "low")]
    finally:
        release_publish.set()
        application.close()


def test_case_handoff_thread_failure_is_terminal_before_creation_lock_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """线程创建失败必须在原子窗口内终结且并发等待者不能创建第二线程。

    Args:
        tmp_path: 保存正式知识和私有handoff的隔离副本。
        monkeypatch: 固定合法BLOCKED Generation并暂停后拒绝首次thread创建。

    Returns:
        None；并发请求均看到FAILED，之后新请求才可创建新handoff时通过。

    Side Effects:
        只在临时副本写FAILED/WAITING handoff和任务，不调用真实Codex或QA。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    handoff_root = knowledge_copy / ".opentest" / "case-generation-handoffs"
    if handoff_root.exists():
        shutil.rmtree(handoff_root)
    application = OpenTestApplication(knowledge_copy)
    blocked_generation = next(
        item
        for item in application.list_hybrid_case_generations(SYSTEM_ID)
        if item.entry_id == CANCEL_ENTRY_ID and item.status == "BLOCKED"
    )
    create_entered = threading.Event()
    release_create = threading.Event()
    generation_lock = threading.Lock()
    generation_count = 0
    create_calls: list[tuple[str, str]] = []

    def create_fresh_blocked_generation(
        requested_system_id: str,
        request: Any,
    ) -> HybridCaseGenerationRecord:
        """为每个并发请求返回同作用域但有独立时间和身份的BLOCKED Generation。

        Args:
            requested_system_id: 必须保持正式退款系统。
            request: 底层确定性entry-only请求。

        Returns:
            可用generated_at区分历史失败与当前并发窗口的不可变记录。

        Side Effects:
            仅在内存锁内递增测试Generation序号。
        """

        nonlocal generation_count
        assert requested_system_id == SYSTEM_ID
        assert request.entry_id == CANCEL_ENTRY_ID
        with generation_lock:
            generation_count += 1
            sequence = generation_count
        return blocked_generation.model_copy(
            update={
                "generation_id": f"hybrid-generation-{sequence:020x}",
                "generated_at": utc_now(),
            }
        )

    def accept_agent_handoff(_generation: HybridCaseGenerationRecord) -> bool:
        """把测试范围固定在线程原子创建失败边界。

        Args:
            _generation: 本轮新建的合法BLOCKED Generation。

        Returns:
            True，使请求进入find-or-create流程。
        """

        return True

    def omit_provider_catalog(_provider_system_id: str) -> Any:
        """跳过与线程失败窗口无关的provider Candidate目录构建。

        Args:
            _provider_system_id: handoff冻结时枚举到的provider系统。

        Raises:
            KnowledgeValidationError: 按生产降级语义保留provider但不附目录快照。
        """

        raise KnowledgeValidationError("provider catalog omitted by failure boundary")

    def create_paused_failure(
        request: CodexThreadCreationRequest,
    ) -> CodexClientThread:
        """暂停首次thread创建后抛出受控ExecutionFailure。

        Args:
            request: 首次请求冻结模型、档位和Case-only机器工具范围。

        Raises:
            ExecutionFailure: 释放并发窗口后模拟Codex App建线程失败。

        Side Effects:
            记录一次调用并等待测试线程显式释放。
        """

        assert request.tool_scope == "case_only"
        create_calls.append((request.model, request.reasoning_effort))
        create_entered.set()
        assert release_create.wait(timeout=10)
        raise ExecutionFailure("Codex App thread creation failed")

    def create_recovery_thread(
        request: CodexThreadCreationRequest,
    ) -> CodexClientThread:
        """为失败窗口结束后的新请求返回新的固定线程。

        Args:
            request: 新请求冻结模型、档位和Case-only机器工具范围。

        Returns:
            与FAILED handoff不同的新线程引用。

        Side Effects:
            追加第二次且非并发窗口内的内存调用记录。
        """

        assert request.tool_scope == "case_only"
        create_calls.append((request.model, request.reasoning_effort))
        return CodexClientThread(
            thread_id="thread-after-failed-window",
            deep_link="codex://threads/thread-after-failed-window",
        )

    def do_not_start_turn(_handoff: Any) -> None:
        """阻止恢复请求向固定线程发送真实Codex turn。

        Args:
            _handoff: 已绑定恢复线程的handoff。

        Returns:
            None；测试只观察所有权和终态边界。
        """

    monkeypatch.setattr(
        application.hybrid_case_generation,
        "generate",
        create_fresh_blocked_generation,
    )
    monkeypatch.setattr(application, "_case_generation_handoff_needed", accept_agent_handoff)
    monkeypatch.setattr(
        application.hybrid_case_handoffs.capabilities.candidates,
        "catalog",
        omit_provider_catalog,
    )
    monkeypatch.setattr(
        application.codex_app_server,
        "create_scoped_thread",
        create_paused_failure,
    )
    monkeypatch.setattr(application, "_start_case_generation_turn_safely", do_not_start_turn)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                application.generate_hybrid_cases,
                SYSTEM_ID,
                HybridCaseGenerationStartRequest(entry_id=CANCEL_ENTRY_ID),
            )
            assert create_entered.wait(timeout=10)
            second_future = executor.submit(
                application.generate_hybrid_cases,
                SYSTEM_ID,
                HybridCaseGenerationStartRequest(
                    entry_id=CANCEL_ENTRY_ID,
                    codex_model="gpt-5.6-sol",
                    reasoning_effort="medium",
                ),
            )
            time.sleep(0.1)
            assert not second_future.done()
            release_create.set()
            first = first_future.result(timeout=30)
            second = second_future.result(timeout=30)

        assert first.status == second.status == "BLOCKED"
        assert first.handoff is not None and second.handoff is not None
        assert first.handoff.handoff_id == second.handoff.handoff_id
        assert first.handoff.status.value == second.handoff.status.value == "failed"
        assert first.handoff.thread_id == second.handoff.thread_id == ""
        assert create_calls == [("gpt-5.6-luna", "low")]

        # 失败窗口结束后生成时间晚于FAILED终态，因此必须创建新的活动handoff而非复用终态。
        monkeypatch.setattr(
            application.codex_app_server,
            "create_scoped_thread",
            create_recovery_thread,
        )
        recovered = application.generate_hybrid_cases(
            SYSTEM_ID,
            HybridCaseGenerationStartRequest(
                entry_id=CANCEL_ENTRY_ID,
                codex_model="gpt-5.6-sol",
                reasoning_effort="medium",
            ),
        )
        assert recovered.status == "WAITING_FOR_AGENT"
        assert recovered.handoff is not None
        assert recovered.handoff.handoff_id != first.handoff.handoff_id
        assert create_calls == [
            ("gpt-5.6-luna", "low"),
            ("gpt-5.6-sol", "medium"),
        ]
    finally:
        release_create.set()
        application.close()
