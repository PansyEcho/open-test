"""验证回归Suite批量编排、BLOCKED保留和QA全局Job一次性确认门禁。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from opentest.application.regression import (
    GlobalJobApprovalGate,
    GlobalJobApprovalScope,
    GlobalJobAuthorizationRequest,
    GlobalJobImpactEstimate,
    GlobalJobTarget,
    RegressionBatchOrchestrator,
    RegressionBatchRequest,
    RegressionRunStatus,
    RegressionSuite,
    RegressionSuiteReader,
    ResourceEvidenceLevel,
    VariantResourceEvidence,
    VariantRunOutcome,
)
from opentest.domain.errors import KnowledgeValidationError


VARIANT_IDS = [
    "variant:regression:normal",
    "variant:regression:blocked",
    "variant:regression:failed",
    "variant:regression:after-failure",
]


class MutableClock:
    """为Token期限测试提供可显式推进的带时区时钟。"""

    def __init__(self):
        """从固定UTC时间初始化可变时钟。"""

        self.current = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        """返回当前测试时间，不隐式推进。"""

        return self.current

    def advance(self, seconds: int) -> None:
        """按秒推进测试时钟以模拟Token过期。

        Args:
            seconds: 需要向未来推进的秒数。

        Side Effects:
            更新后续时钟读取结果。
        """

        self.current += timedelta(seconds=seconds)


class FixedTokenFactory:
    """为门禁测试生成确定且长度合规的不同Token。"""

    def __init__(self):
        """初始化单调递增的Token序号。"""

        self.counter = 0

    def __call__(self) -> str:
        """返回一个新的确定性Token。"""

        self.counter += 1
        return f"confirmation-token-{self.counter:04d}"


class RecordingRunner:
    """记录变体调用并返回预设独立Run结果，不触发任何QA请求。"""

    def __init__(self, outcomes: dict[str, VariantRunOutcome]):
        """绑定按变体ID索引的预设结果。

        Args:
            outcomes: 每个可能执行变体对应的结果。
        """

        self.outcomes = outcomes
        self.calls: list[str] = []

    def __call__(self, variant_id: str, _: RegressionBatchRequest) -> VariantRunOutcome:
        """记录一次单Case执行请求并返回其预设独立Run证据。

        Args:
            variant_id: Suite当前编排的变体ID。
            _: 本测试不使用但保持真实Runner签名的批量请求。

        Returns:
            调用方预设的单Case结果。
        """

        self.calls.append(variant_id)
        return self.outcomes[variant_id]


def _global_job_target() -> GlobalJobTarget:
    """构造Snapshot绑定且脚本、URL都声明QA环境的全局Job目标。"""

    return GlobalJobTarget(
        variant_id="variant:regression:global-job",
        tool_id="job.order.reconcile",
        script_sha256="a" * 64,
        script_environment="qa",
        trigger_url="https://booking.qa.example.invalid/jobs/reconcile",
        url_environment="qa",
        affected_scope=["可能扫描QA全部待处理订单"],
        risk_notes=["不能按单个测试订单限定范围"],
    )


def _approval_scope(environment: str = "qa") -> GlobalJobApprovalScope:
    """构造绑定固定Suite、变体和Snapshot的全局Job确认范围。

    Args:
        environment: 本次预估和执行请求的环境。

    Returns:
        可传入全局Job门禁的严格Scope。
    """

    return GlobalJobApprovalScope(
        system_id="train-booking-core",
        suite_id="suite:train-booking-core:regression-v1",
        variant_id="variant:regression:global-job",
        snapshot_id="snapshot-001",
        environment=environment,
    )


def _impact_estimate() -> GlobalJobImpactEstimate:
    """构造由批准只读Oracle返回的全局Job订单分类计数。"""

    return GlobalJobImpactEstimate(
        operation_id="job.pending_orders.impact",
        estimated_process_count=12,
        test_order_count=2,
        non_test_order_count=10,
    )


def _write_suite(
    knowledge_root: Path,
    lifecycle: str = "ready",
    include_global_job: bool = False,
) -> None:
    """写入最小Suite及同目录覆盖矩阵，验证读取器按schema选择文档。

    Args:
        knowledge_root: 测试知识仓库根目录。
        lifecycle: Suite当前ready、blocked或stale生命周期。
        include_global_job: 是否追加全局Job变体和目标声明。

    Side Effects:
        创建 `systems/.../cases/suites` 下两个YAML文件。
    """

    suite_root = knowledge_root / "systems/train-booking-core/cases/suites"
    suite_root.mkdir(parents=True)
    variants = [*VARIANT_IDS]
    global_job_yaml = ""
    if include_global_job:
        variants = ["variant:regression:global-job"]
        global_job_yaml = f"""
global_jobs:
  - variant_id: variant:regression:global-job
    tool_id: job.order.reconcile
    script_sha256: {'a' * 64}
    script_environment: qa
    trigger_url: https://booking.qa.example.invalid/jobs/reconcile
    url_environment: qa
    affected_scope: [可能扫描QA全部待处理订单]
    risk_notes: [不能按单个测试订单限定范围]
"""
    blocked_yaml = "\nblocked_by: [qa_fixture_catalog, oracle_operation_catalog]" if lifecycle == "blocked" else ""
    variant_yaml = "\n".join(f"  - {variant_id}" for variant_id in variants)
    (suite_root / "regression.yaml").write_text(
        f"""schema_version: opentest.suite/v2alpha1
suite_id: suite:train-booking-core:regression-v1
system_id: train-booking-core
title: 核心回归
lifecycle: {lifecycle}
execution_policy:
  ordering: fixed_per_variant
  stop_on_failure: true
  qa_access_allowed_during_generation: false
  raw_sql_allowed: false
  raw_redis_command_allowed: false
  mq_evidence_policy: EFFECT_ONLY
variants:
{variant_yaml}{blocked_yaml}{global_job_yaml}
""",
        encoding="utf-8",
    )
    (suite_root / "coverage.yaml").write_text(
        "schema_version: opentest.coverage-matrix/v2alpha1\nsystem_id: train-booking-core\n",
        encoding="utf-8",
    )


def _batch_request(**updates: object) -> RegressionBatchRequest:
    """构造固定系统、Suite和Snapshot的批量请求并应用测试覆盖字段。

    Args:
        updates: 需要覆盖的严格请求字段。

    Returns:
        已通过Pydantic校验的批量请求。
    """

    payload: dict[str, object] = {
        "system_id": "train-booking-core",
        "suite_id": "suite:train-booking-core:regression-v1",
        "snapshot_id": "snapshot-001",
        "environment": "qa",
    }
    payload.update(updates)
    return RegressionBatchRequest.model_validate(payload)


def test_suite_reader_loads_suite_and_ignores_coverage_matrix(tmp_path: Path) -> None:
    """Suite读取器应读取现有v2alpha1形态，同时忽略同目录覆盖矩阵。"""

    knowledge_root = tmp_path / "knowledge"
    _write_suite(knowledge_root)
    suite = RegressionSuiteReader(knowledge_root).load(
        "train-booking-core",
        "suite:train-booking-core:regression-v1",
    )
    assert suite.title == "核心回归"
    assert suite.variants == VARIANT_IDS
    assert suite.execution_policy.stop_on_failure is True


def test_blocked_suite_preserves_every_variant_without_calling_runner(tmp_path: Path) -> None:
    """整体BLOCKED Suite应逐变体保留原因且绝不能触发单Case Runner。"""

    knowledge_root = tmp_path / "knowledge"
    _write_suite(knowledge_root, lifecycle="blocked")
    runner = RecordingRunner({})
    orchestrator = RegressionBatchOrchestrator(
        RegressionSuiteReader(knowledge_root),
        runner,
        GlobalJobApprovalGate(),
    )

    batch = orchestrator.run(_batch_request())
    assert batch.status == RegressionRunStatus.BLOCKED
    assert batch.blocked_count == len(VARIANT_IDS)
    assert runner.calls == []
    assert all(outcome.blocked_by == ["qa_fixture_catalog", "oracle_operation_catalog"] for outcome in batch.variant_outcomes)


def test_batch_keeps_independent_runs_blocked_results_and_resource_coverage(tmp_path: Path) -> None:
    """批量编排应保留独立run_id、BLOCKED结果、失败停止和业务资源证据等级。"""

    knowledge_root = tmp_path / "knowledge"
    _write_suite(knowledge_root)
    outcomes = {
        VARIANT_IDS[0]: VariantRunOutcome(
            variant_id=VARIANT_IDS[0],
            status=RegressionRunStatus.PASSED,
            run_id="run-normal-001",
            resource_evidence=[
                VariantResourceEvidence(
                    resource_id="resource:orders",
                    level=ResourceEvidenceLevel.DIRECT,
                    step_ids=["observe-order"],
                    assertion_digest="a" * 64,
                )
            ],
        ),
        VARIANT_IDS[1]: VariantRunOutcome(
            variant_id=VARIANT_IDS[1],
            status=RegressionRunStatus.BLOCKED,
            blocked_by=["oracle_operation_missing"],
            resource_evidence=[
                VariantResourceEvidence(resource_id="resource:orders", level=ResourceEvidenceLevel.BLOCKED)
            ],
        ),
        VARIANT_IDS[2]: VariantRunOutcome(
            variant_id=VARIANT_IDS[2],
            status=RegressionRunStatus.FAILED,
            run_id="run-failed-001",
            resource_evidence=[
                VariantResourceEvidence(
                    resource_id="resource:events",
                    level=ResourceEvidenceLevel.EFFECT_ONLY,
                    step_ids=["observe-event-effect"],
                    assertion_digest="b" * 64,
                )
            ],
        ),
    }
    runner = RecordingRunner(outcomes)
    orchestrator = RegressionBatchOrchestrator(
        RegressionSuiteReader(knowledge_root),
        runner,
        GlobalJobApprovalGate(),
    )

    batch = orchestrator.run(_batch_request())
    assert batch.status == RegressionRunStatus.FAILED
    assert (batch.passed_count, batch.failed_count, batch.blocked_count, batch.skipped_count) == (1, 1, 1, 1)
    assert runner.calls == VARIANT_IDS[:3]
    assert batch.variant_outcomes[-1].status == RegressionRunStatus.SKIPPED
    order_coverage = next(item for item in batch.resource_coverage if item.resource_id == "resource:orders")
    assert order_coverage.direct_variant_ids == [VARIANT_IDS[0]]
    assert order_coverage.blocked_variant_ids == [VARIANT_IDS[1]]
    assert not hasattr(order_coverage, "connected_variant_ids")


def test_global_job_preview_is_read_only_five_minutes_and_token_is_single_use() -> None:
    """全局Job预估不访问QA，Token应绑定目标、五分钟有效且只能成功消费一次。"""

    clock = MutableClock()
    gate = GlobalJobApprovalGate(clock, FixedTokenFactory())
    scope = _approval_scope()
    target = _global_job_target()
    preview = gate.preview(scope, target, _impact_estimate())
    assert preview.read_only is True
    assert preview.expires_at - preview.issued_at == timedelta(minutes=5)
    assert preview.affected_scope == target.affected_scope
    assert preview.estimated_process_count == 12
    assert preview.test_order_count == 2
    assert preview.non_test_order_count == 10

    without_allow = GlobalJobAuthorizationRequest(
        scope=scope,
        allow_global_job=False,
        confirmation_token=preview.confirmation_token,
    )
    with pytest.raises(KnowledgeValidationError, match="allow_global_job=true"):
        gate.authorize(without_allow, target)

    confirmed = without_allow.model_copy(update={"allow_global_job": True})
    gate.authorize(confirmed, target)
    with pytest.raises(KnowledgeValidationError, match="invalid or already used"):
        gate.authorize(confirmed, target)


def test_global_job_impact_estimate_requires_complete_order_partition() -> None:
    """影响预估总数必须等于测试订单与非本轮订单之和。"""

    with pytest.raises(ValidationError, match="partitions"):
        GlobalJobImpactEstimate(
            operation_id="job.pending_orders.impact",
            estimated_process_count=12,
            test_order_count=2,
            non_test_order_count=9,
        )


def test_global_job_gate_rejects_expiry_non_qa_and_script_url_drift() -> None:
    """全局Job门禁应在Runner前拒绝过期Token、非QA和预估后的脚本或URL变化。"""

    clock = MutableClock()
    gate = GlobalJobApprovalGate(clock, FixedTokenFactory())
    target = _global_job_target()
    preview = gate.preview(_approval_scope(), target, _impact_estimate())
    clock.advance(301)
    expired_request = GlobalJobAuthorizationRequest(
        scope=_approval_scope(),
        allow_global_job=True,
        confirmation_token=preview.confirmation_token,
    )
    with pytest.raises(KnowledgeValidationError, match="expired"):
        gate.authorize(expired_request, target)

    # 非QA范围和伪造URL环境在进入门禁前即由严格领域模型拒绝。
    with pytest.raises(ValidationError, match="Input should be 'qa'"):
        _approval_scope("prod")
    wrong_environment_payload = {**target.model_dump(mode="python"), "url_environment": "prod"}
    with pytest.raises(ValidationError, match="environments must match"):
        GlobalJobTarget.model_validate(wrong_environment_payload)

    current_preview = gate.preview(_approval_scope(), target, _impact_estimate())
    drifted_target = target.model_copy(
        update={
            "script_sha256": "b" * 64,
            "trigger_url": "https://other.qa.example.invalid/jobs/reconcile",
        }
    )
    drift_request = GlobalJobAuthorizationRequest(
        scope=_approval_scope(),
        allow_global_job=True,
        confirmation_token=current_preview.confirmation_token,
    )
    with pytest.raises(KnowledgeValidationError, match="script or URL changed"):
        gate.authorize(drift_request, drifted_target)


def test_orchestrator_consumes_global_job_token_before_runner(tmp_path: Path) -> None:
    """Suite中的全局Job只有显式allow和匹配Token齐全时才会进入单Case Runner。"""

    knowledge_root = tmp_path / "knowledge"
    _write_suite(knowledge_root, include_global_job=True)
    reader = RegressionSuiteReader(knowledge_root)
    suite = reader.load("train-booking-core", "suite:train-booking-core:regression-v1")
    target = suite.global_jobs[0]
    clock = MutableClock()
    gate = GlobalJobApprovalGate(clock, FixedTokenFactory())
    preview = gate.preview(_approval_scope(), target, _impact_estimate())
    runner = RecordingRunner(
        {
            target.variant_id: VariantRunOutcome(
                variant_id=target.variant_id,
                status=RegressionRunStatus.PASSED,
                run_id="run-global-job-001",
            )
        }
    )
    orchestrator = RegressionBatchOrchestrator(reader, runner, gate)
    request = _batch_request(
        allow_global_job=True,
        global_job_confirmation_tokens={target.variant_id: preview.confirmation_token},
    )

    batch = orchestrator.run(request)
    assert batch.status == RegressionRunStatus.PASSED
    assert runner.calls == [target.variant_id]
    with pytest.raises(KnowledgeValidationError, match="invalid or already used"):
        orchestrator.run(request)
    assert runner.calls == [target.variant_id]


def test_suite_rejects_global_job_for_unknown_variant() -> None:
    """Suite模型应拒绝无法形成变体引用闭包的全局Job声明。"""

    target = _global_job_target()
    with pytest.raises(ValueError, match="unknown variants"):
        RegressionSuite(
            schema_version="opentest.suite/v2alpha1",
            suite_id="suite:train-booking-core:regression-v1",
            system_id="train-booking-core",
            title="非法Suite",
            variants=["variant:regression:normal"],
            global_jobs=[target],
        )
