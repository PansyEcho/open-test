"""验证接口级覆盖投影、行覆盖率、新增Case和缺口源码读取。"""

from __future__ import annotations

import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.coverage_assistance import CoverageAssistanceService
from opentest.domain.coverage import (
    ArtifactFileIdentity, CodeCoverageGap, CodeLocation, CoverageAnalysisResult,
    CoverageArtifactSelection, CoverageCounts, CoverageScopeLimitation, FrozenCoverageArtifact,
)
from opentest.domain.coverage_workflow import (
    CoverageEnhancement, CoverageMeasurement, CoverageRawCapture, CoverageReport,
)
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.shared_workspace import CaseSelection


def _counts(line_covered: int, line_missed: int) -> CoverageCounts:
    """构造同范围的方法/行/分支计数，便于直接断言页面百分比。"""

    return CoverageCounts(method={"covered": 2, "missed": 1},
                          line={"covered": line_covered, "missed": line_missed},
                          branch={"covered": 1, "missed": 2})


def _analysis(line_covered: int, line_missed: int, gaps: list[CodeCoverageGap]) -> CoverageAnalysisResult:
    """返回带真实缺口范围的分析结果，不依赖 JaCoCo 或网络。"""

    counts = _counts(line_covered, line_missed)
    return CoverageAnalysisResult(raw_counts=counts, scope_counts=counts, matched_class_count=3,
        uncomparable_class_count=0, scope_status="PARTIAL", scope_reason="仅纳入可信已解析调用。",
        scope_limitations=[CoverageScopeLimitation(caller_class="AbstractFacade", caller_method="execute",
            expression="invoke", reason="reflection_target_not_static", line=120)],
        gaps=gaps, candidate_gap_count=len(gaps) + 2, deferred_gap_count=2)


def _gap(kind: str, path: str, class_name: str, method: str, line: int, end_line: int | None,
         missed: int) -> CodeCoverageGap:
    """构造一个页面缺口，行区间由分析器持久化。"""

    return CodeCoverageGap(gap_id=f"gap-{kind}-{line}", kind=kind,
        location=CodeLocation(source_path=path, class_name=class_name, method_name=method,
                              method_descriptor=f"({method})", line=line, end_line=end_line),
        scope_reason="固定扫描已解析调用闭包中的方法。", before={"covered": 0, "missed": missed})


def _case(case_id: str, generation_id: str, variant_id: str, title: str) -> SimpleNamespace:
    """返回与 SingleCaseView 相同的最小投影字段。"""

    return SimpleNamespace(generation_id=generation_id, title=title, source_scan_id="scan-interface",
        operation_id="facade:Refund#billSupplement",
        variant=SimpleNamespace(variant_id=variant_id))


def _workflow(gaps: list[CodeCoverageGap]) -> tuple[CoverageEnhancement, CoverageReport, dict[str, SimpleNamespace], dict[str, SimpleNamespace]]:
    """构造基础2条、增强后4条Case的已完成轮次及原始固定材料。"""

    base_cases = [CaseSelection(case_id="case-base-1", generation_id="generation-base", variant_id="variant-base-1"),
                  CaseSelection(case_id="case-base-2", generation_id="generation-base", variant_id="variant-base-2")]
    added_cases = [CaseSelection(case_id="case-added-1", generation_id="generation-enhanced", variant_id="variant-added-1"),
                   CaseSelection(case_id="case-added-2", generation_id="generation-enhanced", variant_id="variant-added-2")]
    workflow = CoverageEnhancement(
        enhancement_id="coverage-interface", task_id="task-" + "1" * 16,
        system_id="refund", operation_id="facade:Refund#billSupplement",
        base_generation_id="generation-base", enhanced_generation_id="generation-enhanced",
        source_scan_id="scan-interface", source_commit="a" * 40, environment_id="qa",
        owner_user_id="employee-a", baseline_id="baseline-a", status="COMPLETED", stage="FINISHED",
        baseline_case_execution_id="baseline-exec", verification_case_execution_id="verification-exec",
        case_selection=base_cases,
        baseline=CoverageMeasurement(case_execution_id="baseline-exec", status="VALID",
                                     analysis=_analysis(4, 6, gaps)),
        verification=CoverageMeasurement(case_execution_id="verification-exec", status="VALID",
                                         analysis=_analysis(8, 2, gaps)),
    )
    report = CoverageReport(execution_id="coverage-interface", system_id="refund",
        generation_id="generation-base", operation_id=workflow.operation_id, environment_id="qa",
        owner_user_id="employee-a", result={
            "baseline": CoverageRawCapture(exec_artifact_id="exec", deployed_artifact_id="binary",
                                           source_artifact_id="source"),
            "verification": CoverageRawCapture(exec_artifact_id="exec-2", deployed_artifact_id="binary",
                                               source_artifact_id="source"),
        })
    cases = {item.case_id: _case(item.case_id, item.generation_id, item.variant_id, item.case_id)
             for item in [*base_cases, *added_cases]}
    generations = {
        "generation-base": SimpleNamespace(generation_id="generation-base", status="READY",
            baseline_id="baseline-a", operation_id=workflow.operation_id, source_scan_id="scan-interface",
            case_bindings=[SimpleNamespace(case_id=item.case_id, variant_id=item.variant_id) for item in base_cases]),
        "generation-enhanced": SimpleNamespace(generation_id="generation-enhanced", status="READY",
            baseline_id="baseline-a", operation_id=workflow.operation_id, source_scan_id="scan-interface",
            case_bindings=[SimpleNamespace(case_id=item.case_id, variant_id=item.variant_id,
                origin_kind="COVERAGE_REUSED" if item in base_cases else "COVERAGE_NEW") for item in [*base_cases, *added_cases]]),
    }
    # 标题来自本轮不可变编译结果，权限索引本身不需要携带完整 Case。
    enhanced = generations["generation-enhanced"]
    enhanced.variants = [SimpleNamespace(variant_id=item.variant_id, template_id="template-" + item.case_id)
                         for item in enhanced.case_bindings]
    enhanced.submission = SimpleNamespace(case_templates=[
        SimpleNamespace(template_id="template-" + item.case_id, title=item.case_id)
        for item in enhanced.case_bindings])
    return workflow, report, cases, generations


def _service(workflow: CoverageEnhancement, report: CoverageReport,
             cases: dict[str, SimpleNamespace], generations: dict[str, SimpleNamespace]) -> CoverageAssistanceService:
    """组装只读投影服务，所有数据库与外部材料均由显式替身提供。"""

    service = object.__new__(CoverageAssistanceService)
    service.records = Mock()
    service.records.latest_for_operation.return_value = workflow
    service.records.report.return_value = report

    def visible_cases(scope, selections):
        """模拟批量索引只返回精确当前指针，提供实际视图但不加载完整 Case。"""

        visible = {}
        # 旧 Generation 即使仍保留正文，也不等于该 Case 的当前版本仍可见。
        for item in selections:
            case = cases.get(item.case_id)
            if case is not None and (case.generation_id, case.variant.variant_id) == (item.generation_id, item.variant_id):
                visible[item.case_id] = {"case_id": item.case_id, "generation_id": item.generation_id,
                                        "variant_id": item.variant_id, "view": "mine"}
        return visible

    execution = SimpleNamespace(generation_id="generation-enhanced", environment_id="qa",
        selected_cases=[CaseSelection(case_id="case-added-1", generation_id="generation-enhanced", variant_id="variant-added-1"),
                        CaseSelection(case_id="case-added-2", generation_id="generation-enhanced", variant_id="variant-added-2")],
        variant_results=[SimpleNamespace(variant_id="variant-added-1", status="COMPLETED"),
                         SimpleNamespace(variant_id="variant-added-2", status="FAILED")])
    service.app = SimpleNamespace(
        case_template_v4=SimpleNamespace(
            generations=SimpleNamespace(get=lambda system_id, generation_id: generations[generation_id]),
            executions=SimpleNamespace(get=lambda system_id, execution_id: execution),
        ),
        publications=SimpleNamespace(get_case=Mock(side_effect=AssertionError("must not read cases one by one")),
            visible_case_selections=Mock(side_effect=visible_cases)),
        object_storage=None,
    )
    # 任务时间由已保存事实提供；这些旧记录缺时间，不伪造当前时间。
    service.tasks = SimpleNamespace(get=Mock(return_value=SimpleNamespace(started_at=None, ended_at=None, progress=None)))
    return service


def test_interface_projection_returns_line_percent_added_cases_and_uncovered_locations() -> None:
    """接口页一次读取就能得到行覆盖率、两条新增Case真实状态和26行缺口。"""

    gaps = [
        _gap("METHOD", "RefundValidator.java", "RefundValidator", "validateRefund", 92, 104, 1),
        _gap("LINE_BLOCK", "BillSupplementService.java", "BillSupplementService", "handleSupplement", 216, 227, 12),
        _gap("BRANCH_LINE", "RefundCallbackHandler.java", "RefundCallbackHandler", "onFailure", 68, 68, 3),
    ]
    workflow, report, cases, generations = _workflow(gaps)
    service = _service(workflow, report, cases, generations)
    result = service.interface_projection("refund", "baseline-a", "employee-a",
                                          workflow.operation_id, "qa", "mine")
    coverage = result["coverage"]
    assert coverage["baseline"]["line"]["percent"] == 40.0
    assert coverage["verification"]["line"]["percent"] == 80.0
    assert coverage["line_percent"] == 80.0
    assert coverage["added_case_counts"] == {"total": 2, "passed": 1, "failed": 1, "pending": 0, "unknown": 0}
    assert [(item["case_id"], item["verification"]) for item in coverage["added_cases"]] == [
        ("case-added-1", "PASSED"), ("case-added-2", "FAILED")]
    assert coverage["uncovered_summary"] == {"location_count": 3, "line_count": 26,
        "whole_method_count": 1, "candidate_gap_count": 5, "deferred_gap_count": 2}
    assert coverage["source_available"] is True
    assert coverage["anchor_case"] == {"case_id": "case-base-1", "variant_id": "variant-base-1",
        "generation_id": "generation-base", "view": "mine"}
    assert coverage["scope_status"] == "PARTIAL" and coverage["attribution"] == "UNVERIFIED"
    assert coverage["verification"]["scope_limitations"][0]["expression"] == "invoke"
    assert service.records.latest_for_operation.call_args.args == (
        "refund", "baseline-a", workflow.operation_id, "employee-a", "qa")


def test_interface_projection_tolerates_unpublished_enhanced_generation() -> None:
    """补充模型尚未发布子Generation时展示基线覆盖并继续轮询，不报读取失败。"""

    gaps = [_gap("METHOD", "RefundValidator.java", "RefundValidator", "validateRefund", 92, 104, 1)]
    workflow, report, cases, generations = _workflow(gaps)
    workflow = workflow.model_copy(update={"status": "RUNNING", "stage": "SUPPLEMENT_RUNNING",
        "enhanced_generation_id": "generation-pending"})
    workflow.verification = CoverageMeasurement(case_execution_id="verification-exec", status="PENDING")
    service = _service(workflow, report, cases, generations)

    def get_generation(system_id: str, generation_id: str):
        """模拟增强子Generation尚未写入，其他基础Generation仍可读取。"""

        if generation_id == "generation-pending":
            raise KnowledgeNotFoundError("尚未发布")
        return generations[generation_id]

    service.app.case_template_v4.generations.get = get_generation
    coverage = service.interface_projection("refund", "baseline-a", "employee-a",
                                            workflow.operation_id, "qa", "mine")["coverage"]
    assert coverage["status"] == "RUNNING"
    assert coverage["line_percent"] == 40.0
    assert coverage["added_cases"] == []
    assert coverage["added_case_counts"] == {"total": 0, "passed": 0, "failed": 0, "pending": 0, "unknown": 0}
    assert coverage["anchor_case"]["case_id"] == "case-base-1"


def test_interface_projection_returns_none_without_visible_round() -> None:
    """没有本人可见轮次时返回空覆盖，不构造零覆盖率。"""

    service = object.__new__(CoverageAssistanceService)
    service.records = Mock()
    service.records.latest_for_operation.return_value = None
    assert service.interface_projection("refund", "baseline-a", "employee-a",
                                         "facade:Refund#billSupplement", "qa") == {"coverage": None, "availability": "not_found"}


@pytest.mark.parametrize("binding_count", [1, 40])
def test_full_projection_uses_one_batch_for_all_bindings_and_anchor(binding_count: int) -> None:
    """新增数量增加时仍只做一次权限批查，标题与入口不触发单项 Case 查询。"""

    workflow, report, cases, generations = _workflow([])
    enhanced = generations["generation-enhanced"]
    selected = [CaseSelection(case_id=f"new-{index}", generation_id=enhanced.generation_id,
                              variant_id=f"variant-new-{index}") for index in range(binding_count)]
    # 每条绑定有独立模板，防止仅测试共用模板时掩盖逐项读取。
    enhanced.case_bindings = [SimpleNamespace(case_id=item.case_id, variant_id=item.variant_id,
                                             origin_kind="COVERAGE_NEW") for item in selected]
    enhanced.variants = [SimpleNamespace(variant_id=item.variant_id, template_id="template-" + item.case_id)
                         for item in selected]
    enhanced.submission.case_templates = [SimpleNamespace(template_id="template-" + item.case_id,
                                                          title="已授权标题 " + item.case_id) for item in selected]
    cases.update({item.case_id: _case(item.case_id, item.generation_id, item.variant_id, "不得读取的单项标题")
                  for item in selected})
    service = _service(workflow, report, cases, generations)
    execution = service.app.case_template_v4.executions.get(workflow.system_id, workflow.verification_case_execution_id)
    execution.selected_cases, execution.variant_results = selected, []
    service.app.case_template_v4.generations.get = Mock(return_value=enhanced)

    response = service.interface_projection("refund", "baseline-a", "employee-a", workflow.operation_id, "qa", "mine")

    assert response["availability"] == "available"
    coverage = response["coverage"]
    assert coverage["added_case_counts"]["total"] == binding_count
    assert [item["title"] for item in coverage["added_cases"]] == ["已授权标题 " + item.case_id for item in selected]
    assert coverage["anchor_case"]["case_id"] == "case-base-1"
    service.app.publications.visible_case_selections.assert_called_once()
    service.app.publications.get_case.assert_not_called()
    service.app.case_template_v4.generations.get.assert_called_once_with("refund", "generation-enhanced")


@pytest.mark.parametrize("visibility", ["missing", "generation_changed", "variant_changed"])
def test_unselected_hidden_binding_keeps_counts_without_disclosing_title(visibility: str) -> None:
    """未进入复测的绑定失去精确权限时保留占位计数，既不泄露标题也不使整轮失效。"""

    workflow, report, cases, generations = _workflow([])
    enhanced = generations["generation-enhanced"]
    hidden = SimpleNamespace(case_id="case-private-added", variant_id="variant-private", origin_kind="COVERAGE_NEW")
    enhanced.case_bindings.append(hidden)
    enhanced.variants.append(SimpleNamespace(variant_id=hidden.variant_id, template_id="template-private"))
    enhanced.submission.case_templates.append(SimpleNamespace(template_id="template-private", title="不得泄露的来源标题"))
    # 同 Case ID 的新版本同样不能授权读取本轮旧模板标题。
    if visibility != "missing":
        cases[hidden.case_id] = _case(hidden.case_id,
            "other-generation" if visibility == "generation_changed" else enhanced.generation_id,
            "other-variant" if visibility == "variant_changed" else hidden.variant_id, "当前其他版本标题")
    service = _service(workflow, report, cases, generations)
    response = service.interface_projection("refund", "baseline-a", "employee-a", workflow.operation_id, "qa", "mine")

    assert response["availability"] == "available"
    coverage = response["coverage"]
    assert coverage["added_case_counts"]["total"] == 3
    assert coverage["case_origin_counts"] == {"reused": 2, "adjusted": 0, "new": 3, "unknown": 0}
    assert coverage["origin_case_items"][-1]["title"] == "Case " + hidden.case_id[-8:]
    assert "不得泄露" not in str(response) and "当前其他版本标题" not in str(response)
    service.app.publications.visible_case_selections.assert_called_once()
    service.app.publications.get_case.assert_not_called()


@pytest.mark.parametrize("changed_key", ["generation_id", "variant_id"])
def test_anchor_requires_exact_version_and_uses_authorized_view(changed_key: str) -> None:
    """入口跳过 Case ID 相同但版本不符的候选，只返回下一条精确命中的实际视图。"""

    workflow, report, cases, generations = _workflow([])
    service = _service(workflow, report, cases, generations)
    visible = {item.case_id: {**item.model_dump(), "view": "published"} for item in workflow.case_selection}
    # 直接给出冲突候选，验证调用方不会依赖批量服务恰好已过滤这一实现细节。
    visible[workflow.case_selection[0].case_id][changed_key] = "changed"
    anchor = service._anchor_case(workflow.case_selection, visible)
    assert anchor == {**workflow.case_selection[1].model_dump(), "view": "published"}
    visible.pop(workflow.case_selection[1].case_id)
    assert service._anchor_case(workflow.case_selection, visible) is None
    service.app.publications.get_case.assert_not_called()


@pytest.mark.parametrize("missing_case", ["case-base-1", "case-added-1", "empty"])
def test_full_projection_rejects_incomplete_fixed_selection(missing_case: str) -> None:
    """基础或复测任一固定项缺失及空全集均不可查看，不把剩余条目冒充完整覆盖。"""

    workflow, report, cases, generations = _workflow([])
    service = _service(workflow, report, cases, generations)
    if missing_case == "empty":
        workflow.case_selection = []
        execution = service.app.case_template_v4.executions.get(workflow.system_id, workflow.verification_case_execution_id)
        execution.selected_cases = []
    else:
        cases.pop(missing_case)
    # 权限失效必须在报告和任务内容投影之前结束。
    response = service.interface_projection("refund", "baseline-a", "employee-a", workflow.operation_id, "qa")
    assert response["availability"] == "selection_unavailable" and response["coverage"] is None
    service.records.report.assert_not_called()
    service.tasks.get.assert_not_called()
    service.app.publications.get_case.assert_not_called()


def test_full_projection_distinguishes_batch_failure_from_selection_loss() -> None:
    """批量权限存储故障保持读取失败语义，不能降级为旧选择已失效或无覆盖记录。"""

    workflow, report, cases, generations = _workflow([])
    service = _service(workflow, report, cases, generations)
    service.app.publications.visible_case_selections.side_effect = RuntimeError("metadata unavailable")
    response = service.interface_projection("refund", "baseline-a", "employee-a", workflow.operation_id, "qa")
    assert response["availability"] == "coverage_unavailable" and response["coverage"] is None
    service.app.publications.get_case.assert_not_called()


def test_visible_binding_without_fixed_template_is_unavailable() -> None:
    """精确绑定可见但编译模板缺失属于内容损坏，不能伪造普通占位标题掩盖故障。"""

    workflow, report, cases, generations = _workflow([])
    # 与既有单项 Case 投影一致，可见绑定必须具有完整固定 Variant 和模板。
    generations["generation-enhanced"].submission.case_templates = []
    service = _service(workflow, report, cases, generations)
    response = service.interface_projection("refund", "baseline-a", "employee-a", workflow.operation_id, "qa")
    assert response["availability"] == "coverage_unavailable" and response["coverage"] is None
    service.app.publications.get_case.assert_not_called()


def test_source_snippet_reads_only_fixed_material_and_marks_uncovered_lines(tmp_path: Path) -> None:
    """源码抽屉按缺口路径读取固定归档，并只标记请求范围内的未覆盖行。"""

    member = "app/validator/src/main/java/demo/RefundValidator.java"
    source = tmp_path / "RefundValidator.java"
    source.write_text("\n".join(f"line-{number}" for number in range(1, 21)) + "\n", encoding="utf-8")
    archive_path = tmp_path / "source.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source, arcname=member)
    gaps = [_gap("METHOD", member, "demo/RefundValidator", "validateRefund", 2, 5, 1)]
    workflow, report, cases, generations = _workflow(gaps)
    fingerprint = ArtifactFileIdentity(path=str(archive_path), size=archive_path.stat().st_size, modified="1")
    frozen = FrozenCoverageArtifact(selection=CoverageArtifactSelection(app_uk="fixture"), commit="a" * 40,
        transport="LOCAL", artifact=ArtifactFileIdentity(path=str(source), size=source.stat().st_size, modified="1"),
        source=fingerprint)
    report.result["baseline"] = CoverageRawCapture(artifact=frozen)
    workflow.verification.status = "SKIPPED"
    service = _service(workflow, report, cases, generations)
    service.records.get.return_value = workflow
    snippet = service.source_snippet("refund", "baseline-a", "employee-a", "qa",
                                     "coverage-interface", member, 2, 4)
    assert [item["number"] for item in snippet["lines"]] == [2, 3, 4]
    assert snippet["uncovered_lines"] == [2, 3, 4]
    assert snippet["lines"][0]["text"] == "line-2"
    with pytest.raises(KnowledgeValidationError, match="不属于本次覆盖缺口"):
        service.source_snippet("refund", "baseline-a", "employee-a", "qa",
                              "coverage-interface", "other.java", 1, 2)


def test_new_round_rejects_enhanced_case_set_from_another_source_commit() -> None:
    """增强后的Case集源码变化时不能静默作为新基线。"""

    from opentest.application.coverage_retry import _new_round_selection

    previous = SimpleNamespace(operation_id="facade:Refund#billSupplement", environment_id="qa",
                               verification_case_execution_id="")
    generation = SimpleNamespace(status="READY", baseline_id="baseline-a", operation_id=previous.operation_id,
        generation_id="generation-enhanced", source_scan_id="scan-interface",
        source_scopes=[SimpleNamespace(source_system_id="refund", source_baseline=SimpleNamespace(commit="b" * 40))],
        case_bindings=[])
    scope = SimpleNamespace(system_id="refund", baseline_id="baseline-a", user_id="employee-a")
    baseline = SimpleNamespace(source_commit="a" * 40)
    with pytest.raises(KnowledgeValidationError, match="代码基准不一致"):
        _new_round_selection(Mock(), scope, previous, baseline, generation)
