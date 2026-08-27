"""验证分型覆盖义务、双层Case规则和只读预览API。"""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.case_rules import CaseRuleEvaluationContext, CaseRuleResolver
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.application.foundation import OpenTestApplication
from opentest.domain.models import (
    BoundaryObligation,
    CaseRuleDocument,
    EntryPoint,
    KnowledgeNodeKind,
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


def test_resolver_emits_all_typed_obligations_and_preserves_effect_kind() -> None:
    """一条结构化规则应冻结七类义务并保留扫描发现的MQ副作用类型。

    Returns:
        None；全部义务均按判别字段解析且清单冻结时通过。
    """

    document = CaseRuleDocument.model_validate(
        {
            "rules": [
                {
                    "rule_id": "system.complete-coverage",
                    "description": "覆盖全部义务类型",
                    "match": {"entry_patterns": [ENTRY_ID], "effect_kinds": ["mq"]},
                    "emissions": [
                        {
                            "emission_id": "factor",
                            "kind": "factor",
                            "title": "处理模式",
                            "target": "processMode",
                            "values": ["FAST", "SAFE"],
                        },
                        {
                            "emission_id": "boundary",
                            "kind": "boundary",
                            "title": "条目数量",
                            "target": "items",
                            "values": ["EMPTY", "SINGLE", "MULTIPLE"],
                        },
                        {
                            "emission_id": "decision",
                            "kind": "decision",
                            "title": "路由分支",
                            "condition": "processMode == FAST",
                            "outcomes": ["TRUE", "FALSE"],
                        },
                        {
                            "emission_id": "sequence",
                            "kind": "sequence",
                            "title": "状态门控",
                            "sequence": ["VALIDATED", "SUBMITTED"],
                        },
                        {
                            "emission_id": "fault",
                            "kind": "fault_injection",
                            "title": "中间条目失败",
                            "target": "sample.processItem",
                            "values": ["MIDDLE"],
                            "expected_states": {
                                "previous_entities": "SUCCESS",
                                "current_entity": "FAILED",
                                "remaining_entities": "NOT_EXECUTED",
                            },
                        },
                        {
                            "emission_id": "effect",
                            "kind": "effect",
                            "title": "提交消息",
                            "target": "$matched_effect",
                            "effect_kind": "database",
                            "observation": "观察Submitted消息",
                        },
                        {
                            "emission_id": "requirement",
                            "kind": "requirement",
                            "title": "产品条款",
                            "requirement_id": "PRD-SAMPLE-1",
                            "statement": "SAFE模式使用独立的确定性计算公式",
                        },
                    ],
                }
            ]
        }
    )
    context = CaseRuleEvaluationContext(
        system_id=SYSTEM_ID,
        source_scan_id="scan-typed-rules",
        entry=_entry(),
        effect_targets=(("mq", "SubmittedTopic"),),
    )

    preview = CaseRuleResolver(document).preview(context)

    assert preview.manifest.status == "FROZEN"
    assert {item.kind for item in preview.manifest.obligations} == {
        "factor",
        "boundary",
        "decision",
        "sequence",
        "fault_injection",
        "effect",
        "requirement",
    }
    effect = next(item for item in preview.manifest.obligations if item.kind == "effect")
    assert effect.effect_kind == "mq"


def test_system_rules_override_same_identity_accumulate_others_and_block_conflicts() -> None:
    """系统同ID规则应覆盖全局版本，其余规则累加，互斥要求冲突时必须阻塞。

    Returns:
        None；来源、义务值和冲突状态均符合双层规则契约时通过。
    """

    global_rules = CaseRuleDocument.model_validate(
        {
            "rules": [
                _factor_rule("request.items", [1], "global.item-count"),
                _factor_rule("processMode", ["FAST"], "global.process-mode", exclusive=True),
            ]
        }
    )
    system_rules = CaseRuleDocument.model_validate(
        {
            "rules": [
                _factor_rule("request.items", [1, 2], "global.item-count"),
                _factor_rule("itemType", ["PRIMARY", "SECONDARY"], "system.item-type"),
                _factor_rule("processMode", ["SAFE"], "system.process-mode", exclusive=True),
            ]
        }
    )

    preview = CaseRuleResolver(global_rules, system_rules).preview(
        CaseRuleEvaluationContext(system_id=SYSTEM_ID, source_scan_id="scan-layered", entry=_entry())
    )

    sources = {item.rule_id: item.source for item in preview.manifest.matched_rules}
    segment_obligation = next(
        item for item in preview.manifest.obligations if getattr(item, "factor_path", "") == "request.items"
    )
    assert sources["global.item-count"] == "system"
    assert sources["system.item-type"] == "system"
    assert segment_obligation.values == [1, 2]
    assert preview.manifest.status == "BLOCKED"
    assert preview.manifest.blockers[0].code == "BLOCKED_RULE_CONFLICT"
    assert preview.manifest.conflicts[0].conflict_key == "factor:processMode"


def test_case_rule_preview_api_loads_system_git_rules_without_ai_or_qa(tmp_path: Path) -> None:
    """预览API应从最新扫描和系统Git规则生成冻结清单且不调用执行路径。

    Args:
        tmp_path: Pytest提供的隔离源码与知识目录。

    Returns:
        None；HTTP响应包含系统规则来源和单/多航段义务时通过。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "SubmitFacade.java"
    source_file.write_text("interface SubmitFacade {}", encoding="utf-8")
    application = OpenTestApplication(tmp_path / "knowledge")
    baseline = SourceBaseline(source_path=str(source_root), commit="rule-api")
    application.store.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="示例系统", source_path=str(source_root), baseline=baseline)
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    scan_id, tool_root = artifacts.allocate(SYSTEM_ID, baseline)
    tool_root.mkdir(parents=True)
    entry = _entry().model_copy(
        update={
            "source_path": str(source_file),
            "request_type": "sample.SubmitRequest",
            "metadata": {
                # 即使metadata伪造字段影响，可信预览也只能使用独立Program Catalog。
                "case_analysis": {
                    "fields": [
                        {
                            "path": "forgedContacts",
                            "value_kind": "collection",
                            "influence_kinds": ["collection_iteration"],
                        }
                    ]
                },
            },
        }
    )
    entry_method_id = "sample.SubmitFacadeImpl#submit(sample.SubmitRequest)"
    manifest = ScanManifest(
        scan_id=scan_id,
        system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[entry],
        semantic_analysis=SemanticAnalysisResult(
            schema_version=5,
            analyzer="javaparser-symbol-solver",
            analyzer_version="test-case-evidence",
            system_id=SYSTEM_ID,
            methods=[
                SemanticMethodDefinition(
                    symbol_id=entry_method_id,
                    qualified_class_name="sample.SubmitFacadeImpl",
                    method_name="submit",
                    parameter_names=["request"],
                    parameter_types=["SubmitRequest"],
                    parameter_qualified_types=["sample.SubmitRequest"],
                    return_type="void",
                    owner_interfaces=["sample.SubmitFacade"],
                    owner_type_kind="class",
                    has_executable_body=True,
                    source_ref=SourceReference(path="src/main/java/sample/SubmitFacadeImpl.java", symbol=entry_method_id, line=10),
                    entry_point_ids=[entry_method_id],
                )
            ],
            case_evidence=[
                SemanticCaseEvidence(
                    evidence_id=f"{entry_method_id}:field_influence:11:9",
                    method_symbol_id=entry_method_id,
                    kind="field_influence",
                    field_paths=["items"],
                    influence_kind="collection_iteration",
                    operation_ids=["sample.ItemProcessor#process(java.lang.Object)"],
                    binding_kind="method_parameter",
                    source_ref=SourceReference(
                        path="src/main/java/sample/SubmitFacadeImpl.java",
                        symbol=f"{entry_method_id}:field_influence",
                        line=11,
                    ),
                    resolution_status=SemanticResolutionStatus.RESOLVED,
                )
            ],
        ),
        tool_root=str(tool_root),
    )
    catalog = ProgramCaseAnalysisBuilder().build(manifest)
    artifacts.write_scan_bundle(manifest, catalog)
    artifacts.publish_latest(SYSTEM_ID, scan_id)
    system_rule_path = application.store.system_root(SYSTEM_ID) / "case-rules" / "rules.yaml"
    system_rule_path.parent.mkdir(parents=True)
    system_rule_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "rules": [
                    _factor_rule(
                        "request.segments",
                        ["SINGLE", "MULTIPLE"],
                        "system.request-segments",
                    )
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.get(
            f"/api/v2/systems/{SYSTEM_ID}/case-rules/preview",
            params={"entry_id": ENTRY_ID},
        )

    assert response.status_code == 200
    manifest = response.json()["preview"]["manifest"]
    assert manifest["status"] == "FROZEN"
    system_rule = next(item for item in manifest["matched_rules"] if item["source"] == "system")
    assert system_rule["rule_id"] == "system.request-segments"
    system_obligation = next(
        item
        for item in manifest["obligations"]
        if item.get("factor_path") == "request.segments"
    )
    assert system_obligation["values"] == ["SINGLE", "MULTIPLE"]
    collection_boundary = next(
        item
        for item in manifest["obligations"]
        if item.get("boundary_mode") == "collection_cardinality"
    )
    assert collection_boundary["target_path"] == "items"
    assert all(item.get("target_path") != "forgedContacts" for item in manifest["obligations"])
    fault = next(item for item in manifest["obligations"] if item["kind"] == "fault_injection")
    assert fault["target_operation"] == "sample.ItemProcessor#process(java.lang.Object)"
    # 阶段1只冻结集合基数义务；阶段5必须等待可信元素来源，不能在这里伪造空对象实体。
    assert collection_boundary["boundaries"] == ["EMPTY", "SINGLE", "MULTIPLE"]


def _entry() -> EntryPoint:
    """构造规则解析测试共享的最小Facade入口。

    Returns:
        固定系统和入口身份的源码扫描对象。
    """

    return EntryPoint(
        entry_id=ENTRY_ID,
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        display_name="SubmitFacade#submit",
        source_id="sample.SubmitFacade#submit",
        source_path="src/main/java/sample/SubmitFacade.java",
    )


def _factor_rule(
    target: str,
    values: list[object],
    rule_id: str,
    exclusive: bool = False,
) -> dict[str, object]:
    """构造测试所需的结构化因素规则。

    Args:
        target: 规则产生义务的业务字段。
        values: 该字段必须覆盖的候选取值。
        rule_id: 分层合并使用的稳定规则ID。
        exclusive: 是否声明该目标的精确互斥要求。

    Returns:
        可直接交给Pydantic或YAML的规则字典。
    """

    return {
        "rule_id": rule_id,
        "description": f"覆盖{target}",
        "match": {"entry_patterns": [ENTRY_ID]},
        "emissions": [
            {
                "emission_id": "factor-values",
                "kind": "factor",
                "title": f"{target}取值",
                "target": target,
                "values": values,
                "exclusive": exclusive,
            }
        ],
    }
