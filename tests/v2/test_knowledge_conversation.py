"""验证修订式知识聊天的安全存储、提案问题和显式发布边界。"""

from __future__ import annotations

import json
import hashlib
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import KnowledgeQuestionCycleStaleError, KnowledgeValidationError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeStatus,
    KnowledgeConversationScope,
    KnowledgeConversationScopeKind,
    KnowledgeConversationTurnCreate,
    KnowledgeConversationTurnStatus,
    KnowledgeQuestion,
    KnowledgeQuestionCycleAnswer,
    KnowledgeQuestionView,
    ScanManifest,
    SourceReference,
    SystemDefinition,
    RuntimeToolSettings,
)


SYSTEM_ID = "conversation-system"


class _ConversationAgentRunner:
    """把预设Agent信封写入受控证据目录，避免测试启动真实本地Agent。"""

    def __init__(self, payload: dict[str, object] | str):
        """保存严格字典或故意非法的原始输出。

        Args:
            payload: 测试需要Agent返回的JSON对象或非法文本。
        """

        self.payload = payload
        self.prompts: list[str] = []

    def availability(self) -> tuple[bool, bool]:
        """声明测试Codex可用但不解析本机PATH。

        Returns:
            Codex可用、Claude Code不可用的检测结果。
        """

        return True, False

    def is_available(self, agent: str) -> bool:
        """只允许请求中明确选择的Codex。"""

        return agent == "codex"

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """写入预设输出并返回与真实Runner兼容的证据摘要。

        Args:
            request: 包含系统ID和安全提示词的Agent请求。
            source_root: 已注册的当前系统源码目录。
            evidence_root: Git忽略的本地Agent证据根。

        Returns:
            带run_id和output_path属性的轻量证据对象。

        Side Effects:
            仅在pytest临时知识根创建一个输出文件。
        """

        assert source_root.is_dir()
        prompt = str(getattr(request, "prompt"))
        self.prompts.append(prompt)
        # 安全提示不得拼入本地环境设置或Fixture内容字段。
        assert "qa_labrador_token" not in prompt
        assert "qa_gateway_prefix" not in prompt
        run_id = f"agent-{uuid.uuid4().hex[:16]}"
        output_root = evidence_root / run_id
        output_root.mkdir(parents=True, exist_ok=False)
        output_path = output_root / "output.txt"
        output = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        output_path.write_text(output, encoding="utf-8")
        return SimpleNamespace(run_id=run_id, output_path=str(output_path))


class _BlockingConversationAgentRunner(_ConversationAgentRunner):
    """把Agent输出阻塞在受控事件上，用于稳定复现任务身份与取代竞态。"""

    def __init__(self, payload: dict[str, object]):
        """保存合法信封并创建分析开始、允许结束两个同步事件。

        Args:
            payload: 解除阻塞后写入受控证据目录的严格Agent信封。
        """

        super().__init__(payload)
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """通知测试线程Agent已读取会话快照，并等待显式解除阻塞。

        Args:
            request: 包含系统ID和安全提示词的Agent请求。
            source_root: 当前测试系统的隔离源码目录。
            evidence_root: 受控Agent输出目录。

        Returns:
            解除阻塞后由父类写入的兼容证据对象。

        Raises:
            AssertionError: 测试未在五秒内解除阻塞。
        """

        self.started.set()
        # 等待点位于服务已读取轮次、尚未提交结果之间，可确定性覆盖两个并发窗口。
        assert self.release.wait(timeout=5)
        return super().run(request, source_root, evidence_root)


def _application(tmp_path: Path) -> tuple[OpenTestApplication, ScanManifest]:
    """创建带不可变Manifest和背景目标的隔离知识应用。

    Args:
        tmp_path: pytest提供的临时源码和知识目录。

    Returns:
        已注册应用及其latest Manifest。
    """

    source_root = tmp_path / "source"
    source_root.mkdir(parents=True)
    source_file = source_root / "RefundFacade.java"
    source_file.write_text("package demo; interface RefundFacade {}", encoding="utf-8")
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="会话系统", source_path=str(source_root))
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    manifest = ScanManifest(
        scan_id="scan-conversation-test",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id="facade:demo.RefundFacade#create",
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.FACADE,
                display_name="RefundFacade#create",
                source_id="demo.RefundFacade#create",
                source_path=str(source_file),
                metadata={"line": 1},
            ),
            EntryPoint(
                entry_id="facade:demo.RefundFacade#query",
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.FACADE,
                display_name="RefundFacade#query",
                source_id="demo.RefundFacade#query",
                source_path=str(source_file),
                metadata={"line": 1},
            ),
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    gate_runner = _ConversationAgentRunner({})
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="codex"))
    application.agent_runner = gate_runner
    return application, manifest


def _background_request(message: str = "系统负责最终退票结果兜底") -> KnowledgeConversationTurnCreate:
    """构造绑定业务背景的最小显式聊天请求。

    Args:
        message: 仅用于测试的非敏感业务说明。

    Returns:
        不含系统ID、Manifest或知识摘要的页面请求模型。
    """

    return KnowledgeConversationTurnCreate(
        scope=KnowledgeConversationScope(
            kind=KnowledgeConversationScopeKind.TARGET,
            scope_id="background:system",
        ),
        message=message,
        agent="codex",
    )


def _background_envelope(
    manifest: ScanManifest,
    proposed_value: str,
    before_value: str = "",
) -> dict[str, object]:
    """构造一项精确系统定位更新的严格Agent信封。

    Args:
        manifest: 提供系统和扫描身份的固定Manifest。
        proposed_value: 等待右栏确认的人工知识建议值。
        before_value: 提案形成时已经确认的系统定位原值。

    Returns:
        可由KnowledgeConversationAgentEnvelope严格校验的字典。
    """

    return {
        "system_id": SYSTEM_ID,
        "scan_id": manifest.scan_id,
        "scope": {"kind": "TARGET", "scope_id": "background:system"},
        "assistant_summary": "已形成一项精确背景更新，等待右栏确认。",
        "proposals": [
            {
                "kind": "BACKGROUND_UPDATE",
                "title": "确认系统最终兜底责任",
                "detail": "是否把最终退票结果兜底责任发布为人工确认背景？",
                "background_question_id": "interview:system-positioning",
                "before_value": before_value,
                "proposed_value": proposed_value,
                "affected_target_ids": ["background:system"],
            }
        ],
    }


def _set_confirmed_background(application: OpenTestApplication, value: str = "既有系统定位") -> None:
    """为成功会话测试先关闭同一写目标上的开放背景问题。

    Args:
        application: 持有隔离知识真相的测试应用。
        value: 已经人工确认、并将作为后续修订前值的系统定位。

    Side Effects:
        直接写入测试知识上下文，使conversation提案不会与开放访谈问题争写。
    """

    context = application.get_knowledge_context(SYSTEM_ID)
    application.store.write_context(
        context.model_copy(
            update={
                "system_purpose": value,
                "interview_answers": {**context.interview_answers, "interview:system-positioning": value},
            }
        )
    )


def _candidate_creation_envelope(manifest: ScanManifest) -> dict[str, object]:
    """构造同一轮两个纯中文业务术语的新建提案。

    Args:
        manifest: 提供系统和扫描身份的固定Manifest。

    Returns:
        可验证同轮多提案快照推进与Unicode稳定ID的严格信封。
    """

    return {
        "system_id": SYSTEM_ID,
        "scan_id": manifest.scan_id,
        "scope": {"kind": "TARGET", "scope_id": "background:system"},
        "assistant_summary": "已形成两项新业务术语提案。",
        "proposals": [
            {
                "kind": "CANDIDATE_CREATE",
                "title": "确认退票单术语",
                "detail": "是否新增退票单业务术语？",
                "candidate_kind": "BUSINESS_TERM",
                "candidate_name": "退票单",
                "proposed_value": "承载一次退票生命周期的业务单据",
                "affected_target_ids": ["background:system"],
            },
            {
                "kind": "CANDIDATE_CREATE",
                "title": "确认采购账户术语",
                "detail": "是否新增采购账户业务术语？",
                "candidate_kind": "BUSINESS_TERM",
                "candidate_name": "采购账户",
                "proposed_value": "接收最终退款的采购方钱包账户",
                "affected_target_ids": ["background:system"],
            },
        ],
    }


def _target_request(
    target_id: str = "facade:demo.RefundFacade#create",
    message: str = "请按源码修订退票接口知识",
) -> KnowledgeConversationTurnCreate:
    """构造绑定一个源码目录目标的显式聊天请求。

    Args:
        target_id: 当前Manifest中的Facade目标ID。
        message: 不含敏感数据的测试业务修订说明。

    Returns:
        只允许影响所选目标的会话请求。
    """

    return KnowledgeConversationTurnCreate(
        scope=KnowledgeConversationScope(kind=KnowledgeConversationScopeKind.TARGET, scope_id=target_id),
        message=message,
        agent="codex",
    )


def _write_target_nodes(application: OpenTestApplication, count: int = 1) -> dict[str, str]:
    """为两个Facade共享目标写入指定数量、可被聊天精确修订的代码知识节点。

    Args:
        application: 持有隔离知识真相和目录服务的测试应用。
        count: 需要创建的正整数节点数量。

    Returns:
        节点ID到初始自动正文的稳定映射。

    Side Effects:
        写入测试知识Markdown；不生成问题或调用Agent。
    """

    contents: dict[str, str] = {}
    for index in range(count):
        node_id = f"rule:refund:create:{index + 1}"
        content = f"原始代码知识 {index + 1}"
        reference = SourceReference(
            repository="server-repository",
            path="RefundFacade.java",
            symbol=f"demo.RefundFacade#businessRule{index + 1}",
            line=index + 2,
            commit="server-commit",
            content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        node = KnowledgeNode(
            node_id=node_id,
            system_id=SYSTEM_ID,
            kind=KnowledgeNodeKind.BUSINESS_RULE,
            title=f"退票规则 {index + 1}",
            aliases=[
                "facade:demo.RefundFacade#create",
                "demo.RefundFacade#create",
                "facade:demo.RefundFacade#query",
                "demo.RefundFacade#query",
            ],
            source_refs=[reference],
            status=KnowledgeStatus.CODE_VERIFIED,
            confidence=0.95,
        )
        # 每个节点使用独立引用和正文，便于验证规范证据与多节点部分恢复。
        application.store.write_node(node, content)
        contents[node_id] = content
    return contents


def _node_revision_envelope(
    manifest: ScanManifest,
    contents: dict[str, str],
    target_id: str = "facade:demo.RefundFacade#create",
    include_source_refs: bool = True,
) -> dict[str, object]:
    """构造带真实逐节点前后差异的源码修订Agent信封。

    Args:
        manifest: 提供固定系统和扫描身份的Manifest。
        contents: 节点ID到当前自动正文的精确映射。
        target_id: Agent声明受影响的当前Facade目标。
        include_source_refs: 是否携带节点修订必需的源码证据。

    Returns:
        可用于成功、缺证据或作用域越界测试的严格信封字典。
    """

    affected_node_ids = list(contents)
    proposed_by_node = {node_id: f"{content} · 人工修订" for node_id, content in contents.items()}
    source_refs = [
        {
            "repository": "agent-forged-repository",
            "path": "RefundFacade.java",
            "symbol": f"demo.RefundFacade#businessRule{index + 1}",
            "line": index + 2,
            "commit": "agent-forged-commit",
            "content_digest": "a" * 64,
        }
        for index in range(len(contents))
    ] if include_source_refs else []
    return {
        "system_id": SYSTEM_ID,
        "scan_id": manifest.scan_id,
        "scope": {"kind": "TARGET", "scope_id": target_id},
        "assistant_summary": "已形成源码节点修订。",
        "proposals": [
            {
                "kind": "NODE_REVISION",
                "title": "Agent自述标题不应展示",
                "detail": "Agent自述详情不应作为确认事实",
                "affected_target_ids": [target_id],
                "affected_node_ids": affected_node_ids,
                "evidence_basis": "SOURCE_REFERENCE",
                "source_refs": source_refs,
                "before_by_node": contents,
                "proposed_by_node": proposed_by_node,
            }
        ],
    }


def _candidate_update_envelope(
    manifest: ScanManifest,
    scope_candidate_id: str,
    proposal_candidate_id: str,
    before_value: str,
) -> dict[str, object]:
    """构造候选作用域中的人工含义修订信封。

    Args:
        manifest: 提供系统和扫描身份的固定Manifest。
        scope_candidate_id: 用户当前从左侧选中的候选ID。
        proposal_candidate_id: Agent试图修订的候选ID。
        before_value: 被修订候选当前人工含义。

    Returns:
        可用于验证同候选闭包或跨候选越界的严格信封。
    """

    return {
        "system_id": SYSTEM_ID,
        "scan_id": manifest.scan_id,
        "scope": {"kind": "CANDIDATE", "scope_id": scope_candidate_id},
        "assistant_summary": "形成一项候选含义修订。",
        "proposals": [
            {
                "kind": "CANDIDATE_UPDATE",
                "title": "Agent候选标题",
                "detail": "Agent候选详情",
                "candidate_id": proposal_candidate_id,
                "before_value": before_value,
                "proposed_value": f"{before_value} · 修订",
                "evidence_basis": "USER_MESSAGE",
                "affected_target_ids": ["background:system"],
            }
        ],
    }


def _wait_for_task(application: OpenTestApplication, task_id: str) -> None:
    """等待一个测试本地任务进入终态。

    Args:
        application: 持有本地任务管理器的隔离应用。
        task_id: 后台会话分析任务稳定ID。

    Returns:
        None；任务在五秒内结束即返回。

    Raises:
        AssertionError: 任务超时仍未进入终态。
    """

    for _ in range(500):
        task = application.tasks.get(task_id)
        if task.status.value in {"completed", "failed", "interrupted"}:
            return
        time.sleep(0.01)
    raise AssertionError(f"conversation task did not finish: {task_id}")


def test_conversation_storage_is_private_persistent_and_system_isolated(tmp_path: Path) -> None:
    """聊天历史应使用0700目录和0600文件并在应用重启后恢复。

    Args:
        tmp_path: pytest隔离知识根。

    Returns:
        None；权限、恢复和跨系统读取断言全部通过即满足契约。
    """

    application, _ = _application(tmp_path)
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    root = application.knowledge_root / ".opentest" / "knowledge-conversations" / SYSTEM_ID
    path = root / f"{turn.turn_id}.json"

    assert root.stat().st_mode & 0o077 == 0
    assert path.stat().st_mode & 0o077 == 0
    resumed = OpenTestApplication(application.knowledge_root)
    assert resumed.list_knowledge_conversation_turns(SYSTEM_ID)[0].user_message == turn.user_message
    resumed.close()

    other_source = tmp_path / "other-source"
    other_source.mkdir()
    application.register_system(
        SystemDefinition(system_id="other-conversation-system", name="其他系统", source_path=str(other_source))
    )
    assert application.list_knowledge_conversation_turns("other-conversation-system") == []


def test_conversation_storage_rejects_symbolic_link_parent(tmp_path: Path) -> None:
    """会话类别目录被替换为符号链接时不得跟随写出知识根。

    Args:
        tmp_path: pytest隔离知识根和外部目标目录。

    Returns:
        None；安全存储在写入前拒绝符号链接即通过。
    """

    application, _ = _application(tmp_path)
    category = application.knowledge_root / ".opentest" / "knowledge-conversations"
    outside = tmp_path / "outside"
    outside.mkdir()
    category.parent.mkdir(parents=True, exist_ok=True)
    category.symlink_to(outside, target_is_directory=True)

    with pytest.raises(KnowledgeValidationError):
        application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    assert list(outside.iterdir()) == []


def test_agent_proposal_enters_question_cycle_without_publishing_and_keeps_staged_answers(tmp_path: Path) -> None:
    """Agent提案应只新增conversation问题，并继承旧周期稳定暂存答案。

    Args:
        tmp_path: pytest隔离问题周期和会话存储。

    Returns:
        None；知识未变化、问题新增且旧答案保留即满足契约。
    """

    application, manifest = _application(tmp_path)
    original_question = KnowledgeQuestion(
        question_id="question:existing-high-impact",
        system_id=SYSTEM_ID,
        source="published",
        title="确认既有异常边界",
        detail="该异常是否需要人工补偿？",
        category="exception_strategy",
        why_asked="影响测试判定",
        impact="high",
    )
    application.store.write_questions(SYSTEM_ID, [original_question])
    original_cycle = application.get_knowledge_question_cycle(SYSTEM_ID, refresh=True)
    staged = application.stage_knowledge_question_cycle_answer(
        SYSTEM_ID,
        original_cycle.cycle_id,
        KnowledgeQuestionCycleAnswer(question_id=original_question.question_id, answer="已暂存背景答案"),
    )
    _set_confirmed_background(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _background_envelope(manifest, "SaaS退票业务层并负责最终结果兜底", "既有系统定位")
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)

    assert analyzed.status == KnowledgeConversationTurnStatus.NEEDS_CONFIRMATION
    assert application.get_knowledge_context(SYSTEM_ID).system_purpose == "既有系统定位"
    conversation_question = next(
        question
        for question in application.list_unified_knowledge_questions(SYSTEM_ID)
        if question.source == "conversation"
    )
    assert conversation_question.answer_options == ["确认发布", "暂不确定"]
    refreshed_cycle = application.get_knowledge_question_cycle(SYSTEM_ID, refresh=True)
    assert refreshed_cycle.cycle_id != original_cycle.cycle_id
    assert refreshed_cycle.staged_answers[original_question.question_id] == staged.staged_answers[original_question.question_id]
    assert conversation_question.question_id in {question.question_id for question in refreshed_cycle.questions}

    with pytest.raises(KnowledgeValidationError, match="allowed options"):
        application.stage_knowledge_question_cycle_answer(
            SYSTEM_ID,
            refreshed_cycle.cycle_id,
            KnowledgeQuestionCycleAnswer(
                question_id=conversation_question.question_id,
                answer="直接发布",
            ),
        )


def test_analysis_preserves_attached_task_identity_and_superseded_turn_state(tmp_path: Path) -> None:
    """运行中Agent不得丢失任务身份，也不得复活被同作用域新消息取代的轮次。

    Args:
        tmp_path: pytest隔离任务、会话和问题真相。

    Returns:
        None；竞态窗口关闭后任务ID和SUPERSEDED终态均保持即通过。
    """

    application, manifest = _application(tmp_path)
    runner = _BlockingConversationAgentRunner(_background_envelope(manifest, "旧消息建议值"))
    application.knowledge_conversation.runner = runner
    first_turn, task = application.create_knowledge_conversation_turn(SYSTEM_ID, _background_request("第一条消息"))
    assert runner.started.wait(timeout=2)
    assert first_turn.task_id == task.task_id

    # Agent仍运行时的新消息必须取代旧轮次；它只持久化，不在本测试启动第二个Agent。
    replacement = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request("第二条消息"))
    runner.release.set()
    _wait_for_task(application, task.task_id)

    turns = application.list_knowledge_conversation_turns(SYSTEM_ID)
    stored_first = next(turn for turn in turns if turn.turn_id == first_turn.turn_id)
    assert stored_first.status == KnowledgeConversationTurnStatus.SUPERSEDED
    assert stored_first.task_id == task.task_id
    assert replacement.status == KnowledgeConversationTurnStatus.ANALYZING
    assert all(question.source != "conversation" for question in application.list_unified_knowledge_questions(SYSTEM_ID))


def test_missing_conversation_task_recovers_to_retryable_blocked_state(tmp_path: Path) -> None:
    """分析中轮次缺少任务文件时应保留消息并恢复显式重试入口。

    Args:
        tmp_path: pytest隔离会话与任务目录。

    Returns:
        None；缺失任务不会使历史GET失败或永久停在ANALYZING。
    """

    application, _ = _application(tmp_path)
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    application.knowledge_conversation.attach_task(SYSTEM_ID, turn.turn_id, "task-does-not-exist")

    recovered = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]

    assert recovered.status == KnowledgeConversationTurnStatus.BLOCKED
    assert recovered.user_message == turn.user_message
    assert "可保留原消息重试" in recovered.safe_error


def test_multiple_chinese_candidate_proposals_publish_with_distinct_ids(tmp_path: Path) -> None:
    """同轮多提案应推进自身快照，且纯中文候选不得发生稳定ID碰撞。

    Args:
        tmp_path: pytest隔离候选真相和会话提案。

    Returns:
        None；两项提案均发布且生成两个不同候选ID即通过。
    """

    application, manifest = _application(tmp_path)
    application.knowledge_conversation.runner = _ConversationAgentRunner(_candidate_creation_envelope(manifest))
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request("补充两个业务术语"))
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)

    for question_id in analyzed.question_ids:
        question = next(
            item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
            if item.question_id == question_id
        )
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")

    candidates = application.get_knowledge_context(SYSTEM_ID).candidates
    assert {candidate.name for candidate in candidates} == {"退票单", "采购账户"}
    assert len({candidate.candidate_id for candidate in candidates}) == 2
    published = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]
    assert published.status == KnowledgeConversationTurnStatus.PUBLISHED


def test_pending_turns_for_distinct_candidates_remain_publishable(tmp_path: Path) -> None:
    """不同候选的未决会话不应因另一候选先发布而永久stale。

    Args:
        tmp_path: pytest隔离两个候选、会话快照和问题真相。

    Returns:
        None；两个不同写目标依次发布且各自建议值均保留即通过。
    """

    application, manifest = _application(tmp_path)
    application.knowledge_conversation.runner = _ConversationAgentRunner(_candidate_creation_envelope(manifest))
    creation_turn = application.knowledge_conversation.create_turn(
        SYSTEM_ID,
        _background_request("先建立两个可独立修订的业务术语"),
    )
    created = application.knowledge_conversation.analyze_turn(SYSTEM_ID, creation_turn.turn_id)
    for question_id in created.question_ids:
        question = next(
            item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
            if item.question_id == question_id
        )
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")

    candidates = application.get_knowledge_context(SYSTEM_ID).candidates
    pending_questions: list[KnowledgeQuestionView] = []
    for candidate in candidates:
        # 两个作用域分别形成未决提案，复现全系统摘要曾让后发布者永久失效的问题。
        application.knowledge_conversation.runner = _ConversationAgentRunner(
            _candidate_update_envelope(
                manifest,
                candidate.candidate_id,
                candidate.candidate_id,
                candidate.business_meaning,
            )
        )
        request = KnowledgeConversationTurnCreate(
            scope=KnowledgeConversationScope(
                kind=KnowledgeConversationScopeKind.CANDIDATE,
                scope_id=candidate.candidate_id,
            ),
            message=f"修订候选 {candidate.name}",
            agent="codex",
        )
        turn = application.knowledge_conversation.create_turn(SYSTEM_ID, request)
        analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
        pending_questions.append(
            next(
                item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
                if item.question_id == analyzed.question_ids[0]
            )
        )

    application.knowledge_conversation.apply_answer(SYSTEM_ID, pending_questions[0], "确认发布")
    application.knowledge_conversation.apply_answer(SYSTEM_ID, pending_questions[1], "确认发布")

    updated_candidates = application.get_knowledge_context(SYSTEM_ID).candidates
    assert all(candidate.business_meaning.endswith("· 修订") for candidate in updated_candidates)


def test_conversation_publish_retry_converges_after_knowledge_file_was_already_written(tmp_path: Path) -> None:
    """知识先成功而会话终态写入失败时，重试应精确收敛而不是误报stale。

    Args:
        tmp_path: pytest隔离知识文件、问题和会话状态。

    Returns:
        None；精确建议值只发布一次且提案最终进入PUBLISHED。
    """

    application, manifest = _application(tmp_path)
    proposed = "已写入但尚未记录提案终态的系统定位"
    _set_confirmed_background(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _background_envelope(manifest, proposed, "既有系统定位")
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    question = next(
        item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
        if item.question_id == analyzed.question_ids[0]
    )

    # 模拟进程在知识文件原子落盘后、问题和会话终态写入前退出。
    with application.store.system_transaction(SYSTEM_ID):
        application.knowledge_conversation._publish_proposal(analyzed, analyzed.proposals[0])
    application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")

    assert application.get_knowledge_context(SYSTEM_ID).system_purpose == proposed
    resolved = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]
    assert resolved.proposals[0].status.value == "PUBLISHED"


def test_confirmed_conversation_proposal_publishes_only_through_question_answer(tmp_path: Path) -> None:
    """只有固定选择“确认发布”才把提案写为人工背景知识。

    Args:
        tmp_path: pytest隔离知识真相和会话文件。

    Returns:
        None；发布前后背景、问题和提案状态均符合契约即通过。
    """

    application, manifest = _application(tmp_path)
    proposed = "SaaS退票业务层并负责最终退票与退款结果兜底"
    _set_confirmed_background(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _background_envelope(manifest, proposed, "既有系统定位")
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    question = next(
        item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
        if item.question_id == analyzed.question_ids[0]
    )

    application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")
    context = application.get_knowledge_context(SYSTEM_ID)
    published_turn = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]

    assert context.interview_answers["interview:system-positioning"] == proposed
    assert context.system_purpose == proposed
    assert published_turn.status == KnowledgeConversationTurnStatus.PUBLISHED
    assert published_turn.proposals[0].status.value == "PUBLISHED"
    assert published_turn.proposals[0].evidence_basis.value == "USER_MESSAGE"
    # 同一答案重放必须幂等，不能重复创建知识或改变已发布内容。
    application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")
    assert application.get_knowledge_context(SYSTEM_ID).system_purpose == proposed


def test_conversation_proposal_rejects_stale_knowledge_snapshot(tmp_path: Path) -> None:
    """提案形成后背景真相变化时应返回稳定stale冲突而非覆盖新值。

    Args:
        tmp_path: pytest隔离知识真相。

    Returns:
        None；旧提案被拒绝且新背景保留即通过。
    """

    application, manifest = _application(tmp_path)
    _set_confirmed_background(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _background_envelope(manifest, "旧提案建议值", "既有系统定位")
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    question = next(
        item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
        if item.question_id == analyzed.question_ids[0]
    )
    context = application.get_knowledge_context(SYSTEM_ID)
    changed = context.model_copy(
        update={
            "system_purpose": "其他页面的新背景",
            "interview_answers": {"interview:system-positioning": "其他页面的新背景"},
        }
    )
    application.store.write_context(changed)

    with pytest.raises(KnowledgeQuestionCycleStaleError):
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")
    assert application.get_knowledge_context(SYSTEM_ID).system_purpose == "其他页面的新背景"


def test_invalid_agent_output_blocks_without_question_and_allows_retry(tmp_path: Path) -> None:
    """非法Agent输出应保留消息、生成安全BLOCKED状态且不制造问题。

    Args:
        tmp_path: pytest隔离会话和问题真相。

    Returns:
        None；失败轮次可恢复为ANALYZING且没有猜测提案即通过。
    """

    application, _ = _application(tmp_path)
    application.knowledge_conversation.runner = _ConversationAgentRunner("not-json")
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    blocked = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)

    assert blocked.status == KnowledgeConversationTurnStatus.BLOCKED
    assert blocked.proposals == []
    assert blocked.question_ids == []
    assert "not-json" not in blocked.safe_error
    retried = application.knowledge_conversation.prepare_retry(SYSTEM_ID, turn.turn_id, "codex")
    assert retried.status == KnowledgeConversationTurnStatus.ANALYZING
    assert retried.user_message == turn.user_message


def test_background_proposal_is_allowed_after_generic_interview_questions_removed(tmp_path: Path) -> None:
    """通用背景题移出问题周期后，聊天可形成一项明确背景修订提案。

    Args:
        tmp_path: pytest隔离背景问题和会话状态。

    Returns:
        None；轮次进入待确认且只生成conversation问题即通过。
    """

    application, manifest = _application(tmp_path)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _background_envelope(manifest, "与开放问题争写的建议")
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())

    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)

    assert analyzed.status == KnowledgeConversationTurnStatus.NEEDS_CONFIRMATION
    assert len(analyzed.proposals) == 1
    assert any(question.source == "conversation" for question in application.list_unified_knowledge_questions(SYSTEM_ID))


def test_node_revision_uses_canonical_evidence_and_server_generated_diff(tmp_path: Path) -> None:
    """节点提案应替换Agent来源元数据，并由服务端展示真实前后差异。

    Args:
        tmp_path: pytest隔离源码节点、Agent信封和确认问题。

    Returns:
        None；规范引用、确定性标题和逐节点差异均可核对即通过。
    """

    application, manifest = _application(tmp_path)
    # 先形成一个会在正文写完后失败的单节点修订提案。
    contents = _write_target_nodes(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(manifest, contents)
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())

    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    proposal = analyzed.proposals[0]
    question = next(
        item for item in application.store.list_questions(SYSTEM_ID)
        if item.question_id == proposal.question_id
    )

    assert analyzed.status == KnowledgeConversationTurnStatus.NEEDS_CONFIRMATION
    assert proposal.source_refs[0].repository == "server-repository"
    assert proposal.source_refs[0].commit == "server-commit"
    assert proposal.source_refs[0].content_digest != "a" * 64
    assert question.title != "Agent自述标题不应展示"
    assert contents[proposal.affected_node_ids[0]] in question.detail
    assert proposal.proposed_by_node[proposal.affected_node_ids[0]] in question.detail
    assert "SOURCE_REFERENCE" in question.detail


def test_node_revision_without_source_evidence_is_blocked(tmp_path: Path) -> None:
    """源码节点修订缺少规范引用时不得退化为用户消息证据。

    Args:
        tmp_path: pytest隔离代码节点和无证据信封。

    Returns:
        None；轮次进入BLOCKED且不产生猜测问题即通过。
    """

    application, manifest = _application(tmp_path)
    contents = _write_target_nodes(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(manifest, contents, include_source_refs=False)
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())

    blocked = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)

    assert blocked.status == KnowledgeConversationTurnStatus.BLOCKED
    assert blocked.question_ids == []


def test_target_scope_rejects_proposal_for_another_target(tmp_path: Path) -> None:
    """TARGET聊天不得把节点修订的影响目标改成同系统另一个目录对象。

    Args:
        tmp_path: pytest隔离当前Facade和背景目标。

    Returns:
        None；越界提案被BLOCKED且没有问题落盘即通过。
    """

    application, manifest = _application(tmp_path)
    contents = _write_target_nodes(application)
    payload = _node_revision_envelope(manifest, contents)
    payload["proposals"][0]["affected_target_ids"] = ["background:system"]
    application.knowledge_conversation.runner = _ConversationAgentRunner(payload)
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())

    blocked = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)

    assert blocked.status == KnowledgeConversationTurnStatus.BLOCKED
    assert blocked.proposals == []


def test_candidate_scope_can_only_revise_selected_candidate(tmp_path: Path) -> None:
    """候选聊天只能修订当前候选，不能借同系统ID修改另一个术语。

    Args:
        tmp_path: pytest隔离两个已确认候选和越界修订会话。

    Returns:
        None；跨候选提案被BLOCKED且两个候选含义均保持不变即通过。
    """

    application, manifest = _application(tmp_path)
    application.knowledge_conversation.runner = _ConversationAgentRunner(_candidate_creation_envelope(manifest))
    creation_turn = application.knowledge_conversation.create_turn(
        SYSTEM_ID,
        _background_request("新增两个候选用于作用域测试"),
    )
    created = application.knowledge_conversation.analyze_turn(SYSTEM_ID, creation_turn.turn_id)
    for question_id in created.question_ids:
        question = next(
            item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
            if item.question_id == question_id
        )
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")
    candidates = application.get_knowledge_context(SYSTEM_ID).candidates
    selected_candidate, other_candidate = candidates
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _candidate_update_envelope(
            manifest,
            selected_candidate.candidate_id,
            other_candidate.candidate_id,
            other_candidate.business_meaning,
        )
    )
    request = KnowledgeConversationTurnCreate(
        scope=KnowledgeConversationScope(
            kind=KnowledgeConversationScopeKind.CANDIDATE,
            scope_id=selected_candidate.candidate_id,
        ),
        message="请修订当前术语含义",
        agent="codex",
    )
    update_turn = application.knowledge_conversation.create_turn(SYSTEM_ID, request)

    blocked = application.knowledge_conversation.analyze_turn(SYSTEM_ID, update_turn.turn_id)

    assert blocked.status == KnowledgeConversationTurnStatus.BLOCKED
    assert {
        candidate.candidate_id: candidate.business_meaning
        for candidate in application.get_knowledge_context(SYSTEM_ID).candidates
    } == {candidate.candidate_id: candidate.business_meaning for candidate in candidates}


def test_proposal_write_targets_reject_existing_batch_and_pending_conflicts(tmp_path: Path) -> None:
    """节点提案不得与开放问题、同信封或另一作用域未决提案争写。

    Args:
        tmp_path: pytest隔离三个冲突检测分支。

    Returns:
        None；三类冲突都只形成BLOCKED会话且不覆盖首个未决提案。
    """

    existing_application, existing_manifest = _application(tmp_path / "existing")
    existing_contents = _write_target_nodes(existing_application)
    node_id = next(iter(existing_contents))
    existing_application.store.write_questions(
        SYSTEM_ID,
        [
            KnowledgeQuestion(
                question_id="question:existing-node-revision",
                system_id=SYSTEM_ID,
                title="已有节点修订问题",
                detail="等待现有流程确认",
                affected_node_ids=[node_id],
            )
        ],
    )
    existing_application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(existing_manifest, existing_contents)
    )
    existing_turn = existing_application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())
    assert existing_application.knowledge_conversation.analyze_turn(
        SYSTEM_ID,
        existing_turn.turn_id,
    ).status == KnowledgeConversationTurnStatus.BLOCKED

    batch_application, batch_manifest = _application(tmp_path / "batch")
    batch_contents = _write_target_nodes(batch_application)
    duplicate_payload = _node_revision_envelope(batch_manifest, batch_contents)
    duplicate_payload["proposals"].append(dict(duplicate_payload["proposals"][0]))
    batch_application.knowledge_conversation.runner = _ConversationAgentRunner(duplicate_payload)
    batch_turn = batch_application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())
    assert batch_application.knowledge_conversation.analyze_turn(
        SYSTEM_ID,
        batch_turn.turn_id,
    ).status == KnowledgeConversationTurnStatus.BLOCKED

    pending_application, pending_manifest = _application(tmp_path / "pending")
    pending_contents = _write_target_nodes(pending_application)
    pending_application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(pending_manifest, pending_contents)
    )
    first_turn = pending_application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())
    first_analyzed = pending_application.knowledge_conversation.analyze_turn(SYSTEM_ID, first_turn.turn_id)
    pending_application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(
            pending_manifest,
            pending_contents,
            target_id="facade:demo.RefundFacade#query",
        )
    )
    second_turn = pending_application.knowledge_conversation.create_turn(
        SYSTEM_ID,
        _target_request("facade:demo.RefundFacade#query"),
    )
    second_analyzed = pending_application.knowledge_conversation.analyze_turn(SYSTEM_ID, second_turn.turn_id)

    assert first_analyzed.status == KnowledgeConversationTurnStatus.NEEDS_CONFIRMATION
    assert second_analyzed.status == KnowledgeConversationTurnStatus.BLOCKED


def test_multi_node_partial_publish_resumes_without_rewriting_applied_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多节点发布中断后应记录partial，并只补写仍处于before态的节点。

    Args:
        tmp_path: pytest隔离多节点知识和会话文件。
        monkeypatch: 在第二个节点写入前注入一次进程故障。

    Returns:
        None；重试后两个节点和提案都完整发布即通过。
    """

    application, manifest = _application(tmp_path)
    contents = _write_target_nodes(application, count=2)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(manifest, contents)
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    proposal = analyzed.proposals[0]
    question = next(
        item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
        if item.question_id == proposal.question_id
    )
    original_write_node = application.store.write_node
    write_count = 0

    def fail_second_node(node: KnowledgeNode, content: str) -> Path:
        """让首节点正常落盘，并在第二节点写入前模拟进程异常。

        Args:
            node: 本次准备写入的知识节点元数据。
            content: 本次准备写入的自动正文。

        Returns:
            首节点正常写入后的Markdown路径。

        Raises:
            RuntimeError: 第二次调用固定模拟中断。
        """

        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise RuntimeError("simulated second-node failure")
        return original_write_node(node, content)

    monkeypatch.setattr(application.store, "write_node", fail_second_node)
    with pytest.raises(RuntimeError, match="second-node"):
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")
    interrupted = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]
    assert interrupted.proposals[0].application_state.value == "partial"

    monkeypatch.setattr(application.store, "write_node", original_write_node)
    application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")

    published = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]
    assert published.proposals[0].application_state.value == "published"
    assert published.proposals[0].status.value == "PUBLISHED"
    for node_id, proposed in proposal.proposed_by_node.items():
        node, _, body = application.store.get_node(SYSTEM_ID, node_id)
        assert node.status == KnowledgeStatus.USER_CONFIRMED
        assert proposed in body


def test_node_publish_retry_rebuilds_index_after_all_files_were_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """节点正文全部落盘但索引重建失败时，重试必须再次重建后才发布。

    Args:
        tmp_path: pytest隔离知识正文、SQLite索引和会话状态。
        monkeypatch: 让首次索引重建确定性失败并观察第二次调用。

    Returns:
        None；第二次确认完成索引重建并把提案收敛为PUBLISHED即通过。
    """

    application, manifest = _application(tmp_path)
    contents = _write_target_nodes(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(manifest, contents)
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    question = next(
        item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
        if item.question_id == analyzed.question_ids[0]
    )
    original_rebuild = application.knowledge.index.rebuild
    rebuild_calls = 0

    def fail_first_rebuild(store: object) -> object:
        """首次模拟索引阶段故障，后续调用委托真实重建实现。

        Args:
            store: KnowledgeGenerationService传入的当前知识存储。

        Returns:
            第二次及以后调用的真实索引计数。

        Raises:
            RuntimeError: 第一次调用固定模拟索引重建中断。
        """

        nonlocal rebuild_calls
        rebuild_calls += 1
        # 第一次停在正文与索引之间，第二次必须进入真实重建以证明恢复闭环。
        if rebuild_calls == 1:
            raise RuntimeError("simulated index rebuild failure")
        return original_rebuild(store)

    monkeypatch.setattr(application.knowledge.index, "rebuild", fail_first_rebuild)
    with pytest.raises(RuntimeError, match="index rebuild"):
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")

    # 正文已是建议值但提案仍待确认；恢复路径必须补做索引而不能直接标记成功。
    application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")

    published = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]
    assert rebuild_calls == 2
    assert published.proposals[0].status.value == "PUBLISHED"
    assert published.proposals[0].application_state.value == "published"


def test_partial_node_publish_rejects_external_change_to_unaffected_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """部分恢复只能忽略本提案已写节点，目标内其他变化仍必须触发stale。

    Args:
        tmp_path: pytest隔离三个同目标节点和会话快照。
        monkeypatch: 在第二个提案节点写入前模拟一次中断。

    Returns:
        None；未受提案影响的第三节点变化使恢复被稳定拒绝即通过。
    """

    application, manifest = _application(tmp_path)
    # 三个节点属于同一目标，但提案只覆盖前两个，第三个用于模拟外部范围变化。
    all_contents = _write_target_nodes(application, count=3)
    proposed_contents = dict(list(all_contents.items())[:2])
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _node_revision_envelope(manifest, proposed_contents)
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    question = next(
        item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
        if item.question_id == analyzed.question_ids[0]
    )
    original_write_node = application.store.write_node
    write_count = 0

    def interrupt_second_write(node: KnowledgeNode, content: str) -> Path:
        """让首个提案节点落盘，并在第二个节点前中断发布。

        Args:
            node: 准备写入的知识节点元数据。
            content: 准备写入的知识正文。

        Returns:
            首次调用写入后的Markdown路径。

        Raises:
            RuntimeError: 第二次调用固定模拟发布中断。
        """

        nonlocal write_count
        write_count += 1
        # 首节点落盘后持久化partial，第二节点前中断，留下可恢复的精确中间态。
        if write_count == 2:
            raise RuntimeError("simulated partial publish")
        return original_write_node(node, content)

    monkeypatch.setattr(application.store, "write_node", interrupt_second_write)
    with pytest.raises(RuntimeError, match="partial publish"):
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")
    monkeypatch.setattr(application.store, "write_node", original_write_node)

    unaffected_node_id = list(all_contents)[2]
    unaffected_node, _, _ = application.store.get_node(SYSTEM_ID, unaffected_node_id)
    application.store.write_node(unaffected_node, "目标内其他流程写入的新知识")

    with pytest.raises(KnowledgeQuestionCycleStaleError):
        application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "确认发布")
    interrupted = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]
    assert interrupted.proposals[0].application_state.value == "partial"
    assert interrupted.proposals[0].status.value == "PENDING_CONFIRMATION"


def test_current_instance_empty_task_window_stays_analyzing_until_attach(tmp_path: Path) -> None:
    """当前服务刚创建的无task_id轮次不得被历史GET误判为重启中断。

    Args:
        tmp_path: pytest隔离会话创建和列表恢复窗口。

    Returns:
        None；同实例读取保持ANALYZING，重启恢复仍由既有测试覆盖。
    """

    application, _ = _application(tmp_path)
    created = application.knowledge_conversation.create_turn(SYSTEM_ID, _target_request())

    listed = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]

    assert created.task_id == ""
    assert listed.status == KnowledgeConversationTurnStatus.ANALYZING


def test_unknown_conversation_answer_does_not_publish_knowledge(tmp_path: Path) -> None:
    """“暂不确定”应结束提案处理但保持知识未发布和问题阻塞。

    Args:
        tmp_path: pytest隔离会话和知识真相。

    Returns:
        None；背景为空且问题保留开放未知答案即通过。
    """

    application, manifest = _application(tmp_path)
    _set_confirmed_background(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _background_envelope(manifest, "不应发布的建议值", "既有系统定位")
    )
    turn = application.knowledge_conversation.create_turn(SYSTEM_ID, _background_request())
    analyzed = application.knowledge_conversation.analyze_turn(SYSTEM_ID, turn.turn_id)
    question = next(
        item for item in application.list_unified_knowledge_questions(SYSTEM_ID)
        if item.question_id == analyzed.question_ids[0]
    )

    application.knowledge_conversation.apply_answer(SYSTEM_ID, question, "暂不确定")
    stored_question = next(
        item for item in application.store.list_questions(SYSTEM_ID)
        if item.question_id == question.question_id
    )
    resolved_turn = application.list_knowledge_conversation_turns(SYSTEM_ID)[0]

    assert application.get_knowledge_context(SYSTEM_ID).system_purpose == "既有系统定位"
    assert stored_question.status == "open"
    assert stored_question.answer == "暂不确定"
    assert resolved_turn.proposals[0].status.value == "UNKNOWN"


def test_conversation_http_write_is_retired_while_history_remains_readable(tmp_path: Path) -> None:
    """旧聊天POST应返回410，历史GET仍保持一个兼容周期可读。

    Args:
        tmp_path: pytest隔离FastAPI应用、Manifest和会话证据。

    Returns:
        None；写入口不再启动任务且历史读取仍成功即通过。
    """

    application, manifest = _application(tmp_path)
    _set_confirmed_background(application)
    application.knowledge_conversation.runner = _ConversationAgentRunner(
        _background_envelope(manifest, "HTTP会话建议值", "既有系统定位")
    )
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        created = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/conversation-turns",
            json={
                "scope": {"kind": "TARGET", "scope_id": "background:system"},
                "message": "通过页面显式提交的背景补充",
                "agent": "codex",
            },
        )
        assert created.status_code == 410
        assert created.json()["error"]["code"] == "knowledge_question_flow_retired"
        history = client.get(f"/api/v2/systems/{SYSTEM_ID}/knowledge/conversation-turns")

    assert history.status_code == 200
    assert history.json()["turns"] == []
