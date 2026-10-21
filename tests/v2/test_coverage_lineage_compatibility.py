"""验证覆盖增强的多层继承、迟到发布和升级前草稿回执兼容。"""

from types import SimpleNamespace

import pytest

from opentest.application.case_template_v4 import CaseTemplateWriteConflictError
from opentest.domain.case_template_v4 import (
    CaseGenerationExecutionV4,
    CaseTemplateDraftRevisionRequest,
    CaseTemplateGenerationV4,
)
from opentest.domain.coverage_workflow import CoverageDisposition, CoverageEnhancement
from opentest.domain.models import TaskStatus
from test_case_template_v4_revision import _compiled, _handoff, _service, _submission
from test_coverage_publication import publication


def _generation(fixture, letter: str, predecessor: str = "", status: str = "READY") -> CaseTemplateGenerationV4:
    """以同一冻结源码保存测试版本，前驱链由各故障场景显式安排。

    Args:
        fixture: 真实隔离MySQL应用及基础Generation。
        letter: 生成唯一、符合正式ID格式的十六进制字符。
        predecessor: 已存在或故意缺失的前驱版本ID。
        status: 模拟READY或会自动继续的PARTIAL产物。
    Returns:
        权威存储回读的不可变Generation。
    """

    # 测试直接登记不可变产物，不执行模型、数据准备或业务目标。
    generation = fixture.generation.model_copy(update={
        "generation_id": "case-template-generation-" + letter * 20,
        "predecessor_generation_id": predecessor,
        "continuation_intent": "continue" if predecessor else "",
        "status": status,
    })
    return fixture.app.case_template_v4.generations.write(generation)


def _workflow(fixture, enhanced_id: str = "", status: str = "PARTIAL") -> CoverageEnhancement:
    """保存一轮已结束增强，提供真实的基础版与增强版关联。

    Args:
        fixture: 真实隔离应用及基础版本身份。
        enhanced_id: 本轮预留的增强版；空串表示未派发过补充。
        status: 用于核实不可复活的增强终态。
    Returns:
        从MySQL读取的覆盖工作流，执行ID使用固定哨兵值检测意外改写。
    """

    # 这组测试不会进入测量，因此不创建任何能被自动执行的业务记录。
    record = CoverageEnhancement(
        enhancement_id="coverage-lineage", task_id="task-" + "f" * 16,
        system_id=fixture.generation.system_id, operation_id=fixture.generation.operation_id,
        base_generation_id=fixture.generation.generation_id, enhanced_generation_id=enhanced_id,
        source_scan_id=fixture.generation.source_scan_id, source_commit="d" * 40,
        status=status, stage="FINISHED", round_used=1 if enhanced_id else 0,
        baseline_case_execution_id="baseline-preserved",
        verification_case_execution_id="verification-preserved",
        reason_codes=["SUPPLEMENT_NOT_PUBLISHED"],
    )
    fixture.app.coverage_assistance.records.create(record)
    return fixture.app.coverage_assistance.records.get(record.enhancement_id)


def test_partial_enhancement_descendant_cannot_register_another_round(publication) -> None:
    """E(PARTIAL)经A(PARTIAL)继续得到B(READY)，仍只能属于原增强链。

    Args:
        publication: 隔离MySQL发布夹具，实际模型和QA派发已替换。
    Returns:
        None；多层增强祖先使新登记返回空且B产物保持可读时通过。
    """

    enhanced = _generation(publication, "e", status="PARTIAL")
    intermediate = _generation(publication, "a", enhanced.generation_id, "PARTIAL")
    ready = _generation(publication, "b", intermediate.generation_id)
    _workflow(publication, enhanced.generation_id)
    service = publication.app.coverage_assistance

    # 一层父节点A没有增强绑定，必须继续向上找到E才能拒绝递归。
    assert service.records.for_generation(ready.system_id, intermediate.generation_id) is None
    assert service._eligible_lineage(ready) is False
    assert service.register(ready, SimpleNamespace(execution_id="unused-new-execution")) is None
    assert service.records.for_generation(ready.system_id, ready.generation_id) is None
    assert publication.app.case_template_v4.generations.get(ready.system_id, ready.generation_id).status == "READY"


def test_regular_ready_continuation_registers_its_own_baseline(publication) -> None:
    """没有增强祖先的普通READY后继可以登记新基线，不因存在前驱一概排除。

    Args:
        publication: 真实隔离MySQL应用与覆盖已启用的系统。
    Returns:
        None；工作流、执行绑定和专属任务均真实落库时通过。
    """

    app = publication.app
    parent = app.case_template_v4.generations.write(publication.generation)
    _workflow(publication, status="SKIPPED")
    ready = _generation(publication, "b", parent.generation_id)
    execution = app.case_template_v4.executions.create(CaseGenerationExecutionV4(
        execution_id="case-generation-execution-" + "b" * 20,
        generation_id=ready.generation_id, system_id=ready.system_id,
        environment_id="qa", status="RUNNING",
    ))

    # 登记复用发布事务；只落执行身份，不派发任何后台业务。
    with app.store.system_transaction(ready.system_id):
        assert app.coverage_assistance._eligible_lineage(ready) is True
        workflow = app.coverage_assistance.register(ready, execution)
    stored = app.coverage_assistance.records.get(workflow.enhancement_id)
    assert stored.base_generation_id == ready.generation_id
    assert stored.baseline_case_execution_id == execution.execution_id
    assert stored.status == "RUNNING" and stored.stage == "BASELINE_EXECUTING"
    assert app.tasks.get(stored.task_id).status == TaskStatus.RUNNING
    assert publication.observer.get_workflow("coverage_enhancement", stored.enhancement_id) is not None
    app.case_template_v4.dispatch_execution.assert_not_called()


@pytest.mark.parametrize("broken_chain", ["missing", "cycle"])
def test_unverifiable_lineage_skips_only_coverage(publication, broken_chain: str) -> None:
    """前驱缺失或循环只跳过辅助，不能删除或阻断已发布的基础产物。

    Args:
        publication: 隔离MySQL版本存储与覆盖服务。
        broken_chain: 缺失祖先或双节点循环的故障形态。
    Returns:
        None；登记为空、READY产物仍可读取且没有新覆盖记录时通过。
    """

    ready_id = "case-template-generation-" + "b" * 20
    parent_id = "case-template-generation-" + "a" * 20
    if broken_chain == "cycle":
        # 故意保存A->B->A脏链，验证有界遍历不会把截断当成无增强祖先。
        _generation(publication, "a", ready_id)
    ready = _generation(publication, "b", parent_id)
    service = publication.app.coverage_assistance
    assert service._eligible_lineage(ready) is False
    assert service.register(ready, SimpleNamespace(execution_id="unused-new-execution")) is None
    assert service.records.for_generation(ready.system_id, ready.generation_id) is None
    assert publication.app.case_template_v4.generations.get(ready.system_id, ready.generation_id).status == "READY"


@pytest.mark.parametrize("terminal_status", ["COMPLETED", "PARTIAL", "FAILED", "SKIPPED"])
def test_late_enhanced_publication_keeps_terminal_state_and_execution_binding(publication, terminal_status: str) -> None:
    """迟到的READY增强版保留产物关联，但不得复活工作流或换成新的复测执行。

    Args:
        publication: 真实MySQL夹具与独立读取连接。
        terminal_status: 每种已经结束的覆盖结果。
    Returns:
        None；完整工作流、revision和原执行绑定保持原值时通过。
    """

    enhanced = _generation(publication, "e")
    before = _workflow(publication, enhanced.generation_id, terminal_status)
    app = publication.app
    with app.store.system_transaction(enhanced.system_id):
        result = app.coverage_assistance.register(
            enhanced, SimpleNamespace(execution_id="late-new-verification"))

    # 独立连接读取防止同一内存对象原地修改掩盖写回，也校验没有隐式推进revision。
    persisted = publication.observer.get_workflow("coverage_enhancement", before.enhancement_id)
    assert result.model_dump(mode="json") == before.model_dump(mode="json")
    assert persisted == before.model_dump(mode="json")
    assert persisted["verification_case_execution_id"] == "verification-preserved"
    assert app.case_template_v4.generations.get(enhanced.system_id, enhanced.generation_id).status == "READY"


def test_old_draft_receipt_replays_empty_dispositions_but_rejects_new_ones(tmp_path) -> None:
    """旧草稿回执缺少可选处置时接受空值重试，真实新增处置仍属幂等冲突。

    Args:
        tmp_path: 测试专属handoff目录，不读取或修改用户草稿。
    Returns:
        None；同参重试不重新编译，不同处置返回IDEMPOTENCY_CONFLICT时通过。
    """

    service, handoffs, _ = _service(tmp_path, _compiled())
    handoff = _handoff(tmp_path)
    handoffs.write(handoff)
    request = CaseTemplateDraftRevisionRequest(
        request_id="legacy-coverage-draft", expected_revision=0, submission=_submission())
    first = service.revise_draft(handoff.handoff_id, request)

    # 模拟升级前持久回执；领域参数是原始dict，删掉新字段后通过真实store重读。
    legacy = handoffs.get(handoff.handoff_id)
    receipt = next(item for item in legacy.request_receipts if item.request_id == request.request_id)
    receipt.parameters.pop("coverage_dispositions")
    handoffs.write(legacy)
    replay = service.revise_draft(handoff.handoff_id, request)
    assert replay == first
    assert handoffs.get(handoff.handoff_id).revision == legacy.revision
    service._compile_draft.assert_called_once()

    changed = request.model_copy(update={"coverage_dispositions": [CoverageDisposition(
        gap_id="gap-new", action="UNRESOLVED", reason="新增处置不得复用旧请求身份")]})
    with pytest.raises(CaseTemplateWriteConflictError) as conflict:
        service.revise_draft(handoff.handoff_id, changed)
    assert conflict.value.error_code == "IDEMPOTENCY_CONFLICT"
    assert handoffs.get(handoff.handoff_id).revision == legacy.revision
    service._compile_draft.assert_called_once()
