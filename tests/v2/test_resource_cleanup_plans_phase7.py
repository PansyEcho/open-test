"""验证阶段7只从真实scan、Published、Recipe和服务端规则发布Cleanup Plan。"""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from opentest.api import create_app
from opentest.application.cleanup_plans import CleanupPlanService
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    CleanupCandidateClassifier,
    CleanupBusinessIdentityRef,
    ConsumedByActionCleanupContract,
    CleanupContractRuleSet,
    CleanupEntryContract,
    CleanupExpectedField,
    CleanupIdentityContract,
    CleanupIdentityValueRef,
    CleanupOracleContract,
    CleanupPlanSubmission,
    CleanupSqlContract,
    CleanupSqlParameter,
    CaseCompilationRuleSet,
    DataSetupRecipeSubmission,
    DataSetupRecipeRef,
    DataSetupStep,
    DiscoveredResource,
    EntryFactAssertion,
    EntryFactKnowledge,
    KnowledgeConclusionSource,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeStatus,
    PublishedCapabilityRef,
    RecipeFactOutputSubmission,
    ResourceKind,
    ResourceRole,
    SafeConstantInputRef,
    SetupAvailabilityRule,
    SetupContractRuleSet,
    SetupEntityExtractionRule,
    SetupFactContractDefinition,
    SetupFactOrigin,
    SetupFactRequiredField,
    SetupInputBinding,
    SetupInputPolicy,
    SetupStatePredicateDefinition,
    SourceReference,
    SystemDependencyBindingSubmission,
    SystemDependencyPurpose,
    SystemDependencyRole,
)
from test_fault_injection_capabilities_phase6 import (
    PROVIDER_ID,
    Phase6Harness,
    _phase6_harness,
)
from test_typed_case_compiler_phase5 import (
    ENTRY_ID,
    SYSTEM_ID,
    _publish_generic_observer,
)


RESOURCE_ID = "mysql:generic-resource-state"
CONTRACT_ID = "generic_resource_cleanup/v1"


def test_identityless_qtc_cleanup_requires_dependency_anchored_final_query_fact() -> None:
    """无CREATE实体响应的Producer只能用依赖关系验证后的末次Query Fact回收。

    Returns:
        None；查询输入和输出关系闭合时允许最终Fact，去掉关系时拒绝。

    Side Effects:
        无；仅对通用typed Recipe对象执行纯校验。
    """

    query_ref = PublishedCapabilityRef(
        system_id=SYSTEM_ID,
        capability_id="published:generic-entity-query",
    )
    query_rule = SetupAvailabilityRule(type="VALUE_NOT_NULL", path="entity")
    extraction_rule = SetupEntityExtractionRule(type="VALUE", path="entity")
    initial_query = DataSetupStep(
        step_id="query-existing",
        capability_ref=query_ref,
        operation_role="QUERY",
        availability=query_rule,
        entity_extraction=extraction_rule,
    )
    create_step = DataSetupStep(
        step_id="create-entity",
        capability_ref=PublishedCapabilityRef(
            system_id=SYSTEM_ID,
            capability_id="published:generic-entity-create",
        ),
        operation_role="CREATE",
    )
    final_query = DataSetupStep(
        step_id="query-created",
        capability_ref=query_ref,
        operation_role="QUERY",
        input_bindings={
            "order_no": SetupInputBinding(
                source="fact",
                path="dependency_order.order_no",
            )
        },
        availability=query_rule,
        entity_extraction=extraction_rule,
    )
    fact = SimpleNamespace(
        fact_name="verified_entity",
        fact_contract_id="generic-entity/v1",
        from_step_id=final_query.step_id,
        relations={"order_no": "${dependency_order.order_no}"},
    )
    recipe = SimpleNamespace(
        acquisition_policy="QUERY_THEN_CREATE",
        steps=[initial_query, create_step, final_query],
        fact_outputs=[fact],
        requires_facts=[
            SimpleNamespace(
                slot_id="dependency_order",
                fact_contract_id="dependency-order/v1",
            )
        ],
    )
    dependency_contract = SetupFactContractDefinition(
        fact_contract_id="dependency-order/v1",
        required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
        required_fields=[
            SetupFactRequiredField(path="order_no", schema_type="string")
        ],
        business_identity_paths=["order_no"],
    )
    rules = SetupContractRuleSet(
        system_id=SYSTEM_ID,
        fact_contracts=[dependency_contract],
        input_policies=[
            SetupInputPolicy(
                capability_ref=query_ref,
                input_path="order_no",
                allowed_sources=["fact"],
                business_identity=True,
            )
        ],
    )

    anchored = CleanupPlanService._identityless_qtc_final_fact_is_safe(
        recipe,
        fact,
        final_query,
        rules,
    )
    unanchored = CleanupPlanService._identityless_qtc_final_fact_is_safe(
        recipe,
        SimpleNamespace(**{**vars(fact), "relations": {}}),
        final_query,
        rules,
    )

    assert anchored is True
    assert unanchored is False


def test_consumed_by_action_contract_requires_exact_setup_fact_identity() -> None:
    """Action消费终结只能绑定目标入口根Setup Fact，不能复用ActionFact身份。"""

    with pytest.raises(ValidationError, match="Setup Fact identity"):
        CleanupEntryContract(
            cleanup_contract_id="generic_consumed_action/v1",
            entry_id=ENTRY_ID,
            action_profile_id="action-profile:generic-inspect:v1",
            identity=CleanupIdentityContract(
                required_source="action_fact",
                fact_contract_id="generic_action_result/v1",
                fact_path="reference_id",
            ),
            consumed_by_action=ConsumedByActionCleanupContract(
                state_transition_assertion_id="entry-fact:generic-consumed-transition",
                oracle_actual_source="action_result",
                oracle_actual_path="accepted",
            ),
        )


def test_consumed_by_action_plan_requires_formal_transition_and_action_oracle(
    tmp_path: Path,
) -> None:
    """正式状态转换和current Action Oracle齐备时才能发布消费终结Plan。

    Args:
        tmp_path: Pytest隔离源码、知识、Recipe与Cleanup资产根目录。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=False)
    application = harness.application
    manifest = application.case_rules.artifacts.read(SYSTEM_ID, "latest")
    entry = next(item for item in manifest.entries if item.entry_id == ENTRY_ID)
    current_setup_rules = application.setup_contract_rules.read(SYSTEM_ID)
    current_fact = current_setup_rules.fact_contracts[0]
    stateful_fact = current_fact.model_copy(
        update={
            "fact_contract_id": "generic_consumable/v1",
            "business_identity_paths": ["firstOrdinal"],
            "state_path": "mode",
            "state_predicates": [
                SetupStatePredicateDefinition(name="AVAILABLE", allowed_values=["NORMAL"]),
                SetupStatePredicateDefinition(name="CONSUMED", allowed_values=["CONSUMED"]),
            ],
        }
    )
    stateful_rules = application.setup_contract_rules.write(
        current_setup_rules.model_copy(
            update={
                "rule_revision_id": "",
                "fact_contracts": [*current_setup_rules.fact_contracts, stateful_fact],
            }
        )
    )
    setup_ref = PublishedCapabilityRef(
        system_id=PROVIDER_ID,
        capability_id=harness.setup.capability_id,
    )
    recipe_id = "setup:generic-consumable-action"
    publication = application.publish_data_setup_recipe(
        SYSTEM_ID,
        DataSetupRecipeSubmission(
            recipe_id=recipe_id,
            entry_id=ENTRY_ID,
            entry_source_scan_id=manifest.scan_id,
            name="查询或建立可消费通用实体",
            steps=[
                DataSetupStep(
                    step_id="prepare-consumable",
                    capability_ref=setup_ref,
                    input_bindings={
                        "partition": SetupInputBinding(
                            source="literal",
                            value="QA_PARTITION",
                        )
                    },
                )
            ],
            fact_outputs=[
                RecipeFactOutputSubmission(
                    fact_name="consumable_entity",
                    fact_contract_id=stateful_fact.fact_contract_id,
                    from_step_id="prepare-consumable",
                    output_path="trigger",
                    constraints=[
                        {"path": "mode", "operator": "eq", "expected": "NORMAL"}
                    ],
                    produced_state="AVAILABLE",
                )
            ],
        ),
    )
    assert publication.status == "PUBLISHED", publication.issues
    assert publication.recipe is not None
    assert publication.recipe.setup_rule_revision_id == stateful_rules.rule_revision_id
    evidence = SourceReference(
        path=entry.source_path,
        symbol=entry.source_id,
        line=1,
        commit=manifest.baseline.commit,
    )
    transition = EntryFactAssertion(
        assertion_id="entry-fact:generic-consumed-transition",
        assertion_type="STATE_TRANSITION",
        fact_contract_id=stateful_fact.fact_contract_id,
        from_state="AVAILABLE",
        to_state="CONSUMED",
        source=KnowledgeConclusionSource.CODE_PROVEN,
        evidence_refs=[evidence],
    )
    application.store.write_node(
        KnowledgeNode(
            node_id=f"entry:{entry.source_id}",
            system_id=SYSTEM_ID,
            kind=KnowledgeNodeKind.FACADE,
            title=entry.display_name,
            aliases=[entry.entry_id, entry.source_id],
            status=KnowledgeStatus.CODE_VERIFIED,
            entry_fact_knowledge=EntryFactKnowledge(
                entry_id=entry.entry_id,
                source_scan_id=manifest.scan_id,
                source_baseline=manifest.baseline,
                state_transitions=[transition],
            ),
        ),
        "# Generic consumed action\n",
    )
    profile = application.case_compilation_rules.read(SYSTEM_ID).action_profiles[0]
    application.put_cleanup_contract_rules(
        SYSTEM_ID,
        CleanupContractRuleSet(
            system_id=SYSTEM_ID,
            contracts=[
                CleanupEntryContract(
                    cleanup_contract_id="generic_consumed_action/v1",
                    entry_id=ENTRY_ID,
                    action_profile_id=profile.profile_id,
                    identity=CleanupIdentityContract(
                        required_source="setup_fact",
                        fact_contract_id=stateful_fact.fact_contract_id,
                        fact_name="consumable_entity",
                        fact_path="firstOrdinal",
                    ),
                    consumed_by_action=ConsumedByActionCleanupContract(
                        state_transition_assertion_id=transition.assertion_id,
                        oracle_actual_source="action_result",
                        oracle_actual_path="accepted",
                    ),
                )
            ],
        ),
    )

    result = application.publish_cleanup_plan(
        SYSTEM_ID,
        CleanupPlanSubmission(
            cleanup_plan_id="cleanup:generic-consumed-action",
            entry_id=ENTRY_ID,
            source_scan_id=manifest.scan_id,
            setup_recipe_ref=DataSetupRecipeRef(
                system_id=SYSTEM_ID,
                recipe_id=recipe_id,
            ),
            cleanup_contract_id="generic_consumed_action/v1",
            name="目标Action消费通用实体",
        ),
    )

    assert result.status == "PUBLISHED", result.issues
    assert result.plan is not None
    assert result.plan.primary_strategy == "CONSUMED_BY_ACTION"
    assert result.plan.consumed_by_action is not None
    assert result.plan.recovery_oracle is None
    assert application.cleanup_plans.get_current(
        SYSTEM_ID,
        result.plan.cleanup_plan_id,
    ) == result.plan


def test_business_cancel_requires_exact_candidate_and_current_published(
    tmp_path: Path,
) -> None:
    """精确归类的取消Candidate未选Published时应阻塞，选中后优先业务取消。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=True)
    rules = harness.application.put_cleanup_contract_rules(
        SYSTEM_ID,
        _cleanup_rules(harness, include_classifier=True),
    )
    missing = harness.application.publish_cleanup_plan(
        SYSTEM_ID,
        _submission(harness, "cleanup:generic-missing-cancel"),
    )
    published = harness.application.publish_cleanup_plan(
        SYSTEM_ID,
        _submission(
            harness,
            "cleanup:generic-business-cancel",
            include_cancel=True,
        ),
    )

    assert missing.status == "BLOCKED"
    assert {item.code for item in missing.issues} >= {
        "CLEANUP_CANCEL_CAPABILITY_NOT_PUBLISHED"
    }
    assert published.status == "PUBLISHED", published.issues
    assert published.plan is not None
    assert published.plan.primary_strategy == "BUSINESS_CANCEL"
    assert published.plan.sql_update is None
    assert published.plan.business_cancel is not None
    assert published.plan.business_cancel.capability_ref.capability_id == harness.rollback.capability_id
    assert published.plan.business_identity.source_ref.source == "action_fact"
    assert published.plan.business_identity.source_ref.fact_path == "reference_id"
    assert published.plan.cleanup_rule_revision_id == rules.rule_revision_id
    assert harness.application.cleanup_plan_catalog(SYSTEM_ID).plans == [published.plan]
    # current授权撤销不能破坏冻结Plan的历史可读性；第8阶段执行前再重验授权。
    harness.application.put_system_dependency_binding(
        SYSTEM_ID,
        SystemDependencyBindingSubmission(
            provider_system_id=PROVIDER_ID,
            role=SystemDependencyRole.UPSTREAM,
            purposes=[SystemDependencyPurpose.SETUP, SystemDependencyPurpose.FAULT],
        ),
    )
    assert harness.application.get_cleanup_plan(
        SYSTEM_ID,
        published.plan.cleanup_plan_id,
    ) == published.plan
    assert not (harness.application.knowledge_root / ".opentest/operation-executions").exists()
    assert not (harness.application.knowledge_root / ".opentest/case-attempts").exists()


def test_sql_strategy_is_server_derived_and_counts_non_first_business_key(
    tmp_path: Path,
) -> None:
    """无CLEANUP候选范围时才允许规则SQL，且按真实占位符顺序定位业务键。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=False)
    harness.application.put_cleanup_contract_rules(
        SYSTEM_ID,
        _cleanup_rules(harness, include_classifier=False),
    )
    result = harness.application.publish_cleanup_plan(
        SYSTEM_ID,
        _submission(harness, "cleanup:generic-sql-recovery"),
    )

    assert result.status == "PUBLISHED", result.issues
    assert result.plan is not None
    assert result.plan.primary_strategy == "SQL_UPDATE"
    assert result.plan.business_cancel is None
    assert result.plan.sql_update is not None
    assert [item.name for item in result.plan.sql_update.parameters] == [
        "restored_status",
        "tenant_scope",
        "resource_key",
    ]
    assert result.plan.sql_update.business_key_parameter == "resource_key"
    assert result.plan.recovery_oracle.projection == ["status"]


def test_unclassified_cleanup_candidate_blocks_sql_fallback(tmp_path: Path) -> None:
    """CLEANUP范围内看似rollback的Candidate未精确归类时不得改走SQL。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=True)
    harness.application.put_cleanup_contract_rules(
        SYSTEM_ID,
        _cleanup_rules(harness, include_classifier=False),
    )
    result = harness.application.publish_cleanup_plan(
        SYSTEM_ID,
        _submission(harness, "cleanup:generic-unclassified-cancel"),
    )

    assert result.status == "BLOCKED"
    assert {item.code for item in result.issues} >= {
        "CLEANUP_CANCEL_CONTRACT_INCOMPLETE"
    }
    assert harness.application.cleanup_plan_catalog(SYSTEM_ID).plans == []


@pytest.mark.parametrize("method_name", ["removeOrder", "releaseResource", "rollbackOrder"])
def test_cleanup_name_prefixes_only_block_sql_fallback(
    tmp_path: Path,
    method_name: str,
) -> None:
    """remove/release/rollback前缀只能提示未分类并阻塞SQL。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
        method_name: 本次保守发现方法名。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=True)
    candidate = harness.application.candidate_operations.get(
        PROVIDER_ID,
        harness.rollback.candidate_ref.candidate_id,
    )
    renamed = candidate.model_copy(
        update={"qualified_name": f"sample.FaultSupportFacade#{method_name}"}
    )

    assert harness.application.cleanup_plans._looks_like_cleanup(renamed) is True


def test_publication_blocks_provider_scope_expansion_before_provider_read(
    tmp_path: Path,
) -> None:
    """预读后Action provider扩张时必须在读取新provider资产前阻塞。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=False)
    harness.application.put_cleanup_contract_rules(
        SYSTEM_ID,
        _cleanup_rules(harness, include_classifier=False),
    )
    observer = _publish_generic_observer(harness.application, tmp_path)
    current_rules = harness.application.case_compilation_rules.read(SYSTEM_ID)
    current_profile = current_rules.action_profiles[0]
    expanded_rules = CaseCompilationRuleSet(
        system_id=SYSTEM_ID,
        action_profiles=[
            current_profile.model_copy(
                update={
                    "action_capability_ref": current_profile.action_capability_ref.model_copy(
                        update={
                            "system_id": observer.system_id,
                            "capability_id": observer.capability_id,
                        }
                    )
                }
            )
        ],
        input_policies=current_rules.input_policies,
        oracle_templates=current_rules.oracle_templates,
    )
    original_transaction = harness.application.store.multi_system_transaction
    changed = False

    @contextmanager
    def change_scope_before_lock(system_ids: list[str] | set[str]) -> Iterator[None]:
        """在服务预读后、真正取得原锁集合前切换Action provider。

        Args:
            system_ids: Cleanup服务预读形成的旧事务集合。

        Yields:
            原multi-system事务上下文。

        Side Effects:
            首次进入时只改consumer Case compilation current规则。
        """

        nonlocal changed
        if not changed:
            changed = True
            harness.application.case_compilation_rules.write(expanded_rules)
        with original_transaction(system_ids):
            yield

    harness.application.store.multi_system_transaction = change_scope_before_lock
    result = harness.application.publish_cleanup_plan(
        SYSTEM_ID,
        _submission(harness, "cleanup:generic-scope-expansion"),
    )

    assert result.status == "BLOCKED"
    assert {item.code for item in result.issues} == {
        "CLEANUP_PUBLICATION_SCOPE_CHANGED"
    }
    assert harness.application.cleanup_plan_catalog(SYSTEM_ID).plans == []


def test_plan_snapshot_rejects_business_cancel_to_sql_tampering(tmp_path: Path) -> None:
    """current Plan即使改成同Contract SQL，也必须因偏离首次快照而拒绝。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=True)
    source_rules = _cleanup_rules(harness, include_classifier=True)
    harness.application.put_cleanup_contract_rules(SYSTEM_ID, source_rules)
    published = harness.application.publish_cleanup_plan(
        SYSTEM_ID,
        _submission(harness, "cleanup:generic-tamper", include_cancel=True),
    )
    assert published.plan is not None
    contract = source_rules.contracts[0]
    assert contract.sql_contract is not None
    plan_path = (
        harness.application.store.system_root(SYSTEM_ID)
        / "recipes/cleanup/cleanup--generic-tamper.yaml"
    )
    payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    payload["primary_strategy"] = "SQL_UPDATE"
    payload["business_cancel"] = None
    payload["sql_update"] = harness.application.cleanup_plans._materialize_sql(
        contract.sql_contract
    ).model_dump(mode="json")
    plan_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeValidationError, match="integrity"):
        harness.application.get_cleanup_plan(SYSTEM_ID, published.plan.cleanup_plan_id)


def test_cleanup_business_identity_rejects_container_schema() -> None:
    """业务资源身份不得以同顶层类型但不同内部结构的容器进入取消输入。"""

    with pytest.raises(ValidationError, match="scalar fact schema"):
        CleanupBusinessIdentityRef(
            source_ref={
                "source": "action_fact",
                "fact_contract_id": "generic_action_result/v1",
                "fact_path": "reference_id",
            },
            fact_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        )


@pytest.mark.parametrize(
    ("update_statement", "oracle_statement", "expected_code"),
    [
        (
            "UPDATE resource_state SET status = ? WHERE tenant = ? OR resource_id = ?",
            "SELECT status FROM resource_state WHERE tenant = ? AND resource_id = ?",
            "CLEANUP_SQL_UNSAFE",
        ),
        (
            "UPDATE resource_state SET status = ? WHERE tenant = ? AND resource_id = ?; DELETE FROM resource_state",
            "SELECT status FROM resource_state WHERE tenant = ? AND resource_id = ?",
            "CLEANUP_SQL_UNSAFE",
        ),
        (
            "UPDATE resource_state SET status = ? WHERE tenant = ? AND resource_id = ?",
            "SELECT * FROM resource_state WHERE tenant = ? AND resource_id = ?",
            "CLEANUP_ORACLE_UNSAFE",
        ),
    ],
)
def test_rules_reject_unsafe_sql_and_oracle(
    tmp_path: Path,
    update_statement: str,
    oracle_statement: str,
    expected_code: str,
) -> None:
    """OR、多语句和SELECT star必须在规则发布边界失败。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
        update_statement: 本次反例UPDATE。
        oracle_statement: 本次反例Oracle SELECT。
        expected_code: 预期稳定错误码。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=False)
    rules = _cleanup_rules(
        harness,
        include_classifier=False,
        update_statement=update_statement,
        oracle_statement=oracle_statement,
    )

    with pytest.raises(KnowledgeValidationError, match=expected_code):
        harness.application.put_cleanup_contract_rules(SYSTEM_ID, rules)
    assert harness.application.get_cleanup_contract_rules(SYSTEM_ID).contracts == []


def test_api_rejects_client_sql_fact_and_isolation_injection(tmp_path: Path) -> None:
    """Plan API必须在严格模型边界拒绝客户端SQL、业务主键和隔离策略。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=False)
    payload = _submission(harness, "cleanup:generic-api-strict").model_dump(mode="json")
    payload.update(
        {
            "sql_update": {"statement": "UPDATE forged SET state = ?"},
            "business_identity": {"source": "fixture", "value": "forged-id"},
            "isolation_policy": {"isolation_key_fact_path": "fixture.order_no"},
        }
    )

    with TestClient(create_app(harness.application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/cleanup-plans",
            json=payload,
        )

    assert response.status_code == 422
    rejected = {item["loc"][-1] for item in response.json()["detail"]}
    assert rejected >= {"sql_update", "business_identity", "isolation_policy"}


def test_real_refund_knowledge_copy_rejects_missing_recipe_without_asset_mutation(
    tmp_path: Path,
) -> None:
    """真实Refund即使已有正式资产也不得用不存在的Recipe生成Cleanup Plan。

    Args:
        tmp_path: 真实知识最小临时副本目标目录。

    Returns:
        None；无效引用保持阻塞且不改写复制前已有能力、Recipe或Cleanup。

    Side Effects:
        仅在临时真实知识副本提交一个无效Cleanup草稿，不访问QA。
    """

    project_root = Path(__file__).resolve().parents[2]
    source_root = project_root / "open-test-knowledge"
    target_root = tmp_path / "refund-knowledge-copy"
    manifest_payload = json.loads(
        (
            source_root
            / ".opentest/scans/ifightchainsaas.java.refund.core/latest.json"
        ).read_text(encoding="utf-8")
    )
    scan_id = manifest_payload["scan_id"]
    formal_system_id = "ifightchainsaas.java.refund.core"
    _copy_refund_truth(source_root, target_root, scan_id)
    application = OpenTestApplication(target_root)
    system_id = "ifightchainsaas.java.refund.core"
    published_before = application.published_capabilities.list(formal_system_id).capabilities
    recipes_before = application.data_setup_recipes.list(formal_system_id).recipes
    cleanups_before = application.cleanup_plan_catalog(formal_system_id).plans
    manifest = application.case_rules.artifacts.read(system_id, "latest")
    entry_id = next(
        item.entry_id
        for item in manifest.entries
        if item.entry_id.endswith("RefundFacade#createOrder")
    )

    result = application.publish_cleanup_plan(
        system_id,
        CleanupPlanSubmission(
            cleanup_plan_id="cleanup:real-refund-create-order",
            entry_id=entry_id,
            source_scan_id=manifest.scan_id,
            setup_recipe_ref=DataSetupRecipeRef(
                system_id=system_id,
                recipe_id="setup:missing-real-booking-order",
            ),
            cleanup_contract_id="refund_create_order_cleanup/v1",
            name="真实退票创建资源回收",
        ),
    )

    assert application.published_capabilities.list(system_id).capabilities == published_before
    assert application.data_setup_recipes.list(system_id).recipes == recipes_before
    assert result.status == "BLOCKED"
    assert {item.code for item in result.issues} == {"CLEANUP_PUBLICATION_SCOPE_INVALID"}
    assert application.cleanup_plan_catalog(system_id).plans == cleanups_before


def _cleanup_harness(tmp_path: Path, include_cleanup_dependency: bool) -> Phase6Harness:
    """建立带真实scan资源、Published Action、Setup Recipe和取消Candidate的通用环境。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
        include_cleanup_dependency: 是否把provider纳入直接CLEANUP候选范围。

    Returns:
        阶段6正式资产与阶段7所需DB资源环境。
    """

    source_path = tmp_path / "source/src/main/java/sample/AtomicFacade.java"
    resource = DiscoveredResource(
        resource_id=RESOURCE_ID,
        system_id=SYSTEM_ID,
        kind=ResourceKind.MYSQL,
        role=ResourceRole.DATABASE,
        logical_name="generic-resource-state",
        config_keys=["generic.datasource"],
        source_refs=[
            SourceReference(
                path=str(source_path),
                symbol="sample.AtomicFacade#inspect",
                line=1,
                commit="generic-compiler-v1",
            )
        ],
    )
    harness = _phase6_harness(tmp_path, resources=[resource])
    purposes = [SystemDependencyPurpose.SETUP, SystemDependencyPurpose.FAULT]
    if include_cleanup_dependency:
        purposes.append(SystemDependencyPurpose.CLEANUP)
    harness.application.put_system_dependency_binding(
        SYSTEM_ID,
        SystemDependencyBindingSubmission(
            provider_system_id=PROVIDER_ID,
            role=SystemDependencyRole.UPSTREAM,
            purposes=purposes,
        ),
    )
    return harness


def _cleanup_rules(
    harness: Phase6Harness,
    include_classifier: bool,
    update_statement: str = "UPDATE resource_state SET status = ? WHERE tenant = ? AND resource_id = ?",
    oracle_statement: str = "SELECT status FROM resource_state WHERE tenant = ? AND resource_id = ?",
) -> CleanupContractRuleSet:
    """从current rollback Candidate和Action profile构造服务端Cleanup规则。

    Args:
        harness: 正式Published和scan资产环境。
        include_classifier: 是否精确归类rollback Candidate。
        update_statement: 服务端UPDATE规则。
        oracle_statement: 服务端Oracle规则。

    Returns:
        不含运行时业务主键值的Cleanup规则。
    """

    application = harness.application
    candidate = application.candidate_operations.get(
        PROVIDER_ID,
        harness.rollback.candidate_ref.candidate_id,
    )
    profile = application.case_compilation_rules.read(SYSTEM_ID).action_profiles[0]
    classifiers = (
        [
            CleanupCandidateClassifier(
                classifier_id="generic.rollback.release",
                source_system_id=PROVIDER_ID,
                qualified_name=candidate.qualified_name,
                method_signature=candidate.method_signature,
            )
        ]
        if include_classifier
        else []
    )
    return CleanupContractRuleSet(
        system_id=SYSTEM_ID,
        classifiers=classifiers,
        contracts=[
            CleanupEntryContract(
                cleanup_contract_id=CONTRACT_ID,
                entry_id=ENTRY_ID,
                action_profile_id=profile.profile_id,
                identity=CleanupIdentityContract(
                    required_source="action_fact",
                    fact_contract_id="generic_action_result/v1",
                    fact_path="reference_id",
                ),
                cancel_classifier_ids=(
                    ["generic.rollback.release"] if include_classifier else []
                ),
                cancel_input_bindings=(
                    {"mock_key": CleanupIdentityValueRef()}
                    if include_classifier
                    else {}
                ),
                sql_contract=CleanupSqlContract(
                    resource_id=RESOURCE_ID,
                    table_name="resource_state",
                    update_statement=update_statement,
                    update_parameters=[
                        CleanupSqlParameter(
                            name="restored_status",
                            source_ref=SafeConstantInputRef(value="RELEASED"),
                        ),
                        CleanupSqlParameter(
                            name="tenant_scope",
                            source_ref=SafeConstantInputRef(value="QA"),
                        ),
                        CleanupSqlParameter(
                            name="resource_key",
                            source_ref=CleanupIdentityValueRef(),
                        ),
                    ],
                    set_columns=["status"],
                    business_key_column="resource_id",
                    business_key_parameter="resource_key",
                ),
                recovery_oracle=CleanupOracleContract(
                    resource_id=RESOURCE_ID,
                    table_name="resource_state",
                    statement=oracle_statement,
                    parameters=[
                        CleanupSqlParameter(
                            name="tenant_scope",
                            source_ref=SafeConstantInputRef(value="QA"),
                        ),
                        CleanupSqlParameter(
                            name="resource_key",
                            source_ref=CleanupIdentityValueRef(),
                        ),
                    ],
                    business_key_column="resource_id",
                    business_key_parameter="resource_key",
                    projection=["status"],
                    expected_fields=[
                        CleanupExpectedField(
                            field_name="status",
                            expected=SafeConstantInputRef(value="RELEASED"),
                        )
                    ],
                ),
            )
        ],
    )


def _submission(
    harness: Phase6Harness,
    cleanup_plan_id: str,
    include_cancel: bool = False,
) -> CleanupPlanSubmission:
    """构造不包含SQL和业务主键值的最小Cleanup Plan草稿。

    Args:
        harness: 正式Recipe和Published资产环境。
        cleanup_plan_id: 不可变Plan版本ID。
        include_cancel: 是否提交正式业务取消能力引用。

    Returns:
        只定位服务端资产的严格草稿。
    """

    return CleanupPlanSubmission(
        cleanup_plan_id=cleanup_plan_id,
        entry_id=ENTRY_ID,
        source_scan_id=harness.target.candidate_ref.source_scan_id,
        setup_recipe_ref=DataSetupRecipeRef(
            system_id=SYSTEM_ID,
            recipe_id=harness.recipe_id,
        ),
        cleanup_contract_id=CONTRACT_ID,
        name="通用资源回收",
        business_cancel_capability_ref=(
            {
                "system_id": PROVIDER_ID,
                "capability_id": harness.rollback.capability_id,
            }
            if include_cancel
            else None
        ),
    )


def _copy_refund_truth(source_root: Path, target_root: Path, scan_id: str) -> None:
    """复制真实Refund注册、source、latest scan及实际存在的正式能力资产。

    Args:
        source_root: 项目当前真实知识仓库。
        target_root: Pytest隔离知识副本。
        scan_id: current Refund latest扫描ID。

    Side Effects:
        仅复制真实文件并把副本registry缩小为同一个真实系统定义。
    """

    system_id = "ifightchainsaas.java.refund.core"
    target_registry = target_root / "registry"
    target_system = target_root / "systems" / system_id
    target_scans = target_root / ".opentest/scans" / system_id
    target_registry.mkdir(parents=True)
    target_system.mkdir(parents=True)
    target_scans.mkdir(parents=True)
    source_registry = yaml.safe_load(
        (source_root / "registry/systems.yaml").read_text(encoding="utf-8")
    )
    system_definition = next(
        item for item in source_registry["systems"] if item["system_id"] == system_id
    )
    (target_registry / "systems.yaml").write_text(
        yaml.safe_dump({"systems": [system_definition]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    shutil.copy2(source_root / "systems" / system_id / "source.yaml", target_system / "source.yaml")
    dependencies = source_root / "systems" / system_id / "dependencies.yaml"
    if dependencies.exists():
        shutil.copy2(dependencies, target_system / "dependencies.yaml")
    for directory_name in ("capabilities", "recipes", "rules"):
        source_directory = source_root / "systems" / system_id / directory_name
        if source_directory.exists():
            # 正式资产目录若出现，必须原样进入副本，禁止选择性省略以制造BLOCKED。
            shutil.copytree(source_directory, target_system / directory_name)
    shutil.copy2(
        source_root / ".opentest/scans" / system_id / "latest.json",
        target_scans / "latest.json",
    )
    for suffix in (".json", ".case-analysis.json"):
        source = source_root / ".opentest/scans" / system_id / f"{scan_id}{suffix}"
        if source.exists():
            shutil.copy2(source, target_scans / source.name)
