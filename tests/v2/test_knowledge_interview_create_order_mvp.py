"""验证知识访谈、修订、BLOCKED引导和createOrder MVP安全闭环。"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opentest.adapters.create_order_fixture import CreateOrderMvpFixtureStore
from opentest.adapters.environment_config import LocalEnvironmentLoader
from opentest.adapters.knowledge_store import AUTO_END, AUTO_START
from opentest.adapters.qa_worker import QaWorkerClient
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.adapters.source_analysis import GitSourceRepository
from opentest.api import create_app
from opentest.application.create_order_mvp import (
    BOOKING_CORE_SYSTEM_ID,
    CreateOrderMvpService,
    MvpRuntimeDependencies,
)
from opentest.application.foundation import OpenTestApplication
from opentest.application.snapshots import SnapshotService
from opentest.domain.models import (
    CreateOrderMvpFixture,
    CreateOrderMvpRunRequest,
    EntryPoint,
    KnowledgeGenerationBatchRequest,
    KnowledgeInterview,
    KnowledgeConfirmation,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeQuestion,
    KnowledgeRevisionRequest,
    KnowledgeStatus,
    ScanManifest,
    SourceBaseline,
    SystemDefinition,
    ToolDefinition,
    ToolExecutionResult,
)
from opentest.domain.errors import ExecutionFailure


class _UnavailableAgent:
    """让草稿测试模拟Codex单目标失败并验证确定性降级。"""

    def availability(self) -> tuple[bool, bool]:
        """声明Codex可提交，使失败发生在单目标执行阶段。"""

        return True, False

    def is_available(self, agent: str) -> bool:
        """只允许测试显式选择Codex。"""

        return agent == "codex"

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """模拟已选Codex执行失败且绝不调用其他Agent。

        Raises:
            ExecutionFailure: 始终触发当前目标仅代码事实降级。
        """

        del request, source_root, evidence_root
        raise ExecutionFailure("simulated codex failure")


class _FakeDsfExecutor:
    """返回固定安全创单响应且不访问QA。"""

    def execute(self, tool: ToolDefinition, tool_root: Path, params: dict[str, Any], timeout_seconds: int) -> ToolExecutionResult:
        """记录无敏感输出的创单结果，参数只用于确认服务完成请求物化。"""

        del tool_root, timeout_seconds
        assert params["traceId"].startswith("OPENTEST-")
        assert params["bookInfo"]["serialId"].startswith("OPENTEST")
        return ToolExecutionResult(
            tool_id=tool.tool_id,
            exit_code=0,
            command=["fake-dsf"],
            output={
                "success": True,
                "response": {
                    "success": True,
                    "code": 200,
                    "result": {
                        "createResult": True,
                        "orderSerialId": "HT-OPENTEST-1",
                        "transactionId": "TX-OPENTEST-1",
                        "supplierId": "TM-100",
                    },
                },
            },
            elapsed_seconds=0.01,
        )


class _FakeWorker:
    """按批准操作ID返回固定MySQL与Redis白名单投影。"""

    def execute(self, request: object, environment: object, timeout_seconds: float) -> Any:
        """返回MVP通过所需的确定性业务观察值。"""

        del environment, timeout_seconds
        values = {
            "order.primary_detail": {
                "rowCount": 1,
                "rows": [{
                    "orderSerialNo": "HT-OPENTEST-1",
                    "transactionSerialNo": "TX-OPENTEST-1",
                    "orderState": 5,
                    "merchantId": "M-100",
                    "merchantType": 1,
                    "ticketMachineId": "TM-100",
                    "deleted": 0,
                    "environment": "qa",
                }],
            },
            "collection.detail": {"rowCount": 0, "rows": []},
            "order.items_by_transaction": {
                "rowCount": 1,
                "rows": [{
                    "orderSerialNo": "HT-OPENTEST-1",
                    "transactionSerialNo": "TX-OPENTEST-1",
                    "itemId": "ITEM-1",
                    "passengerType": 1,
                    "seatClass": 2,
                    "userTicketPrice": 100,
                    "deleted": 0,
                    "environment": "qa",
                }],
            },
            "redis.merchant_pending_membership": {"member": True},
            "redis.ticket_machine_pending_membership": {"exists": True, "valueMatches": True},
        }
        return values[request.operation_id]


class _AsyncDsfExecutor:
    """返回创单时尚未分配票机的固定响应。"""

    def execute(self, tool: ToolDefinition, tool_root: Path, params: dict[str, Any], timeout_seconds: int) -> ToolExecutionResult:
        """模拟真实入口成功但supplierId为空的异步分票机响应。"""

        del tool_root, params, timeout_seconds
        return ToolExecutionResult(
            tool_id=tool.tool_id,
            exit_code=0,
            command=["fake-dsf"],
            output={"success": True, "response": {"success": True, "code": 200, "result": {"createResult": True, "orderSerialId": "HT-OPENTEST-1", "transactionId": "TX-OPENTEST-1", "supplierId": None}}},
            elapsed_seconds=0.01,
        )


class _MismatchedTicketMachineDsfExecutor(_FakeDsfExecutor):
    """模拟创单成功但返回票机与业务预期不一致的脱敏响应。"""

    def execute(self, tool: ToolDefinition, tool_root: Path, params: dict[str, Any], timeout_seconds: int) -> ToolExecutionResult:
        """保留真实订单号并只篡改票机结果，验证失败报告仍可清理订单。"""

        output = super().execute(tool, tool_root, params, timeout_seconds)
        output.output["response"]["result"]["supplierId"] = "TM-UNEXPECTED"
        return output


class _AsyncWorker(_FakeWorker):
    """让主库票机从空变为已分配，模拟可归因异步效果。"""

    def __init__(self, initially_assigned: bool = False):
        """配置首次主库观察是否已经存在票机。"""

        self.primary_reads = 0
        self.initially_assigned = initially_assigned

    def execute(self, request: object, environment: object, timeout_seconds: float) -> Any:
        """按主库读取次数返回票机空值或分配后的业务投影。"""

        if request.operation_id != "order.primary_detail":
            return super().execute(request, environment, timeout_seconds)
        self.primary_reads += 1
        assigned = self.initially_assigned or self.primary_reads > 1
        return {
            "rowCount": 1,
            "rows": [{
                "orderSerialNo": "HT-OPENTEST-1",
                "transactionSerialNo": "TX-OPENTEST-1",
                "orderState": 5,
                "merchantId": "M-100",
                "merchantType": 1,
                "ticketMachineId": "TM-ASYNC" if assigned else None,
                "deleted": 0,
                "environment": "qa",
            }],
        }


class _AsyncRedisFailureWorker(_AsyncWorker):
    """模拟数据库已异步分票机但Redis业务效果尚未建立。"""

    def execute(self, request: object, environment: object, timeout_seconds: float) -> Any:
        """只让票机处理中Key断言失败，验证MQ证据不会提前标记。"""

        if request.operation_id == "redis.ticket_machine_pending_membership":
            return {"exists": False, "valueMatches": False}
        return super().execute(request, environment, timeout_seconds)


def _write_booking_scan(application: OpenTestApplication, source: Path) -> ScanManifest:
    """写入可创建Snapshot且包含真实createOrder逻辑工具的最小扫描。"""

    baseline = SourceBaseline(source_path=str(source), commit="mvp-test")
    script = application.knowledge_root / ".opentest/tools" / BOOKING_CORE_SYSTEM_ID / "scan-mvp-test/create-order.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    manifest = ScanManifest(
        scan_id="scan-mvp-test",
        system_id=BOOKING_CORE_SYSTEM_ID,
        baseline=baseline,
        entries=[EntryPoint(
            entry_id="facade:booking.TradeFacade#createOrder",
            system_id=BOOKING_CORE_SYSTEM_ID,
            kind="facade",
            display_name="TradeFacade#createOrder",
            source_id="booking.TradeFacade#createOrder",
            source_path=str(source / "TradeFacade.java"),
            tool_id="facade.trade.create_order",
        )],
        tools=[ToolDefinition(
            tool_id="facade.trade.create_order",
            system_id=BOOKING_CORE_SYSTEM_ID,
            display_name="createOrder",
            script_path=str(script),
            source_id="booking.TradeFacade#createOrder",
            metadata={"status": "ready"},
        )],
        tool_root=str(script.parent),
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(BOOKING_CORE_SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(BOOKING_CORE_SYSTEM_ID, baseline)
    return manifest


def _write_mvp_validation_artifacts(application: OpenTestApplication) -> None:
    """写入无QA行为的Worker与结果校验目录占位制品供编排单测使用。

    Args:
        application: 使用临时知识根的测试应用。

    Side Effects:
        仅在pytest临时目录创建计划门禁所需普通文件，不启动Java或访问QA。
    """

    worker_jar = application.knowledge_root.parent / "workers/qa-oracle-worker/target/opentest-qa-oracle-worker.jar"
    worker_jar.parent.mkdir(parents=True, exist_ok=True)
    worker_jar.write_bytes(b"test-worker")
    catalog = application.store.system_root(BOOKING_CORE_SYSTEM_ID) / "oracles/catalog.yaml"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("operations: []\n", encoding="utf-8")


def _fixture() -> CreateOrderMvpFixture:
    """构造含身份占位值但仅保存在测试隔离目录的完整创单Fixture。"""

    return CreateOrderMvpFixture(
        system_id=BOOKING_CORE_SYSTEM_ID,
        request={
            "traceId": "ORIGINAL-TRACE",
            "bookInfo": {"serialId": "ORIGINAL-HT"},
            "passengers": [{"name": "测试乘客", "idCard": "SECRET-CARD", "type": 1, "seatClass": 2, "ticketPrice": 100}],
            "contactInfo": {"phone": "13800000000"},
        },
        expected_merchant_id="M-100",
        ticket_machine_mode="IMMEDIATE",
        expected_ticket_machine_id="TM-100",
    )


def _async_fixture() -> CreateOrderMvpFixture:
    """构造声明异步票机分配的本地Fixture。"""

    return _fixture().model_copy(update={"ticket_machine_mode": "ASYNC", "expected_ticket_machine_id": ""})


def test_async_fixture_rejects_predefined_ticket_machine() -> None:
    """异步模式不得携带预设票机，以免把非本轮变化错误归因为MQ效果。"""

    payload = _fixture().model_dump(mode="json")
    payload.update({"ticket_machine_mode": "ASYNC", "expected_ticket_machine_id": "TM-STALE"})

    with pytest.raises(ValueError, match="must not predefine"):
        CreateOrderMvpFixture.model_validate(payload)


def test_interview_propagates_to_multiple_drafts_without_publishing(tmp_path: Path) -> None:
    """集中访谈应更新草稿，且仅代码事实继续作为非人工知识可浏览。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示", source_path=str(source)))
    (source / "OrderFacade.java").write_text("interface OrderFacade { void query(); }", encoding="utf-8")
    baseline = GitSourceRepository().capture(source)
    manifest = ScanManifest(
        scan_id="scan-interview-test",
        system_id="demo-system",
        baseline=baseline,
        entries=[EntryPoint(entry_id="facade:demo.OrderFacade#query", system_id="demo-system", kind="facade", display_name="OrderFacade#query", source_id="demo.OrderFacade#query", source_path=str(source / "OrderFacade.java"))],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest("demo-system", manifest.scan_id)
    application.store.update_source_baseline("demo-system", manifest.baseline)
    application.skip_background_interview("demo-system")
    batch = application.knowledge.generate_drafts(
        KnowledgeGenerationBatchRequest(
            system_id="demo-system",
            target_ids=[manifest.entries[0].entry_id],
            agent="codex",
            confirmed=True,
        ),
        _UnavailableAgent(),
    )

    result = application.save_knowledge_interview(KnowledgeInterview(system_id="demo-system", system_purpose="订单查询", business_terms={"EBK": "供应商工作台"}))
    updated = application.store.read_draft_batch("demo-system", batch.batch_id)

    assert result["affected_node_ids"]
    assert all("项目访谈口径" in draft.content for draft in updated.drafts)
    published_nodes = application.store.list_nodes("demo-system")
    assert published_nodes
    assert {node.status for node, _, _ in published_nodes} == {KnowledgeStatus.CODE_VERIFIED}
    interview_path = application.knowledge_root / ".opentest/knowledge-interviews/demo-system/interview.json"
    assert stat.S_IMODE(interview_path.stat().st_mode) == 0o600
    application.close()


def test_resaving_interview_preserves_answered_draft_content(tmp_path: Path) -> None:
    """回答草稿问题后再次保存访谈时不得截断人工确认口径。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示", source_path=str(source)))
    (source / "OrderFacade.java").write_text("interface OrderFacade { void query(); }", encoding="utf-8")
    baseline = GitSourceRepository().capture(source)
    manifest = ScanManifest(
        scan_id="scan-interview-answer-test",
        system_id="demo-system",
        baseline=baseline,
        entries=[EntryPoint(entry_id="facade:demo.OrderFacade#query", system_id="demo-system", kind="facade", display_name="OrderFacade#query", source_id="demo.OrderFacade#query", source_path=str(source / "OrderFacade.java"))],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest("demo-system", manifest.scan_id)
    application.store.update_source_baseline("demo-system", manifest.baseline)
    application.skip_background_interview("demo-system")
    batch = application.knowledge.generate_drafts(
        KnowledgeGenerationBatchRequest(
            system_id="demo-system",
            target_ids=[manifest.entries[0].entry_id],
            agent="codex",
            confirmed=True,
        ),
        _UnavailableAgent(),
    )
    question = KnowledgeQuestion(
        question_id="question:interview-preserve",
        system_id="demo-system",
        title="确认EBK口径",
        detail="EBK含义是什么？",
        affected_node_ids=[batch.drafts[0].node.node_id],
    )
    batch = batch.model_copy(update={"questions": [question]})
    application.store.write_draft_batch(batch)

    application.save_knowledge_interview(KnowledgeInterview(system_id="demo-system", system_purpose="订单查询"))
    application.answer_knowledge_batch_question(
        "demo-system",
        batch.batch_id,
        KnowledgeConfirmation(
            question_id=question.question_id,
            answer="EBK是供应商工作台",
            confirmed_node_ids=question.affected_node_ids,
        ),
    )
    application.save_knowledge_interview(
        KnowledgeInterview(system_id="demo-system", system_purpose="订单查询与供应商协作"),
    )
    updated = application.store.read_draft_batch("demo-system", batch.batch_id)

    assert "订单查询与供应商协作" in updated.drafts[0].content
    assert "人工确认：EBK是供应商工作台" in updated.drafts[0].content
    assert "人工确认：EBK是供应商工作台" in updated.drafts[0].answer_notes
    application.close()


def test_revision_requires_answer_and_preserves_manual_region(tmp_path: Path) -> None:
    """知识反馈应先回答再发布，并由存储边界保留已有人工区域。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示", source_path=str(source)))
    node = KnowledgeNode(node_id="facade:OrderFacade#query", system_id="demo-system", kind=KnowledgeNodeKind.FACADE, title="查询订单", status=KnowledgeStatus.USER_CONFIRMED)
    path = application.store.write_node(node, "初始自动内容")
    path.write_text(path.read_text(encoding="utf-8") + "\n人工备注：保留此段\n", encoding="utf-8")

    plan = application.create_knowledge_revision("demo-system", KnowledgeRevisionRequest(node_id=node.node_id, feedback="遗漏EBK筛选规则"))
    question = plan.questions[0]
    answered = application.answer_knowledge_revision(
        "demo-system",
        plan.revision_id,
        SimpleNamespace(question_id=question.question_id, answer="仅查询启用EBK", confirmed_node_ids=plan.affected_node_ids),
    )
    published = application.publish_knowledge_revision("demo-system", plan.revision_id)
    body = application.store.get_node("demo-system", node.node_id)[2]

    assert answered.status == "DRAFT_UPDATED"
    assert published.status == "PUBLISHED"
    assert "仅查询启用EBK" in body
    assert "人工备注：保留此段" in body
    application.close()


def test_revision_retries_same_answer_but_rejects_conflicting_content(tmp_path: Path) -> None:
    """同一修订答案应幂等重放，但必须拒绝覆盖为冲突口径。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示", source_path=str(source)))
    node = KnowledgeNode(
        node_id="facade:OrderFacade#query",
        system_id="demo-system",
        kind=KnowledgeNodeKind.FACADE,
        title="查询订单",
        status=KnowledgeStatus.USER_CONFIRMED,
    )
    application.store.write_node(node, "初始自动内容")
    plan = application.create_knowledge_revision(
        "demo-system",
        KnowledgeRevisionRequest(node_id=node.node_id, feedback="补充EBK规则"),
    )
    first_answer = KnowledgeConfirmation(
        question_id=plan.questions[0].question_id,
        answer="只使用启用的EBK",
        confirmed_node_ids=[node.node_id],
    )
    first_plan = application.answer_knowledge_revision("demo-system", plan.revision_id, first_answer)
    duplicate_plan = application.answer_knowledge_revision("demo-system", plan.revision_id, first_answer)

    with pytest.raises(Exception, match="already been answered"):
        application.answer_knowledge_revision(
            "demo-system",
            plan.revision_id,
            first_answer.model_copy(update={"answer": "改用另一个冲突口径"}),
        )

    updated = application.list_knowledge_revisions("demo-system")[0]
    assert duplicate_plan == first_plan
    assert updated.proposed_by_node[node.node_id].count("只使用启用的EBK") == 1
    assert "改用另一个冲突口径" not in updated.proposed_by_node[node.node_id]
    application.close()


def test_revision_publish_rejects_stale_automatic_content(tmp_path: Path) -> None:
    """修订形成后知识自动区变化时必须拒绝旧差异覆盖新的源码事实。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示", source_path=str(source)))
    node = KnowledgeNode(
        node_id="facade:OrderFacade#create",
        system_id="demo-system",
        kind=KnowledgeNodeKind.FACADE,
        title="创建订单",
        status=KnowledgeStatus.USER_CONFIRMED,
    )
    application.store.write_node(node, "原自动知识")
    revision = application.create_knowledge_revision(
        "demo-system",
        KnowledgeRevisionRequest(node_id=node.node_id, feedback="补充分单规则"),
    )
    application.answer_knowledge_revision(
        "demo-system",
        revision.revision_id,
        SimpleNamespace(
            question_id=revision.questions[0].question_id,
            answer="以新分单规则为准",
            confirmed_node_ids=[node.node_id],
        ),
    )
    application.store.write_node(node, "扫描后新增的自动知识")

    with pytest.raises(Exception, match="changed after revision planning"):
        application.publish_knowledge_revision("demo-system", revision.revision_id)

    body = application.store.get_node("demo-system", node.node_id)[2]
    assert "扫描后新增的自动知识" in body
    assert "以新分单规则为准" not in body
    application.close()


def test_blocked_natural_language_preview_returns_repair_actions_without_qa(tmp_path: Path) -> None:
    """缺少确认知识时应返回BLOCKED引导而不是裸错误或QA副作用。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示", source_path=str(source)))
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post("/api/v2/systems/demo-system/natural-language-tests/previews", json={"text": "创建一个订单"})

    preview = response.json()["preview"]
    assert response.status_code == 201
    assert preview["status"] == "BLOCKED"
    assert {item["action_id"] for item in preview["repair_actions"]} == {"OPEN_SCAN", "GENERATE_KNOWLEDGE", "ANSWER_QUESTIONS"}
    assert not (application.knowledge_root / ".opentest/runs").exists()


def test_fixture_api_returns_only_summary_and_snapshot_binds_digest(tmp_path: Path) -> None:
    """Fixture API不得回显身份字段，Snapshot只记录摘要且Fixture变化会改ID。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    _write_booking_scan(application, source)
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.put(f"/api/v2/systems/{BOOKING_CORE_SYSTEM_ID}/create-order-mvp/fixture", json=_fixture().model_dump(mode="json"))
        snapshot_response = client.post(f"/api/v2/systems/{BOOKING_CORE_SYSTEM_ID}/snapshots")

    assert response.status_code == 200
    assert "SECRET-CARD" not in response.text
    assert "13800000000" not in response.text
    fixture_path = application.knowledge_root / ".opentest/environments" / BOOKING_CORE_SYSTEM_ID / "create-order-mvp.yaml"
    assert stat.S_IMODE(fixture_path.stat().st_mode) == 0o600
    snapshot = snapshot_response.json()["snapshot"]
    assert snapshot["create_order_mvp_fixture_digest"]
    snapshot_text = json.dumps(snapshot, ensure_ascii=False)
    assert "测试乘客" not in snapshot_text and "SECRET-CARD" not in snapshot_text


def test_invalid_fixture_api_does_not_echo_sensitive_payload_fragments(tmp_path: Path) -> None:
    """Fixture校验失败时API不得由默认422回显证件、电话或完整请求片段。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    invalid_payload = _fixture().model_dump(mode="json")
    invalid_payload["request"].pop("bookInfo")

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.put(
            f"/api/v2/systems/{BOOKING_CORE_SYSTEM_ID}/create-order-mvp/fixture",
            json=invalid_payload,
        )

    assert response.status_code == 400
    assert "SECRET-CARD" not in response.text
    assert "13800000000" not in response.text
    assert "测试乘客" not in response.text
    assert "测试数据格式不正确" in response.text
    application.close()


@pytest.mark.parametrize(
    "request_body",
    [
        '[{"idCard":"SECRET-CARD","phone":"13800000000"}]',
        '{"idCard":"SECRET-CARD","phone":"13800000000"',
    ],
)
def test_fixture_api_rejects_non_object_or_malformed_json_without_echo(tmp_path: Path, request_body: str) -> None:
    """Fixture根节点非对象或JSON损坏时也不得由框架默认422回显敏感输入。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.put(
            f"/api/v2/systems/{BOOKING_CORE_SYSTEM_ID}/create-order-mvp/fixture",
            content=request_body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert "SECRET-CARD" not in response.text
    assert "13800000000" not in response.text
    assert "测试数据格式不正确" in response.text
    application.close()


def test_invalid_passenger_fixture_blocks_before_dsf_factory(tmp_path: Path) -> None:
    """缺少Item断言字段的历史Fixture必须在计划阶段阻塞且不构造DSF客户端。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    fixture_path = application.knowledge_root / ".opentest/environments" / BOOKING_CORE_SYSTEM_ID / "create-order-mvp.yaml"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        "\n".join(
            [
                f"system_id: {BOOKING_CORE_SYSTEM_ID}",
                "request:",
                "  bookInfo: {serialId: ORIGINAL}",
                "  passengers:",
                "    - {type: 1}",
                "expected_merchant_id: M-100",
                "ticket_machine_mode: IMMEDIATE",
                "expected_ticket_machine_id: TM-100",
            ]
        ),
        encoding="utf-8",
    )
    fixture_path.chmod(0o600)
    called = {"dsf": 0}
    service = CreateOrderMvpService(
        application.snapshots,
        LocalEnvironmentLoader(application.knowledge_root / ".opentest/environments"),
        application.create_order_fixture,
        MvpRuntimeDependencies(dsf_executor_factory=lambda _env: called.__setitem__("dsf", called["dsf"] + 1)),
    )

    plan = service.plan(BOOKING_CORE_SYSTEM_ID)

    assert plan.status == "BLOCKED"
    assert "create_order_mvp_fixture_invalid" in {item.key for item in plan.missing_conditions}
    assert called["dsf"] == 0
    application.close()


def test_cross_system_fixture_is_reported_as_blocked_but_read_remains_rejected(tmp_path: Path) -> None:
    """历史Fixture系统ID错位时计划应可恢复地阻塞，执行读取仍必须强隔离拒绝。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    fixture_path = application.knowledge_root / ".opentest/environments" / BOOKING_CORE_SYSTEM_ID / "create-order-mvp.yaml"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _fixture().model_dump(mode="json")
    payload["system_id"] = "another-booking-system"
    fixture_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    fixture_path.chmod(0o600)

    summary = application.get_create_order_mvp_fixture(BOOKING_CORE_SYSTEM_ID)

    assert not summary.configured
    assert "create_order_mvp_fixture_invalid" in {item.key for item in summary.missing_conditions}
    with pytest.raises(Exception, match="another system"):
        application.create_order_fixture.read(BOOKING_CORE_SYSTEM_ID)
    application.close()


def test_fixture_store_rejects_symbolic_link(tmp_path: Path) -> None:
    """MVP Fixture最终文件或父目录符号链接不得跨系统覆盖。"""

    root = tmp_path / "environments"
    target = tmp_path / "outside.yaml"
    target.write_text("outside", encoding="utf-8")
    system_root = root / BOOKING_CORE_SYSTEM_ID
    system_root.mkdir(parents=True)
    (system_root / "create-order-mvp.yaml").symlink_to(target)

    with pytest.raises(Exception, match="regular file|symbolic|settings"):
        CreateOrderMvpFixtureStore(root).write(_fixture())
    assert target.read_text(encoding="utf-8") == "outside"


def test_mvp_plan_blocked_does_not_construct_qa_clients(tmp_path: Path) -> None:
    """知识或Fixture缺失时计划必须BLOCKED且不构造DSF或Worker客户端。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    called = {"dsf": 0, "worker": 0}
    service = CreateOrderMvpService(
        application.snapshots,
        LocalEnvironmentLoader(application.knowledge_root / ".opentest/environments"),
        application.create_order_fixture,
        MvpRuntimeDependencies(
            dsf_executor_factory=lambda _env: called.__setitem__("dsf", called["dsf"] + 1),
            worker_factory=lambda _system: called.__setitem__("worker", called["worker"] + 1),
        ),
    )

    plan = service.plan(BOOKING_CORE_SYSTEM_ID)

    assert plan.status == "BLOCKED"
    assert called == {"dsf": 0, "worker": 0}
    application.close()


def test_mvp_plan_blocks_before_order_creation_when_validation_artifacts_are_missing(tmp_path: Path) -> None:
    """Worker或结果校验目录缺失时必须在任何真实DSF构造前阻塞计划。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    _write_booking_scan(application, source)
    application.store.write_node(
        KnowledgeNode(
            node_id="facade:TradeFacade#createOrder",
            system_id=BOOKING_CORE_SYSTEM_ID,
            kind=KnowledgeNodeKind.FACADE,
            title="创建订单",
            status=KnowledgeStatus.USER_CONFIRMED,
        ),
        "创建订单业务知识",
    )
    application.create_order_fixture.write(_fixture())
    # 系统注册会安装Booking.Core固定目录；本用例显式移除它以同时验证两个前置门禁。
    (application.store.system_root(BOOKING_CORE_SYSTEM_ID) / "oracles/catalog.yaml").unlink()
    called = {"dsf": 0}
    service = CreateOrderMvpService(
        application.snapshots,
        LocalEnvironmentLoader(application.knowledge_root / ".opentest/environments"),
        application.create_order_fixture,
        MvpRuntimeDependencies(dsf_executor_factory=lambda _env: called.__setitem__("dsf", called["dsf"] + 1)),
    )

    plan = service.plan(BOOKING_CORE_SYSTEM_ID)

    assert plan.status == "BLOCKED"
    assert {condition.key for condition in plan.missing_conditions} >= {"qa_worker", "validation_catalog"}
    assert called["dsf"] == 0
    application.close()


def test_archive_includes_interview_revision_fixture_and_mvp_report(tmp_path: Path) -> None:
    """系统归档必须携带新增的访谈、修订、Fixture和MVP报告并可恢复。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    application.save_knowledge_interview(KnowledgeInterview(system_id=BOOKING_CORE_SYSTEM_ID, system_purpose="创建并维护供应链订单"))
    node = KnowledgeNode(node_id="facade:TradeFacade#createOrder", system_id=BOOKING_CORE_SYSTEM_ID, kind=KnowledgeNodeKind.FACADE, title="创建订单", status=KnowledgeStatus.USER_CONFIRMED)
    application.store.write_node(node, "创建订单")
    revision = application.create_knowledge_revision(BOOKING_CORE_SYSTEM_ID, KnowledgeRevisionRequest(node_id=node.node_id, feedback="补充分单规则"))
    application.create_order_fixture.write(_fixture())
    report_path = application.knowledge_root / ".opentest/mvp-runs/mvp-run-archive.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({"system_id": BOOKING_CORE_SYSTEM_ID, "run_id": "mvp-run-archive"}), encoding="utf-8")

    record = application.archive_system(BOOKING_CORE_SYSTEM_ID, "验证新增本地产物归档")
    archived_paths = {str(item.relative_path) for item in record.files}

    assert f"knowledge-interviews/{BOOKING_CORE_SYSTEM_ID}/interview.json" in archived_paths
    assert f"knowledge-revisions/{BOOKING_CORE_SYSTEM_ID}/{revision.revision_id}.json" in archived_paths
    assert f"environments/{BOOKING_CORE_SYSTEM_ID}/create-order-mvp.yaml" in archived_paths
    assert "mvp-runs/mvp-run-archive.json" in archived_paths
    application.restore_system(record.archive_id)
    assert application.get_create_order_mvp_fixture(BOOKING_CORE_SYSTEM_ID).configured
    application.close()


def test_immediate_mvp_passes_with_fake_dsf_and_worker_and_redacts_report(tmp_path: Path) -> None:
    """立即分票机MVP应验证主库、临时库、Item和Redis并把MQ标记N/A。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    manifest = _write_booking_scan(application, source)
    application.store.write_node(
        KnowledgeNode(node_id="facade:TradeFacade#createOrder", system_id=BOOKING_CORE_SYSTEM_ID, kind=KnowledgeNodeKind.FACADE, title="创建订单", status=KnowledgeStatus.USER_CONFIRMED),
        "创建订单业务知识",
    )
    _write_mvp_validation_artifacts(application)
    application.create_order_fixture.write(_fixture())
    environment_path = application.knowledge_root / ".opentest/environments" / BOOKING_CORE_SYSTEM_ID / "qa.yaml"
    environment_path.parent.mkdir(parents=True, exist_ok=True)
    environment_path.write_text(f"system_id: {BOOKING_CORE_SYSTEM_ID}\nenvironment: qa\nvalues:\n  tool_environment:\n    LABRADOR_TOKEN: test-token\nconnections: {{}}\n", encoding="utf-8")
    environment_path.chmod(0o600)
    snapshot = application.snapshots.create(BOOKING_CORE_SYSTEM_ID, manifest.scan_id)
    service = CreateOrderMvpService(
        application.snapshots,
        LocalEnvironmentLoader(environment_path.parents[1]),
        application.create_order_fixture,
        MvpRuntimeDependencies(dsf_executor_factory=lambda _env: _FakeDsfExecutor(), worker_factory=lambda _system: _FakeWorker()),
    )

    result = service.execute(BOOKING_CORE_SYSTEM_ID, CreateOrderMvpRunRequest(snapshot_id=snapshot.snapshot_id, confirmed=True))

    assert result.status == "PASSED"
    assert result.mq_evidence_mode == "N/A"
    assert result.tidb_status == "BLOCKED"
    assert {step.step_id for step in result.step_results} >= {"execute-create-order", "observe-primary-order", "observe-collection", "observe-order-items", "observe-merchant-pending", "observe-ticket-machine-pending"}
    report_path = application.knowledge_root / ".opentest/mvp-runs" / f"{result.run_id}.json"
    report = report_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert "SECRET-CARD" not in report and "13800000000" not in report and "test-token" not in report
    assert AUTO_START not in report and AUTO_END not in report
    application.close()


def test_failed_response_assertion_still_retains_created_order_for_cleanup(tmp_path: Path) -> None:
    """创单已返回订单号但票机断言失败时，报告仍须记录保留订单供人工清理。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    manifest = _write_booking_scan(application, source)
    application.store.write_node(
        KnowledgeNode(
            node_id="facade:TradeFacade#createOrder",
            system_id=BOOKING_CORE_SYSTEM_ID,
            kind=KnowledgeNodeKind.FACADE,
            title="创建订单",
            status=KnowledgeStatus.USER_CONFIRMED,
        ),
        "创建订单业务知识",
    )
    _write_mvp_validation_artifacts(application)
    application.create_order_fixture.write(_fixture())
    environment_path = application.knowledge_root / ".opentest/environments" / BOOKING_CORE_SYSTEM_ID / "qa.yaml"
    environment_path.parent.mkdir(parents=True, exist_ok=True)
    environment_path.write_text(
        f"system_id: {BOOKING_CORE_SYSTEM_ID}\nenvironment: qa\nvalues:\n  tool_environment:\n    LABRADOR_TOKEN: test-token\nconnections: {{}}\n",
        encoding="utf-8",
    )
    environment_path.chmod(0o600)
    snapshot = application.snapshots.create(BOOKING_CORE_SYSTEM_ID, manifest.scan_id)
    service = CreateOrderMvpService(
        application.snapshots,
        LocalEnvironmentLoader(environment_path.parents[1]),
        application.create_order_fixture,
        MvpRuntimeDependencies(dsf_executor_factory=lambda _env: _MismatchedTicketMachineDsfExecutor()),
    )

    result = service.execute(
        BOOKING_CORE_SYSTEM_ID,
        CreateOrderMvpRunRequest(snapshot_id=snapshot.snapshot_id, confirmed=True),
    )

    assert result.status == "FAILED"
    assert result.retained_order_serial_no == "HT-OPENTEST-1"
    assert result.transaction_serial_no == "TX-OPENTEST-1"
    application.close()


@pytest.mark.parametrize(
    ("initially_assigned", "expected_status", "expected_mq_mode"),
    [(False, "PASSED", "EFFECT_ONLY"), (True, "FAILED", "N/A")],
)
def test_async_mvp_only_claims_mq_effect_after_empty_to_assigned_transition(
    tmp_path: Path,
    initially_assigned: bool,
    expected_status: str,
    expected_mq_mode: str,
) -> None:
    """异步票机只有先空后有才能标记EFFECT_ONLY，初始已有票机必须失败。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    manifest = _write_booking_scan(application, source)
    application.store.write_node(
        KnowledgeNode(node_id="facade:TradeFacade#createOrder", system_id=BOOKING_CORE_SYSTEM_ID, kind=KnowledgeNodeKind.FACADE, title="创建订单", status=KnowledgeStatus.USER_CONFIRMED),
        "创建订单业务知识",
    )
    _write_mvp_validation_artifacts(application)
    application.create_order_fixture.write(_async_fixture())
    environment_path = application.knowledge_root / ".opentest/environments" / BOOKING_CORE_SYSTEM_ID / "qa.yaml"
    environment_path.parent.mkdir(parents=True, exist_ok=True)
    environment_path.write_text(f"system_id: {BOOKING_CORE_SYSTEM_ID}\nenvironment: qa\nvalues:\n  tool_environment:\n    LABRADOR_TOKEN: test-token\nconnections: {{}}\n", encoding="utf-8")
    environment_path.chmod(0o600)
    snapshot = application.snapshots.create(BOOKING_CORE_SYSTEM_ID, manifest.scan_id)
    worker = _AsyncWorker(initially_assigned)
    service = CreateOrderMvpService(
        application.snapshots,
        LocalEnvironmentLoader(environment_path.parents[1]),
        application.create_order_fixture,
        MvpRuntimeDependencies(dsf_executor_factory=lambda _env: _AsyncDsfExecutor(), worker_factory=lambda _system: worker),
    )

    result = service.execute(BOOKING_CORE_SYSTEM_ID, CreateOrderMvpRunRequest(snapshot_id=snapshot.snapshot_id, confirmed=True))

    assert result.status == expected_status
    assert result.mq_evidence_mode == expected_mq_mode
    assert ("observe-mq-effect" in {step.step_id for step in result.step_results}) is (expected_mq_mode == "EFFECT_ONLY")
    application.close()


def test_async_mvp_does_not_claim_mq_effect_when_redis_business_key_is_missing(tmp_path: Path) -> None:
    """数据库票机变化后Redis业务Key失败时，MQ证据必须保持N/A。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id=BOOKING_CORE_SYSTEM_ID, name="预订核心", source_path=str(source)))
    manifest = _write_booking_scan(application, source)
    application.store.write_node(
        KnowledgeNode(
            node_id="facade:TradeFacade#createOrder",
            system_id=BOOKING_CORE_SYSTEM_ID,
            kind=KnowledgeNodeKind.FACADE,
            title="创建订单",
            status=KnowledgeStatus.USER_CONFIRMED,
        ),
        "创建订单业务知识",
    )
    _write_mvp_validation_artifacts(application)
    application.create_order_fixture.write(_async_fixture())
    environment_path = application.knowledge_root / ".opentest/environments" / BOOKING_CORE_SYSTEM_ID / "qa.yaml"
    environment_path.parent.mkdir(parents=True, exist_ok=True)
    environment_path.write_text(
        f"system_id: {BOOKING_CORE_SYSTEM_ID}\nenvironment: qa\nvalues:\n  tool_environment:\n    LABRADOR_TOKEN: test-token\nconnections: {{}}\n",
        encoding="utf-8",
    )
    environment_path.chmod(0o600)
    snapshot = application.snapshots.create(BOOKING_CORE_SYSTEM_ID, manifest.scan_id)
    service = CreateOrderMvpService(
        application.snapshots,
        LocalEnvironmentLoader(environment_path.parents[1]),
        application.create_order_fixture,
        MvpRuntimeDependencies(
            dsf_executor_factory=lambda _env: _AsyncDsfExecutor(),
            worker_factory=lambda _system: _AsyncRedisFailureWorker(),
        ),
    )

    result = service.execute(
        BOOKING_CORE_SYSTEM_ID,
        CreateOrderMvpRunRequest(snapshot_id=snapshot.snapshot_id, confirmed=True),
    )

    assert result.status == "FAILED"
    assert result.mq_evidence_mode == "N/A"
    assert "observe-mq-effect" not in {step.step_id for step in result.step_results}
    application.close()


def test_worker_type_annotation_remains_compatible() -> None:
    """静态类型依赖的真实Worker类应仍可导入，防止测试桩掩盖适配器回归。"""

    assert QaWorkerClient.__name__ == "QaWorkerClient"
