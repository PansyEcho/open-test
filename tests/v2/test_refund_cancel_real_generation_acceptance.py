"""验证真实退款资产可在零QA、零Codex条件下确定性生成cancel Case。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from opentest.application.case_execution_v3 import (
    FixedResourceInvocation,
    PublishedInvocationResult,
)
from opentest.application.foundation import OpenTestApplication
from opentest.domain.models import (
    CaseConditionType,
    EntryFactAssertion,
    EntryFactKnowledge,
    HybridCaseGenerationRecord,
    HybridCaseGenerationRequest,
    KnowledgeConclusionSource,
    ProducerEntrySourceRef,
    PublishedOperationCapability,
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


def test_complete_current_query_create_knowledge_enables_stateful_recipe_agent_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """完整Query/Create及创建输入Fact绑定必须通过状态实体Codex正向门禁。

    Args:
        monkeypatch: 仅为createOrder正式知识补入未来Booking确认后应有的typed断言。

    Returns:
        None；current Candidate ID可映射查询入口且完整创建输入使门禁为True时通过。

    Side Effects:
        仅读取仓库内正式知识和Published注册表，不写资产、不访问QA或Codex。
    """

    application = OpenTestApplication(Path(__file__).parents[2] / "open-test-knowledge")
    try:
        generation = next(
            item
            for item in application.list_hybrid_case_generations(SYSTEM_ID)
            if item.entry_id == CANCEL_ENTRY_ID
        )
        create_node = application.get_knowledge_node(
            SYSTEM_ID,
            "entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder",
        )["node"]
        query_node = application.get_knowledge_node(
            SYSTEM_ID,
            "entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList",
        )["node"]
        create_knowledge = create_node.entry_fact_knowledge
        query_knowledge = query_node.entry_fact_knowledge
        assert create_knowledge is not None
        assert query_knowledge is not None

        # 模拟Booking正式知识确认后的最小typed输入，不把该尚未证明的事实写入真实知识库。
        ticket_requirement = EntryFactAssertion(
            assertion_id="entry-fact:test-create-requires-issued-ticket",
            assertion_type="REQUIRES_FACT",
            slot_id="ticket_order",
            fact_contract_id="ticket-order/v2",
            required_state="ISSUED",
            acquisition_policy="QUERY_ONLY",
            source=KnowledgeConclusionSource.KNOWLEDGE_CONFIRMED,
            confirmed_assertion_id="entry-fact:test-booking-issued-ticket-formal",
        )
        ticket_binding = EntryFactAssertion(
            assertion_id="entry-fact:test-create-binds-ticket-order",
            assertion_type="BINDING_PATH",
            slot_id="ticket_order",
            fact_contract_id="ticket-order/v2",
            request_path="refund_detail.orderRefundInfo.orderSerialNo",
            fact_path="orderSerialNo",
            source=KnowledgeConclusionSource.KNOWLEDGE_CONFIRMED,
            confirmed_assertion_id="entry-fact:test-booking-issued-ticket-binding",
        )
        completed_create_knowledge = create_knowledge.model_copy(
            update={
                "requires_facts": [ticket_requirement],
                "binding_paths": [ticket_binding],
            }
        )

        def project_completed_formal_knowledge(
            entries: list[ProducerEntrySourceRef],
        ) -> list[EntryFactKnowledge]:
            """返回不落盘的完整Query/Create正式知识投影。

            Args:
                entries: 已由current Fact和Published映射筛出的Producer入口。

            Returns:
                包含查询及创建输入闭合证明的两个Entry Fact知识对象。
            """

            assert any(entry.entry_id.endswith("#queryList") for entry in entries)
            return [query_knowledge, completed_create_knowledge]

        monkeypatch.setattr(
            application.hybrid_case_handoffs,
            "_formal_knowledge_for_entries",
            project_completed_formal_knowledge,
        )

        assert application.hybrid_case_handoffs.has_legal_stateful_recipe_draft_input(
            generation
        )
    finally:
        application.close()


def test_refund_cancel_generation_finishes_with_one_truthful_recipe_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实cancel资产必须零QA、零Codex地结束生成并准确说明Recipe断点。

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
        "create_thread",
        reject_codex_thread_creation,
    )

    try:
        # 生成前冻结运行记录分母，证明本验收没有借历史或新增执行结果变绿。
        before_attempts = application.list_hybrid_case_attempts(SYSTEM_ID)
        before_operation_files = _operation_execution_files(knowledge_copy)
        assert before_attempts == []

        request = HybridCaseGenerationRequest(entry_id=CANCEL_ENTRY_ID)
        # 通过页面/API使用的公开入口生成，确保不相关Published资产不会误触发Codex。
        first_result = application.generate_hybrid_cases(SYSTEM_ID, request)
        second_result = application.generate_hybrid_cases(SYSTEM_ID, request)
        first_generation = first_result.generation
        second_generation = second_result.generation

        assert first_result.status == second_result.status == "BLOCKED"
        assert first_result.handoff is second_result.handoff is None
        assert first_generation.status == second_generation.status == "BLOCKED"
        assert first_generation.handoff_id == second_generation.handoff_id == ""
        assert first_generation.scenarios == second_generation.scenarios == []
        assert first_generation.variants == second_generation.variants == []
        assert first_generation.coverage_manifest.blockers == []
        assert len(first_generation.blockers) == len(second_generation.blockers) == 1
        assert {
            blocker.code for blocker in first_generation.blockers
        } == {"BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED"}

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

        # 正式知识必须已经包含查询、创建产出和Action绑定；缺的是完整Recipe而非用户业务ID。
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
