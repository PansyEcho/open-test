"""验证阶段8只编排正式资产，并在任何QA调用前完成可信预检。"""

from __future__ import annotations

import multiprocessing
import shutil
import stat
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
)
from opentest.application.foundation import OpenTestApplication
from opentest.adapters.resource_quarantine_store import ResourceQuarantineStore
from opentest.domain.errors import KnowledgeValidationError
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
    FaultCapabilityDraftSubmission,
    FaultCapabilityKind,
    FaultPlanningRequest,
    FactorObligation,
    HybridCaseGenerationRequest,
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


def test_entry_only_api_generates_complete_factor_accounting(tmp_path: Path) -> None:
    """API只凭Entry恢复正式资产，并完整证明Factor每个声明值。

    Args:
        tmp_path: Pytest隔离源码、Git知识和本地运行目录。
    """

    obligation = FactorObligation(
        **_obligation_base("factor:mode"),
        factor_path="mode",
        values=["A", "M"],
    )
    harness = _compiler_harness(tmp_path, [obligation])

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


def test_real_refund_truth_stays_blocked_and_handoff_resumes_same_scope(
    tmp_path: Path,
) -> None:
    """真实Refund缺正式资产时保持具体BLOCKED、零READY、零Attempt和同范围handoff。

    Args:
        tmp_path: 正式知识仓库完整副本与私有handoff目录。
    """

    project_root = Path(__file__).parents[2]
    knowledge_copy = tmp_path / "open-test-knowledge"
    shutil.copytree(project_root / "open-test-knowledge", knowledge_copy)
    application = OpenTestApplication(knowledge_copy)
    system_id = "ifightchainsaas.java.refund.core"
    entry_id = "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder"

    generation = application.hybrid_case_generation.generate(
        system_id,
        HybridCaseGenerationRequest(entry_id=entry_id),
    )
    handoff = application.hybrid_case_handoffs.create(generation)
    resumed_generation = application.hybrid_case_handoffs.resume(handoff.handoff_id)
    resumed_handoff = application.hybrid_case_handoffs.get(handoff.handoff_id)

    assert generation.status == "BLOCKED"
    assert generation.scenarios == []
    assert generation.variants == []
    blocker_codes = {item.code for item in generation.blockers}
    assert blocker_codes >= {
        "BLOCKED_SEMANTIC_RESOLUTION_REQUIRED",
        "BLOCKED_ACTION_PROFILE_MISSING",
    }
    assert "BLOCKED_COVERAGE_ACCOUNTING_INCOMPLETE" not in blocker_codes
    assert application.published_capability_registry(system_id).capabilities == []
    assert application.data_setup_recipe_catalog(system_id).recipes == []
    assert application.cleanup_plan_catalog(system_id).plans == []
    assert application.list_hybrid_case_attempts(system_id) == []
    assert [
        item for item in application.list_hybrid_case_generations(system_id) if item.status == "READY"
    ] == []
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

    # 进程退出遗留的VALIDATING状态可在重新取得独占处理锁后恢复同一handoff。
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
        == CaseGenerationHandoffStatus.WAITING_FOR_AGENT
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
            analysis_artifact_id=failed_handoff.analysis_artifact_id,
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
