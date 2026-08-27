"""Validate that the Case workspace is derived from real scan and knowledge truth."""

from __future__ import annotations

import shutil
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
    CaseKnowledgeEntry,
    CaseWorkspaceBlocker,
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
    KnowledgeNodeKind,
    OperationExecutionRecord,
    OperationExecutionStatus,
    OracleAssertionTemplate,
    OracleEffectObservationTemplate,
    OracleExpression,
    OracleTemplate,
    PublishedCapabilityRef,
    ScanManifest,
    SourceBaseline,
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


def test_real_case_workspace_lists_only_current_knowledge_entries() -> None:
    """真实工作台应展示三个现有RefundFacade知识入口且不注入非入口Listener。

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
        assert all(
            entry.blocker_code == "BLOCKED_SEMANTIC_RESOLUTION_REQUIRED"
            for entry in workspace.entries
        )
        assert all(
            (
                entry.published_capability_count,
                entry.setup_recipe_count,
                entry.cleanup_plan_count,
                entry.variant_count,
                entry.attempt_count,
            )
            == (0, 0, 0, 0, 0)
            for entry in workspace.entries
        )
        create_order_entry = next(
            entry for entry in workspace.entries if entry.display_name == "RefundFacade#createOrder"
        )
        assert len(create_order_entry.semantic_gaps) == 5
        assert {gap.status for gap in create_order_entry.semantic_gaps} == {"UNRESOLVED"}
        assert create_order_entry.pipeline_steps[0].stage == "PROGRAM_ANALYSIS"
        assert create_order_entry.pipeline_steps[0].status == "BLOCKED"
        # 旧`entry:<source_id>`生成必须只读挂回规范Facade入口，不能因ID升级从页面消失。
        assert create_order_entry.legacy_generation_id == "case-generation:d193fa2adced2868901d"
    finally:
        application.close()


def test_real_rule_preview_uses_program_catalog_and_blocks_unresolved_semantics() -> None:
    """真实latest scan使用独立Program Catalog并在语义缺口处失败关闭。

    Returns:
        None；createOrder预览引用真实analysis identity并返回全部语义缺口时通过。

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

    assert preview.manifest.status == "BLOCKED"
    assert preview.manifest.analysis_artifact_id.startswith("program-analysis:")
    assert {blocker.code for blocker in preview.manifest.blockers} == {
        "BLOCKED_SEMANTIC_RESOLUTION_REQUIRED"
    }


def test_recovery_workspace_counts_do_not_advance_unresolved_entries() -> None:
    """真实资产计数不得让仍有语义缺口的入口越级推进。

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
    assert all(entry.pipeline_stage == "PROGRAM_ANALYSIS" for entry in workspace.entries)
    assert all(entry.pipeline_status == "BLOCKED" for entry in workspace.entries)
    assert all(
        (
            entry.published_capability_count,
            entry.setup_recipe_count,
            entry.cleanup_plan_count,
        )
        == (0, 0, 0)
        for entry in workspace.entries
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
    assert create_order["published_capability_count"] == 0
    assert create_order["setup_recipe_count"] == 0
    assert create_order["cleanup_plan_count"] == 0
    assert len(create_order["semantic_gaps"]) == 5
    assert create_order["pipeline_steps"][0]["stage"] == "PROGRAM_ANALYSIS"
    assert application.list_hybrid_case_generations(REAL_SYSTEM_ID) == before_generations == []
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
        scenario = SimpleNamespace(scenario_id="scenario-generic-duplicate")
        monkeypatch.setattr(
            service.catalog,
            "base_template",
            lambda *_args: (SimpleNamespace(), scenario, SimpleNamespace()),
        )
        monkeypatch.setattr(
            service.catalog,
            "current_assets",
            lambda *_args: SimpleNamespace(),
        )
        monkeypatch.setattr(
            service,
            "_expected_attempt_evidence",
            lambda _assets: [completed_expected, completed_expected],
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
                [cleanup_expected],
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
            ]
        }
    )
    artifacts.write_scan_bundle(reduced_manifest, reduced_catalog)
    try:
        workspace = application.get_case_workspace(REAL_SYSTEM_ID)
    finally:
        application.close()

    assert "RefundFacade#createOrder" not in {entry.display_name for entry in workspace.entries}


def test_workspace_blocks_program_catalog_with_drifted_real_scan_baseline(tmp_path: Path) -> None:
    """工作台必须按真实latest Manifest复核Program Catalog基线和Entry全集。

    Args:
        tmp_path: 用于隔离真实知识副本和故障注入Catalog的临时目录。

    Returns:
        None；同scan但基线漂移的Catalog只显示bundle损坏断点时通过。

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
        workspace = application.get_case_workspace(REAL_SYSTEM_ID)
    finally:
        application.close()

    assert workspace.entries
    assert {entry.blocker_code for entry in workspace.entries} == {
        "BLOCKED_PROGRAM_ANALYSIS_BASELINE_MISMATCH"
    }
