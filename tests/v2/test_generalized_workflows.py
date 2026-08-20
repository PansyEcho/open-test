"""验证通用知识草稿、矩阵确认和自然语言预览的新业务闭环。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.knowledge_tracing import JavaKnowledgeTracer
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeDraftConfirmation,
    KnowledgeConfirmation,
    KnowledgeGenerationBatchRequest,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeQuestion,
    KnowledgeStatus,
    NaturalLanguageTestPreviewRequest,
    NaturalLanguageTestPreviewUpdate,
    NaturalLanguageTestPreview,
    ScanManifest,
    ResourceConnectionState,
    ResourceStateRecord,
    SourceBaseline,
    SystemDefinition,
    ValidationCapabilityDefinition,
    NaturalLanguageTestRunRequest,
)


class _UnavailableAgentRunner:
    """模拟本地Agent均不可用，验证确定性草稿仍可完成。"""

    def detect(self) -> tuple[None, bool, bool]:
        """返回两个Agent均不可用的固定检测结果。"""

        return None, False, False


class _InvalidOutputAgentRunner:
    """模拟Agent返回非法输出，并检查提示中没有本地敏感输入。"""

    def __init__(self, output_path: Path):
        """绑定测试专用本地输出路径。"""

        self.output_path = output_path
        self.prompt = ""

    def detect(self) -> tuple[str, bool, bool]:
        """声明Codex可用以触发增强路径。"""

        return "codex", True, False

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """记录提示并返回不符合JSON信封的本地证据。"""

        del source_root
        self.prompt = request.prompt
        run_root = evidence_root / "agent-invalid-test"
        run_root.mkdir(parents=True, exist_ok=True)
        self.output_path = run_root / "output.txt"
        self.output_path.write_text("not-json", encoding="utf-8")
        from types import SimpleNamespace

        return SimpleNamespace(output_path=str(self.output_path))


def _manifest(source: Path) -> ScanManifest:
    """构造同时包含Facade、Job、MQ和状态流转的最小真实Java扫描结果。"""

    facade = source / "OtherFacade.java"
    facade.write_text(
        """package demo; interface OtherFacade { void query(Request request); }""",
        encoding="utf-8",
    )
    implementation = source / "OtherFacadeImpl.java"
    implementation.write_text(
        """package demo;
class OtherFacadeImpl {
  Result query(Request request) {
    if (request.enabled()) { return customService.list(request.types()); }
    return Result.empty();
  }
}""",
        encoding="utf-8",
    )
    job = source / "TimeoutJob.java"
    job.write_text(
        """package demo;
class TimeoutJob {
  void doExecute() { for (Order order : orderService.queryTimeout()) { processOrder(order); } }
  void processOrder(Order order) { if (order.expired()) { rejectService.reject(order); } }
}""",
        encoding="utf-8",
    )
    consumer = source / "OrderListener.java"
    consumer.write_text(
        """package demo;
class OrderListener {
  boolean onUniformEvent(Event event) {
    if (orderService.lock(event.id())) { orderService.update(event.id()); }
    retryableProducer.send(event);
    return true;
  }
}""",
        encoding="utf-8",
    )
    actor = source / "TicketingPostActor.java"
    actor.write_text(
        """package demo;
class TicketingPostActor {
  boolean execute(Event event) { orderLogBuilder.save(event.order()); return true; }
  void addTask(Context stateContext) { if (stateContext.api()) { stateContext.addOrderTaskList(buildTask()); } }
}""",
        encoding="utf-8",
    )
    from opentest.domain.models import StateMachineDefinition, StateTransition, SourceReference

    entries = [
        EntryPoint(entry_id="facade:demo.OtherFacade#query", system_id="demo-system", kind="facade", display_name="OtherFacade#query", source_id="demo.OtherFacade#query", source_path=str(facade)),
        EntryPoint(entry_id="job:demo.TimeoutJob", system_id="demo-system", kind="job", display_name="超时处理Job", source_id="demo.TimeoutJob", source_path=str(job)),
        EntryPoint(entry_id="mq:demo.OrderListener#onUniformEvent", system_id="demo-system", kind="mq_consumer", display_name="OrderListener#onUniformEvent", source_id="demo.OrderListener#onUniformEvent", source_path=str(consumer)),
    ]
    transition = StateTransition(
        transition_id="transition:OrderState:TicketingPostActor:1",
        actor="TicketingPostActor",
        phase="post",
        from_states=["OCCUPY_SUCCESS"],
        to_states=["TICKETING"],
        source_ref=SourceReference(path=actor.name, symbol="TicketingPostActor", line=2),
    )
    return ScanManifest(
        scan_id="scan-generalized-test",
        system_id="demo-system",
        baseline=SourceBaseline(source_path=str(source), commit="generalized-test"),
        entries=entries,
        state_machines=[StateMachineDefinition(machine_id="state-machine:OrderState", system_id="demo-system", state_enum="OrderState", title="订单状态机", transitions=[transition])],
    )


def test_general_tracer_expands_facade_job_listener_and_actor(tmp_path: Path) -> None:
    """五类通用目标都应包含分支或副作用，不得回退浅层占位说明。"""

    source = tmp_path / "source"
    source.mkdir()
    manifest = _manifest(source)
    tracer = JavaKnowledgeTracer()

    for target_id in [entry.entry_id for entry in manifest.entries] + ["transition:OrderState:TicketingPostActor:1"]:
        batch = tracer.trace(manifest, target_id)
        assert batch.nodes
        assert all("深层业务关系尚待分析" not in node.summary for node in batch.nodes)
        assert all(node.source_refs and node.source_refs[0].line for node in batch.nodes)
        assert any("条件与分支" in content or "状态与副作用" in content for content in batch.content_by_node.values())


def test_preview_api_does_not_read_qa_or_create_run(tmp_path: Path) -> None:
    """自然语言预览必须只产出业务字段，确认前没有Run或QA读取副作用。"""

    knowledge_root = tmp_path / "knowledge"
    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(knowledge_root)
    application.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    node = KnowledgeNode(
        node_id="facade:TradeFacade#createOrder",
        system_id="demo-system",
        kind=KnowledgeNodeKind.FACADE,
        title="创建订单",
        summary="创建订单入口",
        status=KnowledgeStatus.USER_CONFIRMED,
        confidence=1,
    )
    application.store.write_node(node, "## 业务结论\n\n创建订单")
    client = TestClient(create_app(application))

    response = client.post(
        "/api/v2/systems/demo-system/natural-language-tests/previews",
        json={"text": "创建2个港币支付的多乘客订单，包含成人和儿童"},
    )

    assert response.status_code == 201
    preview = response.json()["preview"]
    assert preview["order_count"] == 2
    assert preview["status"] == "NEEDS_INPUT"
    assert all(resource_id.startswith("resource:demo-system:") for resource_id in preview["required_resource_ids"])
    assert any(item["key"].startswith("validation_capability:") for item in preview["missing_conditions"])
    assert {field["key"] for field in preview["fields"]} >= {"train_fixture", "passenger_fixture", "hk_quote_fixture"}
    assert "template_inputs" not in response.text
    assert not (knowledge_root / ".opentest" / "runs").exists()
    application.close()


def test_preview_resolves_current_system_resources_from_validation_capabilities(tmp_path: Path) -> None:
    """预览必须从当前系统校验目录解析资源，不能拼接booking.core固定系统ID。"""

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    store.write_node(
        KnowledgeNode(
            node_id="facade:TradeFacade#createOrder",
            system_id="demo-system",
            kind=KnowledgeNodeKind.FACADE,
            title="创建订单",
            status=KnowledgeStatus.USER_CONFIRMED,
        ),
        "## 业务结论\n\n创建订单",
    )
    from opentest.application.scenarios import ScenarioGenerationService

    capabilities = [
        ValidationCapabilityDefinition(
            capability_id=capability_id,
            resource_id=f"resource:demo-system:{kind}:database:{slug}",
            kind=kind,
            title=capability_id,
        )
        for capability_id, kind, slug in (
            ("order.primary_detail", "mysql", "primary"),
            ("order.items_by_transaction", "mysql", "primary"),
            ("order.tidb_projection", "tidb", "projection"),
            ("redis.order_done_status", "redis", "done-status"),
        )
    ]
    service = ScenarioGenerationService(store, validation_capability_provider=lambda _system_id: capabilities)

    preview = service.create_natural_language_preview(
        "demo-system",
        NaturalLanguageTestPreviewRequest(text="创建2个港币支付的多乘客订单，包含成人和儿童"),
    )

    assert preview.status == "NEEDS_INPUT"
    assert preview.required_resource_ids == [
        "resource:demo-system:mysql:database:primary",
        "resource:demo-system:tidb:database:projection",
        "resource:demo-system:redis:database:done-status",
    ]
    assert not preview.missing_conditions


def test_business_form_answers_update_constraints_before_materialization(tmp_path: Path) -> None:
    """币种和乘客表单答案必须进入最终约束，非法数量不能先READY再访问QA。"""

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    store.write_node(
        KnowledgeNode(
            node_id="facade:TradeFacade#createOrder",
            system_id="demo-system",
            kind=KnowledgeNodeKind.FACADE,
            title="创建订单",
            status=KnowledgeStatus.USER_CONFIRMED,
        ),
        "## 业务结论\n\n创建订单",
    )
    from opentest.application.scenarios import ScenarioGenerationService

    capabilities = [
        ValidationCapabilityDefinition(
            capability_id=capability_id,
            resource_id=f"resource:demo-system:{kind}:database:{slug}",
            kind=kind,
            title=capability_id,
        )
        for capability_id, kind, slug in (
            ("order.primary_detail", "mysql", "primary"),
            ("order.items_by_transaction", "mysql", "primary"),
            ("order.tidb_projection", "tidb", "projection"),
            ("redis.order_done_status", "redis", "done-status"),
        )
    ]
    service = ScenarioGenerationService(store, validation_capability_provider=lambda _system_id: capabilities)
    preview = service.create_natural_language_preview(
        "demo-system",
        NaturalLanguageTestPreviewRequest(text="创建订单"),
    )
    values = {
        "payment_type": "港币",
        "passenger_mix": "成人+儿童",
        "train_fixture": "train-a",
        "passenger_fixture": "passenger-a",
    }
    updated = service.update_natural_language_preview(
        "demo-system",
        preview.preview_id,
        NaturalLanguageTestPreviewUpdate(field_values=values),
    )

    assert updated.status == "NEEDS_INPUT"
    assert next(item.value for item in updated.constraints if item.field == "payment_type") == "HK_PAYMENT"
    assert next(item.value for item in updated.constraints if item.field == "child_count") == 1
    assert {field.key for field in updated.fields} == {"train_fixture", "passenger_fixture", "hk_quote_fixture"}
    with pytest.raises(KnowledgeValidationError, match="required"):
        service.update_natural_language_preview(
            "demo-system",
            updated.preview_id,
            NaturalLanguageTestPreviewUpdate(
                field_values={
                    "train_fixture": "train-a",
                    "passenger_fixture": "passenger-a",
                    "hk_quote_fixture": "",
                }
            ),
        )


def test_each_natural_language_preview_has_immutable_unique_identity(tmp_path: Path) -> None:
    """相同业务描述重复创建预览时不得覆盖已执行历史或长期Case关联。"""

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    store.write_node(
        KnowledgeNode(
            node_id="facade:TradeFacade#createOrder",
            system_id="demo-system",
            kind=KnowledgeNodeKind.FACADE,
            title="创建订单",
            status=KnowledgeStatus.USER_CONFIRMED,
        ),
        "## 业务结论\n\n创建订单",
    )
    from opentest.application.scenarios import ScenarioGenerationService

    service = ScenarioGenerationService(store)
    request = NaturalLanguageTestPreviewRequest(text="创建港币成人儿童订单")
    first = service.create_natural_language_preview("demo-system", request)
    second = service.create_natural_language_preview("demo-system", request)

    assert first.preview_id != second.preview_id
    assert first.semantic_digest == second.semantic_digest
    assert service.get_natural_language_preview("demo-system", first.preview_id).preview_id == first.preview_id


def test_blocked_preview_rejects_run_before_resource_probe(tmp_path: Path, monkeypatch) -> None:
    """预览仍缺业务条件或校验能力时必须在启动QA Worker前拒绝执行。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    application.store.write_node(
        KnowledgeNode(
            node_id="facade:TradeFacade#createOrder",
            system_id="demo-system",
            kind=KnowledgeNodeKind.FACADE,
            title="创建订单",
            status=KnowledgeStatus.USER_CONFIRMED,
        ),
        "## 业务结论\n\n创建订单",
    )
    preview = application.create_natural_language_preview(
        "demo-system",
        NaturalLanguageTestPreviewRequest(text="创建订单"),
    )

    def fail_if_probed(*_args: object, **_kwargs: object) -> list[object]:
        """若执行边界错误地先探测QA资源，则让测试立即失败。"""

        raise AssertionError("resource probe must not run for an incomplete preview")

    monkeypatch.setattr(application.resources, "probe", fail_if_probed)
    with pytest.raises(KnowledgeValidationError, match="not ready"):
        application.run_natural_language_preview(
            "demo-system",
            preview.preview_id,
            NaturalLanguageTestRunRequest(snapshot_id="snapshot:unused", confirmed=True),
        )
    application.close()


def test_natural_language_run_ignores_unrelated_failed_resource_history(tmp_path: Path, monkeypatch) -> None:
    """本次必需资源已连接时，无关资源的历史失败不得阻塞自然语言执行。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    required_resource_id = "resource:demo-system:mysql:database:primary"
    preview = NaturalLanguageTestPreview(
        preview_id="nl-preview-test",
        system_id="demo-system",
        original_text="创建人民币成人订单",
        status="READY",
        required_resource_ids=[required_resource_id],
    )
    monkeypatch.setattr(
        application.scenarios,
        "get_natural_language_preview",
        lambda _system_id, _preview_id: preview,
    )
    monkeypatch.setattr(
        application.resources,
        "probe",
        lambda _system_id, _environment, _resource_ids: [
            ResourceStateRecord(
                resource_id=required_resource_id,
                system_id="demo-system",
                connection_state=ResourceConnectionState.CONNECTED,
            ),
            ResourceStateRecord(
                resource_id="resource:demo-system:tidb:database:unrelated",
                system_id="demo-system",
                connection_state=ResourceConnectionState.FAILED,
                error_code="READ_POOL_UNAVAILABLE",
            ),
        ],
    )

    def prove_execution_reached_snapshot(_snapshot_id: str) -> object:
        """用稳定异常证明资源门禁已正确放行到Snapshot阶段。"""

        raise KnowledgeValidationError("snapshot stage reached")

    monkeypatch.setattr(application.snapshots, "get", prove_execution_reached_snapshot)
    with pytest.raises(KnowledgeValidationError, match="snapshot stage reached"):
        application.run_natural_language_preview(
            "demo-system",
            preview.preview_id,
            NaturalLanguageTestRunRequest(snapshot_id="snapshot:unused", confirmed=True),
        )
    application.close()


def test_open_high_questions_block_draft_publication_until_all_are_answered(tmp_path: Path) -> None:
    """同一节点任一高影响问题未回答时都不能升级为人工确认知识。"""

    source = tmp_path / "source"
    source.mkdir()
    manifest = _manifest(source)
    knowledge_root = tmp_path / "knowledge"
    application = OpenTestApplication(knowledge_root)
    application.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    manifest = manifest.model_copy(update={"baseline": application.knowledge.git_repository.capture(source)})
    artifacts = SourceScanArtifactStore(knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest("demo-system", manifest.scan_id)
    application.store.update_source_baseline("demo-system", manifest.baseline)
    application.skip_background_interview("demo-system")
    batch = application.knowledge.generate_drafts(
        KnowledgeGenerationBatchRequest(
            system_id="demo-system",
            target_ids=["job:demo.TimeoutJob"],
            scan_id=manifest.scan_id,
            use_agent=False,
        )
    )
    second_question = KnowledgeQuestion(
        question_id="question:second-business-boundary",
        system_id="demo-system",
        title="确认失败边界",
        detail="请补充该Job失败后的人工处理边界。",
        affected_node_ids=[batch.drafts[0].node.node_id],
        impact="high",
    )
    batch = batch.model_copy(update={"questions": [*batch.questions, second_question]})
    application.store.write_draft_batch(batch)
    selected = batch.drafts[0]

    with pytest.raises(KnowledgeValidationError, match="open confirmation questions"):
        application.knowledge.publish_drafts(
            "demo-system",
            batch.batch_id,
            KnowledgeDraftConfirmation(draft_ids=[selected.draft_id]),
        )
    answered = application.knowledge.answer_draft_question(
        "demo-system",
        batch.batch_id,
        KnowledgeConfirmation(
            question_id=batch.questions[0].question_id,
            answer="用于处理过期订单并触发驳回",
            confirmed_node_ids=batch.questions[0].affected_node_ids,
        ),
    )
    current_draft = next(draft for draft in answered.drafts if draft.draft_id == selected.draft_id)
    assert current_draft.status == "HAS_QUESTIONS"
    with pytest.raises(KnowledgeValidationError, match="open confirmation questions"):
        application.knowledge.publish_drafts(
            "demo-system",
            batch.batch_id,
            KnowledgeDraftConfirmation(draft_ids=[selected.draft_id]),
        )
    application.knowledge.answer_draft_question(
        "demo-system",
        batch.batch_id,
        KnowledgeConfirmation(
            question_id=second_question.question_id,
            answer="失败后由运营人工复核，不自动重试",
            confirmed_node_ids=second_question.affected_node_ids,
        ),
    )
    published = application.knowledge.publish_drafts(
        "demo-system",
        batch.batch_id,
        KnowledgeDraftConfirmation(draft_ids=[selected.draft_id]),
    )

    assert any(draft.status == "CONFIRMED" for draft in published.drafts)
    application.close()


def test_tracer_cache_is_invalidated_between_scan_batches(tmp_path: Path) -> None:
    """修改源码并新增Java类后重新追踪必须读取新正文和新文件索引。"""

    source = tmp_path / "source"
    source.mkdir()
    manifest = _manifest(source)
    tracer = JavaKnowledgeTracer()
    first = tracer.trace(manifest, "facade:demo.OtherFacade#query")
    implementation = source / "OtherFacadeImpl.java"
    implementation.write_text(
        """package demo;
class OtherFacadeImpl {
  Result query(Request request) {
    if (request.enabled()) { return secondService.load(request.types()); }
    return Result.empty();
  }
}""",
        encoding="utf-8",
    )
    helper = source / "QueryValidator.java"
    helper.write_text("package demo; class QueryValidator { void validate() { if (true) { auditService.save(); } } }", encoding="utf-8")
    second = tracer.trace(manifest.model_copy(update={"scan_id": "scan-generalized-test-2"}), "facade:demo.OtherFacade#query")

    assert "customService.list" in "\n".join(first.content_by_node.values())
    assert "secondService.load" in "\n".join(second.content_by_node.values())
    assert tracer._find_optional_java(source, "QueryValidator.java") == helper.resolve()


def test_custom_case_digest_is_unchanged_by_generation_records(tmp_path: Path) -> None:
    """矩阵记录写入generated目录时不得改动人工Case内容或身份。"""

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    custom = store.system_root("demo-system") / "cases" / "custom" / "manual.yaml"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("variant_id: custom:stable\ntitle: 人工维护\n", encoding="utf-8")
    before = hashlib.sha256(custom.read_bytes()).hexdigest()

    from opentest.adapters.case_store import GitCaseStore
    from opentest.domain.models import CaseGenerationRecord, CaseGenerationStatus

    case_store = GitCaseStore(store)
    case_store.write_generation_record(
        CaseGenerationRecord(
            generation_id="case-generation-test",
            system_id="demo-system",
            entry_node_id="facade:demo.OtherFacade#query",
            status=CaseGenerationStatus.MATRIX_DRAFT,
        )
    )

    assert hashlib.sha256(custom.read_bytes()).hexdigest() == before


def test_non_create_order_matrix_stays_blocked_before_specialized_generator(tmp_path: Path) -> None:
    """通用入口可展示保守矩阵，但缺少自包含步骤生成能力时不得误调用createOrder生成器。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    node = KnowledgeNode(
        node_id="facade:demo.OtherFacade#query",
        system_id="demo-system",
        kind=KnowledgeNodeKind.FACADE,
        title="查询自定义内容",
        summary="按业务条件查询自定义内容",
        status=KnowledgeStatus.USER_CONFIRMED,
        confidence=1,
    )
    application.store.write_node(node, "## 业务结论\n\n查询自定义内容")
    from opentest.domain.models import CaseGenerationCreateRequest, CaseGenerationStatus

    record = application.create_case_generation(
        "demo-system",
        CaseGenerationCreateRequest(entry_node_id=node.node_id),
    )

    assert record.status == CaseGenerationStatus.BLOCKED
    assert record.matrix_items
    assert any(item.key == "entry_case_generator" for item in record.missing_conditions)
    application.close()


def test_user_regression_case_is_persisted_without_overwriting_custom_case(tmp_path: Path) -> None:
    """自然语言执行选择长期保存时应创建Git Case资产并保持人工目录不变。"""

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    custom = store.system_root("demo-system") / "cases" / "custom" / "manual.yaml"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("variant_id: custom:stable\ntitle: 人工维护\n", encoding="utf-8")
    before = hashlib.sha256(custom.read_bytes()).hexdigest()
    from opentest.adapters.case_store import GitCaseStore
    from opentest.domain.models import UserRegressionCase

    case_store = GitCaseStore(store)
    user_case = UserRegressionCase(
        case_id="user-case:nl-001",
        system_id="demo-system",
        title="自然语言回归：港币成人儿童订单",
        business_description="创建港币成人儿童订单",
        source_preview_id="nl-001",
        source_snapshot_id="snapshot-001",
        source_knowledge_digest="knowledge-digest",
        source_case_digest="case-digest",
        entry_node_id="facade:TradeFacade#createOrder",
        business_field_values={"train_fixture": "qa-train-a"},
        variant_ids=["variant:nl-001"],
        run_ids=["run-001"],
    )

    path = case_store.write_user_regression_case(user_case)

    assert path.is_file()
    assert case_store.list_user_regression_cases("demo-system") == [user_case]
    assert hashlib.sha256(custom.read_bytes()).hexdigest() == before

    repeated = user_case.model_copy(update={"run_ids": ["run-002"]})
    case_store.write_user_regression_case(repeated)
    saved = case_store.list_user_regression_cases("demo-system")
    assert len(saved) == 1
    assert saved[0].run_ids == ["run-001", "run-002"]


def test_draft_batch_survives_unavailable_agent_without_publishing(tmp_path: Path) -> None:
    """Agent不可用时应保留确定性草稿和阻塞说明，且不会提前写入知识真相。"""

    source = tmp_path / "source"
    source.mkdir()
    manifest = _manifest(source)
    knowledge_root = tmp_path / "knowledge"
    application = OpenTestApplication(knowledge_root)
    application.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    manifest = manifest.model_copy(update={"baseline": application.knowledge.git_repository.capture(source)})
    artifacts = SourceScanArtifactStore(knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest("demo-system", manifest.scan_id)
    application.store.update_source_baseline("demo-system", manifest.baseline)
    application.skip_background_interview("demo-system")

    from opentest.domain.models import KnowledgeGenerationBatchRequest

    batch = application.knowledge.generate_drafts(
        KnowledgeGenerationBatchRequest(
            system_id="demo-system",
            target_ids=["job:demo.TimeoutJob"],
            scan_id=manifest.scan_id,
        ),
        runner=_UnavailableAgentRunner(),
    )

    assert batch.drafts
    assert batch.agent.selected_agent is None
    assert "均不可用" in batch.agent.blocked_reason
    assert application.store.list_nodes("demo-system") == []
    application.close()


def test_agent_prompt_excludes_sensitive_inputs_and_invalid_output_is_not_adopted(tmp_path: Path) -> None:
    """Agent只接收源码证据；非法JSON不能进入草稿正文或阻断确定性生成。"""

    source = tmp_path / "source"
    source.mkdir()
    manifest = _manifest(source)
    knowledge_root = tmp_path / "knowledge"
    application = OpenTestApplication(knowledge_root)
    application.register_system(SystemDefinition(system_id="demo-system", name="演示系统", source_path=str(source)))
    manifest = manifest.model_copy(update={"baseline": application.knowledge.git_repository.capture(source)})
    artifacts = SourceScanArtifactStore(knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest("demo-system", manifest.scan_id)
    application.store.update_source_baseline("demo-system", manifest.baseline)
    application.skip_background_interview("demo-system")
    runner = _InvalidOutputAgentRunner(tmp_path / "unused")

    from opentest.domain.models import KnowledgeGenerationBatchRequest

    batch = application.knowledge.generate_drafts(
        KnowledgeGenerationBatchRequest(
            system_id="demo-system",
            target_ids=["job:demo.TimeoutJob"],
            scan_id=manifest.scan_id,
        ),
        runner=runner,
    )

    assert batch.drafts
    assert all("not-json" not in draft.content for draft in batch.drafts)
    assert "Agent增强未采用" in batch.agent.blocked_reason
    for forbidden in ("qa_labrador_token", "OPENTEST_QA_LABRADOR_TOKEN", "fixtures", ".opentest/environments"):
        assert forbidden not in runner.prompt
    application.close()
