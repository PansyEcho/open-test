"""验证证据驱动集中问答周期、未知项和代码事实吸收。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import (
    AgentObserverDetachedError,
    AgentRunInterruptedError,
    ExecutionFailure,
    KnowledgeNotFoundError,
    KnowledgeQuestionCycleStaleError,
    KnowledgeValidationError,
    ScopeViolationError,
)
from opentest.domain.models import (
    AgentKnowledgeEnvelope,
    AgentKnowledgeCompleteness,
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
    KnowledgeClientCandidateConfirmation,
    KnowledgeClientCandidateSubmission,
    KnowledgeClientCandidateEnvelope,
    KnowledgeClientHandoffStatus,
    KnowledgeTargetGenerationOutcome,
    KnowledgeTargetGenerationRequest,
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
    TaskRecord,
    RuntimeToolSettings,
    TaskStatus,
    utc_now,
)


SYSTEM_ID = "demo-interview-system"


def _agent_test_points() -> list[dict[str, str]]:
    """构造测试Agent完成候选必须携带的最小结构化测试点。

    Returns:
        覆盖一个可验证主流程的严格测试点数组。
    """

    return [
        {
            "kind": "main_flow",
            "title": "完成入口主流程",
            "condition": "请求满足当前入口的源码业务条件",
            "expected_outcome": "入口按知识摘要完成业务处理并返回稳定结果",
        }
    ]


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
        assert prompt_payload["business_context"]
        assert prompt_payload["analysis_policy"]["mode"] == "registered_source_read_only"
        assert prompt_payload["analysis_policy"]["available_tools"] == [
            "list_source_files",
            "search_source",
            "read_source",
        ]
        assert "完整业务执行路径" in request.prompt
        assert "不能只复述Facade接口契约" in request.prompt
        summaries = [
            {
                "node_id": item["node_id"],
                "summary": "基于给定源码证据解释该目标的业务目的、主流程、分支、依赖、副作用与异常边界。",
                "test_points": _agent_test_points(),
            }
            for item in prompt_payload["evidence"]
        ]
        source_refs = [
            {
                "path": item["path"],
                "symbol": item["symbol"],
                "line": item["start_line"],
            }
            for item in prompt_payload["source_packet"]
        ]
        envelope = {
            "status": "completed",
            "system_id": prompt_payload["system_id"],
            "target_ids": prompt_payload["target_ids"],
            "summaries": summaries,
            "questions": [],
            "source_refs": source_refs,
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "no_downstream",
                    "source_ref": source_refs[0],
                    "summary": "测试Job的确定性入口没有需要继续展开的数据或远程边界。",
                }
            ],
        }
        output_root = evidence_root / f"test-agent-{len(list(evidence_root.glob('test-agent-*')))}"
        output_root.mkdir(parents=True, exist_ok=False)
        output_path = output_root / "output.txt"
        output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(output_path=str(output_path))


class _FakeCodexAppServer:
    """同时模拟只读App Server快照和Codex桌面follower启动。"""

    def __init__(self) -> None:
        """初始化线程创建、只读快照和桌面启动的可核对状态。"""

        self.call_count = 0
        self.requests: list[dict[str, str]] = []
        self.turn_start_checks = 0
        self.started_thread_ids: set[str] = set()
        self.started_profiles: list[tuple[str, str]] = []
        self.turn_start_failures_remaining = 0
        self.turn_start_gate: threading.Event | None = None
        self.turn_count_by_thread: dict[str, int] = {}
        self.turn_status_by_thread: dict[str, str] = {}
        self.latest_turn_id_by_thread: dict[str, str] = {}

    def require_knowledge_plugin(self) -> None:
        """模拟已经由用户一次性安装并启用OpenTest插件。

        Returns:
            None；测试替身不访问用户Codex配置。
        """

        return None

    def create_thread(
        self,
        prompt: str,
        title: str,
        cwd: Path,
        developer_instructions: str,
        model: str,
        reasoning_effort: str,
    ) -> object:
        """返回不会触发turn/start的固定Codex客户端线程。

        Args:
            prompt: 注入客户端聊天历史的完整单目标任务说明。
            title: 页面和Codex侧栏可识别的目标标题。
            cwd: OpenTest仓库目录，用于加载仓库插件。
            developer_instructions: 强制使用OpenTest桥接和确认发布的线程约束。
            model: 页面明确选择的Codex模型ID。
            reasoning_effort: 页面明确选择的推理档位。

        Returns:
            带线程ID和深链的轻量客户端线程结果。

        Side Effects:
            只记录测试调用；不启动Codex、turn或任何外部Agent。
        """

        self.call_count += 1
        self.requests.append(
            {
                "prompt": prompt,
                "title": title,
                "cwd": str(cwd),
                "developer_instructions": developer_instructions,
                "model": model,
                "reasoning_effort": reasoning_effort,
            }
        )
        thread_id = f"01a-client-thread-{self.call_count}"
        return SimpleNamespace(thread_id=thread_id, deep_link=f"codex://threads/{thread_id}")

    def inspect_thread(self, thread_id: str) -> object:
        """模拟App Server只读返回当前线程最近turn。

        Args:
            thread_id: 应用已持久化的同一Codex线程ID。

        Returns:
            与生产只读快照字段一致的轻量对象。

        Side Effects:
            无；不会改变turn数量、状态或桌面owner。
        """

        turn_count = self.turn_count_by_thread.get(thread_id, 0)
        # 测试可覆盖只读投影中的turn身份，以复现桌面新turn尚未替换旧快照的短暂窗口。
        latest_turn_id = self.latest_turn_id_by_thread.get(
            thread_id,
            f"turn-{thread_id}-{turn_count}" if turn_count else "",
        )
        return SimpleNamespace(
            thread_id=thread_id,
            deep_link=f"codex://threads/{thread_id}",
            turn_count=turn_count,
            latest_turn_id=latest_turn_id,
            latest_turn_status=self.turn_status_by_thread.get(thread_id, ""),
        )

    def start_turn(
        self,
        thread_id: str,
        prompt: str,
        model: str,
        reasoning_effort: str,
    ) -> object:
        """模拟Codex桌面owner接受一次follower turn请求。

        Args:
            thread_id: 应用已持久化的同一Codex线程ID。
            prompt: 首次生成或自动补全的明确Skill消息。
            model: handoff创建时固化的Codex模型。
            reasoning_effort: handoff创建时固化的推理档位。

        Returns:
            started或manual_required桌面启动结果。

        Side Effects:
            记录请求次数和模拟turn状态；不调用任何模型。
        """

        assert prompt.startswith("$knowledge-handoff")
        # 首轮没有可继承的线程设置，记录应用显式交给桌面owner的固化生成配置。
        assert model in {"gpt-5.6-luna", "gpt-5.6-sol"}
        assert reasoning_effort in {"low", "medium"}
        self.started_profiles.append((model, reasoning_effort))
        self.turn_start_checks += 1
        if self.turn_start_gate is not None:
            # 测试可暂停桌面IPC边界，证明应用关闭会等待当前协调请求完整退出。
            self.turn_start_gate.wait(timeout=2)
        if self.turn_start_failures_remaining > 0:
            self.turn_start_failures_remaining -= 1
            return SimpleNamespace(
                state="manual_required",
                turn_id="",
                safe_message="simulated transient desktop failure",
            )
        next_turn_count = self.turn_count_by_thread.get(thread_id, 0) + 1
        self.turn_count_by_thread[thread_id] = next_turn_count
        self.turn_status_by_thread[thread_id] = "inProgress"
        self.started_thread_ids.add(thread_id)
        return SimpleNamespace(
            state="started",
            turn_id=f"turn-{thread_id}-{next_turn_count}",
            safe_message="",
        )

    def complete_latest_turn(self, thread_id: str) -> None:
        """把测试线程最近turn推进为已完成。

        Args:
            thread_id: 已由桌面替身启动过的线程ID。

        Side Effects:
            只更新内存快照，使协调器可验证自动续跑和无进展判定。
        """

        if self.turn_count_by_thread.get(thread_id, 0) <= 0:
            raise AssertionError("cannot complete a thread without a turn")
        self.turn_status_by_thread[thread_id] = "completed"


class _FailingKnowledgeAgentRunner(_KnowledgeAgentRunner):
    """模拟指定Agent启动后失败且确定性源码事实仍可保存的无费用Runner。"""

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """在确定性追踪之后抛出安全执行失败。

        Args:
            request: 已明确选择Agent的单目标运行请求。
            source_root: 注册源码根，本桩不读取正文。
            evidence_root: 私有证据根，本桩不写供应商输出。

        Raises:
            ExecutionFailure: 固定模拟Agent分析失败。
        """

        del request, source_root, evidence_root
        raise ExecutionFailure("simulated invalid_json_schema")


class _DetachedInvalidRecoveryRunner(_KnowledgeAgentRunner):
    """先模拟服务分离，再为接管提供exit 0但结构非法的本地证据。"""

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """在确定性检查点保存后模拟旧服务放弃观察权。

        Args:
            request: 已明确目标与Agent的原始运行请求。
            source_root: 注册源码根，本桩不读取正文。
            evidence_root: 私有证据根，非法结果留给接管阶段写入。

        Raises:
            AgentObserverDetachedError: 固定表示付费进程由新服务接管。
        """

        del request, source_root, evidence_root
        raise AgentObserverDetachedError("simulated service handoff")

    def attach(
        self,
        run_id: str,
        evidence_root: Path,
        event_callback: object | None = None,
    ) -> object:
        """返回缺失严格必填字段的已结束证据，模拟重启后校验失败。

        Args:
            run_id: 原检查点保存的稳定运行ID。
            evidence_root: 当前测试知识根内的私有Agent目录。
            event_callback: 兼容生产接管签名，本桩不发送事件。

        Returns:
            只暴露非法最终输出路径的轻量证据对象。
        """

        del event_callback
        output_root = evidence_root / run_id
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / "output.txt"
        output_path.write_text('{"status":"completed"}', encoding="utf-8")
        return SimpleNamespace(output_path=str(output_path))


class _BlockingKnowledgeAgentRunner(_KnowledgeAgentRunner):
    """保持单次无费用Agent调用在运行中，供刷新和重复提交门禁测试使用。"""

    def __init__(self) -> None:
        """初始化运行信号与调用计数，不启动任何外部进程。"""

        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def run(self, request: object, source_root: Path, evidence_root: Path) -> object:
        """等待测试线程放行后复用成功Runner生成严格结果。

        Args:
            request: 已明确Agent和目标的单次请求。
            source_root: 注册源码根，本桩只传给父类且不读取QA。
            evidence_root: 当前隔离知识库的私有证据目录。

        Returns:
            父类写入的完整严格Agent信封证据。

        Raises:
            AssertionError: 测试未在两秒内放行时终止，避免后台线程悬挂。
        """

        self.call_count += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise AssertionError("blocking Agent test was not released")
        return super().run(request, source_root, evidence_root)


class _WaitingContinuationAgentRunner:
    """先提出高影响疑点，再按原会话返回完整知识解释。"""

    def __init__(self) -> None:
        """初始化两阶段无费用Runner及调用证据。

        Side Effects:
            只创建内存调用列表，不读取源码、认证信息或QA。
        """

        self.requests: list[object] = []
        self.node_ids: list[str] = []
        self.source_refs: list[dict[str, object]] = []

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
            self.source_refs = [
                {
                    "path": item["path"],
                    "symbol": item["symbol"],
                    "line": item["start_line"],
                }
                for item in prompt_payload["source_packet"]
            ]
            envelope = {
                "status": "needs_input",
                "system_id": prompt_payload["system_id"],
                "target_ids": prompt_payload["target_ids"],
                "summaries": [],
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
                        "source_refs": [self.source_refs[0]],
                        "impact": "high",
                    }
                ],
                "source_refs": self.source_refs,
                "trace_steps": [],
            }
        else:
            continuation_payload = json.loads(request.prompt.split("\n", 1)[1])
            assert continuation_payload["answered_questions"][0]["answer"] == "本系统补偿"
            envelope = {
                "status": "completed",
                "system_id": continuation_payload["system_id"],
                "target_ids": continuation_payload["target_ids"],
                "summaries": [
                    {
                        "node_id": node_id,
                        "summary": "异常由本系统记录并执行补偿，人工答案作为确认口径单独保留。",
                        "test_points": _agent_test_points(),
                    }
                    for node_id in self.node_ids
                ],
                "questions": [],
                "source_refs": self.source_refs,
                "trace_steps": [
                    {
                        "sequence": 1,
                        "role": "no_downstream",
                        "source_ref": self.source_refs[0],
                        "summary": "测试Job的补偿结论已经在当前实现中收口。",
                    }
                ],
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


def test_question_cycle_http_get_is_compatible_and_writes_are_retired(tmp_path: Path) -> None:
    """历史周期GET保持可读，PUT和完成POST统一返回退休响应。

    Args:
        tmp_path: pytest隔离的FastAPI应用、周期与知识目录。

    Returns:
        None；通过只读兼容与410写响应断言验证HTTP契约。
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
            assert staged.status_code == 410
            assert staged.json()["error"]["code"] == "knowledge_question_flow_retired"
        assert application.get_knowledge_context(SYSTEM_ID).interview_answers == {}

        # 完成接口同样不能重算或改写已经保留的历史周期。
        retired = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/question-cycles/{cycle['cycle_id']}/complete",
            json={"question_set_digest": cycle["question_set_digest"]},
        )

    assert retired.status_code == 410
    assert retired.json()["error"]["code"] == "knowledge_question_flow_retired"
    assert application.store.read_active_question_cycle(SYSTEM_ID).staged_answers == {}


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


def _prepare_codex_client_handoff_system(
    tmp_path: Path,
) -> tuple[OpenTestApplication, ScanManifest, str, Path, _FakeCodexAppServer]:
    """创建具备单个Job目标和已完成背景的客户端接管测试系统。

    Args:
        tmp_path: pytest隔离的源码、Manifest、任务和知识根。

    Returns:
        应用、固定Manifest、目标ID、源码文件和无模型App Server替身。

    Side Effects:
        只写测试目录内源码与扫描产物，不调用Agent、QA或业务接口。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    source_file = source_root / "ClientQueryJob.java"
    source_file.write_text(
        "package demo; class ClientQueryJob { void execute() { repository.query(); } }\n",
        encoding="utf-8",
    )
    target_id = "job:demo.ClientQueryJob"
    manifest = ScanManifest(
        scan_id="scan-codex-client-handoff",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        entries=[
            EntryPoint(
                entry_id=target_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="客户端查询任务",
                source_id="demo.ClientQueryJob",
                source_path=str(source_file),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, manifest.baseline)
    application.skip_background_interview(SYSTEM_ID)
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="codex"))
    app_server = _FakeCodexAppServer()
    application.codex_app_server = app_server
    application.codex_desktop = app_server
    # 如果客户端接管误走旧Runner，本桩会使测试立即失败而不是产生外部费用。
    application.agent_runner = _FailingKnowledgeAgentRunner()
    application.knowledge.runner = application.agent_runner
    return application, manifest, target_id, source_file, app_server


def _register_additional_codex_client_target(
    application: OpenTestApplication,
    tmp_path: Path,
    system_id: str,
) -> tuple[ScanManifest, str]:
    """在同一知识仓库注册另一个具备客户端生成条件的隔离系统。

    Args:
        application: 已配置假App Server和Codex选择的测试应用。
        tmp_path: Pytest提供的隔离目录。
        system_id: 用于验证跨系统全局互斥的第二系统ID。

    Returns:
        第二系统的固定扫描Manifest和唯一目标ID。

    Side Effects:
        只在测试目录注册系统、写最小源码与扫描产物并跳过背景访谈。
    """

    source_root = tmp_path / f"source-{system_id}"
    source_root.mkdir()
    application.register_system(
        SystemDefinition(system_id=system_id, name="第二客户端系统", source_path=str(source_root))
    )
    source_file = source_root / "OtherClientQueryJob.java"
    source_file.write_text(
        "package other; class OtherClientQueryJob { void execute() { repository.query(); } }\n",
        encoding="utf-8",
    )
    target_id = "job:other.OtherClientQueryJob"
    manifest = ScanManifest(
        scan_id=f"scan-{system_id}-codex-client",
        system_id=system_id,
        baseline=application.knowledge.git_repository.capture(source_root),
        entries=[
            EntryPoint(
                entry_id=target_id,
                system_id=system_id,
                kind="job",
                display_name="第二客户端查询任务",
                source_id="other.OtherClientQueryJob",
                source_path=str(source_file),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(system_id, manifest.scan_id)
    application.store.update_source_baseline(system_id, manifest.baseline)
    application.skip_background_interview(system_id)
    return manifest, target_id


def test_codex_client_handoff_ignores_retired_claude_global_selection(tmp_path: Path) -> None:
    """旧设置残留Claude时，新页面仍应创建唯一Codex客户端任务。

    Args:
        tmp_path: Pytest隔离的源码、Manifest、任务和设置目录。

    Returns:
        None；请求不受隐藏旧选择阻断且只创建一个无模型线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    # 本用例固定恢复和只读投影时点，周期协调行为由后续页面API测试单独覆盖。
    application._client_coordination_stop.set()
    application._client_coordination_wakeup.set()
    application._client_coordination_thread.join(timeout=2)
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="claude"))

    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-retired-claude-0001",
        )
    )

    assert task.status == TaskStatus.WAITING_FOR_CLIENT
    assert task.client_handoff is not None
    assert task.client_handoff.deep_link.startswith("codex://threads/")
    assert app_server.call_count == 1


def test_codex_client_handoff_is_idempotent_and_does_not_publish_or_run_agent(
    tmp_path: Path,
) -> None:
    """同一attempt重复提交必须恢复同一线程，且确认前不发布或运行旧Agent。

    Args:
        tmp_path: pytest隔离的源码、任务、草稿与App Server记录目录。

    Returns:
        None；任务等待客户端、线程只创建一次且Git知识仍为空时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    # 已确认背景和业务术语必须进入可见业务模板，不能只藏在固定协议的审计载荷中。
    application.save_knowledge_context_narrative(
        SYSTEM_ID,
        KnowledgeContextNarrativeUpdate(
            system_purpose="退票查询系统",
            upstream_entry_narrative="运营后台按筛选条件查询退票单",
        ),
    )
    application.create_knowledge_context_candidate(
        SYSTEM_ID,
        KnowledgeContextCandidateCreate(
            kind="BUSINESS_TERM",
            name="自愿退",
            business_meaning="旅客主动申请的退票类型",
            affected_target_ids=[target_id],
        ),
    )
    request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-client-idempotent-0001",
    )

    first = application.submit_knowledge_target_generation(request)
    assert first.client_handoff is not None
    started = application.start_knowledge_client_turn(first.client_handoff.handoff_id)
    assert started["state"] == "started"
    repeated = application.submit_knowledge_target_generation(request)
    batch = application.store.read_draft_batch(SYSTEM_ID, first.client_handoff.batch_id)

    assert first.task_id == repeated.task_id
    assert first.status == TaskStatus.WAITING_FOR_CLIENT
    assert first.client_handoff is not None
    assert first.client_handoff.target_id == target_id
    assert first.client_handoff.attempt_id == request.attempt_id
    assert first.client_handoff.deep_link == f"codex://threads/{first.client_handoff.thread_id}"
    assert repeated.result["start_state"] == "started"
    # 同attempt恢复不能抹掉启动回执，否则thread/read投影延迟会导致第二个turn。
    app_server.turn_count_by_thread[first.client_handoff.thread_id] = 0
    app_server.turn_status_by_thread[first.client_handoff.thread_id] = ""
    lagged_repeat = application.start_knowledge_client_turn(first.client_handoff.handoff_id)
    assert lagged_repeat["state"] == "already_started"
    assert app_server.call_count == 1
    assert app_server.turn_start_checks == 1
    assert app_server.requests[0]["model"] == "gpt-5.6-luna"
    assert app_server.requests[0]["reasoning_effort"] == "low"
    assert "退票查询系统" in app_server.requests[0]["prompt"]
    assert "自愿退" in app_server.requests[0]["prompt"]
    assert batch.client_handoff is not None
    assert batch.client_handoff.task_id == first.task_id
    assert application.store.list_nodes(SYSTEM_ID) == []
    prompt_payload = json.loads(app_server.requests[0]["prompt"].rsplit("\n", 1)[-1])
    handoff_payload = application.get_knowledge_client_handoff(first.client_handoff.handoff_id)
    # 客户端线程只得到请求入口和业务背景；源码正文及确定性下游类必须由三个工具自行发现。
    assert "source_packet" not in prompt_payload
    assert "evidence" not in prompt_payload
    assert handoff_payload["candidate_node_ids"] == [batch.drafts[0].node.node_id]
    diagnostics = application.get_task_agent_diagnostics(first.task_id)
    assert diagnostics.session_id == first.client_handoff.thread_id
    assert diagnostics.prompt
    assert diagnostics.resume_command == ""


def test_codex_client_page_reuses_auto_started_thread_via_loopback_api(tmp_path: Path) -> None:
    """后台自动启动后页面入口应复用原handoff、task和thread而不追加turn。

    Args:
        tmp_path: pytest隔离的源码、OpenTest状态与假App Server。

    Returns:
        None；后台只启动一次，两次页面POST均只读恢复且没有创建第二线程或任务时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-turn-start-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    # 新handoff持久化后后台应立即唤醒，测试有界等待它完成首次幂等启动检查。
    deadline = time.monotonic() + 2
    while task.client_handoff.thread_id not in app_server.started_thread_ids and time.monotonic() < deadline:
        time.sleep(0.01)

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        first = client.post(f"/api/v2/knowledge/client-handoffs/{handoff_id}/turns", json={})
        repeated = client.post(f"/api/v2/knowledge/client-handoffs/{handoff_id}/turns", json={})

    assert first.status_code == 202
    assert repeated.status_code == 202
    assert first.json()["started"] is False
    assert repeated.json()["started"] is False
    assert first.json()["task"]["task_id"] == task.task_id
    assert repeated.json()["task"]["client_handoff"]["thread_id"] == task.client_handoff.thread_id
    assert app_server.call_count == 1
    assert app_server.turn_start_checks == 1
    assert app_server.started_thread_ids == {task.client_handoff.thread_id}


def test_codex_client_manual_start_can_retry_same_identity_after_desktop_recovers(tmp_path: Path) -> None:
    """桌面连接临时失败后应允许同一线程再次接管且不创建第二套知识身份。

    Args:
        tmp_path: Pytest隔离的源码、任务和假App Server状态目录。

    Returns:
        None；第二次协调检查启动原线程且task、handoff、batch身份均保持不变时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    app_server.turn_start_failures_remaining = 1
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-turn-retry-0001",
        )
    )
    assert task.client_handoff is not None

    # 首轮失败不改变持久身份；显式唤醒模拟下一次15秒巡检，避免测试真实等待。
    first_deadline = time.monotonic() + 2
    while app_server.turn_start_checks < 1 and time.monotonic() < first_deadline:
        time.sleep(0.01)
    application._client_coordination_wakeup.set()
    second_deadline = time.monotonic() + 2
    while time.monotonic() < second_deadline:
        # 桌面替身先记录接收，再由应用持久化启动回执；必须等待整个协调事务结束。
        current = application.tasks.get(task.task_id)
        if (
            task.client_handoff.thread_id in app_server.started_thread_ids
            and current.result.get("start_state") == "started"
        ):
            break
        time.sleep(0.01)

    settled = application.tasks.get(task.task_id)
    workflow = application.store.read_draft_batch(SYSTEM_ID, task.client_handoff.batch_id)
    assert app_server.turn_start_checks == 2
    assert app_server.call_count == 1
    assert app_server.started_thread_ids == {task.client_handoff.thread_id}
    assert settled.task_id == task.task_id
    assert settled.client_handoff is not None
    assert workflow.client_handoff is not None
    assert settled.client_handoff.handoff_id == task.client_handoff.handoff_id
    assert workflow.client_handoff.handoff_id == task.client_handoff.handoff_id
    assert settled.client_handoff.thread_id == task.client_handoff.thread_id
    assert workflow.client_handoff.thread_id == task.client_handoff.thread_id
    assert settled.result["start_state"] == "started"
    assert "manual_message" not in settled.result
    application.close()
    assert application._client_coordination_thread.is_alive() is False


def test_codex_client_close_waits_for_active_desktop_coordination(tmp_path: Path) -> None:
    """应用关闭必须等待正在执行桌面接管请求的后台协调线程完整退出。

    Args:
        tmp_path: Pytest隔离的源码、任务和假App Server状态目录。

    Returns:
        None；关闭过程在请求释放前保持等待，并在原线程启动后彻底结束后台线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    app_server.turn_start_gate = threading.Event()
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-close-worker-0001",
        )
    )
    assert task.client_handoff is not None

    # 等待后台线程进入被门闩阻塞的App Server请求，确保关闭测试覆盖真实竞态窗口。
    start_deadline = time.monotonic() + 2
    while app_server.turn_start_checks < 1 and time.monotonic() < start_deadline:
        time.sleep(0.01)
    assert app_server.turn_start_checks == 1

    # 独立关闭线程验证close不会在活动请求结束前提前返回或关闭任务存储。
    close_thread = threading.Thread(target=application.close, name="test-application-close")
    close_thread.start()
    time.sleep(0.05)
    assert close_thread.is_alive() is True

    app_server.turn_start_gate.set()
    close_thread.join(timeout=2)
    assert close_thread.is_alive() is False
    assert application._client_coordination_thread.is_alive() is False
    assert app_server.started_thread_ids == {task.client_handoff.thread_id}


def test_codex_client_snapshots_low_effort_and_prompt_template_per_attempt(tmp_path: Path) -> None:
    """活动聊天必须固定Low档位与创建时模板，后续设置修改只影响新任务。

    Args:
        tmp_path: Pytest隔离的本地设置、任务、Prompt诊断和假App Server目录。

    Returns:
        None；同attempt恢复原线程、模型档位和Prompt快照且只创建一次时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    first_template = "为 {{target_id}} 生成第一版完整业务知识。"
    application.runtime_settings.write(
        RuntimeToolSettings(
            knowledge_agent="codex",
            codex_reasoning_effort="low",
            knowledge_agent_prompt_template=first_template,
        )
    )
    request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-client-prompt-snapshot-0001",
        codex_model="gpt-5.6-sol",
        reasoning_effort="low",
    )

    first = application.submit_knowledge_target_generation(request)
    application.runtime_settings.write(
        RuntimeToolSettings(
            knowledge_agent="codex",
            knowledge_agent_prompt_template="为 {{target_id}} 生成后来修改的模板。",
        )
    )
    repeated = application.submit_knowledge_target_generation(request)

    assert repeated.task_id == first.task_id
    assert app_server.call_count == 1
    assert app_server.requests[0]["reasoning_effort"] == "low"
    assert "第一版完整业务知识" in app_server.requests[0]["prompt"]
    assert "后来修改的模板" not in app_server.requests[0]["prompt"]
    assert first.client_handoff is not None
    assert first.client_handoff.prompt_template_version


@pytest.mark.parametrize("reasoning_effort", ["medium", "low"])
def test_codex_client_snapshots_luna_generation_profiles(
    tmp_path: Path,
    reasoning_effort: str,
) -> None:
    """Luna的Medium和Low选择都应精确固化到线程请求与handoff。

    Args:
        tmp_path: Pytest为每个推理档位提供的隔离知识目录。
        reasoning_effort: 页面允许的Luna推理档位。

    Returns:
        None；本次请求、线程参数和持久handoff使用同一组合时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id=f"attempt-client-luna-{reasoning_effort}-0001",
            codex_model="gpt-5.6-luna",
            reasoning_effort=reasoning_effort,
        )
    )

    assert task.client_handoff is not None
    assert task.client_handoff.codex_model == "gpt-5.6-luna"
    assert task.client_handoff.reasoning_effort == reasoning_effort
    assert app_server.requests[0]["model"] == "gpt-5.6-luna"
    assert app_server.requests[0]["reasoning_effort"] == reasoning_effort
    # 首个turn由后台协调线程异步发起；等待可观察回执后再关闭应用，避免测试抢先终止worker。
    deadline = time.monotonic() + 1
    while not app_server.started_profiles and time.monotonic() < deadline:
        time.sleep(0.01)
    application.close()
    assert app_server.started_profiles == [("gpt-5.6-luna", reasoning_effort)]


def test_codex_client_completion_gaps_reuse_one_thread_without_round_limit(tmp_path: Path) -> None:
    """Facade候选持续改进时应始终复用原聊天且不受固定补全轮数限制。

    Args:
        tmp_path: Pytest隔离的源码、草稿、任务和假App Server目录。

    Returns:
        None；三次不同候选始终处于机器补全并绑定同一任务和线程时通过。
    """

    application, manifest, _target_id, source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    target_id = "facade:demo.ClientQueryJob#execute"
    facade_entry = EntryPoint(
        entry_id=target_id,
        system_id=SYSTEM_ID,
        kind="facade",
        display_name="客户端查询接口",
        source_id="demo.ClientQueryJob#execute",
        source_path=str(source_file),
        request_type="ClientQueryRequest",
        response_type="ClientQueryPage",
        tool_id="client-query",
    )
    facade_manifest = manifest.model_copy(update={"entries": [facade_entry]})
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(facade_manifest)
    artifacts.publish_latest(SYSTEM_ID, facade_manifest.scan_id)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=facade_manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-completion-rounds-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    thread_id = task.client_handoff.thread_id
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": source_file.name, "start_line": 1, "end_line": 1},
    )
    fixed_contract = application.get_knowledge_client_handoff(handoff_id)["deterministic_invocation_contract"]
    reference = {"path": source_file.name, "symbol": "ClientQueryJob#execute", "line": 1}

    # 每轮改变一个已填写章节以形成不同候选摘要，其余缺口持续阻止发布。
    observed = []
    for round_number in range(1, 4):
        candidate = KnowledgeClientCandidateEnvelope(
            status="completed",
            system_id=SYSTEM_ID,
            target_ids=[target_id],
            summaries=[],
            questions=[],
            source_refs=[reference],
            trace_steps=[
                {"sequence": 1, "role": "entry", "source_ref": reference, "summary": "真实入口源码"}
            ],
            completeness=AgentKnowledgeCompleteness(
                business_purpose=f"第{round_number}轮已经补充但仍不完整的接口业务目的说明。"
            ),
            invocation_contract=fixed_contract,
        )
        observed.append(
            application.submit_knowledge_client_candidate(
                handoff_id,
                KnowledgeClientCandidateSubmission(candidate=candidate),
            )
        )

    assert [item.status for item in observed] == [
        TaskStatus.WAITING_FOR_CLIENT,
        TaskStatus.WAITING_FOR_CLIENT,
        TaskStatus.WAITING_FOR_CLIENT,
    ]
    assert all(item.task_id == task.task_id for item in observed)
    assert all(item.client_handoff and item.client_handoff.thread_id == thread_id for item in observed)
    assert observed[-1].client_handoff is not None
    assert observed[-1].client_handoff.completion_round == 3
    assert observed[-1].client_handoff.completion_gaps
    assert app_server.call_count == 1
    assert application.store.list_nodes(SYSTEM_ID) == []
    refreshed_workflow = application.get_knowledge_workflow(SYSTEM_ID)
    assert refreshed_workflow.active_generation_status == "waiting_for_client"
    assert refreshed_workflow.generation_blocked_reason == "waiting_for_client"
    assert refreshed_workflow.next_action == "Codex正在原任务中生成或自动补全，无需人工确认"


def test_codex_client_needs_input_waits_in_same_task_then_auto_publishes(tmp_path: Path) -> None:
    """高影响业务疑点应展示在原任务，回答后的完整候选应自动发布。

    Args:
        tmp_path: pytest隔离的源码、问题、任务和知识目录。

    Returns:
        None；确定性事实先发布、问题保持开放且最终候选沿用原身份完成时通过。
    """

    application, manifest, target_id, source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-client-needs-input-0001",
    )
    task = application.submit_knowledge_target_generation(request)
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    thread_id = task.client_handoff.thread_id
    batch = application.store.read_draft_batch(SYSTEM_ID, task.client_handoff.batch_id)
    node_id = batch.drafts[0].node.node_id
    source_reference = {
        "path": source_file.name,
        "symbol": "ClientQueryJob#execute",
        "line": 1,
    }
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": source_file.name, "start_line": 1, "end_line": 1},
    )
    question_candidate = KnowledgeClientCandidateEnvelope(
        status="needs_input",
        system_id=SYSTEM_ID,
        target_ids=[target_id],
        summaries=[],
        questions=[
            {
                "title": "查询为空时是否应重试",
                "detail": "源码只显示一次仓储查询，无法确定空结果是否需要业务重试。",
                "affected_node_ids": [node_id],
                "affected_target_ids": [target_id],
                "category": "failure_policy",
                "why_asked": "不同选择会改变空结果用例的执行次数和最终断言。",
                "answer_type": "single_choice",
                "answer_options": ["直接返回空结果", "重试一次后返回"],
                "source_refs": [source_reference],
                "impact": "high",
            }
        ],
        source_refs=[source_reference],
        trace_steps=[
            {
                "sequence": 1,
                "role": "no_downstream",
                "source_ref": source_reference,
                "summary": "源码能证明查询入口，但未声明空结果业务策略。",
            }
        ],
    )

    # 顶层trace不能替代问题自身的源码证据；空问题引用必须在进入人工等待前被拒绝。
    question_without_source = question_candidate.model_copy(
        update={
            "questions": [
                question_candidate.questions[0].model_copy(update={"source_refs": []})
            ]
        }
    )
    with pytest.raises(KnowledgeValidationError, match="question with source references"):
        application.submit_knowledge_client_candidate(
            handoff_id,
            KnowledgeClientCandidateSubmission(candidate=question_without_source),
        )

    waiting = application.submit_knowledge_client_candidate(
        handoff_id,
        KnowledgeClientCandidateSubmission(candidate=question_candidate),
    )

    assert waiting.status == TaskStatus.WAITING_FOR_INPUT
    assert waiting.task_id == task.task_id
    assert waiting.client_handoff is not None
    assert waiting.client_handoff.thread_id == thread_id
    assert waiting.result["question_count"] == 1
    assert waiting.result["pending_questions"][0]["title"] == "查询为空时是否应重试"
    published_before_answer = application.store.list_nodes(SYSTEM_ID)
    assert len(published_before_answer) == 1
    assert published_before_answer[0][0].status == KnowledgeStatus.CODE_VERIFIED
    handoff_payload = application.get_knowledge_client_handoff(handoff_id)
    assert handoff_payload["pending_questions"][0].title == "查询为空时是否应重试"

    # 刷新或重复生成使用同一attempt恢复任务时，必须保留问题卡和原线程身份。
    recovered_waiting = application.submit_knowledge_target_generation(request)
    assert recovered_waiting.task_id == task.task_id
    assert recovered_waiting.client_handoff is not None
    assert recovered_waiting.client_handoff.thread_id == thread_id
    assert recovered_waiting.result["pending_questions"][0]["title"] == "查询为空时是否应重试"
    workflow_snapshot = application.get_knowledge_workflow(SYSTEM_ID)
    assert workflow_snapshot.next_action == "在原Codex任务中回答高影响业务问题后继续"

    # 用户已在原Codex任务回答后，客户端只需提交不再含开放问题的完整候选。
    completed_candidate = KnowledgeClientCandidateEnvelope(
        status="completed",
        system_id=SYSTEM_ID,
        target_ids=[target_id],
        summaries=[
            {
                "node_id": node_id,
                "summary": "空查询结果按用户确认口径直接返回，不额外发起重试。",
                "test_points": _agent_test_points(),
            }
        ],
        questions=[],
        source_refs=[source_reference],
        trace_steps=[
            {
                "sequence": 1,
                "role": "no_downstream",
                "source_ref": source_reference,
                "summary": "任务入口的唯一仓储查询调用已被源码读取覆盖。",
            }
        ],
        completeness=AgentKnowledgeCompleteness(
            business_purpose="客户端查询任务用于读取当前业务结果并按确认口径返回空集合。"
        ),
    )
    completed = application.submit_knowledge_client_candidate(
        handoff_id,
        KnowledgeClientCandidateSubmission(candidate=completed_candidate),
    )

    assert completed.status == TaskStatus.COMPLETED
    assert completed.task_id == task.task_id
    assert completed.client_handoff is not None
    assert completed.client_handoff.thread_id == thread_id
    assert completed.client_handoff.status.value == "published"
    stored_questions = application.store.list_questions(SYSTEM_ID)
    assert len(stored_questions) == 1
    assert stored_questions[0].status == "dismissed"
    assert app_server.call_count == 1


def test_codex_client_machine_gaps_continue_then_publish_in_original_thread(tmp_path: Path) -> None:
    """仅缺失败处理和测试断言的Facade候选应自动续跑并在原线程发布。

    Args:
        tmp_path: pytest隔离的Facade源码、任务和桌面协调快照。

    Returns:
        None；机器缺口触发同线程下一turn且补齐后自动发布时通过。
    """

    application, manifest, _target_id, source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    # 本用例逐步控制turn完成时点，先停止周期协调器以消除后台轮询竞态。
    application._client_coordination_stop.set()
    application._client_coordination_wakeup.set()
    application._client_coordination_thread.join(timeout=2)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    service_file = source_root / "ClientQueryService.java"
    repository_file = source_root / "ClientQueryRepository.java"
    source_file.write_text(
        "package demo; class ClientQueryJob { ClientQueryService service; void execute() { service.query(); } }\n",
        encoding="utf-8",
    )
    service_file.write_text(
        "package demo; class ClientQueryService { ClientQueryRepository repository; void query() { repository.query(); } }\n",
        encoding="utf-8",
    )
    repository_file.write_text(
        "package demo; interface ClientQueryRepository { void query(); }\n",
        encoding="utf-8",
    )
    target_id = "facade:demo.ClientQueryJob#execute"
    facade_entry = EntryPoint(
        entry_id=target_id,
        system_id=SYSTEM_ID,
        kind="facade",
        display_name="客户端查询接口",
        source_id="demo.ClientQueryJob#execute",
        source_path=str(source_file),
        request_type="ClientQueryRequest",
        response_type="ClientQueryPage",
        tool_id="client-query",
    )
    facade_manifest = manifest.model_copy(
        update={
            "entries": [facade_entry],
            "baseline": application.knowledge.git_repository.capture(source_root),
        }
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(facade_manifest)
    artifacts.publish_latest(SYSTEM_ID, facade_manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, facade_manifest.baseline)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=facade_manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-machine-closure-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    thread_id = task.client_handoff.thread_id
    initial_start = application.start_knowledge_client_turn(handoff_id)
    assert initial_start["state"] == "started"
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": source_file.name, "start_line": 1, "end_line": 1},
    )
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": service_file.name, "start_line": 1, "end_line": 1},
    )
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": repository_file.name, "start_line": 1, "end_line": 1},
    )
    handoff_payload = application.get_knowledge_client_handoff(handoff_id)
    node_id = handoff_payload["candidate_node_ids"][0]
    fixed_contract = handoff_payload["deterministic_invocation_contract"]
    reference = {"path": source_file.name, "symbol": "ClientQueryJob#execute", "line": 1}
    service_reference = {"path": service_file.name, "symbol": "ClientQueryService#query", "line": 1}
    repository_reference = {
        "path": repository_file.name,
        "symbol": "ClientQueryRepository#query",
        "line": 1,
    }
    trace_steps = [
        {"sequence": 1, "role": "entry", "source_ref": reference, "summary": "Facade入口接收查询请求。"},
        {"sequence": 2, "role": "service", "source_ref": service_reference, "summary": "业务层执行查询流程。"},
        {"sequence": 3, "role": "data_access", "source_ref": repository_reference, "summary": "仓储边界读取查询结果。"},
    ]
    base_completeness = {
        "business_purpose": "该接口用于根据客户端查询条件读取业务结果并返回分页数据集合。",
        "applicable_scenarios": "适用于调用方需要按稳定查询条件浏览当前可见业务记录的场景。",
        "input_semantics": "请求包含业务筛选条件和分页参数，缺失必填条件时不得进入仓储查询。",
        "output_semantics": "响应返回匹配记录、分页位置和总量，空结果使用空集合表达而不是异常。",
        "business_flow": "入口校验请求后进入业务查询阶段，再访问仓储并组装分页响应返回调用方。",
        "important_branches": "合法条件进入查询主流程，无匹配记录进入空集合分支并保留分页元数据。",
        "failure_handling": "",
        "test_oracles": "",
    }
    incomplete_candidate = KnowledgeClientCandidateEnvelope(
        status="completed",
        system_id=SYSTEM_ID,
        target_ids=[target_id],
        summaries=[
            {
                "node_id": node_id,
                "summary": "接口完成校验、仓储查询和分页响应组装。",
                "test_points": _agent_test_points(),
            }
        ],
        questions=[],
        source_refs=[reference, service_reference, repository_reference],
        trace_steps=trace_steps,
        completeness=AgentKnowledgeCompleteness(**base_completeness),
        invocation_contract=fixed_contract,
    )

    waiting = application.submit_knowledge_client_candidate(
        handoff_id,
        KnowledgeClientCandidateSubmission(candidate=incomplete_candidate),
    )

    assert waiting.status == TaskStatus.WAITING_FOR_CLIENT
    assert waiting.client_handoff is not None
    assert waiting.client_handoff.completion_gaps == [
        "missing_or_shallow:failure_handling",
        "missing_or_shallow:test_oracles",
    ]
    assert waiting.result["start_state"] == "started"
    # App Server存储短暂尚未看见桌面已接受的turn时，持久启动回执仍要阻止第二次模型调用。
    app_server.turn_count_by_thread[thread_id] = 0
    app_server.turn_status_by_thread[thread_id] = ""
    duplicate_during_projection_lag = application.start_knowledge_client_turn(handoff_id)
    assert duplicate_during_projection_lag["state"] == "already_started"
    assert app_server.turn_start_checks == 1
    # 只读投影短暂返回旧turn的终态时，不得把桌面已经启动的新turn误写为失败。
    app_server.turn_count_by_thread[thread_id] = 1
    app_server.latest_turn_id_by_thread[thread_id] = "turn-stale-before-desktop-start"
    app_server.turn_status_by_thread[thread_id] = "interrupted"
    stale_projection = application.start_knowledge_client_turn(handoff_id)
    stale_task = stale_projection["task"]
    assert stale_projection["state"] == "already_started"
    assert stale_task.status == TaskStatus.WAITING_FOR_CLIENT
    assert stale_task.client_handoff is not None
    assert stale_task.client_handoff.status == KnowledgeClientHandoffStatus.WAITING_FOR_CLIENT
    assert app_server.turn_start_checks == 1
    # 桌面owner仍在执行时，同一turn也可能短暂投影为interrupted，必须继续等待真实稳定状态。
    app_server.latest_turn_id_by_thread[thread_id] = waiting.result["turn_id"]
    app_server.turn_status_by_thread[thread_id] = "interrupted"
    interrupted_projection = application.start_knowledge_client_turn(handoff_id)
    assert interrupted_projection["state"] == "already_started"
    assert interrupted_projection["task"].status == TaskStatus.WAITING_FOR_CLIENT
    assert app_server.turn_start_checks == 1
    # 真实目标turn投影为运行中后仍只等待；完成后才允许进入既有自动补全路径。
    app_server.turn_status_by_thread[thread_id] = "inProgress"
    active_projection = application.start_knowledge_client_turn(handoff_id)
    assert active_projection["state"] == "already_started"
    assert active_projection["task"].status == TaskStatus.WAITING_FOR_CLIENT
    assert app_server.turn_start_checks == 1
    app_server.complete_latest_turn(thread_id)
    continuation = application.start_knowledge_client_turn(handoff_id)
    assert continuation["state"] == "started"
    assert app_server.turn_count_by_thread[thread_id] == 2
    assert app_server.call_count == 1

    completed_candidate = incomplete_candidate.model_copy(
        update={
            "completeness": AgentKnowledgeCompleteness(
                **{
                    **base_completeness,
                    "failure_handling": "请求校验失败时返回明确参数错误，仓储访问失败时保留原异常边界且不伪造空结果。",
                    "test_oracles": "测试应断言合法查询返回分页结构、空结果保持空集合、非法参数不访问仓储且失败可定位。",
                }
            )
        }
    )
    completed = application.submit_knowledge_client_candidate(
        handoff_id,
        KnowledgeClientCandidateSubmission(candidate=completed_candidate),
    )

    assert completed.status == TaskStatus.COMPLETED
    assert completed.task_id == task.task_id
    assert completed.client_handoff is not None
    assert completed.client_handoff.thread_id == thread_id
    assert completed.client_handoff.status.value == "published"
    assert app_server.call_count == 1


def test_codex_client_matching_failed_turn_fails_handoff(tmp_path: Path) -> None:
    """桌面回执对应的真实turn明确失败时才应终结handoff。

    Args:
        tmp_path: pytest隔离的持久任务、handoff和只读turn快照。

    Returns:
        None；仅匹配目标turn身份的明确failed终态写入handoff失败时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(
        tmp_path
    )
    # 停止周期协调器，确保本用例只由显式调用推进目标turn状态。
    application._client_coordination_stop.set()
    application._client_coordination_wakeup.set()
    application._client_coordination_thread.join(timeout=2)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-terminal-failed-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    thread_id = task.client_handoff.thread_id
    started = application.start_knowledge_client_turn(handoff_id)
    requested_turn_id = started["task"].result["turn_id"]
    # 终态只有与桌面启动回执中的turn身份一致时，才构成可确认的执行失败。
    app_server.latest_turn_id_by_thread[thread_id] = requested_turn_id
    app_server.turn_status_by_thread[thread_id] = "failed"

    terminal = application.start_knowledge_client_turn(handoff_id)
    failed_task = terminal["task"]

    assert terminal["state"] == "already_started"
    assert failed_task.status == TaskStatus.FAILED
    assert failed_task.task_id == task.task_id
    assert failed_task.client_handoff is not None
    assert failed_task.client_handoff.handoff_id == handoff_id
    assert failed_task.client_handoff.status == KnowledgeClientHandoffStatus.FAILED
    assert "Codex任务未正常完成" in failed_task.error
    assert app_server.turn_start_checks == 1
    assert app_server.turn_count_by_thread[thread_id] == 1


def test_codex_client_two_identical_completed_turns_fail_without_new_identity(tmp_path: Path) -> None:
    """只有连续两个已结束turn的实际候选摘要和缺口均未变化才技术失败。

    Args:
        tmp_path: pytest隔离的Facade候选、任务和桌面turn快照。

    Returns:
        None；40x拒绝前已写入的改进候选会重置计数，随后两回合完全相同才停止时通过。
    """

    application, manifest, _target_id, source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    # 本用例需要精确控制连续完成turn，停止周期协调器后全部通过幂等入口手动推进。
    application._client_coordination_stop.set()
    application._client_coordination_wakeup.set()
    application._client_coordination_thread.join(timeout=2)
    target_id = "facade:demo.ClientQueryJob#execute"
    facade_manifest = manifest.model_copy(
        update={
            "entries": [
                EntryPoint(
                    entry_id=target_id,
                    system_id=SYSTEM_ID,
                    kind="facade",
                    display_name="客户端查询接口",
                    source_id="demo.ClientQueryJob#execute",
                    source_path=str(source_file),
                    request_type="ClientQueryRequest",
                    response_type="ClientQueryPage",
                    tool_id="client-query",
                )
            ]
        }
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(facade_manifest)
    artifacts.publish_latest(SYSTEM_ID, facade_manifest.scan_id)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=facade_manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-no-progress-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    thread_id = task.client_handoff.thread_id
    initial_start = application.start_knowledge_client_turn(handoff_id)
    assert initial_start["state"] == "started"
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": source_file.name, "start_line": 1, "end_line": 1},
    )
    handoff_payload = application.get_knowledge_client_handoff(handoff_id)
    reference = {"path": source_file.name, "symbol": "ClientQueryJob#execute", "line": 1}
    incomplete_candidate = KnowledgeClientCandidateEnvelope(
        status="completed",
        system_id=SYSTEM_ID,
        target_ids=[target_id],
        summaries=[],
        questions=[],
        source_refs=[reference],
        trace_steps=[{"sequence": 1, "role": "entry", "source_ref": reference, "summary": "真实入口源码"}],
        completeness=AgentKnowledgeCompleteness(business_purpose="查询接口用于读取当前客户端需要的业务数据列表。"),
        invocation_contract=handoff_payload["deterministic_invocation_contract"],
    )
    waiting = application.submit_knowledge_client_candidate(
        handoff_id,
        KnowledgeClientCandidateSubmission(candidate=incomplete_candidate),
    )
    assert waiting.status == TaskStatus.WAITING_FOR_CLIENT

    # 初始turn结束后在原任务发起第一次机器续跑。
    app_server.complete_latest_turn(thread_id)
    first_continuation = application.start_knowledge_client_turn(handoff_id)
    assert first_continuation["state"] == "started"
    assert first_continuation["task"].client_handoff is not None
    run_root = application.knowledge._client_run_root(first_continuation["task"].client_handoff)
    # 模拟候选在完整校验前被40x拒绝；handoff旧摘要未更新，但实际输出已发生改进。
    application.knowledge._write_private_client_file(
        run_root / "output.txt",
        '{"candidate":"changed-before-validation"}',
    )
    app_server.complete_latest_turn(thread_id)
    second_continuation = application.start_knowledge_client_turn(handoff_id)
    assert second_continuation["state"] == "started"

    # 只有下一个已结束turn仍保持完全相同的输出与缺口时才达到无进展上限。
    app_server.complete_latest_turn(thread_id)
    stopped = application.start_knowledge_client_turn(handoff_id)
    failed = stopped["task"]

    assert failed.status == TaskStatus.FAILED
    assert failed.task_id == task.task_id
    assert failed.client_handoff is not None
    assert failed.client_handoff.handoff_id == handoff_id
    assert failed.client_handoff.thread_id == thread_id
    assert failed.client_handoff.no_progress_turns == 2
    assert "连续两个回合" in failed.error
    assert app_server.turn_count_by_thread[thread_id] == 3
    assert app_server.call_count == 1


def test_codex_client_recovers_reported_waiting_completion_session_in_place(tmp_path: Path) -> None:
    """历史两轮停止会话应原地迁回机器补全并继续同一桌面任务。

    Args:
        tmp_path: pytest隔离的历史任务、handoff和只读线程快照。

    Returns:
        None；报告会话ID及task、batch、scan身份全部保持不变时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    application._client_coordination_stop.set()
    application._client_coordination_wakeup.set()
    application._client_coordination_thread.join(timeout=2)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-reported-waiting-completion-0001",
        )
    )
    assert task.client_handoff is not None
    reported_thread_id = "01a03864-e624-7e12-ba88-ec822f07371d"
    historical_handoff = task.client_handoff.model_copy(
        update={
            "thread_id": reported_thread_id,
            "deep_link": f"codex://threads/{reported_thread_id}",
            "status": KnowledgeClientHandoffStatus.WAITING_FOR_COMPLETION,
            "completion_round": 2,
            "completion_gaps": [
                "missing_or_shallow:failure_handling",
                "missing_or_shallow:test_oracles",
            ],
        }
    )
    application.knowledge.bind_client_handoff_thread(
        SYSTEM_ID,
        historical_handoff.batch_id,
        historical_handoff,
    )
    application.tasks.transition_waiting_task(
        task.task_id,
        TaskStatus.WAITING_FOR_COMPLETION,
        historical_handoff,
        task.result,
    )
    app_server.turn_count_by_thread[reported_thread_id] = 1
    app_server.turn_status_by_thread[reported_thread_id] = "completed"

    recovered = application.start_knowledge_client_turn(historical_handoff.handoff_id)
    recovered_task = recovered["task"]
    recovered_batch = application.store.read_draft_batch(SYSTEM_ID, historical_handoff.batch_id)

    assert recovered["state"] == "started"
    assert recovered_task.task_id == task.task_id
    assert recovered_task.status == TaskStatus.WAITING_FOR_CLIENT
    assert recovered_task.client_handoff is not None
    assert recovered_task.client_handoff.handoff_id == historical_handoff.handoff_id
    assert recovered_task.client_handoff.thread_id == reported_thread_id
    assert recovered_task.client_handoff.batch_id == historical_handoff.batch_id
    assert recovered_task.client_handoff.scan_id == manifest.scan_id
    assert recovered_batch.client_handoff is not None
    assert recovered_batch.client_handoff.thread_id == reported_thread_id
    assert app_server.turn_count_by_thread[reported_thread_id] == 2
    assert app_server.call_count == 1


def test_codex_client_reported_conflict_session_falls_back_to_original_task(tmp_path: Path) -> None:
    """桌面IPC未接管报告冲突会话时应只提示原任务手动开始。

    Args:
        tmp_path: pytest隔离的持久任务、handoff和桌面降级状态。

    Returns:
        None；报告会话深链保留且OpenTest未创建第二线程或取得写入权时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    application._client_coordination_stop.set()
    application._client_coordination_wakeup.set()
    application._client_coordination_thread.join(timeout=2)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-reported-owner-conflict-0001",
        )
    )
    assert task.client_handoff is not None
    reported_thread_id = "01a0394b-9bdf-7e42-bdc9-eed7c1ef8b40"
    reported_handoff = task.client_handoff.model_copy(
        update={
            "thread_id": reported_thread_id,
            "deep_link": f"codex://threads/{reported_thread_id}",
        }
    )
    application.knowledge.bind_client_handoff_thread(
        SYSTEM_ID,
        reported_handoff.batch_id,
        reported_handoff,
    )
    application.tasks.transition_waiting_task(
        task.task_id,
        TaskStatus.WAITING_FOR_CLIENT,
        reported_handoff,
        task.result,
    )
    app_server.turn_start_failures_remaining = 1

    fallback = application.start_knowledge_client_turn(reported_handoff.handoff_id)
    fallback_task = fallback["task"]

    assert fallback["state"] == "manual_required"
    assert fallback_task.task_id == task.task_id
    assert fallback_task.status == TaskStatus.WAITING_FOR_CLIENT
    assert fallback_task.client_handoff is not None
    assert fallback_task.client_handoff.thread_id == reported_thread_id
    assert fallback_task.client_handoff.deep_link == f"codex://threads/{reported_thread_id}"
    assert fallback_task.result["start_state"] == "manual_required"
    assert "desktop failure" in fallback_task.result["manual_message"]
    assert app_server.call_count == 1
    assert app_server.turn_count_by_thread.get(reported_thread_id, 0) == 0


def test_codex_client_cancel_repairs_task_after_terminal_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """批次取消成功但任务终态写失败时，重复取消必须补齐同一任务而不永久阻塞。

    Args:
        tmp_path: Pytest隔离的任务、handoff和草稿目录。
        monkeypatch: 首次任务CANCELLED落盘时注入一次I/O失败。

    Returns:
        None；第二次请求幂等修复任务且不创建新聊天时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-cancel-repair-0001",
        )
    )
    original_transition = application.tasks.transition_waiting_task
    failed_once = False

    def fail_first_cancel(*args: object, **kwargs: object) -> object:
        """仅让首次CANCELLED任务写失败，保留批次已提交的恢复现场。

        Args:
            args: 原状态转换的位置参数。
            kwargs: 原状态转换的命名参数。

        Returns:
            非首次取消调用的真实任务记录。

        Raises:
            OSError: 首次CANCELLED任务文件写入时固定抛出。
        """

        nonlocal failed_once
        status = args[1] if len(args) > 1 else kwargs.get("status")
        if status == TaskStatus.CANCELLED and not failed_once:
            failed_once = True
            raise OSError("simulated cancelled task write failure")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(application.tasks, "transition_waiting_task", fail_first_cancel)
    with pytest.raises(OSError, match="cancelled task write failure"):
        application.cancel_task_agent(task.task_id)

    # 批次已是CANCELLED而任务仍等待；相同请求只补写任务终态，不再修改线程或创建聊天。
    repaired = application.cancel_task_agent(task.task_id)

    assert repaired.status == TaskStatus.CANCELLED
    assert repaired.client_handoff is not None
    assert repaired.client_handoff.status.value == "cancelled"
    assert app_server.call_count == 1


def test_codex_client_rejects_a_second_active_knowledge_chat_for_another_target(
    tmp_path: Path,
) -> None:
    """任一Codex知识聊天活动时必须阻止其他目标并发创建第二聊天。

    Args:
        tmp_path: Pytest隔离的源码、扫描、草稿和任务目录。

    Returns:
        None；第二目标被全局单聊天门禁拒绝且App Server只创建一次线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    other_source = source_root / "AnotherClientQueryJob.java"
    other_source.write_text(
        "package demo; class AnotherClientQueryJob { void execute() { repository.query(); } }\n",
        encoding="utf-8",
    )
    other_target_id = "job:demo.AnotherClientQueryJob"
    refreshed_manifest = manifest.model_copy(
        update={
            "baseline": application.knowledge.git_repository.capture(source_root),
            "entries": [
                *manifest.entries,
                EntryPoint(
                    entry_id=other_target_id,
                    system_id=SYSTEM_ID,
                    kind="job",
                    display_name="另一个客户端查询任务",
                    source_id="demo.AnotherClientQueryJob",
                    source_path=str(other_source),
                ),
            ],
        }
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(refreshed_manifest)
    artifacts.publish_latest(SYSTEM_ID, refreshed_manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, refreshed_manifest.baseline)

    # 第一个页面操作占用唯一知识聊天；不同目标也不能绕过单目标幂等键并发创建线程。
    first = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=refreshed_manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-single-active-chat-0001",
        )
    )
    with pytest.raises(ScopeViolationError, match="已有一个Codex知识聊天"):
        application.submit_knowledge_target_generation(
            KnowledgeTargetGenerationRequest(
                system_id=SYSTEM_ID,
                target_id=other_target_id,
                scan_id=refreshed_manifest.scan_id,
                agent="codex",
                confirmed=True,
                interaction_mode="codex_client",
                intent="initial",
                attempt_id="attempt-single-active-chat-0002",
            )
        )

    assert first.status == TaskStatus.WAITING_FOR_CLIENT
    assert app_server.call_count == 1


def test_codex_client_rejects_a_second_active_chat_across_systems(tmp_path: Path) -> None:
    """一个系统的活动聊天必须阻止另一个系统顺序创建第二聊天。

    Args:
        tmp_path: Pytest提供的隔离源码、扫描、任务和草稿目录。

    Returns:
        None；跨系统第二次提交被拒绝且App Server只收到一次创建请求时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    other_system_id = "other-client-system"
    other_manifest, other_target_id = _register_additional_codex_client_target(
        application,
        tmp_path,
        other_system_id,
    )
    first_request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-cross-system-first-0001",
    )
    second_request = KnowledgeTargetGenerationRequest(
        system_id=other_system_id,
        target_id=other_target_id,
        scan_id=other_manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-cross-system-second-0002",
    )

    first = application.submit_knowledge_target_generation(first_request)
    with pytest.raises(ScopeViolationError, match="已有一个Codex知识聊天"):
        application.submit_knowledge_target_generation(second_request)

    assert first.status == TaskStatus.WAITING_FOR_CLIENT
    assert app_server.call_count == 1


def test_codex_client_serializes_concurrent_cross_system_chat_creation(tmp_path: Path) -> None:
    """两个系统同时点击生成时只能有一个线程越过全局创建门禁。

    Args:
        tmp_path: Pytest提供的隔离源码、扫描、任务和草稿目录。

    Returns:
        None；并发提交恰有一个成功、一个被拒绝且只创建一个App Server线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    other_system_id = "concurrent-client-system"
    other_manifest, other_target_id = _register_additional_codex_client_target(
        application,
        tmp_path,
        other_system_id,
    )
    requests = [
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-concurrent-first-0001",
        ),
        KnowledgeTargetGenerationRequest(
            system_id=other_system_id,
            target_id=other_target_id,
            scan_id=other_manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-concurrent-second-0002",
        ),
    ]
    start_barrier = threading.Barrier(2)
    completed: list[TaskRecord] = []
    rejected: list[Exception] = []

    def submit(request: KnowledgeTargetGenerationRequest) -> None:
        """在共同起跑点提交一个跨系统客户端生成请求并收集确定结果。

        Args:
            request: 绑定唯一系统、目标和attempt的客户端生成请求。

        Returns:
            None；成功任务或拒绝异常写入线程安全的测试结果列表。
        """

        start_barrier.wait(timeout=2)
        try:
            completed.append(application.submit_knowledge_target_generation(request))
        except Exception as exc:  # noqa: BLE001 - 测试需要证明竞争败方的精确领域异常。
            rejected.append(exc)

    workers = [threading.Thread(target=submit, args=(request,)) for request in requests]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert all(not worker.is_alive() for worker in workers)
    assert len(completed) == 1
    assert completed[0].status == TaskStatus.WAITING_FOR_CLIENT
    assert len(rejected) == 1
    assert isinstance(rejected[0], ScopeViolationError)
    assert app_server.call_count == 1


def test_codex_client_active_system_cannot_be_archived_to_bypass_single_chat(
    tmp_path: Path,
) -> None:
    """活动Codex知识聊天所属系统不得归档后从注册表逃逸全局门禁。

    Args:
        tmp_path: Pytest隔离的系统、归档、任务和草稿目录。

    Returns:
        None；归档被拒绝且原系统、任务和唯一聊天均保持活动时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-active-system-archive-0001",
        )
    )

    with pytest.raises(ScopeViolationError, match="Codex知识聊天"):
        application.archive_system(SYSTEM_ID, "不得隐藏活动知识聊天")

    assert task.status == TaskStatus.WAITING_FOR_CLIENT
    assert application.store.get_system(SYSTEM_ID).system_id == SYSTEM_ID
    assert application.list_archives() == []
    assert app_server.call_count == 1


def test_codex_client_legacy_active_archive_blocks_new_chat_creation(tmp_path: Path) -> None:
    """旧归档中的等待聊天本身仍占用全仓库唯一聊天名额。

    Args:
        tmp_path: Pytest提供的隔离系统、归档、任务和草稿目录。

    Returns:
        None；新聊天创建被拒绝且没有产生第二个App Server线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-legacy-archive-active-0001",
        )
    )
    # 直接调用归档适配器模拟升级前已经存在的活动handoff归档；生产入口如今会拒绝这种归档。
    legacy_archive = application.archives.archive(SYSTEM_ID, "模拟升级前活动归档")
    other_system_id = "current-chat-system"
    other_manifest, other_target_id = _register_additional_codex_client_target(
        application,
        tmp_path,
        other_system_id,
    )
    with pytest.raises(ScopeViolationError, match="已有一个Codex知识聊天"):
        application.submit_knowledge_target_generation(
            KnowledgeTargetGenerationRequest(
                system_id=other_system_id,
                target_id=other_target_id,
                scan_id=other_manifest.scan_id,
                agent="codex",
                confirmed=True,
                interaction_mode="codex_client",
                intent="initial",
                attempt_id="attempt-current-chat-active-0002",
            )
        )

    assert application.store.get_system(other_system_id).system_id == other_system_id
    assert application.archives.active_codex_client_handoff_count(legacy_archive.archive_id) == 1
    assert app_server.call_count == 1


def test_codex_client_serializes_legacy_restore_and_new_chat_creation(tmp_path: Path) -> None:
    """旧活动归档恢复与新聊天并发时只能有一个操作成功。

    Args:
        tmp_path: Pytest提供的隔离系统、归档、任务和草稿目录。

    Returns:
        None；恢复或创建恰有一个成功，仓库最终仍只有一个活动聊天时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    # 本用例只验证归档恢复与新建互斥，停止桌面协调器避免它并发更新待归档草稿摘要。
    application._client_coordination_stop.set()
    application._client_coordination_wakeup.set()
    application._client_coordination_thread.join(timeout=2)
    application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-concurrent-archive-active-0001",
        )
    )
    legacy_archive = application.archives.archive(SYSTEM_ID, "模拟并发恢复的旧活动归档")
    other_system_id = "restore-race-system"
    other_manifest, other_target_id = _register_additional_codex_client_target(
        application,
        tmp_path,
        other_system_id,
    )
    new_chat_request = KnowledgeTargetGenerationRequest(
        system_id=other_system_id,
        target_id=other_target_id,
        scan_id=other_manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-restore-race-new-chat-0002",
    )
    start_barrier = threading.Barrier(2)
    completed: list[object] = []
    rejected: list[Exception] = []

    def restore_legacy() -> None:
        """在共同起跑点恢复旧活动归档并记录结果。"""

        start_barrier.wait(timeout=2)
        try:
            completed.append(application.restore_system(legacy_archive.archive_id))
        except Exception as exc:  # noqa: BLE001 - 测试收集竞争败方后断言领域异常。
            rejected.append(exc)

    def create_new_chat() -> None:
        """在共同起跑点创建另一个系统的新聊天并记录结果。"""

        start_barrier.wait(timeout=2)
        try:
            completed.append(application.submit_knowledge_target_generation(new_chat_request))
        except Exception as exc:  # noqa: BLE001 - 测试收集竞争败方后断言领域异常。
            rejected.append(exc)

    workers = [threading.Thread(target=restore_legacy), threading.Thread(target=create_new_chat)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert all(not worker.is_alive() for worker in workers)
    assert len(completed) == 1
    assert len(rejected) == 1
    assert isinstance(rejected[0], ScopeViolationError)
    assert application._active_codex_client_handoff() is not None
    # 准备旧归档只创建一次线程；只有新聊天竞争成功时才会再创建一次。
    assert app_server.call_count in {1, 2}


def test_codex_client_normalizes_read_source_reference_shorthand_before_audit(
    tmp_path: Path,
) -> None:
    """客户端候选的Java方法简称和Mapper节点引用应在安全读取范围内自动规范化。

    Args:
        tmp_path: Pytest隔离的源码、扫描、候选和任务目录。

    Returns:
        None；等价引用被规范化并进入等待最终确认状态时通过。
    """

    application, manifest, target_id, source_file, _app_server = _prepare_codex_client_handoff_system(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    mapper_path = source_root / "DemoMapper.xml"
    mapper_path.write_text(
        '<mapper namespace="demo.DemoMapper">\n'
        '  <select id="listPage">\n'
        "    select 1\n"
        "  </select>\n"
        "</mapper>\n",
        encoding="utf-8",
    )
    refreshed_manifest = manifest.model_copy(
        update={"baseline": application.knowledge.git_repository.capture(source_root)}
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(refreshed_manifest)
    artifacts.publish_latest(SYSTEM_ID, refreshed_manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, refreshed_manifest.baseline)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=refreshed_manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-normalize-client-refs-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    relative_java = source_file.relative_to(source_root).as_posix()
    relative_mapper = mapper_path.relative_to(source_root).as_posix()

    # 两个引用都必须先经过真实read_source；规范化只消除格式差异，不放宽访问范围。
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": relative_java, "start_line": 1, "end_line": 1},
    )
    application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": relative_mapper, "start_line": 1, "end_line": 5},
    )
    workflow = application.store.read_draft_batch(SYSTEM_ID, task.client_handoff.batch_id)
    java_reference = {"path": relative_java, "symbol": "execute", "line": 1}
    mapper_reference = {"path": relative_mapper, "symbol": "DemoMapper#listPage", "line": 3}
    candidate = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": SYSTEM_ID,
            "target_ids": [target_id],
            "summaries": [
                {
                    "node_id": workflow.drafts[0].node.node_id,
                    "summary": "查询任务读取Mapper边界。",
                    "test_points": _agent_test_points(),
                }
            ],
            "questions": [],
            "source_refs": [java_reference, mapper_reference],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "no_downstream",
                    "source_ref": java_reference,
                    "summary": "测试Job读取已验证的Mapper边界。",
                }
            ],
        }
    )

    waiting = application.submit_knowledge_client_candidate(
        handoff_id,
        KnowledgeClientCandidateSubmission(candidate=candidate),
    )

    assert waiting.status == TaskStatus.WAITING_FOR_CONFIRMATION
    stored_candidate = AgentKnowledgeEnvelope.model_validate_json(
        (application.knowledge._client_run_root(waiting.client_handoff) / "output.txt").read_text(encoding="utf-8")
    )
    normalized = {(reference.path, reference.symbol, reference.line) for reference in stored_candidate.source_refs}
    assert (relative_java, "ClientQueryJob#execute", 1) in normalized
    assert (relative_mapper, "listPage", 2) in normalized


def test_codex_client_app_server_failure_persists_task_and_allows_new_attempt(
    tmp_path: Path,
) -> None:
    """线程创建瞬时失败必须形成可恢复终态，并允许用户显式发起新attempt。

    Args:
        tmp_path: pytest隔离的源码、草稿、任务和假App Server。

    Returns:
        None；失败attempt幂等恢复同一任务，新attempt可创建唯一新线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    original_create_thread = app_server.create_thread
    call_count = 0

    def flaky_create_thread(
        prompt: str,
        title: str,
        cwd: Path,
        developer_instructions: str,
        model: str,
        reasoning_effort: str,
    ) -> object:
        """首次模拟App Server失败，后续按同一模型档位恢复无turn线程创建。"""

        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ExecutionFailure("temporary App Server failure")
        return original_create_thread(prompt, title, cwd, developer_instructions, model, reasoning_effort)

    app_server.create_thread = flaky_create_thread
    failed_request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-client-app-server-failed-0001",
    )

    failed = application.submit_knowledge_target_generation(failed_request)
    repeated = application.submit_knowledge_target_generation(failed_request)
    recovered = application.submit_knowledge_target_generation(
        failed_request.model_copy(update={"attempt_id": "attempt-client-app-server-retry-0002"})
    )

    assert failed.status == TaskStatus.FAILED
    assert failed.task_id == repeated.task_id
    assert "未调用模型" in failed.error
    assert recovered.status == TaskStatus.WAITING_FOR_CLIENT
    assert recovered.task_id != failed.task_id
    assert call_count == 2


def test_codex_client_candidate_requires_real_read_audit_and_confirmation_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """客户端候选必须绑定真实read_source，确认前不得覆盖当前知识。

    Args:
        tmp_path: pytest隔离的源码、handoff审计、候选与知识目录。
        monkeypatch: 模拟发布后领域刷新异常及任务终态首次写入失败。

    Returns:
        None；无审计候选被拒、合法候选等待确认且接受后仍保持INFERRED来源时通过。
    """

    application, manifest, target_id, source_file, _app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-confirmation-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    batch = application.store.read_draft_batch(SYSTEM_ID, task.client_handoff.batch_id)
    node_ids = [draft.node.node_id for draft in batch.drafts]
    relative_path = source_file.relative_to(Path(application.store.get_system(SYSTEM_ID).source_path)).as_posix()
    source_reference = {
        "path": relative_path,
        "symbol": "ClientQueryJob#execute",
        "line": 1,
    }
    envelope = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": SYSTEM_ID,
            "target_ids": [target_id],
            "summaries": [
                {
                    "node_id": node_id,
                    "summary": "读取查询仓储并返回本次任务结果。",
                    "test_points": _agent_test_points(),
                }
                for node_id in node_ids
            ],
            "questions": [],
            "source_refs": [source_reference],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "no_downstream",
                    "source_ref": source_reference,
                    "summary": "测试Job的入口已经明确展示唯一查询调用。",
                }
            ],
        }
    )
    submission = KnowledgeClientCandidateSubmission(candidate=envelope)

    with pytest.raises(KnowledgeValidationError, match="not read through the registered source tool"):
        application.submit_knowledge_client_candidate(handoff_id, submission)

    tool_result = application.call_knowledge_client_source_tool(
        handoff_id,
        "read_source",
        {"path": relative_path, "start_line": 1, "end_line": 1},
    )
    waiting = application.submit_knowledge_client_candidate(handoff_id, submission)

    assert "ClientQueryJob" in tool_result["content"]
    assert waiting.status == TaskStatus.WAITING_FOR_CONFIRMATION
    assert waiting.client_handoff is not None
    assert waiting.client_handoff.candidate_digest
    assert application.store.list_nodes(SYSTEM_ID) == []

    confirmation = KnowledgeClientCandidateConfirmation(
        candidate_digest=waiting.client_handoff.candidate_digest,
        decision="accept",
    )
    original_transition = application.tasks.transition_waiting_task
    completed_transition_failed = False

    def fail_post_publish_refresh(*_: object) -> None:
        """模拟正式发布后刷新上下文时出现项目领域异常。

        Raises:
            ScopeViolationError: 固定验证PUBLISHED提交点之后只能告警而不能反写失败。
        """

        raise ScopeViolationError("simulated post-publish scope failure")

    def flaky_transition(*args: object, **kwargs: object) -> object:
        """首次写COMPLETED时模拟任务文件故障，其他等待状态保持原逻辑。

        Args:
            args: 原任务状态转换的位置参数。
            kwargs: 原任务状态转换的命名参数。

        Returns:
            非首次COMPLETED调用的真实任务转换结果。

        Raises:
            OSError: 第一次尝试写客户端COMPLETED终态时固定抛出。
        """

        nonlocal completed_transition_failed
        status = args[1] if len(args) > 1 else kwargs.get("status")
        if status == TaskStatus.COMPLETED and not completed_transition_failed:
            completed_transition_failed = True
            raise OSError("simulated completed task write failure")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(application.knowledge, "_clear_refreshed_target", fail_post_publish_refresh)
    monkeypatch.setattr(application.tasks, "transition_waiting_task", flaky_transition)
    with pytest.raises(OSError, match="completed task write failure"):
        application.confirm_knowledge_client_candidate(handoff_id, confirmation)

    # 重复accept只补写同一任务COMPLETED，不能再次发布或永久停在waiting。
    completed = application.confirm_knowledge_client_candidate(handoff_id, confirmation)

    assert completed.status == TaskStatus.COMPLETED
    published_nodes = [node for node, _metadata, _content in application.store.list_nodes(SYSTEM_ID)]
    assert published_nodes
    assert {node.status for node in published_nodes} == {KnowledgeStatus.INFERRED}
    assert all(node.status != KnowledgeStatus.USER_CONFIRMED for node in published_nodes)


def test_codex_facade_complete_candidate_auto_publishes_with_isolated_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """完整Facade候选应自动发布，且调用契约只保存在结构化附属字段。

    Args:
        tmp_path: Pytest隔离的源码、Manifest、聊天任务和知识目录。
        monkeypatch: 在正式发布提交点暂停，以验证并发取消不会覆盖完成终态。

    Returns:
        None；同一任务完成、正文不含契约示例且能力索引可单独命中时通过。
    """

    application, _manifest, _target_id, _source_file, _app_server = _prepare_codex_client_handoff_system(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    facade_path = source_root / "QueryFacadeImpl.java"
    service_path = source_root / "OrderServiceImpl.java"
    dao_path = source_root / "OrderDAO.java"
    facade_path.write_text(
        "package demo;\nclass QueryFacadeImpl {\n  OrderServiceImpl service; Object queryList(Object request) { return service.query(request); }\n}\n",
        encoding="utf-8",
    )
    service_path.write_text(
        "package demo;\nclass OrderServiceImpl {\n  OrderDAO dao; Object query(Object request) { return dao.list(request); }\n}\n",
        encoding="utf-8",
    )
    dao_path.write_text(
        "package demo;\nclass OrderDAO {\n  Object list(Object request) { return null; }\n}\n",
        encoding="utf-8",
    )
    target_id = "facade:demo.QueryFacadeImpl#queryList"
    manifest = ScanManifest(
        scan_id="scan-client-facade-auto-publish",
        system_id=SYSTEM_ID,
        baseline=application.knowledge.git_repository.capture(source_root),
        entries=[
            EntryPoint(
                entry_id=target_id,
                system_id=SYSTEM_ID,
                kind="facade",
                display_name="查询退票单",
                source_id="demo.QueryFacadeImpl#queryList",
                source_path=str(facade_path),
                request_type="RefundQueryRequest",
                response_type="RefundPage",
                tool_id="refund-query-list",
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, manifest.baseline)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-facade-auto-0001",
        )
    )
    assert task.client_handoff is not None
    handoff_id = task.client_handoff.handoff_id
    workflow = application.store.read_draft_batch(SYSTEM_ID, task.client_handoff.batch_id)
    relative_paths = [path.relative_to(source_root).as_posix() for path in (facade_path, service_path, dao_path)]
    for relative_path in relative_paths:
        application.call_knowledge_client_source_tool(
            handoff_id,
            "read_source",
            {"path": relative_path, "start_line": 1, "end_line": 4},
        )
    references = [
        {"path": relative_paths[0], "symbol": "QueryFacadeImpl#queryList", "line": 3},
        {"path": relative_paths[1], "symbol": "OrderServiceImpl#query", "line": 3},
        {"path": relative_paths[2], "symbol": "OrderDAO#list", "line": 3},
    ]
    fixed_contract = application.get_knowledge_client_handoff(handoff_id)["deterministic_invocation_contract"]
    complete_text = "结合真实源码读取说明查询退票单的完整业务语义、限制条件和可验证结果。"
    contract = fixed_contract.model_copy(
        update={
            "field_meanings": {"refundType": "退票类型，支持区分自愿退。"},
            "date_dimensions": {"applyTime": "退票申请时间。"},
            "pagination_semantics": "分页从第一页开始，空列表表示没有匹配退票单。",
            "error_semantics": ["非法筛选条件返回业务参数异常。"],
            "usage_examples": ["查询七月申请的自愿退退票单列表。"],
        }
    )
    candidate = KnowledgeClientCandidateEnvelope(
        status="completed",
        system_id=SYSTEM_ID,
        target_ids=[target_id],
        summaries=[
            {
                "node_id": workflow.drafts[0].node.node_id,
                "summary": complete_text,
                "test_points": _agent_test_points(),
            }
        ],
        questions=[],
        source_refs=references,
        trace_steps=[
            {"sequence": 1, "role": "entry", "source_ref": references[0], "summary": complete_text},
            {"sequence": 2, "role": "service", "source_ref": references[1], "summary": complete_text},
            {"sequence": 3, "role": "data_access", "source_ref": references[2], "summary": complete_text},
        ],
        completeness=AgentKnowledgeCompleteness(
            business_purpose="用于按运营筛选条件查询退票单分页列表，不创建或修改任何退票业务状态。",
            applicable_scenarios="适用于运营后台按退票类型和时间范围检索订单，并核对列表与总数。",
            input_semantics="请求包含退票类型、时间范围和分页参数；空筛选按源码默认规则处理。",
            output_semantics="返回分页退票单及总数；没有匹配记录时返回空集合而不是伪造错误。",
            business_flow="入口转换请求后调用列表业务服务，再读取数据库中的退票订单数据。",
            important_branches="退票类型条件会改变查询过滤；分页边界和空条件分支影响最终数据库条件。",
            failure_handling="非法筛选参数产生业务参数异常，数据访问失败按现有异常边界向上返回。",
            test_oracles="验证列表元素满足全部过滤条件、总数一致、分页稳定，并覆盖空结果与非法参数。",
        ),
        invocation_contract=contract,
    )

    original_publish = application.knowledge.publish_client_candidate
    publication_started = threading.Event()
    allow_publication = threading.Event()
    submit_result: dict[str, TaskRecord] = {}
    cancel_errors: list[Exception] = []

    def paused_publish(*args: object, **kwargs: object) -> object:
        """在原子发布前制造可控窗口，让取消请求排队等待同一handoff锁。

        Args:
            args: 原发布方法的位置参数。
            kwargs: 原发布方法的命名参数。

        Returns:
            放行后原发布方法返回的已发布工作流。
        """

        publication_started.set()
        assert allow_publication.wait(timeout=2)
        return original_publish(*args, **kwargs)

    def submit_candidate() -> None:
        """在线程中提交完整候选并保存最终任务，模拟真实MCP回写。"""

        submit_result["task"] = application.submit_knowledge_client_candidate(
            handoff_id,
            KnowledgeClientCandidateSubmission(candidate=candidate),
        )

    def cancel_same_task() -> None:
        """在发布持锁期间提交旧页面取消，并记录预期的终态拒绝。"""

        try:
            application.cancel_task_agent(task.task_id)
        except Exception as exc:  # noqa: BLE001 - 测试需断言跨线程传播的领域异常
            cancel_errors.append(exc)

    monkeypatch.setattr(application.knowledge, "publish_client_candidate", paused_publish)
    submit_thread = threading.Thread(target=submit_candidate)
    submit_thread.start()
    assert publication_started.wait(timeout=2)
    cancel_thread = threading.Thread(target=cancel_same_task)
    cancel_thread.start()
    # 取消已在发布期间发起；放行后它必须锁内重读COMPLETED而不是反写旧WAITING快照。
    allow_publication.set()
    submit_thread.join(timeout=3)
    cancel_thread.join(timeout=3)
    assert not submit_thread.is_alive()
    assert not cancel_thread.is_alive()
    completed = submit_result["task"]

    assert completed.status == TaskStatus.COMPLETED
    assert len(cancel_errors) == 1
    assert isinstance(cancel_errors[0], KnowledgeValidationError)
    assert application.tasks.get(task.task_id).status == TaskStatus.COMPLETED
    node, _path, body = application.store.list_nodes(SYSTEM_ID)[0]
    assert node.invocation_contract is not None
    assert "查询七月申请的自愿退退票单列表" not in body
    assert "#### 输入、默认值与过滤分页语义" in body
    assert "#### 测试 Oracle" in body
    assert application.index.search("查询七月申请的自愿退退票单列表", SYSTEM_ID) == []
    assert application.index.search_invocation_contracts("查询七月申请的自愿退退票单列表", SYSTEM_ID)[0]["tool_id"] == "refund-query-list"


def test_codex_client_task_write_failure_is_frozen_without_creating_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务首次写入失败应补齐同一稳定ID的FAILED记录且不创建外部线程。

    Args:
        tmp_path: pytest隔离的源码、草稿和任务目录。
        monkeypatch: 首次阻断等待任务持久化以复现batch已写的半建状态。

    Returns:
        None；同attempt恢复同一失败任务，新attempt才创建唯一线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    original_create = application.tasks.create_waiting_task
    failed_once = False

    def fail_first_task_write(*args: object, **kwargs: object) -> TaskRecord:
        """首次模拟任务文件写入中断，随后允许按预分配ID补齐。

        Args:
            args: 原create_waiting_task位置参数。
            kwargs: 原create_waiting_task命名参数。

        Returns:
            故障后的真实同ID任务记录。

        Raises:
            OSError: 第一次调用固定模拟本地任务写入故障。
        """

        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise OSError("simulated waiting task write failure")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(application.tasks, "create_waiting_task", fail_first_task_write)
    request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-client-task-write-failed-0001",
    )

    failed = application.submit_knowledge_target_generation(request)
    repeated = application.submit_knowledge_target_generation(request)
    attempt_digest = hashlib.sha256(
        f"{SYSTEM_ID}|{target_id}|{manifest.scan_id}|{request.attempt_id}".encode("utf-8")
    ).hexdigest()

    assert failed.status == TaskStatus.FAILED
    assert failed.task_id == f"task-{attempt_digest[16:32]}"
    assert repeated.task_id == failed.task_id
    assert app_server.call_count == 0

    next_attempt = application.submit_knowledge_target_generation(
        request.model_copy(update={"attempt_id": "attempt-client-task-write-retry-0002"})
    )

    assert app_server.call_count == 1
    assert next_attempt.status == TaskStatus.WAITING_FOR_CLIENT
    assert next_attempt.task_id != failed.task_id


def test_codex_client_prepare_failure_before_batch_preserves_original_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """草稿落盘前的知识准备失败必须原样返回，不能被缺失batch错误覆盖。

    Args:
        tmp_path: pytest隔离的源码、草稿和任务目录。
        monkeypatch: 在现有prepare入口模拟确定性准备失败。

    Returns:
        None；调用方收到原异常且没有创建batch、任务或Codex线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)

    def fail_before_batch(*_: object, **__: object) -> object:
        """在任何草稿写入前模拟可直接定位的准备异常。

        Raises:
            KnowledgeValidationError: 固定原始错误供异常传播断言。
        """

        raise KnowledgeValidationError("simulated source trace preparation failure")

    monkeypatch.setattr(application.knowledge, "prepare_client_handoff", fail_before_batch)
    request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-client-prepare-failed-0001",
    )

    with pytest.raises(KnowledgeValidationError, match="simulated source trace preparation failure"):
        application.submit_knowledge_target_generation(request)

    attempt_digest = hashlib.sha256(
        f"{SYSTEM_ID}|{target_id}|{manifest.scan_id}|{request.attempt_id}".encode("utf-8")
    ).hexdigest()
    batch_id = f"knowledge-client-{attempt_digest[:16]}"
    with pytest.raises(KnowledgeNotFoundError, match=batch_id):
        application.store.read_draft_batch(SYSTEM_ID, batch_id)
    with pytest.raises(KnowledgeNotFoundError):
        application.tasks.get(f"task-{attempt_digest[16:32]}")
    assert app_server.call_count == 0


def test_codex_client_prepare_failure_after_batch_uses_existing_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """草稿落盘后的私有运行初始化失败应继续复用既有半成品恢复。

    Args:
        tmp_path: pytest隔离的源码、草稿和任务目录。
        monkeypatch: 在真实prepare写入batch后阻断私有运行初始化。

    Returns:
        None；同attempt固化为唯一FAILED任务且没有创建Codex线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)

    def fail_run_initialization(handoff: object, _prompt: str) -> None:
        """在batch已经写入后模拟私有运行目录初始化失败。

        Args:
            handoff: prepare已经写入batch的客户端接管身份。
            _prompt: 本测试不需要读取的完整客户端Prompt。

        Raises:
            OSError: 固定本地初始化故障供半成品恢复验证。
        """

        # 保留真实初始化已经创建运行目录后的故障形态，使既有恢复可以固化同一失败attempt。
        application.knowledge._client_run_root(handoff, create=True)
        raise OSError("simulated client run initialization failure")

    monkeypatch.setattr(application.knowledge, "_initialize_client_run", fail_run_initialization)
    request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-client-run-init-failed-0001",
    )

    failed = application.submit_knowledge_target_generation(request)
    repeated = application.submit_knowledge_target_generation(request)

    assert failed.status == TaskStatus.FAILED
    assert repeated.task_id == failed.task_id
    assert failed.client_handoff is not None
    assert application.store.read_draft_batch(SYSTEM_ID, failed.client_handoff.batch_id).drafts
    assert app_server.call_count == 0


def test_skill_knowledge_prepare_recovers_same_batch_when_task_write_initially_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skill草稿已落盘但任务写入失败时，重试应补齐同一task而不重建batch。

    Args:
        tmp_path: pytest隔离的源码、草稿和任务目录。
        monkeypatch: 只让第一次等待任务写入失败。

    Returns:
        None；重试复用同一batch和预分配task且未创建Codex线程时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    original_create_waiting_task = application.tasks.create_waiting_task
    create_calls = 0

    def fail_first_task_write(*args: object, **kwargs: object) -> TaskRecord:
        """第一次模拟本地任务文件写入失败，之后调用真实任务存储。

        Args:
            args: 原create_waiting_task位置参数。
            kwargs: 原create_waiting_task命名参数。

        Returns:
            第二次及以后真实持久化的等待任务。

        Raises:
            OSError: 第一次调用固定模拟任务存储故障。
        """

        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            # 故障发生在prepare已经原子写入batch之后，复现审查指出的幂等缺口。
            raise OSError("simulated skill task write failure")
        return original_create_waiting_task(*args, **kwargs)

    monkeypatch.setattr(application.tasks, "create_waiting_task", fail_first_task_write)

    with pytest.raises(OSError, match="simulated skill task write failure"):
        application.prepare_skill_knowledge_target(
            SYSTEM_ID,
            target_id,
            manifest.scan_id,
            "initial",
            "skill-request-task-recovery-0001",
        )

    batches_after_failure = application.store.list_draft_batches(SYSTEM_ID)
    assert len(batches_after_failure) == 1
    failed_handoff = batches_after_failure[0].client_handoff
    assert failed_handoff is not None

    recovered = application.prepare_skill_knowledge_target(
        SYSTEM_ID,
        target_id,
        manifest.scan_id,
        "initial",
        "skill-request-task-recovery-0001",
    )
    repeated = application.prepare_skill_knowledge_target(
        SYSTEM_ID,
        target_id,
        manifest.scan_id,
        "initial",
        "skill-request-task-recovery-0001",
    )

    assert recovered["task"].task_id == failed_handoff.task_id
    assert repeated["task"].task_id == recovered["task"].task_id
    assert recovered["handoff"].batch_id == batches_after_failure[0].batch_id
    assert len(application.store.list_draft_batches(SYSTEM_ID)) == 1
    assert create_calls == 2
    assert app_server.call_count == 0


def test_knowledge_generation_http_returns_safe_original_unknown_prepare_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """页面知识入口应返回未知准备异常的真实类型和原因，同时移除连接凭据。

    Args:
        tmp_path: pytest隔离的应用和源码目录。
        monkeypatch: 在应用提交边界模拟未归类本地异常。

    Returns:
        None；HTTP 400包含可定位原因且不含Token、地址或线程创建时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)

    def fail_unknown_prepare(_request: KnowledgeTargetGenerationRequest) -> TaskRecord:
        """模拟携带凭据与连接地址的未归类Prompt准备故障。

        Args:
            _request: 页面提交的单目标知识生成请求。

        Raises:
            OSError: 固定异常用于验证API安全转换。
        """

        raise OSError("prompt write failed token=local-secret at http://10.0.0.1:8080/internal")

    monkeypatch.setattr(application, "submit_knowledge_target_generation", fail_unknown_prepare)
    request = KnowledgeTargetGenerationRequest(
        system_id=SYSTEM_ID,
        target_id=target_id,
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
        interaction_mode="codex_client",
        intent="initial",
        attempt_id="attempt-http-unknown-prepare-0001",
    )

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/generations",
            json=request.model_dump(mode="json"),
        )

    assert response.status_code == 400
    error_message = response.json()["error"]["message"]
    assert "OSError" in error_message
    assert "prompt write failed" in error_message
    assert "local-secret" not in error_message
    assert "10.0.0.1" not in error_message
    assert app_server.call_count == 0


def test_codex_client_batch_bind_failure_replays_local_writes_without_second_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """线程创建后的批次写入瞬断只能重放本地状态，不能再次thread/start。

    Args:
        tmp_path: pytest隔离的源码、任务、批次和假App Server。
        monkeypatch: 在线程返回后的首次batch绑定模拟I/O故障。

    Returns:
        None；同任务恢复deep link且App Server仅调用一次时通过。
    """

    application, manifest, target_id, _source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    original_bind = application.knowledge.bind_client_handoff_thread
    bind_count = 0

    def fail_first_threaded_bind(system_id: str, batch_id: str, handoff: object) -> object:
        """仅在线程身份首次出现时模拟批次写入中断。

        Args:
            system_id: 当前客户端接管系统。
            batch_id: 当前稳定草稿批次。
            handoff: 可能尚未或已经携带thread ID的接管模型。

        Returns:
            其他阶段的真实批次绑定结果。

        Raises:
            OSError: 首次带thread ID绑定固定模拟写入故障。
        """

        nonlocal bind_count
        if getattr(handoff, "thread_id", ""):
            bind_count += 1
            if bind_count == 1:
                raise OSError("simulated threaded batch bind failure")
        return original_bind(system_id, batch_id, handoff)

    monkeypatch.setattr(application.knowledge, "bind_client_handoff_thread", fail_first_threaded_bind)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-thread-bind-failed-0001",
        )
    )

    assert task.status == TaskStatus.WAITING_FOR_CLIENT
    assert task.client_handoff is not None
    assert task.client_handoff.thread_id
    assert app_server.call_count == 1
    repeated = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-thread-bind-failed-0001",
        )
    )
    assert repeated.task_id == task.task_id
    assert app_server.call_count == 1


def test_codex_client_regenerate_keeps_old_knowledge_until_new_candidate_is_accepted(
    tmp_path: Path,
) -> None:
    """有效目标重新生成应创建新线程，但新候选确认前继续展示旧知识。

    Args:
        tmp_path: pytest隔离的两次客户端接管、知识真相和任务历史目录。

    Returns:
        None；第二attempt拥有新线程且旧节点正文未提前变化时通过。
    """

    application, manifest, target_id, source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    relative_path = source_file.relative_to(source_root).as_posix()

    def publish_attempt(attempt_id: str, summary: str) -> object:
        """完成一次测试客户端候选读取、提交和确认。

        Args:
            attempt_id: 本次明确用户操作的幂等键。
            summary: 将进入INFERRED自动区域的候选摘要。

        Returns:
            完成发布的同一任务记录。
        """

        task = application.submit_knowledge_target_generation(
            KnowledgeTargetGenerationRequest(
                system_id=SYSTEM_ID,
                target_id=target_id,
                scan_id=manifest.scan_id,
                agent="codex",
                confirmed=True,
                interaction_mode="codex_client",
                intent="initial" if app_server.call_count == 0 else "regenerate",
                attempt_id=attempt_id,
            )
        )
        assert task.client_handoff is not None
        batch = application.store.read_draft_batch(SYSTEM_ID, task.client_handoff.batch_id)
        source_reference = {"path": relative_path, "symbol": "ClientQueryJob#execute", "line": 1}
        application.call_knowledge_client_source_tool(
            task.client_handoff.handoff_id,
            "read_source",
            {"path": relative_path, "start_line": 1, "end_line": 1},
        )
        candidate = AgentKnowledgeEnvelope.model_validate(
            {
                "status": "completed",
                "system_id": SYSTEM_ID,
                "target_ids": [target_id],
                "summaries": [
                    {
                        "node_id": draft.node.node_id,
                        "summary": summary,
                        "test_points": _agent_test_points(),
                    }
                    for draft in batch.drafts
                ],
                "questions": [],
                "source_refs": [source_reference],
                "trace_steps": [
                    {
                        "sequence": 1,
                        "role": "no_downstream",
                        "source_ref": source_reference,
                        "summary": "测试Job路径已读取。",
                    }
                ],
            }
        )
        waiting = application.submit_knowledge_client_candidate(
            task.client_handoff.handoff_id,
            KnowledgeClientCandidateSubmission(candidate=candidate),
        )
        assert waiting.client_handoff is not None
        return application.confirm_knowledge_client_candidate(
            task.client_handoff.handoff_id,
            KnowledgeClientCandidateConfirmation(
                candidate_digest=waiting.client_handoff.candidate_digest,
                decision="accept",
            ),
        )

    first = publish_attempt("attempt-client-regenerate-0001", "第一版稳定查询知识。")
    original_content = application.store.list_nodes(SYSTEM_ID)[0][2]
    second = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="regenerate",
            attempt_id="attempt-client-regenerate-0002",
        )
    )

    assert first.client_handoff is not None
    assert second.client_handoff is not None
    assert second.status == TaskStatus.WAITING_FOR_CLIENT
    assert second.client_handoff.thread_id != first.client_handoff.thread_id
    assert app_server.call_count == 2
    assert application.store.list_nodes(SYSTEM_ID)[0][2] == original_content


def test_codex_client_publish_failure_preserves_candidate_and_records_exact_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认后的发布失败必须保留候选并持久化失败，不得自动再次调用Codex。

    Args:
        tmp_path: pytest隔离的源码、候选、任务和草稿目录。
        monkeypatch: 在候选通过审计后模拟发布阶段的精确基线错误。

    Returns:
        None；API抛出原错误且同一任务、候选摘要和草稿仍可恢复时通过。
    """

    application, manifest, target_id, source_file, app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-publish-failure-0001",
        )
    )
    assert task.client_handoff is not None
    handoff = task.client_handoff
    batch = application.store.read_draft_batch(SYSTEM_ID, handoff.batch_id)
    relative_path = source_file.relative_to(Path(application.store.get_system(SYSTEM_ID).source_path)).as_posix()
    source_reference = {"path": relative_path, "symbol": "ClientQueryJob#execute", "line": 1}
    application.call_knowledge_client_source_tool(
        handoff.handoff_id,
        "read_source",
        {"path": relative_path, "start_line": 1, "end_line": 1},
    )
    candidate = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": SYSTEM_ID,
            "target_ids": [target_id],
            "summaries": [
                {
                    "node_id": draft.node.node_id,
                    "summary": "已核对客户端查询任务。",
                    "test_points": _agent_test_points(),
                }
                for draft in batch.drafts
            ],
            "questions": [],
            "source_refs": [source_reference],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "no_downstream",
                    "source_ref": source_reference,
                    "summary": "测试Job入口唯一调用已读取。",
                }
            ],
        }
    )
    waiting = application.submit_knowledge_client_candidate(
        handoff.handoff_id,
        KnowledgeClientCandidateSubmission(candidate=candidate),
    )
    assert waiting.client_handoff is not None
    candidate_digest = waiting.client_handoff.candidate_digest

    def fail_publish(*_: object, **__: object) -> object:
        """模拟确认时源码基线变化并阻止任何知识发布。

        Raises:
            KnowledgeValidationError: 固定精确错误供任务恢复断言。
        """

        raise KnowledgeValidationError("source baseline changed before client publish")

    monkeypatch.setattr(application.knowledge, "publish_client_candidate", fail_publish)
    with pytest.raises(KnowledgeValidationError, match="source baseline changed before client publish"):
        application.confirm_knowledge_client_candidate(
            handoff.handoff_id,
            KnowledgeClientCandidateConfirmation(
                candidate_digest=candidate_digest,
                decision="accept",
            ),
        )

    failed = application.get_task(task.task_id)
    preserved = application.store.read_draft_batch(SYSTEM_ID, handoff.batch_id)
    assert failed.status == TaskStatus.FAILED
    assert failed.error == "source baseline changed before client publish"
    assert failed.client_handoff is not None
    assert failed.client_handoff.candidate_digest == candidate_digest
    assert preserved.drafts
    assert preserved.client_handoff is not None
    assert preserved.client_handoff.status.value == "failed"
    assert app_server.call_count == 1
    assert application.store.list_nodes(SYSTEM_ID) == []


def test_codex_client_publish_rolls_back_nodes_when_index_rebuild_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发布中后段失败必须回滚已写节点，不能留下failed任务配部分新知识。

    Args:
        tmp_path: pytest隔离的源码、候选、Git知识与索引目录。
        monkeypatch: 在节点和关系写入后模拟SQLite索引重建失败。

    Returns:
        None；确认失败后正式节点仍为空且候选草稿保持可恢复时通过。
    """

    application, manifest, target_id, source_file, _app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-index-rollback-0001",
        )
    )
    assert task.client_handoff is not None
    handoff = task.client_handoff
    batch = application.store.read_draft_batch(SYSTEM_ID, handoff.batch_id)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    relative_path = source_file.relative_to(source_root).as_posix()
    source_reference = {"path": relative_path, "symbol": "ClientQueryJob#execute", "line": 1}
    application.call_knowledge_client_source_tool(
        handoff.handoff_id,
        "read_source",
        {"path": relative_path, "start_line": 1, "end_line": 1},
    )
    candidate = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": SYSTEM_ID,
            "target_ids": [target_id],
            "summaries": [
                {
                    "node_id": draft.node.node_id,
                    "summary": "已核对客户端查询任务。",
                    "test_points": _agent_test_points(),
                }
                for draft in batch.drafts
            ],
            "questions": [],
            "source_refs": [source_reference],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "no_downstream",
                    "source_ref": source_reference,
                    "summary": "测试Job入口唯一调用已读取。",
                }
            ],
        }
    )
    waiting = application.submit_knowledge_client_candidate(
        handoff.handoff_id,
        KnowledgeClientCandidateSubmission(candidate=candidate),
    )
    assert waiting.client_handoff is not None

    def fail_index_rebuild(_: object) -> dict[str, int]:
        """在正式节点写入之后模拟派生索引失败。"""

        raise KnowledgeValidationError("simulated index rebuild failure")

    monkeypatch.setattr(application.index, "rebuild", fail_index_rebuild)
    with pytest.raises(KnowledgeValidationError, match="simulated index rebuild failure"):
        application.confirm_knowledge_client_candidate(
            handoff.handoff_id,
            KnowledgeClientCandidateConfirmation(
                candidate_digest=waiting.client_handoff.candidate_digest,
                decision="accept",
            ),
        )

    preserved = application.store.read_draft_batch(SYSTEM_ID, handoff.batch_id)
    assert application.store.list_nodes(SYSTEM_ID) == []
    assert preserved.drafts
    assert preserved.client_handoff is not None
    assert preserved.client_handoff.status.value == "failed"


def test_codex_client_reject_and_accept_are_serialized_across_application_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """跨进程等价应用实例不能让拒绝与接受同时基于旧候选发布。

    Args:
        tmp_path: pytest隔离但由两个应用实例共享的知识、任务与源码目录。
        monkeypatch: 暂停拒绝写入以稳定复现跨实例check-then-act竞态。

    Returns:
        None；拒绝持锁期间接受等待，随后接受失败且没有正式节点时通过。
    """

    rejecting_application, manifest, target_id, source_file, _app_server = _prepare_codex_client_handoff_system(tmp_path)
    task = rejecting_application.submit_knowledge_target_generation(
        KnowledgeTargetGenerationRequest(
            system_id=SYSTEM_ID,
            target_id=target_id,
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
            interaction_mode="codex_client",
            intent="initial",
            attempt_id="attempt-client-confirm-race-0001",
        )
    )
    assert task.client_handoff is not None
    handoff = task.client_handoff
    batch = rejecting_application.store.read_draft_batch(SYSTEM_ID, handoff.batch_id)
    source_root = Path(rejecting_application.store.get_system(SYSTEM_ID).source_path)
    relative_path = source_file.relative_to(source_root).as_posix()
    source_reference = {"path": relative_path, "symbol": "ClientQueryJob#execute", "line": 1}
    rejecting_application.call_knowledge_client_source_tool(
        handoff.handoff_id,
        "read_source",
        {"path": relative_path, "start_line": 1, "end_line": 1},
    )
    candidate = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": SYSTEM_ID,
            "target_ids": [target_id],
            "summaries": [
                {
                    "node_id": draft.node.node_id,
                    "summary": "并发确认候选。",
                    "test_points": _agent_test_points(),
                }
                for draft in batch.drafts
            ],
            "questions": [],
            "source_refs": [source_reference],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "no_downstream",
                    "source_ref": source_reference,
                    "summary": "测试Job入口已读取。",
                }
            ],
        }
    )
    waiting = rejecting_application.submit_knowledge_client_candidate(
        handoff.handoff_id,
        KnowledgeClientCandidateSubmission(candidate=candidate),
    )
    assert waiting.client_handoff is not None
    candidate_digest = waiting.client_handoff.candidate_digest
    accepting_application = OpenTestApplication(rejecting_application.knowledge_root)
    original_reject = rejecting_application.knowledge.reject_client_candidate
    reject_entered = threading.Event()
    release_reject = threading.Event()
    accept_finished = threading.Event()
    errors: dict[str, BaseException] = {}

    def paused_reject(workflow: KnowledgeGenerationWorkflowBatch, digest: str) -> KnowledgeGenerationWorkflowBatch:
        """在拒绝读取候选后暂停，扩大另一个实例并发接受的窗口。"""

        reject_entered.set()
        if not release_reject.wait(timeout=3):
            raise AssertionError("reject pause was not released")
        return original_reject(workflow, digest)

    def reject_candidate() -> None:
        """在第一应用实例执行明确拒绝并记录异常。"""

        try:
            rejecting_application.confirm_knowledge_client_candidate(
                handoff.handoff_id,
                KnowledgeClientCandidateConfirmation(candidate_digest=candidate_digest, decision="reject"),
            )
        except BaseException as exc:  # noqa: BLE001 - 测试线程必须把所有失败传回主断言
            errors["reject"] = exc

    def accept_candidate() -> None:
        """在第二应用实例并发接受，并把终态或异常传回主断言。"""

        try:
            accepting_application.confirm_knowledge_client_candidate(
                handoff.handoff_id,
                KnowledgeClientCandidateConfirmation(candidate_digest=candidate_digest, decision="accept"),
            )
        except BaseException as exc:  # noqa: BLE001 - 测试线程必须把所有失败传回主断言
            errors["accept"] = exc
        finally:
            accept_finished.set()

    monkeypatch.setattr(rejecting_application.knowledge, "reject_client_candidate", paused_reject)
    reject_thread = threading.Thread(target=reject_candidate)
    accept_thread = threading.Thread(target=accept_candidate)
    reject_thread.start()
    assert reject_entered.wait(timeout=2)
    accept_thread.start()
    try:
        # 跨进程系统事务应让接受等待拒绝决策落盘，不能先写入任何正式节点。
        assert not accept_finished.wait(timeout=0.2)
        assert accepting_application.store.list_nodes(SYSTEM_ID) == []
    finally:
        release_reject.set()
        reject_thread.join(timeout=3)
        accept_thread.join(timeout=3)
        rejecting_application.close()
        accepting_application.close()

    assert "reject" not in errors
    assert isinstance(errors.get("accept"), KnowledgeValidationError)
    settled = rejecting_application.store.read_draft_batch(SYSTEM_ID, handoff.batch_id)
    assert settled.client_handoff is not None
    assert settled.client_handoff.status.value == "rejected"
    assert rejecting_application.store.list_nodes(SYSTEM_ID) == []


def test_agent_failure_finishes_partial_and_preserves_code_facts(tmp_path: Path) -> None:
    """Agent失败但确定性追踪成功时，任务必须部分完成并准确累计失败目标。

    Args:
        tmp_path: pytest隔离的源码、Manifest、任务和知识目录。

    Returns:
        None；代码事实保留且任务、进度、计数都呈现partial时通过。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    job_path = source_root / "PartialJob.java"
    job_path.write_text(
        "package demo; class PartialJob { void execute() { repository.query(); } }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    entry_id = "job:demo.PartialJob"
    manifest = ScanManifest(
        scan_id="scan-agent-partial-failure",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="部分完成任务",
                source_id="demo.PartialJob",
                source_path=str(job_path),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    runner = _FailingKnowledgeAgentRunner()
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="codex"))
    application.agent_runner = runner
    application.knowledge.runner = runner

    task = application.submit_knowledge_generation_batch(
        KnowledgeGenerationBatchRequest(
            system_id=SYSTEM_ID,
            target_ids=[entry_id],
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
        )
    )
    current = application.tasks.get(task.task_id)
    for _ in range(200):
        if current.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            break
        time.sleep(0.01)
        current = application.tasks.get(task.task_id)

    assert current.status == TaskStatus.PARTIAL
    assert current.progress is not None
    assert current.progress.status == TaskStatus.PARTIAL
    assert current.result["code_only_count"] == 1
    assert current.result["agent_failed_count"] == 1
    assert current.result["deterministic_failed_count"] == 0
    assert current.result["failed_count"] == 1
    nodes = [node for node, _, _ in application.store.list_nodes(SYSTEM_ID)]
    assert nodes
    assert {node.status for node in nodes} == {KnowledgeStatus.CODE_VERIFIED}


def test_deterministic_trace_failure_finishes_failed_without_publishing_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确定性追踪失败没有可信事实时，任务必须failed并保留独立失败计数。

    Args:
        tmp_path: pytest隔离的源码、Manifest、任务和知识目录。
        monkeypatch: 把确定性追踪器替换为固定本地失败，不调用真实Agent。

    Returns:
        None；任务为failed、确定性失败1且知识目录为空时通过。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    job_path = source_root / "BrokenTraceJob.java"
    job_path.write_text("package demo; class BrokenTraceJob { void execute() {} }", encoding="utf-8")
    baseline = application.knowledge.git_repository.capture(source_root)
    entry_id = "job:demo.BrokenTraceJob"
    manifest = ScanManifest(
        scan_id="scan-deterministic-failure",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="追踪失败任务",
                source_id="demo.BrokenTraceJob",
                source_path=str(job_path),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    runner = _KnowledgeAgentRunner()
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="codex"))
    application.agent_runner = runner
    application.knowledge.runner = runner

    def fail_trace(_: object, __: str) -> object:
        """固定模拟确定性源码证据无法定位。

        Raises:
            KnowledgeValidationError: 每次调用都表示没有可信最小事实。
        """

        raise KnowledgeValidationError("simulated deterministic trace failure")

    monkeypatch.setattr(application.knowledge.tracer, "trace", fail_trace)
    task = application.submit_knowledge_generation_batch(
        KnowledgeGenerationBatchRequest(
            system_id=SYSTEM_ID,
            target_ids=[entry_id],
            scan_id=manifest.scan_id,
            agent="codex",
            confirmed=True,
        )
    )
    current = application.tasks.get(task.task_id)
    for _ in range(200):
        if current.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            break
        time.sleep(0.01)
        current = application.tasks.get(task.task_id)

    assert current.status == TaskStatus.FAILED
    assert current.result["agent_failed_count"] == 0
    assert current.result["deterministic_failed_count"] == 1
    assert current.result["failed_count"] == 1
    assert application.store.list_nodes(SYSTEM_ID) == []


def test_recovered_invalid_agent_envelope_finishes_partial_and_publishes_code_facts(
    tmp_path: Path,
) -> None:
    """重启接管到非法Agent信封时应与首次运行一样保留代码事实并partial。

    Args:
        tmp_path: pytest隔离的源码、工作流检查点、证据和任务目录。

    Returns:
        None；接管不创建第二次调用，任务计数准确且代码事实已发布时通过。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    job_path = source_root / "RecoveredInvalidJob.java"
    job_path.write_text(
        "package demo; class RecoveredInvalidJob { void execute() { repository.query(); } }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    entry_id = "job:demo.RecoveredInvalidJob"
    manifest = ScanManifest(
        scan_id="scan-recovered-invalid-envelope",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="接管非法输出任务",
                source_id="demo.RecoveredInvalidJob",
                source_path=str(job_path),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    runner = _DetachedInvalidRecoveryRunner()
    application.knowledge.runner = runner
    request = KnowledgeGenerationBatchRequest(
        system_id=SYSTEM_ID,
        target_ids=[entry_id],
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
    )

    # 首次运行只保存确定性检查点；恢复阶段消费同一run_id的非法终态证据。
    with pytest.raises(AgentObserverDetachedError):
        application.knowledge.generate_drafts(request)
    workflow = application.store.list_draft_batches(SYSTEM_ID)[0]
    original_run_id = workflow.active_run_id

    def recovery_job() -> dict[str, object]:
        """消费原运行证据并把降级结果转换为任务partial语义。

        Returns:
            已发布代码事实与失败分类计数。

        Raises:
            TaskPartialFailureError: 由应用统一边界把Agent校验失败标为partial。
        """

        settled = application.knowledge.recover_generation(SYSTEM_ID, workflow.batch_id, runner)
        result = application._knowledge_generation_result(settled, 0)
        application._raise_for_partial_generation(result)
        return result

    task = application.tasks.submit("knowledge-target-generation", SYSTEM_ID, recovery_job)
    current = application.tasks.get(task.task_id)
    for _ in range(200):
        if current.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            break
        time.sleep(0.01)
        current = application.tasks.get(task.task_id)

    assert original_run_id
    assert current.status == TaskStatus.PARTIAL
    assert current.result["code_only_count"] == 1
    assert current.result["agent_failed_count"] == 1
    assert current.result["deterministic_failed_count"] == 0
    assert current.result["failed_count"] == 1
    nodes = [node for node, _, _ in application.store.list_nodes(SYSTEM_ID)]
    assert nodes
    assert {node.status for node in nodes} == {KnowledgeStatus.CODE_VERIFIED}


def test_legacy_completed_code_only_task_is_projected_as_partial(tmp_path: Path) -> None:
    """旧completed记录只要outcome含安全错误，读取时就必须无损投影为partial。

    Args:
        tmp_path: pytest隔离的任务历史目录。

    Returns:
        None；原任务文件不改写且API读取结果具有正确部分失败计数时通过。
    """

    application = _application(tmp_path)

    def legacy_job() -> dict[str, object]:
        """返回历史版本曾误记为completed的CODE_ONLY结果。

        Returns:
            含一项Agent安全错误、但旧失败计数为零的兼容任务结果。
        """

        return {
            "target_count": 1,
            "code_only_count": 1,
            "failed_count": 0,
            "outcomes": [
                {
                    "target_id": "facade:demo.Query#list",
                    "status": "CODE_ONLY",
                    "safe_error": "ExecutionFailure: 指定Agent分析失败",
                }
            ],
        }

    task = application.tasks.submit("knowledge-target-generation", SYSTEM_ID, legacy_job)
    raw_task_path = application.tasks.task_root / f"{task.task_id}.json"
    current = application.tasks.get(task.task_id)
    for _ in range(200):
        if current.status in {TaskStatus.COMPLETED, TaskStatus.PARTIAL}:
            break
        time.sleep(0.01)
        current = application.tasks.get(task.task_id)
    raw_payload = json.loads(raw_task_path.read_text(encoding="utf-8"))

    assert raw_payload["status"] == "completed"
    assert raw_payload["result"]["failed_count"] == 0
    assert current.status == TaskStatus.PARTIAL
    assert current.result["agent_failed_count"] == 1
    assert current.result["deterministic_failed_count"] == 0
    assert current.result["failed_count"] == 1


def test_refresh_snapshot_restores_running_task_and_duplicate_submit_is_rejected(tmp_path: Path) -> None:
    """刷新读取必须恢复同一任务身份，运行中重复提交不得创建第二次Agent调用。

    Args:
        tmp_path: pytest隔离的源码、Manifest、任务和工作流快照目录。

    Returns:
        None；两次快照身份一致、重复请求被拒绝且Runner只调用一次时通过。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    job_path = source_root / "SlowQueryJob.java"
    job_path.write_text(
        "package demo; class SlowQueryJob { void execute() { repository.query(); } }",
        encoding="utf-8",
    )
    baseline = application.knowledge.git_repository.capture(source_root)
    entry_id = "job:demo.SlowQueryJob"
    manifest = ScanManifest(
        scan_id="scan-refresh-running-agent",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="慢速查询任务",
                source_id="demo.SlowQueryJob",
                source_path=str(job_path),
            )
        ],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    application.skip_background_interview(SYSTEM_ID)
    runner = _BlockingKnowledgeAgentRunner()
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="codex"))
    application.agent_runner = runner
    application.knowledge.runner = runner
    request = KnowledgeGenerationBatchRequest(
        system_id=SYSTEM_ID,
        target_ids=[entry_id],
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
    )
    client = TestClient(create_app(application))

    task = application.submit_knowledge_generation_batch(request)
    assert task.progress is not None
    assert task.progress.current_item == entry_id
    assert task.progress.agent == "codex"
    try:
        assert runner.started.wait(timeout=1)
        first_snapshot = application.get_knowledge_workflow(SYSTEM_ID)
        refreshed_snapshot = application.get_knowledge_workflow(SYSTEM_ID)

        assert first_snapshot.active_generation_task_id == task.task_id
        assert refreshed_snapshot.active_generation_task_id == task.task_id
        assert refreshed_snapshot.active_generation_target_id == entry_id
        assert refreshed_snapshot.active_generation_agent == "codex"
        assert refreshed_snapshot.active_generation_status == "running"
        assert refreshed_snapshot.generation_blocked_reason == "running"
        with pytest.raises(ScopeViolationError, match="原知识任务仍在运行"):
            application.submit_knowledge_generation_batch(request)
        # 第二标签页对应的HTTP重放必须稳定返回409，且不能进入Runner形成第二次费用调用。
        duplicate = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/generation-batches",
            json=request.model_dump(mode="json"),
        )
        assert duplicate.status_code == 409
        assert "原知识任务仍在运行" in duplicate.json()["error"]["message"]
        assert runner.call_count == 1
    finally:
        # 无论断言结果如何都放行测试Runner，避免后台任务悬挂到其他测试。
        runner.release.set()
        client.close()
    _wait_for_task(application, task.task_id)
    with pytest.raises(ScopeViolationError, match="知识已有效"):
        application.submit_knowledge_generation_batch(request)
    assert runner.call_count == 1


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
    # 产品入口会阻止有效目标重复付费；此处直接调用领域服务，仅验证内部重算仍保护人工内容。
    repeated_batch = application.knowledge.generate_drafts(request, runner=_KnowledgeAgentRunner())
    assert application.get_knowledge_question_cycle(SYSTEM_ID, refresh=True).questions == []
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
    supplemented_node, _, _ = application.store.get_node(SYSTEM_ID, protected_node.node_id)
    # 新人工答案只确认对应段落；刷新后的Agent解释仍使节点整体保持INFERRED。
    assert supplemented_node.status == KnowledgeStatus.INFERRED
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
    # 混合节点保留独立人工段，但新Agent摘要不能借历史答案把整个节点升级为USER_CONFIRMED。
    assert refreshed_node.status == KnowledgeStatus.INFERRED
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
    waiting_snapshot = application.get_knowledge_workflow(SYSTEM_ID)
    assert waiting_snapshot.active_generation_target_id == target_id
    assert waiting_snapshot.active_generation_agent == "codex"
    assert waiting_snapshot.active_generation_status == "waiting_for_input"
    assert waiting_snapshot.generation_blocked_reason == "waiting_for_input"
    application.runtime_settings.write(RuntimeToolSettings(knowledge_agent="codex"))
    application.agent_runner = runner
    application.knowledge.runner = runner
    with pytest.raises(ScopeViolationError, match="正在等待回答"):
        application.submit_knowledge_generation_batch(
            KnowledgeGenerationBatchRequest(
                system_id=SYSTEM_ID,
                target_ids=[target_id],
                scan_id=manifest.scan_id,
                agent="codex",
                confirmed=True,
            )
        )
    assert len(runner.requests) == 1

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
    # 人工答案进入独立确认段，但同一节点含有新Agent解释，整体来源不能伪装为USER_CONFIRMED。
    assert node.status.value == "inferred"
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


def test_knowledge_target_detail_uses_explicit_historical_scan(tmp_path: Path) -> None:
    """历史目录目标详情必须读取同一Manifest，不能静默回落到latest。

    Args:
        tmp_path: pytest隔离的两个扫描Manifest和源码目录。

    Returns:
        None；旧扫描仍能读取其目标，而默认latest明确找不到该目标时通过。
    """

    application = _application(tmp_path)
    source_root = Path(application.store.get_system(SYSTEM_ID).source_path)
    source_file = source_root / "HistoricalQueryJob.java"
    source_file.write_text("package demo; class HistoricalQueryJob { void execute() {} }\n", encoding="utf-8")
    baseline = application.knowledge.git_repository.capture(source_root)
    target_id = "job:demo.HistoricalQueryJob"
    old_manifest = ScanManifest(
        scan_id="scan-historical-detail-old",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=target_id,
                system_id=SYSTEM_ID,
                kind="job",
                display_name="历史查询任务",
                source_id="demo.HistoricalQueryJob",
                source_path=str(source_file),
            )
        ],
    )
    latest_manifest = ScanManifest(
        scan_id="scan-historical-detail-latest",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(old_manifest)
    artifacts.write_manifest(latest_manifest)
    artifacts.publish_latest(SYSTEM_ID, latest_manifest.scan_id)

    historical = application.get_knowledge_target_detail(
        SYSTEM_ID,
        target_id,
        scan_id=old_manifest.scan_id,
    )

    assert historical.target.target_id == target_id
    with pytest.raises(KnowledgeNotFoundError, match="target"):
        application.get_knowledge_target_detail(SYSTEM_ID, target_id)


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


def test_state_background_scope_maps_machine_and_transitions_without_duplicate_semantic_target(tmp_path: Path) -> None:
    """关键状态背景范围覆盖状态机和流转，但单所有者模式不再复制成公共逻辑。

    Args:
        tmp_path: pytest隔离的源码、Manifest和上下文目录。

    Side Effects:
        只发布本地扫描Manifest，不生成知识或访问QA。

    Returns:
        None；通过断言验证背景问题范围和公共逻辑去重结果。
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
    assert set(affected_target_ids) == {
        "state-machine:OrderState",
        transition.transition_id,
    }
    assert application.list_unified_knowledge_questions(SYSTEM_ID) == []
