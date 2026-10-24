"""任务内调用方外部依赖的精确契约、本人草稿与共享状态边界。"""

from __future__ import annotations

from unittest.mock import Mock, patch

from opentest.application.case_template_v4 import CaseTemplateV4Service
from opentest.domain.case_template_v4 import CaseTemplateHandoffV4, CaseTemplateSourceScope
from opentest.domain.models import (
    DsfOperationDefinition,
    OperationCapability,
    OperationInputKnowledgeContract,
    OperationKind,
    OperationMutability,
    OperationProviderKind,
    SourceBaseline,
    SourceReference,
)


SYSTEM_ID = "ifightchainsaas.java.refund.core"
SCAN_ID = "scan-20261020062539-c796af848b-6894bbf5"
OPERATION_ID = "dsf:java.account.supplement.core:distribution:reportQueryList"


def _contract(revision: int) -> OperationInputKnowledgeContract:
    """构造与解析定义完全一致的可执行契约。"""

    return OperationInputKnowledgeContract(
        contract_version="operation-contract/v2",
        contract_revision=revision,
        target_id=OPERATION_ID,
        source_scan_id=SCAN_ID,
        status="READY",
        request_schema={"type": "object", "properties": {"page": {"type": "integer"}}},
        response_schema={"type": "object", "properties": {"list": {}}},
        source_commit="7b962925db34b181f66e39a9262356585a8fcc03",
    )


def _provider() -> OperationCapability:
    """构造调用方已解析的外部DSF能力。"""

    definition = DsfOperationDefinition(
        operation_id=OPERATION_ID,
        provider_system_id="java.account.supplement.core",
        gs_name="dsf.java.account.supplement.core",
        service_name="distribution",
        version="1.0.0.3",
        action="reportQueryList",
        request_schema={"type": "object", "properties": {"page": {"type": "integer"}}},
        response_schema={"type": "object", "properties": {"list": {}}},
        dependency_coordinate="demo:facade:1",
        source_refs=[SourceReference(path="ReportFacade.class", symbol="demo.ReportFacade#reportQueryList", line=1)],
    )
    return OperationCapability(
        operation_id=OPERATION_ID,
        system_id=SYSTEM_ID,
        business_name="reportQueryList",
        kind=OperationKind.EXTERNAL_DSF,
        mutability=OperationMutability.READ_ONLY,
        input_schema=definition.request_schema,
        publication_input_schema=definition.request_schema,
        publication_output_schema=definition.response_schema,
        provider_kind=OperationProviderKind.EXTERNAL_DSF_PROXY,
        provider_operation_id=OPERATION_ID,
        provider_definition=definition,
        source_scan_id=SCAN_ID,
        executable=True,
    )


def test_task_local_external_creates_authored_draft_and_exact_reference(tmp_path):
    """无共享发布行时，任务内外部依赖仍生成可执行引用和本人草稿。"""

    store = Mock()
    store.root = tmp_path
    store.metadata = Mock()
    handoffs = Mock()
    service = CaseTemplateV4Service(store, Mock(), Mock(), handoffs)
    contracts = Mock()
    contracts.interface_id.return_value = 4586
    publications = Mock()
    publications.store.contract.side_effect = lambda interface_id, revision: {
        "system_id": SYSTEM_ID,
        "operation_id": OPERATION_ID,
        "baseline_id": "baseline-0393d1161bc840179925638a2b6b3228",
        "scan_id": SCAN_ID,
        "author_user_id": None if revision == 3 else "1214259",
        "contract": _contract(revision).model_dump(mode="json"),
    }
    publications.store.ensure_interface.return_value = {"baseline_interface_id": 695}
    publications.store.get_item.return_value = {
        "baseline_interface_id": 695,
        "publication_revision": 0,
        "draft_revision": 0,
        "draft_status": None,
    }
    publications.save_interface_draft.return_value = {
        "baseline_interface_id": 695,
        "interface_id": 4586,
        "contract_revision": 4,
    }
    service.operation_contracts = Mock()
    service.operation_contracts.get_contract.side_effect = lambda system, operation, scan, revision=None, **kwargs: (
        _contract(3) if revision in {None, 3} else _contract(revision)
    )
    handoff = CaseTemplateHandoffV4(
        handoff_id="case-template-handoff-" + "c" * 20,
        system_id=SYSTEM_ID,
        entry_id="facade:" + SYSTEM_ID + ".RefundFacade#billSupplement",
        source_scan_id=SCAN_ID,
        baseline_id="baseline-0393d1161bc840179925638a2b6b3228",
        owner_user_id="1214259",
        knowledge_view="published",
        status="WAITING_FOR_AGENT",
        source_scopes=[CaseTemplateSourceScope(
            source_system_id=SYSTEM_ID,
            source_scan_id=SCAN_ID,
            source_baseline=SourceBaseline(source_path=str(tmp_path)),
            contract_revisions={OPERATION_ID: 3},
        )],
    )
    with patch("opentest.application.case_template_v4.PublicationService", return_value=publications), \
         patch("opentest.application.case_template_v4.OperationContractStore", return_value=contracts):
        resolved, reference, contract = service._visible_dependency_knowledge(handoff, _provider())

    assert resolved is not None
    assert reference.baseline_interface_id == 695
    assert reference.interface_id == 4586
    assert reference.contract_revision == 4
    assert contract.contract_revision == 4
    # 旧零版没有作者；复制到新修订而不是改写历史行。
    saved = contracts.save.call_args.args[1]
    assert saved.contract_revision == 4
    assert contracts.save.call_args.kwargs["author_user_id"] == "1214259"
    assert publications.save_interface_draft.call_args.args[1].contract_revision == 4
    assert publications.save_interface_draft.call_args.args[1].status == "READY"


def test_case_binding_keeps_task_local_dependency(tmp_path):
    """冻结Case绑定不能因为依赖尚未共享而丢掉实际引用。"""

    from types import SimpleNamespace

    from opentest.domain.shared_workspace import InterfaceKnowledgeRef

    store = Mock()
    store.root = tmp_path
    store.metadata = Mock()
    handoffs = Mock()
    service = CaseTemplateV4Service(store, Mock(), Mock(), handoffs)
    publications = Mock()
    publications.store.dependency_interface.side_effect = lambda identity: {
        "system_id": SYSTEM_ID,
        "operation_id": OPERATION_ID,
    }
    reference = InterfaceKnowledgeRef(baseline_interface_id=729, interface_id=4586, contract_revision=1)
    handoff = CaseTemplateHandoffV4(
        handoff_id="case-template-handoff-" + "d" * 20,
        system_id=SYSTEM_ID,
        entry_id="facade:" + SYSTEM_ID + ".RefundFacade#billSupplement",
        source_scan_id=SCAN_ID,
        baseline_id="baseline-0393d1161bc840179925638a2b6b3228",
        owner_user_id="1214259",
        status="WAITING_FOR_AGENT",
        source_scopes=[CaseTemplateSourceScope(
            source_system_id=SYSTEM_ID,
            source_scan_id=SCAN_ID,
            source_baseline=SourceBaseline(source_path=str(tmp_path)),
        )],
        knowledge_dependencies=[reference],
    )
    service._used_case_operations = Mock(return_value={(SYSTEM_ID, OPERATION_ID)})
    with patch("opentest.application.case_template_v4.PublicationService", return_value=publications):
        frozen = service._freeze_case_bindings(
            handoff, [SimpleNamespace(variant_id="case-variant-v4-local")])

    assert [item.model_dump() for item in frozen.case_bindings[0].knowledge_dependencies] == [
        reference.model_dump()
    ]
    handoffs.write.assert_called_once()


def test_compiler_accepts_typed_enum_evidence_without_fake_source_lines():
    """精确依赖字节码核验的常量对必须能被编译器消费，而不是伪装成Java源码证据。"""

    from types import SimpleNamespace

    from opentest.application.case_template_compiler_v4 import CaseTemplateValidatorV4

    compiler = CaseTemplateValidatorV4()
    parameter = SimpleNamespace(arguments={"values": [{"name": "ARC", "code": "ARC"}]})
    compilation = SimpleNamespace(
        source_text_by_system_path={SYSTEM_ID: {}},
        dependency_enum_values=[{"class_name": "demo.ReportSourceEnum", "name": "ARC", "code": "ARC"}],
    )
    assert compiler._enum_values_have_source_evidence(parameter, compilation) is True

    compilation.dependency_enum_values = []
    assert compiler._enum_values_have_source_evidence(parameter, compilation) is False


def test_enum_bytecode_parser_proves_name_and_code_without_source_lines():
    """javap指令中的构造器、getter和静态初始化可证明具体常量code。"""

    from opentest.adapters.java_dependencies import JavaDependencyCatalog

    text = '''public final class demo.ReportSourceEnum extends java.lang.Enum<demo.ReportSourceEnum> {
  public static final demo.ReportSourceEnum ARC;
  private java.lang.String code;
  private java.lang.String desc;
  private java.lang.Integer value;
  public java.lang.String getCode();
    Code:
       0: aload_0
       1: getfield      #7                  // Field code:Ljava/lang/String;
       4: areturn

  private demo.ReportSourceEnum(java.lang.String, java.lang.String, java.lang.Integer);
    Code:
       0: aload_0
       1: aload_1
       2: iload_2
       3: invokespecial #6                  // Method java/lang/Enum."<init>":(Ljava/lang/String;I)V
       6: aload_0
       7: aload_3
       8: putfield      #7                  // Field code:Ljava/lang/String;
      11: aload_0
      12: aload         4
      14: putfield      #8                  // Field desc:Ljava/lang/String;
      17: aload_0
      18: aload         5
      20: putfield      #9                  // Field value:Ljava/lang/Integer;
      23: return

  static {};
    Code:
       0: new           #4                  // class demo/ReportSourceEnum
       3: dup
       4: ldc           #14                 // String ARC
       6: iconst_0
       7: ldc           #14                 // String ARC
       9: ldc           #14                 // String ARC
      11: iconst_1
      12: invokestatic  #15                 // Method java/lang/Integer.valueOf:(I)Ljava/lang/Integer;
      15: invokespecial #16                 // Method demo/ReportSourceEnum."<init>":(Ljava/lang/String;ILjava/lang/String;Ljava/lang/String;Ljava/lang/Integer;)V
      18: putstatic     #17                 // Field ARC:demo/ReportSourceEnum;
      21: return
}'''

    assert JavaDependencyCatalog._parse_enum_bytecode(text, "demo.ReportSourceEnum") == [
        {"name": "ARC", "code": "ARC", "fields": {"code": "ARC", "desc": "ARC", "value": 1}}
    ]


def test_other_employees_unpublished_contract_is_not_copied_into_own_draft(tmp_path):
    """他人未发布契约不能成为本人草稿内容；只能从本任务解析定义重建。"""

    from types import SimpleNamespace

    store = Mock()
    store.root = tmp_path
    store.metadata = Mock()
    handoffs = Mock()
    service = CaseTemplateV4Service(store, Mock(), Mock(), handoffs)
    other = _contract(3).model_copy(update={
        "request_schema": {"type": "object", "properties": {"other_secret": {"type": "string"}}},
    })
    contracts = Mock()
    contracts.interface_id.return_value = 4586
    publications = Mock()
    publications.store.contract.side_effect = lambda interface_id, revision: {
        "system_id": SYSTEM_ID,
        "operation_id": OPERATION_ID,
        "baseline_id": "baseline-0393d1161bc840179925638a2b6b3228",
        "scan_id": SCAN_ID,
        "author_user_id": "other-user" if revision == 3 else "1214259",
        "contract": (other if revision == 3 else _contract(revision)).model_dump(mode="json"),
    }
    publications.store.ensure_interface.return_value = {"baseline_interface_id": 729}
    publications.store.get_item.return_value = {
        "baseline_interface_id": 729,
        "publication_revision": 0,
        "draft_revision": 0,
        "draft_status": None,
    }
    publications.save_interface_draft.return_value = {
        "baseline_interface_id": 729,
        "interface_id": 4586,
        "contract_revision": 4,
    }
    service.operation_contracts = Mock()
    service.operation_contracts.get_contract.side_effect = lambda system, operation, scan, revision=None, **kwargs: (
        other if revision in {None, 3} else _contract(revision)
    )
    service.artifacts.read.return_value = SimpleNamespace(
        baseline=SimpleNamespace(commit="7b962925db34b181f66e39a9262356585a8fcc03"))
    handoff = CaseTemplateHandoffV4(
        handoff_id="case-template-handoff-" + "e" * 20,
        system_id=SYSTEM_ID,
        entry_id="facade:" + SYSTEM_ID + ".RefundFacade#billSupplement",
        source_scan_id=SCAN_ID,
        baseline_id="baseline-0393d1161bc840179925638a2b6b3228",
        owner_user_id="1214259",
        status="WAITING_FOR_AGENT",
        source_scopes=[CaseTemplateSourceScope(
            source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
            source_baseline=SourceBaseline(source_path=str(tmp_path)),
            contract_revisions={OPERATION_ID: 3},
        )],
    )
    with patch("opentest.application.case_template_v4.PublicationService", return_value=publications), \
         patch("opentest.application.case_template_v4.OperationContractStore", return_value=contracts):
        _, reference, contract = service._ensure_task_local_dependency(handoff, _provider())

    saved = contracts.save.call_args.args[1]
    assert saved.request_schema == _provider().provider_definition.request_schema
    assert "other_secret" not in saved.request_schema.get("properties", {})
    assert contracts.save.call_args.kwargs["author_user_id"] == "1214259"
    assert reference.contract_revision == 4
    assert contract.contract_revision == 4


def test_typed_enum_evidence_does_not_invalidate_valid_source_evidence():
    """新增 typed evidence 不能遮蔽仍然合法的已读源码证据。"""

    from types import SimpleNamespace

    from opentest.application.case_template_compiler_v4 import CaseTemplateValidatorV4

    validator = CaseTemplateValidatorV4()
    parameter = SimpleNamespace(arguments={"values": [{"name": "ARC", "code": "ARC"}]})
    compilation = SimpleNamespace(
        source_text_by_system_path={SYSTEM_ID: {"SourceEnum.java": '1\tARC("ARC", "ARC")'}},
        dependency_enum_values=[{"name": "BSP", "code": "BSP"}],
    )
    assert validator._enum_values_have_source_evidence(parameter, compilation) is True


def test_enum_parser_rejects_computed_getter():
    """字段经过拼接或调用后再返回时，不能把字段原值当作 getCode()。"""

    from opentest.adapters.java_dependencies import JavaDependencyCatalog

    text = '''public final class demo.CodeEnum extends java.lang.Enum<demo.CodeEnum> {
  private java.lang.String code;
  public java.lang.String getCode();
    Code:
       0: aload_0
       1: getfield      #7                  // Field code:Ljava/lang/String;
       4: ldc           #8                  // String -
       6: invokevirtual #9                  // Method java/lang/String.concat:(Ljava/lang/String;)Ljava/lang/String;
       9: areturn

  private demo.CodeEnum(java.lang.String);
    Code:
       0: aload_0
       1: aload_1
       2: iload_2
       3: invokespecial #6                  // Method java/lang/Enum."<init>":(Ljava/lang/String;I)V
       6: aload_3
       7: putfield      #7                  // Field code:Ljava/lang/String;
      10: return

  static {};
    Code:
       0: new           #4                  // class demo/CodeEnum
       3: dup
       4: ldc           #14                 // String ARC
       6: iconst_0
       7: ldc           #14                 // String ARC
       9: invokespecial #16                 // Method demo/CodeEnum."<init>":(Ljava/lang/String;ILjava/lang/String;)V
      12: putstatic     #17                 // Field ARC:demo/CodeEnum;
      15: return
}'''
    assert JavaDependencyCatalog._parse_enum_bytecode(text, "demo.CodeEnum") == []


def test_dependency_type_prefers_actual_classpath_over_pom_version(tmp_path):
    """实际Maven classpath的调解版本优先，POM直接依赖只在类型缺失时兜底。"""

    from contextlib import nullcontext

    from opentest.adapters.java_dependencies import MavenArtifact

    store = Mock()
    store.root = tmp_path
    store.metadata = Mock()
    handoffs = Mock()
    handoffs.processing_scope.side_effect = lambda handoff_id: nullcontext()
    service = CaseTemplateV4Service(store, Mock(), Mock(), handoffs)
    service.runtime = Mock()
    service.runtime.operation_catalog.derive.return_value = [_provider()]
    handoff = CaseTemplateHandoffV4(
        handoff_id="case-template-handoff-" + "f" * 20,
        system_id=SYSTEM_ID,
        entry_id="facade:" + SYSTEM_ID + ".RefundFacade#billSupplement",
        source_scan_id=SCAN_ID,
        baseline_id="baseline-0393d1161bc840179925638a2b6b3228",
        owner_user_id="1214259",
        status="WAITING_FOR_AGENT",
        source_scopes=[CaseTemplateSourceScope(
            source_system_id=SYSTEM_ID, source_scan_id=SCAN_ID,
            source_baseline=SourceBaseline(source_path=str(tmp_path)))],
    )
    handoffs.get.return_value = handoff
    classpath = MavenArtifact("demo:facade:1", tmp_path / "cp.jar", tmp_path / "cp-sources.jar")
    pom = MavenArtifact("demo:model:1", tmp_path / "pom.jar", tmp_path / "pom-sources.jar")
    search = Mock()
    search._source_root.return_value = tmp_path
    search.resolved_artifacts.return_value = ([classpath], [])
    search.find_type.side_effect = lambda artifacts, class_name: (
        classpath if classpath in artifacts else pom)
    search.local_dependency_artifacts.return_value = [pom]
    search.enum_values_from_bytecode.side_effect = lambda target, class_name: [
        {"name": "ARC", "code": "FROM_CLASSPATH" if target is classpath else "FROM_POM",
         "fields": {"code": "x"}}]
    with patch("opentest.application.downstream_interfaces.DownstreamInterfaceSearchService", return_value=search):
        result = service.read_dependency_type(
            handoff.handoff_id, "demo:facade:1", "demo.SourceEnum")

    assert result["coordinate"] == "demo:facade:1"
    assert result["enum_values"][0]["code"] == "FROM_CLASSPATH"


def test_web_offline_dependency_type_tool_skips_operation_gate():
    """网页离线工具必须在operation_id门禁之前处理任务级枚举读取。"""

    from types import SimpleNamespace

    from opentest.application.web_generation import WebGenerationService

    service = object.__new__(WebGenerationService)
    cases = Mock()
    cases.handoffs.get.return_value = SimpleNamespace(handoff_id="case-template-handoff-" + "a" * 20)
    cases.read_dependency_type.return_value = {"enum_values": [{"name": "ARC", "code": "ARC"}]}
    service.application = SimpleNamespace(case_template_v4=cases)
    task = SimpleNamespace(operation="case-generation", system_id=SYSTEM_ID,
                           task_id="task-1234567890abcdef", trace_id="trace",
                           active_handoff_id="case-template-handoff-" + "a" * 20)

    result = service._offline_tool(task, "read_dependency_type", {
        "coordinate": "demo:facade:1", "class_name": "demo.SourceEnum"})

    assert result["enum_values"][0]["code"] == "ARC"
    cases.read_dependency_type.assert_called_once_with(
        "case-template-handoff-" + "a" * 20, "demo:facade:1", "demo.SourceEnum")
