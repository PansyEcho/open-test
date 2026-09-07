"""验证CaseTemplate V4原生Agent草稿、问答、发布和后继安全。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
from opentest.application.case_template_v4 import (
    CaseTemplateDraftCompilation,
    CaseTemplateV4RuntimeServices,
    CaseTemplateV4Service,
    CaseTemplateWriteConflictError,
)
from opentest.domain.case_template_v4 import (
    CaseTemplateEvidence,
    CaseTemplateContinuationRequest,
    CaseTemplateDraftRevisionRequest,
    CaseTemplateGenerationStartRequest,
    CaseTemplateGenerationV4,
    CaseTemplateHandoffV4,
    CaseTemplatePublicationRequest,
    CaseTemplateQuestionAnswerRequest,
    CaseTemplateSourceQuestionResolution,
    CaseTemplateSourceScope,
    CaseTemplateSubmission,
    CaseTemplateValidationIssue,
    CaseVariantV4,
    DataFunctionCall,
    RuntimeFunctionRegistry,
    ValueFunctionRegistry,
)
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.models import (
    KnowledgeQuestion,
    OperationInputFieldKnowledge,
    OperationInputKnowledgeContract,
    SourceBaseline,
    SourceVersionPin,
    SystemDefinition,
)


SYSTEM_ID = "ifightchainsaas.java.refund.core"
OPERATION_ID = "facade:com.example.RefundFacade#cancel"
SCAN_ID = "scan-case-revision"


def _submission(unresolved: bool = False) -> CaseTemplateSubmission:
    """构造仅供核心状态机测试的严格Case草稿。

    Args:
        unresolved: 是否包含一个全局业务未决项。

    Returns:
        不依赖QA或真实源码的最小V4 submission。
    """

    payload = {
        "data_functions": [],
        "case_templates": [],
        "unresolved": [],
    }
    if unresolved:
        payload["unresolved"] = [
            {
                "unresolved_id": "platform-owner",
                "owner_type": "generation",
                "reason": "需要确认平台身份的业务含义",
            }
        ]
    return CaseTemplateSubmission.model_validate(payload)


def _variant(identity: str = "a") -> CaseVariantV4:
    """构造一个不包含任何执行调用的可运行Variant。

    Args:
        identity: 重复二十次形成稳定测试ID的十六进制字符。

    Returns:
        request、DATA、Oracle均为空的状态机测试Variant。
    """

    return CaseVariantV4(
        variant_id=f"case-variant-v4-{identity * 20}",
        template_id="case.ready",
        ordinal=1,
        parameter_values={},
        request_values={},
        data_calls=[],
        oracles=[],
    )


def _contract(scan_id: str = SCAN_ID) -> OperationInputKnowledgeContract:
    """构造草稿发布需要持久化的READY输入契约。

    Args:
        scan_id: 契约绑定的源码扫描身份。

    Returns:
        无字段的严格READY契约。
    """

    return OperationInputKnowledgeContract(
        target_id=OPERATION_ID,
        request_type="CancelRequest",
        source_scan_id=scan_id,
        status="READY",
        request_schema={
            "type": "object",
            "properties": {"refundSerialNo": {"type": "string"}},
            "required": ["refundSerialNo"],
            "additionalProperties": False,
        },
        fields=[
            OperationInputFieldKnowledge(
                path="refundSerialNo",
                field_name="refundSerialNo",
                schema={"type": "string"},
                required=True,
                business_identity=True,
                requirement_marker="@required",
            )
        ],
    )


def _compiled(
    variants: list[CaseVariantV4] | None = None,
    issues: list[CaseTemplateValidationIssue] | None = None,
) -> CaseTemplateDraftCompilation:
    """构造绕过具体编译器细节的确定性草稿结果。

    Args:
        variants: 已编译Variant；默认一个可运行项。
        issues: 最新结构化issues；默认无问题。

    Returns:
        可供草稿和发布状态机复用的编译结果。
    """

    return CaseTemplateDraftCompilation(
        input_contract=_contract(),
        runtime_registry=RuntimeFunctionRegistry(functions=[]),
        value_registry=ValueFunctionRegistry(functions=[]),
        variants=[_variant()] if variants is None else variants,
        issues=[] if issues is None else issues,
        invalid_resolution_question_ids=set(),
    )


def _handoff(
    tmp_path: Path,
    *,
    status: str = "WAITING_FOR_AGENT",
    revision: int = 0,
) -> CaseTemplateHandoffV4:
    """构造绑定临时源码目录的Case handoff。

    Args:
        tmp_path: 测试隔离目录。
        status: 初始handoff状态。
        revision: 初始乐观并发版本。

    Returns:
        拥有预分配Generation ID的严格handoff。
    """

    return CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'b' * 20}",
        system_id=SYSTEM_ID,
        entry_id=OPERATION_ID,
        source_scan_id=SCAN_ID,
        status=status,
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path=str(tmp_path)),
            )
        ],
        generation_id=f"case-template-generation-{'c' * 20}",
        revision=revision,
    )


def _service(
    tmp_path: Path,
    compiled: CaseTemplateDraftCompilation,
) -> tuple[CaseTemplateV4Service, CaseTemplateHandoffStoreV4, Mock]:
    """组装只使用临时handoff和内存Generation替身的Case服务。

    Args:
        tmp_path: 私有handoff状态根。
        compiled: 每次草稿复验返回的确定性结果。

    Returns:
        服务、真实handoff store和Generation替身。
    """

    handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    generations = Mock()
    generations.get.side_effect = KnowledgeNotFoundError("generation absent")
    generations.write.side_effect = lambda generation: generation
    service = CaseTemplateV4Service(Mock(), Mock(), generations, handoffs)
    service._require_current_source_scopes = Mock()
    service._compile_draft = Mock(return_value=compiled)
    return service, handoffs, generations


def _write_raw_handoff(
    store: CaseTemplateHandoffStoreV4,
    handoff: CaseTemplateHandoffV4,
    extra_fields: dict[str, object],
) -> Path:
    """在pytest隔离目录写入带指定根字段的原始handoff夹具。

    Args:
        store: 指向pytest临时私有根的handoff存储。
        handoff: 当前严格模型部分。
        extra_fields: 模拟历史兼容字段或损坏未知字段的根载荷。

    Returns:
        已写入的临时handoff JSON路径。

    Side Effects:
        仅在``tmp_path``派生的测试目录创建fixture，不读取或修改真实handoff资产。
    """

    path = store.root / handoff.handoff_id / "handoff.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 原始JSON绕过当前领域模型，准确模拟升级前已经存在的磁盘记录。
    payload = {**handoff.model_dump(mode="json"), **extra_fields}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_handoff_store_reads_and_preserves_known_legacy_execution_fields(
    tmp_path: Path,
) -> None:
    """已知旧执行字段可读但不进入领域/API投影，更新时仍原样保留。

    Args:
        tmp_path: pytest隔离的handoff私有根。

    Returns:
        None；严格模型不暴露旧字段，raw JSON写回仍保留相同历史值时通过。
    """

    store = CaseTemplateHandoffStoreV4(tmp_path)
    handoff = _handoff(tmp_path)
    legacy_fields = {
        "execution_mode": "QA_AFTER_GENERATION",
        "execution_results": [
            {
                "variant_id": f"case-variant-v4-{'a' * 20}",
                "status": "COMPLETED",
                "historical_payload": {"opaque": True},
            }
        ],
    }
    path = _write_raw_handoff(store, handoff, legacy_fields)

    loaded = store.get(handoff.handoff_id)

    assert loaded == handoff
    assert "execution_mode" not in loaded.model_dump(mode="json")
    assert "execution_results" not in loaded.model_dump(mode="json")
    # 兼容不得下沉到领域Schema，否则旧QA内容可能重新进入API或新业务逻辑。
    with pytest.raises(ValidationError):
        CaseTemplateHandoffV4.model_validate(
            {**handoff.model_dump(mode="json"), **legacy_fields}
        )

    store.write(loaded.model_copy(update={"revision": 1}))

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["execution_mode"] == legacy_fields["execution_mode"]
    assert persisted["execution_results"] == legacy_fields["execution_results"]
    assert persisted["revision"] == 1


@pytest.mark.parametrize(
    ("extra_fields", "reason"),
    [
        pytest.param({"unexpected_future_field": True}, "extra_forbidden", id="unknown-field"),
        pytest.param({"execution_mode": "FUTURE_MODE"}, "execution_mode", id="bad-mode"),
        pytest.param({"execution_results": ["not-an-object"]}, "execution_results", id="bad-results"),
    ],
)
def test_handoff_store_rejects_unknown_or_malformed_legacy_fields(
    tmp_path: Path,
    extra_fields: dict[str, object],
    reason: str,
) -> None:
    """兼容白名单之外的字段和非法旧字段外壳继续严格失败。

    Args:
        tmp_path: pytest隔离的handoff私有根。
        extra_fields: 当前用例写入的未知或非法兼容载荷。
        reason: 预期出现在安全错误中的字段或校验类型。

    Returns:
        None；错误能定位handoff和安全原因且不回显载荷值时通过。
    """

    store = CaseTemplateHandoffStoreV4(tmp_path)
    handoff = _handoff(tmp_path)
    _write_raw_handoff(store, handoff, extra_fields)

    with pytest.raises(KnowledgeValidationError) as failure:
        store.get(handoff.handoff_id)

    message = str(failure.value)
    assert handoff.handoff_id in message
    assert reason in message
    assert "FUTURE_MODE" not in message
    assert "not-an-object" not in message


def test_handoff_store_rejects_invalid_json_with_safe_identity(tmp_path: Path) -> None:
    """损坏JSON仍失败且错误只返回handoff身份和格式原因。

    Args:
        tmp_path: pytest隔离的handoff私有根。

    Returns:
        None；损坏正文不进入错误消息时通过。
    """

    store = CaseTemplateHandoffStoreV4(tmp_path)
    handoff = _handoff(tmp_path)
    path = store.root / handoff.handoff_id / "handoff.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 使用不会被JSON解析器接受的固定内容，验证读取边界而非领域字段。
    path.write_text('{"sensitive": ', encoding="utf-8")

    with pytest.raises(KnowledgeValidationError) as failure:
        store.get(handoff.handoff_id)

    message = str(failure.value)
    assert handoff.handoff_id in message
    assert "invalid JSON" in message
    assert "sensitive" not in message


def test_start_prepares_same_task_without_starting_background_agent(tmp_path: Path) -> None:
    """历史handoff存在时Case start仍准备新任务且保持request幂等。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；旧字段不阻断新建，同参重试复用且异参重试冲突时通过。
    """

    handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    # 幂等扫描会遍历全部记录；先放置真实旧字段形状才能覆盖原始回归入口。
    _write_raw_handoff(
        handoffs,
        _handoff(tmp_path),
        {"execution_mode": "QA_AFTER_GENERATION", "execution_results": []},
    )
    artifacts = Mock()
    entry = Mock()
    entry.kind.value = "facade"
    entry.entry_id = OPERATION_ID
    artifacts.read.return_value = Mock(scan_id=SCAN_ID, entries=[entry])
    operation_service = Mock()
    store = Mock()
    initial_system = Mock(source_version=None)
    store.get_system.return_value = initial_system
    store.source_scan_matches_configured_version.return_value = True
    service = CaseTemplateV4Service(
        store,
        artifacts,
        Mock(),
        handoffs,
        CaseTemplateV4RuntimeServices(
            operation_catalog=Mock(),
            operation_service=operation_service,
            environment_provider=lambda _system_id: {},
        ),
    )
    service._input_contract = Mock(return_value=_contract())
    service._source_scopes = Mock(return_value=_handoff(tmp_path).source_scopes)
    request = CaseTemplateGenerationStartRequest(
        operation_id="RefundFacade#cancel",
        request_id="case-start-native-001",
        task_id=f"task-{'1' * 16}",
    )

    first = service.start(SYSTEM_ID, request)
    # 首次结果已经落盘后，即使系统pin切换且新扫描未就绪，同参网络重试也应恢复原结果。
    changed_system = Mock(source_path=str(tmp_path), source_version=Mock())
    store.get_system.return_value = changed_system
    store.source_scan_matches_configured_version.return_value = False
    second = service.start(SYSTEM_ID, request)

    assert first == second
    assert first.status == "WAITING_FOR_AGENT"
    assert first.task_id == f"task-{'1' * 16}"
    assert first.entry_id == OPERATION_ID
    assert first.thread_id == ""
    assert store.get_system.call_count == 1
    artifacts.read.assert_called_once_with(SYSTEM_ID, "latest")
    service._input_contract.assert_called_once_with(SYSTEM_ID, OPERATION_ID, SCAN_ID)
    operation_service.execute.assert_not_called()
    with pytest.raises(CaseTemplateWriteConflictError) as conflict:
        service.start(
            SYSTEM_ID,
            request.model_copy(update={"task_id": f"task-{'2' * 16}"}),
        )
    assert conflict.value.error_code == "IDEMPOTENCY_CONFLICT"


def test_start_rejects_ambiguous_short_target_before_handoff_write(tmp_path: Path) -> None:
    """latest完整扫描存在同名Facade时拒绝短名且不猜测包路径。

    Args:
        tmp_path: 仅用于构造隔离系统路径，不读取真实知识或源码。

    Returns:
        None；start返回明确歧义且没有写入handoff时通过。
    """

    first = Mock()
    first.kind.value = "facade"
    first.entry_id = "facade:com.example.first.RefundFacade#cancel"
    second = Mock()
    second.kind.value = "facade"
    second.entry_id = "facade:com.example.second.RefundFacade#cancel"
    artifacts = Mock()
    artifacts.read.return_value = Mock(scan_id=SCAN_ID, entries=[first, second])
    handoffs = Mock()
    handoffs.request_scope.return_value = nullcontext()
    handoffs.find_request_receipt.return_value = None
    store = Mock()
    store.get_system.return_value = Mock(source_version=None, source_path=str(tmp_path))
    store.source_scan_matches_configured_version.return_value = True
    service = CaseTemplateV4Service(store, artifacts, Mock(), handoffs)

    # 短名必须在latest完整基线内唯一；两个包候选不能按扫描顺序选第一个。
    with pytest.raises(KnowledgeValidationError, match="ambiguous.*fully qualified"):
        service.start(
            SYSTEM_ID,
            CaseTemplateGenerationStartRequest(
                operation_id="RefundFacade#cancel",
                request_id="case-start-ambiguous-001",
            ),
        )

    artifacts.read.assert_called_once_with(SYSTEM_ID, "latest")
    handoffs.write.assert_not_called()


def test_repairable_draft_persists_without_blocked_generation(tmp_path: Path) -> None:
    """可修复草稿只推进revision并保存issue，不提前发布BLOCKED。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；Generation store未被调用且handoff仍可修订时通过。
    """

    issue = CaseTemplateValidationIssue(
        code="REQUEST_BINDING_TYPE_MISMATCH",
        owner="case_template:case.ready",
        field="orderState",
        message="请求绑定类型不兼容",
    )
    service, handoffs, generations = _service(tmp_path, _compiled([], [issue]))
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)

    result = service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-repairable-001",
            expected_revision=0,
            submission=_submission(),
        ),
    )

    persisted = handoffs.get(handoff.handoff_id)
    assert result.status == "WAITING_FOR_AGENT"
    assert result.revision == 1
    assert persisted.validation_issues == [issue]
    assert persisted.draft_submission == _submission()
    assert persisted.recoverable is True
    generations.write.assert_not_called()


def test_concurrent_same_revision_has_exactly_one_winner(tmp_path: Path) -> None:
    """两个不同request ID竞争同一revision时最多一个能够写入。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；一个结果成功且另一个收到当前revision冲突时通过。
    """

    service, handoffs, _generations = _service(tmp_path, _compiled())
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    requests = [
        CaseTemplateDraftRevisionRequest(
            request_id=f"draft-concurrent-{index:03d}",
            expected_revision=0,
            submission=_submission(),
        )
        for index in (1, 2)
    ]

    def write(request: CaseTemplateDraftRevisionRequest) -> object:
        """提交一个并发草稿并返回成功值或业务冲突。

        Args:
            request: 使用同一expected revision的不同请求。

        Returns:
            草稿结果或捕获的CaseTemplateWriteConflictError。
        """

        try:
            return service.revise_draft(handoff.handoff_id, request)
        except CaseTemplateWriteConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, requests))

    conflicts = [item for item in outcomes if isinstance(item, CaseTemplateWriteConflictError)]
    assert len(conflicts) == 1
    assert conflicts[0].error_code == "REVISION_CONFLICT"
    assert conflicts[0].current_revision == 1
    assert handoffs.get(handoff.handoff_id).revision == 1


def test_request_receipt_returns_first_result_and_rejects_parameter_reuse(
    tmp_path: Path,
) -> None:
    """相同request重试返回首次结果，异参复用同一ID则冲突。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；首次revision不会被后续修订改写且异参收到稳定冲突码。
    """

    service, handoffs, _generations = _service(tmp_path, _compiled())
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    first = CaseTemplateDraftRevisionRequest(
        request_id="draft-idempotent-001",
        expected_revision=0,
        submission=_submission(),
    )
    first_result = service.revise_draft(handoff.handoff_id, first)
    service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-idempotent-002",
            expected_revision=1,
            submission=_submission(),
        ),
    )

    retried = service.revise_draft(handoff.handoff_id, first)

    assert retried == first_result
    assert retried.revision == 1
    assert handoffs.get(handoff.handoff_id).revision == 2
    with pytest.raises(CaseTemplateWriteConflictError) as conflict:
        service.revise_draft(
            handoff.handoff_id,
            first.model_copy(update={"expected_revision": 2, "submission": _submission(True)}),
        )
    assert conflict.value.error_code == "IDEMPOTENCY_CONFLICT"


def test_case_unknown_answer_stays_open_and_confirmation_keeps_target_scope(
    tmp_path: Path,
) -> None:
    """Case回答跨重启持久化，未知不关闭且确认不冒充知识节点。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；新store可读问题、答案及仅Case target范围的confirmation时通过。
    """

    service, handoffs, _generations = _service(tmp_path, _compiled())
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    question = KnowledgeQuestion(
        question_id="case-question-platform-owner",
        system_id=SYSTEM_ID,
        source="case_template",
        title="平台身份是否等价",
        detail="ownerId是否可作为platFormId",
        affected_node_ids=[],
        affected_target_ids=["case.ready"],
        status="open",
    )
    service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-question-001",
            expected_revision=0,
            submission=_submission(),
            questions=[question],
        ),
    )
    unknown = service.answer_question(
        handoff.handoff_id,
        CaseTemplateQuestionAnswerRequest(
            request_id="answer-question-unknown-001",
            expected_revision=1,
            question_id=question.question_id,
            answer="不知道，需要业务方继续确认",
            outcome="unknown",
        ),
    )

    reloaded = CaseTemplateHandoffStoreV4(tmp_path).get(handoff.handoff_id)
    assert unknown.question.status == "open"
    assert reloaded.status == "WAITING_FOR_INPUT"
    assert reloaded.questions[0].answer == "不知道，需要业务方继续确认"
    assert reloaded.confirmations[0].confirmed_node_ids == []
    assert reloaded.confirmations[0].affected_target_ids == ["case.ready"]


def test_answer_cannot_bypass_deterministic_type_issue(tmp_path: Path) -> None:
    """用户业务确认不能清除编译器字段或类型错误。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；回答后仍等待Agent修复且不允许complete发布时通过。
    """

    issue = CaseTemplateValidationIssue(
        code="REQUEST_BINDING_TYPE_MISMATCH",
        owner="case_template:case.ready",
        field="platFormId",
        message="ownerId与platFormId类型不兼容",
    )
    service, handoffs, _generations = _service(tmp_path, _compiled([], [issue]))
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    question = KnowledgeQuestion(
        question_id="case-question-owner-platform",
        system_id=SYSTEM_ID,
        source="case_template",
        title="确认业务身份",
        detail="确认ownerId与platFormId业务语义",
        affected_target_ids=["case.ready"],
    )
    service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-type-question-001",
            expected_revision=0,
            submission=_submission(),
            questions=[question],
        ),
    )

    answered = service.answer_question(
        handoff.handoff_id,
        CaseTemplateQuestionAnswerRequest(
            request_id="answer-type-question-001",
            expected_revision=1,
            question_id=question.question_id,
            answer="业务语义等价",
        ),
    )

    persisted = handoffs.get(handoff.handoff_id)
    assert answered.status == "WAITING_FOR_AGENT"
    assert persisted.validation_issues == [issue]
    assert "complete" not in service._allowed_publication_modes(persisted)


def test_source_token_cannot_dismiss_case_business_equivalence_question(
    tmp_path: Path,
) -> None:
    """已读源码中的字段token不能关闭另一个字段的业务等价性问题。

    Args:
        tmp_path: pytest临时handoff目录。

    Returns:
        None；源码解决被拒绝、原问题仍开放且handoff revision不变时通过。
    """

    service, handoffs, _generations = _service(tmp_path, _compiled())
    handoff = _handoff(tmp_path)
    question = KnowledgeQuestion(
        question_id="case-question-owner-platform-source",
        system_id=SYSTEM_ID,
        source="case_template",
        title="确认平台身份是否等价",
        detail="ownerId是否一定等价于platFormId",
        affected_target_ids=["case.ready"],
        category="case_template_business_rule",
    )
    handoffs.write(handoff.model_copy(update={"questions": [question]}))
    resolution = CaseTemplateSourceQuestionResolution(
        question_id=question.question_id,
        explanation="源码中存在ownerId字段，因此声称两者等价",
        evidence=[
            CaseTemplateEvidence(
                source_system_id=SYSTEM_ID,
                path="src/main/java/demo/SaasOrderVO.java",
                symbol="ownerId",
                line=12,
            )
        ],
    )

    with pytest.raises(KnowledgeValidationError, match="explicit user answer"):
        service.revise_draft(
            handoff.handoff_id,
            CaseTemplateDraftRevisionRequest(
                request_id="draft-source-business-resolution-001",
                expected_revision=0,
                submission=_submission(),
                source_resolutions=[resolution],
            ),
        )

    persisted = handoffs.get(handoff.handoff_id)
    assert persisted.revision == 0
    assert persisted.questions == [question]
    assert persisted.questions[0].status == "open"


def test_dependency_failure_preserves_draft_reason_and_allows_new_revision(tmp_path: Path) -> None:
    """依赖或归档故障应保留草稿和具体阻塞原因，修复后可在同一handoff继续。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；失败revision可恢复、同request重放原错误且新request修订成功时通过。
    """

    service, handoffs, _generations = _service(tmp_path, _compiled())
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    dependency_error = KnowledgeValidationError(
        "archive file digest mismatch: knowledge-drafts/refund/cancel.yaml"
    )
    service._compile_draft.side_effect = dependency_error
    failed_request = CaseTemplateDraftRevisionRequest(
        request_id="draft-dependency-failure-001",
        expected_revision=0,
        submission=_submission(),
    )

    with pytest.raises(KnowledgeValidationError, match="archive file digest mismatch"):
        service.revise_draft(handoff.handoff_id, failed_request)
    failed = handoffs.get(handoff.handoff_id)
    assert failed.status == "FAILED"
    assert failed.recoverable is True
    assert failed.revision == 1
    assert failed.draft_submission == failed_request.submission
    assert failed.failure_code == "DEPENDENCY_VALIDATION_FAILED"
    assert "knowledge-drafts/refund/cancel.yaml" in failed.safe_error

    with pytest.raises(KnowledgeValidationError, match="knowledge-drafts/refund/cancel.yaml"):
        service.revise_draft(handoff.handoff_id, failed_request)

    service._compile_draft.side_effect = None
    service._compile_draft.return_value = _compiled()
    repaired = service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-after-dependency-repair-001",
            expected_revision=1,
            submission=_submission(),
        ),
    )
    assert repaired.status == "READY_TO_PUBLISH"
    assert repaired.revision == 2


def test_available_publication_requires_question_independent_data_functions(tmp_path: Path) -> None:
    """PARTIAL发布不得把依赖开放data function问题的Variant当成安全可运行项。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；只有引用其他data function的Variant保留available发布资格时通过。
    """

    affected_variant = _variant().model_copy(
        update={
            "data_calls": [
                DataFunctionCall(call_id="load_order", function_name="load_order")
            ]
        }
    )
    independent_variant = _variant("d").model_copy(
        update={
            "template_id": "case.independent",
            "data_calls": [
                DataFunctionCall(call_id="load_user", function_name="load_user")
            ],
        }
    )
    service, _handoffs, _generations = _service(
        tmp_path,
        _compiled([affected_variant, independent_variant]),
    )
    question = KnowledgeQuestion(
        question_id="case-question-load-order",
        system_id=SYSTEM_ID,
        source="case_template",
        title="确认订单准备语义",
        detail="load_order的数据选择条件尚未确认",
        affected_target_ids=["data_function:load_order"],
    )

    assert service._question_affects_variant(question, affected_variant) is True
    assert service._question_affects_variant(question, independent_variant) is False

    unknown_scope_question = question.model_copy(
        update={
            "question_id": "case-question-target-contract",
            "affected_target_ids": [OPERATION_ID],
        }
    )
    assert service._question_affects_variant(unknown_scope_question, independent_variant) is True


def test_complete_publication_is_separate_and_retry_reuses_generation(tmp_path: Path) -> None:
    """READY草稿需显式发布，成功请求重试返回同一Generation。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；草稿阶段不写资产，publish仅写一次且handoff最终完成时通过。
    """

    compiled = _compiled()
    service, handoffs, generations = _service(tmp_path, compiled)
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-ready-publish-001",
            expected_revision=0,
            submission=_submission(),
        ),
    )
    generations.write.assert_not_called()
    publication = CaseTemplatePublicationRequest(
        request_id="publish-ready-generation-001",
        expected_revision=1,
        mode="complete",
    )

    first = service.publish(handoff.handoff_id, publication)
    second = service.publish(handoff.handoff_id, publication)

    assert first == second
    assert first.status == "READY"
    assert generations.write.call_count == 1
    assert handoffs.get(handoff.handoff_id).status == "COMPLETED"
    assert handoffs.get(handoff.handoff_id).revision == 2


def test_generation_write_interruption_is_recovered_without_duplicate_publish(
    tmp_path: Path,
) -> None:
    """Generation已写但handoff更新中断时重试只补齐同一资产。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；Generation write一次且第二次完成状态回执时通过。
    """

    compiled = _compiled()
    service, handoffs, generations = _service(tmp_path, compiled)
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-before-interrupt-001",
            expected_revision=0,
            submission=_submission(),
        ),
    )
    saved: dict[str, CaseTemplateGenerationV4] = {}

    def read_generation(_system_id: str, generation_id: str) -> CaseTemplateGenerationV4:
        """从内存模拟append-only Generation回读。

        Args:
            _system_id: 测试中固定的系统身份。
            generation_id: 预分配Generation身份。

        Returns:
            已写入的Generation。

        Raises:
            KnowledgeNotFoundError: 首次发布尚未写入。
        """

        if generation_id not in saved:
            raise KnowledgeNotFoundError("generation absent")
        return saved[generation_id]

    def write_generation(generation: CaseTemplateGenerationV4) -> CaseTemplateGenerationV4:
        """模拟只允许首次写入的append-only Generation store。

        Args:
            generation: 待发布不可变Generation。

        Returns:
            原样保存的Generation。
        """

        saved[generation.generation_id] = generation
        return generation

    generations.get.side_effect = read_generation
    generations.write.side_effect = write_generation
    original_write = handoffs.write
    fail_once = True

    def flaky_handoff_write(value: CaseTemplateHandoffV4) -> CaseTemplateHandoffV4:
        """仅在首次发布终态写入处模拟进程中断。

        Args:
            value: 当前准备持久化的handoff。

        Returns:
            非中断写入由真实store完成。

        Raises:
            OSError: 第一次COMPLETED状态更新模拟落盘失败。
        """

        nonlocal fail_once
        if value.status == "COMPLETED" and fail_once:
            fail_once = False
            raise OSError("simulated handoff update interruption")
        return original_write(value)

    handoffs.write = flaky_handoff_write  # type: ignore[method-assign]
    request = CaseTemplatePublicationRequest(
        request_id="publish-interruption-repair-001",
        expected_revision=1,
        mode="complete",
    )

    with pytest.raises(OSError, match="interruption"):
        service.publish(handoff.handoff_id, request)
    recovered = service.publish(handoff.handoff_id, request)

    assert recovered.generation_id == handoff.generation_id
    assert generations.write.call_count == 1
    assert handoffs.get(handoff.handoff_id).status == "COMPLETED"


def test_final_blocked_requires_revised_draft_after_answer(tmp_path: Path) -> None:
    """回答只关闭问题，Agent移除unresolved后才能显式发布final_blocked。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；回答后旧草稿仍不可发布，新revision移除unresolved后才允许BLOCKED。
    """

    issue = CaseTemplateValidationIssue(
        code="UNRESOLVED_BLOCKER",
        owner="generation",
        message="需要确认平台身份的业务含义",
    )
    compiled = _compiled([], [issue])
    service, handoffs, generations = _service(tmp_path, compiled)
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    draft = service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-unresolved-blocker-001",
            expected_revision=0,
            submission=_submission(True),
        ),
    )
    assert draft.status == "WAITING_FOR_INPUT"
    assert generations.write.call_count == 0
    question_id = draft.questions[0].question_id
    service.answer_question(
        handoff.handoff_id,
        CaseTemplateQuestionAnswerRequest(
            request_id="answer-unresolved-blocker-001",
            expected_revision=1,
            question_id=question_id,
            answer="该接口在当前业务约束下没有可构造身份",
        ),
    )

    answered = handoffs.get(handoff.handoff_id)
    assert answered.status == "WAITING_FOR_AGENT"
    assert answered.draft_submission is not None
    assert answered.draft_submission.unresolved
    assert service._allowed_publication_modes(answered) == []
    with pytest.raises(KnowledgeValidationError, match="not eligible"):
        service.publish(
            handoff.handoff_id,
            CaseTemplatePublicationRequest(
                request_id="publish-stale-final-blocked-001",
                expected_revision=2,
                mode="final_blocked",
            ),
        )

    # 用户答案需要由Agent落实到新DSL；无可运行项的确定阻塞才可形成正式BLOCKED。
    blocked_variant = _variant().model_copy(update={"blocked_reason": "业务约束下不可构造输入"})
    service._compile_draft.return_value = _compiled([blocked_variant], [])
    revised = service.revise_draft(
        handoff.handoff_id,
        CaseTemplateDraftRevisionRequest(
            request_id="draft-resolved-blocker-001",
            expected_revision=2,
            submission=_submission(),
        ),
    )
    assert revised.status == "READY_TO_PUBLISH"
    assert revised.allowed_publication_modes == ["final_blocked"]
    generation = service.publish(
        handoff.handoff_id,
        CaseTemplatePublicationRequest(
            request_id="publish-final-blocked-001",
            expected_revision=3,
            mode="final_blocked",
        ),
    )

    assert generation.status == "BLOCKED"
    assert generation.variants == [blocked_variant]
    assert handoffs.get(handoff.handoff_id).status == "BLOCKED"


def test_formal_generation_continue_creates_new_frozen_successor(tmp_path: Path) -> None:
    """继续旧正式Generation创建新ID并保留父记录退役字段。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；父记录保留历史执行值，后继记录只使用当前Schema时通过。
    """

    handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    predecessor = _handoff(tmp_path, status="COMPLETED", revision=4)
    legacy_fields = {
        "execution_mode": "QA_AFTER_GENERATION",
        "execution_results": [{"status": "COMPLETED", "historical_payload": {"opaque": True}}],
    }
    predecessor_path = _write_raw_handoff(handoffs, predecessor, legacy_fields)
    generation = CaseTemplateGenerationV4(
        generation_id=predecessor.generation_id,
        handoff_id=predecessor.handoff_id,
        system_id=SYSTEM_ID,
        operation_id=OPERATION_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{OPERATION_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="READY",
        input_contract=_contract(),
        submission=_submission(),
        variants=[_variant()],
    )
    generations = Mock()
    generations.get.return_value = generation
    service = CaseTemplateV4Service(Mock(), Mock(), generations, handoffs)
    service._require_current_source_scopes = Mock()

    successor = service.continue_generation(
        SYSTEM_ID,
        generation.generation_id,
        CaseTemplateContinuationRequest(
            request_id="continue-generation-001",
            expected_revision=4,
            intent="continue",
            task_id=f"task-{'d' * 16}",
        ),
    )

    parent = handoffs.get(predecessor.handoff_id)
    assert successor.handoff_id != predecessor.handoff_id
    assert successor.generation_id != generation.generation_id
    assert successor.predecessor_generation_id == generation.generation_id
    assert successor.source_scan_id == predecessor.source_scan_id
    assert successor.source_scopes == predecessor.source_scopes
    assert successor.task_id == f"task-{'d' * 16}"
    assert parent.successor_handoff_id == successor.handoff_id
    assert parent.revision == 5
    assert generation.generation_id == predecessor.generation_id
    persisted_parent = json.loads(predecessor_path.read_text(encoding="utf-8"))
    successor_path = handoffs.root / successor.handoff_id / "handoff.json"
    persisted_successor = json.loads(successor_path.read_text(encoding="utf-8"))
    assert persisted_parent["execution_mode"] == legacy_fields["execution_mode"]
    assert persisted_parent["execution_results"] == legacy_fields["execution_results"]
    assert "execution_mode" not in persisted_successor
    assert "execution_results" not in persisted_successor


def test_continuation_retry_repairs_parent_link_after_interruption(tmp_path: Path) -> None:
    """后继已写但父链接中断时，同request重试补链且不再创建后继。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；父revision只推进一次且持久状态中只有首次后继时通过。
    """

    handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    predecessor = _handoff(tmp_path, status="COMPLETED", revision=7)
    handoffs.write(predecessor)
    generation = CaseTemplateGenerationV4(
        generation_id=predecessor.generation_id,
        handoff_id=predecessor.handoff_id,
        system_id=SYSTEM_ID,
        operation_id=OPERATION_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{OPERATION_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="READY",
        input_contract=_contract(),
        submission=_submission(),
        variants=[_variant()],
    )
    generations = Mock()
    generations.get.return_value = generation
    service = CaseTemplateV4Service(Mock(), Mock(), generations, handoffs)
    service._require_current_source_scopes = Mock()
    original_write = handoffs.write
    fail_parent_link_once = True

    def flaky_handoff_write(value: CaseTemplateHandoffV4) -> CaseTemplateHandoffV4:
        """仅中断首次父handoff后继链接写入。

        Args:
            value: 当前准备持久化的父或后继handoff。

        Returns:
            未命中故障点时由真实store持久化的handoff。

        Raises:
            OSError: 首次父链接写入模拟进程中断。
        """

        nonlocal fail_parent_link_once
        if (
            value.handoff_id == predecessor.handoff_id
            and value.successor_handoff_id
            and fail_parent_link_once
        ):
            fail_parent_link_once = False
            raise OSError("simulated predecessor link interruption")
        return original_write(value)

    handoffs.write = flaky_handoff_write  # type: ignore[method-assign]
    request = CaseTemplateContinuationRequest(
        request_id="continue-interruption-repair-001",
        expected_revision=7,
        intent="continue",
        task_id=f"task-{'f' * 16}",
    )

    with pytest.raises(OSError, match="predecessor link interruption"):
        service.continue_generation(SYSTEM_ID, generation.generation_id, request)
    recovered = service.continue_generation(SYSTEM_ID, generation.generation_id, request)

    parent = handoffs.get(predecessor.handoff_id)
    successors = [
        item
        for item in handoffs.list()
        if item.predecessor_handoff_id == predecessor.handoff_id
    ]
    assert successors == [recovered]
    assert parent.successor_handoff_id == recovered.handoff_id
    assert parent.revision == 8


def test_regenerate_latest_rebinds_only_on_explicit_intent(tmp_path: Path) -> None:
    """regenerate_latest显式使用最新完整扫描并清除旧源码解决证据。

    Args:
        tmp_path: pytest临时目录。

    Returns:
        None；后继绑定latest scan且旧Generation保持不变时通过。
    """

    handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    predecessor = _handoff(tmp_path, status="BLOCKED", revision=2)
    handoffs.write(predecessor)
    generation = CaseTemplateGenerationV4(
        generation_id=predecessor.generation_id,
        handoff_id=predecessor.handoff_id,
        system_id=SYSTEM_ID,
        operation_id=OPERATION_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{OPERATION_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="BLOCKED",
        input_contract=_contract(),
        submission=_submission(True),
        variants=[],
    )
    generations = Mock()
    generations.get.return_value = generation
    latest_scan_id = "scan-case-latest-complete"
    entry = Mock()
    entry.kind.value = "facade"
    entry.entry_id = OPERATION_ID
    artifacts = Mock()
    artifacts.read.return_value = Mock(
        scan_id=latest_scan_id,
        entries=[entry],
        baseline=SourceBaseline(source_path=str(tmp_path / "latest")),
    )
    store = Mock()
    store.get_system.return_value = Mock(source_version=None)
    store.source_scan_matches_configured_version.return_value = True
    service = CaseTemplateV4Service(store, artifacts, generations, handoffs)
    service._input_contract = Mock(return_value=_contract(latest_scan_id))
    latest_scope = CaseTemplateSourceScope(
        source_system_id=SYSTEM_ID,
        source_scan_id=latest_scan_id,
        source_baseline=SourceBaseline(source_path=str(tmp_path / "latest")),
    )
    service._source_scopes = Mock(return_value=[latest_scope])

    successor = service.continue_generation(
        SYSTEM_ID,
        generation.generation_id,
        CaseTemplateContinuationRequest(
            request_id="regenerate-generation-latest-001",
            expected_revision=2,
            intent="regenerate_latest",
            task_id=f"task-{'e' * 16}",
        ),
    )

    assert successor.source_scan_id == latest_scan_id
    assert successor.source_scopes == [latest_scope]
    assert successor.continuation_intent == "regenerate_latest"
    assert successor.predecessor_generation_id == generation.generation_id
    assert successor.draft_variants == []
    assert successor.validation_issues == []
    assert generation.source_scan_id == SCAN_ID


def test_regenerate_latest_rejects_scan_from_previous_source_pin(tmp_path: Path) -> None:
    """pin切换后的regenerate_latest不得静默复用旧完整latest。

    Args:
        tmp_path: pytest隔离的handoff和源码目录。

    Returns:
        None；旧latest被拒绝且父handoff没有创建successor或推进revision时通过。

    Side Effects:
        仅在临时handoff目录写入一个正式父记录，不创建正式Generation文件。
    """

    handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    predecessor = _handoff(tmp_path, status="BLOCKED", revision=2)
    handoffs.write(predecessor)
    generation = CaseTemplateGenerationV4(
        generation_id=predecessor.generation_id,
        handoff_id=predecessor.handoff_id,
        system_id=SYSTEM_ID,
        operation_id=OPERATION_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{OPERATION_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="BLOCKED",
        input_contract=_contract(),
        submission=_submission(True),
        variants=[],
    )
    generations = Mock()
    generations.get.return_value = generation
    source_root = tmp_path / "source"
    source_root.mkdir()
    configured_commit = "9" * 40
    system = SystemDefinition(
        system_id=SYSTEM_ID,
        name="Refund Core",
        source_path=str(source_root),
        source_version=SourceVersionPin(
            selected_revision=configured_commit,
            commit=configured_commit,
            branch_hint="release/new-baseline",
            managed_tag=f"opentest/baseline/{configured_commit}",
        ),
    )
    store = Mock()
    store.get_system.return_value = system
    store.source_scan_matches_configured_version.return_value = False
    artifacts = Mock()
    artifacts.read.return_value = Mock(
        scan_id="scan-previous-pin",
        entries=[],
        baseline=SourceBaseline(
            source_path=str(source_root),
            commit="8" * 40,
            branch="release/old-baseline",
        ),
    )
    service = CaseTemplateV4Service(store, artifacts, generations, handoffs)
    service.source_repository = Mock()

    # pin B尚无完整扫描时，regenerate_latest必须等待而不是把旧latest A冻结为后继。
    with pytest.raises(
        KnowledgeValidationError,
        match="configured source baseline scan is not ready for Case regeneration",
    ):
        service.continue_generation(
            SYSTEM_ID,
            generation.generation_id,
            CaseTemplateContinuationRequest(
                request_id="regenerate-pin-mismatch-001",
                expected_revision=2,
                intent="regenerate_latest",
                task_id="task-6666666666666666",
            ),
        )

    unchanged = handoffs.get(predecessor.handoff_id)
    assert unchanged.successor_handoff_id == ""
    assert unchanged.revision == 2
    service.source_repository.resolve_source_version_pin.assert_called_once_with(
        system.source_path,
        system.source_version,
    )
