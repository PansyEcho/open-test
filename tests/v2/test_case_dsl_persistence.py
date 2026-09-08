"""覆盖真实动态DSL在草稿、回执及API之间的持久化语义。"""

import json

import pytest
from pydantic import ValidationError

from opentest.domain.case_template_v4 import DslValueSource


@pytest.mark.parametrize("payload", [
    {"kind": "step_output", "step_id": "bookings", "path": "list.pageList"},
    {"kind": "data_output", "call_id": "candidate", "output_name": "refund_no"},
    {"kind": "parameter", "name": "state"},
    {"kind": "function_input", "name": "state"},
    {"kind": "request_field", "path": "refundSerialNo"},
    {"kind": "target_response", "path": "orderSerialNo"},
    {"kind": "current_item", "path": "id"},
    {"kind": "environment", "name": "env"},
    {"kind": "runtime_context", "name": "env"},
    {"kind": "literal", "value": None},
])
def test_source_round_trip_preserves_explicit_literal_semantics(payload):
    """任一合法来源都应在普通JSON保存后保持相同含义。

    Args:
        payload: 动态引用或显式null字面量。
    Returns:
        None；普通序列化和严格重读保持模型相等时通过。
    """

    source = DslValueSource.model_validate(payload)
    # 使用真实默认序列化选项，避免测试替生产调用隐藏默认字段问题。
    serialized = source.model_dump_json()
    assert DslValueSource.model_validate_json(serialized) == source
    assert ("value" in json.loads(serialized)) == (source.kind == "literal")


def test_legacy_default_is_accepted_only_from_private_storage():
    """只允许私有存储恢复已确认的完整默认字段形状。

    Returns:
        None；HTTP输入仍被拒绝，私有存储恢复合法引用且不放宽非空值时通过。
    """

    legacy = dict(kind="step_output", value=None, name="", path="list.pageList",
                  step_id="bookings", call_id="", output_name="")
    with pytest.raises(ValidationError):
        DslValueSource.model_validate(legacy)
    # 历史恢复只由存储传递context；工具调用不能自行携带此校验选项。
    restored = DslValueSource.model_validate(legacy, context={"persisted_dsl": True})
    assert restored.step_id == "bookings"
    with pytest.raises(ValidationError):
        DslValueSource.model_validate({**legacy, "value": 7}, context={"persisted_dsl": True})


def test_dynamic_draft_survives_revision_answers_publication_and_receipt_replay(tmp_path):
    """真实引用草稿在磁盘重读、回答和发布后仍可重放首次回执。

    Args:
        tmp_path: 隔离的handoff与正式产物根。
    Returns:
        None；核心写协议跨所有阶段保留动态引用及显式null时通过。
    """

    from test_case_template_v4 import _golden_submission, _cancel_contract, _runtime_registry, SYSTEM_ID, BOOKING_SYSTEM_ID
    from test_case_template_v4_revision import _service, _compiled, _handoff
    from opentest.application.case_template_v4 import CaseTemplateDraftCompilation
    from opentest.application.case_template_compiler_v4 import CaseTemplateCompilerV4
    from opentest.application.case_template_registries import CaseTemplateRegistryLoader
    from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
    from opentest.domain.case_template_v4 import (
        CaseTemplateDraftRevisionRequest, CaseTemplateQuestionAnswerRequest,
        CaseTemplatePublicationRequest, CaseTemplateGenerationV4,
        CaseTemplateCompilationInput,
    )
    from opentest.domain.models import KnowledgeQuestion

    service, store, generations = _service(tmp_path, _compiled())

    def compile_submission(current_handoff, current_submission, resolutions):
        """每次提交及发布都真实编译当前DSL，检出默认字段引起的身份漂移。

        Args:
            current_handoff: 本轮handoff，夹具已冻结源码事实。
            current_submission: 提交或磁盘重读后的DSL。
            resolutions: 本测试没有源码关闭问题的声明。
        Returns:
            真实编译并排序后的发布候选；不模拟Variant身份或校验结果。
        """
        compilation = CaseTemplateCompilationInput(
            submission=current_submission, input_contract=_cancel_contract(),
            target_output_schema={"type": "object", "properties": {
                "success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
                "required": ["success", "orderSerialNo"]},
            runtime_registry=_runtime_registry(), value_registry=CaseTemplateRegistryLoader().value_registry(),
            allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
        )
        # 冻结源码目录由夹具提供，编译器、默认字段和ID计算全部使用生产路径。
        variants, issues = CaseTemplateCompilerV4().compile(compilation)
        return CaseTemplateDraftCompilation(
            input_contract=compilation.input_contract, runtime_registry=compilation.runtime_registry,
            value_registry=compilation.value_registry, variants=service._freeze_variant_order(variants, current_submission),
            issues=issues, invalid_resolution_question_ids=set(),
        )

    service._compile_draft.side_effect = compile_submission
    handoff = _handoff(tmp_path)
    store.write(handoff)
    submission = _golden_submission()
    question = KnowledgeQuestion(question_id="case-question-qa-scope", system_id=handoff.system_id,
                                 source="case_template", title="测试范围", detail="是否覆盖取消状态",
                                 affected_node_ids=[], affected_target_ids=[submission.case_templates[0].template_id], status="open")
    first = CaseTemplateDraftRevisionRequest(request_id="dynamic-draft-001", expected_revision=0,
                                            submission=submission, questions=[question])
    first_receipt = service.revise_draft(handoff.handoff_id, first)
    # 模拟旧版本把动态引用补上value:null，只改typed draft与其提交回执，不改业务literal。
    path = store.root / handoff.handoff_id / "handoff.json"
    legacy = json.loads(path.read_text())
    for draft in [legacy["draft_submission"], legacy["request_receipts"][-1]["parameters"]["submission"]]:
        for function in draft["data_functions"]:
            for step in function["steps"]:
                source = step.get("input_source")
                if source and source["kind"] != "literal":
                    source["value"] = None
    path.write_text(json.dumps(legacy))
    service.handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    assert service.handoffs.get(handoff.handoff_id).draft_submission == submission
    assert service.revise_draft(handoff.handoff_id, first) == first_receipt
    service.answer_question(handoff.handoff_id, CaseTemplateQuestionAnswerRequest(
        request_id="dynamic-answer-001", expected_revision=1, question_id=question.question_id,
        answer="覆盖取消状态", outcome="answered",
    ))
    service.revise_draft(handoff.handoff_id, CaseTemplateDraftRevisionRequest(
        request_id="dynamic-draft-002", expected_revision=2, submission=submission,
    ))
    # 正式产物也经JSON严格回读，防止Mock隐藏Publication receipt中的动态引用问题。
    def persist_generation(generation):
        """把正式Generation写入隔离文件并严格回读，返回持久结果。"""
        target = tmp_path / "generation.json"
        target.write_text(generation.model_dump_json())
        return CaseTemplateGenerationV4.model_validate_json(target.read_text())

    generations.write.side_effect = persist_generation
    publication = CaseTemplatePublicationRequest(request_id="dynamic-publish-001", expected_revision=3, mode="complete")
    published = service.publish(handoff.handoff_id, publication)
    assert published.submission == submission
    assert service.publish(handoff.handoff_id, publication) == published
    assert service.handoffs.get(handoff.handoff_id).revision == 4
