"""验证证据驱动集中问答周期、未知项和代码事实吸收。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import AgentRunInterruptedError, KnowledgeQuestionCycleStaleError, KnowledgeValidationError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeConfirmation,
    KnowledgeBackgroundUpdate,
    KnowledgeContextCandidate,
    KnowledgeContextCandidateCreate,
    KnowledgeContextCandidateKind,
    KnowledgeContextCandidateStatus,
    KnowledgeContextCandidateUpdate,
    KnowledgeContextNarrativeUpdate,
    KnowledgeDraftConfirmation,
    KnowledgeAgentContinuationRequest,
    KnowledgeEnumValue,
    KnowledgeGenerationBatchRequest,
    KnowledgeGenerationWorkflowBatch,
    KnowledgeTargetGenerationOutcome,
    KnowledgeQuestion,
    KnowledgeQuestionCycle,
    KnowledgeQuestionCycleAnswer,
    KnowledgeQuestionCycleCompletion,
    KnowledgeQuestionCycleStatus,
    KnowledgeQuestionView,
    KnowledgeStatus,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticEnumValue,
    SemanticFieldDefinition,
    SemanticMethodDefinition,
    SemanticPatternEvidence,
    SemanticResolutionStatus,
    SemanticTypeDefinition,
    SourceReference,
    StateMachineDefinition,
    StateTransition,
    SystemDefinition,
    RuntimeToolSettings,
    utc_now,
)


SYSTEM_ID = "demo-interview-system"


def _application(tmp_path: Path) -> OpenTestApplication:
    """创建已初始化且注册一个本地源码系统的测试应用。

    Args:
        tmp_path: pytest隔离目录。

    Returns:
        不含扫描或QA配置的OpenTest应用。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge-base")
    application.initialize()
    application.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="访谈系统", source_path=str(source_root))
    )
    return application


def _wait_for_task(application: OpenTestApplication, task_id: str) -> None:
    """等待测试中的本地任务进入终态。

    Args:
        application: 持有任务管理器的隔离OpenTest应用。
        task_id: 集中问答完成后返回的任务ID。

    Raises:
        AssertionError: 任务未在两秒内完成或以失败状态结束。
    """

    for _ in range(200):
        task = application.tasks.get(task_id)
        if task.status.value in {"completed", "failed", "interrupted"}:
            assert task.status.value == "completed", task.error
            return
        time.sleep(0.01)
    raise AssertionError(f"task did not complete: {task_id}")


class _KnowledgeAgentRunner:
    """按确定性节点返回完整INFERRED摘要，不访问真实Codex或Claude Code。"""

    def availability(self) -> tuple[bool, bool]:
        """声明测试环境中只有Codex可用。"""

        return True, False

    def is_available(self, agent: str) -> bool:
        """仅接受请求明确携带的Codex选择。"""

        return agent == "codex"

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """从安全提示中的节点闭包构造严格Agent信封。

        Args:
            request: 包含显式Agent和结构化业务证据的运行请求。
            source_root: 已注册源码根，本桩不读取正文。
            evidence_root: 允许保存测试输出的本地忽略目录。

        Returns:
            只公开严格JSON输出路径的轻量证据对象。
        """

        del source_root
        prompt_payload = json.loads(request.prompt.split("\n", 1)[1])
        assert prompt_payload["source_packet"]
        assert all(not Path(item["path"]).is_absolute() for item in prompt_payload["source_packet"])
        summaries = {
            item["node_id"]: "基于给定源码证据解释该目标的业务目的、主流程、分支、依赖、副作用与异常边界。"
            for item in prompt_payload["evidence"]
        }
        envelope = {
            "system_id": prompt_payload["system_id"],
            "target_ids": prompt_payload["target_ids"],
            "summaries_by_node": summaries,
            "questions": [],
            "source_refs": [],
        }
        output_root = evidence_root / f"test-agent-{len(list(evidence_root.glob('test-agent-*')))}"
        output_root.mkdir(parents=True, exist_ok=False)
        output_path = output_root / "output.txt"
        output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(output_path=str(output_path))


class _WaitingContinuationAgentRunner:
    """先提出高影响疑点，再按原会话返回完整知识解释。"""

    def __init__(self) -> None:
        """初始化两阶段无费用Runner及调用证据。

        Side Effects:
            只创建内存调用列表，不读取源码、认证信息或QA。
        """

        self.requests: list[object] = []
        self.node_ids: list[str] = []

    def availability(self) -> tuple[bool, bool]:
        """声明测试环境仅Codex可用。

        Returns:
            Codex为True、Claude Code为False的固定可用性。
        """

        return True, False

    def is_available(self, agent: str) -> bool:
        """只接受测试明确提交的Codex。

        Args:
            agent: 本次初始生成或续跑声明的Agent。

        Returns:
            Agent为codex时返回True。
        """

        return agent == "codex"

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """为初始请求生成needs_input，为续跑生成completed信封。

        Args:
            request: 包含运行ID、可选原会话ID和严格提示的请求。
            source_root: 注册源码根，本桩不读取正文。
            evidence_root: 测试输出必须位于其中的私有证据根。

        Returns:
            仅公开严格JSON输出路径的轻量证据。

        Side Effects:
            记录请求并在允许目录写一份测试JSON，不运行真实Agent。
        """

        del source_root
        self.requests.append(request)
        if not request.resume_session_id:
            prompt_payload = json.loads(request.prompt.split("\n", 1)[1])
            self.node_ids = [item["node_id"] for item in prompt_payload["evidence"]]
            envelope = {
                "status": "needs_input",
                "system_id": prompt_payload["system_id"],
                "target_ids": prompt_payload["target_ids"],
                "summaries_by_node": {},
                "questions": [
                    {
                        "title": "确认异常补偿责任",
                        "detail": "源码无法证明下游失败后由本系统还是上游补偿。",
                        "affected_node_ids": self.node_ids,
                        "affected_target_ids": prompt_payload["target_ids"],
                        "category": "responsibility_boundary",
                        "why_asked": "该责任边界影响异常结果与测试判断。",
                        "answer_type": "single_choice",
                        "answer_options": ["本系统补偿", "上游补偿"],
                        "source_refs": [],
                        "impact": "high",
                    }
                ],
                "source_refs": [],
            }
        else:
            continuation_payload = json.loads(request.prompt.split("\n", 1)[1])
            assert continuation_payload["answered_questions"][0]["answer"] == "本系统补偿"
            envelope = {
                "status": "completed",
                "system_id": continuation_payload["system_id"],
                "target_ids": continuation_payload["target_ids"],
                "summaries_by_node": {
                    node_id: "异常由本系统记录并执行补偿，人工答案作为确认口径单独保留。"
                    for node_id in self.node_ids
                },
                "questions": [],
                "source_refs": [],
            }
        output_root = evidence_root / f"test-waiting-agent-{len(self.requests)}"
        output_root.mkdir(parents=True, exist_ok=False)
        output_path = output_root / "output.txt"
        output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(output_path=str(output_path))

    def read_state(self, run_id: str, evidence_root: Path) -> dict[str, object]:
        """返回原运行的稳定Codex会话ID供续跑验证。

        Args:
            run_id: 初始等待回答运行ID。
            evidence_root: 私有证据根，本桩只校验参数存在。

        Returns:
            不含认证信息的固定会话ID与完成状态。
        """

        assert run_id == self.requests[0].run_id
        assert evidence_root.name == "agent-runs"
        return {"status": "completed", "session_id": "codex-session-waiting-test"}


class _InterruptedContinuationAgentRunner(_WaitingContinuationAgentRunner):
    """让第一次续跑中断、第二次续跑完成的无费用会话替身。"""

    def __init__(self) -> None:
        """初始化两阶段Runner并记录续跑中断次数。"""

        super().__init__()
        self.interrupted_continuations = 0

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """首次续跑模拟工作进程丢失，后续沿原会话返回完整信封。

        Args:
            request: 当前初始或续跑Agent请求。
            source_root: 注册源码根，本桩不读取正文。
            evidence_root: 测试私有输出根。

        Returns:
            初始等待或第二次续跑的严格测试证据。

        Raises:
            AgentRunInterruptedError: 第一次带会话ID的续跑模拟进程丢失。
        """

        if request.resume_session_id and self.interrupted_continuations == 0:
            # 记录失败尝试的运行ID，使测试能够验证检查点切换但问题来源保持不变。
            self.requests.append(request)
            self.interrupted_continuations += 1
            raise AgentRunInterruptedError("simulated continuation worker loss")
        return super().run(request, source_root, evidence_root)

    def read_state(self, run_id: str, evidence_root: Path) -> dict[str, object]:
        """仅让原问题运行保存会话，模拟续跑在会话落盘前中断。

        Args:
            run_id: 当前工作流保存的最近一次运行ID。
            evidence_root: 私有证据根。

        Returns:
            原问题运行返回Codex会话ID，中断续跑返回没有会话ID的状态。
        """

        assert run_id in {request.run_id for request in self.requests}
        assert evidence_root.name == "agent-runs"
        if run_id == self.requests[0].run_id:
            return {"status": "completed", "session_id": "codex-session-waiting-test"}
        return {"status": "interrupted", "session_id": ""}


def _enable_codex(application: OpenTestApplication) -> _KnowledgeAgentRunner:
    """为异步生成测试保存全局Codex选择并注入无费用Runner。

    Args:
        application: 当前隔离OpenTest应用。

    Returns:
        同时供应用和知识服务使用的测试Runner。
    """

    runner = _KnowledgeAgentRunner()
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="codex"))
    application.agent_runner = runner
    application.knowledge.runner = runner
    return runner


def _seed_agent_question(
    application: OpenTestApplication,
    question_id: str = "question:agent:test-boundary",
    question_count: int = 1,
) -> KnowledgeQuestionCycle:
    """写入一条真实高影响Agent疑点并显式刷新问题周期。

    Args:
        application: 当前隔离OpenTest应用。
        question_id: 测试需要复用或区分的稳定问题ID。
        question_count: 需要验证部分应用时可创建两条独立高影响疑点。

    Returns:
        仅包含该疑点的持久化活动周期。
    """

    application.store.write_questions(
        SYSTEM_ID,
        [
            KnowledgeQuestion(
                question_id=question_id if question_count == 1 else f"{question_id}:{index + 1}",
                system_id=SYSTEM_ID,
                source="published",
                title="确认高影响业务边界",
                detail="源码与背景仍无法判断该异常结果是否需要业务补偿。",
                category="exception_strategy",
                why_asked="该结论影响异常结果与测试判定。",
                impact="high",
            )
            for index in range(question_count)
        ],
    )
    return application.get_knowledge_question_cycle(SYSTEM_ID, refresh=True)


def test_background_fields_stay_out_of_confirmation_cycle(tmp_path: Path) -> None:
    """首次四项背景由第1步表单维护，不自动进入第3步待确认周期。

    Args:
        tmp_path: pytest隔离的源码与知识根目录。

    Returns:
        None；通过空问题列表和背景流程状态验证职责分离。
    """

    application = _application(tmp_path)

    assert application.list_unified_knowledge_questions(SYSTEM_ID) == []
    assert application.get_knowledge_question_cycle(SYSTEM_ID).questions == []
    workflow = application.get_knowledge_workflow(SYSTEM_ID)
    assert workflow.current_step == "background"
    assert workflow.steps[0].status == "current"


def test_four_core_background_fields_require_explicit_completion(tmp_path: Path) -> None:
    """四项核心背景保存后仍需显式确认，且暂不确定不能完成第1步。

    Args:
        tmp_path: pytest隔离的源码与知识根目录。

    Returns:
        None；通过完成时间和后续编辑断言验证永久完成语义。
    """

    application = _application(tmp_path)
    answers = {
        "interview:system-positioning": "退款核心域服务",
        "interview:core-objects": "退款单、乘客退款项",
        "interview:primary-flow": "受理、校验、退款、回调",
        "interview:responsibility-boundaries": "上游发起申请，本系统编排退款，下游支付执行",
    }
    application.save_knowledge_background(
        SYSTEM_ID,
        KnowledgeBackgroundUpdate(answers={**answers, "interview:primary-flow": "暂不确定"}),
    )
    with pytest.raises(KnowledgeValidationError, match="四项核心背景"):
        application.confirm_knowledge_background(SYSTEM_ID)

    application.save_knowledge_background(SYSTEM_ID, KnowledgeBackgroundUpdate(answers=answers))
    completed = application.confirm_knowledge_background(SYSTEM_ID)
    completed_at = completed.background_completed_at
    assert completed_at is not None
    edited = application.save_knowledge_background(
        SYSTEM_ID,
        KnowledgeBackgroundUpdate(answers={"interview:primary-flow": "受理、审核、退款、回调"}),
    )
    assert edited.background_completed_at == completed_at
    assert application.get_knowledge_workflow(SYSTEM_ID).current_step == "generation"


def test_existing_generated_system_migrates_legacy_background_completion(tmp_path: Path) -> None:
    """旧流程已生成知识的完整四项背景应一次性迁移为步骤1完成。

    Args:
        tmp_path: pytest隔离的旧上下文与批次目录。

    Returns:
        None；完成时间取既有批次时间且不需要用户重复确认时通过。
    """

    application = _application(tmp_path)
    answers = {
        "interview:system-positioning": "退款核心域服务",
        "interview:core-objects": "退款单、乘客退款项",
        "interview:primary-flow": "受理、校验、退款、回调",
        "interview:responsibility-boundaries": "上游发起申请，本系统编排，下游支付执行",
    }
    application.save_knowledge_background(SYSTEM_ID, KnowledgeBackgroundUpdate(answers=answers))
    generated_at = utc_now()
    application.store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-legacy-background",
            system_id=SYSTEM_ID,
            scan_id="scan-legacy-background",
            target_ids=["facade:demo.RefundFacade#create"],
            status="PENDING_CONFIRMATION",
            generated_at=generated_at,
        )
    )

    migrated = application.get_knowledge_context(SYSTEM_ID)

    assert migrated.background_completed_at == generated_at


def test_question_cycle_stages_answers_without_mutating_knowledge(tmp_path: Path) -> None:
    """逐题保存应可跨应用实例恢复，且完成前不得更新人工知识真相。

    Args:
        tmp_path: pytest隔离的持久化周期与知识目录。

    Returns:
        None；通过第二个应用实例和缺答拒绝断言验证暂存边界。
    """

    application = _application(tmp_path)
    cycle = _seed_agent_question(application, question_count=2)
    question = cycle.questions[0]

    staged = application.stage_knowledge_question_cycle_answer(
        SYSTEM_ID,
        cycle.cycle_id,
        KnowledgeQuestionCycleAnswer(question_id=question.question_id, answer="仅暂存的系统定位"),
    )

    assert staged.staged_answers[question.question_id] == "仅暂存的系统定位"
    assert application.get_knowledge_context(SYSTEM_ID).interview_answers == {}
    cycle_root = application.knowledge_root / ".opentest" / "knowledge-question-cycles" / SYSTEM_ID
    assert cycle_root.stat().st_mode & 0o077 == 0
    assert (cycle_root / "active.yaml").stat().st_mode & 0o077 == 0
    assert (cycle_root / f"{cycle.cycle_id}.yaml").stat().st_mode & 0o077 == 0
    resumed_application = OpenTestApplication(application.knowledge_root)
    resumed = resumed_application.get_knowledge_question_cycle(SYSTEM_ID)
    assert resumed.staged_answers == staged.staged_answers
    resumed_application.close()

    with pytest.raises(KnowledgeValidationError, match="unanswered questions"):
        application.complete_knowledge_question_cycle(
            SYSTEM_ID,
            cycle.cycle_id,
            KnowledgeQuestionCycleCompletion(question_set_digest=cycle.question_set_digest),
        )


def test_obsolete_enum_question_cycle_becomes_stale_without_user_answers(tmp_path: Path) -> None:
    """旧枚举问题周期应自动收敛为空周期，不要求用户逐项填写。

    Args:
        tmp_path: pytest隔离的知识上下文与周期目录。

    Returns:
        None；通过旧周期STALE和新周期空问题集合断言验证策略迁移。
    """

    application = _application(tmp_path)
    context = application.get_knowledge_context(SYSTEM_ID)
    application.store.write_context(context.model_copy(update={"interview_skipped": True}))
    enum_question = KnowledgeQuestionView(
        question_id="enum-name-question:candidate:business_term:1234567890abcdef",
        system_id=SYSTEM_ID,
        source="candidate",
        title="确认业务枚举名称",
        detail="旧策略遗留的枚举维护问题。",
        status="open",
    )
    obsolete = KnowledgeQuestionCycle(
        cycle_id="question-cycle-1234567890abcdef",
        system_id=SYSTEM_ID,
        scan_id="unscanned",
        question_set_digest=application._question_set_digest([enum_question]),
        questions=[enum_question],
    )
    application.store.write_active_question_cycle(obsolete)

    refreshed = application.get_knowledge_question_cycle(SYSTEM_ID, refresh=True)
    archived = application.store.read_question_cycle(SYSTEM_ID, obsolete.cycle_id)

    assert refreshed.cycle_id != obsolete.cycle_id
    assert refreshed.questions == []
    assert refreshed.staged_answers == {}
    assert archived is not None
    assert archived.status == KnowledgeQuestionCycleStatus.STALE


def test_question_cycle_rejects_symbolic_link_parent(tmp_path: Path) -> None:
    """周期目录被替换为符号链接时不得读取或写出知识仓库边界。

    Args:
        tmp_path: pytest隔离的知识根和工作区外目标目录。

    Returns:
        None；通过稳定领域异常断言验证私有周期路径边界。
    """

    application = _application(tmp_path)
    outside = tmp_path / "outside-cycles"
    outside.mkdir()
    cycle_root = application.knowledge_root / ".opentest" / "knowledge-question-cycles"
    cycle_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(KnowledgeValidationError, match="parent must be a real directory"):
        application.get_knowledge_question_cycle(SYSTEM_ID)


def test_legacy_background_narrative_is_prefilled_without_creating_questions(tmp_path: Path) -> None:
    """旧自由叙述应继续可编辑，但不自动产生通用待确认问题。

    Args:
        tmp_path: pytest隔离的旧背景叙述、周期与知识目录。

    Returns:
        None；通过上下文预填和空周期断言验证迁移边界。
    """

    application = _application(tmp_path)
    application.save_knowledge_context_narrative(
        SYSTEM_ID,
        KnowledgeContextNarrativeUpdate(
            system_purpose="旧版系统用途",
            upstream_entry_narrative="旧版上下游说明",
        ),
    )

    cycle = application.get_knowledge_question_cycle(SYSTEM_ID)
    context = application.get_knowledge_context(SYSTEM_ID)
    assert context.system_purpose == "旧版系统用途"
    assert context.upstream_entry_narrative == "旧版上下游说明"
    assert cycle.questions == []
    assert cycle.staged_answers == {}


def test_question_cycle_completes_once_and_recalculates_after_all_answers(tmp_path: Path) -> None:
    """整轮答案齐备后才应用人工知识，并且重复完成返回同一重算任务。

    Args:
        tmp_path: pytest隔离的周期、任务与知识目录。

    Returns:
        None；通过任务前后重复请求断言验证持久幂等。
    """

    application = _application(tmp_path)
    cycle = _seed_agent_question(application)
    for question in cycle.questions:
        cycle = application.stage_knowledge_question_cycle_answer(
            SYSTEM_ID,
            cycle.cycle_id,
            KnowledgeQuestionCycleAnswer(
                question_id=question.question_id,
                answer=f"已确认：{question.category}",
            ),
        )

    request = KnowledgeQuestionCycleCompletion(question_set_digest=cycle.question_set_digest)
    task = application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    duplicate = application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    assert duplicate.task_id == task.task_id
    _wait_for_task(application, task.task_id)
    completed_task = application.tasks.get(task.task_id)
    assert completed_task.progress is not None
    assert completed_task.progress.message == "剩余问题 0，已知未知 0"

    answered = next(
        question
        for question in application.store.list_questions(SYSTEM_ID)
        if question.question_id == "question:agent:test-boundary"
    )
    assert answered.status == "answered"
    next_cycle = application.get_knowledge_question_cycle(SYSTEM_ID)
    assert next_cycle.cycle_id != cycle.cycle_id
    assert next_cycle.questions == []
    completed_duplicate = application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    assert completed_duplicate.task_id == task.task_id


def test_question_cycle_rejects_stale_question_set_and_preserves_staged_answers(tmp_path: Path) -> None:
    """旧页面周期在问题真相变化后应返回stale，且不丢失已暂存答案。

    Args:
        tmp_path: pytest隔离的周期与问题真相目录。

    Returns:
        None；通过stale异常和周期文件断言验证冲突保护。
    """

    application = _application(tmp_path)
    cycle = _seed_agent_question(application)
    for question in cycle.questions:
        cycle = application.stage_knowledge_question_cycle_answer(
            SYSTEM_ID,
            cycle.cycle_id,
            KnowledgeQuestionCycleAnswer(question_id=question.question_id, answer="本轮暂存答案"),
        )
    changed_question = cycle.questions[0]
    application.answer_unified_knowledge_question(
        SYSTEM_ID,
        KnowledgeConfirmation(question_id=changed_question.question_id, answer="其他页面已确认"),
    )

    with pytest.raises(KnowledgeQuestionCycleStaleError, match="questions changed"):
        application.complete_knowledge_question_cycle(
            SYSTEM_ID,
            cycle.cycle_id,
            KnowledgeQuestionCycleCompletion(question_set_digest=cycle.question_set_digest),
        )
    assert application.store.read_active_question_cycle(SYSTEM_ID).staged_answers == cycle.staged_answers


def test_question_cycle_recovers_when_task_submission_initially_fails(tmp_path: Path, monkeypatch) -> None:
    """任务提交失败应保留BLOCKED周期，并允许相同答案幂等重试。

    Args:
        tmp_path: pytest隔离的周期与任务目录。
        monkeypatch: 临时替换任务提交边界以模拟失败。

    Returns:
        None；通过BLOCKED状态和后续成功任务断言验证恢复。
    """

    application = _application(tmp_path)
    cycle = _seed_agent_question(application)
    for question in cycle.questions:
        cycle = application.stage_knowledge_question_cycle_answer(
            SYSTEM_ID,
            cycle.cycle_id,
            KnowledgeQuestionCycleAnswer(question_id=question.question_id, answer=f"确认 {question.question_id}"),
        )
    request = KnowledgeQuestionCycleCompletion(question_set_digest=cycle.question_set_digest)
    original_submit = application._submit_question_cycle_reanalysis

    def fail_submission(_cycle):
        """模拟线程池提交边界失败，不修改任何任务或周期文件。

        Args:
            _cycle: 调用方传入但故障桩不会使用的问题周期。

        Raises:
            RuntimeError: 始终模拟本地任务无法提交。
        """

        raise RuntimeError("simulated submit failure")

    monkeypatch.setattr(application, "_submit_question_cycle_reanalysis", fail_submission)
    with pytest.raises(RuntimeError, match="simulated submit failure"):
        application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    blocked = application.store.read_active_question_cycle(SYSTEM_ID)
    assert blocked is not None and blocked.status.value == "BLOCKED"

    monkeypatch.setattr(application, "_submit_question_cycle_reanalysis", original_submit)
    task = application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    _wait_for_task(application, task.task_id)


def test_question_cycle_retries_failed_task_without_intermediate_get(tmp_path: Path, monkeypatch) -> None:
    """失败任务后的重复完成POST应直接创建新任务，不依赖客户端先读取周期。

    Args:
        tmp_path: pytest隔离的周期、任务和知识目录。
        monkeypatch: 首次完成时替换为确定失败的本地重算任务。

    Returns:
        None；通过新任务ID和成功终态断言验证POST自身恢复契约。
    """

    application = _application(tmp_path)
    cycle = _seed_agent_question(application)
    for question in cycle.questions:
        cycle = application.stage_knowledge_question_cycle_answer(
            SYSTEM_ID,
            cycle.cycle_id,
            KnowledgeQuestionCycleAnswer(question_id=question.question_id, answer="任务失败后重试"),
        )
    request = KnowledgeQuestionCycleCompletion(question_set_digest=cycle.question_set_digest)
    original_submit = application._submit_question_cycle_reanalysis

    def submit_failed_task(failed_cycle):
        """提交一个立即失败的本地任务以验证完成接口协调终态。

        Args:
            failed_cycle: 已应用答案并绑定固定扫描的问题周期。

        Returns:
            由本地任务管理器持久化的失败任务记录。
        """

        def fail_job():
            """模拟重算线程失败并保留任务证据。

            Raises:
                RuntimeError: 始终表示本地重算失败。
            """

            raise RuntimeError("simulated reanalysis failure")

        return application.tasks.submit(
            "knowledge-question-reanalysis",
            failed_cycle.system_id,
            fail_job,
            exclusive=True,
        )

    monkeypatch.setattr(application, "_submit_question_cycle_reanalysis", submit_failed_task)
    failed_task = application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    for _ in range(200):
        if application.tasks.get(failed_task.task_id).status.value == "failed":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("simulated reanalysis task did not fail")

    monkeypatch.setattr(application, "_submit_question_cycle_reanalysis", original_submit)
    retried_task = application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    assert retried_task.task_id != failed_task.task_id
    _wait_for_task(application, retried_task.task_id)


def test_question_cycle_preserves_retry_after_partial_answer_application(tmp_path: Path, monkeypatch) -> None:
    """整轮答案应用中途失败时应保留BLOCKED周期并允许幂等重放。

    Args:
        tmp_path: pytest隔离的周期和知识真相目录。
        monkeypatch: 第二项答案处注入一次应用失败。

    Returns:
        None；通过原周期重试成功断言验证半应用恢复边界。
    """

    application = _application(tmp_path)
    cycle = _seed_agent_question(application, question_count=2)
    for question in cycle.questions:
        cycle = application.stage_knowledge_question_cycle_answer(
            SYSTEM_ID,
            cycle.cycle_id,
            KnowledgeQuestionCycleAnswer(question_id=question.question_id, answer="统一应用答案"),
        )
    request = KnowledgeQuestionCycleCompletion(question_set_digest=cycle.question_set_digest)
    original_apply = application._apply_cycle_question_answer
    applied_count = 0

    def fail_second_answer(system_id, question, answer):
        """首项真实应用后在第二项前失败一次。

        Args:
            system_id: 当前问题周期所属系统。
            question: 即将应用的问题快照。
            answer: 用户已暂存的明确答案。

        Raises:
            RuntimeError: 第二项答案首次执行时模拟存储失败。
        """

        nonlocal applied_count
        applied_count += 1
        if applied_count == 2:
            raise RuntimeError("simulated partial apply failure")
        original_apply(system_id, question, answer)

    monkeypatch.setattr(application, "_apply_cycle_question_answer", fail_second_answer)
    with pytest.raises(RuntimeError, match="simulated partial apply failure"):
        application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    blocked = application.get_knowledge_question_cycle(SYSTEM_ID)
    assert blocked.cycle_id == cycle.cycle_id
    assert blocked.status.value == "BLOCKED"

    monkeypatch.setattr(application, "_apply_cycle_question_answer", original_apply)
    task = application.complete_knowledge_question_cycle(SYSTEM_ID, cycle.cycle_id, request)
    _wait_for_task(application, task.task_id)


def test_blocked_question_cycle_becomes_stale_after_new_scan(tmp_path: Path) -> None:
    """失败周期绑定的扫描变化后应创建新周期并继承稳定问题答案。

    Args:
        tmp_path: pytest隔离的两个Manifest、周期和知识目录。

    Returns:
        None；通过新周期ID和继承答案断言验证stale恢复。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    baseline = application.knowledge.git_repository.capture(source_root)
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    first_manifest = ScanManifest(scan_id="scan-cycle-blocked-v1", system_id=SYSTEM_ID, baseline=baseline)
    artifacts.write_manifest(first_manifest)
    artifacts.publish_latest(SYSTEM_ID, first_manifest.scan_id)
    cycle = _seed_agent_question(application)
    first_question = cycle.questions[0]
    cycle = application.stage_knowledge_question_cycle_answer(
        SYSTEM_ID,
        cycle.cycle_id,
        KnowledgeQuestionCycleAnswer(question_id=first_question.question_id, answer="可继承答案"),
    )
    application.store.write_active_question_cycle(
        cycle.model_copy(
            update={
                "status": KnowledgeQuestionCycleStatus.BLOCKED,
                "reanalysis_input_digest": cycle.question_set_digest,
            }
        )
    )
    second_manifest = ScanManifest(scan_id="scan-cycle-blocked-v2", system_id=SYSTEM_ID, baseline=baseline)
    artifacts.write_manifest(second_manifest)
    artifacts.publish_latest(SYSTEM_ID, second_manifest.scan_id)

    refreshed = application.get_knowledge_question_cycle(SYSTEM_ID, refresh=True)

    assert refreshed.cycle_id != cycle.cycle_id
    assert refreshed.scan_id == second_manifest.scan_id
    assert refreshed.staged_answers[first_question.question_id] == "可继承答案"


def test_question_cycle_http_routes_stage_without_confirmation_and_return_stale_conflict(tmp_path: Path) -> None:
    """三个周期HTTP接口应共享系统范围，并以稳定409拒绝旧问题集合。

    Args:
        tmp_path: pytest隔离的FastAPI应用、周期与知识目录。

    Returns:
        None；通过GET、PUT和POST响应断言验证HTTP契约。
    """

    application = _application(tmp_path)
    _seed_agent_question(application)
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        loaded = client.get(f"/api/v2/systems/{SYSTEM_ID}/knowledge/question-cycle")
        assert loaded.status_code == 200
        cycle = loaded.json()["cycle"]
        for question in cycle["questions"]:
            staged = client.put(
                f"/api/v2/systems/{SYSTEM_ID}/knowledge/question-cycles/{cycle['cycle_id']}"
                f"/answers/{question['question_id']}",
                json={"question_id": question["question_id"], "answer": "HTTP暂存答案"},
            )
            assert staged.status_code == 200
        assert application.get_knowledge_context(SYSTEM_ID).interview_answers == {}

        # 兼容旧接口模拟其他页面确认，使固定周期摘要在完成前变旧。
        first_question = cycle["questions"][0]
        application.answer_unified_knowledge_question(
            SYSTEM_ID,
            KnowledgeConfirmation(question_id=first_question["question_id"], answer="其他页面确认"),
        )
        stale = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/question-cycles/{cycle['cycle_id']}/complete",
            json={"question_set_digest": cycle["question_set_digest"]},
        )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "knowledge_question_cycle_stale"
    assert application.store.read_active_question_cycle(SYSTEM_ID).staged_answers


def test_object_draft_generation_requires_background_interview_gate(tmp_path: Path) -> None:
    """背景与术语未显式完成时不得提前运行指定Agent生成对象知识。"""

    application = _application(tmp_path)

    with pytest.raises(KnowledgeValidationError, match="background and business terms"):
        application.knowledge.generate_drafts(
            KnowledgeGenerationBatchRequest(
                system_id=SYSTEM_ID,
                target_ids=["job:demo.PendingJob"],
                scan_id="latest",
                agent="codex",
                confirmed=True,
            )
        )


def test_term_edit_marks_only_affected_target_stale_then_background_marks_all(tmp_path: Path) -> None:
    """术语优先精确标记目标，系统级背景变化才默认影响全部知识。

    Args:
        tmp_path: Pytest提供的隔离源码、Manifest和知识真相目录。

    Side Effects:
        只使用无费用测试Runner生成两个本地目标，不访问真实Agent或QA。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    entries = []
    for class_name in ("TimeoutJob", "CallbackJob"):
        source_path = source_root / f"{class_name}.java"
        source_path.write_text(
            f"package demo; class {class_name} {{ void execute() {{ process(); }} void process() {{}} }}",
            encoding="utf-8",
        )
        entries.append(
            EntryPoint(
                entry_id=f"job:demo.{class_name}",
                system_id=SYSTEM_ID,
                kind="job",
                display_name=class_name,
                source_id=f"demo.{class_name}",
                source_path=str(source_path),
            )
        )
    baseline = application.knowledge.git_repository.capture(source_root)
    manifest = ScanManifest(
        scan_id="scan-context-stale-targets",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=entries,
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    _enable_codex(application)
    for entry in entries:
        # 产品入口一次只处理一个目标；测试依次生成两项以建立术语过期范围基线。
        application.knowledge.generate_drafts(
            KnowledgeGenerationBatchRequest(
                system_id=SYSTEM_ID,
                target_ids=[entry.entry_id],
                scan_id=manifest.scan_id,
                agent="codex",
                confirmed=True,
            ),
            runner=_KnowledgeAgentRunner(),
        )

    application.create_knowledge_context_candidate(
        SYSTEM_ID,
        KnowledgeContextCandidateCreate(
            kind="BUSINESS_TERM",
            name="退款时限",
            business_meaning="超过时限后关闭退款任务",
            affected_target_ids=[entries[0].entry_id],
        ),
    )
    term_catalog = application.get_scan_catalog(SYSTEM_ID, "latest")
    term_statuses = {target.target_id: target.knowledge_status for target in term_catalog.targets}
    assert term_statuses[entries[0].entry_id].value == "STALE"
    assert term_statuses[entries[1].entry_id].value == "GENERATED"

    application.save_knowledge_background(
        SYSTEM_ID,
        KnowledgeBackgroundUpdate(answers={"interview:primary-flow": "新的系统级退款主流程"}),
    )
    background_catalog = application.get_scan_catalog(SYSTEM_ID, "latest")
    background_statuses = {target.target_id: target.knowledge_status for target in background_catalog.targets}
    assert all(background_statuses[entry.entry_id].value == "STALE" for entry in entries)


def test_generation_request_rejects_multiple_targets(tmp_path: Path) -> None:
    """旧批量契约必须拒绝多个目标，避免页面或脚本绕过单目标流程。

    Args:
        tmp_path: Pytest提供的隔离源码、Manifest和知识目录。

    Returns:
        None；请求模型在创建任务前明确拒绝两个目标时通过。
    """

    # 同一批次同时包含空入口和真实外部调用，验证浅层目标不会制造节点或拖垮其他目标。
    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    noop_path = source_root / "NoopJob.java"
    business_path = source_root / "BusinessJob.java"
    noop_path.write_text("package demo; class NoopJob { void execute() {} }", encoding="utf-8")
    business_path.write_text(
        "package demo; class BusinessJob { void execute() { refundClient.query(); } }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    target_ids = ["job:demo.NoopJob", "job:demo.BusinessJob"]
    manifest = ScanManifest(
        scan_id="scan-bulk-minimal-entry",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=target_ids[0],
                system_id=SYSTEM_ID,
                kind="job",
                display_name="空任务入口",
                source_id="demo.NoopJob",
                source_path=str(noop_path),
            ),
            EntryPoint(
                entry_id=target_ids[1],
                system_id=SYSTEM_ID,
                kind="job",
                display_name="业务任务入口",
                source_id="demo.BusinessJob",
                source_path=str(business_path),
            ),
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    _enable_codex(application)

    # 兼容路由仍保留模型名称，但领域上限保证任何调用方都不能提交两个付费目标。
    with pytest.raises(ValueError, match="at most 1 item"):
        KnowledgeGenerationBatchRequest(
            system_id=SYSTEM_ID,
            target_ids=target_ids,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
        )


def test_bulk_generation_publishes_code_and_agent_knowledge_without_generic_questions(tmp_path: Path) -> None:
    """指定Agent生成应发布代码事实与解释，且不制造固定业务口径问题。

    Args:
        tmp_path: pytest隔离的源码、Manifest、草稿批次和知识目录。

    Returns:
        None；通过实际Agent、节点来源、空问题周期和重复生成断言验证SOP闭环。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    job_path = source_root / "TimeoutJob.java"
    job_path.write_text(
        "package demo; class TimeoutJob { void doExecute() { expireOrders(); } void expireOrders() {} }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    entry_id = "job:demo.TimeoutJob"
    manifest = ScanManifest(
        scan_id="scan-bulk-knowledge-sop",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="超时订单处理Job",
                source_id="demo.TimeoutJob",
                source_path=str(job_path),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    _enable_codex(application)

    request = KnowledgeGenerationBatchRequest(
        system_id=SYSTEM_ID,
        target_ids=[entry_id],
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
    )
    assert request.agent == "codex"
    task = application.submit_knowledge_generation_batch(request)
    _wait_for_task(application, task.task_id)
    completed = application.tasks.get(task.task_id)
    batch = application.store.read_draft_batch(SYSTEM_ID, completed.result["batch_id"])
    nodes = [node for node, _, _ in application.store.list_nodes(SYSTEM_ID)]

    assert completed.result["target_count"] == 1
    assert completed.result["agent"] == "codex"
    assert completed.result["code_fact_count"] == len(batch.drafts)
    assert completed.result["inferred_fact_count"] == len(batch.drafts)
    assert completed.result["question_count"] == 0
    assert nodes
    assert {node.status.value for node in nodes} == {"inferred"}
    assert batch.status == "PUBLISHED"
    assert application.get_knowledge_question_cycle(SYSTEM_ID).questions == []

    # 模拟独立修订后的人工正文；重复确定性生成只能复用答案，不能反向覆盖该正文。
    protected_node, _, protected_content_before = application.store.get_node(
        SYSTEM_ID,
        nodes[0].node_id,
    )
    protected_path = application.store.node_path(protected_node)
    protected_content = f"{protected_content_before.rstrip()}\n\n人工后续修订不可覆盖\n"
    application.store.write_node(
        protected_node.model_copy(update={"status": KnowledgeStatus.USER_CONFIRMED}),
        application.knowledge._auto_content(protected_content_before),
    )
    application.store.update_node_status(SYSTEM_ID, protected_node.node_id, KnowledgeStatus.USER_CONFIRMED)
    protected_path.write_text(
        f"{protected_path.read_text(encoding='utf-8').rstrip()}\n\n人工后续修订不可覆盖\n",
        encoding="utf-8",
    )

    # 同一源码快照再次生成时继承稳定问题ID的人工答案，不得重新形成开放问题。
    repeated_task = application.submit_knowledge_generation_batch(request)
    _wait_for_task(application, repeated_task.task_id)
    repeated = application.tasks.get(repeated_task.task_id)
    repeated_batch = application.store.read_draft_batch(SYSTEM_ID, repeated.result["batch_id"])
    assert repeated.result["question_count"] == 0
    assert repeated_batch.status == "PUBLISHED"
    assert repeated_batch.questions == []
    assert "人工后续修订不可覆盖" in protected_path.read_text(encoding="utf-8")

    # 已有人工作为共享节点真相时，新周期明确答案应安全追加，且不能丢失旧正文或人工区。
    supplemental_note = "人工确认：新增共享节点业务规则"
    supplemental_drafts = [
        draft.model_copy(
            update={
                "status": "DRAFT",
                "answer_notes": [*draft.answer_notes, supplemental_note],
                "content": f"{draft.content.rstrip()}\n\n刷新后的自动事实\n",
            }
        )
        if draft.node.node_id == protected_node.node_id
        else draft
        for draft in repeated_batch.drafts
    ]
    supplemental_batch = repeated_batch.model_copy(
        update={
            "batch_id": "knowledge-workflow-2222222222222222",
            "status": "PENDING_CONFIRMATION",
            "drafts": supplemental_drafts,
        }
    )
    application.store.write_draft_batch(supplemental_batch)
    settled_supplement = application.knowledge.publish_ready_drafts(
        SYSTEM_ID,
        supplemental_batch.batch_id,
    )
    supplemented_content = protected_path.read_text(encoding="utf-8")
    assert settled_supplement.status == "PUBLISHED"
    assert "人工后续修订不可覆盖" in supplemented_content
    assert supplemental_note in supplemented_content
    assert "刷新后的自动事实" in supplemented_content

    # 旧自动区已有确认段时，下一轮的新答案与新证据元数据仍必须同时发布。
    second_note = "人工确认：第二轮新增异常责任边界"
    second_drafts = [
        draft.model_copy(
            update={
                "status": "DRAFT",
                "answer_notes": [*draft.answer_notes, second_note],
                "content": f"{draft.content.rstrip()}\n\n第二轮刷新自动事实\n",
                "node": draft.node.model_copy(
                    update={
                        "summary": "第二轮源码与Agent摘要",
                        "confidence": 0.91,
                        "metadata": {**draft.node.metadata, "scan_id": "scan-refreshed-evidence"},
                    }
                ),
            }
        )
        if draft.node.node_id == protected_node.node_id
        else draft
        for draft in settled_supplement.drafts
    ]
    second_batch = settled_supplement.model_copy(
        update={
            "batch_id": "knowledge-workflow-3333333333333333",
            "status": "PENDING_CONFIRMATION",
            "drafts": second_drafts,
        }
    )
    application.store.write_draft_batch(second_batch)
    application.knowledge.publish_ready_drafts(SYSTEM_ID, second_batch.batch_id)
    refreshed_node, _, second_content = application.store.get_node(SYSTEM_ID, protected_node.node_id)
    assert supplemental_note in second_content
    assert second_note in second_content
    assert "第二轮刷新自动事实" in second_content
    assert refreshed_node.status == KnowledgeStatus.USER_CONFIRMED
    assert refreshed_node.summary == "第二轮源码与Agent摘要"
    assert refreshed_node.confidence == 0.91
    assert refreshed_node.metadata["scan_id"] == "scan-refreshed-evidence"


def test_agent_question_answer_continues_original_session_and_preserves_sources(tmp_path: Path) -> None:
    """Agent等待回答后应以原会话续跑，并分别保留人工答案与Agent解释来源。

    Args:
        tmp_path: pytest隔离的源码、Manifest、问题和知识目录。

    Returns:
        None；运行ID更换、会话ID复用、问题闭合和来源正文均正确时通过。

    Side Effects:
        只调用无费用测试Runner，不访问真实Codex、QA或Fixture。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    job_path = source_root / "CompensateJob.java"
    job_path.write_text(
        "package demo; class CompensateJob { void execute() { refundClient.query(); } }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    target_id = "job:demo.CompensateJob"
    manifest = ScanManifest(
        scan_id="scan-agent-waiting-continuation",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=target_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="补偿任务",
                source_id="demo.CompensateJob",
                source_path=str(job_path),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    runner = _WaitingContinuationAgentRunner()

    waiting = application.knowledge.generate_drafts(
        KnowledgeGenerationBatchRequest(
            system_id=SYSTEM_ID,
            target_ids=[target_id],
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
        ),
        runner=runner,
    )
    first_run_id = waiting.active_run_id
    question = waiting.questions[0]
    assert waiting.outcomes[0].status.value == "WAITING_FOR_INPUT"
    assert first_run_id == runner.requests[0].run_id
    assert question.agent_run_id == first_run_id
    assert all(node.status.value == "code_verified" for node, _, _ in application.store.list_nodes(SYSTEM_ID))

    application.knowledge.answer_draft_question(
        SYSTEM_ID,
        waiting.batch_id,
        KnowledgeConfirmation(
            question_id=question.question_id,
            answer="本系统补偿",
            confirmed_node_ids=question.affected_node_ids,
        ),
    )
    question_set_digest = "a" * 64
    waiting = application.store.read_draft_batch(SYSTEM_ID, waiting.batch_id).model_copy(
        update={
            "waiting_question_cycle_id": "question-cycle-aaaaaaaaaaaaaaaa",
            "waiting_question_set_digest": question_set_digest,
        }
    )
    application.store.write_draft_batch(waiting)
    completed = application.knowledge.continue_generation(
        SYSTEM_ID,
        waiting.batch_id,
        "codex",
        question_set_digest,
        runner=runner,
    )

    assert runner.requests[1].resume_session_id == "codex-session-waiting-test"
    assert runner.requests[1].run_id != first_run_id
    assert completed.active_run_id == ""
    assert completed.outcomes[0].status.value == "AGENT_ENRICHED"
    node, _, content = application.store.get_node(SYSTEM_ID, completed.drafts[0].node.node_id)
    assert node.status.value == "user_confirmed"
    assert "人工确认：本系统补偿" in content
    assert "Agent代码解释（INFERRED）" in content


def test_interrupted_continuation_keeps_original_question_scope_for_retry(tmp_path: Path) -> None:
    """续跑中断后应保留原问题来源，并从最近会话检查点再次继续。

    Args:
        tmp_path: pytest隔离的源码、Manifest、草稿和无费用Runner目录。

    Returns:
        None；第二次续跑仍携带原人工答案且最终完成时通过。

    Side Effects:
        只写测试知识资产，不启动真实Codex或访问QA。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    job_path = source_root / "RetryCompensateJob.java"
    job_path.write_text(
        "package demo; class RetryCompensateJob { void execute() { refundClient.query(); } }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    target_id = "job:demo.RetryCompensateJob"
    manifest = ScanManifest(
        scan_id="scan-agent-interrupted-continuation",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=target_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="重试补偿任务",
                source_id="demo.RetryCompensateJob",
                source_path=str(job_path),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    runner = _InterruptedContinuationAgentRunner()
    waiting = application.knowledge.generate_drafts(
        KnowledgeGenerationBatchRequest(
            system_id=SYSTEM_ID,
            target_ids=[target_id],
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
        ),
        runner=runner,
    )
    first_run_id = waiting.active_run_id
    question = waiting.questions[0]
    application.knowledge.answer_draft_question(
        SYSTEM_ID,
        waiting.batch_id,
        KnowledgeConfirmation(
            question_id=question.question_id,
            answer="本系统补偿",
            confirmed_node_ids=question.affected_node_ids,
        ),
    )
    question_set_digest = "b" * 64
    bound = application.store.read_draft_batch(SYSTEM_ID, waiting.batch_id).model_copy(
        update={
            "waiting_question_cycle_id": "question-cycle-bbbbbbbbbbbbbbbb",
            "waiting_question_set_digest": question_set_digest,
        }
    )
    application.store.write_draft_batch(bound)

    with pytest.raises(AgentRunInterruptedError):
        application.knowledge.continue_generation(
            SYSTEM_ID,
            waiting.batch_id,
            "codex",
            question_set_digest,
            runner=runner,
        )
    interrupted = application.store.read_draft_batch(SYSTEM_ID, waiting.batch_id)
    assert interrupted.active_run_id != first_run_id
    assert interrupted.question_run_id == first_run_id

    completed = application.knowledge.continue_generation(
        SYSTEM_ID,
        waiting.batch_id,
        "codex",
        question_set_digest,
        runner=runner,
    )

    assert completed.outcomes[0].status.value == "AGENT_ENRICHED"
    assert runner.requests[-1].resume_session_id == "codex-session-waiting-test"
    continuation_payload = json.loads(runner.requests[-1].prompt.split("\n", 1)[1])
    assert continuation_payload["answered_questions"][0]["answer"] == "本系统补偿"


def test_continuation_requires_the_bound_question_cycle_to_be_completed(tmp_path: Path) -> None:
    """续跑费用确认必须绑定原固定问题集合且仅在周期完成后生效。

    Args:
        tmp_path: pytest隔离的工作流和问题周期存储目录。

    Returns:
        None；开放周期和错误摘要均被拒绝，完成的原周期通过校验时结束。

    Side Effects:
        只写本地测试检查点，不启动Agent或提交后台任务。
    """

    application = _application(tmp_path)
    target_id = "facade:demo.QueryFacade#queryList"
    run_id = "agent-dddddddddddddddd"
    question_id = "question:agent:continuation-boundary"
    batch = KnowledgeGenerationWorkflowBatch(
        batch_id="knowledge-workflow-continuation-boundary",
        system_id=SYSTEM_ID,
        scan_id="scan-continuation-boundary",
        target_ids=[target_id],
        status="PENDING_CONFIRMATION",
        active_run_id=run_id,
        question_run_id=run_id,
        active_target_id=target_id,
        questions=[
            KnowledgeQuestion(
                question_id=question_id,
                system_id=SYSTEM_ID,
                source="draft",
                title="确认查询边界",
                detail="源码仍无法判断查询失败口径。",
                affected_target_ids=[target_id],
                why_asked="影响查询异常结果。",
                agent_run_id=run_id,
                agent="codex",
            )
        ],
        outcomes=[
            KnowledgeTargetGenerationOutcome(
                target_id=target_id,
                status="WAITING_FOR_INPUT",
                agent="codex",
                question_count=1,
            )
        ],
    )
    application.store.write_draft_batch(batch)
    digest = "c" * 64
    cycle = KnowledgeQuestionCycle(
        cycle_id="question-cycle-cccccccccccccccc",
        system_id=SYSTEM_ID,
        scan_id="unscanned",
        question_set_digest=digest,
        questions=[
            KnowledgeQuestionView(
                question_id=question_id,
                system_id=SYSTEM_ID,
                source="draft",
                title="确认查询边界",
                detail="源码仍无法判断查询失败口径。",
                affected_target_ids=[target_id],
                why_asked="影响查询异常结果。",
                agent_run_id=run_id,
                agent="codex",
            )
        ],
    )
    application.store.write_active_question_cycle(cycle)
    application.knowledge.bind_waiting_question_cycle(SYSTEM_ID, batch.batch_id, cycle.cycle_id, digest)
    request = KnowledgeAgentContinuationRequest(
        system_id=SYSTEM_ID,
        agent="codex",
        question_set_digest=digest,
        confirmed=True,
    )

    with pytest.raises(KnowledgeValidationError, match="complete the waiting question cycle"):
        application._validate_generation_continuation_cycle(batch.batch_id, request)
    with pytest.raises(KnowledgeValidationError, match="does not match"):
        application._validate_generation_continuation_cycle(
            batch.batch_id,
            request.model_copy(update={"question_set_digest": "d" * 64}),
        )

    application.store.write_active_question_cycle(
        cycle.model_copy(update={"status": KnowledgeQuestionCycleStatus.COMPLETED, "updated_at": utc_now()})
    )
    application._validate_generation_continuation_cycle(batch.batch_id, request)

def test_latest_target_batch_removes_resolved_agent_question_from_current_cycle(tmp_path: Path) -> None:
    """目标新批次不再提出疑点时，旧Agent开放问题只保留历史文件而不进入当前周期。

    Args:
        tmp_path: pytest隔离的知识根、公共问题和两代草稿批次。

    Returns:
        None；统一问题列表和当前周期都不再包含旧疑点时通过。
    """

    application = _application(tmp_path)
    target_id = "facade:demo.RefundFacade#create"
    question = KnowledgeQuestion(
        question_id="question:agent:resolved-boundary",
        system_id=SYSTEM_ID,
        source="draft",
        title="确认退款责任边界",
        detail="旧代码无法判断失败补偿责任。",
        affected_target_ids=[target_id],
    )
    application.store.write_questions(SYSTEM_ID, [question])
    application.store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-old-question",
            system_id=SYSTEM_ID,
            scan_id="scan-question-history",
            target_ids=[target_id],
            status="PENDING_CONFIRMATION",
            questions=[question],
        )
    )
    assert any(item.question_id == question.question_id for item in application.list_unified_knowledge_questions(SYSTEM_ID))

    application.store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-agent-failed-question",
            system_id=SYSTEM_ID,
            scan_id="scan-question-history",
            target_ids=[target_id],
            status="PUBLISHED",
            outcomes=[
                KnowledgeTargetGenerationOutcome(
                    target_id=target_id,
                    status="CODE_ONLY",
                    agent="codex",
                    safe_error="指定Agent分析失败",
                )
            ],
        )
    )
    assert any(item.question_id == question.question_id for item in application.list_unified_knowledge_questions(SYSTEM_ID))

    application.store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-resolved-question",
            system_id=SYSTEM_ID,
            scan_id="scan-question-history",
            target_ids=[target_id],
            status="PUBLISHED",
            outcomes=[
                KnowledgeTargetGenerationOutcome(
                    target_id=target_id,
                    status="AGENT_ENRICHED",
                    agent="codex",
                )
            ],
        )
    )

    current_questions = application.list_unified_knowledge_questions(SYSTEM_ID)
    assert all(item.question_id != question.question_id for item in current_questions)
    assert all(item.question_id != question.question_id for item in application.get_knowledge_question_cycle(SYSTEM_ID, refresh=True).questions)


def test_candidate_terms_remain_editable_without_joining_question_cycle(tmp_path: Path) -> None:
    """开放候选可在背景页编辑，但不自动进入高影响待确认周期。

    Args:
        tmp_path: pytest隔离的候选、问题与知识目录。

    Returns:
        None；通过上下文候选和空问题列表断言验证职责分离。
    """

    application = _application(tmp_path)
    candidate = application.create_knowledge_context_candidate(
        SYSTEM_ID,
        KnowledgeContextCandidateCreate(
            kind=KnowledgeContextCandidateKind.BUSINESS_TERM,
            name="出票单",
            business_meaning="供应链出票过程中的业务订单",
        ),
    )
    # 人工候选默认已确认；改成开放候选以验证对象级问题门禁。
    application.update_knowledge_context_candidate(
        SYSTEM_ID,
        candidate.candidate_id,
        KnowledgeContextCandidateUpdate(
            status=KnowledgeContextCandidateStatus.OPEN,
            business_meaning="",
        ),
    )
    questions = application.list_unified_knowledge_questions(SYSTEM_ID)
    context = application.get_knowledge_context(SYSTEM_ID)
    assert any(item.candidate_id == candidate.candidate_id for item in context.candidates)
    assert all(question.source != "candidate" for question in questions)


def test_semantic_enums_publish_comment_defaults_without_questions(tmp_path: Path) -> None:
    """枚举应完整发布代码默认值，不再为低价值名称或常量生成问题。

    Args:
        tmp_path: pytest隔离的Java源码、Manifest与候选目录。

    Returns:
        None；通过候选状态、字段来源和空问题集合断言验证默认吸收。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "RefundEnums.java"
    enum_path.write_text(
        "package demo; class RefundEnums { RefundOrderStateEnum state; RefundChannelEnum channel; }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    source_ref = SourceReference(path="RefundEnums.java", symbol="demo.RefundEnums", line=1)
    manifest = ScanManifest(
        scan_id="scan-semantic-enum-candidates",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id="facade:demo.RefundFacade#create",
                system_id=SYSTEM_ID,
                kind="facade",
                display_name="创建退票单",
                source_id="demo.RefundFacade#create",
                source_path=str(enum_path),
                request_type="demo.RefundOrderStateEnum",
                response_type="demo.RefundChannelEnum",
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            types=[
                SemanticTypeDefinition(
                    symbol_id="demo.RefundOrderStateEnum",
                    qualified_class_name="demo.RefundOrderStateEnum",
                    simple_name="RefundOrderStateEnum",
                    kind="enum",
                    javadoc_summary="退票单处理状态",
                    source_ref=source_ref,
                ),
                SemanticTypeDefinition(
                    symbol_id="demo.RefundChannelEnum",
                    qualified_class_name="demo.RefundChannelEnum",
                    simple_name="RefundChannelEnum",
                    kind="enum",
                    javadoc_summary="退票渠道",
                    source_ref=source_ref,
                ),
            ],
            enum_values=[
                SemanticEnumValue(
                    enum_type="demo.RefundOrderStateEnum",
                    code="REFUND_SUCCESS",
                    display_name="退票成功",
                    description_field="desc",
                    source_ref=source_ref,
                    confidence=1.0,
                ),
                SemanticEnumValue(
                    enum_type="demo.RefundOrderStateEnum",
                    code="REFUND_DONE",
                    display_name="退款完成",
                    description_field="desc",
                    source_ref=source_ref,
                    confidence=1.0,
                ),
                SemanticEnumValue(
                    enum_type="demo.RefundChannelEnum",
                    code="CBDS",
                    display_name="C端供应渠道",
                    description_field="name",
                    source_ref=source_ref,
                    confidence=1.0,
                ),
                SemanticEnumValue(
                    enum_type="demo.RefundChannelEnum",
                    code="UNKNOWN",
                    display_name="UNKNOWN",
                    source_ref=source_ref,
                    confidence=0.5,
                ),
            ],
        ),
    )
    SourceScanArtifactStore(application.knowledge_root).write_manifest(manifest)
    SourceScanArtifactStore(application.knowledge_root).publish_latest(SYSTEM_ID, manifest.scan_id)

    envelope = application.knowledge_discovery.discover(manifest)
    by_name = {candidate.name: candidate for candidate in envelope.candidates}

    assert by_name["RefundOrderStateEnum"].status == KnowledgeContextCandidateStatus.CODE_VERIFIED
    assert by_name["RefundOrderStateEnum"].knowledge_form == "BUSINESS_ENUM"
    assert by_name["RefundOrderStateEnum"].business_name == "退票单处理状态"
    assert "退票成功（REFUND_SUCCESS）" in by_name["RefundOrderStateEnum"].code_meaning
    channel = by_name["RefundChannelEnum"]
    channel_values = {value.code: value for value in channel.enum_values}
    assert channel.status == KnowledgeContextCandidateStatus.CODE_VERIFIED
    assert channel.business_name_source == "CODE_DEFAULT"
    assert channel.unresolved_codes == []
    assert channel_values["CBDS"].source == "CODE_VERIFIED"
    assert channel_values["UNKNOWN"].source == "CODE_DEFAULT"
    assert channel_values["UNKNOWN"].business_meaning == "UNKNOWN"
    questions = application.list_unified_knowledge_questions(SYSTEM_ID)
    assert all(candidate.candidate_id not in question.question_id for candidate in by_name.values() for question in questions)
    detail = application.get_knowledge_target_detail(SYSTEM_ID, "facade:demo.RefundFacade#create")
    assert {candidate.business_name for candidate in detail.related_enums} == {"退票单处理状态", "退票渠道"}
    assert detail.related_terms == []


def test_semantic_enum_rescan_preserves_human_meaning_and_refreshes_unique_code_fact(tmp_path: Path) -> None:
    """唯一枚举描述变化应刷新代码事实，同时保持人工含义及CONFIRMED来源。

    Args:
        tmp_path: pytest隔离的两次语义扫描与候选真相目录。

    Returns:
        None；通过人工含义和新代码描述断言验证来源保护。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "RefundState.java"
    enum_path.write_text("package demo; enum RefundState { DONE; }", encoding="utf-8")
    baseline = application.knowledge.git_repository.capture(source_root)
    source_ref = SourceReference(path="RefundState.java", symbol="demo.RefundState", line=1)

    def manifest(scan_id: str, display_name: str) -> ScanManifest:
        """构造同一枚举在两个扫描中的唯一代码描述。

        Args:
            scan_id: 当前扫描稳定ID。
            display_name: DONE常量由源码唯一绑定的展示名。

        Returns:
            可直接交给确定性知识发现器的Manifest。
        """

        return ScanManifest(
            scan_id=scan_id,
            system_id=SYSTEM_ID,
            baseline=baseline,
            entries=[
                EntryPoint(
                    entry_id="facade:demo.RefundFacade#create",
                    system_id=SYSTEM_ID,
                    kind="facade",
                    display_name="创建退票单",
                    source_id="demo.RefundFacade#create",
                    source_path=str(enum_path),
                    request_type="demo.RefundState",
                )
            ],
            semantic_analysis=SemanticAnalysisResult(
                system_id=SYSTEM_ID,
                enum_values=[
                    SemanticEnumValue(
                        enum_type="demo.RefundState",
                        code="DONE",
                        display_name=display_name,
                        description_field="desc",
                        source_ref=source_ref,
                        confidence=1.0,
                    )
                ],
            ),
        )

    first = application.knowledge_discovery.discover(manifest("scan-enum-human-v1", "退票完成"))
    candidate = next(item for item in first.candidates if item.name == "RefundState")
    application.update_knowledge_context_candidate(
        SYSTEM_ID,
        candidate.candidate_id,
        KnowledgeContextCandidateUpdate(status="CONFIRMED", business_meaning="退款单生命周期终态"),
    )

    second = application.knowledge_discovery.discover(manifest("scan-enum-human-v2", "退款处理完成"))
    refreshed = next(item for item in second.candidates if item.candidate_id == candidate.candidate_id)

    assert refreshed.status == KnowledgeContextCandidateStatus.CONFIRMED
    assert refreshed.knowledge_form == "BUSINESS_ENUM"
    assert refreshed.business_meaning == "退款单生命周期终态"
    assert refreshed.code_meaning == "退款处理完成（DONE）"
    assert refreshed.business_name == "RefundState"
    assert refreshed.business_name_source == "CODE_DEFAULT"
    assert all(
        candidate.candidate_id not in question.question_id
        for question in application.list_unified_knowledge_questions(SYSTEM_ID)
    )


def test_semantic_enum_rescan_preserves_single_user_value_and_reloads_context(tmp_path: Path) -> None:
    """只人工修订一个枚举值后重扫应保持CONFIRMED且可由新应用实例读取。

    Args:
        tmp_path: pytest隔离的两次Manifest和持久化知识目录。

    Returns:
        None；通过字段来源、候选状态和重新加载断言覆盖人工单值保护。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "RefundState.java"
    enum_path.write_text("package demo; enum RefundState { DONE, FAILED; }", encoding="utf-8")
    baseline = application.knowledge.git_repository.capture(source_root)

    def manifest(scan_id: str, done_meaning: str) -> ScanManifest:
        """构造名称保持代码默认、逐值描述可变化的枚举Manifest。

        Args:
            scan_id: 当前测试扫描身份。
            done_meaning: DONE常量的本轮代码描述。

        Returns:
            绑定同一源码快照和稳定常量符号的语义Manifest。
        """

        done_ref = SourceReference(path="RefundState.java", symbol="demo.RefundState#DONE", line=1)
        failed_ref = SourceReference(path="RefundState.java", symbol="demo.RefundState#FAILED", line=1)
        return ScanManifest(
            scan_id=scan_id,
            system_id=SYSTEM_ID,
            baseline=baseline,
            entries=[
                EntryPoint(
                    entry_id="facade:demo.RefundFacade#create",
                    system_id=SYSTEM_ID,
                    kind="facade",
                    display_name="创建退票单",
                    source_id="demo.RefundFacade#create",
                    source_path=str(enum_path),
                    request_type="demo.RefundState",
                )
            ],
            semantic_analysis=SemanticAnalysisResult(
                system_id=SYSTEM_ID,
                enum_values=[
                    SemanticEnumValue(
                        enum_type="demo.RefundState",
                        code="DONE",
                        display_name=done_meaning,
                        description_field="desc",
                        source_ref=done_ref,
                        confidence=1.0,
                    ),
                    SemanticEnumValue(
                        enum_type="demo.RefundState",
                        code="FAILED",
                        display_name="处理失败",
                        description_field="desc",
                        source_ref=failed_ref,
                        confidence=1.0,
                    ),
                ],
            ),
        )

    first = application.knowledge_discovery.discover(manifest("scan-enum-value-v1", "处理完成"))
    candidate = next(item for item in first.candidates if item.name == "RefundState")
    value_question_id = application.knowledge_discovery._enum_value_question_id(candidate.candidate_id, "DONE")
    application.knowledge_discovery.answer_enum_question(SYSTEM_ID, value_question_id, "人工确认的退票完成")

    second = application.knowledge_discovery.discover(manifest("scan-enum-value-v2", "代码更新后的完成"))
    refreshed = next(item for item in second.candidates if item.candidate_id == candidate.candidate_id)
    values = {value.code: value for value in refreshed.enum_values}

    assert refreshed.status == KnowledgeContextCandidateStatus.CONFIRMED
    assert refreshed.business_name_source == "CODE_DEFAULT"
    assert values["DONE"].source == "USER_CONFIRMED"
    assert values["DONE"].business_meaning == "人工确认的退票完成"
    assert values["FAILED"].source == "CODE_VERIFIED"

    # 新实例会从YAML重新执行完整模型校验，可证明没有落盘非法来源组合。
    reloaded_application = OpenTestApplication(application.knowledge_root)
    reloaded = next(
        item for item in reloaded_application.get_knowledge_context(SYSTEM_ID).candidates
        if item.candidate_id == candidate.candidate_id
    )
    assert reloaded.status == KnowledgeContextCandidateStatus.CONFIRMED
    assert next(value for value in reloaded.enum_values if value.code == "DONE").source == "USER_CONFIRMED"
    reloaded_application.close()


def test_enum_user_value_follows_qualified_symbol_through_name_conflicts(tmp_path: Path) -> None:
    """同名类型冲突出现和消失时人工值应按全限定源码符号双向迁移。

    Args:
        tmp_path: pytest隔离的唯一类型与冲突类型Manifest目录。

    Returns:
        None；通过裸code和全限定code之间的往返断言验证稳定身份。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "OrderContext.java"
    enum_path.write_text("package demo; class OrderContext {}", encoding="utf-8")
    baseline = application.knowledge.git_repository.capture(source_root)

    def manifest(scan_id: str, include_conflict: bool) -> ScanManifest:
        """构造仅有a类型或同时包含a/b同名类型的Manifest。

        Args:
            scan_id: 当前测试扫描身份。
            include_conflict: 是否加入b包中的同名枚举和值。

        Returns:
            使用值级全限定symbol区分同名类型的语义Manifest。
        """

        enum_values = [
            SemanticEnumValue(
                enum_type="a.RefundState",
                code="DONE",
                display_name="A完成",
                description_field="desc",
                source_ref=SourceReference(
                    path="OrderContext.java",
                    symbol="a.RefundState#DONE",
                    line=1,
                ),
                confidence=1.0,
            )
        ]
        response_type = ""
        if include_conflict:
            # b类型只用于制造简单名冲突，人工修订仍应唯一归属于a类型常量。
            response_type = "b.RefundState"
            enum_values.append(
                SemanticEnumValue(
                    enum_type="b.RefundState",
                    code="DONE",
                    display_name="B完成",
                    description_field="desc",
                    source_ref=SourceReference(
                        path="OrderContext.java",
                        symbol="b.RefundState#DONE",
                        line=1,
                    ),
                    confidence=1.0,
                )
            )
        return ScanManifest(
            scan_id=scan_id,
            system_id=SYSTEM_ID,
            baseline=baseline,
            entries=[
                EntryPoint(
                    entry_id="facade:demo.RefundFacade#create",
                    system_id=SYSTEM_ID,
                    kind="facade",
                    display_name="创建退票单",
                    source_id="demo.RefundFacade#create",
                    source_path=str(enum_path),
                    request_type="a.RefundState",
                    response_type=response_type,
                )
            ],
            semantic_analysis=SemanticAnalysisResult(system_id=SYSTEM_ID, enum_values=enum_values),
        )

    first = application.knowledge_discovery.discover(manifest("scan-enum-identity-unique-v1", False))
    candidate = next(item for item in first.candidates if item.name == "RefundState")
    value_question_id = application.knowledge_discovery._enum_value_question_id(candidate.candidate_id, "DONE")
    application.knowledge_discovery.answer_enum_question(SYSTEM_ID, value_question_id, "人工A完成")

    conflicted = application.knowledge_discovery.discover(manifest("scan-enum-identity-conflict", True))
    conflicted_candidate = next(item for item in conflicted.candidates if item.candidate_id == candidate.candidate_id)
    conflicted_values = {value.code: value for value in conflicted_candidate.enum_values}
    assert conflicted_candidate.status == KnowledgeContextCandidateStatus.CONFIRMED
    assert conflicted_values["a.RefundState#DONE"].business_meaning == "人工A完成"
    assert conflicted_values["a.RefundState#DONE"].source == "USER_CONFIRMED"
    assert conflicted_values["b.RefundState#DONE"].source == "CODE_VERIFIED"

    unique_again = application.knowledge_discovery.discover(manifest("scan-enum-identity-unique-v2", False))
    unique_candidate = next(item for item in unique_again.candidates if item.candidate_id == candidate.candidate_id)
    unique_values = {value.code: value for value in unique_candidate.enum_values}
    assert unique_candidate.status == KnowledgeContextCandidateStatus.CONFIRMED
    assert unique_values["DONE"].business_meaning == "人工A完成"
    assert unique_values["DONE"].source == "USER_CONFIRMED"


def test_enum_merge_preserves_one_to_many_user_value_for_review(tmp_path: Path) -> None:
    """一个历史人工值命中多个当前常量时应原样保留并要求复核。

    Args:
        tmp_path: pytest隔离的应用根目录。

    Returns:
        None；通过完整匹配图的冲突标记和人工值断言验证无损降级。
    """

    application = _application(tmp_path)
    shared_ref = SourceReference(path="RefundState.java", symbol="demo.RefundState", line=1)
    previous_values = [
        KnowledgeEnumValue(
            code="legacy-done",
            business_meaning="人工完成含义",
            source="USER_CONFIRMED",
            confidence=1.0,
            source_refs=[shared_ref],
        ),
    ]
    discovered_values = [
        KnowledgeEnumValue(
            code="DONE",
            business_meaning="代码默认完成",
            source="CODE_DEFAULT",
            confidence=0.5,
            source_refs=[shared_ref],
        ),
        KnowledgeEnumValue(
            code="FAILED",
            business_meaning="代码默认失败",
            source="CODE_DEFAULT",
            confidence=0.5,
            source_refs=[shared_ref],
        ),
    ]

    merged, needs_review = application.knowledge_discovery._merge_enum_values(
        previous_values,
        discovered_values,
    )

    assert needs_review is True
    assert {value.business_meaning for value in merged if value.source == "USER_CONFIRMED"} == {
        "人工完成含义",
    }
    assert {value.code for value in merged if value.source == "CODE_DEFAULT"} == {"DONE", "FAILED"}


@pytest.mark.parametrize(
    "enum_value",
    [
        KnowledgeEnumValue(
            code="DONE",
            business_meaning="完成",
            source="CODE_DEFAULT",
            confidence=0.5,
        ),
        KnowledgeEnumValue(
            code="DONE",
            business_meaning="完成",
            source="CODE_DEFAULT",
            known_unknown=True,
            confidence=0.5,
            source_refs=[SourceReference(path="RefundState.java", symbol="demo.RefundState#DONE", line=1)],
        ),
        KnowledgeEnumValue(
            code="DONE",
            business_meaning="完成",
            source="CODE_VERIFIED",
            confidence=0.8,
            source_refs=[SourceReference(path="RefundState.java", symbol="demo.RefundState#DONE", line=1)],
        ),
    ],
)
def test_code_verified_enum_rejects_unproven_value_provenance(enum_value: KnowledgeEnumValue) -> None:
    """代码已验证候选不得包含无证据、已知未知或低置信的值级来源。

    Args:
        enum_value: 缺少一项必要代码来源约束的枚举值。

    Returns:
        None；模型必须拒绝伪装成CODE_VERIFIED的非法组合。
    """

    with pytest.raises(ValueError, match="CODE_VERIFIED requires"):
        KnowledgeContextCandidate(
            candidate_id="candidate:business_term:1234567890abcdef",
            system_id=SYSTEM_ID,
            kind="BUSINESS_TERM",
            knowledge_form="BUSINESS_ENUM",
            name="RefundState",
            business_name="退票状态",
            business_name_source="CODE_DEFAULT",
            enum_values=[enum_value],
            status="CODE_VERIFIED",
            source_refs=[SourceReference(path="RefundState.java", symbol="demo.RefundState", line=1)],
        )


def test_legacy_enum_override_updates_only_name_or_selected_value(tmp_path: Path) -> None:
    """兼容人工覆盖入口应只更新枚举名称或单值，并保护其他代码事实。

    Args:
        tmp_path: pytest隔离的语义Manifest和候选真相目录。

    Returns:
        None；通过默认值、人工名称和人工单值的独立来源断言验证精确更新。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "RefundResultEnum.java"
    enum_path.write_text("package demo; enum RefundResultEnum { DONE, UNKNOWN; }", encoding="utf-8")
    source_ref = SourceReference(path="RefundResultEnum.java", symbol="demo.RefundResultEnum", line=1)
    manifest = ScanManifest(
        scan_id="scan-enum-field-answers",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        entries=[
            EntryPoint(
                entry_id="facade:demo.RefundFacade#create",
                system_id=SYSTEM_ID,
                kind="facade",
                display_name="创建退票单",
                source_id="demo.RefundFacade#create",
                source_path=str(enum_path),
                    request_type="demo.RefundResultEnum",
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            types=[
                SemanticTypeDefinition(
                        symbol_id="demo.RefundResultEnum",
                        qualified_class_name="demo.RefundResultEnum",
                        simple_name="RefundResultEnum",
                    kind="enum",
                    source_ref=source_ref,
                )
            ],
            enum_values=[
                SemanticEnumValue(
                        enum_type="demo.RefundResultEnum",
                    code="DONE",
                    display_name="处理完成",
                    description_field="desc",
                    source_ref=source_ref,
                    confidence=1.0,
                ),
                SemanticEnumValue(
                        enum_type="demo.RefundResultEnum",
                    code="UNKNOWN",
                    display_name="UNKNOWN",
                    source_ref=source_ref,
                    confidence=0.5,
                ),
            ],
        ),
    )

    discovered = application.knowledge_discovery.discover(manifest)
    candidate = next(item for item in discovered.candidates if item.name == "RefundResultEnum")
    questions = application.list_unified_knowledge_questions(SYSTEM_ID)
    assert all(candidate.candidate_id not in question.question_id for question in questions)
    name_question_id = f"enum-name-question:{candidate.candidate_id}"
    value_question_id = application.knowledge_discovery._enum_value_question_id(candidate.candidate_id, "UNKNOWN")

    application.knowledge_discovery.answer_enum_question(SYSTEM_ID, name_question_id, "退票处理结果")
    application.knowledge_discovery.answer_enum_question(SYSTEM_ID, value_question_id, "未知处理结果")
    updated = next(
        item for item in application.get_knowledge_context(SYSTEM_ID).candidates
        if item.candidate_id == candidate.candidate_id
    )
    values = {item.code: item for item in updated.enum_values}

    assert updated.business_name == "退票处理结果"
    assert updated.business_name_source == "USER_CONFIRMED"
    assert values["DONE"].source == "CODE_VERIFIED"
    assert values["DONE"].business_meaning == "处理完成"
    assert values["UNKNOWN"].source == "USER_CONFIRMED"
    assert values["UNKNOWN"].business_meaning == "未知处理结果"


@pytest.mark.parametrize(
    "summary",
    [
        "",
        "Description",
        "TODO",
        "@author tester",
        "请填写",
        "@date 2026-08-22",
        "Created by tester",
        "Author tester",
        "Date 2026-08-22",
        "作者：tester",
        "0-退票申请，1-审核通过",
        "订单类型：1-出票，2-退票",
    ],
)
def test_template_javadoc_does_not_become_business_enum_name(tmp_path: Path, summary: str) -> None:
    """空注释、作者日期和模板文字不得被自动发布为业务枚举名称。

    Args:
        tmp_path: pytest隔离的应用目录。
        summary: Sidecar可能返回的类级注释摘要。

    Returns:
        None；不可信摘要被过滤为空即通过。
    """

    application = _application(tmp_path)

    assert application.knowledge_discovery._trusted_business_name(summary) == ""


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("退款订单锁定状态。枚举名称与历史协议兼容", "退款订单锁定状态"),
        ("是否自动退票 Created by tester", "是否自动退票"),
        ("订单类型 2、出票 3、退票", "订单类型"),
    ],
)
def test_business_enum_name_uses_only_javadoc_summary_phrase(
    tmp_path: Path,
    summary: str,
    expected: str,
) -> None:
    """可信类注释只取业务摘要短语，不把兼容说明、作者或逐值列表放进标题。

    Args:
        tmp_path: pytest隔离的应用目录。
        summary: Sidecar返回的完整类级Javadoc摘要。
        expected: 页面可用的简短业务名称。

    Returns:
        None；标题与预期摘要一致即通过。
    """

    application = _application(tmp_path)

    assert application.knowledge_discovery._trusted_business_name(summary) == expected


def test_legacy_term_yaml_migrates_to_business_enum_without_losing_identity_or_human_note(tmp_path: Path) -> None:
    """旧术语形态的枚举应在语义发现时迁移，同时保留稳定ID、状态和历史回答。

    Args:
        tmp_path: pytest隔离的旧候选YAML、源码和Manifest目录。

    Returns:
        None；候选身份、人工备注和确认状态均未丢失即通过。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "OrderLockEnum.java"
    enum_path.write_text("package demo; enum OrderLockEnum { LOCKED; }", encoding="utf-8")
    source_ref = SourceReference(path="OrderLockEnum.java", symbol="demo.OrderLockEnum", line=1)
    legacy = application.knowledge_discovery._candidate(
        SYSTEM_ID,
        KnowledgeContextCandidateKind.BUSINESS_TERM,
        "OrderLockEnum",
        ["facade:demo.RefundFacade#create"],
        [source_ref],
    ).model_copy(
        update={
            "status": KnowledgeContextCandidateStatus.CONFIRMED,
            "business_meaning": "代码注释有",
        }
    )
    context = application.get_knowledge_context(SYSTEM_ID)
    application.store.write_context(context.model_copy(update={"candidates": [legacy]}))
    manifest = ScanManifest(
        scan_id="scan-legacy-enum-migration",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        entries=[
            EntryPoint(
                entry_id="facade:demo.RefundFacade#create",
                system_id=SYSTEM_ID,
                kind="facade",
                display_name="创建退票单",
                source_id="demo.RefundFacade#create",
                source_path=str(enum_path),
                request_type="demo.OrderLockEnum",
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            types=[
                SemanticTypeDefinition(
                    symbol_id="demo.OrderLockEnum",
                    qualified_class_name="demo.OrderLockEnum",
                    simple_name="OrderLockEnum",
                    kind="enum",
                    javadoc_summary="退款订单锁定状态",
                    source_ref=source_ref,
                )
            ],
            enum_values=[
                SemanticEnumValue(
                    enum_type="demo.OrderLockEnum",
                    code="LOCKED",
                    display_name="锁定",
                    description_field="desc",
                    source_ref=source_ref,
                    confidence=1.0,
                )
            ],
        ),
    )

    envelope = application.knowledge_discovery.discover(manifest)
    migrated = next(item for item in envelope.candidates if item.name == "OrderLockEnum")

    assert migrated.candidate_id == legacy.candidate_id
    assert migrated.knowledge_form == "BUSINESS_ENUM"
    assert migrated.status == KnowledgeContextCandidateStatus.CONFIRMED
    assert migrated.business_meaning == "代码注释有"
    assert migrated.business_name == "退款订单锁定状态"
    assert migrated.business_name_source == "CODE_DEFAULT"

    application.knowledge_discovery.answer_enum_question(
        SYSTEM_ID,
        f"enum-name-question:{migrated.candidate_id}",
        "退票单锁单类型",
    )
    changed_type = manifest.semantic_analysis.types[0].model_copy(
        update={"javadoc_summary": "代码侧修改后的锁定状态"}
    )
    changed_manifest = manifest.model_copy(
        update={
            "scan_id": "scan-legacy-enum-migration-v2",
            "semantic_analysis": manifest.semantic_analysis.model_copy(update={"types": [changed_type]}),
        }
    )
    refreshed = application.knowledge_discovery.discover(changed_manifest)
    protected = next(item for item in refreshed.candidates if item.candidate_id == migrated.candidate_id)

    assert protected.business_name == "退票单锁单类型"
    assert protected.business_name_source == "USER_CONFIRMED"


def test_manual_candidate_update_cannot_claim_code_verified() -> None:
    """人工请求与无效持久化候选均不得伪造CODE_VERIFIED来源。

    Returns:
        None；通过更新请求和候选模型双重拒绝断言验证来源隔离。
    """

    source_ref = SourceReference(path="RefundState.java", symbol="demo.RefundState", line=1)
    with pytest.raises(ValueError, match="reserved for deterministic code analysis"):
        KnowledgeContextCandidateUpdate(status="CODE_VERIFIED")
    with pytest.raises(ValueError, match="unambiguous business-term code evidence"):
        KnowledgeContextCandidate(
            candidate_id="candidate:external_application:0123456789abcdef",
            system_id=SYSTEM_ID,
            kind=KnowledgeContextCandidateKind.EXTERNAL_APPLICATION,
            name="WalletClient",
            status="CODE_VERIFIED",
            code_meaning="伪造的代码事实",
            source_refs=[source_ref],
        )


def test_semantic_enum_rescan_preserves_ignored_human_state(tmp_path: Path) -> None:
    """用户明确忽略的术语不得因后续唯一代码映射重新进入知识上下文。

    Args:
        tmp_path: pytest隔离的枚举源码和候选真相目录。

    Returns:
        None；通过二次发现后的IGNORED状态断言验证人工终态优先级。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "RefundState.java"
    enum_path.write_text("package demo; enum RefundState { DONE; }", encoding="utf-8")
    source_ref = SourceReference(path="RefundState.java", symbol="demo.RefundState", line=1)
    manifest = ScanManifest(
        scan_id="scan-enum-ignored",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        entries=[
            EntryPoint(
                entry_id="facade:demo.RefundFacade#create",
                system_id=SYSTEM_ID,
                kind="facade",
                display_name="创建退票单",
                source_id="demo.RefundFacade#create",
                source_path=str(enum_path),
                request_type="demo.RefundState",
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            types=[
                SemanticTypeDefinition(
                    symbol_id="demo.RefundState",
                    qualified_class_name="demo.RefundState",
                    simple_name="RefundState",
                    kind="enum",
                    javadoc_summary="退票处理结果",
                    source_ref=source_ref,
                )
            ],
            enum_values=[
                SemanticEnumValue(
                    enum_type="demo.RefundState",
                    code="DONE",
                    display_name="退票完成",
                    description_field="desc",
                    source_ref=source_ref,
                    confidence=1.0,
                )
            ],
        ),
    )
    artifact_store = SourceScanArtifactStore(application.knowledge_root)
    artifact_store.write_manifest(manifest)
    artifact_store.publish_latest(SYSTEM_ID, manifest.scan_id)
    first = application.knowledge_discovery.discover(manifest)
    candidate = next(item for item in first.candidates if item.name == "RefundState")
    application.update_knowledge_context_candidate(
        SYSTEM_ID,
        candidate.candidate_id,
        KnowledgeContextCandidateUpdate(status="IGNORED"),
    )

    second = application.knowledge_discovery.discover(manifest)
    refreshed = next(item for item in second.candidates if item.candidate_id == candidate.candidate_id)

    assert refreshed.status == KnowledgeContextCandidateStatus.IGNORED
    assert all(candidate.candidate_id not in question.question_id for question in application.list_unified_knowledge_questions(SYSTEM_ID))
    assert application.get_knowledge_target_detail(
        SYSTEM_ID,
        "facade:demo.RefundFacade#create",
    ).related_enums == []
    assert application.knowledge._system_context_payload(SYSTEM_ID)["confirmed_candidates"] == []

    # 终态枚举不应参与上下文摘要；从源码消失的STALE状态使用相同排除边界。
    terminal_context = application.get_knowledge_context(SYSTEM_ID)
    ignored_digest = application.knowledge_discovery._context_digest(SYSTEM_ID)
    empty_context = terminal_context.model_copy(update={"candidates": []})
    application.store.write_context(empty_context)
    empty_digest = application.knowledge_discovery._context_digest(SYSTEM_ID)
    assert ignored_digest == empty_digest

    stale_candidate = refreshed.model_copy(update={"status": KnowledgeContextCandidateStatus.STALE})
    application.store.write_context(empty_context.model_copy(update={"candidates": [stale_candidate]}))
    assert application.get_knowledge_target_detail(
        SYSTEM_ID,
        "facade:demo.RefundFacade#create",
    ).related_enums == []
    assert application.knowledge._system_context_payload(SYSTEM_ID)["confirmed_candidates"] == []
    assert application.knowledge_discovery._context_digest(SYSTEM_ID) == empty_digest


def test_same_simple_enum_name_from_two_types_uses_qualified_code_defaults(tmp_path: Path) -> None:
    """同名枚举映射到多个类型时应按全限定常量发布代码默认值。

    Args:
        tmp_path: pytest隔离的冲突枚举源码与Manifest目录。

    Returns:
        None；通过全限定常量、独立含义和空问题集合断言验证安全默认展示。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    enum_path = source_root / "OrderContext.java"
    enum_path.write_text(
        "package demo; class OrderContext { a.RefundState first; b.RefundState second; }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    source_ref = SourceReference(path="OrderContext.java", symbol="demo.OrderContext", line=1)
    manifest = ScanManifest(
        scan_id="scan-enum-simple-name-conflict",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id="facade:demo.RefundFacade#create",
                system_id=SYSTEM_ID,
                kind="facade",
                display_name="创建退票单",
                source_id="demo.RefundFacade#create",
                source_path=str(enum_path),
                request_type="a.RefundState",
                response_type="b.RefundState",
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            enum_values=[
                SemanticEnumValue(
                    enum_type="a.RefundState",
                    code="DONE",
                    display_name="A完成",
                    description_field="desc",
                    source_ref=source_ref,
                    confidence=1.0,
                ),
                SemanticEnumValue(
                    enum_type="b.RefundState",
                    code="DONE",
                    display_name="B完成",
                    description_field="desc",
                    source_ref=source_ref,
                    confidence=1.0,
                ),
            ],
        ),
    )

    envelope = application.knowledge_discovery.discover(manifest)
    candidate = next(item for item in envelope.candidates if item.name == "RefundState")

    values = {value.code: value for value in candidate.enum_values}
    assert candidate.status == KnowledgeContextCandidateStatus.CODE_VERIFIED
    assert candidate.business_name == "RefundState"
    assert candidate.business_name_source == "CODE_DEFAULT"
    assert candidate.unresolved_codes == []
    assert values["a.RefundState#DONE"].business_meaning == "A完成"
    assert values["b.RefundState#DONE"].business_meaning == "B完成"
    assert all(
        candidate.candidate_id not in question.question_id
        for question in application.list_unified_knowledge_questions(SYSTEM_ID)
    )


def test_core_object_background_hint_embeds_type_evidence_without_ownership_inference(tmp_path: Path) -> None:
    """核心对象背景提示可展示字段关系，但不进入待确认问题周期。

    Args:
        tmp_path: pytest隔离的类型语义Manifest与问题目录。

    Returns:
        None；通过背景提示与空周期断言验证不推断所有权。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    context_path = source_root / "OrderContext.java"
    context_path.write_text("package demo; class OrderContext {}", encoding="utf-8")
    baseline = application.knowledge.git_repository.capture(source_root)
    source_ref = SourceReference(path="OrderContext.java", symbol="demo.OrderContext", line=1)
    manifest = ScanManifest(
        scan_id="scan-core-object-evidence",
        system_id=SYSTEM_ID,
        baseline=baseline,
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            types=[
                SemanticTypeDefinition(
                    symbol_id="demo.OrderContext",
                    qualified_class_name="demo.OrderContext",
                    simple_name="OrderContext",
                    source_ref=source_ref,
                    fields=[
                        SemanticFieldDefinition(
                            field_name="order",
                            declared_type="SaasRefundOrderVO",
                            referenced_type="demo.SaasRefundOrderVO",
                            source_ref=source_ref,
                        ),
                        SemanticFieldDefinition(
                            field_name="passengers",
                            declared_type="List<SaasRefundOrderPassagerVO>",
                            referenced_type="demo.SaasRefundOrderPassagerVO",
                            collection=True,
                            source_ref=source_ref,
                        ),
                        SemanticFieldDefinition(
                            field_name="paymentClientFallback",
                            declared_type="PaymentRecord",
                            referenced_type="demo.PaymentRecord",
                            source_ref=source_ref,
                            resolution_status=SemanticResolutionStatus.PARTIAL,
                            confidence=0.75,
                        ),
                    ],
                )
            ],
        ),
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)

    detail = application.knowledge_discovery._core_object_question_detail(SYSTEM_ID, "fallback")

    assert "OrderContext 通过 order 直接字段引用 SaasRefundOrderVO" in detail
    assert "passengers 集合字段引用 SaasRefundOrderPassagerVO" in detail
    assert "paymentClientFallback" not in detail
    assert "生命周期归属" in detail
    assert application.list_unified_knowledge_questions(SYSTEM_ID) == []


def test_state_background_scope_maps_machine_transitions_and_semantic_pattern(tmp_path: Path) -> None:
    """关键状态背景范围仍覆盖状态机、流转和语义公共逻辑，但不自动提问。

    Args:
        tmp_path: pytest隔离的源码、Manifest和上下文目录。

    Side Effects:
        只发布本地扫描Manifest，不生成知识或访问QA。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    source_ref = SourceReference(path="StateMachine.java", symbol="demo.StateMachine#apply()", line=1)
    transition = StateTransition(
        transition_id="state-transition:pending-done",
        actor="demo.StateMachine",
        from_states=["PENDING"],
        to_states=["DONE"],
        source_ref=source_ref,
    )
    method = SemanticMethodDefinition(
        symbol_id="demo.StateMachine#apply()",
        qualified_class_name="demo.StateMachine",
        method_name="apply",
        source_ref=source_ref,
    )
    manifest = ScanManifest(
        scan_id="scan-state-interview-targets",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        state_machines=[
            StateMachineDefinition(
                machine_id="state-machine:OrderState",
                system_id=SYSTEM_ID,
                state_enum="demo.OrderState",
                title="订单状态机",
                transitions=[transition],
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            methods=[method],
            patterns=[
                SemanticPatternEvidence(
                    symbol_id=method.symbol_id,
                    pattern="state_machine",
                    evidence="状态机类型命名和流转方法共同证明。",
                    source_refs=[source_ref],
                    confidence=0.95,
                )
            ],
        ),
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)

    affected_target_ids = application.knowledge_discovery._interview_targets(SYSTEM_ID, "state_semantics")
    semantic_target = "semantic:" + hashlib.sha256(method.symbol_id.encode("utf-8")).hexdigest()[:20]

    assert set(affected_target_ids) == {
        "state-machine:OrderState",
        transition.transition_id,
        semantic_target,
    }
    assert application.list_unified_knowledge_questions(SYSTEM_ID) == []
