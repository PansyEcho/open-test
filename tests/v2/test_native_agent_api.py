"""验证原生Agent prepare、任务恢复和冲突响应的V2 HTTP契约。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.case_template_v4 import CaseTemplateWriteConflictError
from opentest.application.foundation import OpenTestApplication
from opentest.domain.case_template_v4 import (
    CaseTemplateContinuationRequest,
    CaseTemplateGenerationStartRequest,
    CaseTemplateHandoffV4,
    CaseTemplateSourceScope,
)
from opentest.domain.errors import IdempotencyConflictError, KnowledgeNotFoundError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeClientHandoff,
    KnowledgeConfirmation,
    KnowledgeDraft,
    KnowledgeGenerationWorkflowBatch,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeQuestion,
    KnowledgeTarget,
    OperationInputKnowledgeContract,
    RuntimeToolSettings,
    ScanCatalog,
    ScanManifest,
    SourceBaseline,
    TaskRecord,
    TaskStatus,
    utc_now,
)


SYSTEM_ID = "sample.java.system"
TARGET_ID = "facade:sample.RefundFacade#cancel"


def test_knowledge_generation_accepts_prepare_only_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """网页知识入口只需目标、扫描、意图和幂等身份即可准备当前Agent任务。

    Args:
        tmp_path: Pytest提供的隔离知识根。
        monkeypatch: 替换实际知识准备，避免要求真实扫描资产。

    Returns:
        None；严格请求不返回422且参数原样进入prepare-only应用服务时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    received: list[tuple[str, str, str, str, str]] = []
    availability_calls = 0

    def record_agent_availability() -> tuple[bool, bool]:
        """记录prepare是否错误探测本机Agent可用性。

        Returns:
            Codex和Claude都不可用的固定离线结果。

        Side Effects:
            只增加测试内计数，用于证明原生prepare没有探测可执行文件。
        """

        nonlocal availability_calls
        availability_calls += 1
        return False, False

    def prepare(
        system_id: str,
        target_id: str,
        scan_id: str,
        intent: str,
        request_id: str,
    ) -> dict[str, object]:
        """记录网页prepare参数并返回不含thread的最小持久任务响应。

        Args:
            system_id: 路由与请求共同声明的系统。
            target_id: 页面选择的知识目标。
            scan_id: 页面选择的扫描基线。
            intent: 初次生成或显式重生成。
            request_id: 页面跨网络重试复用的身份。

        Returns:
            可由页面继续展示的最小任务和handoff身份。

        Side Effects:
            只向测试内存追加参数，不写知识或启动Agent。
        """

        received.append((system_id, target_id, scan_id, intent, request_id))
        return {
            "task_id": "task-1111111111111111",
            "handoff_id": "knowledge-client-handoff-test",
            "continuation_instruction": "继续 task-1111111111111111",
        }

    monkeypatch.setattr(application, "prepare_native_knowledge_generation", prepare)
    monkeypatch.setattr(application.agent_runner, "availability", record_agent_availability)
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/knowledge/generations",
            json={
                "system_id": SYSTEM_ID,
                "target_id": TARGET_ID,
                "scan_id": "scan-current",
                "intent": "regenerate",
                "request_id": "knowledge-request-0001",
            },
        )

    assert response.status_code == 202
    assert received == [
        (SYSTEM_ID, TARGET_ID, "scan-current", "regenerate", "knowledge-request-0001")
    ]
    assert availability_calls == 0
    assert not hasattr(application, "codex_app_server")
    assert not hasattr(application, "codex_desktop")
    assert response.json()["task_id"] == "task-1111111111111111"
    assert "thread_id" not in response.json()


def test_knowledge_handoff_and_task_context_freeze_analysis_instructions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """知识handoff和任务恢复始终读取prepare时冻结的业务分析指令。

    Args:
        tmp_path: Pytest提供的私有指令、任务和扫描夹具目录。
        monkeypatch: 固定handoff关联的批次、目录和扫描，不启动真实扫描器。

    Returns:
        None；修改全局Prompt后两个读取入口仍返回原任务指令时通过。

    Side Effects:
        只在临时目录写入原生Agent指令和运行设置，不调用Agent或QA。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    frozen_instructions = "冻结知识规则：只处理当前目标，不启动后台Agent。"
    handoff = KnowledgeClientHandoff(
        handoff_id="handoff-" + "1" * 24,
        task_id="task-1111111111111111",
        attempt_id="native-instructions-0001",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        scan_id="scan-native-instructions",
        batch_id="knowledge-client-native-instructions",
        agent_run_id="agent-" + "1" * 16,
    )
    assert handoff.codex_model == ""
    assert handoff.reasoning_effort == ""
    # 指令正文进入任务私有检查点；后续读取不得重新渲染当前Runtime模板。
    application.knowledge._initialize_client_run(handoff, frozen_instructions)
    node = KnowledgeNode(
        node_id="common:refund-cancel",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.COMMON_LOGIC,
        title="Refund cancel",
    )
    workflow = KnowledgeGenerationWorkflowBatch(
        batch_id=handoff.batch_id,
        system_id=SYSTEM_ID,
        scan_id=handoff.scan_id,
        target_ids=[TARGET_ID],
        status="GENERATING",
        drafts=[
            KnowledgeDraft(
                draft_id="draft-native-instructions",
                system_id=SYSTEM_ID,
                target_id=TARGET_ID,
                node=node,
                content="deterministic draft",
            )
        ],
        client_handoff=handoff,
    )
    task = TaskRecord(
        task_id=handoff.task_id,
        operation="knowledge-codex-client-handoff",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        client_handoff=handoff,
        status=TaskStatus.WAITING_FOR_CLIENT,
        trace_id="trace-knowledge-instructions",
        ended_at=utc_now(),
    )
    catalog = ScanCatalog(
        scan_id=handoff.scan_id,
        system_id=SYSTEM_ID,
        generated_at=utc_now(),
        targets=[
            KnowledgeTarget(
                target_id=TARGET_ID,
                category="common_logic",
                display_name="Refund cancel",
            )
        ],
    )
    manifest = ScanManifest(
        scan_id=handoff.scan_id,
        system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path=str(tmp_path / "source")),
        entries=[
            EntryPoint(
                entry_id=TARGET_ID,
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.COMMON_LOGIC,
                display_name="Refund cancel",
                source_id="sample.RefundFacade#cancel",
                source_path="RefundFacade.java",
            )
        ],
    )
    monkeypatch.setattr(application, "_find_knowledge_client_handoff", lambda _handoff_id: workflow)
    monkeypatch.setattr(application.tasks, "get", lambda _task_id: task)
    monkeypatch.setattr(application.store, "read_draft_batch", lambda _system_id, _batch_id: workflow)
    monkeypatch.setattr(application.scan_catalogs, "build_catalog", lambda _system_id, _scan_id: catalog)
    monkeypatch.setattr(application.knowledge.artifacts, "read", lambda _system_id, _scan_id: manifest)
    monkeypatch.setattr(application.knowledge, "_system_context_payload", lambda _system_id: {})

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        initial_handoff = client.get(
            f"/api/v2/knowledge/client-handoffs/{handoff.handoff_id}"
        )
        initial_context = client.get(f"/api/v2/tasks/{task.task_id}/context")
        application.runtime_settings.write(
            RuntimeToolSettings(
                knowledge_agent_prompt_template="新全局规则 {{target_id}}"
            )
        )
        repeated_handoff = client.get(
            f"/api/v2/knowledge/client-handoffs/{handoff.handoff_id}"
        )
        repeated_context = client.get(f"/api/v2/tasks/{task.task_id}/context")

    for response in (
        initial_handoff,
        initial_context,
        repeated_handoff,
        repeated_context,
    ):
        assert response.status_code == 200
    assert initial_handoff.json()["analysis_instructions"] == frozen_instructions
    assert repeated_handoff.json()["analysis_instructions"] == frozen_instructions
    assert initial_context.json()["context"]["analysis_instructions"] == frozen_instructions
    assert repeated_context.json()["context"]["analysis_instructions"] == frozen_instructions


def test_task_context_keeps_task_and_authoritative_context_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务上下文响应保持页面约定的顶层task和嵌套context形状。

    Args:
        tmp_path: Pytest提供的隔离知识根。
        monkeypatch: 替换任务存储读取，构造无thread的Case恢复场景。

    Returns:
        None；页面可分别读取任务摘要和权威handoff上下文时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    task = TaskRecord(
        task_id="task-2222222222222222",
        operation="case-generation",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        active_handoff_id="case-template-handoff-" + "2" * 20,
        status=TaskStatus.WAITING_FOR_INPUT,
        trace_id="trace-task-context",
        ended_at=utc_now(),
    )
    context = {
        "kind": "case_template",
        "handoff": {"handoff_id": task.active_handoff_id},
        "questions": [{"question_id": "question-1", "status": "open"}],
    }
    monkeypatch.setattr(application, "get_task", lambda _task_id: task)
    monkeypatch.setattr(application, "get_task_context", lambda _task_id: context)

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.get(f"/api/v2/tasks/{task.task_id}/context")

    assert response.status_code == 200
    assert response.json()["task"]["task_id"] == task.task_id
    assert response.json()["context"] == context
    assert response.json()["task"]["client_handoff"] is None


def test_task_scoped_knowledge_answer_updates_the_same_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """知识问题回答必须回写当前TaskRecord，而不是依赖未定义的路由局部变量。

    Args:
        tmp_path: Pytest提供的隔离知识根。
        monkeypatch: 固定知识批次和任务存储写入，避免构造无关扫描资产。

    Returns:
        None；回答后同一task ID进入等待完成状态且答案返回时通过。

    Side Effects:
        只在临时目录初始化应用；不会启动Agent、扫描或QA执行。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    question = KnowledgeQuestion(
        question_id="question-native-task-answer",
        system_id=SYSTEM_ID,
        source="interview",
        title="取消原因由谁确认？",
        detail="源码无法确定最终业务责任方。",
        affected_target_ids=[TARGET_ID],
    )
    handoff = KnowledgeClientHandoff(
        handoff_id="handoff-" + "3" * 24,
        task_id="task-3333333333333333",
        attempt_id="native-task-answer-0001",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        scan_id="scan-native-task-answer",
        batch_id="knowledge-client-native-task-answer",
        agent_run_id="agent-" + "3" * 16,
    )
    workflow = KnowledgeGenerationWorkflowBatch(
        batch_id=handoff.batch_id,
        system_id=SYSTEM_ID,
        scan_id=handoff.scan_id,
        target_ids=[TARGET_ID],
        status="GENERATING",
        questions=[question],
        client_handoff=handoff,
    )
    answered_question = question.model_copy(
        update={"status": "answered", "answer": "由退款域业务负责人确认"}
    )
    answered_workflow = workflow.model_copy(update={"questions": [answered_question]})
    task = TaskRecord(
        task_id=handoff.task_id,
        operation="knowledge-codex-client-handoff",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        client_handoff=handoff,
        status=TaskStatus.WAITING_FOR_INPUT,
        trace_id="trace-native-task-answer",
        ended_at=utc_now(),
    )
    transitioned_task_ids: list[str] = []

    def transition_same_task(
        task_id: str,
        status: TaskStatus,
        updated_handoff: KnowledgeClientHandoff,
        result: dict[str, object] | None = None,
    ) -> TaskRecord:
        """记录知识回答投影使用的任务身份和等待状态。

        Args:
            task_id: 应与原知识任务一致的稳定身份。
            status: 所有问题关闭后的业务等待状态。
            updated_handoff: 已切换到等待完成的知识handoff。
            result: 页面使用的安全问题计数摘要。

        Returns:
            模拟持久化后的同一任务记录。

        Side Effects:
            仅把task ID追加到测试内存列表。
        """

        assert status == TaskStatus.WAITING_FOR_COMPLETION
        assert updated_handoff.task_id == task.task_id
        assert result is not None and result["open_question_count"] == 0
        transitioned_task_ids.append(task_id)
        return task.model_copy(
            update={"status": status, "client_handoff": updated_handoff}
        )

    monkeypatch.setattr(application.tasks, "get", lambda _task_id: task)
    monkeypatch.setattr(
        application.store,
        "read_draft_batch",
        lambda _system_id, _batch_id: workflow,
    )
    monkeypatch.setattr(
        application.knowledge,
        "answer_draft_question",
        lambda *_args, **_kwargs: answered_workflow,
    )
    monkeypatch.setattr(application.knowledge, "bind_client_handoff_thread", lambda *_args: None)
    monkeypatch.setattr(application.tasks, "transition_waiting_task", transition_same_task)
    try:
        result = application.answer_task_question(
            task.task_id,
            "knowledge-answer-request-0001",
            0,
            "answered",
            KnowledgeConfirmation(
                question_id=question.question_id,
                answer="由退款域业务负责人确认",
                affected_target_ids=[TARGET_ID],
            ),
        )
    finally:
        application.close()

    assert transitioned_task_ids == [task.task_id]
    assert result["answer"].status == "answered"
    assert result["task"].task_id == task.task_id


def test_case_handoff_and_task_context_freeze_analysis_instructions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case目录和任务恢复使用handoff冻结规则，不受后续Runtime模板修改影响。

    Args:
        tmp_path: Pytest提供的隔离运行设置目录。
        monkeypatch: 固定Case handoff、输入契约和Runtime能力目录。

    Returns:
        None；handoff与task context在设置变化前后都返回同一冻结规则时通过。

    Side Effects:
        只更新临时运行设置；不提交草稿、发布Generation或访问QA。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    frozen_instructions = "冻结Case规则：先修订草稿，再显式发布；禁止执行QA。"
    handoff = CaseTemplateHandoffV4(
        handoff_id="case-template-handoff-" + "5" * 20,
        system_id=SYSTEM_ID,
        entry_id=TARGET_ID,
        source_scan_id="scan-case-instructions",
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id="scan-case-instructions",
                source_baseline=SourceBaseline(source_path=str(tmp_path / "case-source")),
            )
        ],
        task_id="task-5555555555555555",
        generation_id="case-template-generation-" + "5" * 20,
        analysis_instructions=frozen_instructions,
    )
    task = TaskRecord(
        task_id=handoff.task_id,
        operation="case-generation",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        active_handoff_id=handoff.handoff_id,
        generation_id=handoff.generation_id,
        status=TaskStatus.WAITING_FOR_CLIENT,
        trace_id="trace-case-instructions",
        ended_at=utc_now(),
    )
    blocked_contract = OperationInputKnowledgeContract(
        target_id=TARGET_ID,
        source_scan_id=handoff.source_scan_id,
        status="BLOCKED",
        request_schema={},
        blocked_reason="fixture contract",
    )
    monkeypatch.setattr(application.tasks, "get", lambda _task_id: task)
    monkeypatch.setattr(application.case_template_v4.handoffs, "get", lambda _handoff_id: handoff)
    monkeypatch.setattr(application.case_template_v4, "_input_contract", lambda *_args: blocked_contract)
    monkeypatch.setattr(application.case_template_v4, "_runtime_capabilities", lambda _handoff: [])

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        initial_handoff = client.get(f"/api/v2/case-handoffs/{handoff.handoff_id}")
        initial_context = client.get(f"/api/v2/tasks/{task.task_id}/context")
        application.runtime_settings.write(
            RuntimeToolSettings(
                knowledge_agent_prompt_template="变化后的全局规则 {{target_id}}"
            )
        )
        repeated_handoff = client.get(f"/api/v2/case-handoffs/{handoff.handoff_id}")
        repeated_context = client.get(f"/api/v2/tasks/{task.task_id}/context")

    for response in (
        initial_handoff,
        initial_context,
        repeated_handoff,
        repeated_context,
    ):
        assert response.status_code == 200
    assert initial_handoff.json()["handoff"]["analysis_instructions"] == frozen_instructions
    assert initial_handoff.json()["analysis_instructions"] == frozen_instructions
    assert repeated_handoff.json()["analysis_instructions"] == frozen_instructions
    assert initial_context.json()["context"]["analysis_instructions"] == frozen_instructions
    assert repeated_context.json()["context"]["analysis_instructions"] == frozen_instructions


def test_case_write_conflict_returns_stable_code_and_current_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case revision冲突必须以409返回机器可处理的code和当前版本。

    Args:
        tmp_path: Pytest提供的隔离知识根。
        monkeypatch: 在发布边界注入核心并发冲突而不写Generation。

    Returns:
        None；调用方可按current_revision重新读取上下文时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")

    def reject_publish(_handoff_id: str, _request: object) -> dict[str, object]:
        """模拟另一个修订已先推进handoff版本。

        Args:
            _handoff_id: API解析出的Case handoff身份。
            _request: 已完成严格校验的发布请求。

        Returns:
            本函数总是抛错，不返回业务结果。

        Raises:
            CaseTemplateWriteConflictError: 固定返回服务端当前revision。
        """

        raise CaseTemplateWriteConflictError("REVISION_CONFLICT", 7)

    monkeypatch.setattr(application, "publish_case_template_v4", reject_publish)
    handoff_id = "case-template-handoff-" + "3" * 20
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v2/case-handoffs/{handoff_id}/publications",
            json={
                "request_id": "case-publish-request-1",
                "expected_revision": 6,
                "mode": "complete",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "REVISION_CONFLICT",
        "message": "Case草稿revision已变化，请读取最新上下文后重试",
        "current_revision": 7,
    }


def test_business_task_idempotency_conflict_returns_stable_http_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务task复用request ID但改变参数时返回稳定409幂等冲突。

    Args:
        tmp_path: Pytest提供的隔离知识根。
        monkeypatch: 在Case prepare入口注入任务创建竞争结果。

    Returns:
        None；错误码可被网页和MCP区别于普通作用域冲突时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")

    def reject_prepare(_system_id: str, _request: object) -> dict[str, object]:
        """模拟另一个调用已用相同request ID创建不同目标任务。

        Args:
            _system_id: API路由已经解析的系统身份。
            _request: 严格解析但与首次参数冲突的Case请求。

        Returns:
            本函数总是抛错，不返回业务结果。

        Raises:
            IdempotencyConflictError: 固定表示幂等参数冲突。
        """

        raise IdempotencyConflictError()

    monkeypatch.setattr(application, "start_case_template_generation_v4", reject_prepare)
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/case-generations",
            json={
                "operation_id": TARGET_ID,
                "request_id": "case-start-request-conflict-001",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "IDEMPOTENCY_CONFLICT",
        "message": "request_id is already used with different parameters",
    }


def test_precreated_case_tasks_compare_complete_request_identity(tmp_path: Path) -> None:
    """预建Case任务必须拒绝复用request ID后改变task、根任务、意图或父revision。

    Args:
        tmp_path: Pytest提供的隔离任务目录。

    Returns:
        None；首次任务保持原始创建身份且四类异参重试均冲突时通过。

    Side Effects:
        在隔离知识根写入一个Case初始任务和一个successor任务，不创建handoff或Generation。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    start_request_id = "case-precreated-start-identity-001"
    start_task_id = application._stable_case_task_id(SYSTEM_ID, start_request_id)
    start_request = CaseTemplateGenerationStartRequest(
        operation_id=TARGET_ID,
        request_id=start_request_id,
        task_id=start_task_id,
        root_task_id="task-2222222222222222",
    )

    # 初始任务先落盘后，改变root仍是同一个task/request身份，必须由持久创建回执拒绝。
    initial_task, _effective_request = application._prepare_case_start_task(
        SYSTEM_ID,
        start_request,
    )
    with pytest.raises(IdempotencyConflictError):
        application._prepare_case_start_task(
            SYSTEM_ID,
            start_request.model_copy(
                update={"root_task_id": "task-3333333333333333"}
            ),
        )
    with pytest.raises(IdempotencyConflictError):
        application._prepare_case_start_task(
            SYSTEM_ID,
            start_request.model_copy(update={"task_id": "task-3333333333333333"}),
        )
    assert [
        item.task_id for item in application.tasks.query_records(system_id=SYSTEM_ID)
    ] == [start_task_id]

    predecessor = TaskRecord(
        task_id="task-4444444444444444",
        operation="case-generation",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        root_task_id=initial_task.root_task_id,
        generation_id="case-template-generation-" + "4" * 20,
        active_handoff_id="case-template-handoff-" + "4" * 20,
        status=TaskStatus.COMPLETED,
        trace_id="trace-case-predecessor",
        ended_at=utc_now(),
    )
    successor_request_id = "case-precreated-successor-001"
    successor_task_id = application._stable_case_task_id(
        SYSTEM_ID,
        successor_request_id,
    )
    continuation = CaseTemplateContinuationRequest(
        request_id=successor_request_id,
        expected_revision=4,
        intent="continue",
        task_id=successor_task_id,
        root_task_id=initial_task.root_task_id,
    )

    # successor的继续意图与父revision共同决定业务结果，任何一个变化都不能复用首次任务。
    successor = application._prepare_case_successor_task(predecessor, continuation)
    with pytest.raises(IdempotencyConflictError):
        application._prepare_case_successor_task(
            predecessor,
            continuation.model_copy(update={"intent": "regenerate_latest"}),
        )
    with pytest.raises(IdempotencyConflictError):
        application._prepare_case_successor_task(
            predecessor,
            continuation.model_copy(update={"expected_revision": 5}),
        )
    with pytest.raises(IdempotencyConflictError):
        application._prepare_case_successor_task(
            predecessor,
            continuation.model_copy(update={"task_id": "task-6666666666666666"}),
        )

    assert successor.result["continuation_intent"] == "continue"
    assert successor.result["expected_revision"] == 4
    assert {
        item.task_id for item in application.tasks.query_records(system_id=SYSTEM_ID)
    } == {start_task_id, successor_task_id}


def test_task_context_preserves_case_recovery_data_when_generation_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正式产物缺失时仍返回Case handoff、草稿问题和安全工程诊断。

    Args:
        tmp_path: Pytest提供的隔离知识根。
        monkeypatch: 构造已结算handoff与缺失Generation的本地存储状态。

    Returns:
        None；恢复上下文不因不可读正式产物整体变成404时通过。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    handoff_id = "case-template-handoff-" + "4" * 20
    generation_id = "case-template-generation-" + "4" * 20
    task = TaskRecord(
        task_id="task-4444444444444444",
        operation="case-generation",
        system_id=SYSTEM_ID,
        target_id=TARGET_ID,
        active_handoff_id=handoff_id,
        generation_id=generation_id,
        status=TaskStatus.FAILED,
        trace_id="trace-missing-generation",
        ended_at=utc_now(),
    )
    handoff = CaseTemplateHandoffV4(
        handoff_id=handoff_id,
        system_id=SYSTEM_ID,
        entry_id=TARGET_ID,
        source_scan_id="scan-missing-generation",
        status="BLOCKED",
        generation_id=generation_id,
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id="scan-missing-generation",
                source_baseline=SourceBaseline(source_path="/private/isolated-source"),
            )
        ],
    )
    monkeypatch.setattr(application.tasks, "get", lambda _task_id: task)
    monkeypatch.setattr(application.case_template_v4.handoffs, "get", lambda _handoff_id: handoff)

    def missing_generation(_system_id: str, _generation_id: str) -> object:
        """模拟Generation文件已缺失但handoff仍可读取。

        Args:
            _system_id: Generation所属系统。
            _generation_id: handoff记录的正式产物身份。

        Returns:
            本函数总是抛错，不返回产物。

        Raises:
            KnowledgeNotFoundError: 固定表示本地产物缺失。
        """

        raise KnowledgeNotFoundError("Case Generation not found")

    monkeypatch.setattr(application.case_template_v4.generations, "get", missing_generation)
    context = application.get_task_context(task.task_id)

    assert context["handoff"] == handoff
    assert context["generation"] is None
    assert context["generation_error"] == "Case Generation not found"
