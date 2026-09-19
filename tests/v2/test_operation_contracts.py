"""验证独立接口契约的知识解耦、证据边界及固定版本读取。"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.application.case_template_v4 import CaseTemplateV4RuntimeServices, CaseTemplateV4Service
from opentest.application.knowledge import KnowledgeGenerationService
from opentest.application.foundation import OpenTestApplication
from opentest.application.operation_contracts import (
    OperationContractService, OperationContractSupplement, OperationFieldSupplement, OperationResponseFieldSupplement,
)
from opentest.domain.errors import IdempotencyConflictError, KnowledgeValidationError
from opentest.domain.models import (
    DiscoveredResource, EntryPoint, KnowledgeConfirmation, KnowledgeNode, KnowledgeNodeKind,
    KnowledgeStatus, KnowledgeTargetStatus, KnowledgeToolIntentRequest,
    OperationCapability, OperationFieldEvidence,
    OperationKind, OperationMutability, ScanManifest, SemanticAnalysisResult,
    SemanticFieldDefinition, SemanticMethodDefinition, SemanticTypeDefinition, SourceReference,
    SystemDefinition, TaskRecord, TaskStatus, utc_now,
)


SYSTEM_ID = "contract-system"
SCAN_ID = "scan-contract-source"
OPERATION_ID = "facade:demo.RefundFacade#billSupplement"


def _service(tmp_path: Path) -> OperationContractService:
    """建立无知识节点的真实扫描文件及最小Operation目录。

    Args:
        tmp_path: Pytest隔离目录。
    Returns:
        使用真实契约存储和固定源码的服务；仅Operation目录及注册信息用桩提供。
    """

    # 用真实源码和Manifest验证存储/版本边界，避免仅mock契约即可让测试假通过。
    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "RefundFacade.java"
    source_file.write_text("package demo;\nclass RefundFacade {\n"
                           " void billSupplement(Request request) {\n"
                           "  if (request.id == null) throw new IllegalArgumentException();\n"
                           " }\n}\n", encoding="utf-8")
    evidence = SourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#billSupplement", line=3)
    baseline = GitSourceRepository().capture(source)
    entry = EntryPoint(entry_id=OPERATION_ID, system_id=SYSTEM_ID,
                       kind=KnowledgeNodeKind.FACADE, display_name="补单",
                       source_id="demo.RefundFacade#billSupplement", source_path="RefundFacade.java")
    manifest = ScanManifest(system_id=SYSTEM_ID, scan_id=SCAN_ID, baseline=baseline, entries=[entry],
        semantic_analysis=SemanticAnalysisResult(system_id=SYSTEM_ID, methods=[SemanticMethodDefinition(
            symbol_id="demo.RefundFacade#billSupplement(Request)", qualified_class_name="demo.RefundFacade",
            method_name="billSupplement", source_ref=evidence, has_executable_body=True,
            entry_point_ids=[OPERATION_ID],
        )]))
    artifacts = SourceScanArtifactStore(tmp_path / "knowledge")
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, SCAN_ID)
    schema = {"type": "object", "properties": {"id": {"type": "string"}, "state": {"type": "string"},
              "optional": {"type": "string"}}, "required": ["id", "optional"], "additionalProperties": False}
    operation = OperationCapability(operation_id=OPERATION_ID, system_id=SYSTEM_ID,
        business_name="补单", operation_summary="根据分销报表ID补单", kind=OperationKind.FACADE,
        mutability=OperationMutability.WRITE, input_schema=schema, publication_input_schema=schema,
        publication_output_schema={"type": "object", "properties": {"success": {"type": "boolean"}}},
        input_fields=[OperationFieldEvidence(field_path=name, field_name=name, declared_type="String",
                      documentation_required=name == "id", runtime_required=name == "optional")
                      for name in ("id", "state", "optional")], source_scan_id=SCAN_ID)
    store = Mock(root=tmp_path / "knowledge")
    store.get_system.return_value = Mock(source_path=str(source))
    store.list_nodes.return_value = []
    store.system_transaction.return_value = nullcontext()
    catalog = Mock()
    catalog.derive.return_value = [operation]
    return OperationContractService(store, artifacts, catalog)


def _supplement(description: str = "分销报表ID") -> OperationContractSupplement:
    """构造引用实际入口方法的业务ID与必填补充。

    Args:
        description: 本轮业务说明。
    Returns:
        只改变一个字段、不携带运行数据的补充请求。
    """

    return OperationContractSupplement(fields=[OperationFieldSupplement(
        path="id", description=description, business_identity=True, requirement_status="required",
        evidence_refs=[SourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#billSupplement", line=3)],
    )])


def _contract_application(tmp_path: Path) -> OpenTestApplication:
    """建立具有Facade和MQ消费者的真实应用及固定语义扫描。

    Args:
        tmp_path: Pytest提供的隔离源码和知识根。
    Returns:
        未生成历史知识的应用；目录、详情和契约均使用正式服务。
    """

    source = tmp_path / "source"
    source.mkdir()
    files = {
        "RefundFacade.java": "class RefundFacade {\n Reply billSupplement(Request request) { return null; }\n}\n",
        "Request.java": "class Request {\n String refundNo;\n}\n",
        "Reply.java": "class Reply {\n boolean success;\n}\n",
        "Listener.java": '@Component("refundListener")\nclass Listener {\n boolean process(Request message) { return true; }\n}\n',
    }
    for filename, content in files.items():
        (source / filename).write_text(content, encoding="utf-8")
    application = OpenTestApplication(tmp_path / "knowledge")
    application.initialize()
    application.register_system(SystemDefinition(system_id=SYSTEM_ID, name="退款契约系统", source_path=str(source)))
    method_ref = SourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#billSupplement", line=2)
    listener_ref = SourceReference(path="Listener.java", symbol="demo.Listener", line=2)
    baseline = GitSourceRepository().capture(source)
    # MQ仅有扫描资源和明确bean绑定，刻意不加入entries以覆盖合成目录目标。
    manifest = ScanManifest(system_id=SYSTEM_ID, scan_id=SCAN_ID, baseline=baseline, entries=[EntryPoint(
        entry_id=OPERATION_ID, system_id=SYSTEM_ID, kind="facade", display_name="退款补单",
        source_id="demo.RefundFacade#billSupplement", source_path=str(source / "RefundFacade.java"),
        request_type="demo.Request", response_type="demo.Reply",
    )], resources=[DiscoveredResource(
        resource_id="resource:refund:consumer", system_id=SYSTEM_ID, kind="mq", role="consumer",
        logical_name="refundConsumer", listener_ref="refundListener", nameserver_config_key="mq.servers",
        topic_config_key="mq.refund.topic", source_refs=[listener_ref],
    )], semantic_analysis=SemanticAnalysisResult(schema_version=4, system_id=SYSTEM_ID, types=[
        SemanticTypeDefinition(symbol_id="demo.Request", qualified_class_name="demo.Request", simple_name="Request",
            source_ref=SourceReference(path="Request.java", symbol="demo.Request", line=1),
            fields=[SemanticFieldDefinition(field_name="refundNo", declared_type="String",
                referenced_type="java.lang.String", javadoc_summary="退款单号",
                source_ref=SourceReference(path="Request.java", symbol="demo.Request#refundNo", line=2))]),
        SemanticTypeDefinition(symbol_id="demo.Reply", qualified_class_name="demo.Reply", simple_name="Reply",
            source_ref=SourceReference(path="Reply.java", symbol="demo.Reply", line=1),
            fields=[SemanticFieldDefinition(field_name="success", declared_type="boolean", referenced_type="boolean",
                javadoc_summary="是否成功", source_ref=SourceReference(path="Reply.java", symbol="demo.Reply#success", line=2))]),
        SemanticTypeDefinition(symbol_id="demo.Listener", qualified_class_name="demo.Listener", simple_name="Listener",
            javadoc_summary="处理退款完成通知", source_ref=listener_ref),
    ], methods=[
        SemanticMethodDefinition(symbol_id="demo.RefundFacade#billSupplement(demo.Request)",
            qualified_class_name="demo.RefundFacade", method_name="billSupplement",
            parameter_qualified_types=["demo.Request"], return_qualified_type="demo.Reply",
            has_executable_body=True, source_ref=method_ref, entry_point_ids=[OPERATION_ID],
            javadoc_summary="补建退款订单"),
        SemanticMethodDefinition(symbol_id="demo.Listener#process(demo.Request)", qualified_class_name="demo.Listener",
            method_name="process", parameter_qualified_types=["demo.Request"], has_executable_body=True,
            source_ref=SourceReference(path="Listener.java", symbol="demo.Listener#process(demo.Request)", line=3)),
    ]))
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(SYSTEM_ID, SCAN_ID)
    application.store.update_source_baseline(SYSTEM_ID, baseline)
    return application


def test_facade_detail_without_legacy_nodes_shows_purpose_and_response_updates(tmp_path: Path) -> None:
    """没有历史知识时直接展示接口契约，纯用途和纯响应补充均在详情生效。

    Args:
        tmp_path: 隔离的真实应用、源码和契约目录。
    Returns:
        None；目录状态和详情字段均跟随独立补充版本时通过。
    """

    application = _contract_application(tmp_path)
    detail = application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID)
    assert detail.published_nodes == []
    assert detail.latest_drafts == []
    assert detail.target.knowledge_status == KnowledgeTargetStatus.CODE_ONLY
    assert detail.operation_contract.operation_summary == "补建退款订单"
    assert detail.operation_contract.fields[0].path == "refundNo"
    assert detail.operation_contract.response_fields[0].path == "success"
    assert set(detail.operation_contract.response_schema["properties"]) == {"success"}
    # 两种独立提交都不需要输入字段改动，也不需要创建知识长文或后台任务。
    application.operation_contracts.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, OperationContractSupplement(
        operation_summary="按退款单号补建订单", summary_evidence_refs=detail.operation_contract.summary_evidence_refs,
    ))
    purpose_detail = application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID)
    assert purpose_detail.operation_contract.contract_revision == 1
    assert purpose_detail.operation_contract.operation_summary == "按退款单号补建订单"
    response_field = purpose_detail.operation_contract.response_fields[0]
    application.operation_contracts.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, OperationContractSupplement(
        response_fields=[OperationResponseFieldSupplement(path="success", description="本次补单是否成功",
                                                         evidence_refs=[response_field.source_ref])],
    ))
    response_detail = application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID)
    assert response_detail.operation_contract.contract_revision == 2
    assert response_detail.operation_contract.operation_summary == "按退款单号补建订单"
    assert response_detail.operation_contract.response_fields[0].description == "本次补单是否成功"
    assert response_detail.target.knowledge_status == KnowledgeTargetStatus.GENERATED
    assert response_detail.operation_contract.source_scan_id == SCAN_ID
    assert application.store.list_nodes(SYSTEM_ID) == []
    assert application.tasks.list_records(SYSTEM_ID) == []


def test_resource_only_mq_target_exposes_consumer_message_contract(tmp_path: Path) -> None:
    """仅由MQ资源发现的消费者可从目录打开并展示真实消息DTO字段。

    Args:
        tmp_path: 隔离的源码、固定资源扫描和应用存储。
    Returns:
        None；无旧entry的MQ目标仍拥有可用详情时通过。
    """

    application = _contract_application(tmp_path)
    operation_id = f"mq:{SYSTEM_ID}:refundconsumer"
    catalog = application.get_scan_catalog(SYSTEM_ID, "latest")
    target = next(item for item in catalog.targets if item.target_id == operation_id)
    assert target.category == "mq_consumer"
    assert catalog.counts["mq_consumer"] == 1
    assert target.knowledge_status == KnowledgeTargetStatus.CODE_ONLY
    # 从正式详情入口验证合成目录身份能反查同一消费者，而非只验证Operation内部投影。
    detail = application.get_knowledge_target_detail(SYSTEM_ID, operation_id)
    contract = detail.operation_contract
    assert contract.source_scan_id == SCAN_ID
    assert contract.operation_summary == "处理退款完成通知"
    assert contract.fields[0].path == "message.refundNo"
    assert contract.fields[0].description == "退款单号"
    assert contract.request_schema["properties"]["message"]["properties"]["refundNo"] == {"type": "string"}
    assert detail.published_nodes == []


@pytest.mark.parametrize("unrelated_binding", ["other_class_line", "unrelated_annotation"])
def test_mq_binding_rejects_other_class_or_unrelated_annotation(
    tmp_path: Path, unrelated_binding: str,
) -> None:
    """允许注解行定位后仍拒绝其他类型位置或非Spring注解制造的监听器绑定。

    Args:
        tmp_path: 隔离的源码、固定扫描和目录应用。
        unrelated_binding: 另一类的声明位置或无Spring含义的同值注解。
    Returns:
        None；不相关声明不会被投影为当前消费者DTO时通过。
    """

    application = _contract_application(tmp_path)
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read(SYSTEM_ID, SCAN_ID)
    source = Path(manifest.baseline.source_path)
    binding_source = (
        '@Component("refundListener")\nclass Other {}\n'
        '@Component("refundListener")\nclass Listener {\n boolean process(Request message) { return true; }\n}\n'
        if unrelated_binding == "other_class_line"
        else '@Tag("refundListener")\nclass Listener {\n boolean process(Request message) { return true; }\n}\n'
    )
    (source / "Listener.java").write_text(binding_source, encoding="utf-8")
    listener = next(item for item in manifest.semantic_analysis.types if item.simple_name == "Listener")
    # 第一种把Listener证据放在Other的注解行；第二种保留正确位置但没有Spring bean含义。
    listener.source_ref = listener.source_ref.model_copy(update={"line": 1})
    artifacts.write_manifest(manifest.model_copy(update={"baseline": GitSourceRepository().capture(source)}))
    contract = application.operation_contracts.get_contract(SYSTEM_ID, f"mq:{SYSTEM_ID}:refundconsumer", SCAN_ID)
    assert contract.fields == []
    assert contract.operation_summary == "消费refundConsumer消息。"


def test_http_catalog_freezes_external_tree_to_selected_scan(tmp_path: Path) -> None:
    """HTTP历史目录必须传递所选Manifest，不能从关系接口混入latest外部引用。

    Args:
        tmp_path: 两个扫描代际及真实HTTP应用的隔离根。
    Returns:
        None；latest和历史目录分别返回各自外部引用时通过。
    """

    from fastapi.testclient import TestClient
    from opentest.api import create_app
    from opentest.application.system_relations import SystemRelationService
    from unittest.mock import patch

    application = _contract_application(tmp_path)
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    original = artifacts.read(SYSTEM_ID, SCAN_ID)
    newer = original.model_copy(update={"scan_id": "scan-contract-next", "generated_at": utc_now()})
    artifacts.write_manifest(newer)
    artifacts.publish_latest(SYSTEM_ID, newer.scan_id)
    # 聚合算法另有真实DSF覆盖；这里检查HTTP交付的Manifest身份，故意让两代返回不同目录。
    external_tree = Mock(side_effect=lambda manifest: [{"gs_name": manifest.scan_id, "interfaces": []}])
    try:
        with patch.object(SystemRelationService, "external_systems", external_tree), TestClient(create_app(application)) as client:
            for selected, expected in [("latest", newer.scan_id), (SCAN_ID, SCAN_ID)]:
                response = client.get(f"/api/v2/systems/{SYSTEM_ID}/scans/{selected}/catalog")
                assert response.status_code == 200
                payload = response.json()
                assert payload["catalog"]["scan_id"] == expected
                assert payload["external_systems"][0]["gs_name"] == expected
                assert external_tree.call_args.args[0].scan_id == expected
    finally:
        application.close()


def test_contract_catalog_separates_historical_narrative_and_scan_versions(tmp_path: Path) -> None:
    """历史长文过期不污染契约状态，换扫描后旧补充也不能覆盖新的源码契约。

    Args:
        tmp_path: 隔离的应用及两个明确扫描代际。
    Returns:
        None；当前代码契约、历史补充和旧长文各保留正确来源时通过。
    """

    application = _contract_application(tmp_path)
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    original = artifacts.read(SYSTEM_ID, SCAN_ID)
    old_contract = application.operation_contracts.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID)
    application.operation_contracts.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, OperationContractSupplement(
        operation_summary="旧版退款补单说明", summary_evidence_refs=old_contract.summary_evidence_refs,
    ))
    application.store.write_node(KnowledgeNode(node_id="entry:demo.RefundFacade#billSupplement",
        system_id=SYSTEM_ID, kind="facade", title="历史退款长文", summary="旧状态机及公共逻辑说明",
        status=KnowledgeStatus.STALE, aliases=[OPERATION_ID], metadata={"scan_id": "scan-retired-narrative"}),
        "历史状态机记录")
    # 同扫描已有正式补充时显示已补充，不把独立于契约的旧长文过期传播到页面状态。
    current = application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID)
    assert current.target.knowledge_status == KnowledgeTargetStatus.GENERATED
    assert current.operation_contract.operation_summary == "旧版退款补单说明"
    assert current.operation_contract.source_commit == original.baseline.commit
    changed_analysis = original.semantic_analysis.model_copy(deep=True)
    changed_analysis.methods[0].javadoc_summary = "新扫描的退款补单用途"
    newer = original.model_copy(update={"scan_id": "scan-contract-next", "semantic_analysis": changed_analysis,
                                       "generated_at": utc_now()})
    artifacts.write_manifest(newer)
    artifacts.publish_latest(SYSTEM_ID, newer.scan_id)
    latest = application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID)
    assert latest.target.knowledge_status == KnowledgeTargetStatus.STALE
    assert latest.operation_contract.source_scan_id == newer.scan_id
    assert latest.operation_contract.contract_revision == 0
    assert latest.operation_contract.operation_summary == "新扫描的退款补单用途"
    historical = application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID, scan_id=SCAN_ID)
    assert historical.operation_contract.source_scan_id == SCAN_ID
    assert historical.operation_contract.contract_revision == 1
    assert historical.operation_contract.operation_summary == "旧版退款补单说明"
    # 当前扫描完成补充后清除过期标记，但历史扫描的独立版本仍保持原文和版本号。
    application.operation_contracts.supplement(SYSTEM_ID, OPERATION_ID, newer.scan_id, OperationContractSupplement(
        operation_summary="新版退款补单说明", summary_evidence_refs=latest.operation_contract.summary_evidence_refs,
    ))
    updated = application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID)
    assert updated.target.knowledge_status == KnowledgeTargetStatus.GENERATED
    assert updated.operation_contract.operation_summary == "新版退款补单说明"
    assert application.operation_contracts.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 1).operation_summary == "旧版退款补单说明"


def test_contract_catalog_rejects_same_scan_wrong_source_commit(tmp_path: Path) -> None:
    """同scan契约如果持有错误commit，目录必须提示更新且详情不能返回伪READY。

    Args:
        tmp_path: 隔离源码、应用与含错误来源的契约记录。
    Returns:
        None；错误版本不会因status字符串是READY而被认可时通过。
    """

    application = _contract_application(tmp_path)
    contract = application.operation_contracts.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID)
    # 模拟历史文件的来源漂移；正常supplement始终绑定固定源码，不能构造这种不一致。
    application.operation_contracts.contracts.save(SYSTEM_ID, contract.model_copy(update={
        "contract_revision": 1, "source_commit": "other-source-version",
    }))
    catalog = application.get_scan_catalog(SYSTEM_ID, SCAN_ID)
    target = next(item for item in catalog.targets if item.target_id == OPERATION_ID)
    assert target.knowledge_status == KnowledgeTargetStatus.STALE
    with pytest.raises(KnowledgeValidationError, match="固定源码版本不一致"):
        application.get_knowledge_target_detail(SYSTEM_ID, OPERATION_ID, scan_id=SCAN_ID)


def test_contract_without_knowledge_keeps_annotations_unknown(tmp_path: Path) -> None:
    """无长文时直接取得结构，Javadoc与未证实触发的注解都不得变成必填。

    Args:
        tmp_path: 隔离目录。
    """

    service = _service(tmp_path)
    contract = service.get_contract(SYSTEM_ID, OPERATION_ID)
    assert contract.status == "READY"
    assert contract.contract_version == "operation-contract/v2"
    assert all(not field.required and field.requirement_status == "unknown" for field in contract.fields)
    assert "required" not in contract.request_schema
    assert contract.response_schema["properties"]["success"] == {"type": "boolean"}
    # 读基础契约不产生批量持久资产，真正补充时才保存。
    assert not (service.store.root / "contracts").exists()


def test_case_contract_without_knowledge_uses_same_service(tmp_path: Path) -> None:
    """Case入口直接取得独立契约，不创建知识前置任务。

    Args:
        tmp_path: 隔离目录。
    """

    contracts = _service(tmp_path)
    runtime = CaseTemplateV4RuntimeServices(contracts.catalog, Mock(), Mock())
    case_service = CaseTemplateV4Service(contracts.store, contracts.artifacts, Mock(), Mock(), runtime)
    assert case_service._input_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID).status == "READY"
    contracts.store.write_node.assert_not_called()


def test_supplements_append_versions_without_changing_frozen_contract(tmp_path: Path) -> None:
    """补充版本仅追加，旧Generation持有的契约和显式版本读取都不受更新影响。

    Args:
        tmp_path: 隔离目录。
    """

    service = _service(tmp_path)
    first = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, _supplement())
    frozen_contract = first.model_copy(deep=True)
    second = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, _supplement("新版业务说明"))
    assert first.contract_revision == 1
    assert second.contract_revision == 2
    assert frozen_contract.fields[0].description == "分销报表ID"
    assert service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 1) == frozen_contract
    assert service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID).fields[0].description == "新版业务说明"
    assert second.request_schema["required"] == ["id"]
    assert second.fields[0].business_identity
    with pytest.raises(KnowledgeValidationError, match="版本不存在"):
        service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 99)


@pytest.mark.parametrize("mutation", ["different_method", "wrong_commit", "outside_root", "dto_annotation"])
def test_supplement_rejects_unproven_execution_evidence(tmp_path: Path, mutation: str) -> None:
    """错误方法、版本、路径或DTO注解不能证明当前入口约束。

    Args:
        tmp_path: 隔离目录。
        mutation: 本次伪造或不足的证据类型。
    """

    service = _service(tmp_path)
    request = _supplement()
    evidence = request.fields[0].evidence_refs[0]
    changes = {"different_method": {"symbol": "demo.RefundFacade#other"},
               "wrong_commit": {"commit": "other"}, "outside_root": {"path": "../RefundFacade.java"},
               "dto_annotation": {"symbol": "demo.Request#id", "line": 1}}
    request.fields[0].evidence_refs = [evidence.model_copy(update=changes[mutation])]
    with pytest.raises(KnowledgeValidationError, match="执行方法"):
        service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, request)
    assert service.contracts.read(SYSTEM_ID, SCAN_ID) == {}


def test_conditional_constraint_stays_explicit_without_global_blocking(tmp_path: Path) -> None:
    """条件必填保留可读条件及证据，未补充的无关字段仍可用。

    Args:
        tmp_path: 隔离目录。
    """

    service = _service(tmp_path)
    request = _supplement()
    request.fields[0] = request.fields[0].model_copy(update={
        "requirement_status": "conditional", "requirement_condition": "补单类型为分销时必填",
    })
    contract = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, request)
    assert contract.status == "READY"
    assert not contract.fields[0].required
    assert contract.fields[0].requirement_status == "conditional"
    assert contract.fields[1].requirement_status == "unknown"


def test_scan_publication_does_not_create_program_case_catalog(tmp_path: Path) -> None:
    """扫描发布无需旧回归点目录，不产生伪造BLOCKED覆盖资产。

    Args:
        tmp_path: 隔离目录。
    """

    service = _service(tmp_path)
    assert service.artifacts.read(SYSTEM_ID, "latest").scan_id == SCAN_ID
    assert not list(service.artifacts.scan_root.rglob("*case-analysis*"))


def test_new_internal_knowledge_entrypoints_are_retired() -> None:
    """停用在Agent或文件写入之前生效，空测试点不再成为历史候选门禁。"""

    service = KnowledgeGenerationService.__new__(KnowledgeGenerationService)
    # 无需组装任何写存储即可拒绝，证明旧入口没有隐藏执行副作用。
    with pytest.raises(KnowledgeValidationError, match="已停用"):
        service.generate(Mock())
    with pytest.raises(KnowledgeValidationError, match="已停用"):
        service.generate_drafts(Mock())
    with pytest.raises(KnowledgeValidationError, match="已停用"):
        service.prepare_client_handoff(Mock(), Mock())
    assert service._require_agent_test_points(Mock()) is None


def test_legacy_intent_api_discovers_operations_without_knowledge(tmp_path: Path) -> None:
    """旧调用意图接口改从Operation发现，无知识索引时仍返回兼容契约外形。

    Args:
        tmp_path: 隔离契约与扫描目录。
    """

    contracts = _service(tmp_path)
    application = OpenTestApplication.__new__(OpenTestApplication)
    application.store = contracts.store
    application.operations = Mock()
    application.operations.search.return_value = contracts.catalog.derive.return_value
    application.operation_contracts = contracts
    # 入口只检索与返回计划，不能因为匹配到写接口就执行它。
    response = application.resolve_knowledge_tool_intent(SYSTEM_ID, KnowledgeToolIntentRequest(query="补单", intent="execute"))
    assert not response["executed"]
    assert response["matches"][0]["target_id"] == OPERATION_ID
    assert response["matches"][0]["invocation_contract"]["required_fields"] == []
    assert not response["matches"][0]["invocation_contract"]["read_only"]
    application.operations.execute.assert_not_called()


def test_knowledge_workflow_does_not_require_all_internal_nodes() -> None:
    """未生成任何接口知识及未确认背景时仍允许从契约进入数据与Case。

    Returns:
        None；下一步不是生成内部长文且不返回全局生成门禁。
    """

    application = OpenTestApplication.__new__(OpenTestApplication)
    application.knowledge_discovery = Mock()
    application.knowledge_discovery.get_context.return_value = Mock(background_completed_at=None, interview_skipped=False)
    application.scan_catalogs = Mock()
    application.scan_catalogs.build_catalog.return_value = Mock(targets=[
        Mock(category="facade", knowledge_status=KnowledgeTargetStatus.NOT_GENERATED),
    ])
    application.tasks = Mock()
    application.tasks.list_records.return_value = []
    # 背景用于理解业务，但不能成为不依赖它的接口调用和Case的批量生成前置。
    workflow = application.get_knowledge_workflow(SYSTEM_ID)
    assert workflow.current_step == "ready"
    assert workflow.generation_blocked_reason == ""
    assert "直接准备数据或生成Case" in workflow.next_action


@pytest.mark.parametrize("operation", ["data-capability-generation", "contract-completion"])
def test_task_center_dispatches_shared_preparation_context_answers_and_continue(operation: str) -> None:
    """共享数据与契约任务复用任务中心的读、回答和继续入口，不路由到旧知识流程。

    Args:
        operation: 两种采用共享准备handoff的业务任务类型。
    Returns:
        None；原任务和固定revision贯穿各入口，回答不会丢失unknown语义。
    """

    application = OpenTestApplication.__new__(OpenTestApplication)
    task = TaskRecord(task_id="task-shared-test", system_id=SYSTEM_ID, operation=operation,
                      trace_id="trace-shared-test", status=TaskStatus.WAITING_FOR_INPUT,
                      active_handoff_id="task-shared-test", ended_at=utc_now())
    application.tasks = Mock()
    application.tasks.get.return_value = task
    application.data_capabilities = Mock()
    application.data_capabilities.task_context.return_value = {"kind": operation, "revision": 3}
    application.data_capabilities.continue_task.return_value = task
    confirmation = KnowledgeConfirmation(question_id="required-environment", answer="暂不确定")

    # 共享问题由同一权威服务保存，用户不知道时不能被任务中心自动改成已验证事实。
    assert application.get_task_context(task.task_id) == {"kind": operation, "revision": 3}
    application.answer_task_question(task.task_id, "answer-shared-001", 3, "unknown", confirmation)
    application.data_capabilities.answer.assert_called_once_with(task.task_id, {
        "request_id": "answer-shared-001", "expected_revision": 3, "outcome": "unknown",
        "confirmation": confirmation.model_dump(mode="json"),
    })
    continued = application.continue_case_task(task.task_id, "continue-shared-001", "continue", 3)
    assert continued["task"] is task
    assert continued["context"]["revision"] == 3
    application.data_capabilities.continue_task.assert_called_once_with(task.task_id)


@pytest.mark.parametrize("intent,revision,error", [
    ("regenerate_latest", 3, KnowledgeValidationError),
    ("continue", 2, IdempotencyConflictError),
])
def test_shared_task_continuation_rejects_silent_version_switch_or_stale_revision(
    intent: str, revision: int, error: type[Exception],
) -> None:
    """共享定义更新必须另建显式版本任务，旧页面也不得覆盖已经推进的草稿。

    Args:
        intent: 继续或非法切换到latest的请求意图。
        revision: 页面持有的任务版本。
        error: 当前冲突应该报告的业务错误。
    Returns:
        None；拒绝请求且权威服务没有执行状态变更。
    """

    application = OpenTestApplication.__new__(OpenTestApplication)
    application.tasks = Mock()
    application.tasks.get.return_value = TaskRecord(
        task_id="task-shared-test", system_id=SYSTEM_ID, operation="data-capability-generation",
        trace_id="trace-shared-test", status=TaskStatus.WAITING_FOR_COMPLETION, ended_at=utc_now(),
    )
    application.data_capabilities = Mock()
    application.data_capabilities.task_context.return_value = {"revision": 3}
    # 两种拒绝都应发生在调用continue_task之前，避免先变更再报告冲突。
    with pytest.raises(error):
        application.continue_case_task("task-shared-test", "continue-shared-002", intent, revision)
    application.data_capabilities.continue_task.assert_not_called()


def test_data_execution_task_context_reads_its_persisted_result() -> None:
    """独立执行任务展示对应运行结果及来源，而不是把任务结束当作业务成功。

    Returns:
        None；按任务所属系统和运行身份查询独立记录并返回专用上下文。
    """

    application = OpenTestApplication.__new__(OpenTestApplication)
    application.tasks = Mock()
    application.tasks.get.return_value = TaskRecord(
        task_id="task-data-execution", system_id=SYSTEM_ID, operation="data-execution",
        trace_id="trace-data-execution", status=TaskStatus.FAILED,
        result={"execution_id": "data-execution-example"}, ended_at=utc_now(),
    )
    application.data_capabilities = Mock()
    execution = {"execution_id": "data-execution-example", "status": "FAILED", "outputs": {}}
    application.data_capabilities.records.get_execution.return_value = execution
    context = application.get_task_context("task-data-execution")
    assert context == {"kind": "data_execution", "execution": execution, "questions": []}
    application.data_capabilities.records.get_execution.assert_called_once_with(SYSTEM_ID, "data-execution-example")


def test_purpose_and_response_supplements_publish_independent_versions(tmp_path: Path) -> None:
    """用途或响应说明可独立保存，且旧请求字段和固定历史版本不被覆盖。

    Args:
        tmp_path: 隔离的源码和契约目录。
    """

    service = _service(tmp_path)
    operation = service.catalog.derive.return_value[0]
    evidence = service.artifacts.read(SYSTEM_ID, SCAN_ID).semantic_analysis.methods[0].source_ref
    operation.source_symbol_refs = [evidence]
    # 只有用途也能形成正式补充版本，不要求捏造输入字段改动。
    purpose = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, OperationContractSupplement(
        operation_summary="按分销报表补建退款订单", summary_evidence_refs=[evidence],
    ))
    from opentest.application.operation_contracts import OperationResponseFieldSupplement

    response = service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, OperationContractSupplement(
        response_fields=[OperationResponseFieldSupplement(
            path="success", description="补单是否成功", evidence_refs=[evidence],
        )],
    ))
    assert purpose.contract_revision == 1
    assert response.contract_revision == 2
    assert response.operation_summary == purpose.operation_summary
    assert response.response_fields[0].description == "补单是否成功"
    assert service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID, 1).response_fields == []
    assert service.get_contract(SYSTEM_ID, OPERATION_ID, SCAN_ID).response_fields == response.response_fields
    with pytest.raises(KnowledgeValidationError, match="没有绑定"):
        service.supplement(SYSTEM_ID, OPERATION_ID, SCAN_ID, OperationContractSupplement(
            operation_summary="其他接口用途", summary_evidence_refs=[evidence.model_copy(update={"symbol": "demo.Other#call"})],
        ))


def test_facade_contract_exposes_business_response_without_execution_envelope(tmp_path: Path) -> None:
    """知识字段只展示Facade业务返回值，不混入执行器request_id等回执。

    Args:
        tmp_path: 隔离契约服务目录。
    """

    service = _service(tmp_path)
    operation = service.catalog.derive.return_value[0]
    operation.publication_output_schema = {"type": "object", "properties": {
        "output": {"type": "object", "properties": {"success": {"type": "boolean"}}},
        "request_id": {"type": "string"},
    }}
    operation.output_fields = [OperationFieldEvidence(
        field_path="success", field_name="success", declared_type="boolean", description="业务成功状态",
    )]
    # 基础读取无需旧知识节点或Agent即可展示扫描已证明的响应字段。
    contract = service.get_contract(SYSTEM_ID, OPERATION_ID)
    assert set(contract.response_schema["properties"]) == {"success"}
    assert contract.response_fields[0].description == "业务成功状态"


def test_external_interface_purpose_uses_caller_declaration_without_entry(tmp_path: Path) -> None:
    """未接入下游的接口用途可引用调用方声明补充，无需伪造本系统入口实现。

    Args:
        tmp_path: 隔离源码与契约目录。
    """

    service = _service(tmp_path)
    manifest = service.artifacts.read(SYSTEM_ID, SCAN_ID)
    evidence = manifest.semantic_analysis.methods[0].source_ref
    operation = service.catalog.derive.return_value[0].model_copy(update={
        "kind": OperationKind.EXTERNAL_DSF, "operation_id": "dsf:remote:refund#query",
        "source_symbol_refs": [evidence], "input_fields": [],
    })
    service.catalog.derive.return_value = [operation]
    service.artifacts.write_manifest(manifest.model_copy(update={"entries": []}))
    # 用途说明只要求扫描声明，无provider源码也不会误授予执行权限。
    saved = service.supplement(SYSTEM_ID, operation.operation_id, SCAN_ID, OperationContractSupplement(
        operation_summary="查询资源侧退款记录", summary_evidence_refs=[evidence],
    ))
    assert saved.operation_summary == "查询资源侧退款记录"
    assert saved.contract_revision == 1


@pytest.mark.parametrize("annotation_prefix,listener_line", [("", 1), ("", 2), ("@Slf4j\n", 1)])
def test_mq_contract_resolves_bound_listener_payload_and_accepts_field_supplement(
    tmp_path: Path, annotation_prefix: str, listener_line: int,
) -> None:
    """MQ按明确Spring bean绑定取得消息DTO，并对其真实消费者执行路径补充字段。

    Args:
        tmp_path: 隔离的Spring源码、语义扫描和契约目录。
        annotation_prefix: 同一类在Spring注解之前可选的Lombok注解。
        listener_line: JavaParser返回的注解首行或旧扫描返回的class声明行。
    """

    from opentest.application.operations import OperationCapabilityCatalog
    from opentest.domain.models import DiscoveredResource, SemanticTypeDefinition, SemanticFieldDefinition

    service = _service(tmp_path)
    source = tmp_path / "source"
    (source / "Listener.java").write_text(
        annotation_prefix + '@Component(value = "refundListener")\nclass Listener {\n'
        ' boolean process(Payload payload) { return payload.refundNo != null; }\n}\n', encoding="utf-8",
    )
    (source / "Payload.java").write_text('class Payload {\n String refundNo;\n}\n', encoding="utf-8")
    listener_ref = SourceReference(path="Listener.java", symbol="demo.Listener", line=listener_line)
    method_ref = SourceReference(path="Listener.java", symbol="demo.Listener#process(demo.Payload)",
                                 line=3 + annotation_prefix.count("\n"))
    payload_ref = SourceReference(path="Payload.java", symbol="demo.Payload", line=1)
    field_ref = SourceReference(path="Payload.java", symbol="demo.Payload#refundNo", line=2)
    manifest = ScanManifest(
        system_id=SYSTEM_ID, scan_id=SCAN_ID, baseline=GitSourceRepository().capture(source),
        resources=[DiscoveredResource(resource_id="resource:refund:mq", system_id=SYSTEM_ID,
            kind="mq", role="consumer", logical_name="refundConsumer", listener_ref="refundListener",
            nameserver_config_key="mq.servers", topic_config_key="mq.refund.topic", source_refs=[listener_ref])],
        semantic_analysis=SemanticAnalysisResult(system_id=SYSTEM_ID, types=[
            SemanticTypeDefinition(symbol_id="demo.Listener", qualified_class_name="demo.Listener",
                simple_name="Listener", source_ref=listener_ref, javadoc_summary="处理退款完成通知"),
            SemanticTypeDefinition(symbol_id="demo.Payload", qualified_class_name="demo.Payload",
                simple_name="Payload", source_ref=payload_ref, fields=[SemanticFieldDefinition(
                    field_name="refundNo", declared_type="String", referenced_type="java.lang.String",
                    javadoc_summary="退款单号", source_ref=field_ref,
                )]),
        ], methods=[SemanticMethodDefinition(symbol_id=method_ref.symbol, qualified_class_name="demo.Listener",
            method_name="process", parameter_qualified_types=["demo.Payload"], has_executable_body=True,
            source_ref=method_ref)]),
    )
    service.artifacts.write_manifest(manifest)
    service.catalog = OperationCapabilityCatalog(service.store, service.artifacts)
    operation_id = f"mq:{SYSTEM_ID}:refundconsumer"
    contract = service.get_contract(SYSTEM_ID, operation_id, SCAN_ID)
    # 执行包装继续为message，但知识可见其真实字段；没有扫描entry也能定位process。
    assert contract.request_schema["properties"]["message"]["properties"]["refundNo"] == {"type": "string"}
    assert contract.fields[0].path == "message.refundNo"
    assert contract.operation_summary == "处理退款完成通知"
    saved = service.supplement(SYSTEM_ID, operation_id, SCAN_ID, OperationContractSupplement(fields=[
        OperationFieldSupplement(path="message.refundNo", description="已完成退款对应的退票单号",
                                 requirement_status="required", evidence_refs=[method_ref]),
    ]))
    assert saved.fields[0].required is True
    assert saved.contract_revision == 1
    # 仅更新说明可使用消息DTO声明，但必须继续保留已确定必填的process执行证据。
    described = service.supplement(SYSTEM_ID, operation_id, SCAN_ID, OperationContractSupplement(fields=[
        OperationFieldSupplement(path="message.refundNo", description="退款订单唯一编号", evidence_refs=[field_ref]),
    ]))
    assert described.fields[0].required is True
    assert {reference.symbol for reference in described.fields[0].evidence_refs} == {method_ref.symbol, field_ref.symbol}


@pytest.mark.parametrize('number', [1, 1.0, 0.0, -2.0])
def test_integer_contract_accepts_integral_json_numbers(number):
    """真实DSF数据可能把整数序号编码为小数形式，整数契约按数值而非Python类型判断。"""

    from opentest.application.operations import OperationExecutionService

    OperationExecutionService._validate_schema_value(number, {'type': 'integer'}, 'segment.sequence')


@pytest.mark.parametrize('number', [True, 1.5, float('nan'), float('inf')])
def test_integer_contract_rejects_non_integral_values(number):
    """兼容Gson整数不能把布尔、小数或非有限值带入Java请求。"""

    from opentest.application.operations import OperationExecutionService

    with pytest.raises(KnowledgeValidationError, match='integer'):
        OperationExecutionService._validate_schema_value(number, {'type': 'integer'}, 'segment.sequence')
