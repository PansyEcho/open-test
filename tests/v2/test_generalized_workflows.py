"""验证通用知识追踪、草稿确认和 Agent 安全边界。"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentest.adapters.knowledge_tracing import JavaKnowledgeTracer
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeDraftConfirmation,
    KnowledgeConfirmation,
    KnowledgeGenerationBatchRequest,
    KnowledgeQuestion,
    ScanManifest,
    SourceBaseline,
    SystemDefinition,
)


class _UnavailableAgentRunner:
    """模拟本地Agent均不可用，验证提交前门禁。"""

    def availability(self) -> tuple[bool, bool]:
        """返回两个Agent均不可用的固定检测结果。"""

        return False, False

    def is_available(self, agent: str) -> bool:
        """任一显式Agent选择都不可用。"""

        del agent
        return False


class _InvalidOutputAgentRunner:
    """模拟Agent返回非法输出，并检查提示中没有本地敏感输入。"""

    def __init__(self, output_path: Path):
        """绑定测试专用本地输出路径。"""

        self.output_path = output_path
        self.prompt = ""

    def availability(self) -> tuple[bool, bool]:
        """声明Codex可用以触发增强路径。"""

        return True, False

    def is_available(self, agent: str) -> bool:
        """仅允许测试明确选择Codex。"""

        return agent == "codex"

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
class OtherFacadeImpl implements OtherFacade {
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
            agent="codex",
            confirmed=True,
        ),
        runner=_InvalidOutputAgentRunner(tmp_path / "open-question-output"),
    )
    first_question = KnowledgeQuestion(
        question_id="question:first-business-boundary",
        system_id="demo-system",
        title="确认过期任务用途",
        detail="请补充该Job处理的业务对象。",
        affected_node_ids=[batch.drafts[0].node.node_id],
        impact="high",
    )
    second_question = KnowledgeQuestion(
        question_id="question:second-business-boundary",
        system_id="demo-system",
        title="确认失败边界",
        detail="请补充该Job失败后的人工处理边界。",
        affected_node_ids=[batch.drafts[0].node.node_id],
        impact="high",
    )
    batch = batch.model_copy(update={"questions": [first_question, second_question], "status": "PENDING_CONFIRMATION"})
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
class OtherFacadeImpl implements OtherFacade {
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


def test_unavailable_selected_agent_blocks_before_generation(tmp_path: Path) -> None:
    """用户选择的Agent不可用时应在目标追踪与知识写入前阻止生成。"""

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

    with pytest.raises(KnowledgeValidationError, match="当前不可用"):
        application.knowledge.generate_drafts(
            KnowledgeGenerationBatchRequest(
                system_id="demo-system",
                target_ids=["job:demo.TimeoutJob"],
                scan_id=manifest.scan_id,
                agent="codex",
                confirmed=True,
            ),
            runner=_UnavailableAgentRunner(),
        )

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
            agent="codex",
            confirmed=True,
        ),
        runner=runner,
    )

    assert batch.drafts
    assert all("not-json" not in draft.content for draft in batch.drafts)
    assert batch.agent.selected_agent == "codex"
    assert batch.outcomes[0].status.value == "CODE_ONLY"
    assert "指定Agent分析失败" in batch.outcomes[0].safe_error
    assert {node.status.value for node, _, _ in application.store.list_nodes("demo-system")} == {"code_verified"}
    for forbidden in ("qa_labrador_token", "OPENTEST_QA_LABRADOR_TOKEN", "fixtures", ".opentest/environments"):
        assert forbidden not in runner.prompt
    application.close()
