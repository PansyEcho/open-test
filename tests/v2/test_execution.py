"""验证Snapshot、真实工具边界、类型化执行、Oracle和本地环境配置。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opentest.adapters.case_store import GitCaseStore
from opentest.adapters.dsf_executor import DsfExecutor
from opentest.adapters.environment_config import LocalEnvironmentLoader
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.oracles import MySqlOracleAdapter, OraclePoller, RedisOracleAdapter
from opentest.adapters.qa_worker import QaWorkerOracleAdapter
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.execution import ScenarioExecutionService
from opentest.application.execution_core import (
    AssertionEngine,
    ExecutionBindings,
    JsonOutputParser,
    ValueResolver,
)
from opentest.application.snapshots import SnapshotService
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    ExecutionRequest,
    LocalEnvironmentDefinition,
    OracleRequest,
    ScanManifest,
    ScenarioDefinition,
    ScenarioGenerationBatch,
    ScenarioStep,
    ScenarioVariant,
    SourceBaseline,
    SystemDefinition,
    ToolDefinition,
)


class SequenceOracle:
    """按顺序返回观察值，用于验证轮询在满足断言时终止。"""

    def __init__(self, values: list[Any]):
        """保存每次read应返回的值序列。"""

        self.values = list(values)

    def read(
        self,
        request: OracleRequest,
        environment: LocalEnvironmentDefinition,
        timeout_seconds: float = 30,
    ) -> Any:
        """在调用方传入的剩余deadline内返回下一个测试观察值。"""

        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class FakeClock:
    """由测试显式推进的单调时钟，避免Oracle测试真实等待。"""

    def __init__(self):
        """从零初始化可控时间。"""

        self.value = 0.0

    def now(self) -> float:
        """返回当前测试时间。"""

        return self.value

    def sleep(self, seconds: float) -> None:
        """用增加数值模拟等待而不阻塞测试进程。"""

        self.value += seconds


def _execution_fixture(tmp_path: Path) -> tuple[ScenarioExecutionService, ScenarioVariant, SnapshotService]:
    """创建真实生成脚本、Case、环境配置和Snapshot执行夹具。"""

    source = tmp_path / "source"
    source.mkdir()
    baseline = SourceBaseline(source_path=str(source), commit="abc123", dirty=False)
    knowledge_root = tmp_path / "knowledge"
    store = GitKnowledgeStore(knowledge_root)
    store.register_system(
        SystemDefinition(
            system_id="train-booking-core",
            name="火车票预订",
            source_path=str(source),
            baseline=baseline,
        )
    )
    artifacts = SourceScanArtifactStore(knowledge_root)
    scan_id, tool_root = artifacts.allocate("train-booking-core", baseline)
    script = tool_root / "facade" / "trade" / "create-order-raw.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"success\":true,\"response\":{\"orderSerialNo\":\"QA-ORDER-1\"}}'\n",
        encoding="utf-8",
    )
    tool = ToolDefinition(
        tool_id="facade.trade.create_order",
        system_id="train-booking-core",
        display_name="创建订单",
        script_path=str(script),
        source_id="TradeFacade#createOrder",
        metadata={"raw_tool_id": "facade_raw.trade.createOrder", "status": "ready"},
    )
    manifest = ScanManifest(
        scan_id=scan_id,
        system_id="train-booking-core",
        baseline=baseline,
        tools=[tool],
        tool_root=str(tool_root),
    )
    artifacts.write_manifest(manifest)
    artifacts.publish_latest("train-booking-core", scan_id)
    scenario = ScenarioDefinition(
        scenario_id="scenario:create-order:test",
        system_id="train-booking-core",
        entry_node_id="facade:TradeFacade#createOrder",
        title="执行测试",
        coverage_target_ids=[],
        steps=[],
    )
    variant = ScenarioVariant(
        variant_id="variant:create-order:test",
        scenario_id=scenario.scenario_id,
        system_id="train-booking-core",
        seed=0,
        inputs={"request": {"trainNo": "${qa.train_no}"}},
        steps=[
            ScenarioStep(
                step_id="create-order",
                name="调用真实生成工具",
                tool_id=tool.tool_id,
                params={"request": "${inputs.request}"},
            ),
            ScenarioStep(
                step_id="assert-create-order",
                name="校验创建成功",
                action="assert",
                assertions={"$.success": True, "$.response.orderSerialNo": {"op": "not_null"}},
            ),
        ],
        cleanup_steps=[
            ScenarioStep(
                step_id="capture-cleanup-key",
                name="记录清理订单号",
                action="cleanup",
                params={"order_serial_no": "${steps.create-order.output.response.orderSerialNo}"},
            )
        ],
    )
    case_store = GitCaseStore(store)
    case_store.write_batch(
        ScenarioGenerationBatch(
            batch_id="batch:test",
            system_id="train-booking-core",
            entry_node_id="facade:TradeFacade#createOrder",
            coverage_targets=[],
            scenarios=[scenario],
            variants=[variant],
        )
    )
    environment_root = knowledge_root / ".opentest" / "environments"
    environment_path = environment_root / "train-booking-core" / "qa.yaml"
    environment_path.parent.mkdir(parents=True)
    environment_path.write_text(
        "system_id: train-booking-core\nenvironment: qa\nvalues:\n  train_no: QA-G100\n  tool_environment: {}\nconnections: {}\n",
        encoding="utf-8",
    )
    snapshots = SnapshotService(store, artifacts)
    service = ScenarioExecutionService(
        store,
        case_store,
        artifacts,
        snapshots,
        LocalEnvironmentLoader(environment_root),
    )
    return service, variant, snapshots


def test_value_resolver_preserves_types_and_rejects_missing_paths() -> None:
    """完整占位符应保留对象类型，缺失引用不得静默替换为空字符串。"""

    bindings = ExecutionBindings(
        inputs={"request": {"count": 2}},
        qa={"prefix": "QA"},
        steps={"create-order": {"output": {"id": 42}}},
    )
    resolver = ValueResolver()

    assert resolver.resolve("${inputs.request}", bindings) == {"count": 2}
    assert resolver.resolve("${steps.create-order.output.id}", bindings) == 42
    assert resolver.resolve("${qa.prefix}-ORDER", bindings) == "QA-ORDER"
    with pytest.raises(KnowledgeValidationError, match="missing"):
        resolver.resolve("${steps.create-order.output.unknown}", bindings)


def test_json_parser_and_assertion_engine_return_structured_differences() -> None:
    """工具诊断文本后的JSON应可解析，失败断言应包含精确路径差异。"""

    actual = JsonOutputParser().parse('diagnostic\n{"success": true, "count": 2, "response": {"id": 42}}')
    differences = AssertionEngine().compare(actual, {"$.success": True, "$.count": {"op": "gte", "value": 3}})

    assert actual["success"] is True
    assert actual["response"] == {"id": 42}
    assert AssertionEngine().compare([{"status": "READY"}], {"$[0].status": "READY"}) == []
    assert differences == [
        {
            "path": "$.count",
            "operator": "gte",
            "expected": 3,
            "actual": 2,
            "error": "",
        }
    ]


def test_rows_unordered_match_handles_multiple_passengers_and_duplicate_rows() -> None:
    """逐乘客Item应忽略SQL行序，同时对重复业务行执行一对一消费。"""

    engine = AssertionEngine()
    actual_rows = [
        {
            "itemId": "ITEM-C2",
            "orderSerialNo": "HT-1",
            "transactionSerialNo": "TX-1",
            "passengerType": 2,
            "seatClass": "O",
            "merchantTicketPrice": "100.00",
            "deleted": 0,
            "environment": "qa",
        },
        {
            "itemId": "ITEM-A1",
            "orderSerialNo": "HT-1",
            "transactionSerialNo": "TX-1",
            "passengerType": 1,
            "seatClass": "O",
            "merchantTicketPrice": "200.00",
            "deleted": 0,
            "environment": "qa",
        },
        {
            "itemId": "ITEM-C1",
            "orderSerialNo": "HT-1",
            "transactionSerialNo": "TX-1",
            "passengerType": 2,
            "seatClass": "O",
            "merchantTicketPrice": "100.00",
            "deleted": 0,
            "environment": "qa",
        },
    ]
    match_contract = {
        "expected_rows": [
            {"passengerType": 2, "seatClass": "O", "merchantTicketPrice": "100.00"},
            {"passengerType": 1, "seatClass": "O", "merchantTicketPrice": "200.00"},
            {"passengerType": 2, "seatClass": "O", "merchantTicketPrice": "100.00"},
        ],
        "common_fields": {
            "orderSerialNo": "HT-1",
            "transactionSerialNo": "TX-1",
            "deleted": 0,
            "environment": "qa",
        },
        "non_null_fields": ["itemId"],
    }

    # 两条相同儿童期望必须各消费一条实际行，且不依赖数据库返回顺序。
    assert engine.compare(actual_rows, {"$": {"op": "rows_unordered_match", "value": match_contract}}) == []

    # 任一逐乘客字段不符都应产生可定位的结构化差异，不能只凭行数通过。
    mismatched_contract = {
        **match_contract,
        "expected_rows": [
            *match_contract["expected_rows"][:-1],
            {"passengerType": 2, "seatClass": "O", "merchantTicketPrice": "101.00"},
        ],
    }
    differences = engine.compare(
        actual_rows,
        {"$": {"op": "rows_unordered_match", "value": mismatched_contract}},
    )
    assert differences[0]["operator"] == "rows_unordered_match"

    # 宽泛期望不能贪心占用具体期望的唯一候选，存在一对一映射就应通过。
    overlapping_actual = [
        {"itemId": "ITEM-O", "passengerType": 1, "seatClass": "O"},
        {"itemId": "ITEM-F", "passengerType": 1, "seatClass": "F"},
    ]
    overlapping_contract = {
        "expected_rows": [
            {"passengerType": 1},
            {"passengerType": 1, "seatClass": "O"},
        ],
        "common_fields": {},
        "non_null_fields": ["itemId"],
    }
    assert engine.compare(
        overlapping_actual,
        {"$": {"op": "rows_unordered_match", "value": overlapping_contract}},
    ) == []


def test_scenario_step_rejects_action_fields_that_would_be_ignored() -> None:
    """断言、Oracle和工具步骤不得夹带执行器不会消费的互斥字段。"""

    with pytest.raises(ValueError, match="assert action requires only"):
        ScenarioStep(
            step_id="assert-unsafe",
            name="夹带工具的断言",
            action="assert",
            tool_id="facade.trade.create_order",
            assertions={"$.success": True},
        )
    with pytest.raises(ValueError, match="assert action requires only"):
        ScenarioStep(
            step_id="assert-params",
            name="夹带参数的断言",
            action="assert",
            params={"request": {}},
            assertions={"$.success": True},
        )
    with pytest.raises(ValueError, match="oracle action requires only"):
        ScenarioStep(
            step_id="oracle-unsafe",
            name="夹带参数的Oracle",
            action="oracle",
            params={"ignored": True},
            oracle=OracleRequest(
                oracle_id="oracle:unsafe",
                system_id="train-booking-core",
                kind="mysql",
                resource_id="resource:train-booking-core:mysql:database:bookingcoredatasource",
                operation_id="order.primary_detail",
                assertions={"rowCount": 1},
            ),
        )
    with pytest.raises(ValueError, match="cannot define assertions"):
        ScenarioStep(
            step_id="execute-unsafe",
            name="夹带断言的执行步骤",
            action="execute",
            tool_id="facade.trade.create_order",
            assertions={"$.success": True},
        )
    with pytest.raises(ValueError, match="requires a logical tool ID"):
        ScenarioStep(
            step_id="execute-empty",
            name="没有真实工具的执行步骤",
            action="execute",
        )


def test_request_payload_merges_fixture_copy_and_rejects_ambiguous_wrappers(tmp_path: Path) -> None:
    """出票请求应以运行期订单键覆盖Fixture副本，并拒绝混合请求封装。"""

    service, _, _ = _execution_fixture(tmp_path)
    fixture_request = {"serialId": "FIXTURE", "nested": {"keep": True}}
    resolved_params = {
        "request_base": fixture_request,
        "request_overrides": {"serialId": "HT-REAL", "transactionSerialNo": "TX-REAL"},
    }

    merged = service._request_payload("execute-issue", resolved_params)

    # 合成结果允许顶层业务键覆盖，但不得污染可供其他Case复用的本地Fixture。
    assert merged == {
        "serialId": "HT-REAL",
        "transactionSerialNo": "TX-REAL",
        "nested": {"keep": True},
    }
    assert fixture_request == {"serialId": "FIXTURE", "nested": {"keep": True}}
    assert merged is not fixture_request

    # 同时出现直接request或额外字段会产生歧义，必须在调用真实DSF前拒绝。
    with pytest.raises(KnowledgeValidationError, match="request wrapper is invalid"):
        service._request_payload(
            "execute-issue",
            {**resolved_params, "request": {"serialId": "AMBIGUOUS"}},
        )
    with pytest.raises(KnowledgeValidationError, match="merge values must be objects"):
        service._request_payload(
            "execute-issue",
            {"request_base": "not-an-object", "request_overrides": {}},
        )


def test_mq_oracle_uses_fixed_java_worker_adapter(tmp_path: Path) -> None:
    """MQ效果声明必须走固定Worker操作，不能退回要求Broker连接的旧适配器。"""

    service, _, _ = _execution_fixture(tmp_path)
    manifest = service.artifacts.read("train-booking-core")
    poller = service._build_oracle_poller(manifest, DsfExecutor())

    # MQ与数据库、Redis共用无密钥Worker边界；实际操作仍由catalog限制为mq.trace_match。
    assert isinstance(poller.adapters["mq"], QaWorkerOracleAdapter)
    assert poller.adapters["mq"] is poller.adapters["mysql"]
    assert poller.adapters["mq"] is poller.adapters["redis"]


def test_executable_boundaries_reject_empty_assertions_and_non_qa() -> None:
    """执行模型、断言器和Oracle轮询器必须共同拒绝假绿色与非QA范围。"""

    with pytest.raises(KnowledgeValidationError, match="must not be empty"):
        AssertionEngine().compare({"status": "READY"}, {})
    with pytest.raises(ValueError, match="Input should be 'qa'"):
        ExecutionRequest(
            system_id="train-booking-core",
            variant_id="variant:unsafe",
            snapshot_id="snapshot-unsafe",
            environment="prod",
        )
    with pytest.raises(ValueError, match="requires business assertions"):
        ScenarioVariant(
            variant_id="variant:empty-oracle",
            scenario_id="scenario:empty-oracle",
            system_id="train-booking-core",
            seed=1,
            inputs={},
            steps=[
                ScenarioStep(
                    step_id="observe-empty",
                    name="空Oracle",
                    action="oracle",
                    oracle=OracleRequest(
                        oracle_id="oracle:empty",
                        system_id="train-booking-core",
                        kind="dsf",
                        operation_id="facade.order.query",
                    ),
                )
            ],
        )

    poller = OraclePoller({"dsf": SequenceOracle([{"status": "READY"}])})
    request = OracleRequest(
        oracle_id="oracle:empty",
        system_id="train-booking-core",
        kind="dsf",
        operation_id="facade.order.query",
    )
    environment = LocalEnvironmentDefinition(system_id="train-booking-core", environment="qa")
    with pytest.raises(KnowledgeValidationError, match="must not be empty"):
        poller.poll(request, environment)


def test_dsf_executor_rejects_tool_outside_scan_root(tmp_path: Path) -> None:
    """manifest中的脚本越过绑定tool_root时必须在启动前失败。"""

    tool_root = tmp_path / "tools"
    tool_root.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    tool = ToolDefinition(
        tool_id="facade.trade.create_order",
        system_id="train-booking-core",
        display_name="创建订单",
        script_path=str(outside),
        metadata={"status": "ready"},
    )

    with pytest.raises(KnowledgeValidationError, match="escapes"):
        DsfExecutor().execute(tool, tool_root, {}, 10)


def test_snapshot_is_stable_and_changes_when_case_changes(tmp_path: Path) -> None:
    """同一资产应复用Snapshot，Case文件变化后必须生成不同ID。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    first = snapshots.create("train-booking-core")
    second = snapshots.create("train-booking-core")
    assert first.snapshot_id == second.snapshot_id

    variant_root = service.case_store.knowledge_store.system_root("train-booking-core") / "cases" / "variants"
    variant_path = next(variant_root.glob("*.yaml"))
    variant_path.write_text(variant_path.read_text(encoding="utf-8") + "\n# manual change\n", encoding="utf-8")
    changed = snapshots.create("train-booking-core")
    assert changed.snapshot_id != first.snapshot_id


def test_snapshot_changes_when_worker_or_oracle_catalog_changes(tmp_path: Path) -> None:
    """Worker Jar或固定Oracle目录变化后必须生成新的内容寻址Snapshot。

    Args:
        tmp_path: Pytest提供的隔离临时目录。

    Side Effects:
        写入测试Worker Jar和Oracle目录，以验证两类资产均参与版本身份。
    """

    _, _, snapshots = _execution_fixture(tmp_path)
    initial = snapshots.create("train-booking-core")

    # Worker虽可在纯DSF执行时缺失，但一旦出现就必须进入Snapshot身份。
    worker_path = tmp_path / "workers/qa-oracle-worker/target/opentest-qa-oracle-worker.jar"
    worker_path.parent.mkdir(parents=True)
    worker_path.write_bytes(b"worker-v1")
    worker_bound = snapshots.create("train-booking-core")
    assert worker_bound.snapshot_id != initial.snapshot_id
    assert worker_bound.worker_digest

    # 固定操作目录决定可执行查询白名单，其任何变化都不能复用旧Snapshot。
    catalog_path = snapshots.store.system_root("train-booking-core") / "oracles/catalog.yaml"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text("schema_version: 1\noperations: []\n", encoding="utf-8")
    catalog_bound = snapshots.create("train-booking-core")
    assert catalog_bound.snapshot_id != worker_bound.snapshot_id
    assert catalog_bound.oracle_catalog_digest


def test_snapshot_normalizes_legacy_mq_resource_id_without_rewriting_case(tmp_path: Path) -> None:
    """Snapshot应绑定MQ集群ID，同时保留人工Case中的旧Consumer兼容字段。

    Args:
        tmp_path: Pytest提供的隔离知识、扫描和Case目录。
    """

    service, _, snapshots = _execution_fixture(tmp_path)
    case_root = snapshots.store.system_root("train-booking-core") / "cases/custom"
    case_root.mkdir(parents=True)
    case_path = case_root / "legacy-mq.yaml"
    legacy_resource_id = "resource:train-booking-core:mq:consumer:jobmessagelistener"
    case_path.write_text(
        "steps:\n"
        "- action: oracle\n"
        "  oracle:\n"
        f"    resource_id: {legacy_resource_id}\n",
        encoding="utf-8",
    )
    snapshots.resource_id_resolver = lambda _system_id, resource_id: (
        "resource:train-booking-core:mq:cluster:mq-namesrvaddress"
        if resource_id == legacy_resource_id
        else resource_id
    )

    snapshot = snapshots.create("train-booking-core")

    assert snapshot.resource_ids == ["resource:train-booking-core:mq:cluster:mq-namesrvaddress"]
    assert legacy_resource_id in case_path.read_text(encoding="utf-8")


def test_snapshot_rejects_tampered_content_addressed_file(tmp_path: Path) -> None:
    """手工修改Snapshot摘要字段后读取必须因内容寻址身份不匹配而失败。"""

    _, _, snapshots = _execution_fixture(tmp_path)
    snapshot = snapshots.create("train-booking-core")
    path = snapshots.snapshot_root / f"{snapshot.snapshot_id}.json"
    tampered = snapshot.model_copy(update={"tool_digest": "tampered"})
    path.write_text(tampered.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(KnowledgeValidationError, match="content digest"):
        snapshots.get(snapshot.snapshot_id)


def test_snapshot_ignores_stale_variant_from_previous_scan(tmp_path: Path) -> None:
    """历史stale变体可保留旧scan证据，但不得阻塞当前活跃Case创建Snapshot。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    stale = variant.model_copy(
        update={
            "variant_id": "variant:create-order:stale-history",
            "lifecycle": "stale",
            "replay": {"source_scan_id": "scan-from-previous-baseline"},
        }
    )
    service.case_store.write_variant(stale)

    snapshot = snapshots.create("train-booking-core")

    assert snapshot.scan_id == service.artifacts.read("train-booking-core").scan_id


def test_execution_runs_real_generated_tool_assertion_and_cleanup(tmp_path: Path) -> None:
    """执行服务应调用真实脚本、校验JSON并在finally保存清理键证据。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    snapshot = snapshots.create("train-booking-core")
    record = service.execute(
        ExecutionRequest(
            system_id="train-booking-core",
            variant_id=variant.variant_id,
            snapshot_id=snapshot.snapshot_id,
        )
    )

    assert record.status == "passed"
    assert [item.status for item in record.step_results] == ["passed", "passed", "passed"]
    assert record.step_results[0].command[-2] == "--request-file"
    assert record.step_results[0].command[-1] == "<redacted>"
    assert record.step_results[-1].evidence[0]["cleanup"]["order_serial_no"] == "QA-ORDER-1"
    assert service.get_run(record.run_id) == record


def test_negative_execution_passes_without_unresolvable_order_cleanup(tmp_path: Path) -> None:
    """业务拒绝没有订单号时应只校验失败响应，不执行成功订单清理占位符。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    manifest = service.artifacts.read("train-booking-core")
    Path(manifest.tools[0].script_path).write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"success\":true,\"response\":{\"success\":false,\"code\":101413}}'\n",
        encoding="utf-8",
    )
    negative = variant.model_copy(
        update={
            "steps": [
                variant.steps[0],
                ScenarioStep(
                    step_id="assert-no-adult",
                    name="校验无成人业务拒绝",
                    action="assert",
                    assertions={"$.success": True, "$.response.success": False, "$.response.code": 101413},
                ),
            ],
            "cleanup_steps": [],
            "expected_outcome": "no_adult",
        }
    )
    service.case_store.write_variant(negative)
    snapshot = snapshots.create("train-booking-core")

    record = service.execute(
        ExecutionRequest(
            system_id="train-booking-core",
            variant_id=variant.variant_id,
            snapshot_id=snapshot.snapshot_id,
        )
    )

    assert record.status == "passed"
    assert [item.step_id for item in record.step_results] == ["create-order", "assert-no-adult"]


def test_execution_rejects_missing_validated_data_precondition_before_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """港币报价条件没有QA证据时必须在真实工具调用前拒绝执行。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    conditioned = variant.model_copy(
        update={
            "replay": {
                "data_preconditions": {
                    "hk_quote_status": {"expected": "valid", "evidence_required": True}
                }
            }
        }
    )
    service.case_store.write_variant(conditioned)
    snapshot = snapshots.create("train-booking-core")

    def unexpected_execute(
        executor: DsfExecutor,
        tool: ToolDefinition,
        tool_root: Path,
        params: dict[str, Any],
        timeout_seconds: int,
    ) -> None:
        """无视执行参数并在工具被调用时暴露前置校验顺序错误。

        Args:
            executor: 被monkeypatch的DSF执行器实例。
            tool: 本不应到达的真实工具定义。
            tool_root: Snapshot绑定的工具根目录。
            params: 已解析但本不应发送的请求参数。
            timeout_seconds: 调用方给出的工具超时。
        """

        raise AssertionError("DSF tool must not run before data preconditions pass")

    monkeypatch.setattr(DsfExecutor, "execute", unexpected_execute)
    with pytest.raises(KnowledgeValidationError, match="validated data precondition is missing"):
        service.execute(
            ExecutionRequest(
                system_id="train-booking-core",
                variant_id=variant.variant_id,
                snapshot_id=snapshot.snapshot_id,
            )
        )


def test_execution_records_matching_validated_data_precondition(tmp_path: Path) -> None:
    """值和证据完整的QA前置条件应允许执行并进入RunRecord证据。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    conditioned = variant.model_copy(
        update={
            "replay": {
                "data_preconditions": {
                    "hk_quote_status": {"expected": "valid", "evidence_required": True}
                }
            }
        }
    )
    service.case_store.write_variant(conditioned)
    environment_path = (
        service.environment_loader.environment_root / "train-booking-core" / "qa.yaml"
    )
    environment_path.write_text(
        "system_id: train-booking-core\n"
        "environment: qa\n"
        "values:\n"
        "  train_no: QA-G100\n"
        "  tool_environment: {}\n"
        "  validated_preconditions:\n"
        "    hk_quote_status:\n"
        "      value: valid\n"
        "      evidence: QA-MTR-QUOTE-42\n"
        "      observed_at: '2026-08-11T10:00:00Z'\n"
        "connections: {}\n",
        encoding="utf-8",
    )
    snapshot = snapshots.create("train-booking-core")

    record = service.execute(
        ExecutionRequest(
            system_id="train-booking-core",
            variant_id=variant.variant_id,
            snapshot_id=snapshot.snapshot_id,
        )
    )

    assert record.status == "passed"
    precondition = record.step_results[0]
    assert precondition.step_id == "validate-data-preconditions"
    assert precondition.evidence[0]["condition"] == "hk_quote_status"
    assert precondition.evidence[0]["evidence"] == "QA-MTR-QUOTE-42"


def test_oracle_poller_stops_when_expected_state_arrives() -> None:
    """异步Oracle应保留中间观察，并在deadline前命中状态后停止。"""

    clock = FakeClock()
    poller = OraclePoller(
        {"dsf": SequenceOracle([{"status": "CREATED"}, {"status": "TICKETING"}])},
        clock=clock.now,
        sleeper=clock.sleep,
    )
    environment = LocalEnvironmentDefinition(system_id="train-booking-core", environment="qa")
    request = OracleRequest(
        oracle_id="oracle:order-state",
        system_id="train-booking-core",
        kind="dsf",
        operation="facade.order.query",
        assertions={"$.status": "TICKETING"},
        timeout_seconds=5,
        poll_interval_seconds=1,
    )
    result = poller.poll(request, environment)

    assert result.status == "passed"
    assert len(result.observations) == 2
    assert result.observations[0].assertion_diffs
    assert result.observations[1].assertion_diffs == []


def test_oracle_poller_deadline_preserves_last_observation() -> None:
    """截止时间到达仍不满足时应失败并保留最后观察值。"""

    clock = FakeClock()
    poller = OraclePoller(
        {"mq": SequenceOracle([{"found": False}])},
        clock=clock.now,
        sleeper=clock.sleep,
    )
    environment = LocalEnvironmentDefinition(system_id="train-booking-core", environment="qa")
    request = OracleRequest(
        oracle_id="oracle:mq-event",
        system_id="train-booking-core",
        kind="mq",
        operation="order-created",
        assertions={"$.found": True},
        timeout_seconds=2,
        poll_interval_seconds=1,
    )
    result = poller.poll(request, environment)

    assert result.status == "failed"
    assert len(result.observations) == 3
    assert result.observations[-1].value == {"found": False}


def test_oracle_request_rejects_subsecond_poll_interval() -> None:
    """Oracle轮询间隔不得小于证据数量上限所依赖的半秒边界。"""

    with pytest.raises(ValueError):
        OracleRequest(
            oracle_id="oracle:too-fast",
            system_id="train-booking-core",
            kind="mq",
            operation="order-created",
            poll_interval_seconds=0.1,
        )


def test_redis_oracle_rejects_write_commands() -> None:
    """Redis Oracle不得允许SET等会修改QA状态的命令。"""

    environment = LocalEnvironmentDefinition(
        system_id="train-booking-core",
        environment="qa",
        connections={"cache": {"kind": "redis", "host": "localhost"}},
    )
    request = OracleRequest(
        oracle_id="oracle:redis-write",
        system_id="train-booking-core",
        kind="redis",
        connection="cache",
        operation="SET",
    )
    with pytest.raises(KnowledgeValidationError, match="read-only"):
        RedisOracleAdapter(client_factory=lambda **_: object()).read(request, environment)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders FOR UPDATE",
        "SELECT SLEEP(30)",
        "SELECT * FROM orders INTO OUTFILE '/tmp/orders'",
        "SELECT 1; SELECT 2",
    ],
)
def test_mysql_oracle_rejects_side_effectful_or_multiple_statements(sql: str) -> None:
    """MySQL Oracle必须在建立连接前拒绝加锁、休眠、写文件和多语句查询。"""

    environment = LocalEnvironmentDefinition(
        system_id="train-booking-core",
        environment="qa",
        connections={"booking": {"kind": "mysql", "host": "localhost"}},
    )
    request = OracleRequest(
        oracle_id="oracle:mysql-safety",
        system_id="train-booking-core",
        kind="mysql",
        connection="booking",
        operation="query",
        params={"sql": sql},
    )

    with pytest.raises(KnowledgeValidationError, match="side-effect-free"):
        MySqlOracleAdapter(connect_factory=lambda **_: object()).read(request, environment)


def test_snapshot_changes_when_bound_script_changes_and_old_snapshot_is_rejected(tmp_path: Path) -> None:
    """修改manifest引用脚本后必须产生新Snapshot，并拒绝旧版本执行新脚本。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    original = snapshots.create("train-booking-core")
    manifest = service.artifacts.read("train-booking-core", original.scan_id)
    script = Path(manifest.tools[0].script_path)
    script.write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"success\":true,\"response\":{\"orderSerialNo\":\"CHANGED\"}}'\n",
        encoding="utf-8",
    )

    changed = snapshots.create("train-booking-core", original.scan_id)
    assert changed.snapshot_id != original.snapshot_id
    with pytest.raises(KnowledgeValidationError, match="stale"):
        service.execute(
            ExecutionRequest(
                system_id="train-booking-core",
                variant_id=variant.variant_id,
                snapshot_id=original.snapshot_id,
            )
        )


def test_snapshot_rejects_custom_lifecycle_case_from_another_scan(tmp_path: Path) -> None:
    """BLOCKED自定义Case仍必须与Snapshot的源码扫描版本一致。"""

    service, _, snapshots = _execution_fixture(tmp_path)
    custom_root = service.store.system_root("train-booking-core") / "cases" / "custom"
    custom_root.mkdir(parents=True)
    (custom_root / "blocked-case.yaml").write_text(
        """schema_version: opentest.variant/v2alpha1
lifecycle: blocked
source_scan_id: scan-from-another-baseline
""",
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeValidationError, match="belongs to"):
        snapshots.create("train-booking-core")


def test_execution_reaches_oracle_step_and_persists_observations(tmp_path: Path) -> None:
    """ScenarioStep中的Oracle应由执行服务组装轮询并写入RunRecord证据。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    oracle_step = ScenarioStep(
        step_id="query-order-state",
        name="查询订单状态",
        action="oracle",
        oracle=OracleRequest(
            oracle_id="oracle:order-state",
            system_id="train-booking-core",
            kind="dsf",
            operation="facade.order.query_order_info",
            assertions={"$.status": "TICKETING"},
            timeout_seconds=2,
            poll_interval_seconds=1,
        ),
    )
    updated = variant.model_copy(update={"steps": [*variant.steps, oracle_step]})
    service.case_store.write_variant(updated)

    def build_test_poller(manifest: ScanManifest, executor: DsfExecutor) -> OraclePoller:
        """返回确定性DSF Oracle以验证生产执行路径，不访问真实QA。"""

        return OraclePoller({"dsf": SequenceOracle([{"status": "TICKETING"}])})

    service._build_oracle_poller = build_test_poller  # type: ignore[method-assign]
    snapshot = snapshots.create("train-booking-core")
    record = service.execute(
        ExecutionRequest(
            system_id="train-booking-core",
            variant_id=variant.variant_id,
            snapshot_id=snapshot.snapshot_id,
        )
    )

    assert record.status == "passed"
    oracle_result = next(item for item in record.step_results if item.step_id == "query-order-state")
    assert oracle_result.status == "passed"
    assert oracle_result.evidence[0]["value"] == {"status": "TICKETING"}


def test_invalid_assertion_contract_produces_failed_run_record(tmp_path: Path) -> None:
    """非法正则等断言契约错误必须落入失败步骤而不是让整个RunRecord消失。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    invalid_assert = ScenarioStep(
        step_id="invalid-regex",
        name="模拟损坏断言",
        action="assert",
        assertions={"$.success": {"op": "regex", "value": "["}},
    )
    updated = variant.model_copy(update={"steps": [variant.steps[0], invalid_assert]})
    service.case_store.write_variant(updated)
    snapshot = snapshots.create("train-booking-core")

    record = service.execute(
        ExecutionRequest(
            system_id="train-booking-core",
            variant_id=variant.variant_id,
            snapshot_id=snapshot.snapshot_id,
        )
    )

    assert record.status == "failed"
    assert record.step_results[1].status == "failed"
    assert "KnowledgeValidationError" in record.step_results[1].error
    assert service.get_run(record.run_id) == record


def test_run_record_redacts_sensitive_business_response_fields(tmp_path: Path) -> None:
    """工具原始业务响应中的姓名和手机号不得原样写入RunRecord。"""

    service, variant, snapshots = _execution_fixture(tmp_path)
    manifest = service.artifacts.read("train-booking-core")
    script = Path(manifest.tools[0].script_path)
    script.write_text(
        "#!/bin/sh\nprintf '%s\\n' "
        "'{\"success\":true,\"response\":{\"orderSerialNo\":\"QA-ORDER-1\","
        "\"name\":\"ALICE\",\"phone\":\"13800000000\"}}'\n",
        encoding="utf-8",
    )
    snapshot = snapshots.create("train-booking-core")

    record = service.execute(
        ExecutionRequest(
            system_id="train-booking-core",
            variant_id=variant.variant_id,
            snapshot_id=snapshot.snapshot_id,
        )
    )

    persisted_output = record.step_results[0].output["response"]
    assert persisted_output["name"] == "<redacted>"
    assert persisted_output["phone"] == "<redacted>"
