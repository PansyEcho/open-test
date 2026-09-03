"""验证scan绑定程序Case分析、Semantic Draft完整性和bundle发布门禁。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.models import (
    CaseCondition,
    CaseConditionResolutionOwner,
    CaseConditionType,
    CaseSemanticDraft,
    CaseSemanticResolution,
    DecisionObligation,
    DsfOperationDefinition,
    EntryPoint,
    KnowledgeNodeKind,
    ProgramAnalysisIssue,
    ProgramCaseAnalysisArtifact,
    ProgramCaseAnalysisCatalog,
    ProgramSemanticGap,
    RequirementObligation,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticCaseEvidence,
    SemanticMethodDefinition,
    SemanticResolutionStatus,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
)


SYSTEM_ID = "sample-system"
ENTRY_ID = "facade:sample.SubmitFacade#submit"


def test_scan_bundle_publish_requires_matching_program_catalog(tmp_path: Path) -> None:
    """latest发布必须同时具备同scan、baseline和Entry全集的Program Catalog。

    Args:
        tmp_path: Pytest隔离的本地扫描缓存根。

    Returns:
        None；孤立Manifest被拒绝且完整BLOCKED bundle可以发布时通过。

    Side Effects:
        仅在隔离目录写入通用Manifest、Catalog和latest指针。
    """

    store = SourceScanArtifactStore(tmp_path / "knowledge")
    manifest = _manifest(tmp_path)
    manifest_path = store.scan_root / SYSTEM_ID / f"{manifest.scan_id}.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(KnowledgeNotFoundError, match="program case analysis"):
        store.publish_latest(SYSTEM_ID, manifest.scan_id)

    catalog = _blocked_catalog(manifest)
    store.write_scan_bundle(manifest, catalog)
    store.publish_latest(SYSTEM_ID, manifest.scan_id)

    assert store.read(SYSTEM_ID, "latest").scan_id == manifest.scan_id
    assert store.read_case_analysis(SYSTEM_ID, "latest") == catalog


def test_scan_bundle_rejects_baseline_and_entry_drift(tmp_path: Path) -> None:
    """bundle准备阶段应拒绝Catalog基线漂移或遗漏Entry。

    Args:
        tmp_path: Pytest隔离的本地扫描缓存根。

    Returns:
        None；两类不完整Catalog均无法写成可发布bundle时通过。

    Side Effects:
        只创建隔离目录；校验失败发生在任何bundle文件写入之前。
    """

    store = SourceScanArtifactStore(tmp_path / "knowledge")
    manifest = _manifest(tmp_path)
    drifted_catalog = _blocked_catalog(manifest).model_copy(
        update={"source_baseline": manifest.baseline.model_copy(update={"commit": "other"})}
    )
    empty_catalog = _blocked_catalog(manifest).model_copy(update={"artifacts": []})

    with pytest.raises(KnowledgeValidationError, match="baseline"):
        store.write_scan_bundle(manifest, drifted_catalog)
    with pytest.raises(KnowledgeValidationError, match="entry set"):
        store.write_scan_bundle(manifest, empty_catalog)


def test_semantic_draft_requires_exactly_one_resolution_per_program_gap(tmp_path: Path) -> None:
    """Semantic Draft遗漏、跨作用域或控制服务端字段时必须阻塞。

    Args:
        tmp_path: 用于构造通用SourceBaseline的隔离路径。

    Returns:
        None；只有完整且不夹带义务身份的Resolution集合通过时结束。

    Side Effects:
        无；全部校验在内存模型上执行。
    """

    manifest = _manifest(tmp_path)
    requirement = RequirementObligation(
        obligation_id="obligation:program:0001:0001",
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        title="程序影响待语义分区",
        origin="program",
        requirement_id="semantic-gap:program:0001:0001",
        statement="字段影响计算结果但候选分区尚未确定。",
    )
    gap_evidence = SemanticCaseEvidence(
        evidence_id="sample#submit:field_influence:1:1",
        method_symbol_id="sample.SubmitFacadeImpl#submit(sample.SubmitRequest)",
        kind="field_influence",
        field_paths=["request.amount"],
        influence_kind="calculation",
        binding_kind="entry_parameter",
        source_ref=SourceReference(path="src/main/java/sample/SubmitFacadeImpl.java", line=10),
    )
    unrelated_evidence = SemanticCaseEvidence(
        evidence_id="sample#submit:decision:20:1",
        method_symbol_id="sample.SubmitFacadeImpl#submit(sample.SubmitRequest)",
        kind="decision",
        field_paths=["request.mode"],
        condition="request.mode == 'M'",
        outcomes=["TRUE", "FALSE"],
        source_ref=SourceReference(path="src/main/java/sample/SubmitFacadeImpl.java", line=20),
    )
    artifact = ProgramCaseAnalysisArtifact(
        artifact_id=f"program-analysis:{manifest.scan_id}:0001",
        system_id=SYSTEM_ID,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        entry_id=ENTRY_ID,
        status="ANALYZED",
        evidence=[gap_evidence, unrelated_evidence],
        core_obligations=[requirement],
        conditions=[
            CaseCondition(
                condition_id="condition:program:0001:calculation",
                condition_type=CaseConditionType.INPUT_COVERAGE,
                title="计算影响待业务分区",
                summary="入口字段影响计算，但业务取值仍需确认。",
                evidence_ids=[gap_evidence.evidence_id],
                source_refs=[gap_evidence.source_ref],
                resolution_owner=CaseConditionResolutionOwner.AI,
                blocks_generation=True,
                technical_code="BLOCKED_FIELD_PARTITION_REQUIRED",
            )
        ],
        semantic_gaps=[
            ProgramSemanticGap(
                gap_id="semantic-gap:program:0001:0001",
                condition_id="condition:program:0001:calculation",
                requirement_obligation_id=requirement.obligation_id,
                evidence_ids=["sample#submit:field_influence:1:1"],
                reason_code="BLOCKED_FIELD_PARTITION_REQUIRED",
                message="需要语义确定业务分区。",
            )
        ],
    )
    builder = ProgramCaseAnalysisBuilder()
    missing_draft = _semantic_draft(artifact, [])
    controlled_payload = _semantic_draft(
        artifact,
        [
            CaseSemanticResolution(
                gap_id=artifact.semantic_gaps[0].gap_id,
                condition_id=artifact.semantic_gaps[0].condition_id,
                action="REPLACE_WITH_TYPED_OBLIGATION",
                obligation_kind="factor",
                title="示例因素",
                payload={
                    "obligation_id": "obligation:program:forged",
                    "factor_path": "mode",
                    "values": ["A", "B"],
                },
                reason="业务枚举需要两个等价类。",
            )
        ],
    )
    valid_replacement = _semantic_draft(
        artifact,
        [
            CaseSemanticResolution(
                gap_id=artifact.semantic_gaps[0].gap_id,
                condition_id=artifact.semantic_gaps[0].condition_id,
                action="REPLACE_WITH_TYPED_OBLIGATION",
                obligation_kind="factor",
                title="金额分区",
                payload={"factor_path": "request.amount", "values": [1, 2]},
                reason="业务确认两个代表值。",
            )
        ],
    )
    complete_draft = _semantic_draft(
        artifact,
        [
            CaseSemanticResolution(
                gap_id=artifact.semantic_gaps[0].gap_id,
                condition_id=artifact.semantic_gaps[0].condition_id,
                action="NO_ADDITIONAL_OBLIGATION",
                reason="程序Decision义务已经覆盖该影响，无需新增因素。",
            )
        ],
    )
    borrowed_evidence_draft = _semantic_draft(
        artifact,
        [
            CaseSemanticResolution(
                gap_id=artifact.semantic_gaps[0].gap_id,
                condition_id=artifact.semantic_gaps[0].condition_id,
                action="REPLACE_WITH_TYPED_OBLIGATION",
                obligation_kind="decision",
                title="借用其他分支证据",
                payload={
                    "condition": unrelated_evidence.condition,
                    "outcomes": unrelated_evidence.outcomes,
                    "decision_evidence_id": unrelated_evidence.evidence_id,
                    "predicate": {
                        "operator": "eq",
                        "input_path": "request.mode",
                        "expected": "M",
                    },
                    "outcome_expectations": {"TRUE": True, "FALSE": False},
                    "input_vectors": {
                        "TRUE": {"request.mode": "M"},
                        "FALSE": {"request.mode": "A"},
                    },
                },
                reason="故意引用不属于当前Gap的证据。",
            )
        ],
    )

    with pytest.raises(KnowledgeValidationError, match="every program gap"):
        builder.validate_semantic_draft(artifact, missing_draft)
    with pytest.raises(KnowledgeValidationError, match="server-owned"):
        builder.validate_semantic_draft(artifact, controlled_payload)
    with pytest.raises(KnowledgeValidationError, match="outside its program gap"):
        builder.validate_semantic_draft(artifact, borrowed_evidence_draft)
    with pytest.raises(KnowledgeValidationError, match="cannot remove"):
        builder.validate_semantic_draft(artifact, complete_draft)
    accepted = builder.validate_semantic_draft(artifact, valid_replacement)
    assert len(accepted) == 1
    assert accepted[0].kind == "factor"
    assert artifact.core_obligations == [requirement]


def test_semantic_draft_rejects_unsupported_and_non_ai_condition_disposal(
    tmp_path: Path,
) -> None:
    """不支持动作和非AI条件都不能删除程序冻结的覆盖分母。

    Args:
        tmp_path: 用于构造通用源码扫描基线的隔离路径。

    Returns:
        None；两种绕过均被稳定校验错误拒绝时结束。

    Side Effects:
        无；仅构造内存程序分析和语义草稿。
    """

    artifact = _semantic_input_artifact(tmp_path)
    gap = artifact.semantic_gaps[0]
    unsupported = _semantic_draft(
        artifact,
        [
            CaseSemanticResolution(
                gap_id=gap.gap_id,
                condition_id=gap.condition_id,
                action="UNSUPPORTED",
                reason="当前没有可验证的类型化处理方式。",
            )
        ],
    )
    program_owned_artifact = artifact.model_copy(
        update={
            "conditions": [
                artifact.conditions[0].model_copy(
                    update={"resolution_owner": CaseConditionResolutionOwner.PROGRAM}
                )
            ]
        }
    )
    replacement = _semantic_draft(
        program_owned_artifact,
        [
            CaseSemanticResolution(
                gap_id=gap.gap_id,
                condition_id=gap.condition_id,
                action="REPLACE_WITH_TYPED_OBLIGATION",
                obligation_kind="factor",
                title="金额分区",
                payload={"factor_path": "request.amount", "values": [1, 2]},
                reason="业务确认两个代表值。",
            )
        ],
    )

    builder = ProgramCaseAnalysisBuilder()
    with pytest.raises(
        KnowledgeValidationError,
        match="BLOCKED_UNSUPPORTED_CASE_CONDITION_RESOLUTION",
    ):
        builder.validate_semantic_draft(artifact, unsupported)
    with pytest.raises(KnowledgeValidationError, match="non-AI"):
        builder.validate_semantic_draft(program_owned_artifact, replacement)


def test_program_analysis_blocks_ambiguous_entry_implementation(tmp_path: Path) -> None:
    """入口接口存在两个同签名实现时不得任意挑选一个作为程序真相。

    Args:
        tmp_path: 用于构造通用源码基线的隔离路径。

    Returns:
        None；Artifact明确返回入口方法歧义且列出两个候选symbol时通过。

    Side Effects:
        无；仅在内存构造不含真实业务名的语义scan。
    """

    manifest = _manifest(tmp_path)
    entry_method_name = "submit"
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="javaparser-symbol-solver",
        analyzer_version="test-case-evidence",
        system_id=SYSTEM_ID,
        methods=[
            _semantic_method("sample.FirstSubmitFacadeImpl", entry_method_name),
            _semantic_method("sample.SecondSubmitFacadeImpl", entry_method_name),
        ],
    )

    catalog = ProgramCaseAnalysisBuilder().build(manifest.model_copy(update={"semantic_analysis": semantic}))

    artifact = catalog.artifacts[0]
    assert artifact.status == "BLOCKED"
    assert artifact.issues[0].code == "BLOCKED_ENTRY_METHOD_AMBIGUOUS"
    assert artifact.issues[0].subject_ids == [method.symbol_id for method in semantic.methods]


def test_program_analysis_preserves_proven_core_and_deduplicates_semantic_gap(tmp_path: Path) -> None:
    """程序证据应生成不可删除核心义务并按同一字段影响去重语义缺口。

    Args:
        tmp_path: 用于构造通用源码基线的隔离路径。

    Returns:
        None；Decision、Boundary、Sequence保持program来源且重复计算影响只留一个Gap时通过。

    Side Effects:
        无；不读取规则、AI、知识文件或QA。
    """

    manifest = _manifest(tmp_path)
    method = _semantic_method("sample.SubmitFacadeImpl", "submit")
    source_ref = method.source_ref
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="javaparser-symbol-solver",
        analyzer_version="test-case-evidence",
        system_id=SYSTEM_ID,
        methods=[method],
        case_evidence=[
            SemanticCaseEvidence(
                evidence_id="sample:decision:1",
                method_symbol_id=method.symbol_id,
                kind="decision",
                field_paths=["request.mode"],
                condition="request.mode == 'FAST'",
                outcomes=["TRUE", "FALSE"],
                binding_kind="method_parameter",
                source_ref=source_ref,
            ),
            SemanticCaseEvidence(
                evidence_id="sample:collection:1",
                method_symbol_id=method.symbol_id,
                kind="field_influence",
                field_paths=["request.items"],
                influence_kind="collection_iteration",
                binding_kind="method_parameter",
                source_ref=source_ref,
            ),
            SemanticCaseEvidence(
                evidence_id="sample:calculation:1",
                method_symbol_id=method.symbol_id,
                kind="field_influence",
                field_paths=["request.amount"],
                influence_kind="calculation",
                binding_kind="method_parameter",
                source_ref=source_ref,
            ),
            SemanticCaseEvidence(
                evidence_id="sample:calculation:2",
                method_symbol_id=method.symbol_id,
                kind="field_influence",
                field_paths=["request.amount"],
                influence_kind="calculation",
                binding_kind="method_parameter",
                source_ref=source_ref.model_copy(update={"line": 12}),
            ),
            SemanticCaseEvidence(
                evidence_id="sample:sequence:1",
                method_symbol_id=method.symbol_id,
                kind="sequence",
                operation_ids=["sample.Validator#validate()", "sample.Repository#save()"],
                control_flow_path=["block:10"],
                binding_kind="same_path_resolved_calls",
                source_ref=source_ref,
            ),
        ],
    )

    catalog = ProgramCaseAnalysisBuilder().build(manifest.model_copy(update={"semantic_analysis": semantic}))

    artifact = catalog.artifacts[0]
    assert artifact.status == "ANALYZED"
    assert {obligation.kind for obligation in artifact.core_obligations} == {
        "boundary",
        "decision",
        "requirement",
        "sequence",
    }
    assert {obligation.origin for obligation in artifact.core_obligations} == {"program"}
    assert len(artifact.semantic_gaps) == 1
    assert artifact.semantic_gaps[0].evidence_ids == ["sample:calculation:1"]
    assert {item.binding_kind for item in artifact.evidence if item.field_paths} == {"entry_parameter"}


def test_unresolved_collection_multi_fields_receive_distinct_condition_ids(
    tmp_path: Path,
) -> None:
    """同一未解析集合证据绑定多个入口字段时应形成可分别确认的稳定条件。

    Args:
        tmp_path: 用于构造通用源码基线的隔离路径。

    Returns:
        None；两个Gap各自引用唯一AI条件且程序目录可正常构建时通过。
    """

    artifact = _multi_field_unresolved_artifact(tmp_path, "collection_iteration")

    condition_ids = [gap.condition_id for gap in artifact.semantic_gaps]
    assert artifact.status == "ANALYZED"
    assert len(condition_ids) == 2
    assert len(set(condition_ids)) == 2
    assert set(condition_ids) == {item.condition_id for item in artifact.conditions}


def test_unresolved_calculation_multi_fields_support_exact_resolutions(
    tmp_path: Path,
) -> None:
    """多字段计算缺口必须允许AI逐Gap提交互不借用的typed替换。

    Args:
        tmp_path: 用于构造通用源码基线的隔离路径。

    Returns:
        None；两个Resolution精确绑定各自条件并共同通过校验时结束。
    """

    artifact = _multi_field_unresolved_artifact(tmp_path, "calculation")
    fields = ["request.amount", "request.fee"]
    resolutions = [
        CaseSemanticResolution(
            gap_id=gap.gap_id,
            condition_id=gap.condition_id,
            action="REPLACE_WITH_TYPED_OBLIGATION",
            obligation_kind="factor",
            title=f"{field_path}业务分区",
            payload={"factor_path": field_path, "values": ["LOW", "HIGH"]},
            reason="该入口字段影响计算结果，需要两个确定性代表分区。",
        )
        for gap, field_path in zip(artifact.semantic_gaps, fields, strict=True)
    ]

    accepted_obligations = ProgramCaseAnalysisBuilder().validate_semantic_draft(
        artifact,
        _semantic_draft(artifact, resolutions),
    )

    assert len(accepted_obligations) == 2
    assert {item.factor_path for item in accepted_obligations} == set(fields)
    assert len({gap.condition_id for gap in artifact.semantic_gaps}) == 2


def test_reachable_method_parameter_never_becomes_entry_request_field(tmp_path: Path) -> None:
    """查询结果与入口子对象传入helper但无传播证明时只保留内部诊断。

    Args:
        tmp_path: 用于构造通用源码基线的隔离路径。

    Returns:
        None；内部字段不进入Entry字段目录、覆盖分母或强制AI任务时通过。

    Side Effects:
        无；仅验证Java证据到程序分析的可信提升边界。
    """

    manifest = _manifest(tmp_path)
    entry_method = _semantic_method("sample.SubmitFacadeImpl", "submit")
    query_helper = _semantic_method("sample.SubmitService", "checkRecord").model_copy(
        update={
            "symbol_id": "sample.SubmitService#checkRecord(sample.QueryRecord)",
            "parameter_names": ["record"],
            "parameter_types": ["QueryRecord"],
            "parameter_qualified_types": ["sample.QueryRecord"],
            "owner_interfaces": [],
            "entry_point_ids": [entry_method.symbol_id],
        }
    )
    child_helper = _semantic_method("sample.SubmitService", "checkChild").model_copy(
        update={
            "symbol_id": "sample.SubmitService#checkChild(sample.ChildRequest)",
            "parameter_names": ["child"],
            "parameter_types": ["ChildRequest"],
            "parameter_qualified_types": ["sample.ChildRequest"],
            "owner_interfaces": [],
            "entry_point_ids": [entry_method.symbol_id],
        }
    )
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="javaparser-symbol-solver",
        analyzer_version="test-case-evidence",
        system_id=SYSTEM_ID,
        methods=[entry_method, query_helper, child_helper],
        case_evidence=[
            SemanticCaseEvidence(
                evidence_id="sample:query-record-decision:1",
                method_symbol_id=query_helper.symbol_id,
                kind="decision",
                field_paths=["record.status"],
                condition="record.status == 'ACTIVE'",
                outcomes=["TRUE", "FALSE"],
                binding_kind="method_parameter",
                source_ref=query_helper.source_ref,
            ),
            SemanticCaseEvidence(
                evidence_id="sample:child-calculation:1",
                method_symbol_id=child_helper.symbol_id,
                kind="field_influence",
                field_paths=["child.rate"],
                influence_kind="calculation",
                binding_kind="method_parameter",
                source_ref=child_helper.source_ref,
            )
        ],
    )

    catalog = ProgramCaseAnalysisBuilder().build(manifest.model_copy(update={"semantic_analysis": semantic}))

    artifact = catalog.artifacts[0]
    assert artifact.status == "ANALYZED"
    assert artifact.fields == []
    assert artifact.core_obligations == []
    assert artifact.semantic_gaps == []
    assert {condition.condition_type.value for condition in artifact.conditions} == {
        "INTERNAL_DIAGNOSTIC"
    }
    assert all(not condition.blocks_generation for condition in artifact.conditions)
    assert {item.binding_kind for item in artifact.evidence} == {"method_parameter"}


def test_unbound_collection_loop_is_internal_diagnostic(tmp_path: Path) -> None:
    """查询或局部计算得到的集合循环不得扩大入口覆盖分母。

    Args:
        tmp_path: 用于构造通用源码基线的隔离路径。

    Returns:
        None；无入口字段的真实循环只形成不阻塞的内部诊断时通过。

    Side Effects:
        无；不生成Case且不访问数据源。
    """

    manifest = _manifest(tmp_path)
    entry_method = _semantic_method("sample.SubmitFacadeImpl", "submit")
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="javaparser-symbol-solver",
        analyzer_version="test-case-evidence",
        system_id=SYSTEM_ID,
        methods=[entry_method],
        case_evidence=[
            SemanticCaseEvidence(
                evidence_id="sample:local-record-loop:1",
                method_symbol_id=entry_method.symbol_id,
                kind="field_influence",
                influence_kind="collection_iteration",
                operation_ids=["sample.RecordProcessor#process(sample.Record)"],
                binding_kind="unbound",
                gap_reason="collection_input_source_unresolved",
                source_ref=entry_method.source_ref,
            )
        ],
    )

    artifact = ProgramCaseAnalysisBuilder().build(
        manifest.model_copy(update={"semantic_analysis": semantic})
    ).artifacts[0]

    assert artifact.fields == []
    assert artifact.core_obligations == []
    assert artifact.semantic_gaps == []
    assert [condition.condition_type.value for condition in artifact.conditions] == [
        "INTERNAL_DIAGNOSTIC"
    ]
    assert artifact.operations == []


def test_helper_method_error_response_downstream_call_is_internal_diagnostic(
    tmp_path: Path,
) -> None:
    """AbstractFacade方法参数不得冒充入口字段并升级为业务覆盖分区。

    Args:
        tmp_path: 用于构造通用退款Facade扫描基线的隔离路径。

    Returns:
        None；真实helper参数形状的createErrorResponse调用仅保留非阻塞诊断时通过。

    Side Effects:
        无；只在内存复现真实方法形状和downstream_call证据。
    """

    manifest = _manifest(tmp_path)
    entry_method = _semantic_method("sample.SubmitFacadeImpl", "submit")
    error_method = _semantic_method("com.ly.flight.chainsaas.refund.facade.impl.AbstractFacade", "createErrorResponse").model_copy(
        update={
            "symbol_id": (
                "com.ly.flight.chainsaas.refund.facade.impl.AbstractFacade"
                "#createErrorResponse(Request,APIException,Class<Response>)"
            ),
            "parameter_names": ["request", "exception", "responseType"],
            "parameter_types": ["Request", "APIException", "Class<Response>"],
            "parameter_qualified_types": [
                "sample.Request",
                "sample.APIException",
                "java.lang.Class",
            ],
            "owner_interfaces": [],
            "entry_point_ids": [entry_method.symbol_id],
        }
    )
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="javaparser-symbol-solver",
        analyzer_version="test-case-evidence",
        system_id=SYSTEM_ID,
        methods=[entry_method, error_method],
        case_evidence=[
            SemanticCaseEvidence(
                evidence_id="refund:create-error-response:downstream:1",
                method_symbol_id=error_method.symbol_id,
                kind="field_influence",
                field_paths=["errorCode", "message"],
                influence_kind="downstream_call",
                operation_ids=["sample.ResponseFactory#createErrorResponse()"],
                binding_kind="method_parameter",
                gap_reason="downstream_operation_unresolved",
                source_ref=error_method.source_ref,
                resolution_status="partial",
            )
        ],
    )

    artifact = ProgramCaseAnalysisBuilder().build(
        manifest.model_copy(update={"semantic_analysis": semantic})
    ).artifacts[0]

    assert artifact.semantic_gaps == []
    assert artifact.core_obligations == []
    assert [condition.condition_type.value for condition in artifact.conditions] == [
        "INTERNAL_DIAGNOSTIC"
    ]
    assert artifact.conditions[0].blocks_generation is False


def test_entry_matching_requires_resolved_concrete_method_body(tmp_path: Path) -> None:
    """接口声明、partial实现和未解析接口归属都不能冒充可分析入口实现。

    Args:
        tmp_path: 用于构造三类通用scan基线的隔离路径。

    Returns:
        None；三个Catalog均返回具体实现缺失阻塞时通过。

    Side Effects:
        无；全部匹配发生在内存。
    """

    manifest = _manifest(tmp_path)
    interface_method = _semantic_method("sample.SubmitFacade", "submit").model_copy(
        update={
            "owner_interfaces": [],
            "owner_type_kind": "interface",
            "has_executable_body": False,
        }
    )
    partial_implementation = _semantic_method("sample.SubmitFacadeImpl", "submit").model_copy(
        update={"resolution_status": SemanticResolutionStatus.PARTIAL}
    )
    unresolved_interface_implementation = _semantic_method(
        "sample.SubmitFacadeImpl",
        "submit",
    ).model_copy(update={"owner_interfaces": ["SubmitFacade"]})
    method_sets = [
        [interface_method],
        [interface_method, partial_implementation],
        [interface_method, unresolved_interface_implementation],
    ]

    artifacts = [
        ProgramCaseAnalysisBuilder().build(
            manifest.model_copy(
                update={
                    "semantic_analysis": SemanticAnalysisResult(
                        schema_version=5,
                        analyzer="javaparser-symbol-solver",
                        analyzer_version="test-case-evidence",
                        system_id=SYSTEM_ID,
                        methods=methods,
                    )
                }
            )
        ).artifacts[0]
        for methods in method_sets
    ]

    assert {artifact.status for artifact in artifacts} == {"BLOCKED"}
    assert {artifact.issues[0].code for artifact in artifacts} == {
        "BLOCKED_ENTRY_IMPLEMENTATION_MISSING"
    }


def test_program_artifact_rejects_dangling_or_mismatched_gap_references(tmp_path: Path) -> None:
    """SemanticGap必须引用真实证据和同ID的program Requirement。

    Args:
        tmp_path: 用于构造通用源码引用的隔离路径。

    Returns:
        None；悬空证据、非Requirement和不一致gap ID均被模型拒绝时通过。

    Side Effects:
        无；只执行Pydantic引用完整性校验。
    """

    manifest = _manifest(tmp_path)
    evidence = SemanticCaseEvidence(
        evidence_id="sample:calculation:valid",
        method_symbol_id="sample.SubmitFacadeImpl#submit(sample.SubmitRequest)",
        kind="field_influence",
        field_paths=["request.amount"],
        influence_kind="calculation",
        binding_kind="entry_parameter",
        source_ref=SourceReference(path="src/main/java/sample/SubmitFacadeImpl.java", line=10),
    )
    requirement = RequirementObligation(
        obligation_id="obligation:program:0001:0001",
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        title="程序影响待语义分区",
        origin="program",
        requirement_id="semantic-gap:program:0001:0001",
        statement="金额影响计算结果。",
    )
    valid_gap = ProgramSemanticGap(
        gap_id=requirement.requirement_id,
        requirement_obligation_id=requirement.obligation_id,
        evidence_ids=[evidence.evidence_id],
        reason_code="BLOCKED_FIELD_PARTITION_REQUIRED",
        message="需要确定业务分区。",
    )
    base = {
        "artifact_id": f"program-analysis:{manifest.scan_id}:0001",
        "system_id": SYSTEM_ID,
        "source_scan_id": manifest.scan_id,
        "source_baseline": manifest.baseline,
        "entry_id": ENTRY_ID,
        "status": "ANALYZED",
        "evidence": [evidence],
    }
    decision = DecisionObligation(
        obligation_id=requirement.obligation_id,
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        title="分支",
        origin="program",
        condition="request.mode == 'FAST'",
        outcomes=["TRUE", "FALSE"],
    )

    with pytest.raises(ValueError, match="unknown program evidence"):
        ProgramCaseAnalysisArtifact(
            **base,
            core_obligations=[requirement],
            semantic_gaps=[valid_gap.model_copy(update={"evidence_ids": ["missing-evidence"]})],
        )
    with pytest.raises(ValueError, match="program requirement"):
        ProgramCaseAnalysisArtifact(
            **base,
            core_obligations=[decision],
            semantic_gaps=[valid_gap],
        )
    with pytest.raises(ValueError, match="must match"):
        ProgramCaseAnalysisArtifact(
            **base,
            core_obligations=[requirement],
            semantic_gaps=[valid_gap.model_copy(update={"gap_id": "semantic-gap:program:0001:9999"})],
        )


def test_effect_evidence_requires_unique_verified_operation_binding(tmp_path: Path) -> None:
    """外部副作用候选只有唯一DSF绑定时才能成为RPC Effect。

    Args:
        tmp_path: 用于构造通用源码基线和DSF证据路径的隔离目录。

    Returns:
        None；无绑定和歧义绑定形成Gap，唯一绑定形成Effect时通过。

    Side Effects:
        无；不连接DSF注册中心或QA。
    """

    manifest = _manifest(tmp_path)
    entry_method = _semantic_method("sample.SubmitFacadeImpl", "submit")
    operation_target = "sample.ExternalFacade#submit(sample.SubmitRequest)"
    effect_evidence = SemanticCaseEvidence(
        evidence_id="sample:external-effect:1",
        method_symbol_id=entry_method.symbol_id,
        kind="effect",
        operation_ids=[operation_target],
        effect_kind="unknown",
        effect_target=operation_target,
        binding_kind="resolved_external_operation",
        gap_reason="operation_effect_binding_required",
        source_ref=entry_method.source_ref,
    )
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="javaparser-symbol-solver",
        analyzer_version="test-case-evidence",
        system_id=SYSTEM_ID,
        methods=[entry_method],
        case_evidence=[effect_evidence],
    )
    source_ref = SourceReference(path="src/main/java/sample/ExternalFacade.java", line=10)
    first_operation = DsfOperationDefinition(
        operation_id="dsf:sample-provider:submit-v1",
        provider_system_id="sample-provider",
        gs_name="sample-provider",
        service_name="sample.ExternalFacade",
        version="1.0.0",
        action="submit",
        request_type="sample.SubmitRequest",
        source_refs=[source_ref],
    )
    second_operation = first_operation.model_copy(
        update={
            "operation_id": "dsf:sample-provider:submit-v2",
            "version": "2.0.0",
        }
    )
    builder = ProgramCaseAnalysisBuilder()
    unbound = builder.build(
        manifest.model_copy(update={"semantic_analysis": semantic})
    ).artifacts[0]
    uniquely_bound = builder.build(
        manifest.model_copy(
            update={
                "semantic_analysis": semantic,
                "dsf_operations": [first_operation],
            }
        )
    ).artifacts[0]
    ambiguous = builder.build(
        manifest.model_copy(
            update={
                "semantic_analysis": semantic,
                "dsf_operations": [first_operation, second_operation],
            }
        )
    ).artifacts[0]

    assert [item.kind for item in unbound.core_obligations] == ["requirement"]
    assert unbound.semantic_gaps[0].reason_code == "BLOCKED_EFFECT_BINDING_REQUIRED"
    assert [item.kind for item in uniquely_bound.core_obligations] == ["effect"]
    assert uniquely_bound.effect_targets[0].target == first_operation.operation_id
    assert uniquely_bound.evidence[0].effect_kind == "rpc"
    assert uniquely_bound.evidence[0].effect_target == first_operation.operation_id
    assert uniquely_bound.semantic_gaps == []
    assert [item.kind for item in ambiguous.core_obligations] == ["requirement"]
    assert ambiguous.semantic_gaps[0].reason_code == "BLOCKED_EFFECT_BINDING_REQUIRED"
    assert ambiguous.effect_targets == []


def test_retired_case_generation_routes_are_absent_without_writes(tmp_path: Path) -> None:
    """历史类型化编译和Hybrid编排路由必须移除且不得留下资产。

    Args:
        tmp_path: Pytest隔离的注册系统和知识目录。

    Returns:
        None；两个历史入口均不存在且未创建旧Case目录时通过。

    Side Effects:
        只在隔离知识目录注册一个通用系统；不会生成Case或访问QA。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    baseline = SourceBaseline(source_path=str(source_root), commit="sample-commit")
    application = OpenTestApplication(tmp_path / "knowledge")
    application.store.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="示例系统", source_path=str(source_root), baseline=baseline)
    )
    compile_payload = {
        "manifest": {
            "system_id": SYSTEM_ID,
            "entry_id": ENTRY_ID,
            "source_scan_id": "scan-sample",
            "status": "FROZEN",
        },
        "base_execution_graph": ["ACTION"],
    }
    hybrid_payload = {
        "entry_id": ENTRY_ID,
        "action_capability_id": "capability:sample.action",
        "data_setup_recipe_id": "recipe:sample.setup",
        "cleanup_plan_id": "cleanup:sample.resource",
    }

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        compile_response = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/typed-case-compilations",
            json=compile_payload,
        )
        hybrid_response = client.post(
            f"/api/v3/systems/{SYSTEM_ID}/case-generations",
            json=hybrid_payload,
        )

    assert compile_response.status_code == 404
    assert hybrid_response.status_code == 404
    assert not (application.store.system_root(SYSTEM_ID) / "cases" / "v3").exists()


def _manifest(tmp_path: Path) -> ScanManifest:
    """构造不含真实业务名称的单Entry扫描Manifest。

    Args:
        tmp_path: 通用源码根路径。

    Returns:
        固定scan、baseline和Facade Entry的最小Manifest。
    """

    baseline = SourceBaseline(source_path=str(tmp_path / "source"), commit="sample-commit")
    return ScanManifest(
        scan_id="scan-20260827020000-sample-00000001",
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=ENTRY_ID,
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.FACADE,
                display_name="SubmitFacade#submit",
                source_id="sample.SubmitFacade#submit",
                source_path="src/main/java/sample/SubmitFacade.java",
            )
        ],
    )


def _blocked_catalog(manifest: ScanManifest) -> ProgramCaseAnalysisCatalog:
    """为bundle存储测试构造显式BLOCKED而非空成功的Program Catalog。

    Args:
        manifest: Catalog必须精确绑定的通用Manifest。

    Returns:
        唯一Entry含分析器不可用Issue的合法Catalog。
    """

    return ProgramCaseAnalysisCatalog(
        system_id=manifest.system_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        artifacts=[
            ProgramCaseAnalysisArtifact(
                artifact_id=f"program-analysis:{manifest.scan_id}:0001",
                system_id=manifest.system_id,
                source_scan_id=manifest.scan_id,
                source_baseline=manifest.baseline,
                entry_id=ENTRY_ID,
                status="BLOCKED",
                issues=[
                    ProgramAnalysisIssue(
                        code="BLOCKED_PROGRAM_ANALYZER_UNAVAILABLE",
                        message="测试显式验证阻塞bundle。",
                    )
                ],
            )
        ],
    )


def _semantic_method(qualified_class_name: str, method_name: str) -> SemanticMethodDefinition:
    """构造一个由Facade接口拥有且参数签名完整的通用实现方法。

    Args:
        qualified_class_name: 具体实现类FQN。
        method_name: 入口方法名。

    Returns:
        可参与唯一Entry映射的resolved Java方法定义。
    """

    symbol_id = f"{qualified_class_name}#{method_name}(sample.SubmitRequest)"
    return SemanticMethodDefinition(
        symbol_id=symbol_id,
        qualified_class_name=qualified_class_name,
        method_name=method_name,
        parameter_names=["request"],
        parameter_types=["SubmitRequest"],
        parameter_qualified_types=["sample.SubmitRequest"],
        return_type="void",
        owner_interfaces=["sample.SubmitFacade"],
        owner_type_kind="class",
        has_executable_body=True,
        source_ref=SourceReference(
            path=f"src/main/java/{qualified_class_name.replace('.', '/')}.java",
            symbol=symbol_id,
            line=10,
        ),
        entry_point_ids=[symbol_id],
        resolution_status=SemanticResolutionStatus.RESOLVED,
    )


def _semantic_draft(
    artifact: ProgramCaseAnalysisArtifact,
    resolutions: list[CaseSemanticResolution],
) -> CaseSemanticDraft:
    """构造精确绑定一个Program Artifact的通用Semantic Draft。

    Args:
        artifact: Draft作用域来源。
        resolutions: 待验证的完整或不完整Resolution集合。

    Returns:
        不包含真实业务或客户端最终义务身份的草稿。
    """

    return CaseSemanticDraft(
        draft_id="case-semantic-draft-11111111111111111111",
        system_id=artifact.system_id,
        source_scan_id=artifact.source_scan_id,
        analysis_artifact_id=artifact.artifact_id,
        entry_id=artifact.entry_id,
        resolutions=resolutions,
    )


def _multi_field_unresolved_artifact(
    tmp_path: Path,
    influence_kind: str,
) -> ProgramCaseAnalysisArtifact:
    """用一条真实入口证据构造两个字段共享来源的未解析Program Artifact。

    Args:
        tmp_path: 通用源码Manifest使用的隔离路径。
        influence_kind: 本次证据的集合迭代或计算影响类型。

    Returns:
        由正式Builder生成且每个入口字段均形成独立Gap的分析资产。
    """

    manifest = _manifest(tmp_path)
    method = _semantic_method("sample.SubmitFacadeImpl", "submit")
    field_paths = (
        ["request.items", "request.moreItems"]
        if influence_kind == "collection_iteration"
        else ["request.amount", "request.fee"]
    )
    evidence = SemanticCaseEvidence(
        evidence_id=f"sample:multi-field:{influence_kind}",
        method_symbol_id=method.symbol_id,
        kind="field_influence",
        field_paths=field_paths,
        influence_kind=influence_kind,
        binding_kind="method_parameter",
        resolution_status=SemanticResolutionStatus.UNRESOLVED,
        source_ref=method.source_ref,
    )
    semantic = SemanticAnalysisResult(
        schema_version=5,
        analyzer="javaparser-symbol-solver",
        analyzer_version="test-multi-field-condition-id",
        system_id=SYSTEM_ID,
        methods=[method],
        case_evidence=[evidence],
    )

    return ProgramCaseAnalysisBuilder().build(
        manifest.model_copy(update={"semantic_analysis": semantic})
    ).artifacts[0]


def _semantic_input_artifact(tmp_path: Path) -> ProgramCaseAnalysisArtifact:
    """构造一个只能由精确AI类型化替换关闭的入口字段计算缺口。

    Args:
        tmp_path: 用于构造通用源码扫描基线的隔离路径。

    Returns:
        带一个Program Requirement、AI条件和对应Semantic Gap的分析资产。
    """

    manifest = _manifest(tmp_path)
    evidence = SemanticCaseEvidence(
        evidence_id="sample:calculation:typed",
        method_symbol_id="sample.SubmitFacadeImpl#submit(sample.SubmitRequest)",
        kind="field_influence",
        field_paths=["request.amount"],
        influence_kind="calculation",
        binding_kind="entry_parameter",
        source_ref=SourceReference(
            path="src/main/java/sample/SubmitFacadeImpl.java",
            line=10,
        ),
    )
    gap_id = "semantic-gap:program:0001:0001"
    condition_id = "condition:program:0001:calculation"
    requirement = RequirementObligation(
        obligation_id="obligation:program:0001:0001",
        system_id=SYSTEM_ID,
        entry_id=ENTRY_ID,
        title="程序影响待语义分区",
        origin="program",
        requirement_id=gap_id,
        statement="入口金额影响计算结果。",
    )
    condition = CaseCondition(
        condition_id=condition_id,
        condition_type=CaseConditionType.INPUT_COVERAGE,
        title="金额影响待业务分区",
        summary="入口金额影响计算，但业务取值仍需确认。",
        evidence_ids=[evidence.evidence_id],
        source_refs=[evidence.source_ref],
        resolution_owner=CaseConditionResolutionOwner.AI,
        blocks_generation=True,
        technical_code="BLOCKED_FIELD_PARTITION_REQUIRED",
    )
    return ProgramCaseAnalysisArtifact(
        artifact_id=f"program-analysis:{manifest.scan_id}:0001",
        system_id=SYSTEM_ID,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        entry_id=ENTRY_ID,
        status="ANALYZED",
        evidence=[evidence],
        core_obligations=[requirement],
        conditions=[condition],
        semantic_gaps=[
            ProgramSemanticGap(
                gap_id=gap_id,
                condition_id=condition_id,
                requirement_obligation_id=requirement.obligation_id,
                evidence_ids=[evidence.evidence_id],
                reason_code="BLOCKED_FIELD_PARTITION_REQUIRED",
                message="需要确定业务分区。",
            )
        ],
    )
