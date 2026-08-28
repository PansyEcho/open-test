"""验证阶段8只编排正式资产，并在任何QA调用前完成可信预检。"""

from __future__ import annotations

import fcntl
import multiprocessing
import shutil
import stat
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.case_execution_v3 import (
    CaseExecutionContext,
    FixedResourceInvocation,
    PublishedInvocationResult,
    _StatefulSetupRunState,
)
from opentest.application.foundation import OpenTestApplication
from opentest.adapters.resource_quarantine_store import ResourceQuarantineStore
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.models import (
    ActionInputBindingTemplate,
    CaseCompilationActionProfile,
    CaseCompilationAssetDraft,
    CaseCompilationRuleSet,
    CaseGenerationDraftBundle,
    CaseGenerationHandoff,
    CaseGenerationHandoffStatus,
    CaseSemanticDraft,
    CaseVariantExecutionRequest,
    CleanupBusinessIdentityRef,
    CleanupPlan,
    ConsumedByActionCleanupProof,
    FaultCapabilityDraftSubmission,
    FaultCapabilityKind,
    FaultPlanningRequest,
    FactorObligation,
    HybridCaseGenerationRecord,
    HybridCaseGenerationRequest,
    OperationMutability,
    PublishedCapabilityRef,
    PublishedOperationCapability,
    ResourceQuarantineRecord,
    SetupFactInputRef,
    SystemDefinition,
    SystemDependencyBindingSubmission,
    SystemDependencyPurpose,
    SystemDependencyRole,
)
from test_data_setup_recipes_phase4 import (
    CONSUMER_ID as RECIPE_CONSUMER_ID,
    FACT_CONTRACT_ID,
    _prepare_workspace,
    _recipe_submission,
)
from test_fault_injection_capabilities_phase6 import _phase6_harness
from test_resource_cleanup_plans_phase7 import (
    _cleanup_harness,
    _cleanup_rules,
    _submission as _cleanup_submission,
)
from test_typed_case_compiler_phase5 import (
    ENTRY_ID,
    SYSTEM_ID,
    _compiler_harness,
    _obligation_base,
)


class QaInvocationProbe:
    """记录预检失败后是否错误触达了Published或资源QA边界。"""

    def __init__(self) -> None:
        """初始化零调用计数且不配置任何provider结果。"""

        self.calls = 0


    def invoke(
        self,
        capability: PublishedOperationCapability,
        arguments: dict[str, Any],
        execution_key: str,
        environment: str,
        timeout_seconds: int,
    ) -> PublishedInvocationResult:
        """在测试中把任何Published QA调用视为可信边界违规。

        Args:
            capability: 不应被调用的Published能力。
            arguments: 不应被发送的provider参数。
            execution_key: 不应生成的QA幂等键。
            environment: 固定QA环境。
            timeout_seconds: 调用超时。

        Raises:
            AssertionError: 预检失败后执行器仍触达QA。
        """

        del capability, arguments, execution_key, environment, timeout_seconds
        self.calls += 1
        raise AssertionError("preflight blocker must prevent Published QA invocation")

    def invoke_resource(
        self,
        request: FixedResourceInvocation,
        execution_key: str,
        environment: str,
        timeout_seconds: int,
    ) -> PublishedInvocationResult:
        """在测试中把任何Cleanup资源调用视为可信边界违规。

        Args:
            request: 不应执行的固定资源请求。
            execution_key: 不应生成的QA幂等键。
            environment: 固定QA环境。
            timeout_seconds: 调用超时。

        Raises:
            AssertionError: 预检失败后执行器仍触达QA资源。
        """

        del request, execution_key, environment, timeout_seconds
        self.calls += 1
        raise AssertionError("preflight blocker must prevent resource QA invocation")


def test_consumed_by_action_finalization_reuses_passed_action_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Action和Oracle均通过时只登记消费证明，不再次调用QA回收操作。

    Args:
        tmp_path: Pytest隔离应用和隔离记录目录。
        monkeypatch: 将任何旧Cleanup策略调用变成测试失败。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    plan = CleanupPlan.model_construct(
        cleanup_plan_id="cleanup:generic-consumed-action",
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        source_scan_id=harness.scan_id,
        setup_recipe_ref={"system_id": SYSTEM_ID, "recipe_id": "setup:generic-consumed"},
        name="目标Action消费实体",
        cleanup_contract_id="generic_consumed_action/v1",
        cleanup_rule_revision_id="cleanup-rule-revision:" + "a" * 32,
        compilation_rule_revision_id="case-compilation-rule-revision:" + "b" * 32,
        action_profile_id="action-profile:generic-inspect:v1",
        action_capability_ref={
            "system_id": SYSTEM_ID,
            "capability_id": harness.action.capability_id,
        },
        action_fact_contract_id="generic_action_result/v1",
        resource_scope="ACTION_EFFECT",
        business_identity=CleanupBusinessIdentityRef(
            source_ref=SetupFactInputRef(
                fact_contract_id="generic_consumable/v1",
                fact_path="entity_id",
            ),
            fact_schema={"type": "string"},
            fact_name="consumable_entity",
        ),
        primary_strategy="CONSUMED_BY_ACTION",
        business_cancel=None,
        sql_update=None,
        consumed_by_action=ConsumedByActionCleanupProof(
            state_transition_assertion_id="entry-fact:generic-consumed-transition",
            fact_contract_id="generic_consumable/v1",
            from_state="AVAILABLE",
            to_state="CONSUMED",
            oracle_template_id="oracle:generic-consumed",
            oracle_actual_source="action_result",
            oracle_actual_path="accepted",
            oracle_expected_value=True,
        ),
        recovery_oracle=None,
        isolation_policy={"action": "QUARANTINE_RESOURCE", "block_reuse": True},
    )
    context = CaseExecutionContext(
        attempt_id=f"attempt-{'c' * 20}",
        environment="qa",
        timeout_seconds=30,
        fixture={},
        setup_facts_by_contract={"generic_consumable/v1": {"entity_id": "entity-1"}},
        action_may_have_written=True,
        action_completed=True,
        oracle_completed=True,
    )

    def reject_legacy_strategy(*_args: Any, **_kwargs: Any) -> None:
        """若消费终结仍发起旧Cleanup调用则立即失败。"""

        raise AssertionError("consumed-by-action must not invoke a second cleanup operation")

    monkeypatch.setattr(service, "_execute_cleanup_strategy", reject_legacy_strategy)

    failures = service._finalize_one_cleanup(plan, context)
    expected_evidence = []
    service._append_expected_cleanup_plan_evidence(
        expected_evidence,
        SimpleNamespace(capabilities={}),
        plan,
    )

    assert failures == (None, None, None)
    assert context.evidence[-1].stage == "CLEANUP"
    assert context.evidence[-1].status == "PASSED"
    assert len(expected_evidence) == 1
    assert expected_evidence[0].subject_id == plan.cleanup_plan_id
    assert not expected_evidence[0].operation_id


def test_consumed_by_action_finalization_blocks_without_passed_oracle(
    tmp_path: Path,
) -> None:
    """Action虽已调用但Oracle未通过时不得登记消费完成。

    Args:
        tmp_path: Pytest隔离应用和隔离记录目录。
    """

    harness = _compiler_harness(tmp_path, [])
    plan = CleanupPlan.model_construct(
        cleanup_plan_id="cleanup:generic-unproven-consumption",
        system_id=SYSTEM_ID,
        business_identity=CleanupBusinessIdentityRef(
            source_ref=SetupFactInputRef(
                fact_contract_id="generic_consumable/v1",
                fact_path="entity_id",
            ),
            fact_schema={"type": "string"},
            fact_name="consumable_entity",
        ),
        primary_strategy="CONSUMED_BY_ACTION",
        consumed_by_action=ConsumedByActionCleanupProof(
            state_transition_assertion_id="entry-fact:generic-consumed-transition",
            fact_contract_id="generic_consumable/v1",
            from_state="AVAILABLE",
            to_state="CONSUMED",
            oracle_template_id="oracle:generic-consumed",
            oracle_actual_source="action_result",
            oracle_actual_path="accepted",
            oracle_expected_value=True,
        ),
    )
    context = CaseExecutionContext(
        attempt_id=f"attempt-{'d' * 20}",
        environment="qa",
        timeout_seconds=30,
        fixture={},
        setup_facts_by_contract={"generic_consumable/v1": {"entity_id": "entity-2"}},
        action_may_have_written=True,
        action_completed=True,
        oracle_completed=False,
    )

    cleanup, oracle, _quarantine = (
        harness.application.case_execution_v3._finalize_one_cleanup(plan, context)
    )

    assert cleanup is not None
    assert cleanup.code == "BLOCKED_CONSUMED_BY_ACTION_UNPROVEN"
    assert oracle is None
    assert not any(
        evidence.stage == "CLEANUP" and evidence.status == "PASSED"
        for evidence in context.evidence
    )


def test_consumed_by_action_generation_requires_root_state_to_be_non_reusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generation只接受覆盖根谓词且目标状态不再可复用的Action消费证明。

    Args:
        tmp_path: Pytest隔离Generation服务依赖。
        monkeypatch: 固定exact Recipe和其Fact contract历史版本。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.hybrid_case_generation
    recipe_ref = SimpleNamespace(system_id=SYSTEM_ID, recipe_id="setup:generic-consumed")
    recipe = SimpleNamespace(
        system_id=SYSTEM_ID,
        recipe_id=recipe_ref.recipe_id,
        setup_rule_revision_id="setup-rule-revision:" + "a" * 32,
    )
    fact_contract = SimpleNamespace(
        fact_contract_id="generic_consumable/v1",
        state_predicates=[
            SimpleNamespace(name="AVAILABLE", allowed_values=["READY", "WAITING"]),
            SimpleNamespace(name="CONSUMED", allowed_values=["DONE"]),
        ],
    )
    monkeypatch.setattr(service.recipes, "get", lambda *_args: recipe)
    monkeypatch.setattr(
        service.recipes.rules,
        "read_revision",
        lambda *_args: SimpleNamespace(fact_contracts=[fact_contract]),
    )
    root = SimpleNamespace(
        slot_id="consumable",
        recipe_ref=recipe_ref,
        fact_contract_id=fact_contract.fact_contract_id,
        output_fact_name="consumable_entity",
        required_state="AVAILABLE",
    )
    scenario = SimpleNamespace(
        template_key=SimpleNamespace(
            stateful_setup_plan=SimpleNamespace(
                root_slot_ids=[root.slot_id],
                nodes=[root],
            )
        )
    )
    identity = CleanupBusinessIdentityRef(
        source_ref=SetupFactInputRef(
            fact_contract_id=fact_contract.fact_contract_id,
            fact_path="entity_id",
        ),
        fact_schema={"type": "string"},
        fact_name="consumable_entity",
    )
    proof = ConsumedByActionCleanupProof(
        state_transition_assertion_id="entry-fact:generic-consumed-transition",
        fact_contract_id=fact_contract.fact_contract_id,
        from_state="AVAILABLE",
        to_state="CONSUMED",
        oracle_template_id="oracle:generic-consumed",
        oracle_actual_source="action_result",
        oracle_actual_path="accepted",
        oracle_expected_value=True,
    )
    plan = SimpleNamespace(
        primary_strategy="CONSUMED_BY_ACTION",
        consumed_by_action=proof,
        business_identity=identity,
        setup_recipe_ref=recipe_ref,
    )

    assert service._action_consumption_matches(scenario, plan) is True
    reusable_target = plan.consumed_by_action.model_copy(update={"to_state": "AVAILABLE"})
    assert service._action_consumption_matches(
        scenario,
        SimpleNamespace(**{**plan.__dict__, "consumed_by_action": reusable_target}),
    ) is False


def test_qtc_create_keeps_producer_cleanup_when_action_did_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QTC创建实体后Action未运行时仍必须执行冻结Producer Cleanup。

    Args:
        tmp_path: Pytest隔离Attempt服务和隔离记录目录。
        monkeypatch: 只记录终结Plan选择，不调用任何QA能力。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    node = SimpleNamespace(
        node_id="stateful-node:qtc-created",
        slot_id="consumable",
    )
    producer_plan = CleanupPlan.model_construct(
        cleanup_plan_id="cleanup:generic-producer",
        system_id=SYSTEM_ID,
        resource_scope="STATEFUL_PRODUCER",
        business_identity=CleanupBusinessIdentityRef(
            source_ref=SetupFactInputRef(
                fact_contract_id="generic_consumable/v1",
                fact_path="entity_id",
                slot_id=node.slot_id,
            ),
            fact_schema={"type": "string"},
            fact_name="created_entity",
        ),
        primary_strategy="BUSINESS_CANCEL",
    )
    action_plan = producer_plan.model_copy(
        update={
            "cleanup_plan_id": "cleanup:generic-action-consumption",
            "resource_scope": "ACTION_EFFECT",
            "primary_strategy": "CONSUMED_BY_ACTION",
        }
    )
    assets = SimpleNamespace(
        scenario=SimpleNamespace(
            template_key=SimpleNamespace(
                stateful_setup_plan=SimpleNamespace(nodes=[node])
            )
        ),
        cleanup_plan=action_plan,
        stateful_cleanup_plans={node.node_id: producer_plan},
    )
    context = CaseExecutionContext(
        attempt_id=f"attempt-{'e' * 20}",
        environment="qa",
        timeout_seconds=30,
        fixture={},
        resource_may_exist=True,
        action_may_have_written=False,
        stateful_created_node_ids={node.node_id},
    )
    finalized_plan_ids: list[str] = []

    def record_finalization(
        plan: CleanupPlan,
        _context: CaseExecutionContext,
    ) -> tuple[None, None, None]:
        """记录运行期真正选择的Plan且不触达任何外部边界。"""

        finalized_plan_ids.append(plan.cleanup_plan_id)
        return None, None, None

    monkeypatch.setattr(service, "_finalize_one_cleanup", record_finalization)

    failures = service._finalize_cleanup(assets, context)

    assert failures == (None, None, None)
    assert finalized_plan_ids == [producer_plan.cleanup_plan_id]

    # 同一QTC分支只有Action和Oracle均通过后，才允许消费证明替代Producer二次回收。
    finalized_plan_ids.clear()
    context.action_may_have_written = True
    context.action_completed = True
    context.oracle_completed = True
    failures = service._finalize_cleanup(assets, context)

    assert failures == (None, None, None)
    assert finalized_plan_ids == [action_plan.cleanup_plan_id]


def test_runtime_snapshot_locks_distinct_stateful_producer_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """执行预检必须在读取Producer知识前锁定其独立源码系统。

    Args:
        tmp_path: Pytest隔离的通用Generation和资产根目录。
        monkeypatch: 捕获多系统事务集合而不访问其他系统或QA。

    Returns:
        None；consumer、能力provider、依赖provider和Producer source均被锁定时通过。

    Side Effects:
        仅建立临时应用并替换其事务上下文；不会创建Attempt或调用Published能力。
    """

    harness = _compiler_harness(tmp_path, [])
    producer_node = SimpleNamespace(
        producer_entry_ref=SimpleNamespace(system_id="generic-producer-source")
    )
    plan = SimpleNamespace(nodes=[producer_node])
    scenario = SimpleNamespace(
        scenario_id="scenario:lock-scope",
        variant_ids=["variant:lock-scope"],
        template_key=SimpleNamespace(stateful_setup_plan=plan),
    )
    variant = SimpleNamespace(
        scenario_id=scenario.scenario_id,
        variant_id=scenario.variant_ids[0],
    )
    generation = SimpleNamespace(
        system_id=SYSTEM_ID,
        generation_id="hybrid-generation-00000000000000000000",
        scenarios=[scenario],
        variants=[variant],
        capability_proofs=[
            SimpleNamespace(
                capability_ref=SimpleNamespace(system_id="generic-step-provider")
            )
        ],
        dependency_proofs=[
            SimpleNamespace(provider_system_id="generic-dependency-provider")
        ],
    )
    captured_system_ids: set[str] = set()

    @contextmanager
    def capture_transaction(system_ids: set[str]):
        """记录执行预检申请的完整系统集合并继续进入只读验证。"""

        captured_system_ids.update(system_ids)
        yield

    catalog = harness.application.case_execution_v3.catalog
    knowledge_store = catalog.capabilities.registry.knowledge_store
    monkeypatch.setattr(
        knowledge_store,
        "multi_system_transaction",
        capture_transaction,
    )

    with pytest.raises(KnowledgeNotFoundError):
        catalog.current_assets(generation, scenario, variant)

    assert captured_system_ids == {
        SYSTEM_ID,
        "generic-step-provider",
        "generic-dependency-provider",
        "generic-producer-source",
    }


def _hold_stateful_lock_file(
    lock_path: str,
    ready: Any,
    release: Any,
) -> None:
    """在独立进程持有状态实体文件锁以验证跨进程串行边界。

    Args:
        lock_path: 父进程按正式锁键派生的隔离文件路径。
        ready: 通知父进程文件锁已持有的进程事件。
        release: 允许子进程结束持锁的进程事件。

    Returns:
        None。

    Side Effects:
        在Pytest临时Attempt目录打开并暂时持有一个POSIX文件锁。
    """

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock_file:
        # 只有实际取得主机锁后才通知父进程，避免进程调度导致假阳性。
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        ready.set()
        release.wait(timeout=10)


def _stateful_lock_assets(harness: Any, acquisition_policy: str) -> Any:
    """构造只包含一个查询型状态实体节点的最小冻结运行资产。

    Args:
        harness: 通用编译测试夹具，提供正式Published能力身份。
        acquisition_policy: QUERY_ONLY、QUERY_THEN_CREATE或CREATE_ONLY。

    Returns:
        可直接交给状态实体串行门禁的只读运行资产投影。
    """

    query_ref = PublishedCapabilityRef(
        system_id=SYSTEM_ID,
        capability_id="published:generic-state-lock-query",
    )
    query_capability = harness.action.model_copy(
        update={
            "capability_id": query_ref.capability_id,
            "mutability": OperationMutability.READ_ONLY,
        }
    )
    node = SimpleNamespace(
        node_id="stateful-node:generic-lock",
        fact_contract_id="generic-entity/v1",
    )
    recipe = SimpleNamespace(
        acquisition_policy=acquisition_policy,
        steps=[
            SimpleNamespace(
                operation_role="QUERY",
                capability_ref=query_ref,
            )
        ],
    )
    return SimpleNamespace(
        scenario=SimpleNamespace(
            template_key=SimpleNamespace(
                stateful_setup_plan=SimpleNamespace(nodes=[node]),
            )
        ),
        stateful_recipes={node.node_id: recipe},
        capabilities={
            (query_ref.system_id, query_ref.capability_id): query_capability,
        },
    )


def _add_quarantine_in_process(
    runtime_root: str,
    system_id: str,
    suffix: str,
    start_event: Any,
) -> None:
    """在独立进程同时追加一条隔离记录以验证跨进程读改写。

    Args:
        runtime_root: 多个进程共享的本地运行时根目录。
        system_id: 隔离记录所属通用测试系统。
        suffix: 构造互不相同资源键和Attempt身份的十六进制字符。
        start_event: 父进程统一释放并发写入的同步事件。

    Side Effects:
        等待父进程信号后向共享Quarantine文件追加一条记录。
    """

    if not start_event.wait(timeout=10):
        raise RuntimeError("quarantine concurrency test start timed out")
    store = ResourceQuarantineStore(runtime_root)
    store.add(
        ResourceQuarantineRecord(
            quarantine_id=f"quarantine-{suffix * 20}",
            system_id=system_id,
            cleanup_plan_id="cleanup:generic-multiprocess",
            isolation_fact_path="resource_id",
            resource_key=f"resource-{suffix}",
            reason_code="CLEANUP_FAILED",
            attempt_id=f"attempt-{suffix * 20}",
        )
    )


def test_entry_only_api_generates_complete_factor_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API只凭Entry生成完整Factor账本，READY路径不得调用Codex或QA。

    Args:
        tmp_path: Pytest隔离源码、Git知识和本地运行目录。
        monkeypatch: 将Codex创建线程替换为一旦调用即失败的边界探针。

    Returns:
        None；程序独立完成覆盖生成且外部调用均为零时通过。

    Side Effects:
        只写Pytest临时Generation；不创建Codex线程、Attempt或QA请求。
    """

    obligation = FactorObligation(
        **_obligation_base("factor:mode"),
        factor_path="mode",
        values=["A", "M"],
    )
    harness = _compiler_harness(tmp_path, [obligation])
    qa_probe = QaInvocationProbe()
    harness.application.case_execution_v3.invoker = qa_probe

    def reject_codex_thread_creation(*args: Any, **kwargs: Any) -> Any:
        """READY Generation误进入AI路径时立即失败。

        Args:
            *args: 不应出现的Codex线程位置参数。
            **kwargs: 不应出现的Codex线程命名参数。

        Raises:
            AssertionError: READY生成错误调用Codex。
        """

        del args, kwargs
        raise AssertionError("READY generation must not create a Codex thread")

    monkeypatch.setattr(
        harness.application.codex_app_server,
        "create_thread",
        reject_codex_thread_creation,
    )

    with TestClient(create_app(harness.application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v3/systems/{SYSTEM_ID}/case-generations",
            json={"entry_id": ENTRY_ID},
        )

    assert response.status_code == 201
    result = response.json()["result"]
    assert result["status"] == "READY"
    generation = result["generation"]
    assert generation["status"] == "READY"
    assert len(generation["scenarios"]) == 1
    assert {variant["factor_values"]["mode"] for variant in generation["variants"]} == {
        "A",
        "M",
    }
    resolution = generation["obligation_resolutions"][0]
    assert resolution["obligation_id"] == obligation.obligation_id
    assert resolution["status"] == "GENERATED"
    assert set(resolution["variant_ids"]) == {
        variant["variant_id"] for variant in generation["variants"]
    }
    assert qa_probe.calls == 0
    assert harness.application.list_hybrid_case_attempts(SYSTEM_ID) == []


def test_entry_only_api_rejects_client_asset_injection(tmp_path: Path) -> None:
    """V3请求夹带Action、Recipe、Cleanup或Fixture时不得写任何资产。

    Args:
        tmp_path: Pytest隔离知识根目录。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:preflight-mode"),
                factor_path="mode",
                values=["A", "M"],
            )
        ],
    )
    payload = {
        "entry_id": ENTRY_ID,
        "action_capability_id": harness.action.capability_id,
        "data_setup_recipe_id": "setup:client-forged",
        "cleanup_plan_id": "cleanup:client-forged",
        "fixture": {"resource_id": "client-business-key"},
    }

    with TestClient(create_app(harness.application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v3/systems/{SYSTEM_ID}/case-generations",
            json=payload,
        )

    assert response.status_code == 422
    assert {item["loc"][-1] for item in response.json()["detail"]} >= {
        "action_capability_id",
        "data_setup_recipe_id",
        "cleanup_plan_id",
        "fixture",
    }
    assert harness.application.list_hybrid_case_generations(SYSTEM_ID) == []
    assert harness.application.list_hybrid_case_attempts(SYSTEM_ID) == []


def test_generation_first_publication_detects_valid_yaml_mutation(tmp_path: Path) -> None:
    """Generation当前文件即使仍符合模型，也必须与首次发布快照完全一致。

    Args:
        tmp_path: Pytest隔离知识根目录。
    """

    harness = _compiler_harness(tmp_path, [])
    generation = harness.application.hybrid_case_generation.generate(
        SYSTEM_ID,
        HybridCaseGenerationRequest(entry_id=ENTRY_ID),
    )
    path = (
        harness.application.store.system_root(SYSTEM_ID)
        / "cases/v3/generations"
        / f"{generation.generation_id}.yaml"
    )
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["analyzer_version"] = "tampered-but-valid"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeValidationError, match="first publication"):
        harness.application.get_hybrid_case_generation(
            SYSTEM_ID,
            generation.generation_id,
        )


def test_current_asset_drift_writes_blocked_attempt_without_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Published current证明漂移时只写PREFLIGHT BLOCKED且QA调用为零。

    Args:
        tmp_path: Pytest隔离知识与Attempt目录。
        monkeypatch: 在Generation后模拟真实current能力漂移。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:preflight-mode"),
                factor_path="mode",
                values=["A", "M"],
            )
        ],
    )
    generation = harness.application.hybrid_case_generation.generate(
        SYSTEM_ID,
        HybridCaseGenerationRequest(entry_id=ENTRY_ID),
    )
    variant = generation.variants[0]
    probe = QaInvocationProbe()
    harness.application.case_execution_v3.invoker = probe

    def reject_stale_capability(system_id: str, capability_id: str) -> None:
        """模拟预检读取到Candidate或Provider已经不再current。

        Args:
            system_id: owning-system Published范围。
            capability_id: Generation冻结的能力身份。

        Raises:
            KnowledgeValidationError: 固定表达current证明漂移。
        """

        del system_id, capability_id
        raise KnowledgeValidationError("published capability is not current")

    monkeypatch.setattr(
        harness.application.published_capabilities,
        "get_current",
        reject_stale_capability,
    )
    attempt = harness.application.execute_hybrid_case_variant(
        SYSTEM_ID,
        variant.variant_id,
        CaseVariantExecutionRequest(generation_id=generation.generation_id),
    )

    assert attempt.status == "BLOCKED"
    assert attempt.primary_failure is not None
    assert attempt.primary_failure.stage == "PREFLIGHT"
    assert attempt.step_evidence[0].stage == "PREFLIGHT"
    assert probe.calls == 0
    persisted = harness.application.list_hybrid_case_attempts(
        SYSTEM_ID,
        generation.generation_id,
        variant.variant_id,
    )
    assert persisted == [attempt]


def test_missing_runtime_binding_blocks_attempt_before_running_or_qa(tmp_path: Path) -> None:
    """Published可离线生成，但所选环境缺Token时必须在PREFLIGHT零调用阻塞。

    Args:
        tmp_path: Pytest隔离知识、环境配置、Attempt和Operation记录根目录。
    """

    harness = _compiler_harness(
        tmp_path,
        [
            FactorObligation(
                **_obligation_base("factor:runtime-binding"),
                factor_path="mode",
                values=["A", "M"],
            )
        ],
    )
    generation = harness.application.hybrid_case_generation.generate(
        SYSTEM_ID,
        HybridCaseGenerationRequest(entry_id=ENTRY_ID),
    )
    variant = generation.variants[0]
    harness.application.local_settings.write(
        SYSTEM_ID,
        "",
        "http://qa.example/gateway",
    )
    probe = QaInvocationProbe()
    harness.application.case_execution_v3.invoker = probe

    attempt = harness.application.execute_hybrid_case_variant(
        SYSTEM_ID,
        variant.variant_id,
        CaseVariantExecutionRequest(
            generation_id=generation.generation_id,
            environment="qa",
        ),
    )

    assert attempt.status == "BLOCKED"
    assert attempt.primary_failure is not None
    assert attempt.primary_failure.stage == "PREFLIGHT"
    assert "BLOCKED_EXECUTION_LOCAL_BINDING_MISSING" in attempt.primary_failure.message
    assert attempt.step_evidence[0].stage == "PREFLIGHT"
    assert all(item.stage == "PREFLIGHT" for item in attempt.step_evidence)
    assert probe.calls == 0
    execution_root = (
        harness.application.knowledge_root
        / ".opentest/runtime"
        / SYSTEM_ID
        / "operation-executions"
    )
    assert not execution_root.exists() or not list(execution_root.rglob("*.yaml"))


@pytest.mark.parametrize(
    (
        "initial_result",
        "initial_status",
        "initial_availability",
        "expected_roles",
        "expected_failure",
    ),
    [
        (
            {"entity": {"id": "existing", "state": "READY"}},
            "PASSED",
            None,
            ["QUERY"],
            None,
        ),
        (
            {"entity": None},
            "PASSED",
            None,
            ["QUERY", "DEPENDENCY_QUERY", "CREATE", "QUERY"],
            None,
        ),
        ({}, "FAILED", None, ["QUERY"], "SETUP_FAILED"),
        (
            {"result_code": "NOT_FOUND"},
            "PASSED",
            SimpleNamespace(
                type="RESULT_CODE_MAP",
                path="result_code",
                found_values=["FOUND"],
                not_found_values=["NOT_FOUND"],
            ),
            ["QUERY"],
            "SETUP_STATEFUL_QUERY_PROTOCOL_FAILED",
        ),
    ],
)
def test_stateful_query_then_create_uses_only_explicit_miss_for_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_result: dict[str, Any],
    initial_status: str,
    initial_availability: Any | None,
    expected_roles: list[str],
    expected_failure: str | None,
) -> None:
    """QTC命中跳过CREATE，明确miss才创建，provider失败不得触发fallback。

    Args:
        tmp_path: Pytest隔离的执行服务与Attempt存储根目录。
        monkeypatch: 用内存Published结果验证分支，不触达QA。
        initial_result: 首次查询的逻辑输出。
        initial_status: 首次Published调用状态。
        initial_availability: 可选首次查询判定；为空时使用结构型非空判定。
        expected_roles: 应执行的冻结步骤角色序列。
        expected_failure: 预期Setup失败码；成功路径为空。

    Returns:
        None；三类分支严格遵守冻结QTC语义时通过。

    Side Effects:
        只修改测试内存上下文，不写真实Operation或业务实体。

    Notes:
        七个参数由pytest参数化共同描述一个分支用例，彼此没有可复用领域生命周期；
        保持显式字段比为单个测试引入一次性参数对象更容易核对安全边界。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    query_ref = PublishedCapabilityRef(
        system_id=SYSTEM_ID,
        capability_id="published:generic-state-query",
    )
    create_ref = PublishedCapabilityRef(
        system_id=SYSTEM_ID,
        capability_id="published:generic-state-create",
    )
    dependency_query_ref = PublishedCapabilityRef(
        system_id=SYSTEM_ID,
        capability_id="published:generic-dependency-query",
    )
    query_capability = harness.action.model_copy(
        update={
            "capability_id": query_ref.capability_id,
            "mutability": OperationMutability.READ_ONLY,
        }
    )
    create_capability = harness.action.model_copy(
        update={
            "capability_id": create_ref.capability_id,
            "mutability": OperationMutability.WRITE,
        }
    )
    dependency_query_capability = harness.action.model_copy(
        update={
            "capability_id": dependency_query_ref.capability_id,
            "mutability": OperationMutability.READ_ONLY,
        }
    )
    query_step = SimpleNamespace(
        step_id="query-existing",
        operation_role="QUERY",
        capability_ref=query_ref,
        input_bindings={},
        availability=(
            initial_availability
            or SimpleNamespace(type="VALUE_NOT_NULL", path="entity")
        ),
        availability_assertion_id="",
        entity_extraction=SimpleNamespace(type="VALUE", path="entity"),
    )
    create_step = SimpleNamespace(
        step_id="create-new",
        operation_role="CREATE",
        capability_ref=create_ref,
        input_bindings={},
        availability=None,
        entity_extraction=None,
    )
    final_query_step = SimpleNamespace(
        step_id="query-created",
        operation_role="QUERY",
        capability_ref=query_ref,
        input_bindings={},
        availability=SimpleNamespace(type="VALUE_NOT_NULL", path="entity"),
        entity_extraction=SimpleNamespace(type="VALUE", path="entity"),
    )
    created_fact = SimpleNamespace(
        fact_name="created_entity",
        fact_contract_id="generic-entity/v1",
        from_step_id="create-new",
        output_path="created",
        fact_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "state": {"type": "string"},
            },
            "required": ["id", "state"],
        },
        constraints=[],
    )
    final_fact = SimpleNamespace(
        fact_name="verified_entity",
        fact_contract_id="generic-entity/v1",
        from_step_id="query-created",
        output_path="entity",
        fact_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "state": {"type": "string"},
            },
            "required": ["id", "state"],
        },
        constraints=[],
    )
    recipe = SimpleNamespace(
        acquisition_policy="QUERY_THEN_CREATE",
        steps=[query_step, create_step, final_query_step],
        fact_outputs=[created_fact, final_fact],
    )
    dependency_step = SimpleNamespace(
        step_id="query-dependency",
        operation_role="QUERY",
        capability_ref=dependency_query_ref,
        input_bindings={},
        availability=SimpleNamespace(type="VALUE_NOT_NULL", path="entity"),
        entity_extraction=SimpleNamespace(type="VALUE", path="entity"),
    )
    dependency_recipe = SimpleNamespace(
        acquisition_policy="QUERY_ONLY",
        steps=[dependency_step],
        fact_outputs=[],
    )
    dependency_node = SimpleNamespace(
        node_id="stateful-node:generic-query-dependency",
        slot_id="dependency_entity",
        dependency_node_ids=[],
        created_fact_name="",
        output_fact_name="dependency_entity",
    )
    node = SimpleNamespace(
        node_id="stateful-node:generic-query-then-create",
        slot_id="generic_entity",
        dependency_node_ids=[dependency_node.node_id],
        created_fact_name="created_entity",
        output_fact_name="verified_entity",
    )
    assets = SimpleNamespace(
        capabilities={
            (query_ref.system_id, query_ref.capability_id): query_capability,
            (create_ref.system_id, create_ref.capability_id): create_capability,
            (
                dependency_query_ref.system_id,
                dependency_query_ref.capability_id,
            ): dependency_query_capability,
        },
        stateful_recipes={dependency_node.node_id: dependency_recipe},
        stateful_cleanup_plans={},
    )
    context = CaseExecutionContext(
        attempt_id="attempt-stateful-qtc-branch",
        environment="qa",
        timeout_seconds=30,
        fixture={},
    )
    calls: list[str] = []
    parent_query_calls = 0

    def invoke(capability: Any, _inputs: dict[str, Any], _stage: str, _context: Any) -> PublishedInvocationResult:
        """按调用顺序返回内存结果并记录实际步骤角色。

        Args:
            capability: 当前QUERY或CREATE Published能力。
            _inputs: 本测试无输入绑定。
            _stage: 固定SETUP阶段。
            _context: 当前Attempt瞬时上下文。

        Returns:
            与本次分支序号对应的Published调用结果。
        """

        nonlocal parent_query_calls
        if capability.capability_id == dependency_query_ref.capability_id:
            calls.append("DEPENDENCY_QUERY")
            return PublishedInvocationResult(
                status="PASSED",
                result={"entity": {"id": "dependency", "state": "READY"}},
            )
        if capability.mutability == OperationMutability.WRITE:
            calls.append("CREATE")
            return PublishedInvocationResult(
                status="PASSED",
                result={"created": {"id": "created", "state": "NEW"}},
            )
        calls.append("QUERY")
        parent_query_calls += 1
        if parent_query_calls == 1:
            return PublishedInvocationResult(
                status=initial_status,
                result=initial_result,
            )
        return PublishedInvocationResult(
            status="PASSED",
            result={"entity": {"id": "created", "state": "READY"}},
        )

    def verify(
        _node: Any,
        _recipe: Any,
        entity: Any,
        target_context: CaseExecutionContext,
        include_create_relations: bool = False,
    ) -> None:
        """把通过验证的最终实体保存到slot，模拟已单测的Schema/状态校验边界。

        Args:
            _node: 本测试固定的状态节点。
            _recipe: 本测试固定的QTC Recipe。
            entity: 查询返回的最终实体。
            target_context: 接收最终slot的Attempt上下文。
            include_create_relations: 是否来自创建分支后的最终查询。

        Returns:
            None；本测试只观察分支，不重复状态谓词算法。
        """

        del _recipe, include_create_relations
        target_context.setup_facts_by_slot[_node.slot_id] = entity
        return None

    monkeypatch.setattr(service, "_invoke_capability", invoke)
    monkeypatch.setattr(service, "_mapped_outputs", lambda _capability, result: result)
    monkeypatch.setattr(service, "_verify_and_store_stateful_entity", verify)
    failure = service._run_stateful_recipe(
        node,
        recipe,
        _StatefulSetupRunState(
            nodes_by_id={
                node.node_id: node,
                dependency_node.node_id: dependency_node,
            }
        ),
        assets,
        context,
    )

    if expected_failure is None:
        assert failure is None
    assert calls == expected_roles
    assert (failure.code if failure is not None else None) == expected_failure
    if "CREATE" in expected_roles:
        assert context.stateful_cleanup_facts_by_slot[node.slot_id]["id"] == "created"
        assert context.setup_facts_by_slot[node.slot_id]["state"] == "READY"


def test_identityless_create_uses_verified_final_query_entity_for_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """创建响应无实体身份时，末次查询必须按依赖关系验证后提供回收身份。

    Args:
        tmp_path: Pytest隔离的执行服务和规则根目录。
        monkeypatch: 注入当前冻结Fact规则，避免访问任何外部运行时。

    Returns:
        None；关系一致时保存最终实体，关系错误时失败且不留下回收身份。

    Side Effects:
        只修改两个内存Attempt上下文，不调用QA、Action、Oracle或Cleanup。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    contract = SimpleNamespace(
        fact_contract_id="generic-entity/v1",
        state_path="state",
        state_predicates=[
            SimpleNamespace(name="READY", allowed_values=["READY"])
        ],
        business_identity_paths=["id"],
    )
    rules = SimpleNamespace(fact_contracts=[contract])
    recipe = SimpleNamespace(
        system_id=SYSTEM_ID,
        setup_rule_revision_id="setup-rule-revision:identityless-create",
        fact_outputs=[
            SimpleNamespace(
                fact_name="verified_entity",
                fact_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "order_no": {"type": "string"},
                        "state": {"type": "string"},
                    },
                    "required": ["id", "order_no", "state"],
                },
            )
        ],
    )
    node = SimpleNamespace(
        slot_id="generic_entity",
        fact_contract_id=contract.fact_contract_id,
        output_fact_name="verified_entity",
        created_fact_name="",
        required_state="READY",
        constraints={},
        relations={},
        create_relations={"order_no": "${dependency_order.order_no}"},
    )
    entity = {"id": "entity-1", "order_no": "order-1", "state": "READY"}
    context = CaseExecutionContext(
        attempt_id="attempt-identityless-create",
        environment="qa",
        timeout_seconds=30,
        fixture={},
        setup_facts_by_slot={"dependency_order": {"order_no": "order-1"}},
    )
    monkeypatch.setattr(service.catalog.recipes.rules, "read_revision", lambda *_args: rules)

    failure = service._verify_and_store_stateful_entity(
        node,
        recipe,
        entity,
        context,
        include_create_relations=True,
    )
    mismatch_context = CaseExecutionContext(
        attempt_id="attempt-identityless-create-mismatch",
        environment="qa",
        timeout_seconds=30,
        fixture={},
        setup_facts_by_slot={"dependency_order": {"order_no": "order-2"}},
    )
    mismatch = service._verify_and_store_stateful_entity(
        node,
        recipe,
        entity,
        mismatch_context,
        include_create_relations=True,
    )

    assert failure is None
    assert context.setup_facts_by_slot[node.slot_id] == entity
    assert context.stateful_cleanup_facts_by_slot[node.slot_id] == entity
    assert mismatch is not None
    assert mismatch.code == "SETUP_STATEFUL_ENTITY_VERIFICATION_FAILED"
    assert node.slot_id not in mismatch_context.stateful_cleanup_facts_by_slot


def test_query_only_miss_is_setup_blocked_before_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QUERY_ONLY未找到实体必须形成Setup Blocked且不产生写资源标记。

    Args:
        tmp_path: Pytest隔离的执行服务和Attempt根目录。
        monkeypatch: 返回一次明确查询miss而不访问QA。

    Returns:
        None；失败阶段、状态和零CREATE事实均符合协议时通过。

    Side Effects:
        只执行内存中的单节点Setup函数，不调用Action或Oracle。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    query_ref = PublishedCapabilityRef(
        system_id=SYSTEM_ID,
        capability_id="published:generic-query-only",
    )
    capability = harness.action.model_copy(
        update={
            "capability_id": query_ref.capability_id,
            "mutability": OperationMutability.READ_ONLY,
        }
    )
    step = SimpleNamespace(
        step_id="query-only",
        operation_role="QUERY",
        capability_ref=query_ref,
        input_bindings={},
        availability=SimpleNamespace(type="VALUE_NOT_NULL", path="entity"),
        entity_extraction=SimpleNamespace(type="VALUE", path="entity"),
    )
    recipe = SimpleNamespace(
        acquisition_policy="QUERY_ONLY",
        steps=[step],
        fact_outputs=[],
    )
    node = SimpleNamespace(
        node_id="stateful-node:generic-query-only",
        slot_id="generic_entity",
        dependency_node_ids=[],
        created_fact_name="",
        output_fact_name="queried_entity",
    )
    assets = SimpleNamespace(
        capabilities={(query_ref.system_id, query_ref.capability_id): capability},
        stateful_cleanup_plans={},
    )
    context = CaseExecutionContext(
        attempt_id="attempt-stateful-query-only-miss",
        environment="qa",
        timeout_seconds=30,
        fixture={},
    )
    monkeypatch.setattr(
        service,
        "_invoke_capability",
        lambda *_args: PublishedInvocationResult(
            status="PASSED",
            result={"entity": None},
        ),
    )
    monkeypatch.setattr(service, "_mapped_outputs", lambda _capability, result: result)

    failure = service._run_stateful_recipe(
        node,
        recipe,
        _StatefulSetupRunState(nodes_by_id={node.node_id: node}),
        assets,
        context,
    )

    assert failure is not None
    assert (failure.stage, failure.status, failure.code) == (
        "SETUP",
        "BLOCKED",
        "BLOCKED_SETUP_STATEFUL_ENTITY_NOT_FOUND",
    )
    assert context.resource_may_exist is False
    assert context.stateful_created_node_ids == set()


def test_stateful_query_gate_serializes_in_process_and_skips_create_only(
    tmp_path: Path,
) -> None:
    """查询策略必须在进程内串行，而CREATE_ONLY不得取得查询锁。

    Args:
        tmp_path: Pytest隔离的Attempt存储和状态实体锁目录。

    Returns:
        None；第二个查询被阻塞、释放后可重试且CREATE_ONLY无锁时通过。

    Side Effects:
        仅在临时目录创建空锁文件，不调用QA或创建业务实体。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    query_assets = _stateful_lock_assets(harness, "QUERY_ONLY")
    owner_context = CaseExecutionContext(
        attempt_id="attempt-stateful-lock-owner",
        environment="qa",
        timeout_seconds=1,
        fixture={},
    )
    contender_context = CaseExecutionContext(
        attempt_id="attempt-stateful-lock-contender",
        environment="qa",
        timeout_seconds=1,
        fixture={},
    )
    owner_locks, owner_failure = service._acquire_stateful_query_locks(
        query_assets,
        owner_context,
    )
    try:
        contender_locks, contender_failure = service._acquire_stateful_query_locks(
            query_assets,
            contender_context,
        )
        assert contender_locks == []
        assert contender_failure is not None
        assert contender_failure.code == "BLOCKED_SETUP_STATEFUL_ENTITY_BUSY"
    finally:
        service._release_stateful_query_locks(owner_locks)

    assert owner_failure is None
    retry_locks, retry_failure = service._acquire_stateful_query_locks(
        query_assets,
        contender_context,
    )
    service._release_stateful_query_locks(retry_locks)
    assert retry_failure is None

    # CREATE_ONLY拥有独立实体，不应承受查询复用的串行等待。
    create_locks, create_failure = service._acquire_stateful_query_locks(
        _stateful_lock_assets(harness, "CREATE_ONLY"),
        contender_context,
    )
    assert create_locks == []
    assert create_failure is None
    harness.application.close()


def test_stateful_query_gate_honors_cross_process_flock_and_releases_timeout(
    tmp_path: Path,
) -> None:
    """跨进程文件锁冲突必须阻塞Setup，并在超时后释放进程锁。

    Args:
        tmp_path: Pytest隔离的Attempt存储和文件锁目录。

    Returns:
        None；子进程持锁时阻塞、释放后同一Attempt宿主可重新取得锁时通过。

    Side Effects:
        启动一个只持有Pytest临时文件锁的子进程，不调用QA。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    assets = _stateful_lock_assets(harness, "QUERY_THEN_CREATE")
    node = assets.scenario.template_key.stateful_setup_plan.nodes[0]
    recipe = assets.stateful_recipes[node.node_id]
    query_step = recipe.steps[0]
    capability = assets.capabilities[
        (query_step.capability_ref.system_id, query_step.capability_ref.capability_id)
    ]
    key = (
        "qa",
        capability.provider_operation_ref.source_system_id,
        node.fact_contract_id,
    )
    lock_root = service.attempts.root / "stateful-entity-locks"
    lock_path = service._stateful_lock_path(lock_root, key)
    process_context = multiprocessing.get_context("spawn")
    ready = process_context.Event()
    release = process_context.Event()
    process = process_context.Process(
        target=_hold_stateful_lock_file,
        args=(str(lock_path), ready, release),
    )
    process.start()
    try:
        assert ready.wait(timeout=5)
        context = CaseExecutionContext(
            attempt_id="attempt-stateful-flock-contender",
            environment="qa",
            timeout_seconds=1,
            fixture={},
        )
        blocked_locks, blocked_failure = service._acquire_stateful_query_locks(
            assets,
            context,
        )
        assert blocked_locks == []
        assert blocked_failure is not None
        assert blocked_failure.code == "BLOCKED_SETUP_STATEFUL_ENTITY_BUSY"
    finally:
        release.set()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    assert process.exitcode == 0
    recovered_locks, recovered_failure = service._acquire_stateful_query_locks(
        assets,
        context,
    )
    service._release_stateful_query_locks(recovered_locks)
    assert recovered_failure is None
    harness.application.close()


def test_stateful_query_gate_releases_thread_lock_when_file_lock_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文件锁打开失败时必须释放已取得的进程锁供后续Attempt使用。

    Args:
        tmp_path: Pytest隔离的Attempt存储和锁目录。
        monkeypatch: 临时让锁路径指向目录以触发受控OSError。

    Returns:
        None；首次报告环境阻塞且恢复路径后可正常取得锁时通过。

    Side Effects:
        仅创建Pytest临时锁目录和空锁文件，不调用QA。
    """

    harness = _compiler_harness(tmp_path, [])
    service = harness.application.case_execution_v3
    assets = _stateful_lock_assets(harness, "QUERY_ONLY")
    context = CaseExecutionContext(
        attempt_id="attempt-stateful-lock-unavailable",
        environment="qa",
        timeout_seconds=1,
        fixture={},
    )
    original_lock_path = service._stateful_lock_path
    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(
            service,
            "_stateful_lock_path",
            lambda lock_root, _key: lock_root,
        )
        unavailable_locks, unavailable_failure = service._acquire_stateful_query_locks(
            assets,
            context,
        )
    assert unavailable_locks == []
    assert unavailable_failure is not None
    assert unavailable_failure.code == "BLOCKED_SETUP_STATEFUL_GATE_UNAVAILABLE"

    monkeypatch.setattr(service, "_stateful_lock_path", original_lock_path)
    recovered_locks, recovered_failure = service._acquire_stateful_query_locks(
        assets,
        context,
    )
    service._release_stateful_query_locks(recovered_locks)
    assert recovered_failure is None
    harness.application.close()


def test_final_generation_accounts_for_legal_factor_pairs_after_filtering(
    tmp_path: Path,
) -> None:
    """最终Variant丢失合法二元组合时必须阻塞相关Factor义务。

    Args:
        tmp_path: Pytest隔离知识根目录。
    """

    obligations = [
        FactorObligation(
            **_obligation_base("factor:mode-pair"),
            factor_path="mode",
            values=["A", "M"],
        ),
        FactorObligation(
            **_obligation_base("factor:amount-pair"),
            factor_path="amount",
            values=[1, 2],
        ),
    ]
    harness = _compiler_harness(tmp_path, obligations)
    generation = harness.application.hybrid_case_generation.generate(
        SYSTEM_ID,
        HybridCaseGenerationRequest(entry_id=ENTRY_ID),
    )

    # 两个二值Factor的最后一个Variant被生命周期过滤后，单值仍齐全但一个合法pair已丢失。
    retained_variants = generation.variants[:-1]
    resolutions, blockers = harness.application.hybrid_case_generation._coverage_resolutions(
        generation.coverage_manifest.obligations,
        generation.scenarios,
        retained_variants,
        generation.fault_plans,
        generation.obligation_resolutions,
        [],
    )

    assert generation.status == "READY"
    assert len(generation.expected_factor_pair_goals) == 4
    assert {item.status for item in resolutions} == {"BLOCKED"}
    assert {item.blocker_code for item in resolutions} == {
        "BLOCKED_FACTOR_PAIRWISE_COVERAGE_LOST"
    }
    assert {item.code for item in blockers} == {
        "BLOCKED_FACTOR_PAIRWISE_COVERAGE_LOST"
    }


def test_equivalent_current_setup_recipes_are_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅ID和名称不同的等价Setup Recipe不得拆成多个Scenario。

    Args:
        tmp_path: Pytest隔离consumer/provider源码和知识根目录。
        monkeypatch: 把阶段4直接存储夹具限定为current，隔离本测试的Recipe等价判断。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    first_submission = _recipe_submission(
        manifest,
        provider,
        consumer,
        "equivalent-one",
        "SINGLE",
    )
    second_submission = _recipe_submission(
        manifest,
        provider,
        consumer,
        "equivalent-two",
        "SINGLE",
    )
    first_step, second_step = second_submission.steps
    renamed_fact = second_submission.fact_outputs[0].model_copy(
        update={
            "fact_name": "renamed_resource_fact",
            "from_step_id": "produce-renamed-resource",
            "constraints": list(reversed(second_submission.fact_outputs[0].constraints)),
        }
    )
    renamed_submission = second_submission.model_copy(
        update={
            "steps": [
                first_step.model_copy(update={"step_id": "produce-renamed-resource"}),
                second_step.model_copy(
                    update={
                        "step_id": "consume-renamed-resource",
                        "input_bindings": {
                            "request_id": second_step.input_bindings[
                                "request_id"
                            ].model_copy(
                                update={"path": "renamed_resource_fact.resourceId"}
                            )
                        },
                    }
                ),
            ],
            "fact_outputs": [renamed_fact],
        }
    )
    for submission in (first_submission, renamed_submission):
        publication = application.publish_data_setup_recipe(
            RECIPE_CONSUMER_ID,
            submission,
        )
        assert publication.status == "PUBLISHED", publication.issues
    profile = CaseCompilationActionProfile(
        profile_id="action-profile:equivalent-recipes",
        entry_id=manifest.entries[0].entry_id,
        source_scan_id=manifest.scan_id,
        action_capability_ref=PublishedCapabilityRef(
            system_id=consumer.system_id,
            capability_id=consumer.capability_id,
        ),
        input_bindings=[
            ActionInputBindingTemplate(
                input_path="request_id",
                source_ref=SetupFactInputRef(
                    fact_contract_id=FACT_CONTRACT_ID,
                    fact_path="resourceId",
                ),
            )
        ],
    )
    blockers = []

    def current_recipe(_system_id: str, _recipe: object) -> list[str]:
        """让阶段4通用存储夹具通过current边界以单测等价Recipe选择。

        Args:
            _system_id: 本测试不使用的consumer身份。
            _recipe: 已由阶段4正式服务发布的Recipe。

        Returns:
            空问题列表，使测试只观察等价性冲突而非Candidate夹具差异。
        """

        return []

    monkeypatch.setattr(
        application.typed_case_compiler,
        "_recipe_current_issues",
        current_recipe,
    )

    # 直接验证确定性Recipe选择边界，不进入QA或伪造任何运行结果。
    recipes = application.typed_case_compiler._resolve_recipes(
        RECIPE_CONSUMER_ID,
        application.case_rules.preview(
            RECIPE_CONSUMER_ID,
            manifest.entries[0].entry_id,
        ).manifest,
        profile,
        consumer,
        blockers,
    )

    assert recipes == []
    assert {item.code for item in blockers} == {"BLOCKED_AMBIGUOUS_SETUP_RECIPE"}


def test_same_priority_fault_capabilities_require_explicit_disambiguation(
    tmp_path: Path,
) -> None:
    """同位置存在多个REAL_DATA能力时Planner不得按ID静默选择。

    Args:
        tmp_path: Pytest隔离Fault正式资产根目录。
    """

    harness = _phase6_harness(tmp_path)
    original = next(
        item
        for item in harness.application.fault_capability_registry(SYSTEM_ID).capabilities
        if item.kind == FaultCapabilityKind.REAL_DATA
    )
    draft_payload = original.model_dump(
        mode="python",
        include=set(FaultCapabilityDraftSubmission.model_fields),
    )
    draft_payload["publication_request_id"] = "generic.real-data.middle.second.v1"
    duplicate = harness.application.publish_fault_capability(
        SYSTEM_ID,
        FaultCapabilityDraftSubmission.model_validate(draft_payload),
    )

    planned = harness.application.plan_fault_injection(
        SYSTEM_ID,
        FaultPlanningRequest(
            entry_id=ENTRY_ID,
            obligation_id=harness.fault_obligation_id,
        ),
    )

    assert duplicate.status == "PUBLISHED", duplicate.issues
    assert planned.status == "WITH_BLOCKED"
    assert {item.code for item in planned.issues} >= {
        "BLOCKED_AMBIGUOUS_FAULT_CAPABILITY"
    }
    assert "MIDDLE" not in {plan.selector.position for plan in planned.plans}


def test_compilation_draft_cannot_change_policy_shared_by_another_entry(
    tmp_path: Path,
) -> None:
    """Case Agent草稿不得改写仍由其他Entry共用的输入来源策略。

    Args:
        tmp_path: Pytest隔离编译规则和handoff范围。
    """

    harness = _compiler_harness(tmp_path, [])
    current = harness.application.case_compilation_rules.read(SYSTEM_ID)
    target_profile = current.action_profiles[0]
    other_profile = target_profile.model_copy(
        update={
            "profile_id": "action-profile:other-entry-shared-policy",
            "entry_id": "facade:sample.OtherFacade#inspect",
        }
    )
    harness.application.case_compilation_rules.write(
        CaseCompilationRuleSet(
            system_id=SYSTEM_ID,
            action_profiles=[target_profile, other_profile],
            input_policies=current.input_policies,
            oracle_templates=current.oracle_templates,
        )
    )
    changed_policy = current.input_policies[0].model_copy(
        update={
            "allowed_sources": ["safe_constant"],
            "allowed_safe_constants": ["A"],
        }
    )
    handoff = CaseGenerationHandoff(
        handoff_id=f"case-handoff-{'a' * 24}",
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        source_scan_id=harness.scan_id,
        source_baseline=harness.action.candidate_ref.source_baseline,
    )
    issues = []

    # 调用正式合并边界；冲突必须在写规则修订前被拒绝。
    harness.application.hybrid_case_handoffs._publish_compilation(
        handoff,
        CaseCompilationAssetDraft(
            draft_id="case-compilation-draft:shared-policy-conflict",
            action_profile=target_profile,
            input_policies=[changed_policy],
            oracle_template=current.oracle_templates[0],
        ),
        [],
        issues,
    )

    assert {item.code for item in issues} == {
        "CASE_COMPILATION_SHARED_POLICY_CONFLICT"
    }
    assert harness.application.case_compilation_rules.read(SYSTEM_ID).input_policies == (
        current.input_policies
    )

    # 共享能力原本缺少某个策略键时，当前Entry也不能新增全局策略影响另一个Entry。
    amount_policy = next(
        policy for policy in current.input_policies if policy.input_path == "amount"
    )
    without_amount_policy = [
        policy for policy in current.input_policies if policy.input_path != "amount"
    ]
    harness.application.case_compilation_rules.write(
        CaseCompilationRuleSet(
            system_id=SYSTEM_ID,
            action_profiles=[target_profile, other_profile],
            input_policies=without_amount_policy,
            oracle_templates=current.oracle_templates,
        )
    )
    missing_key_issues = []
    harness.application.hybrid_case_handoffs._publish_compilation(
        handoff,
        CaseCompilationAssetDraft(
            draft_id="case-compilation-draft:shared-policy-new-key",
            action_profile=target_profile,
            input_policies=[amount_policy],
            oracle_template=current.oracle_templates[0],
        ),
        [],
        missing_key_issues,
    )

    assert {item.code for item in missing_key_issues} == {
        "CASE_COMPILATION_SHARED_POLICY_CONFLICT"
    }
    assert {
        policy.input_path
        for policy in harness.application.case_compilation_rules.read(
            SYSTEM_ID
        ).input_policies
    } == {"mode"}


def test_attempt_evidence_redacts_provider_messages_and_object_keys(
    tmp_path: Path,
) -> None:
    """Attempt证据只能保留状态形状，不能复制provider消息和响应字段名。

    Args:
        tmp_path: Pytest隔离Attempt服务依赖。
    """

    harness = _compiler_harness(tmp_path, [])
    context = CaseExecutionContext(
        attempt_id=f"attempt-{'b' * 20}",
        environment="qa",
        timeout_seconds=30,
        fixture={},
    )
    invocation = PublishedInvocationResult(
        status="FAILED",
        result={"business-order-123": "secret"},
        error_code="GENERIC_FAILURE",
        message="provider leaked order-123",
    )

    harness.application.case_execution_v3._append_evidence(
        "ACTION",
        harness.action.capability_id,
        invocation,
        context,
    )
    failure = harness.application.case_execution_v3._from_invocation(
        "ACTION",
        invocation,
        "ACTION_FAILED",
    )

    assert context.evidence[0].result_summary == {"type": "object", "field_count": 1}
    assert context.evidence[0].message == "ACTION阶段执行失败。"
    assert failure.message == "ACTION阶段执行失败。"
    assert "order-123" not in context.evidence[0].model_dump_json()
    assert "order-123" not in failure.model_dump_json()


def test_missing_cleanup_identity_records_independent_quarantine_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """资源可能已产生但缺少回收键时同时保留Cleanup与隔离失败。

    Args:
        tmp_path: Pytest隔离Cleanup正式资产和Attempt上下文。
        monkeypatch: 模拟Plan与Scenario关系字段发生current漂移。
    """

    harness = _cleanup_harness(tmp_path, include_cleanup_dependency=True)
    harness.application.put_cleanup_contract_rules(
        SYSTEM_ID,
        _cleanup_rules(harness, include_classifier=True),
    )
    publication = harness.application.publish_cleanup_plan(
        SYSTEM_ID,
        _cleanup_submission(
            harness,
            "cleanup:generic-missing-runtime-identity",
            include_cancel=True,
        ),
    )
    assert publication.status == "PUBLISHED", publication.issues
    generation = harness.application.hybrid_case_generation.generate(
        SYSTEM_ID,
        HybridCaseGenerationRequest(entry_id=ENTRY_ID),
    )
    scenario = next(
        item
        for item in generation.scenarios
        if item.template_key.cleanup_plan_ref is not None
        and item.template_key.cleanup_plan_ref.cleanup_plan_id
        == publication.plan.cleanup_plan_id
    )
    assert (
        harness.application.case_execution_v3.catalog._current_cleanup(
            generation,
            scenario,
        )
        == publication.plan
    )
    drifted_plan = publication.plan.model_copy(
        update={"action_profile_id": "action-profile:drifted-cleanup-relation"}
    )

    def return_drifted_plan(_system_id: str, _plan_id: str) -> object:
        """返回身份存在但Scenario关系字段漂移的current CleanupPlan。

        Args:
            _system_id: 本测试不使用的Plan所属系统。
            _plan_id: 本测试不使用的Cleanup身份。

        Returns:
            只修改Action Profile关系的正式Plan副本。
        """

        return drifted_plan

    monkeypatch.setattr(
        harness.application.case_execution_v3.catalog.cleanup_plans,
        "get_current",
        return_drifted_plan,
    )
    with pytest.raises(KnowledgeValidationError, match="CLEANUP_PLAN_RELATION_DRIFT"):
        harness.application.case_execution_v3.catalog._current_cleanup(
            generation,
            scenario,
        )

    context = CaseExecutionContext(
        attempt_id=f"attempt-{'c' * 20}",
        environment="qa",
        timeout_seconds=30,
        fixture={},
        resource_may_exist=True,
    )

    cleanup, cleanup_oracle, quarantine = (
        harness.application.case_execution_v3._finalize_cleanup(
            SimpleNamespace(cleanup_plan=publication.plan),
            context,
        )
    )

    assert cleanup is not None
    assert cleanup.code == "BLOCKED_CLEANUP_IDENTITY_MISSING"
    assert cleanup_oracle is None
    assert quarantine is not None
    assert quarantine.code == "BLOCKED_QUARANTINE_IDENTITY_MISSING"
    assert [item.stage for item in context.evidence] == ["CLEANUP", "QUARANTINE"]


def test_quarantine_state_uses_owner_only_permissions(tmp_path: Path) -> None:
    """含业务资源键的本地隔离目录和文件必须限制为当前用户访问。

    Args:
        tmp_path: Pytest隔离运行时根目录。
    """

    store = ResourceQuarantineStore(tmp_path / "runtime")
    store.add(
        ResourceQuarantineRecord(
            quarantine_id=f"quarantine-{'d' * 20}",
            system_id=SYSTEM_ID,
            cleanup_plan_id="cleanup:generic-permission-check",
            isolation_fact_path="resource_id",
            resource_key="generic-resource-key",
            reason_code="CLEANUP_FAILED",
            attempt_id=f"attempt-{'e' * 20}",
        )
    )
    path = store.root / f"{SYSTEM_ID}.json"

    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_quarantine_add_is_serialized_across_processes(tmp_path: Path) -> None:
    """多个OpenTest进程并发追加隔离记录时不得由最后写入者覆盖。

    Args:
        tmp_path: 多个spawn进程共享的本地运行时根目录。
    """

    runtime_root = tmp_path / "runtime"
    process_context = multiprocessing.get_context("spawn")
    start_event = process_context.Event()
    processes = [
        process_context.Process(
            target=_add_quarantine_in_process,
            args=(str(runtime_root), SYSTEM_ID, suffix, start_event),
        )
        for suffix in ("1", "2", "3", "4")
    ]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(timeout=20)

    assert [process.exitcode for process in processes] == [0, 0, 0, 0]
    records = ResourceQuarantineStore(runtime_root).list(SYSTEM_ID)
    assert {record.resource_key for record in records} == {
        "resource-1",
        "resource-2",
        "resource-3",
        "resource-4",
    }


def test_real_refund_cancel_truth_stays_blocked_and_handoff_resumes_same_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实Refund未闭合入口保持具体BLOCKED且handoff不改写既有正式资产。

    Args:
        tmp_path: 正式知识仓库完整副本与私有handoff目录。
        monkeypatch: 复用已验真的BLOCKED Generation检查handoff状态机，避免重复扫描真实仓库。

    Returns:
        None；生成只新增自身历史记录，不发布能力、Recipe、Cleanup或Attempt。

    Side Effects:
        在临时知识副本创建BLOCKED Generation与handoff，不访问QA。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    application = OpenTestApplication(knowledge_copy)
    system_id = "ifightchainsaas.java.refund.core"
    entry_id = "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel"
    published_before = application.published_capability_registry(system_id).capabilities
    recipes_before = application.data_setup_recipe_catalog(system_id).recipes
    cleanups_before = application.cleanup_plan_catalog(system_id).plans
    attempts_before = application.list_hybrid_case_attempts(system_id)
    ready_before = {
        item.generation_id
        for item in application.list_hybrid_case_generations(system_id)
        if item.status == "READY"
    }

    generation = next(
        item
        for item in application.list_hybrid_case_generations(system_id)
        if item.entry_id == entry_id
        and {blocker.code for blocker in item.blockers}
        == {"BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED"}
    )

    def skip_redundant_provider_candidate_rebuild(_provider_system_id: str) -> None:
        """让handoff状态机测试跳过已由Candidate专项测试覆盖的Booking重扫。

        Args:
            _provider_system_id: Handoff尝试冻结的直接provider系统。

        Raises:
            KnowledgeNotFoundError: 按生产降级语义保留provider绑定但不附Candidate快照。
        """

        raise KnowledgeNotFoundError("provider candidate snapshot omitted by handoff unit boundary")

    monkeypatch.setattr(
        application.hybrid_case_handoffs.capabilities.candidates,
        "catalog",
        skip_redundant_provider_candidate_rebuild,
    )
    handoff = application.hybrid_case_handoffs.create(generation)
    resume_count = 0

    def reuse_truthful_blocked_generation(
        requested_system_id: str,
        request: HybridCaseGenerationRequest,
        handoff_id: str = "",
    ) -> HybridCaseGenerationRecord:
        """为handoff状态机返回同一真实业务投影的新Generation身份。

        Args:
            requested_system_id: 必须保持为真实退款系统。
            request: 必须保持为同一cancel入口。
            handoff_id: 恢复时绑定的原handoff身份。

        Returns:
            仅发布身份变化、业务条件和阻塞完全不变的BLOCKED Generation。

        Side Effects:
            只递增当前测试内计数；不写Generation、不访问QA或Codex。
        """

        nonlocal resume_count
        assert requested_system_id == system_id
        assert request.entry_id == entry_id
        resume_count += 1
        # 真实生成的重复编译已由独立非跳过验收覆盖；本测试只隔离handoff所有权状态机。
        return generation.model_copy(
            update={
                "generation_id": f"hybrid-generation-{resume_count:020x}",
                "handoff_id": handoff_id,
            }
        )

    monkeypatch.setattr(
        application.hybrid_case_handoffs.generator,
        "generate",
        reuse_truthful_blocked_generation,
    )
    resumed_generation = application.hybrid_case_handoffs.resume(handoff.handoff_id)
    resumed_handoff = application.hybrid_case_handoffs.get(handoff.handoff_id)

    assert generation.status == "BLOCKED"
    assert generation.scenarios == []
    assert generation.variants == []
    blocker_codes = {item.code for item in generation.blockers}
    assert blocker_codes == {"BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED"}
    assert "BLOCKED_COVERAGE_ACCOUNTING_INCOMPLETE" not in blocker_codes
    assert application.published_capability_registry(system_id).capabilities == published_before
    assert application.data_setup_recipe_catalog(system_id).recipes == recipes_before
    assert application.cleanup_plan_catalog(system_id).plans == cleanups_before
    assert application.list_hybrid_case_attempts(system_id) == attempts_before
    assert {
        item.generation_id
        for item in application.list_hybrid_case_generations(system_id)
        if item.status == "READY"
    } == ready_before
    assert resumed_handoff.handoff_id == handoff.handoff_id
    assert resumed_handoff.entry_id == entry_id
    assert resumed_generation.status == "BLOCKED"

    # 本地状态以修订号拒绝基于同一旧快照的第二次覆盖。
    application.hybrid_case_handoffs.handoffs.write(
        resumed_handoff.model_copy(update={"safe_error": "first serialized update"})
    )
    with pytest.raises(KnowledgeValidationError, match="concurrent update conflict"):
        application.hybrid_case_handoffs.handoffs.write(
            resumed_handoff.model_copy(update={"safe_error": "stale overwrite"})
        )

    # 进程退出遗留的VALIDATING状态可恢复同一handoff，但无合法AI输入时必须终止等待。
    latest_handoff = application.hybrid_case_handoffs.get(handoff.handoff_id)
    application.hybrid_case_handoffs.handoffs.write(
        latest_handoff.model_copy(
            update={"status": CaseGenerationHandoffStatus.VALIDATING}
        )
    )
    recovered_generation = application.hybrid_case_handoffs.resume(handoff.handoff_id)
    assert recovered_generation.status == "BLOCKED"
    assert (
        application.hybrid_case_handoffs.get(handoff.handoff_id).status
        == CaseGenerationHandoffStatus.BLOCKED
    )

    # Handoff创建后新增直接provider会扩大Candidate范围，因此必须终止旧任务而非纳入新系统。
    new_provider_root = tmp_path / "new-provider-source"
    new_provider_root.mkdir()
    application.register_system(
        SystemDefinition(
            system_id="generic-new-provider",
            name="通用新增Provider",
            source_path=str(new_provider_root),
        )
    )
    application.put_system_dependency_binding(
        system_id,
        SystemDependencyBindingSubmission(
            provider_system_id="generic-new-provider",
            role=SystemDependencyRole.UPSTREAM,
            purposes=[SystemDependencyPurpose.SETUP],
        ),
    )
    with pytest.raises(KnowledgeValidationError, match="STALE_SOURCE"):
        application.hybrid_case_handoffs.resume(handoff.handoff_id)
    stale_handoff = application.hybrid_case_handoffs.get(handoff.handoff_id)
    assert stale_handoff.status.value == "stale_source"

    # FAILED等终态不得再次接受typed草稿，避免两个Agent继续修改同一冻结任务。
    failed_handoff = application.hybrid_case_handoffs.fail(
        handoff.handoff_id,
        "task stopped after source scope changed",
    )
    bundle = CaseGenerationDraftBundle(
        source_scan_id=failed_handoff.source_scan_id,
        semantic_draft=CaseSemanticDraft(
            draft_id=f"case-semantic-draft-{'f' * 20}",
            system_id=system_id,
            source_scan_id=failed_handoff.source_scan_id,
            analysis_artifact_id=(
                failed_handoff.analysis_artifact_id
                or "program-analysis-legacy-placeholder"
            ),
            entry_id=entry_id,
            resolutions=[],
        ),
    )
    with pytest.raises(KnowledgeValidationError, match="does not accept drafts"):
        application.hybrid_case_handoffs.submit(handoff.handoff_id, bundle)

    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            project_root / "opentest/application/hybrid_case_generation.py",
            project_root / "opentest/application/case_execution_v3.py",
            project_root / "opentest/application/hybrid_case_handoffs.py",
        )
    )
    assert "RefundFacade" not in production_text
    assert "TradeOrderSyncMessageListener" not in production_text
