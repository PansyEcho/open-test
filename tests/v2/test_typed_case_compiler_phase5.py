"""验证阶段5只从真实Git/scan/Published资产静态编译Case。"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.application.scenarios import PairwiseVariantSelector
from opentest.application.typed_case_compiler import (
    ConstrainedPairwiseGenerator,
    StatefulPlanResolutionState,
)
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    ActionFactContractDefinition,
    ActionInputBindingTemplate,
    BoundaryObligation,
    CandidateRef,
    CapabilityDraftSubmission,
    CapabilityInputSourcePolicy,
    CaseCondition,
    CaseConditionResolutionOwner,
    CaseConditionType,
    CaseCompilationActionProfile,
    CaseCompilationRuleSet,
    DecisionObligation,
    DecisionPredicate,
    DiscoveredResource,
    DsfClientProfile,
    DsfOperationDefinition,
    DsfOperationMutability,
    DsfProfileStatus,
    EffectObligation,
    EntryFactAssertion,
    EntryFactCandidateSet,
    EntryFactKnowledge,
    EntryPoint,
    FactorObligation,
    FactorCombinationConstraint,
    FaultInjectionObligation,
    GeneratedInputRef,
    HybridCaseGenerationRequest,
    KnowledgeConclusionSource,
    KnowledgeDraft,
    KnowledgeGenerationWorkflowBatch,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeStatus,
    OperationMutability,
    OracleAssertionTemplate,
    OracleEffectObservationTemplate,
    OracleExpression,
    OracleTemplate,
    ProgramCaseAnalysisArtifact,
    ProgramCaseAnalysisCatalog,
    ProducerEntrySourceRef,
    ProviderOperationRef,
    PublishedCapabilityRef,
    PublishedOperationCapability,
    RequirementFactorTarget,
    RequirementObligation,
    SafeConstantInputRef,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticCaseEvidence,
    SemanticFieldDefinition,
    SemanticMethodDefinition,
    SemanticTypeDefinition,
    SequenceObligation,
    SetupFactRequiredField,
    SetupContractRuleSet,
    SetupFactContractDefinition,
    SetupFactOrigin,
    SetupStatePredicateDefinition,
    SourceBaseline,
    SourceReference,
    StatefulEntityRequirement,
    SystemDefinition,
    SystemDependencyBindingSubmission,
    SystemDependencyPurpose,
    SystemDependencyRole,
    TypedCaseCompileRequest,
    compatible_setup_acquisition_policies,
)


SYSTEM_ID = "generic-case-compiler"
ENTRY_ID = "facade:sample.AtomicFacade#inspect"
METHOD_ID = "sample.AtomicFacade#inspect(sample.AtomicRequest)"


@dataclass(frozen=True)
class CompilerHarness:
    """保存通用阶段5集成测试的真实应用、入口和Published Action。"""

    application: OpenTestApplication
    action: PublishedOperationCapability
    scan_id: str


def test_public_compile_request_rejects_all_client_asset_injection(tmp_path: Path) -> None:
    """公共API只允许entry_id，客户端Manifest、能力和业务输入必须在边界拒绝。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    harness = _compiler_harness(tmp_path, [])
    payload = {
        "entry_id": ENTRY_ID,
        "manifest": {"status": "FROZEN"},
        "base_execution_graph": [harness.action.capability_id],
        "data_setup_recipe_id": "setup:forged",
        "oracle_template": {"oracle_template_id": "oracle:forged"},
        "cleanup_plan_id": "cleanup:forged",
        "base_inputs": {"resource_id": "forged-business-key"},
    }

    with TestClient(create_app(harness.application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/typed-case-compilations",
            json=payload,
        )

    assert response.status_code == 422
    rejected = {item["loc"][-1] for item in response.json()["detail"]}
    assert rejected >= {
        "manifest",
        "base_execution_graph",
        "data_setup_recipe_id",
        "oracle_template",
        "cleanup_plan_id",
        "base_inputs",
    }


def test_formal_entry_fact_knowledge_uses_scan_entry_identity_in_case_preview(
    tmp_path: Path,
) -> None:
    """正式知识节点的历史ID必须桥接到scan入口并进入Case条件。

    Args:
        tmp_path: Pytest隔离知识节点、Setup契约和Case预览资产。

    Returns:
        None；canonical入口事实进入Frozen条件且缺Producer时友好阻塞。

    Side Effects:
        仅在临时Git知识根写正式节点和Setup规则，不访问AI或QA。
    """

    harness = _compiler_harness(tmp_path, [])
    manifest = harness.application.source_analysis.artifacts.read(SYSTEM_ID, "latest")
    entry = manifest.entries[0]
    fact_contract_id = "generic-entity/v1"
    harness.application.setup_contract_rules.write(
        SetupContractRuleSet(
            system_id=SYSTEM_ID,
            fact_contracts=[
                SetupFactContractDefinition(
                    fact_contract_id=fact_contract_id,
                    required_origin=SetupFactOrigin.UPSTREAM_PUBLISHED_OUTPUT,
                    required_fields=[
                        SetupFactRequiredField(path="entity_id", schema_type="string"),
                        SetupFactRequiredField(path="status", schema_type="string"),
                    ],
                    business_identity_paths=["entity_id"],
                        state_path="status",
                        state_predicates=[
                            SetupStatePredicateDefinition(
                                name="READY",
                                allowed_values=["READY"],
                            )
                        ],
                )
            ],
        )
    )
    requirement = EntryFactAssertion(
        assertion_id="entry-fact:generic-requires-ready",
        assertion_type="REQUIRES_FACT",
        slot_id="generic_entity",
        fact_contract_id=fact_contract_id,
        required_state="READY",
        acquisition_policy="QUERY_THEN_CREATE",
        source=KnowledgeConclusionSource.CODE_PROVEN,
        evidence_refs=[
            SourceReference(
                path=entry.source_path,
                symbol=METHOD_ID,
                line=1,
                commit=manifest.baseline.commit,
            )
        ],
    )
    node = KnowledgeNode(
        node_id=f"entry:{entry.source_id}",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        title=entry.display_name,
        aliases=[entry.entry_id, entry.source_id, entry.display_name],
        status=KnowledgeStatus.CODE_VERIFIED,
        entry_fact_knowledge=EntryFactKnowledge(
            entry_id=entry.entry_id,
            source_scan_id=manifest.scan_id,
            source_baseline=manifest.baseline,
            requires_facts=[requirement],
        ),
    )
    harness.application.store.write_node(node, "# Generic entry\n")

    preview = harness.application.preview_case_rules(SYSTEM_ID, ENTRY_ID)
    compilation = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    stateful_conditions = [
        condition
        for condition in preview.manifest.conditions
        if condition.condition_type.value == "STATEFUL_ENTITY_PRECONDITION"
    ]
    assert len(stateful_conditions) == 1
    assert stateful_conditions[0].stateful_requirement.slot_id == "generic_entity"
    assert {blocker.code for blocker in compilation.blockers} >= {
        "BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED"
    }
    producer_blocker = next(
        blocker
        for blocker in compilation.blockers
        if blocker.code == "BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED"
    )
    assert producer_blocker.obligation_id == stateful_conditions[0].condition_id


def test_pending_entry_fact_candidate_blocks_without_becoming_case_condition(
    tmp_path: Path,
) -> None:
    """未确认Fact候选只能形成单一待确认阻塞，精确确认后才进入正式条件。

    Args:
        tmp_path: Pytest隔离知识草稿、正式节点、Fact契约和Generation资产。

    Returns:
        None；候选不被消费、Generation保持Blocked且精确确认后出现正式条件时通过。

    Side Effects:
        仅写临时知识草稿与正式节点，不调用AI、QA或业务接口。
    """

    harness = _compiler_harness(tmp_path, [])
    manifest = harness.application.source_analysis.artifacts.read(SYSTEM_ID, "latest")
    entry = manifest.entries[0]
    contract = SetupFactContractDefinition(
        fact_contract_id="generic-entity/v1",
        display_name="通用业务实体",
        required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
        required_fields=[
            SetupFactRequiredField(path="entity_id", schema_type="string"),
            SetupFactRequiredField(path="status", schema_type="string"),
        ],
        business_identity_paths=["entity_id"],
        state_path="status",
        state_predicates=[
            SetupStatePredicateDefinition(
                name="READY",
                display_name="可用",
                allowed_values=["READY"],
            )
        ],
    )
    harness.application.setup_contract_rules.write(
        SetupContractRuleSet(system_id=SYSTEM_ID, fact_contracts=[contract])
    )
    evidence_path = Path(entry.source_path).relative_to(manifest.baseline.source_path).as_posix()
    evidence = SourceReference(
        path=evidence_path,
        symbol=METHOD_ID,
        line=1,
        commit=manifest.baseline.commit,
    )
    node = KnowledgeNode(
        node_id=f"entry:{entry.source_id}",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        title=entry.display_name,
        aliases=[entry.entry_id, entry.source_id, entry.display_name],
        source_refs=[evidence],
        status=KnowledgeStatus.INFERRED,
    )
    harness.application.store.write_node(node, "# Generic entry\n")
    candidate = EntryFactAssertion(
        assertion_id="entry-fact:generic-pending-ready",
        assertion_type="REQUIRES_FACT",
        slot_id="generic_entity",
        fact_contract_id=contract.fact_contract_id,
        required_state="READY",
        acquisition_policy="QUERY_ONLY",
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[evidence],
    )
    candidate_set = EntryFactCandidateSet(
        system_id=SYSTEM_ID,
        entry_id=entry.entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        assertions=[candidate],
    )
    draft = KnowledgeDraft(
        draft_id="knowledge-draft:generic-pending-fact",
        system_id=SYSTEM_ID,
        target_id=entry.entry_id,
        node=node,
        content="候选事实仍待精确确认。",
        entry_fact_candidates=candidate_set,
    )
    batch = KnowledgeGenerationWorkflowBatch(
        batch_id="knowledge-client-generic-pending-fact",
        system_id=SYSTEM_ID,
        scan_id=manifest.scan_id,
        target_ids=[entry.entry_id],
        status="PENDING_CONFIRMATION",
        drafts=[draft],
    )
    harness.application.store.write_draft_batch(batch)

    with TestClient(create_app(harness.application)) as client:
        detail_response = client.get(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/targets/{quote(entry.entry_id, safe='')}",
            params={
                "include_questions": "false",
                "include_context": "false",
                "scan_id": manifest.scan_id,
            },
        )
    assert detail_response.status_code == 200
    pending_projection = detail_response.json()["target"]
    assert pending_projection["formal_entry_facts"] == []
    assert pending_projection["pending_entry_fact_candidates"] == [
        {
            "batch_id": batch.batch_id,
            "draft_id": draft.draft_id,
            "assertions": [candidate.model_dump(mode="json")],
        }
    ]

    pending_preview = harness.application.preview_case_rules(SYSTEM_ID, ENTRY_ID)
    pending_generation = harness.application.hybrid_case_generation.generate(
        SYSTEM_ID,
        HybridCaseGenerationRequest(entry_id=ENTRY_ID),
    )

    pending_codes = [blocker.code for blocker in pending_preview.manifest.blockers]
    assert pending_codes.count("BLOCKED_ENTRY_FACT_CANDIDATE_CONFIRMATION_REQUIRED") == 1
    assert not any(
        condition.condition_type == CaseConditionType.STATEFUL_ENTITY_PRECONDITION
        for condition in pending_preview.manifest.conditions
    )
    assert pending_generation.status == "BLOCKED"
    assert {
        blocker.code for blocker in pending_generation.coverage_manifest.blockers
    } >= {"BLOCKED_ENTRY_FACT_CANDIDATE_CONFIRMATION_REQUIRED"}

    with TestClient(create_app(harness.application)) as client:
        confirmation_response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/generation-batches/"
            f"{batch.batch_id}/entry-fact-confirmations",
            json={
                "draft_id": draft.draft_id,
                "fact_candidate_ids": [candidate.assertion_id],
            },
        )
        confirmed_detail_response = client.get(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/targets/{quote(entry.entry_id, safe='')}",
            params={
                "include_questions": "false",
                "include_context": "false",
                "scan_id": manifest.scan_id,
            },
        )
    assert confirmation_response.status_code == 200
    assert confirmed_detail_response.status_code == 200
    confirmed_detail = confirmed_detail_response.json()["target"]
    assert confirmed_detail["pending_entry_fact_candidates"] == []
    assert confirmed_detail["formal_entry_facts"][0]["assertions"][0]["source"] == (
        "USER_CONFIRMED"
    )
    confirmed_preview = harness.application.preview_case_rules(SYSTEM_ID, ENTRY_ID)

    assert "BLOCKED_ENTRY_FACT_CANDIDATE_CONFIRMATION_REQUIRED" not in {
        blocker.code for blocker in confirmed_preview.manifest.blockers
    }
    assert [
        condition.stateful_requirement.slot_id
        for condition in confirmed_preview.manifest.conditions
        if condition.condition_type == CaseConditionType.STATEFUL_ENTITY_PRECONDITION
    ] == ["generic_entity"]


def test_compiler_snapshot_includes_distinct_stateful_producer_source(
    tmp_path: Path,
) -> None:
    """编译锁集合必须包含与Recipe步骤provider不同的Producer源码系统。

    Args:
        tmp_path: Pytest隔离的通用编译资产根目录。

    Returns:
        None；consumer、步骤provider和Producer source均参与固定快照时通过。

    Side Effects:
        仅建立临时编译资产并调用锁集合计算，不访问QA或发布Recipe。
    """

    harness = _compiler_harness(tmp_path, [])
    recipe_catalog = SimpleNamespace(
        recipes=[
            SimpleNamespace(
                steps=[
                    SimpleNamespace(
                        capability_ref=SimpleNamespace(system_id="generic-step-provider")
                    )
                ],
                producer_entry_ref=SimpleNamespace(
                    system_id="generic-producer-source"
                ),
            )
        ]
    )

    system_ids = harness.application.typed_case_compiler._asset_system_ids(
        SYSTEM_ID,
        None,
        recipe_catalog,
    )

    assert system_ids == {
        SYSTEM_ID,
        "generic-step-provider",
        "generic-producer-source",
    }


def test_stateful_recipe_resolution_builds_recursive_dag_and_detects_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """状态实体Recipe必须递归冻结依赖、无响应身份创建和依赖环。

    Args:
        tmp_path: Pytest隔离的编译、扫描和Published资产根目录。
        monkeypatch: 隔离current Recipe重验，使本测试聚焦递归与环算法。

    Returns:
        None；Ticket依赖先于Refund、无CREATE身份时冻结末次查询Fact，且反向依赖
        产生稳定环阻塞时通过。

    Side Effects:
        仅创建临时通用编译资产，不发布Recipe、访问AI或调用QA。
    """

    harness = _compiler_harness(tmp_path, [])
    compiler = harness.application.typed_case_compiler
    current_manifest = harness.application.source_analysis.artifacts.read(
        SYSTEM_ID,
        "latest",
    )
    producer_entry_ref = ProducerEntrySourceRef(
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        source_scan_id=harness.scan_id,
        source_baseline=current_manifest.baseline,
    )
    ticket_contract = SetupFactContractDefinition(
        fact_contract_id="ticket-order/v1",
        display_name="通用出票单",
        required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
        required_fields=[
            SetupFactRequiredField(path="order_no", schema_type="string"),
            SetupFactRequiredField(path="state", schema_type="string"),
        ],
        business_identity_paths=["order_no"],
        state_path="state",
        state_predicates=[
            SetupStatePredicateDefinition(
                name="ISSUED",
                display_name="已出票",
                allowed_values=["ISSUED"],
            )
        ],
    )
    refund_contract = SetupFactContractDefinition(
        fact_contract_id="refund-order/v1",
        display_name="通用退票单",
        required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
        required_fields=[
            SetupFactRequiredField(path="refund_no", schema_type="string"),
            SetupFactRequiredField(path="ticket_order_no", schema_type="string"),
            SetupFactRequiredField(path="state", schema_type="string"),
        ],
        business_identity_paths=["refund_no"],
        state_path="state",
        state_predicates=[
            SetupStatePredicateDefinition(
                name="CREATED",
                display_name="已创建",
                allowed_values=["CREATED"],
            ),
            SetupStatePredicateDefinition(
                name="CANCELLABLE",
                display_name="可取消",
                allowed_values=["CANCELLABLE"],
            ),
        ],
    )
    ticket_output = SimpleNamespace(
        fact_name="issued_ticket",
        fact_contract_id=ticket_contract.fact_contract_id,
        from_step_id="query-ticket",
        produced_state="ISSUED",
        constraints=[],
        relations={},
        fact_schema={
            "type": "object",
            "properties": {
                "order_no": {"type": "string"},
                "state": {"type": "string"},
            },
            "required": ["order_no", "state"],
        },
    )
    ticket_requirement = SimpleNamespace(
        slot_id="ticket_order",
        fact_contract_id=ticket_contract.fact_contract_id,
        required_state="ISSUED",
        acquisition_policy="QUERY_ONLY",
        constraints={},
        relations={},
    )
    ticket_recipe = SimpleNamespace(
        system_id=SYSTEM_ID,
        recipe_id="setup:generic-ticket-query",
        entry_source_scan_id=harness.scan_id,
        producer_scope="ENTITY_PRODUCER",
        acquisition_policy="QUERY_ONLY",
        selection_priority=10,
        steps=[SimpleNamespace(step_id="query-ticket", operation_role="QUERY")],
        fact_outputs=[ticket_output],
        requires_facts=[],
        producer_entry_ref=producer_entry_ref,
    )
    created_refund = SimpleNamespace(
        fact_name="created_refund",
        fact_contract_id=refund_contract.fact_contract_id,
        from_step_id="create-refund",
        produced_state="CREATED",
        constraints=[],
        relations={"ticket_order_no": "${ticket_order.order_no}"},
        fact_schema={
            "type": "object",
            "properties": {
                "refund_no": {"type": "string"},
                "ticket_order_no": {"type": "string"},
                "state": {"type": "string"},
            },
            "required": ["refund_no", "ticket_order_no", "state"],
        },
    )
    verified_refund = SimpleNamespace(
        **{
            **vars(created_refund),
            "fact_name": "verified_refund",
            "from_step_id": "query-refund-after-create",
            "produced_state": "CANCELLABLE",
        }
    )
    refund_requirement = StatefulEntityRequirement(
        slot_id="refund_order",
        fact_contract_id=refund_contract.fact_contract_id,
        required_state="CANCELLABLE",
        acquisition_policy="QUERY_THEN_CREATE",
    )
    refund_recipe = SimpleNamespace(
        system_id=SYSTEM_ID,
        recipe_id="setup:generic-refund-query-create",
        entry_source_scan_id=harness.scan_id,
        producer_scope="ENTITY_PRODUCER",
        acquisition_policy="QUERY_THEN_CREATE",
        selection_priority=10,
        steps=[
            SimpleNamespace(step_id="query-refund", operation_role="QUERY"),
            SimpleNamespace(step_id="create-refund", operation_role="CREATE"),
            SimpleNamespace(
                step_id="query-refund-after-create",
                operation_role="QUERY",
            ),
        ],
        fact_outputs=[created_refund, verified_refund],
        requires_facts=[ticket_requirement],
        producer_entry_ref=producer_entry_ref,
    )

    def accept_current_recipe(_system_id: str, _recipe: object) -> list[object]:
        """让测试只验证递归解析，不重复覆盖current资产重验。

        Args:
            _system_id: 固定通用consumer系统。
            _recipe: 当前内存Recipe。

        Returns:
            空问题列表，表示外层current验证已通过。
        """

        return []

    monkeypatch.setattr(compiler, "_recipe_current_issues", accept_current_recipe)
    contracts = {
        ticket_contract.fact_contract_id: ticket_contract,
        refund_contract.fact_contract_id: refund_contract,
    }
    state = StatefulPlanResolutionState(
        system_id=SYSTEM_ID,
        manifest=SimpleNamespace(source_scan_id=harness.scan_id),
        recipes=(ticket_recipe, refund_recipe),
        contracts=contracts,
        nodes=[],
        selected_recipes={},
        visiting=set(),
        resolved_nodes={},
    )
    blockers = []
    root = compiler._resolve_stateful_requirement(state, refund_requirement, blockers)

    assert blockers == []
    assert root is not None
    assert [node.slot_id for node in state.nodes] == ["ticket_order", "refund_order"]
    assert root.dependency_node_ids == [state.nodes[0].node_id]
    assert root.output_fact_name == "verified_refund"
    assert root.created_fact_name == "created_refund"
    assert root.create_relations == {"ticket_order_no": "${ticket_order.order_no}"}

    # 真实创建接口可以只返回成功码；最终查询关系闭合时无需伪造CREATE实体Fact。
    identityless_recipe = SimpleNamespace(
        **{**vars(refund_recipe), "fact_outputs": [verified_refund]}
    )
    identityless_state = StatefulPlanResolutionState(
        system_id=SYSTEM_ID,
        manifest=SimpleNamespace(source_scan_id=harness.scan_id),
        recipes=(ticket_recipe, identityless_recipe),
        contracts=contracts,
        nodes=[],
        selected_recipes={},
        visiting=set(),
        resolved_nodes={},
    )
    identityless_blockers = []
    identityless_root = compiler._resolve_stateful_requirement(
        identityless_state,
        refund_requirement,
        identityless_blockers,
    )

    assert identityless_blockers == []
    assert identityless_root is not None
    assert identityless_root.created_fact_name == ""
    assert identityless_root.output_fact_name == "verified_refund"

    related_state = StatefulPlanResolutionState(
        system_id=SYSTEM_ID,
        manifest=SimpleNamespace(source_scan_id=harness.scan_id),
        recipes=(ticket_recipe, refund_recipe),
        contracts=contracts,
        nodes=[],
        selected_recipes={},
        visiting=set(),
        resolved_nodes={},
    )
    relation_blockers = []
    related_root = compiler._resolve_stateful_requirement(
        related_state,
        refund_requirement.model_copy(
            update={
                "relations": {
                    "ticket_order_no": "${ticket_order.order_no}"
                }
            }
        ),
        relation_blockers,
    )

    assert related_root is None
    assert {blocker.code for blocker in relation_blockers} == {
        "BLOCKED_STATEFUL_QUERY_HIT_RELATION_UNAVAILABLE"
    }

    refund_dependency = SimpleNamespace(
        slot_id="refund_order",
        fact_contract_id=refund_contract.fact_contract_id,
        required_state="CANCELLABLE",
        acquisition_policy="QUERY_THEN_CREATE",
        constraints={},
        relations={},
    )
    cyclic_ticket_recipe = SimpleNamespace(
        **{**vars(ticket_recipe), "requires_facts": [refund_dependency]}
    )
    cyclic_state = StatefulPlanResolutionState(
        system_id=SYSTEM_ID,
        manifest=SimpleNamespace(source_scan_id=harness.scan_id),
        recipes=(cyclic_ticket_recipe, refund_recipe),
        contracts=contracts,
        nodes=[],
        selected_recipes={},
        visiting=set(),
        resolved_nodes={},
    )
    cycle_blockers = []
    cyclic_root = compiler._resolve_stateful_requirement(
        cyclic_state,
        refund_requirement,
        cycle_blockers,
    )

    assert cyclic_root is None
    assert {blocker.code for blocker in cycle_blockers} == {
        "BLOCKED_STATEFUL_ENTITY_DEPENDENCY_CYCLE"
    }
    harness.application.close()


def test_stateful_recipe_policy_compatibility_prefers_complete_policy_then_query_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QTC需求必须优先完整QTC，并只允许完整Query-only作为降级。

    Args:
        tmp_path: Pytest隔离的编译、扫描和Published资产根目录。
        monkeypatch: 隔离current Recipe重验，使测试聚焦通用策略兼容和选择顺序。

    Returns:
        None；QTC优先、Query-only降级以及Create-only拒绝均满足时通过。

    Side Effects:
        仅创建临时通用编译资产，不发布Recipe、不访问AI或QA。
    """

    assert compatible_setup_acquisition_policies("QUERY_THEN_CREATE") == (
        "QUERY_THEN_CREATE",
        "QUERY_ONLY",
    )
    assert compatible_setup_acquisition_policies("QUERY_ONLY") == ("QUERY_ONLY",)
    assert compatible_setup_acquisition_policies("CREATE_ONLY") == ("CREATE_ONLY",)
    with pytest.raises(ValueError, match="unsupported setup acquisition policy"):
        compatible_setup_acquisition_policies("UNSAFE_FALLBACK")

    harness = _compiler_harness(tmp_path, [])
    compiler = harness.application.typed_case_compiler
    current_manifest = harness.application.source_analysis.artifacts.read(
        SYSTEM_ID,
        "latest",
    )
    contract = SetupFactContractDefinition(
        fact_contract_id="generic-stateful/v1",
        required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
        required_fields=[
            SetupFactRequiredField(path="entity_id", schema_type="string"),
            SetupFactRequiredField(path="state", schema_type="string"),
        ],
        business_identity_paths=["entity_id"],
        state_path="state",
        state_predicates=[
            SetupStatePredicateDefinition(
                name="READY",
                allowed_values=["READY"],
            )
        ],
    )
    producer_entry_ref = ProducerEntrySourceRef(
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        source_scan_id=harness.scan_id,
        source_baseline=current_manifest.baseline,
    )
    output = SimpleNamespace(
        fact_name="generic_entity",
        fact_contract_id=contract.fact_contract_id,
        from_step_id="query-generic",
        produced_state="READY",
        constraints=[],
        relations={},
        fact_schema={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "state": {"type": "string"},
            },
            "required": ["entity_id", "state"],
        },
    )
    query_recipe = SimpleNamespace(
        system_id=SYSTEM_ID,
        recipe_id="setup:generic-query-only",
        entry_source_scan_id=harness.scan_id,
        producer_scope="ENTITY_PRODUCER",
        acquisition_policy="QUERY_ONLY",
        selection_priority=1,
        steps=[SimpleNamespace(step_id="query-generic", operation_role="QUERY")],
        fact_outputs=[output],
        requires_facts=[],
        producer_entry_ref=producer_entry_ref,
    )
    qtc_recipe = SimpleNamespace(
        **{
            **vars(query_recipe),
            "recipe_id": "setup:generic-query-then-create",
            "acquisition_policy": "QUERY_THEN_CREATE",
            "selection_priority": 100,
        }
    )
    create_recipe = SimpleNamespace(
        **{
            **vars(query_recipe),
            "recipe_id": "setup:generic-create-only",
            "acquisition_policy": "CREATE_ONLY",
            "steps": [
                SimpleNamespace(step_id="query-generic", operation_role="CREATE")
            ],
        }
    )
    requirement = StatefulEntityRequirement(
        slot_id="generic_entity",
        fact_contract_id=contract.fact_contract_id,
        required_state="READY",
        acquisition_policy="QUERY_THEN_CREATE",
    )

    def accept_current_recipe(_system_id: str, _recipe: object) -> list[object]:
        """让策略测试只验证选择顺序，不重复执行current资产重验。

        Args:
            _system_id: 固定通用consumer系统。
            _recipe: 当前内存Recipe。

        Returns:
            空问题列表，表示外层current验证已通过。
        """

        return []

    monkeypatch.setattr(compiler, "_recipe_current_issues", accept_current_recipe)

    def resolve(recipes: tuple[object, ...]) -> tuple[object | None, list[object], object]:
        """使用同一QTC需求解析指定Recipe集合。

        Args:
            recipes: 本轮允许参与选择的完整Recipe集合。

        Returns:
            解析节点、阻塞列表和包含最终选择的共享解析状态。

        Side Effects:
            解析器会向返回的状态追加冻结节点和选择结果。
        """

        # 每个断言使用全新状态，避免上一轮选择缓存影响策略判断。
        state = StatefulPlanResolutionState(
            system_id=SYSTEM_ID,
            manifest=SimpleNamespace(source_scan_id=harness.scan_id),
            recipes=recipes,
            contracts={contract.fact_contract_id: contract},
            nodes=[],
            selected_recipes={},
            visiting=set(),
            resolved_nodes={},
        )
        blockers: list[object] = []
        node = compiler._resolve_stateful_requirement(state, requirement, blockers)
        return node, blockers, state

    preferred_node, preferred_blockers, preferred_state = resolve(
        (query_recipe, qtc_recipe)
    )
    assert preferred_node is not None
    assert preferred_blockers == []
    assert next(iter(preferred_state.selected_recipes.values())).recipe_id == (
        qtc_recipe.recipe_id
    )

    fallback_node, fallback_blockers, fallback_state = resolve((query_recipe,))
    assert fallback_node is not None
    assert fallback_blockers == []
    assert next(iter(fallback_state.selected_recipes.values())).recipe_id == (
        query_recipe.recipe_id
    )

    rejected_node, rejected_blockers, rejected_state = resolve((create_recipe,))
    assert rejected_node is None
    assert rejected_blockers == []
    assert rejected_state.selected_recipes == {}
    harness.application.close()


def test_unhandled_case_condition_fails_closed_while_diagnostic_does_not_block(
    tmp_path: Path,
) -> None:
    """无执行处理器的条件必须明确阻塞，内部诊断仍不得影响Ready。

    Args:
        tmp_path: Pytest隔离的Program与冻结清单资产根目录。

    Returns:
        None；异步条件得到稳定unsupported blocker且诊断条件无阻塞时通过。

    Side Effects:
        仅生成临时通用编译资产，不访问AI或QA。
    """

    harness = _compiler_harness(tmp_path, [])
    manifest = harness.application.preview_case_rules(SYSTEM_ID, ENTRY_ID).manifest
    async_condition = CaseCondition(
        condition_id="condition:generic:async-wait",
        condition_type=CaseConditionType.ASYNC_WAIT_CONDITION,
        title="等待通用异步结果",
        summary="业务结果需要等待异步状态完成。",
    )
    diagnostic = CaseCondition(
        condition_id="condition:generic:internal-diagnostic",
        condition_type=CaseConditionType.INTERNAL_DIAGNOSTIC,
        title="内部错误响应组装",
        summary="该证据不由入口字段控制。",
        resolution_owner=CaseConditionResolutionOwner.NONE,
    )
    fault_source = SourceReference(
        path="src/main/java/sample/ItemService.java",
        symbol="sample.ItemService#apply",
        line=20,
        commit="generic-compiler-v1",
    )
    fault_condition = CaseCondition(
        condition_id="condition:generic:fault-trigger",
        condition_type=CaseConditionType.FAULT_TRIGGER_REQUIREMENT,
        title="真实故障触发",
        summary="在指定业务调用处触发一次已发布故障。",
        evidence_ids=["evidence:fault:item-service"],
        source_refs=[fault_source],
    )
    unrelated_fault_condition = fault_condition.model_copy(
        update={
            "condition_id": "condition:generic:unrelated-fault-trigger",
            "evidence_ids": ["evidence:fault:unrelated-service"],
            "source_refs": [
                fault_source.model_copy(
                    update={"path": "src/main/java/sample/UnrelatedService.java"}
                )
            ],
        }
    )
    fault_obligation = FaultInjectionObligation(
        **_obligation_base("fault:item-service"),
        source_refs=[fault_source],
        target_operation="sample.ItemService#apply",
        invocation_positions=["FIRST"],
        expected_entity_states={
            "previous_entities": "SUCCESS",
            "current_entity": "FAILED",
            "remaining_entities": "NOT_EXECUTED",
        },
    )

    async_blockers = (
        harness.application.typed_case_compiler._condition_dispatch_blockers(
            manifest.model_copy(update={"conditions": [async_condition]})
        )
    )
    diagnostic_blockers = (
        harness.application.typed_case_compiler._condition_dispatch_blockers(
            manifest.model_copy(update={"conditions": [diagnostic]})
        )
    )
    fault_blockers = (
        harness.application.typed_case_compiler._condition_dispatch_blockers(
            manifest.model_copy(
                update={
                    "conditions": [fault_condition],
                    "obligations": [fault_obligation],
                }
            )
        )
    )
    unrelated_fault_blockers = (
        harness.application.typed_case_compiler._condition_dispatch_blockers(
            manifest.model_copy(
                update={
                    "conditions": [unrelated_fault_condition],
                    "obligations": [fault_obligation],
                }
            )
        )
    )

    assert {blocker.code for blocker in async_blockers} == {
        "BLOCKED_UNSUPPORTED_CASE_CONDITION"
    }
    assert diagnostic_blockers == []
    assert fault_blockers == []
    assert {blocker.code for blocker in unrelated_fault_blockers} == {
        "BLOCKED_UNSUPPORTED_CASE_CONDITION"
    }
    harness.application.close()


def test_typed_generators_preserve_exact_proofs_and_fault_blocker(tmp_path: Path) -> None:
    """Factor、Boundary、Decision、Sequence和Requirement应分别留证，Fault不得伪造Case字段。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    decision_evidence = _evidence(
        "evidence:decision:mode",
        "decision",
        condition="mode == M",
        outcomes=["TRUE", "FALSE"],
        field_paths=["mode"],
        decision_predicate=DecisionPredicate(
            operator="eq",
            input_path="mode",
            expected="M",
        ),
        outcome_expectations={"TRUE": True, "FALSE": False},
    )
    sequence_evidence = _evidence(
        "evidence:sequence:validation",
        "sequence",
        field_paths=["mode"],
        operation_ids=["validate", "route"],
        control_flow_path=["validate", "route"],
        activation_predicate=DecisionPredicate(
            operator="eq",
            input_path="mode",
            expected="A",
        ),
        binding_kind="same_path_resolved_calls",
    )
    obligations = [
        FactorObligation(
            **_obligation_base("factor:mode"),
            factor_path="mode",
            values=["A", "M"],
        ),
        BoundaryObligation(
            **_obligation_base("boundary:amount"),
            target_path="amount",
            boundaries=[0, 10],
        ),
        DecisionObligation(
            **_obligation_base("decision:mode"),
            condition="mode == M",
            outcomes=["TRUE", "FALSE"],
            input_vectors={
                "TRUE": {"mode": "M", "amount": 1},
                "FALSE": {"mode": "A", "amount": 1},
            },
            decision_evidence_id=decision_evidence.evidence_id,
            predicate=DecisionPredicate(operator="eq", input_path="mode", expected="M"),
            outcome_expectations={"TRUE": True, "FALSE": False},
        ),
        SequenceObligation(
            **_obligation_base("sequence:validation"),
            sequence=["validate", "route"],
            evidence_ids=[sequence_evidence.evidence_id],
            activation_predicate=DecisionPredicate(
                operator="eq",
                input_path="mode",
                expected="A",
            ),
            activation_vector={"mode": "A", "amount": 2},
        ),
        FaultInjectionObligation(
            **_obligation_base("fault:middle"),
            target_operation="sample.ItemService#apply",
            invocation_positions=["MIDDLE"],
            expected_entity_states={
                "previous_entities": "SUCCESS",
                "current_entity": "FAILED",
                "remaining_entities": "NOT_EXECUTED",
            },
        ),
        RequirementObligation(
            **_obligation_base("requirement:amount"),
            requirement_id="REQ-AMOUNT",
            statement="金额必须覆盖低值和正常值。",
            compile_target=RequirementFactorTarget(
                factor_path="amount",
                values=[1, 2],
            ),
        ),
    ]
    harness = _compiler_harness(
        tmp_path,
        obligations,
        evidence=[decision_evidence, sequence_evidence],
    )

    compilation = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    assert compilation.status == "WITH_BLOCKED"
    assert len(compilation.scenarios) == 1
    assert compilation.variants
    assert "BLOCKED_MISSING_FAULT_CAPABILITY" in {
        blocker.code for blocker in compilation.blockers
    }
    assert all("failurePosition" not in variant.factor_values for variant in compilation.variants)
    assert all(
        [node.role for node in scenario.template_key.execution_graph] == ["ACTION"]
        for scenario in compilation.scenarios
    )
    decision_outcomes = {
        proof.outcome
        for variant in compilation.variants
        for proof in variant.coverage_proof.decision_proofs
    }
    assert decision_outcomes == {"TRUE", "FALSE"}
    assert any(variant.coverage_proof.sequence_proofs for variant in compilation.variants)
    assert all(
        variant.factor_values.get("mode") == "A"
        for variant in compilation.variants
        if variant.coverage_proof.sequence_proofs
    )
    assert any(
        "obligation:requirement:amount" in variant.coverage_proof.requirement_obligation_ids
        for variant in compilation.variants
    )
    first = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )
    assert [item.scenario_id for item in first.scenarios] == [
        item.scenario_id for item in compilation.scenarios
    ]
    assert [item.variant_id for item in first.variants] == [
        item.variant_id for item in compilation.variants
    ]


def test_unproven_decision_and_collection_boundary_fail_closed(tmp_path: Path) -> None:
    """自然语言Decision和无元素来源的集合边界必须阻塞且不得生成空对象数组。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    evidence = _evidence(
        "evidence:decision:unproven",
        "decision",
        condition="items are special",
        outcomes=["TRUE", "FALSE"],
        field_paths=["mode"],
    )
    obligations = [
        DecisionObligation(
            **_obligation_base("decision:unproven"),
            condition="items are special",
            outcomes=["TRUE", "FALSE"],
            decision_evidence_id=evidence.evidence_id,
        ),
        BoundaryObligation(
            **_obligation_base("boundary:items"),
            target_path="items",
            boundaries=["EMPTY", "SINGLE", "MULTIPLE"],
            boundary_mode="collection_cardinality",
        ),
    ]
    harness = _compiler_harness(tmp_path, obligations, evidence=[evidence], include_items=True)

    compilation = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    codes = {blocker.code for blocker in compilation.blockers}
    assert "BLOCKED_DECISION_REACHABILITY_UNPROVEN" in codes
    assert "BLOCKED_BOUNDARY_ELEMENT_SOURCE_MISSING" in codes
    assert all(variant.factor_values.get("items") not in ([{}], [{}, {}]) for variant in compilation.variants)


def test_effect_observer_requires_direct_oracle_dependency_and_does_not_add_variants(tmp_path: Path) -> None:
    """跨系统Effect Observer必须是current READ_ONLY且有直接ORACLE依赖，附加后不扩组合。

    Args:
        tmp_path: Pytest隔离consumer/provider知识仓库。
    """

    evidence = _evidence(
        "evidence:effect:event",
        "effect",
        field_paths=["mode"],
        effect_kind="mq",
        effect_target="topic.generic.event",
        activation_predicate=DecisionPredicate(
            operator="eq",
            input_path="mode",
            expected="M",
        ),
        binding_kind="resolved_external_operation",
    )
    effect = EffectObligation(
        **_obligation_base("effect:event"),
        effect_kind="mq",
        effect_target="topic.generic.event",
        observation="观察通用事件数量。",
        effect_evidence_id=evidence.evidence_id,
    )
    factor = FactorObligation(
        **_obligation_base("factor:mode"),
        factor_path="mode",
        values=["A", "M"],
    )
    harness = _compiler_harness(tmp_path, [factor, effect], evidence=[evidence])
    observer = _publish_generic_observer(harness.application, tmp_path)
    _write_compilation_rules(
        harness.application,
        harness.action,
        harness.scan_id,
        oracle=OracleTemplate(
            oracle_template_id="oracle:generic-effect:v1",
            entry_id=ENTRY_ID,
            source_scan_id=harness.scan_id,
            action_capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id=harness.action.capability_id,
            ),
            effect_observations=[
                OracleEffectObservationTemplate(
                    effect_evidence_id=evidence.evidence_id,
                    effect_kind="mq",
                    effect_target="topic.generic.event",
                    observer_capability_ref=PublishedCapabilityRef(
                        system_id="generic-observer",
                        capability_id=observer.capability_id,
                    ),
                    input_bindings={
                        "scope": SafeConstantInputRef(value="ALL"),
                    },
                    assertions=[
                        OracleAssertionTemplate(
                            actual_source="observer_output",
                            actual_path="count",
                            expected=OracleExpression(operator="literal", value=1),
                        )
                    ],
                )
            ],
        ),
        suffix="v2",
    )

    blocked = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )
    harness.application.candidate_operations.put_dependency_binding(
        SYSTEM_ID,
        SystemDependencyBindingSubmission(
            provider_system_id="generic-observer",
            role=SystemDependencyRole.DOWNSTREAM,
            purposes=[SystemDependencyPurpose.ORACLE],
        ),
    )
    completed = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    assert "BLOCKED_EFFECT_OBSERVER_DEPENDENCY_MISSING" in {
        blocker.code for blocker in blocked.blockers
    }
    assert completed.status == "COMPLETED"
    assert len(completed.variants) == 2
    effects_by_mode = {
        variant.factor_values["mode"]: variant.coverage_proof.effect_obligation_ids
        for variant in completed.variants
    }
    assert effects_by_mode == {"A": [], "M": [effect.obligation_id]}


def test_write_action_compiles_static_cases_without_claiming_cleanup(tmp_path: Path) -> None:
    """阶段5只编译静态Case，资源回收由阶段8唯一选择正式CleanupPlan。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:mode"),
                factor_path="mode",
                values=["A", "M"],
            )
        ],
        mutability=OperationMutability.WRITE,
    )

    compilation = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    assert compilation.status == "COMPLETED"
    assert compilation.blockers == []
    assert len(compilation.scenarios) == 1
    assert len(compilation.variants) == 2
    assert compilation.scenarios[0].template_key.cleanup_plan_ref is None


def test_compilation_rules_reject_mutated_current_and_missing_history(tmp_path: Path) -> None:
    """Current规则改写或历史快照缺失时都不得继续生成Scenario。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    mutated = _compiler_harness(tmp_path / "mutated", [])
    current_path = (
        mutated.application.store.system_root(SYSTEM_ID)
        / "rules/case-compilation.yaml"
    )
    current_payload = yaml.safe_load(current_path.read_text(encoding="utf-8"))
    current_payload["action_profiles"][0]["resource_lifecycle_policy"] = "per_scenario"
    current_path.write_text(
        yaml.safe_dump(current_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    mutated_result = mutated.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    missing = _compiler_harness(tmp_path / "missing", [])
    rules = missing.application.case_compilation_rules.read(SYSTEM_ID)
    revision_path = (
        missing.application.store.system_root(SYSTEM_ID)
        / "rules/history"
        / f"{rules.rule_revision_id.replace(':', '--')}.yaml"
    )
    revision_path.unlink()
    missing_result = missing.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    assert {item.code for item in mutated_result.blockers} == {
        "BLOCKED_CASE_COMPILATION_RULES_INVALID"
    }
    assert {item.code for item in missing_result.blockers} == {
        "BLOCKED_CASE_COMPILATION_RULES_INVALID"
    }
    assert not mutated_result.variants
    assert not missing_result.variants


def test_forged_published_registry_entry_is_not_an_action(tmp_path: Path) -> None:
    """绕过发布服务写入Git的伪能力不得参与Action唯一性或Scenario生成。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:mode"),
                factor_path="mode",
                values=["A", "M"],
            )
        ],
    )
    forged = harness.action.model_copy(
        update={
            "capability_id": "published:generic-case-compiler:forged-v1",
            "publication_request_id": "generic.inspect.forged.v1",
            "draft_id": "capability-draft:generic.inspect.forged.v1",
            "provider_operation_ref": harness.action.provider_operation_ref.model_copy(
                update={"operation_id": "facade:missing.Operation#forged"}
            ),
        }
    )
    harness.application.published_capabilities.registry.publish(forged)

    compilation = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    assert len(harness.application.published_capability_registry(SYSTEM_ID).capabilities) == 2
    assert compilation.status == "COMPLETED"
    assert len(compilation.scenarios) == 1
    assert len(compilation.variants) == 2


def test_safe_constants_and_pairwise_coverage_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自由文本常量和遗漏合法值/Pair的选择器都必须在模型或生成边界失败。

    Args:
        monkeypatch: 临时替换Pairwise选择结果以模拟不完整实现。
    """

    with pytest.raises(ValidationError):
        SafeConstantInputRef(value="free-form-resource-id")
    with pytest.raises(ValidationError):
        SafeConstantInputRef(value={"resource_id": "forged"})
    with pytest.raises(ValidationError):
        CapabilityInputSourcePolicy(
            capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id="published:generic:identity-v1",
            ),
            input_path="resource_id",
            business_identity=True,
            allowed_sources=["generated"],
        )

    generator = ConstrainedPairwiseGenerator(PairwiseVariantSelector())
    monkeypatch.setattr(
        generator.selector,
        "select",
        lambda _dimensions, _predicate: [{"mode": "A", "channel": "WEB"}],
    )
    obligations = [
        FactorObligation(
            **_obligation_base("factor:mode"),
            factor_path="mode",
            values=["A", "M"],
        ),
        FactorObligation(
            **_obligation_base("factor:channel"),
            factor_path="channel",
            values=["WEB", "APP"],
            constraints=[
                FactorCombinationConstraint(
                    factor_path="channel",
                    operator="ne",
                    value="UNSUPPORTED",
                )
            ],
        ),
    ]
    with pytest.raises(KnowledgeValidationError, match="omitted"):
        generator.generate(obligations)


def test_pairwise_generator_scales_by_reachable_goals_not_cartesian_product() -> None:
    """三十个二值Factor应在有界时间内覆盖全部值与二元pair而不枚举笛卡尔积。

    Returns:
        None；断言输出证明目标完整且候选规模保持多项式级。
    """

    obligations = [
        FactorObligation(
            **_obligation_base(f"factor:{index:02d}"),
            factor_path=f"factor_{index:02d}",
            values=[False, True],
        )
        for index in range(30)
    ]
    started_at = time.monotonic()

    vectors = ConstrainedPairwiseGenerator().generate(obligations)

    elapsed = time.monotonic() - started_at
    value_goals = {goal for vector in vectors for goal in vector.factor_value_goals}
    pair_goals = {goal for vector in vectors for goal in vector.factor_pair_goals}
    assert elapsed < 15
    assert len(vectors) <= 1_800
    assert len(value_goals) == 60
    assert len(pair_goals) == 1_740


def test_sequence_activation_vector_cannot_override_analyzer_predicate(tmp_path: Path) -> None:
    """Sequence草稿提供的任意向量不得覆盖Analyzer证明的真实控制门控。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    predicate = DecisionPredicate(operator="eq", input_path="mode", expected="M")
    evidence = _evidence(
        "evidence:sequence:gated",
        "sequence",
        field_paths=["mode"],
        operation_ids=["validate", "route"],
        control_flow_path=["validate", "route"],
        activation_predicate=predicate,
        binding_kind="same_path_resolved_calls",
    )
    harness = _compiler_harness(
        tmp_path,
        [
            SequenceObligation(
                **_obligation_base("sequence:gated"),
                sequence=["validate", "route"],
                evidence_ids=[evidence.evidence_id],
                activation_predicate=predicate,
                activation_vector={"mode": "A"},
            )
        ],
        evidence=[evidence],
    )

    compilation = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    assert "BLOCKED_SEQUENCE_REACHABILITY_UNPROVEN" in {
        blocker.code for blocker in compilation.blockers
    }
    assert all(not variant.coverage_proof.sequence_proofs for variant in compilation.variants)


def test_oracle_factor_namespace_rejects_decision_only_input(tmp_path: Path) -> None:
    """Oracle的factor来源不得读取只有Decision生成、没有Factor义务的路径。

    Args:
        tmp_path: Pytest隔离知识仓库根目录。
    """

    predicate = DecisionPredicate(operator="eq", input_path="mode", expected="M")
    evidence = _evidence(
        "evidence:decision:oracle-namespace",
        "decision",
        condition="mode == M",
        outcomes=["TRUE", "FALSE"],
        field_paths=["mode"],
        decision_predicate=predicate,
        outcome_expectations={"TRUE": True, "FALSE": False},
    )
    harness = _compiler_harness(
        tmp_path,
        [
            DecisionObligation(
                **_obligation_base("decision:oracle-namespace"),
                condition=evidence.condition,
                outcomes=evidence.outcomes,
                input_vectors={"TRUE": {"mode": "M"}, "FALSE": {"mode": "A"}},
                decision_evidence_id=evidence.evidence_id,
                predicate=predicate,
                outcome_expectations=evidence.outcome_expectations,
            )
        ],
        evidence=[evidence],
    )
    _write_compilation_rules(
        harness.application,
        harness.action,
        harness.scan_id,
        oracle=OracleTemplate(
            oracle_template_id="oracle:generic-factor-namespace:v2",
            entry_id=ENTRY_ID,
            source_scan_id=harness.scan_id,
            action_capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id=harness.action.capability_id,
            ),
            assertions=[
                OracleAssertionTemplate(
                    actual_source="action_result",
                    actual_path="reference_id",
                    expected=OracleExpression(operator="factor", path="mode"),
                )
            ],
        ),
        suffix="v2",
    )

    compilation = harness.application.compile_typed_cases(
        SYSTEM_ID,
        TypedCaseCompileRequest(entry_id=ENTRY_ID),
    )

    assert "BLOCKED_ORACLE_EXPRESSION_TYPE_INVALID" in {
        blocker.code for blocker in compilation.blockers
    }
    assert not compilation.scenarios
    assert not compilation.variants


def test_real_refund_copy_uses_current_formal_facts_without_generated_attempt(tmp_path: Path) -> None:
    """正式退款知识副本必须读取current结构化事实且不能编造Scenario或Attempt。

    Args:
        tmp_path: 保存正式知识仓库只读副本的隔离目录。

    Returns:
        None；仅当current正式事实消除旧候选阻塞且没有执行副作用时通过。

    Side Effects:
        只复制知识到临时目录并读取编译结果；不访问QA或创建Attempt。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    application = OpenTestApplication(knowledge_copy)
    system_id = "ifightchainsaas.java.refund.core"
    entry_id = "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder"

    try:
        before_attempts = application.list_hybrid_case_attempts(system_id)
        compilation = application.compile_typed_cases(
            system_id,
            TypedCaseCompileRequest(entry_id=entry_id),
        )

        # createOrder的产出事实已由current源码证明；尚未发布Action Profile才是当前精确断点。
        assert {blocker.code for blocker in compilation.blockers} == {
            "BLOCKED_ACTION_PROFILE_MISSING",
        }
        assert compilation.scenarios == []
        assert compilation.variants == []
        assert application.list_hybrid_case_attempts(system_id) == before_attempts == []
    finally:
        application.close()


def _compiler_harness(
    tmp_path: Path,
    obligations: list[object] | None,
    evidence: list[SemanticCaseEvidence] | None = None,
    mutability: OperationMutability = OperationMutability.READ_ONLY,
    include_items: bool = False,
    resources: list[DiscoveredResource] | None = None,
) -> CompilerHarness:
    """建立读取真实registered/latest/Program/Published/规则资产的通用编译环境。

    Args:
        tmp_path: Pytest隔离根目录。
        obligations: 程序核心覆盖义务；``None``时由真实分析器从evidence生成。
        evidence: exact Java分析证据。
        mutability: Action读写属性。
        include_items: 是否在Action Schema中增加可选集合字段。
        resources: 可选由通用源码scan固定的资源证据。

    Returns:
        可直接调用公共编译API的真实Git资产环境。

    Side Effects:
        仅在临时目录写入通用源码、scan bundle、Published和编译规则。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    source_root = tmp_path / "source"
    source_file = source_root / "src/main/java/sample/AtomicFacade.java"
    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "package sample; "
        "interface AtomicFacade { AtomicResponse inspect(AtomicRequest request); } "
        "class AtomicRequest { String mode; Integer amount; java.util.List<String> items; } "
        "class AtomicResponse { Boolean accepted; String referenceId; } "
        "class AtomicFacadeImpl implements AtomicFacade { "
        "public AtomicResponse inspect(AtomicRequest request) { return new AtomicResponse(); } }\n",
        encoding="utf-8",
    )
    baseline = SourceBaseline(source_path=str(source_root), commit="generic-compiler-v1")
    application.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="通用编译系统", source_path=str(source_root))
    )
    source_ref = SourceReference(
        path=str(source_file),
        symbol=METHOD_ID,
        line=1,
        commit=baseline.commit,
    )
    interface_method = SemanticMethodDefinition(
        symbol_id=METHOD_ID,
        qualified_class_name="sample.AtomicFacade",
        method_name="inspect",
        parameter_names=["request"],
        parameter_types=["AtomicRequest"],
        parameter_qualified_types=["sample.AtomicRequest"],
        return_type="AtomicResponse",
        return_qualified_type="sample.AtomicResponse",
        owner_type_kind="interface",
        source_ref=source_ref,
        entry_point_ids=[ENTRY_ID],
    )
    implementation_method_id = "sample.AtomicFacadeImpl#inspect(sample.AtomicRequest)"
    implementation_method = interface_method.model_copy(
        update={
            "symbol_id": implementation_method_id,
            "qualified_class_name": "sample.AtomicFacadeImpl",
            "owner_interfaces": ["sample.AtomicFacade"],
            "owner_type_kind": "class",
            "has_executable_body": True,
            "source_ref": source_ref.model_copy(update={"symbol": implementation_method_id}),
        }
    )
    entry = EntryPoint(
        entry_id=ENTRY_ID,
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        display_name="AtomicFacade#inspect",
        source_id="sample.AtomicFacade#inspect",
        source_path=str(source_file),
        request_type="sample.AtomicRequest",
        response_type="sample.AtomicResponse",
    )
    scan_id = "scan-generic-compiler-v1"
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="generic-stage5-test",
        analyzer_version="1",
        system_id=SYSTEM_ID,
        methods=[interface_method, implementation_method],
        types=[
            SemanticTypeDefinition(
                symbol_id="sample.AtomicRequest",
                qualified_class_name="sample.AtomicRequest",
                simple_name="AtomicRequest",
                fields=[
                    SemanticFieldDefinition(
                        field_name="mode",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        runtime_required=True,
                        runtime_required_evidence=["jakarta.validation.constraints.NotBlank"],
                        source_ref=source_ref,
                    ),
                    SemanticFieldDefinition(
                        field_name="amount",
                        declared_type="Integer",
                        referenced_type="java.lang.Integer",
                        source_ref=source_ref,
                    ),
                    SemanticFieldDefinition(
                        field_name="items",
                        declared_type="java.util.List<String>",
                        referenced_type="java.lang.String",
                        collection=True,
                        source_ref=source_ref,
                    ),
                ],
                source_ref=source_ref,
            ),
            SemanticTypeDefinition(
                symbol_id="sample.AtomicResponse",
                qualified_class_name="sample.AtomicResponse",
                simple_name="AtomicResponse",
                fields=[
                    SemanticFieldDefinition(
                        field_name="accepted",
                        declared_type="Boolean",
                        referenced_type="java.lang.Boolean",
                        source_ref=source_ref,
                    ),
                    SemanticFieldDefinition(
                        field_name="referenceId",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        source_ref=source_ref,
                    ),
                ],
                source_ref=source_ref,
            ),
        ],
        case_evidence=evidence or [],
    )
    provider_ref = source_ref.model_copy(update={"symbol": "sample.AtomicFacade#inspect"})
    manifest = ScanManifest(
        scan_id=scan_id,
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[entry],
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            client_name="generic-case-compiler-client",
            routing_environment="qa",
            target_environment="test",
            status=DsfProfileStatus.CONFIRMED,
            source_refs=[provider_ref],
        ),
        dsf_operations=[
            DsfOperationDefinition(
                operation_id="dsf:generic-case-compiler:inspect",
                provider_system_id=SYSTEM_ID,
                gs_name="generic-case-compiler-service",
                service_name="sample.AtomicFacade",
                version="1.0.0",
                action="inspect",
                request_type="sample.AtomicRequest",
                response_type="sample.AtomicResponse",
                mutability=(
                    DsfOperationMutability.READ_ONLY
                    if mutability == OperationMutability.READ_ONLY
                    else DsfOperationMutability.WRITE
                ),
                source_refs=[provider_ref],
            )
        ],
        semantic_analysis=semantic,
        resources=resources or [],
    )
    if obligations is None:
        # 阶段6需验证全局故障规则消费的operations分析结果，不在测试中伪造义务。
        catalog = ProgramCaseAnalysisBuilder().build(manifest)
    else:
        artifact = ProgramCaseAnalysisArtifact(
            artifact_id="program-case-analysis:generic:inspect",
            system_id=SYSTEM_ID,
            source_scan_id=scan_id,
            source_baseline=baseline,
            entry_id=ENTRY_ID,
            entry_method_symbol_id=METHOD_ID,
            analyzer=semantic.analyzer,
            analyzer_version=semantic.analyzer_version,
            status="ANALYZED",
            evidence=evidence or [],
            core_obligations=obligations,
        )
        catalog = ProgramCaseAnalysisCatalog(
            system_id=SYSTEM_ID,
            source_scan_id=scan_id,
            source_baseline=baseline,
            analyzer=semantic.analyzer,
            analyzer_version=semantic.analyzer_version,
            artifacts=[artifact],
        )
    application.case_rules.artifacts.write_scan_bundle(manifest, catalog)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.case_rules.artifacts.publish_latest(SYSTEM_ID, scan_id)

    candidate = next(
        item
        for item in application.candidate_operations.catalog(SYSTEM_ID).candidates
        if item.entry_ids
    )
    operation = next(
        item
        for item in application.operation_catalog.derive(SYSTEM_ID)
        if item.source_entry_ids
    )
    properties = {
        "mode": {"type": "string"},
        "amount": {"type": "integer"},
    }
    if include_items:
        properties["items"] = {"type": "array", "items": {"type": "string"}}
    application.local_settings.write(
        SYSTEM_ID,
        "generic-stage5-local-token",
        "http://qa.example/gateway",
    )
    submission = CapabilityDraftSubmission(
        publication_request_id="generic.inspect.v1",
        candidate_ref=_candidate_ref(candidate),
        provider_operation_ref=ProviderOperationRef(
            source_system_id=SYSTEM_ID,
            operation_id=operation.operation_id,
            source_scan_id=operation.source_scan_id,
        ),
        business_name="执行通用检查",
        business_purpose="验证分型编译器的静态输入与输出契约。",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": ["mode"],
            "additionalProperties": False,
        },
        input_mapping={name: name for name in properties},
        output_fact_schema={
            "type": "object",
            "properties": {
                "accepted": {"type": "boolean"},
                "reference_id": {"type": "string"},
            },
            "required": ["accepted", "reference_id"],
            "additionalProperties": False,
        },
        output_mapping={
            "accepted": "output.accepted",
            "reference_id": "output.referenceId",
        },
    )
    publication = application.publish_operation_capability(SYSTEM_ID, submission)
    assert publication.status == "PUBLISHED", (
        publication.issues,
        candidate.model_dump(mode="json"),
        operation.model_dump(mode="json"),
    )
    assert publication.capability is not None
    action = publication.capability
    _write_compilation_rules(application, action, scan_id, include_items=include_items)
    return CompilerHarness(application=application, action=action, scan_id=scan_id)


def _write_compilation_rules(
    application: OpenTestApplication,
    action: PublishedOperationCapability,
    scan_id: str,
    oracle: OracleTemplate | None = None,
    suffix: str = "v1",
    include_items: bool = False,
) -> None:
    """写入一个只含服务器Action绑定与可选Oracle的不可变规则版本。

    Args:
        application: 规则所属consumer应用。
        action: 当前Entry的Published Action。
        scan_id: Profile精确绑定的latest scan。
        oracle: 可选Effect或Action Oracle模板。
        suffix: 新资产ID后缀，避免修改已有不可变资产。
        include_items: 是否授权可选集合Generated路径。

    Side Effects:
        发布consumer Git中的新规则历史和current指针。
    """

    action_ref = PublishedCapabilityRef(system_id=SYSTEM_ID, capability_id=action.capability_id)
    bindings = [
        ActionInputBindingTemplate(
            input_path="mode",
            source_ref=GeneratedInputRef(generated_path="mode"),
        ),
        ActionInputBindingTemplate(
            input_path="amount",
            source_ref=GeneratedInputRef(generated_path="amount"),
        ),
    ]
    if include_items:
        bindings.append(
            ActionInputBindingTemplate(
                input_path="items",
                source_ref=GeneratedInputRef(generated_path="items"),
            )
        )
    selected_oracle = oracle or OracleTemplate(
        oracle_template_id=f"oracle:generic-action:{suffix}",
        entry_id=ENTRY_ID,
        source_scan_id=scan_id,
        action_capability_ref=action_ref,
        assertions=[
            OracleAssertionTemplate(
                actual_source="action_result",
                actual_path="accepted",
                expected=OracleExpression(operator="literal", value=True),
            )
        ],
    )
    rules = CaseCompilationRuleSet(
        system_id=SYSTEM_ID,
        action_profiles=[
            CaseCompilationActionProfile(
                profile_id=f"action-profile:generic-inspect:{suffix}",
                entry_id=ENTRY_ID,
                source_scan_id=scan_id,
                action_capability_ref=action_ref,
                input_bindings=bindings,
                action_fact_contract=ActionFactContractDefinition(
                    fact_contract_id="generic_action_result/v1",
                    required_fields=[
                        SetupFactRequiredField(path="reference_id", schema_type="string")
                    ],
                    business_identity_paths=["reference_id"],
                ),
                oracle_template_id=selected_oracle.oracle_template_id,
                resource_lifecycle_policy="shared_read_only",
            )
        ],
        input_policies=[
            CapabilityInputSourcePolicy(
                capability_ref=action_ref,
                input_path=binding.input_path,
                allowed_sources=[binding.source_ref.source],
            )
            for binding in bindings
        ]
        + [
            CapabilityInputSourcePolicy(
                capability_ref=observation.observer_capability_ref,
                input_path=input_path,
                allowed_sources=[source.source],
                allowed_safe_constants=(
                    [source.value] if isinstance(source, SafeConstantInputRef) else []
                ),
            )
            for observation in selected_oracle.effect_observations
            for input_path, source in observation.input_bindings.items()
        ],
        oracle_templates=[selected_oracle],
    )
    application.case_compilation_rules.write(rules)


def _publish_generic_observer(
    application: OpenTestApplication,
    tmp_path: Path,
) -> PublishedOperationCapability:
    """为Effect测试注册独立provider scan和current READ_ONLY Published observer。

    Args:
        application: 已注册consumer的共享知识应用。
        tmp_path: Provider通用源码根目录。

    Returns:
        当前provider Candidate绑定的只读Published能力。

    Side Effects:
        注册第二个系统并发布其latest scan与Published registry。
    """

    system_id = "generic-observer"
    source_root = tmp_path / "observer-source"
    source_file = source_root / "src/main/java/sample/EventObserver.java"
    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "package sample; "
        "class ObserverRequest { String scope; } "
        "class ObserverResponse { Integer count; } "
        "class EventObserver { ObserverResponse count(ObserverRequest request) { "
        "return new ObserverResponse(); } }\n",
        encoding="utf-8",
    )
    baseline = SourceBaseline(source_path=str(source_root), commit="observer-v1")
    application.register_system(
        SystemDefinition(system_id=system_id, name="通用观察系统", source_path=str(source_root))
    )
    method_id = "sample.EventObserver#count(sample.ObserverRequest)"
    source_ref = SourceReference(
        path=str(source_file),
        symbol=method_id,
        line=1,
        commit=baseline.commit,
    )
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="generic-stage5-test",
        analyzer_version="1",
        system_id=system_id,
        methods=[
            SemanticMethodDefinition(
                symbol_id=method_id,
                qualified_class_name="sample.EventObserver",
                method_name="count",
                parameter_names=["request"],
                parameter_types=["ObserverRequest"],
                parameter_qualified_types=["sample.ObserverRequest"],
                return_type="ObserverResponse",
                return_qualified_type="sample.ObserverResponse",
                owner_type_kind="class",
                has_executable_body=True,
                source_ref=source_ref,
            )
        ],
        types=[
            SemanticTypeDefinition(
                symbol_id="sample.ObserverRequest",
                qualified_class_name="sample.ObserverRequest",
                simple_name="ObserverRequest",
                fields=[
                    SemanticFieldDefinition(
                        field_name="scope",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        runtime_required=True,
                        runtime_required_evidence=["jakarta.validation.constraints.NotBlank"],
                        source_ref=source_ref,
                    )
                ],
                source_ref=source_ref,
            ),
            SemanticTypeDefinition(
                symbol_id="sample.ObserverResponse",
                qualified_class_name="sample.ObserverResponse",
                simple_name="ObserverResponse",
                fields=[
                    SemanticFieldDefinition(
                        field_name="count",
                        declared_type="Integer",
                        referenced_type="java.lang.Integer",
                        source_ref=source_ref,
                    )
                ],
                source_ref=source_ref,
            ),
        ],
    )
    scan_id = "scan-generic-observer-v1"
    entry_id = "facade:sample.EventObserver#count"
    provider_ref = source_ref.model_copy(update={"symbol": "sample.EventObserver#count"})
    manifest = ScanManifest(
        scan_id=scan_id,
        system_id=system_id,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id=system_id,
                kind=KnowledgeNodeKind.FACADE,
                display_name="EventObserver#count",
                source_id="sample.EventObserver#count",
                source_path=str(source_file),
                request_type="sample.ObserverRequest",
                response_type="sample.ObserverResponse",
            )
        ],
        dsf_profile=DsfClientProfile(
            system_id=system_id,
            client_name="generic-observer-client",
            routing_environment="qa",
            target_environment="test",
            status=DsfProfileStatus.CONFIRMED,
            source_refs=[provider_ref],
        ),
        dsf_operations=[
            DsfOperationDefinition(
                operation_id="dsf:generic-observer:count",
                provider_system_id=system_id,
                gs_name="generic-observer-service",
                service_name="sample.EventObserver",
                version="1.0.0",
                action="count",
                request_type="sample.ObserverRequest",
                response_type="sample.ObserverResponse",
                mutability=DsfOperationMutability.READ_ONLY,
                source_refs=[provider_ref],
            )
        ],
        semantic_analysis=semantic,
    )
    application.case_rules.artifacts.write_scan_bundle(
        manifest,
        ProgramCaseAnalysisCatalog(
            system_id=system_id,
            source_scan_id=scan_id,
            source_baseline=baseline,
            analyzer=semantic.analyzer,
            analyzer_version=semantic.analyzer_version,
            artifacts=[
                ProgramCaseAnalysisArtifact(
                    artifact_id="program-case-analysis:generic:observer",
                    system_id=system_id,
                    source_scan_id=scan_id,
                    source_baseline=baseline,
                    entry_id=entry_id,
                    entry_method_symbol_id=method_id,
                    analyzer=semantic.analyzer,
                    analyzer_version=semantic.analyzer_version,
                    status="ANALYZED",
                )
            ],
        ),
    )
    application.store.update_source_baseline(system_id, baseline)
    application.case_rules.artifacts.publish_latest(system_id, scan_id)
    candidate = next(
        item
        for item in application.candidate_operations.catalog(system_id).candidates
        if item.entry_ids
    )
    operation = next(
        item
        for item in application.operation_catalog.derive(system_id)
        if item.source_entry_ids
    )
    application.local_settings.write(
        system_id,
        "generic-observer-local-token",
        "http://qa.example/gateway",
    )
    publication = application.publish_operation_capability(
        system_id,
        CapabilityDraftSubmission(
        publication_request_id="generic.observer.count.v1",
        candidate_ref=_candidate_ref(candidate),
        provider_operation_ref=ProviderOperationRef(
            source_system_id=system_id,
            operation_id=operation.operation_id,
            source_scan_id=operation.source_scan_id,
        ),
        business_name="查询通用事件计数",
        business_purpose="只读观察Effect是否发生。",
        input_schema={
            "type": "object",
            "properties": {"scope": {"type": "string"}},
            "required": ["scope"],
            "additionalProperties": False,
        },
        input_mapping={"scope": "scope"},
        output_fact_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        output_mapping={"count": "output.count"},
        ),
    )
    assert publication.status == "PUBLISHED", publication.issues
    assert publication.capability is not None
    return publication.capability


def _candidate_ref(candidate: object) -> CandidateRef:
    """冻结一个真实latest Candidate的完整源码和DTO身份。

    Args:
        candidate: CandidateOperation目录项。

    Returns:
        可供通用Published模型引用的不可变CandidateRef。
    """

    return CandidateRef(
        source_system_id=candidate.system_id,
        candidate_id=candidate.candidate_id,
        source_scan_id=candidate.source_scan_id,
        source_baseline=candidate.source_baseline,
        candidate_signature=candidate.method_signature,
        request_dto_types=candidate.request_dto_types,
        response_dto_type=candidate.response_dto_type,
        dto_definitions=candidate.dto_definitions,
        field_conversions=candidate.field_conversions,
    )


def _evidence(
    evidence_id: str,
    kind: str,
    **updates: object,
) -> SemanticCaseEvidence:
    """构造绑定通用Java方法和源码行的exact程序证据。

    Args:
        evidence_id: 稳定证据身份。
        kind: decision、sequence或effect证据类型。
        updates: 对应证据类型要求的结构化字段。

    Returns:
        可进入ProgramCaseAnalysisArtifact的严格证据。
    """

    return SemanticCaseEvidence(
        evidence_id=evidence_id,
        method_symbol_id=METHOD_ID,
        kind=kind,
        source_ref=SourceReference(
            path="src/main/java/sample/AtomicFacade.java",
            symbol=METHOD_ID,
            line=1,
            commit="generic-compiler-v1",
        ),
        **updates,
    )


def _obligation_base(suffix: str) -> dict[str, str]:
    """构造通用程序义务共享的可信系统和入口身份。

    Args:
        suffix: obligation ID中区分覆盖目标的后缀。

    Returns:
        Program artifact要求的服务端身份字段。
    """

    return {
        "obligation_id": f"obligation:{suffix}",
        "system_id": SYSTEM_ID,
        "entry_id": ENTRY_ID,
        "title": suffix,
        "origin": "program",
    }
