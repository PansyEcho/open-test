"""验证回归应用服务的Snapshot绑定、报告持久化与资源证据升级。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from opentest.application.regression import GlobalJobApprovalScope, RegressionBatchRequest, RegressionRunStatus
from opentest.application.regression_service import RegressionApplicationService
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.models import (
    OracleRequest,
    ResourceBusinessEvidence,
    RunRecord,
    ScenarioStep,
    ScenarioVariant,
    ScanManifest,
    Snapshot,
    SourceBaseline,
    StepResult,
    ToolDefinition,
    utc_now,
)


SYSTEM_ID = "train-booking-core"
SUITE_ID = "suite:train-booking-core:test"
VARIANT_ID = "variant:train-booking-core:test"
MYSQL_RESOURCE_ID = "resource:train-booking-core:mysql:database:bookingcoredatasource"
MQ_RESOURCE_ID = "resource:train-booking-core:mq:consumer:jobmessagelistener"


class FakeSnapshots:
    """为回归服务返回固定系统Snapshot。"""

    def get(self, snapshot_id: str) -> Snapshot:
        """按请求ID构造属于Booking.Core的最小Snapshot。

        Args:
            snapshot_id: 回归请求声明的Snapshot身份。

        Returns:
            归属固定系统的Snapshot。
        """

        return Snapshot(
            snapshot_id=snapshot_id,
            system_id=SYSTEM_ID,
            source_baseline=SourceBaseline(source_path="/tmp/booking-core"),
            scan_id="scan-test",
        )

    def create(self, system_id: str, _scan_id: str) -> Snapshot:
        """返回与请求系统一致的当前Snapshot，供Job防漂移测试使用。

        Args:
            system_id: 必须为固定Booking.Core系统。
            _scan_id: 测试不区分扫描版本。

        Returns:
            固定Snapshot身份。
        """

        return self.get("snapshot-regression-001")


class FakeExecution:
    """记录单Case执行并返回已持久化形态的通过结果。"""

    def __init__(self):
        """绑定固定Snapshot读取器并初始化调用记录。"""

        self.snapshots = FakeSnapshots()
        self.calls: list[str] = []

    def execute(self, request) -> RunRecord:
        """记录变体并返回包含两个通过Oracle步骤的独立Run。

        Args:
            request: 回归服务转换得到的ExecutionRequest。

        Returns:
            状态为passed且绑定原Snapshot的RunRecord。
        """

        self.calls.append(request.variant_id)
        now = utc_now()
        return RunRecord(
            run_id="run-regression-001",
            system_id=request.system_id,
            variant_id=request.variant_id,
            status="passed",
            snapshot_id=request.snapshot_id,
            step_results=[
                StepResult(step_id="oracle-mysql", status="passed", evidence=[{"attempt": 1}]),
                StepResult(step_id="oracle-mq-effect", status="passed", evidence=[{"attempt": 1}]),
            ],
            started_at=now,
            ended_at=now,
        )


class FakeCaseStore:
    """按稳定ID返回测试ScenarioVariant。"""

    def __init__(self, variant: ScenarioVariant | None):
        """保存可选变体，None用于模拟尚未编译。

        Args:
            variant: Suite引用的已编译变体或None。
        """

        self.variant = variant

    def get_variant(self, _system_id: str, variant_id: str) -> ScenarioVariant:
        """返回匹配变体，缺失时遵循GitCaseStore异常契约。

        Args:
            _system_id: 测试固定为Booking.Core系统。
            variant_id: Suite请求的稳定变体ID。

        Returns:
            预设ScenarioVariant。

        Raises:
            KnowledgeNotFoundError: 测试没有提供已编译变体或ID不匹配。
        """

        if self.variant is None or self.variant.variant_id != variant_id:
            raise KnowledgeNotFoundError(f"scenario variant not found: {variant_id}")
        return self.variant


class RecordingResources:
    """记录业务Case驱动的READY与EFFECT_ONLY状态升级。"""

    def __init__(self):
        """初始化资源证据调用列表。"""

        self.calls: list[tuple[str, ResourceBusinessEvidence, bool]] = []

    def mark_business_evidence(
        self,
        resource_id: str,
        evidence: ResourceBusinessEvidence,
        effect_only: bool,
    ) -> object:
        """记录资源证据，不访问源码或持久化状态。

        Args:
            resource_id: Oracle声明的逻辑资源ID。
            evidence: Snapshot、Case和Run组成的业务证据。
            effect_only: 是否仅观察到MQ消费后的业务效果。

        Returns:
            测试不使用的占位对象。
        """

        self.calls.append((resource_id, evidence, effect_only))
        return object()


def _write_suite(knowledge_root: Path, lifecycle: str = "ready") -> None:
    """写入只引用一个稳定变体的测试业务Suite。

    Args:
        knowledge_root: 隔离知识仓库根目录。
        lifecycle: Suite的ready或blocked状态。

    Side Effects:
        创建系统Suite YAML。
    """

    suite_path = knowledge_root / "systems/train-booking-core/cases/suites/test.yaml"
    suite_path.parent.mkdir(parents=True)
    blocked = "\nblocked_by: [qa_fixture_missing]" if lifecycle == "blocked" else ""
    suite_path.write_text(
        f"""schema_version: opentest.suite/v2alpha1
suite_id: {SUITE_ID}
system_id: {SYSTEM_ID}
title: 应用服务测试Suite
lifecycle: {lifecycle}
variants:
  - {VARIANT_ID}{blocked}
""",
        encoding="utf-8",
    )


def _variant() -> ScenarioVariant:
    """构造同时包含MySQL直接证据和MQ效果证据的可执行变体。"""

    return ScenarioVariant(
        variant_id=VARIANT_ID,
        scenario_id="scenario:train-booking-core:test",
        system_id=SYSTEM_ID,
        seed=1,
        inputs={},
        steps=[
            ScenarioStep(
                step_id="oracle-mysql",
                name="校验主库订单",
                action="oracle",
                oracle=OracleRequest(
                    oracle_id="oracle-mysql",
                    system_id=SYSTEM_ID,
                    kind="mysql",
                    resource_id=MYSQL_RESOURCE_ID,
                    operation_id="order.primary_detail",
                    assertions={"$.orderState": "ISSUE_SUCCESS"},
                ),
            ),
            ScenarioStep(
                step_id="oracle-mq-effect",
                name="校验MQ下游效果",
                action="oracle",
                oracle=OracleRequest(
                    oracle_id="oracle-mq-effect",
                    system_id=SYSTEM_ID,
                    kind="mq",
                    resource_id=MQ_RESOURCE_ID,
                    operation_id="mq.trace_match",
                    assertions={"$.effectObserved": True},
                ),
            ),
        ],
    )


def _request() -> RegressionBatchRequest:
    """构造固定Suite与Snapshot的QA批量请求。"""

    return RegressionBatchRequest(
        system_id=SYSTEM_ID,
        suite_id=SUITE_ID,
        snapshot_id="snapshot-regression-001",
        environment="qa",
    )


def test_ready_suite_runs_variant_persists_report_and_upgrades_resources(tmp_path: Path) -> None:
    """通过Case应保存批量报告，并分别发布MySQL直接与MQ效果证据。"""

    knowledge_root = tmp_path / "knowledge"
    _write_suite(knowledge_root)
    execution = FakeExecution()
    resources = RecordingResources()
    service = RegressionApplicationService(
        knowledge_root,
        FakeCaseStore(_variant()),
        execution,
        resources,
    )

    report = service.run(_request())
    loaded = service.list_reports(SYSTEM_ID, SUITE_ID)

    assert report.status == RegressionRunStatus.PASSED
    assert execution.calls == [VARIANT_ID]
    assert loaded == [report]
    assert {(resource_id, effect_only) for resource_id, _, effect_only in resources.calls} == {
        (MYSQL_RESOURCE_ID, False),
        (MQ_RESOURCE_ID, True),
    }
    assert all(evidence.snapshot_id == "snapshot-regression-001" for _, evidence, _ in resources.calls)


def test_ready_suite_keeps_uncompiled_custom_variant_blocked(tmp_path: Path) -> None:
    """Suite已ready但业务骨架未编译时应保留BLOCKED且不调用真实执行器。"""

    knowledge_root = tmp_path / "knowledge"
    _write_suite(knowledge_root)
    execution = FakeExecution()
    service = RegressionApplicationService(
        knowledge_root,
        FakeCaseStore(None),
        execution,
        RecordingResources(),
    )

    report = service.run(_request())

    assert report.status == RegressionRunStatus.BLOCKED
    assert report.blocked_count == 1
    assert report.variant_outcomes[0].blocked_by == ["scenario_variant_not_compiled"]
    assert execution.calls == []


def test_snapshot_job_target_reloads_script_digest_and_url(tmp_path: Path) -> None:
    """全局Job必须从Snapshot manifest重读脚本字节和URL并拒绝漂移。"""

    knowledge_root = tmp_path / "knowledge"
    script_root = tmp_path / "tools"
    script_root.mkdir()
    script_path = script_root / "timeout-job.sh"
    script_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script_digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
    trigger_url = "https://jobs.qa.example.invalid/TIME_OUT_CANCEL_JOB"
    suite_path = knowledge_root / "systems/train-booking-core/cases/suites/job.yaml"
    suite_path.parent.mkdir(parents=True)
    suite_path.write_text(
        f"""schema_version: opentest.suite/v2alpha1
suite_id: {SUITE_ID}
system_id: {SYSTEM_ID}
title: Job Snapshot绑定测试
variants: [{VARIANT_ID}]
global_jobs:
  - variant_id: {VARIANT_ID}
    tool_id: job.time_out_cancel_job
    script_sha256: {script_digest}
    script_environment: qa
    trigger_url: {trigger_url}
    url_environment: qa
    affected_scope: [isolated_test_orders]
""",
        encoding="utf-8",
    )
    execution = FakeExecution()
    manifest = ScanManifest(
        scan_id="scan-test",
        system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path="/tmp/booking-core"),
        tool_root=str(script_root),
        tools=[
            ToolDefinition(
                tool_id="job.time_out_cancel_job",
                system_id=SYSTEM_ID,
                display_name="超时撤单Job",
                script_path=str(script_path),
                metadata={"default_url": trigger_url},
            )
        ],
    )

    class BoundArtifacts:
        """返回绑定测试脚本的固定扫描manifest。"""

        def read(self, _system_id: str, _scan_id: str) -> ScanManifest:
            """返回当前测试manifest，不访问磁盘派生索引。"""

            return manifest

    execution.artifacts = BoundArtifacts()
    service = RegressionApplicationService(
        knowledge_root,
        FakeCaseStore(None),
        execution,
        RecordingResources(),
    )
    suite = service.suite_reader.load(SYSTEM_ID, SUITE_ID)
    scope = GlobalJobApprovalScope(
        system_id=SYSTEM_ID,
        suite_id=SUITE_ID,
        variant_id=VARIANT_ID,
        snapshot_id="snapshot-regression-001",
        environment="qa",
    )

    assert service._load_snapshot_job_target(suite, VARIANT_ID, scope) == suite.global_jobs[0]
    script_path.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="differs from suite"):
        service._load_snapshot_job_target(suite, VARIANT_ID, scope)
