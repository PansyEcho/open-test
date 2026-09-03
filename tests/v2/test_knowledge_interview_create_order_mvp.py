"""验证知识访谈和知识修订的当前业务契约。"""

from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import ExecutionFailure
from opentest.domain.models import (
    EntryPoint,
    KnowledgeConfirmation,
    KnowledgeGenerationBatchRequest,
    KnowledgeInterview,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeQuestion,
    KnowledgeRevisionRequest,
    KnowledgeStatus,
    ScanManifest,
    SystemDefinition,
)


class _UnavailableAgent:
    """模拟已选 Codex 在单目标分析阶段失败。"""

    def availability(self) -> tuple[bool, bool]:
        """声明 Codex 可选择，以便测试进入单目标执行阶段。"""

        return True, False

    def is_available(self, agent: str) -> bool:
        """仅允许测试显式选择 Codex。"""

        return agent == "codex"

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """模拟 Codex 失败，使知识生成按当前规则降级为代码事实。

        Args:
            request: 本次知识分析请求。
            source_root: 已注册源码根。
            evidence_root: 本次分析证据目录。

        Raises:
            ExecutionFailure: 始终抛出，验证确定性降级路径。
        """

        del request, source_root, evidence_root
        raise ExecutionFailure("simulated codex failure")


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
