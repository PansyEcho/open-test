"""验证系统专属知识候选、统一问题、目标详情与持久化长任务进度。"""

from __future__ import annotations

import time
import json
from pathlib import Path

import pytest

from opentest.adapters.knowledge_interview import KnowledgeInterviewStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.knowledge_tracing import JavaKnowledgeTracer
from opentest.application.knowledge_discovery import KnowledgeDiscoveryService
from opentest.application.knowledge_context import legacy_knowledge_context_digest
from opentest.application.tasks import LocalTaskManager, TaskProgressReporter, report_task_progress, report_task_warning
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeContextCandidateStatus,
    KnowledgeContextCandidateCreate,
    KnowledgeContextCandidateUpdate,
    KnowledgeContextNarrativeUpdate,
    KnowledgeDraft,
    KnowledgeGenerationWorkflowBatch,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeQuestion,
    KnowledgeStatus,
    KnowledgeTarget,
    KnowledgeTargetStatus,
    ScanCatalog,
    ScanManifest,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
    TaskProgressUpdate,
    TaskRecord,
    TaskStatus,
    TaskWarning,
    utc_now,
)


class _EnvelopeAgentRunner:
    """返回指定严格JSON信封，用于验证Agent系统与源码范围门禁。"""

    def __init__(self, payload: dict[str, object]):
        """保存测试输出，不读取任何源码、Token或QA配置。"""

        self.payload = payload

    def availability(self) -> tuple[bool, bool]:
        """声明只有用户选择的Codex可用。"""

        return True, False

    def is_available(self, agent: str) -> bool:
        """只允许测试请求中明确选择Codex。"""

        return agent == "codex"

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """把预设信封写入允许的本地证据目录并返回路径。"""

        del request, source_root
        output_root = evidence_root / "agent-scope-test"
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / "output.txt"
        output_path.write_text(json.dumps(self.payload), encoding="utf-8")
        from types import SimpleNamespace

        return SimpleNamespace(output_path=str(output_path))


def _registered_store(tmp_path: Path, system_id: str = "refund.core") -> tuple[GitKnowledgeStore, Path]:
    """构造已经注册Java源码目录的隔离知识真相源。

    Args:
        tmp_path: Pytest隔离目录。
        system_id: 本次测试系统ID。

    Returns:
        Git知识存储与已创建的源码根。
    """

    source_root = tmp_path / system_id
    source_root.mkdir(parents=True)
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id=system_id, name=system_id, source_path=str(source_root)))
    return store, source_root


def _manifest(system_id: str, source_root: Path, source_file: Path) -> ScanManifest:
    """构造包含一个退款Facade入口的最小真实扫描Manifest。"""

    entry = EntryPoint(
        entry_id=f"facade:demo.RefundFacade#createRefund",
        system_id=system_id,
        kind=KnowledgeNodeKind.FACADE,
        display_name="RefundFacade#createRefund",
        source_id="demo.RefundFacade#createRefund",
        source_path=str(source_file),
        request_type="CreateRefundRequest",
        response_type="CreateRefundResponse",
    )
    return ScanManifest(
        scan_id="scan-refund-1",
        system_id=system_id,
        baseline=SourceBaseline(source_path=str(source_root), commit="abc123"),
        entries=[entry],
    )


def test_discovery_is_system_specific_and_preserves_answer_on_rescan(tmp_path: Path) -> None:
    """退款源码应只产生退款候选，重扫后必须保留人工含义。"""

    store, source_root = _registered_store(tmp_path)
    source_file = source_root / "RefundFacade.java"
    source_file.write_text(
        "package demo; public interface RefundFacade { CreateRefundResponse createRefund(CreateRefundRequest r); }",
        encoding="utf-8",
    )
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))
    envelope = service.discover(_manifest("refund.core", source_root, source_file))

    names = {candidate.name for candidate in envelope.candidates if candidate.status != KnowledgeContextCandidateStatus.STALE}
    assert "CreateRefundRequest" not in names
    assert not names.intersection({"EBK", "HT", "票机", "收单"})
    manual = service.create_candidate(
        "refund.core",
        KnowledgeContextCandidateCreate(
            kind="BUSINESS_TERM",
            name="退票单",
            business_meaning="乘客针对原客票发起退款的业务单",
        ),
    )
    service.discover(_manifest("refund.core", source_root, source_file))
    current = next(item for item in service.get_context("refund.core").candidates if item.candidate_id == manual.candidate_id)
    assert current.business_meaning == "乘客针对原客票发起退款的业务单"
    assert current.status == KnowledgeContextCandidateStatus.CONFIRMED


def test_discovery_rejects_source_evidence_outside_registered_system(tmp_path: Path) -> None:
    """Manifest引用其他源码根时不得把候选写入当前系统。"""

    store, source_root = _registered_store(tmp_path)
    outside = tmp_path / "outside.java"
    outside.write_text("public enum RefundOrderStateEnum { CREATED }", encoding="utf-8")
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))

    with pytest.raises(ScopeViolationError):
        service.discover(_manifest("refund.core", source_root, outside))

    assert service.get_context("refund.core").candidates == []


def test_discovery_skips_java_symlink_escaping_registered_source(tmp_path: Path) -> None:
    """自动候选发现不得通过Java符号链接读取注册源码根外的应用名称。"""

    store, source_root = _registered_store(tmp_path)
    source_dir = source_root / "app" / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    facade_file = source_dir / "RefundFacade.java"
    facade_file.write_text(
        "package demo; interface RefundFacade { void createRefund(Request request); }",
        encoding="utf-8",
    )
    outside = tmp_path / "ExternalClient.java"
    outside.write_text("package secret; interface SecretGateway { void send(); }", encoding="utf-8")
    (source_dir / "ExternalClient.java").symlink_to(outside)
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))

    envelope = service.discover(_manifest("refund.core", source_root, facade_file))

    assert "SecretGateway" not in {candidate.name for candidate in envelope.candidates}


def test_discovery_external_application_evidence_points_to_actual_source_file(tmp_path: Path) -> None:
    """外部应用影响关系可经实现闭包传播，但证据路径和行号必须属于真实命中文件。"""

    store, source_root = _registered_store(tmp_path)
    source_dir = source_root / "app" / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    facade_file = source_dir / "RefundFacade.java"
    facade_file.write_text(
        "package demo; interface RefundFacade { void createRefund(Request request); }",
        encoding="utf-8",
    )
    implementation_file = source_dir / "RefundFacadeImpl.java"
    implementation_file.write_text(
        "package demo;\nclass RefundFacadeImpl implements RefundFacade {\n"
        "  WalletClient walletClient;\n  public void createRefund(Request request) { walletClient.refund(); }\n}",
        encoding="utf-8",
    )
    client_file = source_dir / "WalletClient.java"
    client_file.write_text("package demo; interface WalletClient { void refund(); }", encoding="utf-8")
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))

    envelope = service.discover(_manifest("refund.core", source_root, facade_file))
    candidate = next(item for item in envelope.candidates if item.name == "WalletClient")

    assert candidate.affected_target_ids == ["facade:demo.RefundFacade#createRefund"]
    assert {reference.path for reference in candidate.source_refs} == {
        "app/src/main/java/demo/RefundFacadeImpl.java"
    }
    assert all(reference.line and reference.line <= 5 for reference in candidate.source_refs)


def test_discovery_rescan_marks_changed_and_missing_candidates_without_losing_meaning(tmp_path: Path) -> None:
    """重扫时证据变化应待复核、候选消失应陈旧，人工含义不得丢失。"""

    store, source_root = _registered_store(tmp_path)
    source_dir = source_root / "app" / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "RefundFacade.java"
    term_file = source_dir / "RefundOrderStateEnum.java"
    source_file.write_text(
        "package demo; interface RefundFacade { RefundOrderStateEnum createRefund(Request r); }",
        encoding="utf-8",
    )
    term_file.write_text("package demo; enum RefundOrderStateEnum { CREATED }", encoding="utf-8")
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))
    manifest = _manifest("refund.core", source_root, source_file)
    first = service.discover(manifest)
    candidate = next(item for item in first.candidates if item.name == "RefundOrderStateEnum")
    service.update_candidate(
        "refund.core",
        candidate.candidate_id,
        KnowledgeContextCandidateUpdate(
            status="CONFIRMED",
            business_meaning="退票单从申请到完成的状态定义",
        ),
    )

    term_file.write_text("package demo; enum RefundOrderStateEnum { CREATED, PROCESSING }", encoding="utf-8")
    changed = service.discover(manifest.model_copy(update={"scan_id": "scan-refund-2"}))
    reviewed = next(item for item in changed.candidates if item.candidate_id == candidate.candidate_id)
    assert reviewed.status == KnowledgeContextCandidateStatus.NEEDS_REVIEW
    assert reviewed.business_meaning == "退票单从申请到完成的状态定义"

    term_file.unlink()
    missing = service.discover(manifest.model_copy(update={"scan_id": "scan-refund-3"}))
    stale = next(item for item in missing.candidates if item.candidate_id == candidate.candidate_id)
    assert stale.status == KnowledgeContextCandidateStatus.STALE
    assert stale.business_meaning == "退票单从申请到完成的状态定义"


def test_context_candidates_and_answers_are_isolated_between_two_systems(tmp_path: Path) -> None:
    """两个系统的叙述、候选和人工答案必须落在各自Git目录且完全隔离。"""

    store, _ = _registered_store(tmp_path, "refund.core")
    order_root = tmp_path / "order.core"
    order_root.mkdir()
    store.register_system(SystemDefinition(system_id="order.core", name="order.core", source_path=str(order_root)))
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))
    service.save_narrative(
        "refund.core",
        KnowledgeContextNarrativeUpdate(system_purpose="退款", upstream_entry_narrative="交易系统调用退款入口"),
    )
    refund_candidate = service.create_candidate(
        "refund.core",
        KnowledgeContextCandidateCreate(kind="BUSINESS_TERM", name="退票单", business_meaning="退款业务单"),
    )
    order_candidate = service.create_candidate(
        "order.core",
        KnowledgeContextCandidateCreate(kind="BUSINESS_TERM", name="预订单", business_meaning="下单业务单"),
    )

    refund = service.get_context("refund.core")
    order = service.get_context("order.core")
    assert refund.system_purpose == "退款"
    assert order.system_purpose == ""
    assert {item.candidate_id for item in refund.candidates} == {refund_candidate.candidate_id}
    assert {item.candidate_id for item in order.candidates} == {order_candidate.candidate_id}
    assert all(question.system_id == "refund.core" for question in service.list_questions("refund.core"))
    assert all(question.system_id == "order.core" for question in service.list_questions("order.core"))
    assert list((store.system_root("refund.core") / "references" / "terms").glob("*.yaml"))
    assert list((store.system_root("order.core") / "references" / "terms").glob("*.yaml"))


def test_unified_questions_include_old_draft_question(tmp_path: Path) -> None:
    """旧草稿高影响问题应保留，而通用背景题不再进入待确认周期。

    Args:
        tmp_path: pytest隔离的知识库和草稿目录。

    Returns:
        None；通过唯一开放问题的来源断言验证旧草稿兼容与新策略。
    """

    store, _ = _registered_store(tmp_path)
    question = KnowledgeQuestion(
        question_id="question:refund-meaning",
        system_id="refund.core",
        title="确认退票查询口径",
        detail="请说明查询入口的业务使用方。",
        affected_node_ids=["entry:demo.RefundFacade#queryList"],
    )
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#queryList",
        system_id="refund.core",
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#queryList",
        status=KnowledgeStatus.INFERRED,
    )
    store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-refund",
            system_id="refund.core",
            scan_id="scan-old",
            target_ids=["facade:demo.RefundFacade#queryList"],
            status="PENDING_CONFIRMATION",
            drafts=[
                KnowledgeDraft(
                    draft_id="draft-refund",
                    system_id="refund.core",
                    target_id="facade:demo.RefundFacade#queryList",
                    node=node,
                    content="旧草稿",
                    status="HAS_QUESTIONS",
                )
            ],
            questions=[question],
        )
    )
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))

    questions = service.list_questions("refund.core")

    assert any(item.question_id == question.question_id and item.source == "draft" for item in questions)
    assert sum(item.status == "open" for item in questions) == 1


def test_target_detail_returns_only_selected_target_context(tmp_path: Path) -> None:
    """点击知识叶子应加载对应草稿和问题，且不会自动生成新草稿。"""

    store, _ = _registered_store(tmp_path)
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#queryList",
        system_id="refund.core",
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#queryList",
        status=KnowledgeStatus.INFERRED,
    )
    draft = KnowledgeDraft(
        draft_id="draft-refund",
        system_id="refund.core",
        target_id="facade:demo.RefundFacade#queryList",
        node=node,
        content="退款列表查询草稿",
        status="DRAFT",
    )
    store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-refund",
            system_id="refund.core",
            scan_id="scan-refund-1",
            target_ids=[draft.target_id],
            status="PENDING_CONFIRMATION",
            drafts=[draft],
        )
    )
    target = KnowledgeTarget(
        target_id=draft.target_id,
        category="facade",
        group="RefundFacade",
        display_name="RefundFacade#queryList",
        knowledge_status=KnowledgeTargetStatus.PENDING_CONFIRMATION,
        source_refs=[SourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#queryList")],
    )
    catalog = ScanCatalog(
        scan_id="scan-refund-1",
        system_id="refund.core",
        generated_at=utc_now(),
        targets=[target],
    )
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))

    detail = service.target_detail("refund.core", target.target_id, catalog)

    assert detail.breadcrumb == ["Facade", "RefundFacade", "RefundFacade#queryList"]
    assert detail.latest_drafts[0].content == "退款列表查询草稿"
    assert len(store.list_draft_batches("refund.core")) == 1


def test_target_detail_light_mode_skips_global_questions_and_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三栏页轻量详情不得读取问题全集或完整背景，并保持小响应。

    Args:
        tmp_path: pytest隔离的知识仓库目录。
        monkeypatch: 把禁止执行的全量查询替换为立即失败的守卫。

    Returns:
        None；通过守卫未触发、字段为空和序列化体积断言验证轻量路径。
    """

    store, _ = _registered_store(tmp_path)
    target = KnowledgeTarget(
        target_id="facade:demo.RefundFacade#queryList",
        category="facade",
        group="RefundFacade",
        display_name="RefundFacade#queryList",
        source_refs=[SourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#queryList")],
    )
    catalog = ScanCatalog(
        scan_id="scan-refund-1",
        system_id="refund.core",
        generated_at=utc_now(),
        targets=[target],
    )
    service = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))

    def reject_full_query(*_args: object, **_kwargs: object) -> None:
        """在轻量路径意外读取全量问题或上下文时立即终止测试。"""

        raise AssertionError("light target detail executed a full knowledge query")

    monkeypatch.setattr(service, "list_questions", reject_full_query)
    monkeypatch.setattr(service, "get_context", reject_full_query)

    detail = service.target_detail(
        "refund.core",
        target.target_id,
        catalog,
        include_questions=False,
        include_context=False,
    )

    assert detail.questions == []
    assert detail.related_terms == []
    assert detail.related_enums == []
    assert detail.background_context is None
    assert len(detail.model_dump_json().encode("utf-8")) < 60 * 1024


def test_target_detail_marks_draft_without_system_context_digest_as_legacy(tmp_path: Path) -> None:
    """新流程前生成且未绑定系统上下文摘要的旧草稿必须提示重新生成。"""

    store, _ = _registered_store(tmp_path)
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#queryList",
        system_id="refund.core",
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#queryList",
    )
    draft = KnowledgeDraft(
        draft_id="draft-old",
        system_id="refund.core",
        target_id="facade:demo.RefundFacade#queryList",
        node=node,
        content="旧草稿",
    )
    store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-old",
            system_id="refund.core",
            scan_id="scan-refund-1",
            target_ids=[draft.target_id],
            status="PENDING_CONFIRMATION",
            drafts=[draft],
        )
    )
    target = KnowledgeTarget(
        target_id=draft.target_id,
        category="facade",
        group="RefundFacade",
        display_name="RefundFacade#queryList",
    )
    catalog = ScanCatalog(
        scan_id="scan-refund-1",
        system_id="refund.core",
        generated_at=utc_now(),
        targets=[target],
    )

    detail = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest")).target_detail(
        "refund.core",
        target.target_id,
        catalog,
    )

    assert detail.legacy_version is True


def test_target_detail_accepts_pre_upgrade_generation_context_digest(tmp_path: Path) -> None:
    """升级前生成摘要仍匹配当前背景时不得把有效知识误标为旧版本。

    Args:
        tmp_path: pytest隔离的旧批次和知识上下文目录。

    Returns:
        None；旧生成契约摘要通过兼容比较时验证成功。
    """

    store, _ = _registered_store(tmp_path)
    target_id = "facade:demo.RefundFacade#queryList"
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#queryList",
        system_id="refund.core",
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#queryList",
    )
    store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-compatible-digest",
            system_id="refund.core",
            scan_id="scan-refund-1",
            target_ids=[target_id],
            status="PENDING_CONFIRMATION",
            context_digest=legacy_knowledge_context_digest(store.read_context("refund.core")),
            drafts=[
                KnowledgeDraft(
                    draft_id="draft-compatible-digest",
                    system_id="refund.core",
                    target_id=target_id,
                    node=node,
                    content="升级前已生成知识",
                )
            ],
        )
    )
    target = KnowledgeTarget(
        target_id=target_id,
        category="facade",
        group="RefundFacade",
        display_name="RefundFacade#queryList",
    )
    catalog = ScanCatalog(
        scan_id="scan-refund-1",
        system_id="refund.core",
        generated_at=utc_now(),
        targets=[target],
    )

    detail = KnowledgeDiscoveryService(
        store,
        KnowledgeInterviewStore(store.root / ".opentest"),
    ).target_detail("refund.core", target_id, catalog)

    assert detail.legacy_version is False


def test_task_progress_persists_stage_items_warnings_and_terminal_state(tmp_path: Path) -> None:
    """长任务进度应在刷新读取后保留真实阶段、当前项和安全警告。"""

    manager = LocalTaskManager(tmp_path / "tasks", max_workers=1)

    def progress_job() -> dict[str, object]:
        """模拟两个知识目标中的第一个处理阶段并返回安全摘要。"""

        report_task_progress(
            TaskProgressUpdate(
                stage_code="knowledge_trace",
                stage_name="分析源码业务逻辑",
                stage_index=1,
                stage_total=2,
                completed_units=1,
                total_units=2,
                current_item="RefundFacade#queryList",
                message="剩余问题 0，已知未知 0",
            )
        )
        report_task_warning(TaskWarning(code="AGENT_UNAVAILABLE", message="已保留确定性草稿", retryable=True))
        return {"draft_count": 1}

    task = manager.submit("knowledge-draft-batch", "refund.core", progress_job, exclusive=True)
    for _ in range(100):
        current = manager.get(task.task_id)
        if current.status == TaskStatus.COMPLETED:
            break
        time.sleep(0.01)
    manager.close()

    assert current.progress is not None
    assert current.progress.status == TaskStatus.COMPLETED
    assert current.progress.total_units == 2
    assert current.progress.completed_units == 2
    assert current.progress.message == "剩余问题 0，已知未知 0"
    assert current.progress.warnings[0].code == "AGENT_UNAVAILABLE"


@pytest.mark.parametrize(
    "update",
    [
        TaskProgressUpdate(
            stage_code="knowledge_trace",
            stage_name="分析源码",
            stage_index=1,
            stage_total=1,
            completed_units=2,
            total_units=1,
        ),
        TaskProgressUpdate(
            stage_code="knowledge_trace",
            stage_name="分析源码",
            stage_index=2,
            stage_total=1,
        ),
    ],
)
def test_task_progress_reporter_rejects_inconsistent_counts(
    tmp_path: Path,
    update: TaskProgressUpdate,
) -> None:
    """进度完成量或阶段序号越界时必须返回稳定领域异常而不是NameError。"""

    manager = LocalTaskManager(tmp_path / "tasks", max_workers=1)
    record = TaskRecord(task_id="task-progress-invalid", operation="knowledge", trace_id="trace")
    reporter = TaskProgressReporter(manager, record)

    with pytest.raises(KnowledgeValidationError):
        reporter.update(update)
    manager.close()


def test_scan_manifest_can_complete_with_retryable_discovery_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Manifest发布后的发现失败只能形成警告，不得把扫描任务改成失败。"""

    from opentest.application.foundation import OpenTestApplication
    from opentest.domain.models import SourceScanRequest

    application = OpenTestApplication(tmp_path / "knowledge")
    source_root = tmp_path / "refund-source"
    source_root.mkdir()
    application.register_system(SystemDefinition(system_id="refund.core", name="退款", source_path=str(source_root)))
    source_file = source_root / "RefundFacade.java"
    source_file.write_text("package demo; interface RefundFacade { void createRefund(Request r); }", encoding="utf-8")
    manifest = _manifest("refund.core", source_root, source_file)
    application.source_analysis.scriptgen = object()
    monkeypatch.setattr(application.source_analysis, "analyze", lambda _request: manifest)

    def blocked_discovery(*_args: object, **_kwargs: object) -> object:
        """模拟发现阶段在Manifest发布后发生可恢复故障。"""

        raise ValueError("local analysis unavailable")

    monkeypatch.setattr(application.knowledge_discovery, "discover", blocked_discovery)
    task = application.submit_source_scan(
        SourceScanRequest(
            system_id="refund.core",
            facade_http_prefix="http://servicegw.qa.ly.com/gateway/refund/v2",
        )
    )
    for _ in range(100):
        current = application.get_task(task.task_id)
        if current.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            break
        time.sleep(0.01)
    application.close()

    assert current.status == TaskStatus.COMPLETED
    assert current.result["scan_id"] == manifest.scan_id
    assert current.progress is not None
    assert current.progress.warnings[0].code == "KNOWLEDGE_DISCOVERY_BLOCKED"


def test_same_named_create_order_uses_general_tracer_outside_booking_core(tmp_path: Path) -> None:
    """普通系统同名TradeFacade#createOrder不得进入Booking.Core专用追踪。"""

    source_root = tmp_path / "other.core"
    source_root.mkdir()
    source_file = source_root / "TradeFacade.java"
    source_file.write_text(
        "package demo; public interface TradeFacade { Result createOrder(Request request); }",
        encoding="utf-8",
    )
    manifest = ScanManifest(
        scan_id="scan-other",
        system_id="other.core",
        baseline=SourceBaseline(source_path=str(source_root)),
        entries=[
            EntryPoint(
                entry_id="facade:demo.TradeFacade#createOrder",
                system_id="other.core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="TradeFacade#createOrder",
                source_id="demo.TradeFacade#createOrder",
                source_path=str(source_file),
            )
        ],
    )

    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)

    assert batch.nodes[0].metadata["analysis_depth"] == "business"
    assert all("hk-payment" not in node.node_id for node in batch.nodes)
    assert all("EBK" not in content for content in batch.content_by_node.values())


def test_general_tracer_skips_java_symlink_escaping_registered_source(tmp_path: Path) -> None:
    """通用追踪不得把源码根外符号链接中的下游调用写入当前系统知识。"""

    source_root = tmp_path / "other.core"
    source_dir = source_root / "app" / "src" / "main" / "java" / "demo"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "RefundFacade.java"
    source_file.write_text(
        "package demo; public interface RefundFacade { Result createRefund(Request request); }",
        encoding="utf-8",
    )
    outside = tmp_path / "RefundFacadeImpl.java"
    outside.write_text(
        "package secret; class RefundFacadeImpl { SecretGateway gateway; "
        "Result createRefund(Request request) { return gateway.create(request); } }",
        encoding="utf-8",
    )
    (source_dir / "RefundFacadeImpl.java").symlink_to(outside)
    manifest = _manifest("other.core", source_root, source_file)

    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)

    assert all("SecretGateway" not in content for content in batch.content_by_node.values())


def test_agent_enrichment_rejects_other_system_unknown_target_and_escaping_source(tmp_path: Path) -> None:
    """Agent返回其他系统、未知目标或源码根外证据时都必须确定性拒绝。"""

    store, source_root = _registered_store(tmp_path)
    source_file = source_root / "RefundFacade.java"
    source_file.write_text("package demo; interface RefundFacade { void query(Request r); }", encoding="utf-8")
    manifest = _manifest("refund.core", source_root, source_file)
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#createRefund",
        system_id="refund.core",
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#createRefund",
        source_refs=[SourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#createRefund")],
    )
    from opentest.adapters.source_analysis import SourceScanArtifactStore
    from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
    from opentest.application.knowledge import KnowledgeGenerationService
    from opentest.domain.models import KnowledgeGenerationBatchRequest

    service = KnowledgeGenerationService(
        store,
        SqliteKnowledgeIndex(store.root / ".opentest" / "index.sqlite"),
        SourceScanArtifactStore(store.root),
    )
    request = KnowledgeGenerationBatchRequest(
        system_id="refund.core",
        target_ids=[manifest.entries[0].entry_id],
        agent="codex",
        confirmed=True,
    )
    base = {
        "system_id": "refund.core",
        "target_ids": request.target_ids,
        "summaries_by_node": {node.node_id: "摘要"},
        "questions": [],
        "source_refs": [],
    }
    with pytest.raises(ScopeViolationError, match="system and targets"):
        service._run_safe_agent_enrichment(
            request,
            str(source_root),
            manifest,
            [node],
            _EnvelopeAgentRunner({**base, "system_id": "order.core"}),
        )
    with pytest.raises(ScopeViolationError, match="system and targets"):
        service._run_safe_agent_enrichment(
            request,
            str(source_root),
            manifest,
            [node],
            _EnvelopeAgentRunner({**base, "target_ids": ["facade:unknown#target"]}),
        )
    with pytest.raises(ScopeViolationError, match="escapes"):
        service._run_safe_agent_enrichment(
            request,
            str(source_root),
            manifest,
            [node],
            _EnvelopeAgentRunner({**base, "source_refs": [{"path": "../other.java"}]}),
        )
