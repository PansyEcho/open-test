"""Validate that the Case workspace is derived from real scan and knowledge truth."""

from __future__ import annotations

import shutil
from urllib.parse import quote
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.case_execution_v3 import (
    CaseExecutionContext,
    _ExpectedAttemptEvidence,
)
from opentest.application.foundation import OpenTestApplication
from opentest.domain.models import (
    AttemptFailureSummary,
    CaseCondition,
    CaseConditionType,
    CaseGenerationHandoff,
    CaseGenerationHandoffStatus,
    CaseKnowledgeEntry,
    CaseWorkspaceBlocker,
    CleanupBusinessIdentityRef,
    CleanupOracleDefinition,
    CleanupPlan,
    EntryPoint,
    ExecutionAttempt,
    ExecutionStepEvidence,
    FactorObligation,
    FaultCapabilityKind,
    FaultExpectedEntityStates,
    FrozenCoverageManifest,
    HybridCaseGenerationRecord,
    HybridCaseGenerationRequest,
    HybridGenerationBlocker,
    KnowledgeNodeKind,
    OperationExecutionRecord,
    OperationExecutionStatus,
    OperationMutability,
    OracleAssertionTemplate,
    OracleEffectObservationTemplate,
    OracleExpression,
    OracleTemplate,
    PublishedCapabilityRef,
    DataSetupRecipeRef,
    ScanManifest,
    SourceBaseline,
    SetupFactInputRef,
    StatefulAcquisitionPlan,
    StatefulAcquisitionPlanNode,
    StatefulEntityRequirement,
)
from opentest.domain.errors import KnowledgeValidationError
from test_typed_case_compiler_phase5 import (
    ENTRY_ID as GENERIC_ENTRY_ID,
    SYSTEM_ID as GENERIC_SYSTEM_ID,
    _compiler_harness,
    _obligation_base,
)


PROJECT_ROOT = Path(__file__).parents[2]
REAL_KNOWLEDGE_ROOT = PROJECT_ROOT / "open-test-knowledge"
REAL_SYSTEM_ID = "ifightchainsaas.java.refund.core"
REAL_REFUND_METHODS = {"RefundFacade#cancel", "RefundFacade#createOrder", "RefundFacade#refundReshopSubmit"}


def test_real_case_workspace_lists_all_current_scan_entries_as_neutral_when_ungenerated() -> None:
    """真实工作台应展示latest入口且把尚未生成保持为中性生命周期。

    Returns:
        None；真实latest scan、知识目录和工作台入口完全一致时通过。

    Side Effects:
        仅读取仓库内真实知识和忽略的本地派生状态，不访问QA。
    """

    application = OpenTestApplication(REAL_KNOWLEDGE_ROOT)
    try:
        workspace = application.get_case_workspace(REAL_SYSTEM_ID)
        display_names = {entry.display_name for entry in workspace.entries}
        manifest_entry_ids = {
            entry.entry_id
            for entry in application.source_analysis.artifacts.read(REAL_SYSTEM_ID, "latest").entries
        }

        assert REAL_REFUND_METHODS.issubset(display_names)
        assert "TradeOrderSyncMessageListener" not in display_names
        assert {entry.entry_id for entry in workspace.entries}.issubset(manifest_entry_ids)
        ungenerated_entries = [
            entry
            for entry in workspace.entries
            if entry.generation_lifecycle == "NOT_GENERATED"
        ]
        assert ungenerated_entries
        assert all(entry.user_status.technical_code == "" for entry in ungenerated_entries)
        assert all(
            {
                "published_capability_count",
                "setup_recipe_count",
                "cleanup_plan_count",
                "attempt_count",
                "pipeline_stage",
                "pipeline_status",
            }.isdisjoint(entry.model_dump(mode="json"))
            for entry in workspace.entries
        )
        create_order_entry = next(
            entry for entry in workspace.entries if entry.display_name == "RefundFacade#createOrder"
        )
        # 正式知识已通过程序证明，但尚未请求Generation仍是中性生命周期。
        assert create_order_entry.generation_lifecycle == "NOT_GENERATED"
        assert create_order_entry.readiness_status == "NOT_EVALUATED"
        assert create_order_entry.user_status.display_status == "未生成"
        assert create_order_entry.generation_progress is None
        create_order_detail = application.get_case_workspace_entry_detail(
            REAL_SYSTEM_ID,
            create_order_entry.entry_id,
        )
        assert create_order_detail.technical_details["semantic_gaps"] == []
        assert create_order_detail.technical_details["pipeline_steps"] == []
        assert (
            create_order_detail.technical_details["published_capability_count"],
            create_order_detail.technical_details["setup_recipe_count"],
            create_order_detail.technical_details["cleanup_plan_count"],
        ) == (1, 0, 0)
        # 旧`entry:<source_id>`生成必须只读挂回规范Facade入口，不能因ID升级从页面消失。
        assert (
            create_order_detail.technical_details["legacy_generation_id"]
            == "case-generation:d193fa2adced2868901d"
        )
    finally:
        application.close()


def test_real_rule_preview_uses_current_condition_classification_contract() -> None:
    """真实latest scan必须使用新Program条件协议和已证明的入口知识。

    Returns:
        None；createOrder预览引用当前analysis且不再保留已发布候选阻塞时通过。

    Side Effects:
        仅读取仓库内真实注册系统、latest scan和规则，不访问AI或QA。
    """

    application = OpenTestApplication(REAL_KNOWLEDGE_ROOT)
    try:
        preview = application.preview_case_rules(
            REAL_SYSTEM_ID,
            "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder",
        )
    finally:
        application.close()

    assert preview.manifest.status == "FROZEN"
    assert preview.manifest.analysis_artifact_id.startswith("program-analysis:")
    assert preview.manifest.blockers == []
    # 当前createOrder的程序证据只有未绑定技术影响，不能重新扩大为业务覆盖分母。
    assert preview.manifest.conditions
    assert {
        condition.condition_type.value
        for condition in preview.manifest.conditions
    } == {"INTERNAL_DIAGNOSTIC"}


def test_recovery_workspace_counts_do_not_turn_ungenerated_entries_into_errors() -> None:
    """真实资产计数不得让尚未生成的入口越级推进或显示为阻塞。

    Returns:
        None；三个真实目录均为零且入口仍停在Program断点时通过。

    Side Effects:
        仅读取真实scan、知识和正式资产目录，不访问QA。
    """

    application = OpenTestApplication(REAL_KNOWLEDGE_ROOT)
    try:
        workspace = application.get_case_workspace(REAL_SYSTEM_ID)
    finally:
        application.close()

    assert workspace.entries
    ungenerated_entries = [
        entry
        for entry in workspace.entries
        if entry.generation_lifecycle == "NOT_GENERATED"
    ]
    assert ungenerated_entries
    assert all(
        entry.readiness_status == "NOT_EVALUATED"
        and entry.latest_execution_status == "NOT_RUN"
        and entry.finalization_status == "NOT_APPLICABLE"
        and entry.user_status.display_status == "未生成"
        for entry in ungenerated_entries
    )


def test_current_v3_index_rejects_stale_scan_and_keeps_read_only_alias() -> None:
    """当前V3索引应拒绝旧scan，并兼容同scan的旧入口别名。

    Returns:
        None；只有同scan且可唯一归并的最新生成进入当前入口映射时通过。

    Side Effects:
        无；使用不含真实业务名称的最小模型夹具验证身份规则。
    """

    entry = EntryPoint.model_construct(
        entry_id="facade:sample.api.OrderFacade#create",
        source_id="sample.api.OrderFacade#create",
        system_id="sample.system",
        kind=KnowledgeNodeKind.FACADE,
        display_name="OrderFacade#create",
        source_path="src/OrderFacade.java",
    )
    baseline = SourceBaseline(source_path="/tmp/generic-source", commit="generic-current")
    manifest = ScanManifest.model_construct(
        scan_id="scan-current",
        system_id="sample.system",
        baseline=baseline,
        entries=[entry],
    )
    coverage = FrozenCoverageManifest.model_construct(
        system_id="sample.system",
        entry_id=entry.entry_id,
        source_scan_id="scan-current",
    )
    stale_generation = HybridCaseGenerationRecord.model_construct(
        generation_id="hybrid-generation-11111111111111111111",
        system_id="sample.system",
        entry_id=entry.entry_id,
        source_scan_id="scan-old",
        source_baseline=baseline,
        coverage_manifest=coverage,
    )
    aliased_generation = HybridCaseGenerationRecord.model_construct(
        generation_id="hybrid-generation-22222222222222222222",
        system_id="sample.system",
        entry_id=f"entry:{entry.source_id}",
        source_scan_id="scan-current",
        source_baseline=baseline,
        coverage_manifest=coverage,
    )

    indexed = OpenTestApplication._index_current_hybrid_generations(
        manifest,
        [stale_generation, aliased_generation],
    )

    assert indexed == {entry.entry_id: aliased_generation}


def test_attempt_summary_uses_latest_attempt_for_every_variant() -> None:
    """Attempt汇总应按Variant取最新状态，并把未执行Variant计为未通过。

    Returns:
        None；重试成功覆盖旧失败且其他未执行Variant仍保持未通过时通过。

    Side Effects:
        无；仅使用通用Attempt模型夹具执行确定性聚合。
    """

    started_at = datetime(2026, 8, 27, tzinfo=UTC)
    older_failure = ExecutionAttempt(
        attempt_id="attempt-11111111111111111111",
        generation_id="hybrid-generation-11111111111111111111",
        scenario_id="scenario-sample",
        variant_id="variant-alpha",
        system_id="sample.system",
        status="FAILED",
        created_at=started_at,
    )
    newer_success = older_failure.model_copy(
        update={
            "attempt_id": "attempt-22222222222222222222",
            "status": "PASSED",
            "created_at": started_at + timedelta(minutes=1),
        }
    )

    attempt_count, non_passing_count = OpenTestApplication._summarize_workspace_attempts(
        ["variant-alpha", "variant-beta"],
        [older_failure, newer_success],
    )

    assert attempt_count == 2
    assert non_passing_count == 1


def test_stateful_cleanup_keeps_distinct_slots_and_matches_exact_create_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一Recipe被两个slot复用时必须分别回收并按CREATE Fact精确选Plan。

    Args:
        tmp_path: Pytest隔离的通用编译和执行资产根目录。
        monkeypatch: 隔离Cleanup读取与执行以检查冻结编排，不访问QA。

    Returns:
        None；两个slot各保留一次Finalization且错误Fact契约不会参与匹配时通过。

    Side Effects:
        仅写临时知识资产并记录内存中的回收调用，不执行provider。
    """

    harness = _compiler_harness(tmp_path, [])
    recipe_ref = DataSetupRecipeRef(
        system_id=GENERIC_SYSTEM_ID,
        recipe_id="setup:generic-stateful-producer",
    )
    node_a = StatefulAcquisitionPlanNode(
        node_id="stateful-node:generic-node-a",
        slot_id="refund_order_a",
        fact_contract_id="refund-order/v1",
        required_state="CANCELLABLE",
        recipe_ref=recipe_ref,
        output_fact_name="created_refund",
        created_fact_name="created_refund",
        acquisition_policy="CREATE_ONLY",
    )
    node_b = node_a.model_copy(
        update={
            "node_id": "stateful-node:generic-node-b",
            "slot_id": "refund_order_b",
        }
    )
    identity = CleanupBusinessIdentityRef(
        source_ref=SetupFactInputRef(
            fact_contract_id="refund-order/v1",
            fact_path="refund_serial_no",
        ),
        fact_schema={"type": "string"},
        fact_name="created_refund",
    )
    matching_plan = CleanupPlan.model_construct(
        cleanup_plan_id="cleanup:generic-refund-created",
        system_id=GENERIC_SYSTEM_ID,
        entry_id=GENERIC_ENTRY_ID,
        source_scan_id=harness.scan_id,
        setup_recipe_ref=recipe_ref,
        resource_scope="STATEFUL_PRODUCER",
        primary_strategy="SQL_UPDATE",
        business_identity=identity,
    )
    wrong_contract_plan = matching_plan.model_copy(
        update={
            "cleanup_plan_id": "cleanup:generic-ticket-created",
            "business_identity": identity.model_copy(
                update={
                    "source_ref": identity.source_ref.model_copy(
                        update={"fact_contract_id": "ticket-order/v1"}
                    )
                }
            ),
        }
    )
    plans_by_id = {
        matching_plan.cleanup_plan_id: matching_plan,
        wrong_contract_plan.cleanup_plan_id: wrong_contract_plan,
    }
    monkeypatch.setattr(
        harness.application.hybrid_case_generation.cleanup_plans,
        "get_current",
        lambda _system_id, plan_id: plans_by_id[plan_id],
    )

    selected = harness.application.hybrid_case_generation._matching_stateful_cleanup(
        GENERIC_SYSTEM_ID,
        [wrong_contract_plan, matching_plan],
        node_a,
        GENERIC_ENTRY_ID,
        harness.scan_id,
    )

    assert selected == matching_plan

    plan_a = matching_plan.model_copy(
        update={
            "business_identity": identity.model_copy(
                update={
                    "source_ref": identity.source_ref.model_copy(
                        update={"slot_id": node_a.slot_id}
                    )
                }
            )
        }
    )
    plan_b = matching_plan.model_copy(
        update={
            "business_identity": identity.model_copy(
                update={
                    "source_ref": identity.source_ref.model_copy(
                        update={"slot_id": node_b.slot_id}
                    )
                }
            )
        }
    )
    stateful_plan = StatefulAcquisitionPlan(
        nodes=[node_a, node_b],
        root_slot_ids=[node_a.slot_id, node_b.slot_id],
    )
    scenario = SimpleNamespace(
        template_key=SimpleNamespace(stateful_setup_plan=stateful_plan)
    )
    assets = SimpleNamespace(
        scenario=scenario,
        cleanup_plan=None,
        stateful_cleanup_plans={node_a.node_id: plan_a, node_b.node_id: plan_b},
    )
    context = CaseExecutionContext(
        attempt_id="attempt-stateful-cleanup-two-slots",
        environment="qa",
        timeout_seconds=1,
        fixture={},
    )
    context.resource_may_exist = True
    context.stateful_created_node_ids = {node_a.node_id, node_b.node_id}
    finalized_slots = []

    def record_finalization(
        plan: CleanupPlan,
        _context: CaseExecutionContext,
    ) -> tuple[None, None, None]:
        """记录每个冻结slot的Finalization调用而不访问任何provider。

        Args:
            plan: 已绑定具体slot的current Cleanup Plan视图。
            _context: 本测试不读取的Attempt瞬时上下文。

        Returns:
            三个终结阶段均成功的空失败元组。

        Side Effects:
            把本次Plan的slot追加到内存列表。
        """

        finalized_slots.append(plan.business_identity.source_ref.slot_id)
        return None, None, None

    monkeypatch.setattr(
        harness.application.case_execution_v3,
        "_finalize_one_cleanup",
        record_finalization,
    )
    harness.application.case_execution_v3._finalize_cleanup(assets, context)
    passing_plans = harness.application.case_execution_v3._passing_cleanup_plans(
        assets,
        harness.action.model_copy(update={"mutability": OperationMutability.READ_ONLY}),
        context.stateful_created_node_ids,
    )

    assert finalized_slots == [node_b.slot_id, node_a.slot_id]
    assert [
        plan.business_identity.source_ref.slot_id for plan in passing_plans
    ] == [node_b.slot_id, node_a.slot_id]

    action_plan = matching_plan.model_copy(
        update={
            "cleanup_plan_id": "cleanup:generic-cancel-action",
            "resource_scope": "ACTION_EFFECT",
            "business_identity": identity.model_copy(
                update={
                    "fact_name": "verified_refund",
                    "source_ref": identity.source_ref.model_copy(
                        update={"slot_id": node_a.slot_id}
                    ),
                }
            ),
        }
    )
    producer_plan = plan_a.model_copy(
        update={"resource_scope": "STATEFUL_PRODUCER"}
    )
    identity_context = CaseExecutionContext(
        attempt_id="attempt-stateful-identity-scope",
        environment="qa",
        timeout_seconds=30,
        fixture={},
        setup_facts_by_slot={
            node_a.slot_id: {"refund_serial_no": "query-hit-refund"}
        },
        stateful_cleanup_facts_by_slot={
            node_a.slot_id: {"refund_serial_no": "created-refund"}
        },
    )

    # QUERY_ONLY/QTC命中时Action回收取最终slot；Producer回收始终取CREATE专用身份。
    service = harness.application.case_execution_v3
    assert service._cleanup_identity(action_plan, identity_context) == "query-hit-refund"
    assert service._cleanup_identity(producer_plan, identity_context) == "created-refund"


def test_case_workspace_http_returns_real_directory_without_qa() -> None:
    """运行中HTTP接口应返回与真实应用投影相同的通用入口目录。

    Returns:
        None；API没有canary字段且入口来自真实知识目录时通过。

    Side Effects:
        启停本地FastAPI测试生命周期，不调用任何QA provider。
    """

    application = OpenTestApplication(REAL_KNOWLEDGE_ROOT)
    before_generations = application.list_hybrid_case_generations(REAL_SYSTEM_ID)
    before_attempts = application.list_hybrid_case_attempts(REAL_SYSTEM_ID)
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.get(f"/api/v3/systems/{REAL_SYSTEM_ID}/case-workspace")

    assert response.status_code == 200
    payload = response.json()["workspace"]
    assert "canaries" not in payload
    assert REAL_REFUND_METHODS.issubset({entry["display_name"] for entry in payload["entries"]})
    create_order = next(
        entry for entry in payload["entries"] if entry["display_name"] == "RefundFacade#createOrder"
    )
    # 正式知识已更新但尚未生成Case时，HTTP摘要必须保持中性生命周期。
    assert create_order["generation_lifecycle"] == "NOT_GENERATED"
    assert create_order["readiness_status"] == "NOT_EVALUATED"
    assert create_order["blocker_count"] == 0
    assert create_order["user_status"]["display_status"] == "未生成"
    assert create_order["generation_progress"] is None
    assert create_order["user_status"]["technical_code"] == ""
    assert create_order["user_status"]["technical_details"] == {}
    assert {
        "published_capability_count",
        "setup_recipe_count",
        "cleanup_plan_count",
        "analysis_artifact_id",
        "semantic_gaps",
        "pipeline_steps",
        "blockers",
    }.isdisjoint(create_order)
    assert {"legacy_generations", "v3_generations", "attempts"}.isdisjoint(payload)
    assert application.list_hybrid_case_generations(REAL_SYSTEM_ID) == before_generations
    assert application.list_hybrid_case_attempts(REAL_SYSTEM_ID) == before_attempts == []


def test_handwritten_passed_attempt_cannot_satisfy_operation_provenance(
    tmp_path: Path,
) -> None:
    """手写PASSED阶段即使匹配Scenario身份也不能替代真实Operation执行记录。

    Args:
        tmp_path: Pytest隔离真实注册、latest scan和正式通用资产。

    Returns:
        None；缺少operation-execution来源证明的Attempt被拒绝时通过。

    Side Effects:
        仅在临时知识目录生成通用正式资产，不访问QA或写入伪造Attempt文件。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:provenance-mode"),
                factor_path="mode",
                values=["A", "M"],
            )
        ],
    )
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        scenario = generation.scenarios[0]
        variant = generation.variants[0]
        forged = ExecutionAttempt(
            attempt_id="attempt-aaaaaaaaaaaaaaaaaaaa",
            generation_id=generation.generation_id,
            scenario_id=scenario.scenario_id,
            variant_id=variant.variant_id,
            system_id=GENERIC_SYSTEM_ID,
            status="PASSED",
            execution_boundary="INDEXED_OPERATION",
            step_evidence=[
                ExecutionStepEvidence(
                    sequence=1,
                    stage="ACTION",
                    subject_id=harness.action.capability_id,
                    status="PASSED",
                ),
                ExecutionStepEvidence(
                    sequence=2,
                    stage="ORACLE",
                    subject_id=scenario.template_key.oracle_template_id,
                    status="PASSED",
                ),
            ],
        )

        with pytest.raises(
            KnowledgeValidationError,
            match="BLOCKED_ATTEMPT_PROVENANCE_MISSING",
        ):
            harness.application.case_execution_v3.verify_passing_attempt(forged)
    finally:
        harness.application.close()


def test_operation_relation_and_oracle_result_are_replayed_for_passed_attempt(
    tmp_path: Path,
) -> None:
    """真实Operation记录也必须精确属于Attempt且其结果能重新通过Oracle。

    Args:
        tmp_path: Pytest隔离通用源码、Published和Operation执行记录。

    Returns:
        None；错误request关系和与Oracle相反的真实结果均被拒绝时通过。

    Side Effects:
        仅在临时目录写入不含真实业务名称的负向Operation记录，不访问QA。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:replay-mode"),
                factor_path="mode",
                values=["A", "M"],
            )
        ],
    )
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        scenario = generation.scenarios[0]
        variant = generation.variants[0]
        provider_ref = harness.action.provider_operation_ref
        operation = harness.application.operations.get(
            provider_ref.source_system_id,
            provider_ref.operation_id,
        )
        attempt_id = "attempt-bbbbbbbbbbbbbbbbbbbb"
        record = OperationExecutionRecord(
            execution_id="operation-execution-cccccccccccccccccccc",
            request_id=f"{attempt_id}:9:action",
            request_digest="d" * 64,
            system_id=provider_ref.source_system_id,
            operation_id=provider_ref.operation_id,
            kind=operation.kind,
            status=OperationExecutionStatus.COMPLETED,
            result={
                "output": {
                    "accepted": False,
                    "referenceId": "generic-reference",
                }
            },
        )
        harness.application.operations.records.write(record)
        capability_ref = PublishedCapabilityRef(
            system_id=harness.action.system_id,
            capability_id=harness.action.capability_id,
        )
        forged = ExecutionAttempt(
            attempt_id=attempt_id,
            generation_id=generation.generation_id,
            scenario_id=scenario.scenario_id,
            variant_id=variant.variant_id,
            system_id=GENERIC_SYSTEM_ID,
            status="PASSED",
            execution_boundary="INDEXED_OPERATION",
            step_evidence=[
                ExecutionStepEvidence(
                    sequence=1,
                    stage="ACTION",
                    subject_id=harness.action.capability_id,
                    status="PASSED",
                    operation_execution_id=record.execution_id,
                    operation_system_id=record.system_id,
                    operation_id=record.operation_id,
                    capability_ref=capability_ref,
                ),
                ExecutionStepEvidence(
                    sequence=2,
                    stage="ORACLE",
                    subject_id=scenario.template_key.oracle_template_id,
                    status="PASSED",
                ),
            ],
        )

        with pytest.raises(
            KnowledgeValidationError,
            match="BLOCKED_ATTEMPT_PROVENANCE_INVALID",
        ):
            harness.application.case_execution_v3.verify_passing_attempt(forged)

        # 修正request归属后，真实返回accepted=false仍不能被本地伪造的Oracle PASSED覆盖。
        harness.application.operations.records.write(
            record.model_copy(update={"request_id": f"{attempt_id}:1:action"})
        )
        with pytest.raises(
            KnowledgeValidationError,
            match="BLOCKED_ATTEMPT_ORACLE_REPLAY_MISMATCH",
        ):
            harness.application.case_execution_v3.verify_passing_attempt(forged)
    finally:
        harness.application.close()


def test_fault_failure_proof_and_duplicate_operation_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fault目标允许预期FAILED，但错误语义或重复Operation证明必须被拒绝。

    Args:
        tmp_path: Pytest隔离通用Published和Operation执行记录。
        monkeypatch: 隔离验证器的冻结图输入以直接覆盖重复证明门禁。

    Returns:
        None；合法Fault失败被接受，实体漂移和重复执行ID分别被阻塞时通过。

    Side Effects:
        仅在临时目录写通用Operation记录，不访问QA或真实业务系统。
    """

    harness = _compiler_harness(tmp_path, [])
    try:
        service = harness.application.case_execution_v3
        provider_ref = harness.action.provider_operation_ref
        operation = harness.application.operations.get(
            provider_ref.source_system_id,
            provider_ref.operation_id,
        )
        capability_ref = PublishedCapabilityRef(
            system_id=harness.action.system_id,
            capability_id=harness.action.capability_id,
        )
        fault_attempt = ExecutionAttempt(
            attempt_id="attempt-dddddddddddddddddddd",
            generation_id="hybrid-generation-dddddddddddddddddddd",
            scenario_id="scenario-generic-fault",
            variant_id="variant-generic-fault",
            system_id=GENERIC_SYSTEM_ID,
            status="PASSED",
            execution_boundary="INDEXED_OPERATION",
        )
        fault_record = OperationExecutionRecord(
            execution_id="operation-execution-eeeeeeeeeeeeeeeeeeee",
            request_id=f"{fault_attempt.attempt_id}:1:action",
            request_digest="e" * 64,
            system_id=provider_ref.source_system_id,
            operation_id=provider_ref.operation_id,
            kind=operation.kind,
            status=OperationExecutionStatus.FAILED,
            result={
                "output": {
                    "accepted": False,
                    "referenceId": "generic-fault-reference",
                    "entity_states": {
                        "previous_entities": "SUCCESS",
                        "current_entity": "FAILED",
                        "remaining_entities": "NOT_EXECUTED",
                    },
                }
            },
            error_code="GENERIC_FAILURE",
        )
        harness.application.operations.records.write(fault_record)
        expected_fault = _ExpectedAttemptEvidence(
            stage="ACTION",
            subject_id=harness.action.capability_id,
            operation_system_id=provider_ref.source_system_id,
            operation_id=provider_ref.operation_id,
            capability_ref=capability_ref,
            operation_status=OperationExecutionStatus.FAILED,
            operation_error_code="GENERIC_FAILURE",
            failure_outcome="error_response",
            request_ordinal=1,
        )
        actual_fault = ExecutionStepEvidence(
            sequence=1,
            stage="ACTION",
            subject_id=harness.action.capability_id,
            status="PASSED",
            operation_execution_id=fault_record.execution_id,
            operation_system_id=fault_record.system_id,
            operation_id=fault_record.operation_id,
            capability_ref=capability_ref,
        )

        verified_record = service._verify_operation_evidence(
            fault_attempt,
            expected_fault,
            actual_fault,
        )
        expected_states = FaultExpectedEntityStates(
            previous_entities="SUCCESS",
            current_entity="FAILED",
            remaining_entities="NOT_EXECUTED",
        )
        fault_assets = SimpleNamespace(
            fault_plan=SimpleNamespace(
                fault_result=SimpleNamespace(
                    error_code="GENERIC_FAILURE",
                    outcome="error_response",
                ),
                expected_entity_states=expected_states,
                resolution=FaultCapabilityKind.REAL_DATA,
            )
        )
        replay_context = CaseExecutionContext(
            attempt_id=fault_attempt.attempt_id,
            environment="qa",
            timeout_seconds=1,
            fixture={},
            action_result={"entity_states": expected_states.model_dump(mode="json")},
        )
        service._replay_fault_outcomes(
            fault_assets,
            [expected_fault],
            {1: fault_record},
            1,
            replay_context,
        )

        assert verified_record.execution_id == fault_record.execution_id
        assert verified_record.status == OperationExecutionStatus.FAILED
        replay_context.action_result = {
            "entity_states": {
                "previous_entities": "SUCCESS",
                "current_entity": "SUCCESS",
                "remaining_entities": "NOT_EXECUTED",
            }
        }
        with pytest.raises(
            KnowledgeValidationError,
            match="BLOCKED_ATTEMPT_FAULT_ORACLE_REPLAY_MISMATCH",
        ):
            service._replay_fault_outcomes(
                fault_assets,
                [expected_fault],
                {1: fault_record},
                1,
                replay_context,
            )

        # 两个逻辑节点即使被构造为同一request关系，也不能重复消费一条真实执行记录。
        duplicate_record = fault_record.model_copy(
            update={
                "execution_id": "operation-execution-ffffffffffffffffffff",
                "request_id": "attempt-ffffffffffffffffffff:1:action",
                "status": OperationExecutionStatus.COMPLETED,
                "error_code": "",
            }
        )
        harness.application.operations.records.write(duplicate_record)
        completed_expected = expected_fault.__class__(
            stage="ACTION",
            subject_id=harness.action.capability_id,
            operation_system_id=provider_ref.source_system_id,
            operation_id=provider_ref.operation_id,
            capability_ref=capability_ref,
            request_ordinal=1,
        )
        scenario = SimpleNamespace(
            scenario_id="scenario-generic-duplicate",
            template_key=SimpleNamespace(stateful_setup_plan=None),
        )
        monkeypatch.setattr(
            service.catalog,
            "base_template",
            lambda *_args: (SimpleNamespace(), scenario, SimpleNamespace()),
        )
        monkeypatch.setattr(
            service.catalog,
            "current_assets",
            lambda *_args: SimpleNamespace(
                recipe=None,
                scenario=scenario,
                cleanup_plan=None,
            ),
        )
        monkeypatch.setattr(
            service,
            "_append_expected_action_and_oracle",
            lambda expected, _assets: (
                expected.extend([completed_expected, completed_expected])
                or harness.action
            ),
        )
        duplicate_attempt = ExecutionAttempt(
            attempt_id="attempt-ffffffffffffffffffff",
            generation_id="hybrid-generation-ffffffffffffffffffff",
            scenario_id=scenario.scenario_id,
            variant_id="variant-generic-duplicate",
            system_id=GENERIC_SYSTEM_ID,
            status="PASSED",
            execution_boundary="INDEXED_OPERATION",
            step_evidence=[
                actual_fault.model_copy(
                    update={
                        "sequence": sequence,
                        "operation_execution_id": duplicate_record.execution_id,
                    }
                )
                for sequence in (1, 2)
            ],
        )
        with pytest.raises(
            KnowledgeValidationError,
            match="BLOCKED_ATTEMPT_PROVENANCE_DUPLICATED",
        ):
            service.verify_passing_attempt(duplicate_attempt)
    finally:
        harness.application.close()


def test_effect_and_cleanup_oracles_replay_stored_operation_results(
    tmp_path: Path,
) -> None:
    """Effect与Cleanup本地PASSED都必须被真实Operation结果重新证明。

    Args:
        tmp_path: Pytest隔离通用Published能力和确定性验证服务。

    Returns:
        None；错误Observer计数和未恢复Cleanup查询结果分别被阻塞时通过。

    Side Effects:
        仅构造内存中的通用Operation结果，不访问QA或写Attempt。
    """

    harness = _compiler_harness(tmp_path, [])
    try:
        service = harness.application.case_execution_v3
        observer = harness.action.model_copy(
            update={
                "capability_id": "published:generic-observer:count-v1",
                "business_name": "读取通用副作用计数",
                "output_mapping": {"count": "output.count"},
            }
        )
        observer_ref = PublishedCapabilityRef(
            system_id=observer.system_id,
            capability_id=observer.capability_id,
        )
        oracle = OracleTemplate(
            oracle_template_id="oracle:generic-replay:v1",
            entry_id=GENERIC_ENTRY_ID,
            source_scan_id=harness.scan_id,
            action_capability_ref=PublishedCapabilityRef(
                system_id=harness.action.system_id,
                capability_id=harness.action.capability_id,
            ),
            effect_observations=[
                OracleEffectObservationTemplate(
                    effect_evidence_id="evidence:generic-effect-count",
                    effect_kind="rpc",
                    effect_target="generic.effect",
                    observer_capability_ref=observer_ref,
                    assertions=[
                        OracleAssertionTemplate(
                            actual_source="observer_output",
                            actual_path="count",
                            expected=OracleExpression(operator="literal", value=1),
                        )
                    ],
                )
            ],
        )
        observer_expected = _ExpectedAttemptEvidence(
            stage="ORACLE",
            subject_id=observer.capability_id,
            operation_system_id=observer.provider_operation_ref.source_system_id,
            operation_id=observer.provider_operation_ref.operation_id,
            capability_ref=observer_ref,
            request_ordinal=1,
        )
        observer_record = OperationExecutionRecord(
            execution_id="operation-execution-11111111111111111111",
            request_id="attempt-11111111111111111111:1:oracle",
            request_digest="1" * 64,
            system_id=observer.provider_operation_ref.source_system_id,
            operation_id=observer.provider_operation_ref.operation_id,
            kind=harness.application.operations.get(
                observer.provider_operation_ref.source_system_id,
                observer.provider_operation_ref.operation_id,
            ).kind,
            status=OperationExecutionStatus.COMPLETED,
            result={"output": {"count": 0}},
        )
        oracle_assets = SimpleNamespace(
            oracle_template=oracle,
            variant=SimpleNamespace(factor_values={}),
            capabilities={(observer.system_id, observer.capability_id): observer},
        )
        context = CaseExecutionContext(
            attempt_id="attempt-11111111111111111111",
            environment="qa",
            timeout_seconds=1,
            fixture={},
            action_result={"accepted": True},
        )
        with pytest.raises(
            KnowledgeValidationError,
            match="BLOCKED_ATTEMPT_ORACLE_REPLAY_MISMATCH",
        ):
            service._replay_oracle_outcomes(
                oracle_assets,
                [observer_expected],
                {1: observer_record},
                context,
            )

        cleanup_plan = CleanupPlan.model_construct(
            recovery_oracle=CleanupOracleDefinition.model_construct(
                expected_rows=0,
                expected_fields=[],
            )
        )
        cleanup_expected = _ExpectedAttemptEvidence(
            stage="CLEANUP_ORACLE",
            subject_id="resource:generic-cleanup-query",
            operation_system_id=GENERIC_SYSTEM_ID,
            operation_id="resource:generic-cleanup-query",
            request_ordinal=1,
        )
        cleanup_record = observer_record.model_copy(
            update={
                "execution_id": "operation-execution-22222222222222222222",
                "operation_id": cleanup_expected.operation_id,
                "result": {"rows": [{"state": "ACTIVE"}]},
            }
        )
        with pytest.raises(
            KnowledgeValidationError,
            match="BLOCKED_ATTEMPT_CLEANUP_ORACLE_REPLAY_MISMATCH",
        ):
            service._replay_cleanup_outcome(
                cleanup_plan,
                cleanup_expected.request_ordinal,
                {1: cleanup_record},
            )
    finally:
        harness.application.close()


def test_workspace_attempt_projection_uses_trustworthy_priority_and_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工作台应优先真实失败、拒绝错误Scenario并允许完成后再次执行。

    Args:
        tmp_path: Pytest隔离通用scan、Generation和工作台资产。
        monkeypatch: 在COMPLETE分支隔离已由专门测试覆盖的Operation证明器。

    Returns:
        None；失败优先、Scope阻塞、重跑门禁和阶段排序均准确时通过。

    Side Effects:
        仅在临时知识目录读取通用正式资产，不访问QA或写Attempt存储。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:workspace-priority"),
                factor_path="mode",
                values=["A", "M", "Z"],
            )
        ],
    )
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        manifest = harness.application.source_analysis.artifacts.read(
            GENERIC_SYSTEM_ID,
            "latest",
        )
        entry = CaseKnowledgeEntry(
            entry_id=GENERIC_ENTRY_ID,
            kind="facade",
            display_name="AtomicFacade#inspect",
            group="AtomicFacade",
            knowledge_status="GENERATED",
        )
        started_at = datetime(2026, 8, 27, tzinfo=UTC)
        failed = ExecutionAttempt(
            attempt_id="attempt-33333333333333333333",
            generation_id=generation.generation_id,
            scenario_id=generation.variants[0].scenario_id,
            variant_id=generation.variants[0].variant_id,
            system_id=GENERIC_SYSTEM_ID,
            status="FAILED",
            failure_code="GENERIC_FAILURE",
            failure_message="通用Variant执行失败。",
            created_at=started_at,
        )
        newer_blocked = ExecutionAttempt(
            attempt_id="attempt-44444444444444444444",
            generation_id=generation.generation_id,
            scenario_id=generation.variants[1].scenario_id,
            variant_id=generation.variants[1].variant_id,
            system_id=GENERIC_SYSTEM_ID,
            status="BLOCKED",
            failure_code="BLOCKED_GENERIC_INPUT",
            failure_message="通用输入尚未准备。",
            created_at=started_at + timedelta(minutes=1),
        )

        projected_failure = harness.application._project_case_workspace_entry(
            entry,
            manifest,
            None,
            generation,
            [failed, newer_blocked],
        )
        assert projected_failure.pipeline_status == "FAILED"
        assert projected_failure.blocker_code == "GENERIC_FAILURE"
        assert projected_failure.status_message == failed.failure_message

        invalid_scope = failed.model_copy(
            update={
                "attempt_id": "attempt-55555555555555555555",
                "scenario_id": "scenario-invalid-scope",
            }
        )
        projected_scope = harness.application._project_case_workspace_entry(
            entry,
            manifest,
            None,
            generation,
            [invalid_scope],
        )
        assert projected_scope.blocker_code == "BLOCKED_ATTEMPT_SCOPE_INVALID"

        monkeypatch.setattr(
            harness.application.case_execution_v3,
            "verify_passing_attempt",
            lambda _attempt: None,
        )
        passing_attempts = [
            ExecutionAttempt(
                attempt_id=f"attempt-{index:020x}",
                generation_id=generation.generation_id,
                scenario_id=variant.scenario_id,
                variant_id=variant.variant_id,
                system_id=GENERIC_SYSTEM_ID,
                status="PASSED",
                execution_boundary="INDEXED_OPERATION",
            )
            for index, variant in enumerate(generation.variants, start=10)
        ]
        projected_complete = harness.application._project_case_workspace_entry(
            entry,
            manifest,
            None,
            generation,
            passing_attempts,
        )
        assert projected_complete.pipeline_status == "PASSED"
        assert projected_complete.can_execute is True

        sorted_blockers = OpenTestApplication._sort_workspace_blockers(
            [
                CaseWorkspaceBlocker(
                    stage="CLEANUP_PLAN",
                    code="BLOCKED_CLEANUP_GENERIC",
                    message="Cleanup尚未准备。",
                ),
                CaseWorkspaceBlocker(
                    stage="ACTION_CAPABILITY",
                    code="BLOCKED_ACTION_GENERIC",
                    message="Action尚未发布。",
                ),
            ]
        )
        assert [item.stage for item in sorted_blockers] == [
            "ACTION_CAPABILITY",
            "CLEANUP_PLAN",
        ]
    finally:
        harness.application.close()


def test_workspace_attempt_guidance_and_finalization_are_independent(
    tmp_path: Path,
) -> None:
    """Setup缺数、占用冲突和回收结果必须使用独立业务投影。

    Args:
        tmp_path: Pytest隔离的通用Generation与正式资产根目录。

    Returns:
        None；技术日志被折叠、Setup miss不算断言失败且Action失败后回收仍为PASSED时通过。

    Side Effects:
        只写临时Generation；不调用QA provider。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:attempt-projection-mode"),
                factor_path="mode",
                values=["A", "B"],
            )
        ],
    )
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        missing = ExecutionAttempt(
            attempt_id="attempt-66666666666666666666",
            generation_id=generation.generation_id,
            scenario_id="scenario:generic-attempt-projection",
            variant_id="variant:generic-attempt-projection",
            system_id=GENERIC_SYSTEM_ID,
            status="BLOCKED",
            failure_code="SETUP_STATEFUL_ENTITY_NOT_FOUND",
            failure_message="internal provider log and asset-id",
            primary_failure=AttemptFailureSummary(
                stage="SETUP",
                status="BLOCKED",
                code="SETUP_STATEFUL_ENTITY_NOT_FOUND",
                message="internal provider log and asset-id",
            ),
        )
        missing_summary = harness.application._workspace_attempt_summary(missing)
        assert missing_summary.user_status.title == "本次没有找到可用前置数据"
        assert "internal provider" not in missing_summary.user_status.summary
        assert missing_summary.user_status.technical_details["failure_message"] == (
            missing.failure_message
        )
        readiness, execution, finalization, blocked_status = (
            harness.application._workspace_status_projection(
                generation,
                [],
                [missing],
                can_execute=True,
                all_variants_proven=False,
            )
        )
        assert (readiness, execution, finalization) == (
            "EXECUTABLE",
            "BLOCKED",
            "NOT_APPLICABLE",
        )
        assert blocked_status.display_status == "待补充"
        assert blocked_status.title == "本次没有找到可用前置数据"

        scenario_missing = missing.model_copy(
            update={
                "scenario_id": generation.variants[0].scenario_id,
                "variant_id": generation.variants[0].variant_id,
            }
        )
        scenario_summaries = harness.application._workspace_scenario_summaries(
            SimpleNamespace(blockers=[], user_status=blocked_status),
            generation,
            [scenario_missing],
        )
        assert scenario_summaries[0].user_status.display_status == "待补充"

        failed_but_cleaned = missing.model_copy(
            update={
                "attempt_id": "attempt-77777777777777777777",
                "status": "FAILED",
                "failure_code": "ACTION_BUSINESS_FAILURE",
                "primary_failure": AttemptFailureSummary(
                    stage="ACTION",
                    status="FAILED",
                    code="ACTION_BUSINESS_FAILURE",
                    message="Action未通过。",
                ),
                "step_evidence": [
                    ExecutionStepEvidence(
                        sequence=1,
                        stage="CLEANUP",
                        subject_id="cleanup:generic-action",
                        status="PASSED",
                    ),
                    ExecutionStepEvidence(
                        sequence=2,
                        stage="CLEANUP_ORACLE",
                        subject_id="resource:generic-cleanup-query",
                        status="PASSED",
                    ),
                ],
            }
        )
        _, execution, finalization, _ = harness.application._workspace_status_projection(
            generation,
            [],
            [failed_but_cleaned],
            can_execute=True,
            all_variants_proven=False,
        )
        assert execution == "FAILED"
        assert finalization == "PASSED"

        cleanup_failed = missing.model_copy(
            update={
                "attempt_id": "attempt-99999999999999999999",
                "status": "FAILED",
                "failure_code": "CLEANUP_EXECUTION_FAILED",
                "failure_message": "internal cleanup provider detail",
                "primary_failure": None,
                "cleanup_failure": AttemptFailureSummary(
                    stage="CLEANUP",
                    status="FAILED",
                    code="CLEANUP_EXECUTION_FAILED",
                    message="internal cleanup provider detail",
                ),
            }
        )
        cleanup_summary = harness.application._workspace_attempt_summary(cleanup_failed)
        assert cleanup_summary.user_status.title == "资源终结未完成"
        assert "internal cleanup" not in cleanup_summary.user_status.summary

        passed_without_cleanup = missing.model_copy(
            update={
                "attempt_id": "attempt-88888888888888888888",
                "status": "PASSED",
                "failure_code": "",
                "failure_message": "",
                "primary_failure": None,
                "step_evidence": [],
            }
        )
        _, passed_execution, no_cleanup, passed_status = (
            harness.application._workspace_status_projection(
                generation,
                [],
                [passed_without_cleanup],
                can_execute=True,
                all_variants_proven=True,
            )
        )
        assert (passed_execution, no_cleanup) == ("PASSED", "NOT_APPLICABLE")
        assert passed_status.display_status == "已通过"

        busy_guidance = harness.application._workspace_business_guidance(
            generation,
            CaseWorkspaceBlocker(
                stage="ATTEMPT",
                code="BLOCKED_SETUP_STATEFUL_ENTITY_BUSY",
                message="internal lock detail",
            ),
        )
        cleanup_guidance = harness.application._workspace_business_guidance(
            generation,
            CaseWorkspaceBlocker(
                stage="CLEANUP_PLAN",
                code="BLOCKED_STATEFUL_CLEANUP_PLAN_MISSING",
                message="internal cleanup detail",
            ),
        )
        assert busy_guidance[0] == "前置数据暂时不可用"
        assert cleanup_guidance[0] == "执行后的资源处理方式尚未就绪"
    finally:
        harness.application.close()


def test_workspace_projects_current_case_handoff_as_generating(tmp_path: Path) -> None:
    """同源码代际的活动Case handoff必须覆盖历史Generation显示为生成中。

    Args:
        tmp_path: Pytest隔离Generation、handoff和目录资产根目录。

    Returns:
        None；目录不运行preview也能显示生成中且不暴露handoff身份时通过。

    Side Effects:
        只写临时Generation和handoff记录；不启动Agent或访问QA。
    """

    harness = _compiler_harness(tmp_path, [])
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        manifest = harness.application.source_analysis.artifacts.read(
            GENERIC_SYSTEM_ID,
            "latest",
        )
        harness.application.hybrid_case_handoffs.handoffs.write(
            CaseGenerationHandoff(
                handoff_id="case-handoff-aaaaaaaaaaaaaaaaaaaaaaaa",
                system_id=GENERIC_SYSTEM_ID,
                entry_id=GENERIC_ENTRY_ID,
                source_scan_id=manifest.scan_id,
                source_baseline=manifest.baseline,
                analysis_artifact_id=generation.coverage_manifest.analysis_artifact_id,
                status=CaseGenerationHandoffStatus.VALIDATING,
                generation_ids=[generation.generation_id],
            )
        )

        workspace = harness.application.get_case_workspace(GENERIC_SYSTEM_ID)
        entry = next(
            item for item in workspace.entries if item.entry_id == GENERIC_ENTRY_ID
        )

        assert entry.generation_lifecycle == "GENERATING"
        assert entry.user_status.display_status == "生成中"
        assert entry.user_status.technical_code == ""
        assert entry.user_status.technical_details == {}
    finally:
        harness.application.close()


def test_workspace_directory_defers_inventory_until_target_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目录不得逐入口重验技术资产，单入口详情才读取一次资产计数。

    Args:
        tmp_path: Pytest隔离工作台、Generation和正式资产目录。
        monkeypatch: 记录技术资产计数边界的调用入口。

    Returns:
        None；目录零调用且详情只读取目标入口一次时通过。

    Side Effects:
        只在Pytest临时应用上替换只读计数方法，不访问QA或创建Agent任务。
    """

    harness = _compiler_harness(tmp_path, [])
    inventory_entry_ids: list[str] = []

    def record_inventory(
        system_id: str,
        manifest: ScanManifest,
        entry_id: str,
    ) -> tuple[int, int, int]:
        """记录按需详情读取的入口并返回固定技术资产数量。

        Args:
            system_id: 当前工作台consumer系统。
            manifest: 当前latest scan。
            entry_id: 正在读取详情的exact入口。

        Returns:
            用于验证详情投影的固定Published、Setup和Cleanup数量。

        Side Effects:
            向测试局部列表追加一次入口身份。
        """

        assert system_id == GENERIC_SYSTEM_ID
        assert manifest.system_id == GENERIC_SYSTEM_ID
        inventory_entry_ids.append(entry_id)
        return 3, 2, 1

    monkeypatch.setattr(
        harness.application,
        "_workspace_inventory_counts",
        record_inventory,
    )
    try:
        # 目录只消费业务摘要，不能因折叠技术详情重复读取完整正式资产注册表。
        workspace = harness.application.get_case_workspace(GENERIC_SYSTEM_ID)
        assert workspace.entries
        assert inventory_entry_ids == []

        detail = harness.application.get_case_workspace_entry_detail(
            GENERIC_SYSTEM_ID,
            GENERIC_ENTRY_ID,
        )
        assert inventory_entry_ids == [GENERIC_ENTRY_ID]
        assert (
            detail.technical_details["published_capability_count"],
            detail.technical_details["setup_recipe_count"],
            detail.technical_details["cleanup_plan_count"],
        ) == (3, 2, 1)
    finally:
        harness.application.close()


def test_workspace_progress_stops_when_case_agent_turn_reaches_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case Agent turn结束或失败后不得继续伪装为生成中。

    Args:
        tmp_path: Pytest隔离Generation和正式资产目录。
        monkeypatch: 提供不启动Codex的只读turn快照与任务投影。

    Returns:
        None；活动、完成无产物和失败turn分别得到真实阶段时通过。

    Side Effects:
        只写Pytest临时Generation；不创建Codex线程或访问QA。
    """

    harness = _compiler_harness(tmp_path, [])
    try:
        ready_generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        # 测试只替换为一个AI可处理的语义阻塞，不写入伪Generation。
        blocked_generation = ready_generation.model_copy(
            update={
                "status": "BLOCKED",
                "scenarios": [],
                "variants": [],
                "blockers": [
                    HybridGenerationBlocker(
                        code="BLOCKED_SEMANTIC_RESOLUTION_REQUIRED",
                        message="程序已冻结需要typed Resolution的语义缺口。",
                    )
                ],
            }
        )
        handoff = CaseGenerationHandoff(
            handoff_id="case-handoff-bbbbbbbbbbbbbbbbbbbbbbbb",
            task_id="task-bbbbbbbbbbbbbbbb",
            system_id=GENERIC_SYSTEM_ID,
            entry_id=GENERIC_ENTRY_ID,
            source_scan_id=ready_generation.source_scan_id,
            source_baseline=ready_generation.source_baseline,
            status=CaseGenerationHandoffStatus.WAITING_FOR_AGENT,
            generation_ids=[ready_generation.generation_id],
            thread_id="01a-case-progress-thread",
        )
        task = SimpleNamespace(
            result={"start_state": "started", "turn_id": "turn-case-progress"}
        )
        turn_status = {"value": "inProgress"}
        turn_id = {"value": "turn-case-progress"}

        def load_case_task(task_id: str) -> object:
            """返回已有桌面启动回执的同一Case任务。

            Args:
                task_id: Handoff冻结的本地任务身份。

            Returns:
                仅含turn启动事实的轻量任务。
            """

            assert task_id == handoff.task_id
            return task

        def inspect_case_thread(thread_id: str) -> object:
            """返回测试指定的同一Codex turn终态。

            Args:
                thread_id: Handoff冻结的持久线程身份。

            Returns:
                与本地App Server只读合同一致的turn摘要。
            """

            assert thread_id == handoff.thread_id
            return SimpleNamespace(
                turn_count=1,
                latest_turn_id=turn_id["value"],
                latest_turn_status=turn_status["value"],
            )

        def fail_thread_inspection(thread_id: str) -> object:
            """模拟已启动Codex线程无法再由本地Owner确认。

            Args:
                thread_id: Handoff冻结的持久线程身份。

            Raises:
                KnowledgeValidationError: 线程摘要不可用，不能继续证明任务活动。
            """

            assert thread_id == handoff.thread_id
            raise KnowledgeValidationError("case turn snapshot unavailable")

        def reject_candidate_catalog_rebuild(
            generation: HybridCaseGenerationRecord,
        ) -> bool:
            """拒绝进度投影为已启动或终态Handoff重新构建Candidate目录。

            Args:
                generation: 不应触发AI输入重验的当前Generation。

            Raises:
                AssertionError: 进度投影错误进入昂贵的Candidate扫描。
            """

            del generation
            raise AssertionError("active or terminal progress must not rebuild candidates")

        monkeypatch.setattr(harness.application.tasks, "get", load_case_task)
        monkeypatch.setattr(
            harness.application.codex_app_server,
            "inspect_thread",
            inspect_case_thread,
        )
        monkeypatch.setattr(
            harness.application,
            "_case_generation_handoff_needed",
            reject_candidate_catalog_rebuild,
        )

        running = harness.application._workspace_generation_progress(
            blocked_generation,
            handoff,
        )
        assert running is not None
        assert running.phase == "AGENT_RUNNING"

        turn_status["value"] = "completed"
        completed = harness.application._workspace_generation_progress(
            blocked_generation,
            handoff,
        )
        assert completed is not None
        assert completed.phase == "NEEDS_INPUT"
        assert "已结束" in completed.summary

        turn_status["value"] = "failed"
        failed = harness.application._workspace_generation_progress(
            blocked_generation,
            handoff,
        )
        assert failed is not None
        assert failed.phase == "FAILED"

        turn_status["value"] = "interrupted"
        interrupted = harness.application._workspace_generation_progress(
            blocked_generation,
            handoff,
        )
        assert interrupted is not None
        assert interrupted.phase == "FAILED"

        turn_status["value"] = "inProgress"
        turn_id["value"] = "turn-from-another-request"
        mismatched = harness.application._workspace_generation_progress(
            blocked_generation,
            handoff,
        )
        assert mismatched is not None
        assert mismatched.phase == "NEEDS_INPUT"

        monkeypatch.setattr(
            harness.application.codex_app_server,
            "inspect_thread",
            fail_thread_inspection,
        )
        unavailable = harness.application._workspace_generation_progress(
            blocked_generation,
            handoff,
        )
        assert unavailable is not None
        assert unavailable.phase == "NEEDS_INPUT"

        # 一个后写入且不属于旧handoff的Generation必须成为当前终态，不能再被历史turn覆盖。
        newer_generation = blocked_generation.model_copy(
            update={
                "generation_id": "hybrid-generation-newer-terminal",
                "generated_at": handoff.updated_at + timedelta(seconds=1),
            }
        )
        terminal = harness.application._workspace_generation_progress(
            newer_generation,
            handoff,
        )
        assert terminal is not None
        assert terminal.phase == "BLOCKED"
    finally:
        harness.application.close()


def test_scenario_status_does_not_inherit_another_scenario_failure(
    tmp_path: Path,
) -> None:
    """一个Scenario的失败不得污染同Generation内未运行Scenario的业务投影。

    Args:
        tmp_path: Pytest隔离Generation和正式Action资产根目录。

    Returns:
        None；失败场景和未运行可执行场景拥有各自独立提示时通过。

    Side Effects:
        仅构造内存Scenario与Attempt投影；不持久化Attempt或访问QA。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:scenario-isolation"),
                factor_path="mode",
                values=["A", "B"],
            )
        ],
    )
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        original_scenario = generation.scenarios[0]
        first_variant = generation.variants[0].model_copy(
            update={
                "variant_id": "variant:scenario-isolation-a",
                "scenario_id": "scenario:scenario-isolation-a",
            }
        )
        second_variant = generation.variants[1].model_copy(
            update={
                "variant_id": "variant:scenario-isolation-b",
                "scenario_id": "scenario:scenario-isolation-b",
            }
        )
        first_scenario = original_scenario.model_copy(
            update={
                "scenario_id": first_variant.scenario_id,
                "title": "失败场景",
                "variant_ids": [first_variant.variant_id],
            }
        )
        second_scenario = original_scenario.model_copy(
            update={
                "scenario_id": second_variant.scenario_id,
                "title": "未运行场景",
                "variant_ids": [second_variant.variant_id],
            }
        )
        isolated_generation = generation.model_copy(
            update={
                "scenarios": [first_scenario, second_scenario],
                "variants": [first_variant, second_variant],
            }
        )
        failed_attempt = ExecutionAttempt(
            attempt_id="attempt-99999999999999999999",
            generation_id=generation.generation_id,
            scenario_id=first_scenario.scenario_id,
            variant_id=first_variant.variant_id,
            system_id=GENERIC_SYSTEM_ID,
            status="FAILED",
            failure_code="ACTION_BUSINESS_FAILURE",
            failure_message="internal first-scenario failure",
            primary_failure=AttemptFailureSummary(
                stage="ACTION",
                status="FAILED",
                code="ACTION_BUSINESS_FAILURE",
                message="internal first-scenario failure",
            ),
        )
        entry = SimpleNamespace(
            blockers=[
                CaseWorkspaceBlocker(
                    stage="ATTEMPT",
                    code="ACTION_BUSINESS_FAILURE",
                    message="internal first-scenario failure",
                    subject_ids=[failed_attempt.attempt_id],
                )
            ],
            generation_lifecycle="GENERATED",
            readiness_status="EXECUTABLE",
        )

        summaries = harness.application._workspace_scenario_summaries(
            entry,
            isolated_generation,
            [failed_attempt],
        )
        statuses = {item.scenario_id: item.user_status for item in summaries}

        assert statuses[first_scenario.scenario_id].display_status == "有失败"
        assert statuses[second_scenario.scenario_id].display_status == "可执行"
        assert statuses[second_scenario.scenario_id].missing == []
        assert statuses[second_scenario.scenario_id].recommended_actions == []
        assert statuses[second_scenario.scenario_id].technical_code == ""
        assert statuses[second_scenario.scenario_id].technical_details == {}
    finally:
        harness.application.close()


def test_scenario_global_blocker_counts_all_variants_and_names_exact_root(
    tmp_path: Path,
) -> None:
    """全场景阻塞必须计入全部Variant并按subject展示正确根实体。

    Args:
        tmp_path: Pytest隔离Generation和Action资产根目录。

    Returns:
        None；双root中第二项缺Producer时数量和业务名称均精确时通过。

    Side Effects:
        仅构造内存条件和工作台投影，不访问QA。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:global-blocker-count"),
                factor_path="mode",
                values=["A", "B"],
            )
        ],
    )
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        ticket_condition = CaseCondition(
            condition_id="condition:knowledge:ticket-root",
            condition_type=CaseConditionType.STATEFUL_ENTITY_PRECONDITION,
            title="准备已出票订单",
            summary="执行前需要已出票订单。",
            stateful_requirement=StatefulEntityRequirement(
                slot_id="ticket_order",
                fact_contract_id="ticket-order/v1",
                required_state="ISSUED",
                entity_display_name="出票单",
                state_display_name="已出票",
            ),
        )
        refund_condition = CaseCondition(
            condition_id="condition:knowledge:refund-root",
            condition_type=CaseConditionType.STATEFUL_ENTITY_PRECONDITION,
            title="准备可取消退票单",
            summary="执行前需要可取消退票单。",
            stateful_requirement=StatefulEntityRequirement(
                slot_id="refund_order",
                fact_contract_id="refund-order/v1",
                required_state="CANCELLABLE",
                entity_display_name="退票单",
                state_display_name="可取消",
            ),
        )
        projected_generation = generation.model_copy(
            update={
                "coverage_manifest": generation.coverage_manifest.model_copy(
                    update={"conditions": [ticket_condition, refund_condition]}
                )
            }
        )
        blocker = CaseWorkspaceBlocker(
            stage="SETUP_RECIPE",
            code="BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED",
            message="internal second-root detail",
            subject_ids=[refund_condition.condition_id],
        )
        entry = SimpleNamespace(
            blockers=[blocker],
            generation_lifecycle="GENERATED",
            readiness_status="PARTIALLY_BLOCKED",
        )

        guidance = harness.application._workspace_business_guidance(
            projected_generation,
            blocker,
        )
        summaries = harness.application._workspace_scenario_summaries(
            entry,
            projected_generation,
            [],
        )

        assert guidance[0] == "缺少可取消退票单的准备方式"
        assert all(
            summary.blocked_variant_count == summary.variant_count
            for summary in summaries
        )
        assert all(
            summary.user_status.display_status == "待补充"
            for summary in summaries
        )
    finally:
        harness.application.close()


def test_entry_and_scenario_details_separate_business_projection_from_raw_assets(
    tmp_path: Path,
) -> None:
    """入口只返回摘要，Scenario六区业务字段与原始技术载荷必须分层。

    Args:
        tmp_path: Pytest隔离Generation、能力和API持久化根目录。

    Returns:
        None；Entry不含原始对象且Scenario API只在技术详情保留冻结模型时通过。

    Side Effects:
        仅通过TestClient读取临时工作台；不访问QA。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:scenario-business-detail"),
                factor_path="mode",
                values=["A", "B"],
            )
        ],
    )
    try:
        generation = harness.application.hybrid_case_generation.generate(
            GENERIC_SYSTEM_ID,
            HybridCaseGenerationRequest(entry_id=GENERIC_ENTRY_ID),
        )
        client = TestClient(create_app(harness.application))
        encoded_entry = quote(GENERIC_ENTRY_ID, safe="")
        entry_response = client.get(
            f"/api/v3/systems/{GENERIC_SYSTEM_ID}/case-workspace/entries/{encoded_entry}"
        )
        assert entry_response.status_code == 200
        entry_detail = entry_response.json()["detail"]
        assert "generation" not in entry_detail
        assert "attempts" not in entry_detail
        assert "attempt_summaries" not in entry_detail
        assert len(entry_detail["scenarios"]) == 1
        assert {
            "legacy_generation_id",
            "v3_generation_id",
            "analysis_artifact_id",
            "semantic_draft_id",
            "semantic_gaps",
            "pipeline_steps",
            "blockers",
            "pipeline_stage",
            "pipeline_status",
            "blocker_code",
        }.isdisjoint(entry_detail["entry"])
        assert entry_detail["entry"]["user_status"]["technical_code"] == ""
        assert entry_detail["entry"]["user_status"]["technical_details"] == {}
        assert entry_detail["technical_details"]["v3_generation_id"] == generation.generation_id
        assert "pipeline_steps" in entry_detail["technical_details"]

        scenario_response = client.get(
            f"/api/v3/systems/{GENERIC_SYSTEM_ID}/case-workspace-scenarios/detail",
            params={
                "entry_id": GENERIC_ENTRY_ID,
                "scenario_id": generation.scenarios[0].scenario_id,
            },
        )
        assert scenario_response.status_code == 200
        scenario_detail = scenario_response.json()["detail"]
        assert scenario_detail["user_status"]["scope"] == "SCENARIO"
        assert scenario_detail["preconditions"] == []
        assert scenario_detail["coverage"]
        assert len(scenario_detail["variants"]) == 2
        assert scenario_detail["assertions"]
        assert scenario_detail["finalization"]
        assert scenario_detail["recent_results"] == []
        assert "generation_id" not in {
            key
            for key in scenario_detail
            if key != "technical_details"
        }
        assert scenario_detail["technical_details"]["generation_id"] == generation.generation_id
        assert "template_key" not in scenario_detail["summary"]
        assert all("coverage_proof" not in item for item in scenario_detail["coverage"])
    finally:
        harness.application.close()


def test_workspace_entry_disappears_when_real_scan_entry_is_absent_from_copy(tmp_path: Path) -> None:
    """真实知识临时副本删除scan入口后，工作台不得用硬编码名称补回该入口。

    Args:
        tmp_path: Pytest隔离目录，用于保护仓库中的真实知识资产。

    Returns:
        None；被删除知识入口从临时工作台同步消失时通过。

    Side Effects:
        仅复制并修改临时知识目录，不改动当前真实知识仓库。
    """

    copied_root = tmp_path / "open-test-knowledge"
    shutil.copytree(
        REAL_KNOWLEDGE_ROOT,
        copied_root,
        ignore=shutil.ignore_patterns(".opentest", ".git", "__pycache__"),
    )
    # latest scan是工作台真实性的一部分，仅复制只读扫描产物，不复制任务或运行状态。
    shutil.copytree(
        REAL_KNOWLEDGE_ROOT / ".opentest" / "scans",
        copied_root / ".opentest" / "scans",
    )
    shutil.copytree(
        REAL_KNOWLEDGE_ROOT / ".opentest" / "knowledge-drafts",
        copied_root / ".opentest" / "knowledge-drafts",
    )
    application = OpenTestApplication(copied_root)
    artifacts = application.source_analysis.artifacts
    manifest, program_catalog = artifacts.read_scan_bundle(REAL_SYSTEM_ID, "latest")
    removed_entry_id = next(
        entry.entry_id
        for entry in manifest.entries
        if entry.display_name == "RefundFacade#createOrder"
    )
    # 同时缩减Manifest与程序分析分母，保持临时bundle完整且只移除一个真实扫描入口。
    reduced_manifest = manifest.model_copy(
        update={
            "entries": [
                entry for entry in manifest.entries if entry.entry_id != removed_entry_id
            ]
        }
    )
    reduced_catalog = program_catalog.model_copy(
        update={
            "artifacts": [
                artifact
                for artifact in program_catalog.artifacts
                if artifact.entry_id != removed_entry_id
            ],
            "legacy_artifacts": [
                artifact
                for artifact in program_catalog.legacy_artifacts
                if artifact.entry_id != removed_entry_id
            ],
        }
    )
    artifacts.write_scan_bundle(reduced_manifest, reduced_catalog)
    try:
        workspace = application.get_case_workspace(REAL_SYSTEM_ID)
    finally:
        application.close()

    assert "RefundFacade#createOrder" not in {entry.display_name for entry in workspace.entries}


def test_rule_preview_blocks_program_catalog_with_drifted_real_scan_baseline(tmp_path: Path) -> None:
    """规则预览必须按真实latest Manifest复核Program Catalog基线。

    Args:
        tmp_path: 用于隔离真实知识副本和故障注入Catalog的临时目录。

    Returns:
        None；同scan但基线漂移的Catalog包含精确bundle损坏断点时通过。

    Side Effects:
        仅在真实知识临时副本中写入并篡改负向测试Catalog，不改动仓库真相。
    """

    copied_root = tmp_path / "open-test-knowledge"
    shutil.copytree(
        REAL_KNOWLEDGE_ROOT,
        copied_root,
        ignore=shutil.ignore_patterns(".opentest", ".git", "__pycache__"),
    )
    shutil.copytree(
        REAL_KNOWLEDGE_ROOT / ".opentest" / "scans",
        copied_root / ".opentest" / "scans",
    )
    shutil.copytree(
        REAL_KNOWLEDGE_ROOT / ".opentest" / "knowledge-drafts",
        copied_root / ".opentest" / "knowledge-drafts",
    )
    application = OpenTestApplication(copied_root)
    artifacts = application.source_analysis.artifacts
    manifest = artifacts.read(REAL_SYSTEM_ID, "latest")
    # 临时副本排除了派生SQLite，先从真实Git知识重建目录再注入bundle漂移。
    application.rebuild_index(REAL_SYSTEM_ID)
    artifacts.write_manifest(manifest)
    catalog = artifacts.read_case_analysis(REAL_SYSTEM_ID, manifest.scan_id)
    drifted_baseline = manifest.baseline.model_copy(update={"commit": "drifted-negative-test"})
    drifted_catalog = catalog.model_copy(
        update={
            "source_baseline": drifted_baseline,
            "artifacts": [
                artifact.model_copy(update={"source_baseline": drifted_baseline})
                for artifact in catalog.artifacts
            ],
        }
    )
    catalog_path = (
        copied_root
        / ".opentest"
        / "scans"
        / REAL_SYSTEM_ID
        / f"{manifest.scan_id}.case-analysis.json"
    )
    catalog_path.write_text(drifted_catalog.model_dump_json(indent=2), encoding="utf-8")

    try:
        preview = application.preview_case_rules(
            REAL_SYSTEM_ID,
            "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder",
        )
    finally:
        application.close()

    blocker_codes = {blocker.code for blocker in preview.manifest.blockers}
    assert "BLOCKED_PROGRAM_ANALYSIS_BASELINE_MISMATCH" in blocker_codes
    assert "BLOCKED_PROGRAM_ANALYSIS_RESCAN_REQUIRED" not in blocker_codes
