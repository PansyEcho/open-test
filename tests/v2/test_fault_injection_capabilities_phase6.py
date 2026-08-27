"""验证阶段6只使用真实来源Tool、正式Published和冻结Fault义务。"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from opentest.api import create_app
from opentest.application.fault_lifecycle import (
    FaultLifecycleExecutor,
    FaultPublishedInvocation,
)
from opentest.application.foundation import OpenTestApplication
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    ActionInputBindingTemplate,
    CapabilityDraftSubmission,
    CapabilityInputSourcePolicy,
    CaseCompilationActionProfile,
    CaseCompilationRuleSet,
    DataSetupRecipeSubmission,
    DataSetupStep,
    DsfClientProfile,
    DsfOperationDefinition,
    DsfOperationMutability,
    DsfProfileStatus,
    DiscoveredResource,
    EntryPoint,
    FaultCapabilityDraftSubmission,
    FaultCapabilityKind,
    FaultExpectedEntityStates,
    FaultObservedActionResult,
    FaultPlanningRequest,
    FaultResultDefinition,
    FaultToolCandidateRef,
    FaultToolCandidateSubmission,
    FaultTriggerFactContractDefinition,
    FaultTriggerRuleSet,
    KnowledgeNodeKind,
    OperationMutability,
    ProviderOperationRef,
    PublishedCapabilityRef,
    PublishedOperationCapability,
    RecipeFactOutputSubmission,
    SafeConstantInputRef,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticFieldDefinition,
    SemanticMethodDefinition,
    SemanticTypeDefinition,
    SetupContractRuleSet,
    SetupFactContractDefinition,
    SetupFactInputRef,
    SetupFactOrigin,
    SetupFactRequiredField,
    SetupInputBinding,
    SetupInputPolicy,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
    SystemDependencyBindingSubmission,
    SystemDependencyPurpose,
    SystemDependencyRole,
    TestFactConstraint as FactConstraint,
)
from test_typed_case_compiler_phase5 import (
    ENTRY_ID,
    SYSTEM_ID,
    _candidate_ref,
    _compiler_harness,
    _evidence,
)
from opentest.domain.models import FaultInjectionObligation


PROVIDER_ID = "generic-fault-provider"
TRIGGER_FACT_ID = "generic_fault_trigger/v1"
TRIGGER_CONTRACT_ID = "generic_fault_trigger_semantics/v1"
TOOL_ID = "generic-interface-mock"


@dataclass(frozen=True)
class Phase6Harness:
    """保存阶段6正式资产、发布结果和两个冻结Fault义务。"""

    application: OpenTestApplication
    target: PublishedOperationCapability
    setup: PublishedOperationCapability
    install: PublishedOperationCapability
    verify: PublishedOperationCapability
    rollback: PublishedOperationCapability
    tool_ref: FaultToolCandidateRef
    recipe_id: str
    fault_obligation_id: str


def test_real_booking_script_remains_discovery_only_and_lifecycle_blocked(
    tmp_path: Path,
) -> None:
    """真实Booking脚本只能形成安全候选且不能伪称完整Fault能力。

    Args:
        tmp_path: 隔离候选目录和API应用的临时根目录。
    """

    script_path = Path(
        "/Users/user/temp/self-skill/knowledge-bases/"
        "travelsystem-java-dsf-supplychain-booking-core/scripts/create-interface-mock.sh"
    )
    if not script_path.is_file():
        pytest.skip("真实Booking Mock脚本在当前机器不可用")
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(
            system_id="generic-tool-consumer",
            name="通用工具候选消费者",
            source_path=str(tmp_path),
        )
    )

    discovery = application.discover_fault_tool_candidate(
        "generic-tool-consumer",
        FaultToolCandidateSubmission(
            tool_id="booking-interface-mock",
            source_path=str(script_path),
        ),
    )

    assert discovery.status == "DISCOVERED"
    assert discovery.candidate is not None
    candidate = discovery.candidate
    assert candidate.protocol.supports_install is True
    assert candidate.protocol.supports_update is True
    assert candidate.protocol.result_key == "mockKey"
    assert candidate.protocol.supports_verify is False
    assert candidate.protocol.supports_rollback is False
    assert set(candidate.blockers).issuperset(
        {
            "FAULT_ADAPTER_ENVIRONMENT_UNSAFE",
            "FAULT_INSTALL_OPERATION_BINDING_MISSING",
            "FAULT_VERIFY_CAPABILITY_MISSING",
            "FAULT_ROLLBACK_CAPABILITY_MISSING",
        }
    )
    persisted = (
        application.store.system_root("generic-tool-consumer")
        / "capabilities/fault-tool-candidates.yaml"
    ).read_text(encoding="utf-8")
    assert "http://" not in persisted
    assert "https://" not in persisted
    assert "Authorization:" not in persisted
    assert "--app-uk" not in persisted

    # 发现API只接收真实路径；客户端手写协议字段必须由严格模型直接拒绝。
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v2/systems/generic-tool-consumer/fault-tool-candidates",
            json={
                "tool_id": "booking-interface-mock",
                "source_path": str(script_path),
                "supports_verify": True,
                "supports_rollback": True,
            },
        )
    assert response.status_code == 422


def test_formal_real_data_and_mock_capabilities_plan_exact_positions(
    tmp_path: Path,
) -> None:
    """正式Published、Recipe、Trigger和依赖应支持精确序号并优先真实数据。

    Args:
        tmp_path: 隔离源码、Git工具和知识资产的临时根目录。
    """

    publish_scopes: list[set[str]] = []
    harness = _phase6_harness(tmp_path, publish_scopes)
    planned = harness.application.plan_fault_injection(
        SYSTEM_ID,
        FaultPlanningRequest(
            entry_id=ENTRY_ID,
            obligation_id=harness.fault_obligation_id,
        ),
    )

    assert planned.status == "PLANNED"
    assert len(planned.plans) == 3
    by_position = {plan.selector.position: plan for plan in planned.plans}
    assert by_position["MIDDLE"].resolution == FaultCapabilityKind.REAL_DATA
    assert by_position["MIDDLE"].selector.total_invocations == 3
    assert by_position["MIDDLE"].selector.invocation_number == 2
    assert by_position["MIDDLE"].install_capability_ref is None
    assert by_position["FIRST"].resolution == FaultCapabilityKind.MOCK
    assert by_position["FIRST"].selector.invocation_number == 1
    assert by_position["LAST"].resolution == FaultCapabilityKind.MOCK
    assert by_position["LAST"].selector.invocation_number == 3
    assert by_position["FIRST"].expected_entity_states == FaultExpectedEntityStates(
        previous_entities="SUCCESS",
        current_entity="FAILED",
        remaining_entities="NOT_EXECUTED",
    )
    assert by_position["FIRST"].install_capability_ref == PublishedCapabilityRef(
        system_id=PROVIDER_ID,
        capability_id=harness.install.capability_id,
    )
    assert by_position["FIRST"].rollback_capability_ref == PublishedCapabilityRef(
        system_id=PROVIDER_ID,
        capability_id=harness.rollback.capability_id,
    )
    assert publish_scopes
    assert all({SYSTEM_ID, PROVIDER_ID}.issubset(scope) for scope in publish_scopes)

    # 公共规划请求不能覆盖服务端已经冻结的目标、位置或逐实体期望。
    with pytest.raises(ValidationError):
        FaultPlanningRequest.model_validate(
            {
                "entry_id": ENTRY_ID,
                "obligation_id": harness.fault_obligation_id,
                "target_operation": "forged",
                "invocation_positions": ["LAST"],
            }
        )


def test_tool_drift_and_lifecycle_failures_preserve_rollback_evidence(
    tmp_path: Path,
) -> None:
    """Tool漂移必须失效，install后的verify异常仍要回滚并保留双重失败。

    Args:
        tmp_path: 隔离正式资产和可修改测试Git工具的临时根目录。
    """

    harness = _phase6_harness(tmp_path)
    planned = harness.application.plan_fault_injection(
        SYSTEM_ID,
        FaultPlanningRequest(
            entry_id=ENTRY_ID,
            obligation_id=harness.fault_obligation_id,
        ),
    )
    first = next(plan for plan in planned.plans if plan.selector.position == "FIRST")
    invoker = _FailingVerifyInvoker()
    execution = FaultLifecycleExecutor(
        harness.application.published_capabilities,
        invoker,
    ).execute(
        first,
        lambda: FaultObservedActionResult(
            outcome="error_response",
            error_code="GENERIC_FAILURE",
            entity_states=first.expected_entity_states,
        ),
    )

    assert execution.status == "FAILED"
    assert execution.primary_failure is not None
    assert execution.primary_failure.stage == "VERIFY"
    assert execution.primary_failure.error_code == "FAULT_LIFECYCLE_RUNTIME_FAILURE"
    assert execution.rollback_failure is not None
    assert execution.rollback_failure.error_code == "FAULT_ROLLBACK_NOT_CONFIRMED"
    assert invoker.stages == ["INSTALL", "VERIFY", "ROLLBACK"]

    tool = harness.application.fault_tool_candidates.list(SYSTEM_ID).candidates[0]
    script_path = Path(tool.source_path)
    script_path.write_text(
        script_path.read_text(encoding="utf-8") + "\n# protocol drift\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="FAULT_TOOL_CANDIDATE_DRIFT"):
        harness.application.fault_tool_candidates.get_current(harness.tool_ref)
    registry = harness.application.fault_capability_registry(SYSTEM_ID)
    assert [item.kind for item in registry.capabilities] == [FaultCapabilityKind.REAL_DATA]
    assert "FAULT_ADAPTER_CANDIDATE_DRIFT" in {issue.code for issue in registry.issues}


def test_lifecycle_failure_matrix_always_attempts_post_install_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install后的映射、资产、Action、Oracle和rollback失败都必须封闭。

    Args:
        tmp_path: 隔离正式阶段6资产的临时根目录。
        monkeypatch: 仅用于模拟verify Published资产在执行前漂移。
    """

    harness = _phase6_harness(tmp_path)
    planned = harness.application.plan_fault_injection(
        SYSTEM_ID,
        FaultPlanningRequest(
            entry_id=ENTRY_ID,
            obligation_id=harness.fault_obligation_id,
        ),
    )
    plan = next(item for item in planned.plans if item.selector.position == "FIRST")
    matching_action = FaultObservedActionResult(
        outcome="error_response",
        error_code="GENERIC_FAILURE",
        entity_states=plan.expected_entity_states,
    )

    missing_key_invoker = _LifecycleBranchInvoker("missing_install_key")
    missing_key = FaultLifecycleExecutor(
        harness.application.published_capabilities,
        missing_key_invoker,
    ).execute(plan, _ActionProbe(matching_action))
    assert missing_key.primary_failure is not None
    assert missing_key.primary_failure.error_code == "FAULT_INSTALL_OUTPUT_INVALID"
    assert missing_key.rollback_failure is None
    assert missing_key_invoker.stages == ["INSTALL", "ROLLBACK"]

    action_cases = [
        (
            _ActionProbe(FaultObservedActionResult(outcome="success")),
            "FAULT_EXPECTED_ERROR_NOT_OBSERVED",
            "ACTION",
        ),
        (
            _ActionProbe(
                FaultObservedActionResult(
                    outcome="exception",
                    error_code="GENERIC_FAILURE",
                    entity_states=plan.expected_entity_states,
                )
            ),
            "FAULT_RESULT_OUTCOME_MISMATCH",
            "ACTION",
        ),
        (
            _ActionProbe(raise_error=True),
            "FAULT_LIFECYCLE_RUNTIME_FAILURE",
            "ACTION",
        ),
        (
            _ActionProbe(
                FaultObservedActionResult(
                    outcome="error_response",
                    error_code="GENERIC_FAILURE",
                    entity_states=FaultExpectedEntityStates(
                        previous_entities="SUCCESS",
                        current_entity="SUCCESS",
                        remaining_entities="NOT_EXECUTED",
                    ),
                )
            ),
            "FAULT_ENTITY_ORACLE_MISMATCH",
            "ORACLE",
        ),
    ]
    for action_probe, error_code, stage in action_cases:
        # 每个Action/Oracle反例都重新安装并独立证明撤销已执行。
        invoker = _LifecycleBranchInvoker()
        execution = FaultLifecycleExecutor(
            harness.application.published_capabilities,
            invoker,
        ).execute(plan, action_probe)
        assert execution.primary_failure is not None
        assert execution.primary_failure.error_code == error_code
        assert execution.primary_failure.stage == stage
        assert execution.rollback_failure is None
        assert invoker.stages == ["INSTALL", "VERIFY", "ROLLBACK"]

    rollback_invoker = _LifecycleBranchInvoker("rollback_raises")
    rollback_failed = FaultLifecycleExecutor(
        harness.application.published_capabilities,
        rollback_invoker,
    ).execute(plan, _ActionProbe(matching_action))
    assert rollback_failed.primary_failure is None
    assert rollback_failed.rollback_failure is not None
    assert rollback_failed.rollback_failure.error_code == "FAULT_ROLLBACK_RUNTIME_FAILURE"
    assert rollback_failed.status == "FAILED"

    capability_service = harness.application.published_capabilities
    original_get_current = capability_service.get_current

    def reject_verify_asset(
        system_id: str,
        capability_id: str,
    ) -> PublishedOperationCapability:
        """仅使verify能力在执行前漂移，rollback仍可current重读。

        Args:
            system_id: Published能力所属系统。
            capability_id: 当前重读的不可变能力身份。

        Returns:
            非verify能力的current验证结果。

        Raises:
            KnowledgeValidationError: verify能力的漂移反例。
        """

        if capability_id == harness.verify.capability_id:
            raise KnowledgeValidationError("generic verify capability drift")
        return original_get_current(system_id, capability_id)

    monkeypatch.setattr(capability_service, "get_current", reject_verify_asset)
    drift_invoker = _LifecycleBranchInvoker()
    drifted = FaultLifecycleExecutor(
        capability_service,
        drift_invoker,
    ).execute(plan, _ActionProbe(matching_action))
    assert drifted.status == "BLOCKED"
    assert drifted.primary_failure is not None
    assert drifted.primary_failure.error_code == "BLOCKED_FAULT_LIFECYCLE_ASSET"
    assert drifted.rollback_failure is None
    assert drift_invoker.stages == ["INSTALL", "ROLLBACK"]


def test_missing_exact_ordinal_and_revoked_dependency_fail_closed(
    tmp_path: Path,
) -> None:
    """缺少精确序号或撤销直接依赖后不得继续发布、列表或规划Fault能力。

    Args:
        tmp_path: 隔离正式资产、规则和依赖历史的临时根目录。
    """

    harness = _phase6_harness(tmp_path)
    incomplete_recipe_id = _publish_trigger_recipe(
        harness.application,
        harness.target.candidate_ref.source_scan_id,
        harness.setup,
        "missing-middle",
        True,
    )
    blocked = harness.application.publish_fault_capability(
        SYSTEM_ID,
        FaultCapabilityDraftSubmission(
            publication_request_id="generic.real-data.missing-ordinal.v1",
            source_scan_id=harness.target.candidate_ref.source_scan_id,
            entry_id=ENTRY_ID,
            target_capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id=harness.target.capability_id,
            ),
            kind=FaultCapabilityKind.REAL_DATA,
            supported_positions=["MIDDLE"],
            fault_result=FaultResultDefinition(
                outcome="error_response",
                error_code="GENERIC_FAILURE",
            ),
            trigger_recipe_ref={
                "system_id": SYSTEM_ID,
                "recipe_id": incomplete_recipe_id,
            },
            trigger_contract_id=TRIGGER_CONTRACT_ID,
        ),
    )

    assert blocked.status == "BLOCKED"
    assert "BLOCKED_FAULT_INVOCATION_UNPROVEN" in {
        issue.code for issue in blocked.issues
    }
    harness.application.delete_system_dependency_binding(SYSTEM_ID, PROVIDER_ID)
    registry = harness.application.fault_capability_registry(SYSTEM_ID)
    assert registry.capabilities == []
    codes = {issue.code for issue in registry.issues}
    assert "FAULT_SETUP_DEPENDENCY_MISSING" in codes
    assert "FAULT_FAULT_DEPENDENCY_MISSING" in codes


def test_tool_protocol_rejects_textual_hints_and_untracked_sources(
    tmp_path: Path,
) -> None:
    """注释、帮助heredoc和未追踪文件不得伪造可发布Tool协议。

    Args:
        tmp_path: 隔离两个通用Git工作树的临时目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(
            system_id="generic-tool-parser",
            name="通用Tool解析验证",
            source_path=str(tmp_path),
        )
    )
    hinted_repository = tmp_path / "hinted-tool"
    hinted_script = _commit_tool_repository(
        hinted_repository,
        "hinted.sh",
        "#!/usr/bin/env bash\n"
        "# --app-uk --class-name --method-name --param-filter --mock-result --request POST\n"
        "cat <<'EOF'\n"
        'help: --verify fault_installed --rollback fault_removed {"mockKey":"fake"}\n'
        'OPENTEST_FAULT_VERIFY_OPERATION_ID="facade:fake.Tool#verify"\n'
        "EOF\n"
        "usage() { echo '--verify fault_installed --rollback fault_removed'; }\n"
        "echo 'usage only'\n",
    )

    hinted = application.discover_fault_tool_candidate(
        "generic-tool-parser",
        FaultToolCandidateSubmission(
            tool_id="hinted-tool",
            source_path=str(hinted_script),
        ),
    )

    assert hinted.status == "DISCOVERED"
    assert hinted.candidate is not None
    assert hinted.candidate.protocol.supports_install is False
    assert hinted.candidate.protocol.supports_verify is False
    assert hinted.candidate.protocol.supports_rollback is False
    assert hinted.candidate.protocol.verify_operation_ids == []

    undeclared_repository = tmp_path / "undeclared-tool"
    undeclared_script = _commit_tool_repository(
        undeclared_repository,
        "undeclared.sh",
        "#!/usr/bin/env bash\n"
        "MOCK_URL=\"${MOCK_URL:?}\"\n"
        "case \"$1\" in\n"
        "  --verify) echo '{\"fault_installed\":true}' ;;\n"
        "  --rollback) echo '{\"fault_removed\":true}' ;;\n"
        "  *) curl --request POST \"$MOCK_URL/mock2/auto/create\" "
        "--app-uk x --class-name x --method-name x --param-filter x --mock-result x; "
        "echo '{\"mockKey\":\"ephemeral\"}' ;;\n"
        "esac\n",
    )
    undeclared = application.discover_fault_tool_candidate(
        "generic-tool-parser",
        FaultToolCandidateSubmission(
            tool_id="undeclared-tool",
            source_path=str(undeclared_script),
        ),
    )
    assert undeclared.status == "DISCOVERED"
    assert undeclared.candidate is not None
    assert undeclared.candidate.protocol.supports_install is True
    assert undeclared.candidate.protocol.supports_verify is True
    assert undeclared.candidate.protocol.supports_rollback is True
    assert undeclared.candidate.protocol.install_operation_ids == []
    assert undeclared.candidate.protocol.verify_operation_ids == []
    assert undeclared.candidate.protocol.rollback_operation_ids == []
    assert set(undeclared.candidate.blockers).issuperset(
        {
            "FAULT_INSTALL_OPERATION_BINDING_MISSING",
            "FAULT_VERIFY_CAPABILITY_MISSING",
            "FAULT_ROLLBACK_CAPABILITY_MISSING",
        }
    )

    untracked_repository = tmp_path / "untracked-tool"
    untracked_repository.mkdir()
    ignored_script = untracked_repository / "ignored.sh"
    ignored_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    ignore_file = untracked_repository / ".gitignore"
    ignore_file.write_text("ignored.sh\n", encoding="utf-8")
    _git(untracked_repository, "init", "-q")
    _git(untracked_repository, "add", ".gitignore")
    _git(
        untracked_repository,
        "-c",
        "user.name=OpenTest",
        "-c",
        "user.email=opentest@example.invalid",
        "commit",
        "-q",
        "-m",
        "ignore untracked tool",
    )

    untracked = application.discover_fault_tool_candidate(
        "generic-tool-parser",
        FaultToolCandidateSubmission(
            tool_id="untracked-tool",
            source_path=str(ignored_script.resolve()),
        ),
    )

    assert untracked.status == "BLOCKED"
    assert [issue.code for issue in untracked.issues] == ["FAULT_TOOL_SOURCE_INVALID"]


def test_real_registered_workspace_has_no_publishable_fault_assets(
    tmp_path: Path,
) -> None:
    """正式Refund/Booking副本没有Published与Recipe时必须保持真实阻塞且无Attempt。

    Args:
        tmp_path: 正式知识仓库只读副本的临时根目录。
    """

    project_root = Path(__file__).resolve().parents[2]
    formal_root = project_root / "open-test-knowledge"
    isolated_root = tmp_path / "open-test-knowledge"
    shutil.copytree(
        formal_root,
        isolated_root,
        ignore=shutil.ignore_patterns(".opentest", ".git", "__pycache__"),
    )
    scan_root = formal_root / ".opentest/scans"
    if scan_root.exists():
        shutil.copytree(scan_root, isolated_root / ".opentest/scans")
    application = OpenTestApplication(isolated_root)
    system_id = "ifightchainsaas.java.refund.core"
    manifest = application.source_analysis.artifacts.read(system_id, "latest")
    entry = next(
        item for item in manifest.entries if item.display_name == "RefundFacade#createOrder"
    )
    attempts_before = application.list_hybrid_case_attempts(system_id)

    planning = application.plan_fault_injection(
        system_id,
        FaultPlanningRequest(
            entry_id=entry.entry_id,
            obligation_id="obligation:missing-real-fault",
        ),
    )

    assert planning.status == "BLOCKED"
    assert planning.plans == []
    assert {issue.code for issue in planning.issues}.issubset(
        {
            "BLOCKED_FAULT_COVERAGE_MANIFEST",
            "BLOCKED_FAULT_OBLIGATION_NOT_FROZEN",
        }
    )
    assert application.fault_capability_registry(system_id).capabilities == []
    assert application.list_hybrid_case_attempts(system_id) == attempts_before == []


class _FailingVerifyInvoker:
    """仅为异常分支契约测试提供可观察调用序列，不作为真实链路通过证据。"""

    def __init__(self) -> None:
        """初始化空阶段序列。

        Side Effects:
            只在内存中记录测试调用阶段。
        """

        self.stages: list[str] = []

    def invoke(
        self,
        capability: PublishedOperationCapability,
        logical_inputs: dict[str, object],
        stage: str,
    ) -> FaultPublishedInvocation:
        """让install成功、verify抛错并让rollback返回未确认。

        Args:
            capability: 当前正式Published能力，仅用于确认调用走正式引用。
            logical_inputs: 生命周期组装的逻辑输入。
            stage: INSTALL、VERIFY或ROLLBACK阶段。

        Returns:
            install或rollback的归一化响应。

        Raises:
            RuntimeError: verify阶段模拟执行边界的非业务异常。
        """

        assert capability.capability_id
        assert logical_inputs
        self.stages.append(stage)
        if stage == "INSTALL":
            return FaultPublishedInvocation(
                status="PASSED",
                result={"output": {"mockKey": "ephemeral-key"}},
            )
        if stage == "VERIFY":
            raise RuntimeError("generic verify transport failure")
        return FaultPublishedInvocation(
            status="PASSED",
            result={"output": {"faultRemoved": False}},
        )


class _LifecycleBranchInvoker:
    """为生命周期失败矩阵提供可控的通用Published调用结果。"""

    def __init__(self, mode: str = "happy") -> None:
        """初始化一个明确失败模式和空调用轨迹。

        Args:
            mode: happy、missing_install_key、verify_false或rollback_raises。

        Side Effects:
            只保存内存测试状态，不访问外部服务。
        """

        self.mode = mode
        self.stages: list[str] = []

    def invoke(
        self,
        capability: PublishedOperationCapability,
        logical_inputs: dict[str, object],
        stage: str,
    ) -> FaultPublishedInvocation:
        """按阶段返回可验证的通用响应或抛出撤销异常。

        Args:
            capability: 执行器在当前时点重新验证的Published能力。
            logical_inputs: 生命周期组装的逻辑输入。
            stage: INSTALL、VERIFY或ROLLBACK。

        Returns:
            不含真实环境值的归一化调用结果。

        Raises:
            RuntimeError: rollback_raises模式到达ROLLBACK时抛出。
        """

        assert capability.capability_id
        assert logical_inputs
        self.stages.append(stage)
        if stage == "INSTALL":
            install_output = (
                {} if self.mode == "missing_install_key" else {"mockKey": "ephemeral-key"}
            )
            return FaultPublishedInvocation(
                status="PASSED",
                result={"output": install_output},
            )
        if stage == "VERIFY":
            return FaultPublishedInvocation(
                status="PASSED",
                result={
                    "output": {"faultInstalled": self.mode != "verify_false"}
                },
            )
        if self.mode == "rollback_raises":
            raise RuntimeError("generic rollback transport failure")
        return FaultPublishedInvocation(
            status="PASSED",
            result={"output": {"faultRemoved": True}},
        )


class _ActionProbe:
    """为Action/Oracle分支提供可调用的归一化观察。"""

    def __init__(
        self,
        observed: FaultObservedActionResult | None = None,
        raise_error: bool = False,
    ) -> None:
        """固定一个Action观察或运行时异常。

        Args:
            observed: 正常返回的Action观察。
            raise_error: 是否在Action边界抛出通用异常。
        """

        self.observed = observed
        self.raise_error = raise_error

    def __call__(self) -> FaultObservedActionResult:
        """返回预置观察或模拟Action边界异常。

        Returns:
            归一化Action结果。

        Raises:
            RuntimeError: 测试显式选择Action运行时异常时抛出。
            AssertionError: 未配置观察且未要求抛错。
        """

        if self.raise_error:
            raise RuntimeError("generic action transport failure")
        assert self.observed is not None
        return self.observed


def _phase6_harness(
    tmp_path: Path,
    publish_scopes: list[set[str]] | None = None,
    resources: list[DiscoveredResource] | None = None,
) -> Phase6Harness:
    """建立不含业务名称的正式阶段1至6集成环境。

    Args:
        tmp_path: 隔离源码、知识和Git工具根目录。
        publish_scopes: 可选收集registry写入时已锁定的系统范围。
        resources: 可选由consumer scan固定的资源证据。

    Returns:
        已发布Real Data与Mock能力并冻结两个Fault义务的环境。

    Side Effects:
        写临时Java/Git文件、正式Published/Recipe/规则和Fault注册表。
    """

    iteration_evidence = _evidence(
        "evidence:fault:ordered-items",
        "field_influence",
        field_paths=["items"],
        influence_kind="collection_iteration",
        operation_ids=[ENTRY_ID],
        binding_kind="entry_parameter",
    ).model_copy(
        update={
            "method_symbol_id": "sample.AtomicFacadeImpl#inspect(sample.AtomicRequest)"
        }
    )
    compiler = _compiler_harness(
        tmp_path,
        None,
        evidence=[iteration_evidence],
        mutability=OperationMutability.WRITE,
        include_items=True,
        resources=resources,
    )
    application = compiler.application
    frozen_manifest = application.case_rules.preview(SYSTEM_ID, ENTRY_ID).manifest
    fault_obligations = [
        obligation
        for obligation in frozen_manifest.obligations
        if isinstance(obligation, FaultInjectionObligation)
    ]
    assert len(fault_obligations) == 1
    fault_obligation = fault_obligations[0]
    assert fault_obligation.invocation_positions == ["FIRST", "MIDDLE", "LAST"]
    provider_capabilities = _publish_fault_provider(application, tmp_path)
    setup = provider_capabilities["prepare"]
    install = provider_capabilities["install"]
    verify = provider_capabilities["verify"]
    rollback = provider_capabilities["rollback"]
    application.put_system_dependency_binding(
        SYSTEM_ID,
        SystemDependencyBindingSubmission(
            provider_system_id=PROVIDER_ID,
            role=SystemDependencyRole.UPSTREAM,
            purposes=[SystemDependencyPurpose.SETUP, SystemDependencyPurpose.FAULT],
        ),
    )
    recipe_id = _publish_trigger_recipe(application, compiler.scan_id, setup)
    _write_fault_action_and_trigger_rules(
        application,
        compiler.action,
        compiler.scan_id,
    )
    tool_ref = _discover_complete_tool(application, tmp_path)
    if publish_scopes is not None:
        original_publish = application.fault_capabilities.registry.publish

        def capture_publish_scope(capability: object) -> object:
            """记录Fault registry写入时多系统事务的实际锁范围。

            Args:
                capability: 通过服务完整验证的Fault能力。

            Returns:
                原registry持久化结果。

            Side Effects:
                仅在测试内存中附加当前锁定系统集合。
            """

            active_scope = set(
                getattr(application.store._transaction_state, "system_ids", ())
            )
            publish_scopes.append(active_scope)
            return original_publish(capability)

        application.fault_capabilities.registry.publish = capture_publish_scope
    fault_result = FaultResultDefinition(
        outcome="error_response",
        error_code="GENERIC_FAILURE",
    )
    real_data = application.publish_fault_capability(
        SYSTEM_ID,
        FaultCapabilityDraftSubmission(
            publication_request_id="generic.real-data.middle.v1",
            source_scan_id=compiler.scan_id,
            entry_id=ENTRY_ID,
            target_capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id=compiler.action.capability_id,
            ),
            kind=FaultCapabilityKind.REAL_DATA,
            supported_positions=["MIDDLE"],
            fault_result=fault_result,
            trigger_recipe_ref={"system_id": SYSTEM_ID, "recipe_id": recipe_id},
            trigger_contract_id=TRIGGER_CONTRACT_ID,
        ),
    )
    mock = application.publish_fault_capability(
        SYSTEM_ID,
        FaultCapabilityDraftSubmission(
            publication_request_id="generic.mock.all-positions.v1",
            source_scan_id=compiler.scan_id,
            entry_id=ENTRY_ID,
            target_capability_ref=PublishedCapabilityRef(
                system_id=SYSTEM_ID,
                capability_id=compiler.action.capability_id,
            ),
            kind=FaultCapabilityKind.MOCK,
            supported_positions=["FIRST", "MIDDLE", "LAST"],
            fault_result=fault_result,
            trigger_recipe_ref={"system_id": SYSTEM_ID, "recipe_id": recipe_id},
            trigger_contract_id=TRIGGER_CONTRACT_ID,
            tool_candidate_ref=tool_ref,
            install_capability_ref=PublishedCapabilityRef(
                system_id=PROVIDER_ID,
                capability_id=install.capability_id,
            ),
            verify_capability_ref=PublishedCapabilityRef(
                system_id=PROVIDER_ID,
                capability_id=verify.capability_id,
            ),
            rollback_capability_ref=PublishedCapabilityRef(
                system_id=PROVIDER_ID,
                capability_id=rollback.capability_id,
            ),
        ),
    )
    assert real_data.status == "PUBLISHED", real_data.issues
    assert mock.status == "PUBLISHED", mock.issues
    return Phase6Harness(
        application=application,
        target=compiler.action,
        setup=setup,
        install=install,
        verify=verify,
        rollback=rollback,
        tool_ref=tool_ref,
        recipe_id=recipe_id,
        fault_obligation_id=fault_obligation.obligation_id,
    )


def _publish_fault_provider(
    application: OpenTestApplication,
    tmp_path: Path,
) -> dict[str, PublishedOperationCapability]:
    """扫描并通过正式发布服务建立Setup与三段Fault生命周期原子能力。

    Args:
        application: 已有consumer和目标Action的隔离应用。
        tmp_path: Provider真实Java文件所在临时根目录。

    Returns:
        按prepare/install/verify/rollback角色索引的正式能力。

    Side Effects:
        注册独立provider、发布latest scan和写入本地QA绑定及Published目录。
    """

    source_root = tmp_path / "generic-fault-provider-source"
    source_file = source_root / "src/main/java/sample/FaultSupportFacade.java"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(
        "package sample; "
        "interface FaultSupportFacade { "
        "TriggerResponse prepare(TriggerRequest request); "
        "InstallResponse install(InstallRequest request); "
        "VerifyResponse verify(KeyRequest request); "
        "RollbackResponse rollback(KeyRequest request); } "
        "class TriggerRequest { String partition; } "
        "class TriggerResponse { String mode; Integer totalInvocations; Integer firstOrdinal; "
        "Integer middleOrdinal; Integer lastOrdinal; String expectedErrorCode; "
        "String expectedOutcome; java.util.List<String> entities; } "
        "class InstallRequest { String targetOperation; Integer totalInvocations; "
        "Integer invocationNumber; String faultOutcome; String faultErrorCode; } "
        "class InstallResponse { String mockKey; } "
        "class KeyRequest { String mockKey; } "
        "class VerifyResponse { Boolean faultInstalled; } "
        "class RollbackResponse { Boolean faultRemoved; } "
        "class FaultSupportFacadeImpl implements FaultSupportFacade { "
        "public TriggerResponse prepare(TriggerRequest request) { return new TriggerResponse(); } "
        "public InstallResponse install(InstallRequest request) { return new InstallResponse(); } "
        "public VerifyResponse verify(KeyRequest request) { return new VerifyResponse(); } "
        "public RollbackResponse rollback(KeyRequest request) { return new RollbackResponse(); } }\n",
        encoding="utf-8",
    )
    baseline = SourceBaseline(source_path=str(source_root), commit="generic-fault-provider-v1")
    application.register_system(
        SystemDefinition(
            system_id=PROVIDER_ID,
            name="通用故障支持Provider",
            source_path=str(source_root),
        )
    )
    scan_id = "scan-generic-fault-provider-v1"
    interface_name = "sample.FaultSupportFacade"
    implementation_name = "sample.FaultSupportFacadeImpl"
    method_contracts = {
        "prepare": ("sample.TriggerRequest", "sample.TriggerResponse"),
        "install": ("sample.InstallRequest", "sample.InstallResponse"),
        "verify": ("sample.KeyRequest", "sample.VerifyResponse"),
        "rollback": ("sample.KeyRequest", "sample.RollbackResponse"),
    }
    provider_dsf_operation_ids = {
        "prepare": "dsf:generic-fault-provider:prepare",
        "install": "dsf:generic-fault-provider:install",
        "verify": "dsf:generic-fault-provider:verify",
        "rollback": "dsf:generic-fault-provider:rollback",
    }
    methods: list[SemanticMethodDefinition] = []
    entries: list[EntryPoint] = []
    operations: list[DsfOperationDefinition] = []
    for role, (request_type, response_type) in method_contracts.items():
        # 每个角色用独立Entry和源码symbol证明Candidate与既有Operation是同一原子方法。
        interface_symbol = f"{interface_name}#{role}({request_type})"
        implementation_symbol = f"{implementation_name}#{role}({request_type})"
        source_ref = SourceReference(
            path=str(source_file),
            symbol=implementation_symbol,
            line=1,
            commit=baseline.commit,
        )
        entry_id = f"facade:{interface_name}#{role}"
        methods.extend(
            [
                SemanticMethodDefinition(
                    symbol_id=interface_symbol,
                    qualified_class_name=interface_name,
                    method_name=role,
                    parameter_names=["request"],
                    parameter_types=[request_type.rsplit(".", 1)[-1]],
                    parameter_qualified_types=[request_type],
                    return_type=response_type.rsplit(".", 1)[-1],
                    return_qualified_type=response_type,
                    owner_type_kind="interface",
                    source_ref=source_ref.model_copy(update={"symbol": interface_symbol}),
                    entry_point_ids=[entry_id],
                ),
                SemanticMethodDefinition(
                    symbol_id=implementation_symbol,
                    qualified_class_name=implementation_name,
                    method_name=role,
                    parameter_names=["request"],
                    parameter_types=[request_type.rsplit(".", 1)[-1]],
                    parameter_qualified_types=[request_type],
                    return_type=response_type.rsplit(".", 1)[-1],
                    return_qualified_type=response_type,
                    owner_interfaces=[interface_name],
                    owner_type_kind="class",
                    has_executable_body=True,
                    source_ref=source_ref,
                    entry_point_ids=[entry_id],
                ),
            ]
        )
        entries.append(
            EntryPoint(
                entry_id=entry_id,
                system_id=PROVIDER_ID,
                kind=KnowledgeNodeKind.FACADE,
                display_name=f"FaultSupportFacade#{role}",
                source_id=f"{interface_name}#{role}",
                source_path=str(source_file),
                request_type=request_type,
                response_type=response_type,
            )
        )
        operations.append(
            DsfOperationDefinition(
                    operation_id=provider_dsf_operation_ids[role],
                provider_system_id=PROVIDER_ID,
                gs_name="generic-fault-provider-service",
                service_name=interface_name,
                version="1.0.0",
                action=role,
                request_type=request_type,
                response_type=response_type,
                mutability=(
                    DsfOperationMutability.READ_ONLY
                    if role == "verify"
                    else DsfOperationMutability.WRITE
                ),
                source_refs=[
                    source_ref.model_copy(update={"symbol": f"{interface_name}#{role}"})
                ],
            )
        )
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="generic-phase6-test",
        analyzer_version="1",
        system_id=PROVIDER_ID,
        methods=methods,
        types=_provider_types(source_file, baseline.commit),
    )
    manifest = ScanManifest(
        scan_id=scan_id,
        system_id=PROVIDER_ID,
        baseline=baseline,
        entries=entries,
        dsf_profile=DsfClientProfile(
            system_id=PROVIDER_ID,
            client_name="generic-fault-provider-client",
            routing_environment="qa",
            target_environment="test",
            status=DsfProfileStatus.CONFIRMED,
            source_refs=[operations[0].source_refs[0]],
        ),
        dsf_operations=operations,
        semantic_analysis=semantic,
    )
    artifacts = application.source_analysis.artifacts
    artifacts.write_scan_bundle(manifest, ProgramCaseAnalysisBuilder().build(manifest))
    application.store.update_source_baseline(PROVIDER_ID, baseline)
    artifacts.publish_latest(PROVIDER_ID, scan_id)
    application.local_settings.write(
        PROVIDER_ID,
        "generic-phase6-local-token",
        "http://qa.example/gateway",
    )
    schemas = _provider_capability_schemas()
    published = {}
    candidates = application.candidate_operation_catalog(PROVIDER_ID).candidates
    operation_catalog = application.operation_catalog.derive(PROVIDER_ID)
    for role in method_contracts:
        # 发布必须走CandidateDraft校验，测试不直接写Published注册表。
        candidate = next(
            item
            for item in candidates
            if item.qualified_name.endswith(f"#{role}") and item.entry_ids
        )
        operation = next(
            item
            for item in operation_catalog
            if item.operation_id == f"facade:sample.FaultSupportFacade#{role}"
        )
        input_schema, input_mapping, output_schema, output_mapping = schemas[role]
        result = application.publish_operation_capability(
            PROVIDER_ID,
            CapabilityDraftSubmission(
                publication_request_id=f"generic.fault-provider.{role}.v1",
                candidate_ref=_candidate_ref(candidate),
                provider_operation_ref=ProviderOperationRef(
                    source_system_id=PROVIDER_ID,
                    operation_id=operation.operation_id,
                    source_scan_id=operation.source_scan_id,
                ),
                business_name=f"通用故障支持{role}",
                business_purpose="验证阶段6正式原子能力、生命周期角色和Schema绑定。",
                input_schema=input_schema,
                input_mapping=input_mapping,
                output_fact_schema=output_schema,
                output_mapping=output_mapping,
            ),
        )
        assert result.status == "PUBLISHED", (role, result.issues)
        assert result.capability is not None
        published[role] = result.capability
    return published


def _provider_types(source_file: Path, commit: str) -> list[SemanticTypeDefinition]:
    """构造与通用Java源码逐字段一致的DTO语义定义。

    Args:
        source_file: 类型真实声明所在Java文件。
        commit: Provider扫描基线。

    Returns:
        Candidate和Operation Schema可共同解析的完整DTO集合。
    """

    definitions = {
        "sample.TriggerRequest": [("partition", "String", "java.lang.String", False)],
        "sample.TriggerResponse": [
            ("mode", "String", "java.lang.String", False),
            ("totalInvocations", "Integer", "java.lang.Integer", False),
            ("firstOrdinal", "Integer", "java.lang.Integer", False),
            ("middleOrdinal", "Integer", "java.lang.Integer", False),
            ("lastOrdinal", "Integer", "java.lang.Integer", False),
            ("expectedErrorCode", "String", "java.lang.String", False),
            ("expectedOutcome", "String", "java.lang.String", False),
            ("entities", "java.util.List<String>", "java.lang.String", True),
        ],
        "sample.InstallRequest": [
            ("targetOperation", "String", "java.lang.String", False),
            ("totalInvocations", "Integer", "java.lang.Integer", False),
            ("invocationNumber", "Integer", "java.lang.Integer", False),
            ("faultOutcome", "String", "java.lang.String", False),
            ("faultErrorCode", "String", "java.lang.String", False),
        ],
        "sample.InstallResponse": [("mockKey", "String", "java.lang.String", False)],
        "sample.KeyRequest": [("mockKey", "String", "java.lang.String", False)],
        "sample.VerifyResponse": [("faultInstalled", "Boolean", "java.lang.Boolean", False)],
        "sample.RollbackResponse": [("faultRemoved", "Boolean", "java.lang.Boolean", False)],
    }
    types = []
    for qualified_type, fields in definitions.items():
        source_ref = SourceReference(
            path=str(source_file),
            symbol=qualified_type,
            line=1,
            commit=commit,
        )
        types.append(
            SemanticTypeDefinition(
                symbol_id=qualified_type,
                qualified_class_name=qualified_type,
                simple_name=qualified_type.rsplit(".", 1)[-1],
                fields=[
                    SemanticFieldDefinition(
                        field_name=name,
                        declared_type=declared,
                        referenced_type=referenced,
                        collection=collection,
                        runtime_required=True,
                        runtime_required_evidence=["jakarta.validation.constraints.NotNull"],
                        source_ref=source_ref,
                    )
                    for name, declared, referenced, collection in fields
                ],
                source_ref=source_ref,
            )
        )
    return types


def _provider_capability_schemas() -> dict[str, tuple[dict, dict, dict, dict]]:
    """定义四个通用Published能力的逻辑Schema与provider映射。

    Returns:
        每个角色的input schema、input mapping、output schema和output mapping。
    """

    trigger_properties = {
        "mode": {"type": "string"},
        "totalInvocations": {"type": "integer"},
        "firstOrdinal": {"type": "integer"},
        "middleOrdinal": {"type": "integer"},
        "lastOrdinal": {"type": "integer"},
        "expectedErrorCode": {"type": "string"},
        "expectedOutcome": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"}},
    }
    install_inputs = {
        "target_operation": {"type": "string"},
        "total_invocations": {"type": "integer"},
        "invocation_number": {"type": "integer"},
        "fault_outcome": {"type": "string"},
        "fault_error_code": {"type": "string"},
    }
    return {
        "prepare": (
            _object_schema({"partition": {"type": "string"}}),
            {"partition": "partition"},
            _object_schema({"trigger": _object_schema(trigger_properties)}),
            {"trigger": "output"},
        ),
        "install": (
            _object_schema(install_inputs),
            {
                "target_operation": "targetOperation",
                "total_invocations": "totalInvocations",
                "invocation_number": "invocationNumber",
                "fault_outcome": "faultOutcome",
                "fault_error_code": "faultErrorCode",
            },
            _object_schema({"mock_key": {"type": "string"}}),
            {"mock_key": "output.mockKey"},
        ),
        "verify": (
            _object_schema({"mock_key": {"type": "string"}}),
            {"mock_key": "mockKey"},
            _object_schema({"fault_installed": {"type": "boolean"}}),
            {"fault_installed": "output.faultInstalled"},
        ),
        "rollback": (
            _object_schema({"mock_key": {"type": "string"}}),
            {"mock_key": "mockKey"},
            _object_schema({"fault_removed": {"type": "boolean"}}),
            {"fault_removed": "output.faultRemoved"},
        ),
    }


def _object_schema(properties: dict[str, dict]) -> dict:
    """把通用字段表转换为关闭额外字段的必填对象Schema。

    Args:
        properties: 逻辑字段到子Schema的映射。

    Returns:
        所有字段必填的严格JSON Schema对象。
    """

    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _publish_trigger_recipe(
    application: OpenTestApplication,
    consumer_scan_id: str,
    setup: PublishedOperationCapability,
    recipe_suffix: str = "v1",
    omit_middle_ordinal: bool = False,
) -> str:
    """发布从真实provider输出派生精确调用序号的Trigger Recipe。

    Args:
        application: 已注册consumer和provider的隔离应用。
        consumer_scan_id: Recipe绑定的consumer latest代际。
        setup: 真实provider Published前置能力。
        recipe_suffix: 不可变Recipe身份后缀。
        omit_middle_ordinal: 是否构造缺少MIDDLE精确序号的失败关闭反例。

    Returns:
        成功发布的不可变Recipe ID。

    Side Effects:
        写服务器Setup规则和consumer Recipe Git资产。
    """

    setup_ref = PublishedCapabilityRef(
        system_id=PROVIDER_ID,
        capability_id=setup.capability_id,
    )
    trigger_fields = [
        SetupFactRequiredField(path="mode", schema_type="string"),
        SetupFactRequiredField(path="totalInvocations", schema_type="integer"),
        SetupFactRequiredField(path="firstOrdinal", schema_type="integer"),
        SetupFactRequiredField(path="middleOrdinal", schema_type="integer"),
        SetupFactRequiredField(path="lastOrdinal", schema_type="integer"),
        SetupFactRequiredField(path="expectedErrorCode", schema_type="string"),
        SetupFactRequiredField(path="expectedOutcome", schema_type="string"),
        SetupFactRequiredField(path="entities", schema_type="array"),
    ]
    application.setup_contract_rules.write(
        SetupContractRuleSet(
            system_id=SYSTEM_ID,
            fact_contracts=[
                SetupFactContractDefinition(
                    fact_contract_id=TRIGGER_FACT_ID,
                    required_origin=SetupFactOrigin.UPSTREAM_PUBLISHED_OUTPUT,
                    required_fields=trigger_fields,
                )
            ],
            input_policies=[
                SetupInputPolicy(
                    capability_ref=setup_ref,
                    input_path="partition",
                    allowed_sources=["literal"],
                    allowed_literal_values=["QA_PARTITION"],
                )
            ],
        )
    )
    constraints = [
        FactConstraint(path="totalInvocations", operator="eq", expected=3),
        FactConstraint(path="firstOrdinal", operator="eq", expected=1),
        FactConstraint(path="lastOrdinal", operator="eq", expected=3),
        FactConstraint(
            path="expectedErrorCode",
            operator="eq",
            expected="GENERIC_FAILURE",
        ),
        FactConstraint(
            path="expectedOutcome",
            operator="eq",
            expected="error_response",
        ),
        FactConstraint(
            path="entities",
            operator="cardinality",
            expected="MULTIPLE",
        ),
    ]
    if not omit_middle_ordinal:
        # MIDDLE必须由Recipe的Published输出约束证明，不能由Planner默认成第二次调用。
        constraints.insert(
            2,
            FactConstraint(path="middleOrdinal", operator="eq", expected=2),
        )
    recipe_id = f"setup:generic-fault-trigger-{recipe_suffix}"
    publication = application.publish_data_setup_recipe(
        SYSTEM_ID,
        DataSetupRecipeSubmission(
            recipe_id=recipe_id,
            entry_id=ENTRY_ID,
            entry_source_scan_id=consumer_scan_id,
            name="构造通用精确故障触发数据",
            steps=[
                DataSetupStep(
                    step_id="prepare-trigger",
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
                    fact_name="fault_trigger",
                    fact_contract_id=TRIGGER_FACT_ID,
                    from_step_id="prepare-trigger",
                    output_path="trigger",
                    constraints=constraints,
                )
            ],
        ),
    )
    assert publication.status == "PUBLISHED", publication.issues
    return recipe_id


def _write_fault_action_and_trigger_rules(
    application: OpenTestApplication,
    target: PublishedOperationCapability,
    scan_id: str,
) -> None:
    """把Trigger Fact绑定到Action并发布受控序号语义。

    Args:
        application: 规则所属consumer应用。
        target: 当前被测Action能力。
        scan_id: Action Profile绑定的consumer latest代际。

    Side Effects:
        替换current Case编译规则并追加Fault Trigger规则版本。
    """

    target_ref = PublishedCapabilityRef(
        system_id=SYSTEM_ID,
        capability_id=target.capability_id,
    )
    current_rules = application.case_compilation_rules.read(SYSTEM_ID)
    oracle = current_rules.oracle_templates[0]
    mode_binding = ActionInputBindingTemplate(
        input_path="mode",
        source_ref=SetupFactInputRef(
            fact_contract_id=TRIGGER_FACT_ID,
            fact_path="mode",
        ),
    )
    amount_binding = ActionInputBindingTemplate(
        input_path="amount",
        source_ref=SafeConstantInputRef(value=1),
    )
    application.case_compilation_rules.write(
        CaseCompilationRuleSet(
            system_id=SYSTEM_ID,
            action_profiles=[
                CaseCompilationActionProfile(
                    profile_id="action-profile:generic-inspect:fault-v1",
                    entry_id=ENTRY_ID,
                    source_scan_id=scan_id,
                    action_capability_ref=target_ref,
                    input_bindings=[mode_binding, amount_binding],
                    action_fact_contract=current_rules.action_profiles[0].action_fact_contract,
                    oracle_template_id=oracle.oracle_template_id,
                    resource_lifecycle_policy="per_variant",
                )
            ],
            input_policies=[
                CapabilityInputSourcePolicy(
                    capability_ref=target_ref,
                    input_path="mode",
                    allowed_sources=["setup_fact"],
                ),
                CapabilityInputSourcePolicy(
                    capability_ref=target_ref,
                    input_path="amount",
                    allowed_sources=["safe_constant"],
                    allowed_safe_constants=[1],
                ),
            ],
            oracle_templates=[oracle],
        )
    )
    application.fault_trigger_rules.write(
        FaultTriggerRuleSet(
            system_id=SYSTEM_ID,
            contracts=[
                FaultTriggerFactContractDefinition(
                    trigger_contract_id=TRIGGER_CONTRACT_ID,
                    setup_fact_contract_id=TRIGGER_FACT_ID,
                    target_capability_ref=target_ref,
                    total_invocations_path="totalInvocations",
                    position_ordinal_paths={
                        "FIRST": "firstOrdinal",
                        "MIDDLE": "middleOrdinal",
                        "LAST": "lastOrdinal",
                    },
                    expected_error_code_path="expectedErrorCode",
                    expected_outcome_path="expectedOutcome",
                    entity_collection_path="entities",
                    action_binding_fact_paths=["mode"],
                )
            ],
        )
    )


def _discover_complete_tool(
    application: OpenTestApplication,
    tmp_path: Path,
) -> FaultToolCandidateRef:
    """创建干净Git工具并让程序从源码发现完整Mock生命周期协议。

    Args:
        application: Tool Candidate归属的consumer应用。
        tmp_path: 临时Git工作树父目录。

    Returns:
        exact commit绑定的不可执行Tool Candidate引用。

    Side Effects:
        创建并提交一个通用脚本，然后写入安全候选摘要。
    """

    repository = tmp_path / "generic-fault-tool"
    repository.mkdir()
    script_path = repository / "generic-interface-mock.sh"
    script_path.write_text(
        "#!/usr/bin/env bash\n"
        "MOCK_URL=\"${MOCK_URL:?}\"\n"
        "OPENTEST_FAULT_INSTALL_OPERATION_ID=\"facade:sample.FaultSupportFacade#install\"\n"
        "OPENTEST_FAULT_VERIFY_OPERATION_ID=\"facade:sample.FaultSupportFacade#verify\"\n"
        "OPENTEST_FAULT_ROLLBACK_OPERATION_ID=\"facade:sample.FaultSupportFacade#rollback\"\n"
        "case \"$1\" in\n"
        "  --verify) echo '{\"fault_installed\":true}' ;;\n"
        "  --rollback) echo '{\"fault_removed\":true}' ;;\n"
        "  *) curl --request POST \"$MOCK_URL/mock2/auto/create\" "
        "--app-uk x --class-name x --method-name x --param-filter x --mock-result x; "
        "echo '{\"mockKey\":\"ephemeral\"}' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    _git(repository, "init", "-q")
    _git(repository, "add", "generic-interface-mock.sh")
    _git(
        repository,
        "-c",
        "user.name=OpenTest",
        "-c",
        "user.email=opentest@example.invalid",
        "commit",
        "-q",
        "-m",
        "generic fault tool",
    )
    discovery = application.discover_fault_tool_candidate(
        SYSTEM_ID,
        FaultToolCandidateSubmission(
            tool_id=TOOL_ID,
            source_path=str(script_path.resolve()),
        ),
    )
    assert discovery.status == "DISCOVERED", discovery.issues
    assert discovery.candidate is not None
    assert discovery.candidate.blockers == []
    return FaultToolCandidateRef(
        system_id=SYSTEM_ID,
        candidate_id=discovery.candidate.candidate_id,
        source_commit=discovery.candidate.source_commit,
    )


def _commit_tool_repository(
    repository: Path,
    filename: str,
    script_text: str,
) -> Path:
    """创建一个仅包通用脚本的干净Git来源。

    Args:
        repository: 待初始化的临时工作树。
        filename: 工作树内的脚本文件名。
        script_text: 不含真实业务名称或环境密钥的测试源文本。

    Returns:
        已提交脚本的绝对路径。

    Side Effects:
        创建临时文件并产生一个本地Git commit。
    """

    repository.mkdir()
    script_path = repository / filename
    script_path.write_text(script_text, encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "add", filename)
    _git(
        repository,
        "-c",
        "user.name=OpenTest",
        "-c",
        "user.email=opentest@example.invalid",
        "commit",
        "-q",
        "-m",
        "generic tool source",
    )
    return script_path.resolve()


def _git(workdir: Path, *arguments: str) -> str:
    """在临时通用工具仓库执行一个确定性Git命令。

    Args:
        workdir: 临时Git仓库路径。
        arguments: 不经shell解释的Git参数。

    Returns:
        去除首尾空白的标准输出。

    Raises:
        CalledProcessError: Git初始化或提交失败。
    """

    completed = subprocess.run(
        ["git", "-C", str(workdir), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()
