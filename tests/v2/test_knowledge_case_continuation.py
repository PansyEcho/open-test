"""验证真实存储中的知识问答版本和Case知识前置续跑。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.foundation import OpenTestApplication
from opentest.domain.case_template_v4 import CaseTemplateGenerationStartRequest
from opentest.domain.errors import IdempotencyConflictError, KnowledgeValidationError, MissingCaseKnowledgeError
from opentest.domain.models import (
    KnowledgeClientHandoff, KnowledgeConfirmation, KnowledgeGenerationWorkflowBatch,
    KnowledgeQuestion, SystemDefinition, TaskRecord, TaskStatus, utc_now,
)
from test_case_template_v4_revision import _handoff, SYSTEM_ID, OPERATION_ID


def _knowledge_task(application):
    """建立含业务问题的真实批次和任务，返回可通过HTTP回答的身份。

    Args:
        application: 使用临时知识根的应用。
    Returns:
        已落盘的知识任务；不访问源码或模型。
    """
    handoff = KnowledgeClientHandoff(
        handoff_id="handoff-" + "7" * 24, task_id="task-" + "7" * 16,
        attempt_id="knowledge-continuation-001", system_id=SYSTEM_ID,
        target_id=OPERATION_ID, scan_id="scan-continuation", batch_id="knowledge-client-continuation",
        agent_run_id="agent-" + "7" * 16,
    )
    # 私有分析指令与批次均走生产持久化接口，避免Mock掩盖重启后的版本丢失。
    application.knowledge._initialize_client_run(handoff, "按已保存答案补齐本接口知识。")
    application.store.write_draft_batch(KnowledgeGenerationWorkflowBatch(
        batch_id=handoff.batch_id, system_id=SYSTEM_ID, scan_id=handoff.scan_id,
        target_ids=[OPERATION_ID], status="GENERATING", client_handoff=handoff,
        questions=[KnowledgeQuestion(question_id="question-business-owner", system_id=SYSTEM_ID,
                                     source="interview", title="取消由谁发起？", detail="源码没有业务角色",
                                     affected_target_ids=[OPERATION_ID])],
    ))
    return application.tasks.create_business_record(TaskRecord(
        task_id=handoff.task_id, system_id=SYSTEM_ID, operation="knowledge-codex-client-handoff",
        target_id=OPERATION_ID, client_handoff=handoff, trace_id="knowledge-continuation",
        result={"request_id": "knowledge-continuation-001"},
        status=TaskStatus.WAITING_FOR_INPUT, ended_at=utc_now(),
    ))


def test_knowledge_unknown_answer_replay_revision_and_disk_reload(tmp_path):
    """未知答案保持问题开放，回答幂等且旧revision不能覆盖新答案。

    Args:
        tmp_path: 隔离知识及任务目录。
    Returns:
        None；真实批次回读与任务版本一致时通过。
    """
    application = OpenTestApplication(tmp_path / "knowledge")
    try:
        application.store.register_system(SystemDefinition(system_id=SYSTEM_ID, name="退款", source_path=str(tmp_path)))
        task = _knowledge_task(application)
        # 损坏的旧候选不能让任务、问题或已保存答案整体不可读取。
        candidate_path = application.knowledge._client_run_root(task.client_handoff) / "output.txt"
        candidate_path.write_text('{"incomplete": true}')
        assert application.get_task_context(task.task_id)["candidate_error"]
        answer = KnowledgeConfirmation(question_id="question-business-owner", answer="不知道",
                                       affected_target_ids=[OPERATION_ID])
        application.answer_task_question(task.task_id, "answer-unknown-001", 0, "unknown", answer)
        application.answer_task_question(task.task_id, "answer-unknown-001", 0, "unknown", answer)
        context = application.get_task_context(task.task_id)
        assert context["revision"] == 1 and context["questions"][0].status == "open"
        known = answer.model_copy(update={"answer": "客服发起"})
        # 同一个已回答内容可以重放，变化内容必须持有最新版本。
        with pytest.raises(IdempotencyConflictError):
            application.answer_task_question(task.task_id, "answer-stale-001", 0, "answered", known)
        application.answer_task_question(task.task_id, "answer-known-001", 1, "answered", known)
        application.answer_task_question(task.task_id, "answer-known-001", 1, "answered", known)
        context = application.get_task_context(task.task_id)
        assert context["revision"] == 2
        assert context["questions"][0].answer == "客服发起"
        assert application.tasks.get(task.task_id).status == TaskStatus.WAITING_FOR_COMPLETION
    finally:
        application.close()


@pytest.mark.parametrize("preparation_fails", [False, True])
def test_case_missing_knowledge_keeps_identity_and_continues(tmp_path, preparation_fails):
    """知识前置成功后继续同一Case；前置准备异常保存明确失败。

    Args:
        tmp_path: 隔离应用状态。
        preparation_fails: 模拟准备源码失败或正常知识发布。
    Returns:
        None；关联与失败状态可恢复、不另建Case任务时通过。
    """
    application = OpenTestApplication(tmp_path / "knowledge")
    try:
        application.store.register_system(SystemDefinition(system_id=SYSTEM_ID, name="退款", source_path=str(tmp_path)))
        prerequisite = _knowledge_task(application)
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
                    request_id="case-with-knowledge-001", interaction_mode="web")
        application.case_template_v4.start = Mock(side_effect=MissingCaseKnowledgeError("missing knowledge"))
        application.knowledge.artifacts.read = Mock(return_value=SimpleNamespace(entries=[], scan_id="scan-continuation"))
        application.case_template_v4._resolve_entry = Mock(return_value=SimpleNamespace(entry_id=OPERATION_ID))
        application.prepare_skill_knowledge_target = Mock(return_value={"task": prerequisite})
        task_id = application._stable_case_task_id(SYSTEM_ID, request.request_id)
        if preparation_fails:
            application.prepare_skill_knowledge_target.side_effect = KnowledgeValidationError("源码准备失败")
            with pytest.raises(KnowledgeValidationError):
                application.start_case_template_generation_v4(SYSTEM_ID, request)
            assert application.tasks.get(task_id).status == TaskStatus.FAILED
            return
        prepared = application.start_case_template_generation_v4(SYSTEM_ID, request)
        assert prepared["task"].task_id == task_id
        assert application.get_task_context(task_id)["answer_task_id"] == prerequisite.task_id
        assert application.web_generation.bound_task(task_id).task_id == prerequisite.task_id
        with pytest.raises(KnowledgeValidationError):
            application.resume_case_after_knowledge(task_id)
        # 模拟知识发布边界完成，其余任务关联、后继准备和磁盘状态都走真实应用服务。
        application.tasks.save_business_record(prerequisite.model_copy(update={"status": TaskStatus.COMPLETED}))
        handoff = _handoff(tmp_path).model_copy(update={"task_id": task_id, "root_task_id": task_id})
        application.case_template_v4.handoffs.write(handoff)
        application.case_template_v4.start = Mock(return_value=handoff)
        application.codex_system_skill_name = Mock(return_value="open-test-test-system")
        resumed = application.resume_case_after_knowledge(task_id)
        assert resumed["task"].task_id == task_id
        assert application.web_generation.bound_task(task_id).active_handoff_id == handoff.handoff_id
        assert len(application.tasks.query_records(operations={"case-generation"})) == 1
    finally:
        application.close()
