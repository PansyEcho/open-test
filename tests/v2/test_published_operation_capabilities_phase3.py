"""验证阶段3只发布有真实源码与现有Operation证据的V2原子能力。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.capability_schemas import (
    candidate_has_restricted_projection_surface,
    candidate_projection_path_evidence,
    java_closed_business_generic_reference,
    project_value_to_schema,
)
from opentest.application.foundation import OpenTestApplication
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.models import (
    CandidateOperation,
    CandidateOperationKind,
    CandidateOperationStatus,
    CandidateDtoDefinition,
    CandidateDtoField,
    CandidateRef,
    CapabilityDraftSubmission,
    DsfClientProfile,
    DsfOperationDefinition,
    DsfOperationMutability,
    DsfProfileStatus,
    EntryPoint,
    KnowledgeNodeKind,
    ProviderOperationRef,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticFieldDefinition,
    SemanticFieldConversionEvidence,
    SemanticMethodDefinition,
    SemanticResolutionStatus,
    SemanticTypeDefinition,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
)


def _publish_atomic_scan(
    application: OpenTestApplication,
    system_id: str,
    commit: str = "atomic-v1",
    response_mode: str = "plain",
    generic_field_required: bool = False,
) -> None:
    """发布一个具有真实Java文件、完整DTO和唯一DSF Operation的通用扫描。

    Args:
        application: 隔离知识仓库应用。
        system_id: 本次扫描独立所属系统。
        commit: 用于漂移测试的源码基线标识。
        response_mode: plain、bound_generic或raw_generic响应继承模式。
        generic_field_required: raw或bound父响应的泛型字段是否有运行时必填证据。

    Side Effects:
        写入通用Java源码、注册系统并原子发布latest scan bundle。
    """

    source_root = application.knowledge_root.parent / f"source-{system_id}"
    source_file = source_root / "src/main/java/sample/AtomicFacadeImpl.java"
    source_file.parent.mkdir(parents=True)
    generic_source = (
        (
            "@interface NotNull {} class BaseResponse<T> { @NotNull T data; } "
            if generic_field_required
            else "class BaseResponse<T> { T data; } "
        )
        if response_mode != "plain"
        else ""
    )
    response_source = (
        "class AtomicResponse extends BaseResponse<String> { String referenceId; } "
        if response_mode == "bound_generic"
        else (
            "class AtomicResponse extends BaseResponse { String referenceId; } "
            if response_mode == "raw_generic"
            else "class AtomicResponse { String referenceId; } "
        )
    )
    source_file.write_text(
        "package sample; "
        "interface AtomicFacade { AtomicResponse execute(AtomicRequest request); } "
        "class BaseRequest { String traceId; } "
        "class AtomicPayload { String itemCode; } "
        "class AtomicRequest extends BaseRequest { String requestId; AtomicPayload payload; } "
        + generic_source
        + response_source
        + "class AtomicFacadeImpl implements AtomicFacade { "
        + "public AtomicResponse execute(AtomicRequest request) { return new AtomicResponse(); } "
        + "public AtomicResponse inspect(AtomicRequest request) { return new AtomicResponse(); } }\n",
        encoding="utf-8",
    )
    baseline = SourceBaseline(source_path=str(source_root), commit=commit)
    application.register_system(
        SystemDefinition(system_id=system_id, name=system_id, source_path=str(source_root))
    )

    interface_type = "sample.AtomicFacade"
    implementation_type = "sample.AtomicFacadeImpl"
    request_type = "sample.AtomicRequest"
    response_type = "sample.AtomicResponse"
    interface_symbol = f"{interface_type}#execute({request_type})"
    implementation_symbol = f"{implementation_type}#execute({request_type})"
    inspect_symbol = f"{implementation_type}#inspect({request_type})"
    implementation_ref = SourceReference(
        path=str(source_file),
        symbol=implementation_symbol,
        line=1,
        commit=commit,
    )
    interface_ref = implementation_ref.model_copy(update={"symbol": interface_symbol})
    request_ref = implementation_ref.model_copy(update={"symbol": request_type})
    response_ref = implementation_ref.model_copy(update={"symbol": response_type})
    generic_base_type = "sample.BaseResponse"
    generic_base_ref = implementation_ref.model_copy(update={"symbol": generic_base_type})
    base_request_type = "sample.BaseRequest"
    payload_type = "sample.AtomicPayload"
    base_request_ref = implementation_ref.model_copy(update={"symbol": base_request_type})
    payload_ref = implementation_ref.model_copy(update={"symbol": payload_type})
    analysis = SemanticAnalysisResult(
        schema_version=5,
        analyzer="phase3-test",
        analyzer_version="1",
        system_id=system_id,
        methods=[
            SemanticMethodDefinition(
                symbol_id=interface_symbol,
                qualified_class_name=interface_type,
                method_name="execute",
                parameter_names=["request"],
                parameter_types=["AtomicRequest"],
                parameter_qualified_types=[request_type],
                return_type="AtomicResponse",
                return_qualified_type=response_type,
                owner_type_kind="interface",
                source_ref=interface_ref,
            ),
            SemanticMethodDefinition(
                symbol_id=implementation_symbol,
                qualified_class_name=implementation_type,
                method_name="execute",
                parameter_names=["request"],
                parameter_types=["AtomicRequest"],
                parameter_qualified_types=[request_type],
                return_type="AtomicResponse",
                return_qualified_type=response_type,
                owner_interfaces=[interface_type],
                owner_type_kind="class",
                has_executable_body=True,
                source_ref=implementation_ref,
            ),
            SemanticMethodDefinition(
                symbol_id=inspect_symbol,
                qualified_class_name=implementation_type,
                method_name="inspect",
                parameter_names=["request"],
                parameter_types=["AtomicRequest"],
                parameter_qualified_types=[request_type],
                return_type="AtomicResponse",
                return_qualified_type=response_type,
                owner_type_kind="class",
                has_executable_body=True,
                source_ref=implementation_ref.model_copy(update={"symbol": inspect_symbol}),
            ),
        ],
        types=[
            SemanticTypeDefinition(
                symbol_id=request_type,
                qualified_class_name=request_type,
                simple_name="AtomicRequest",
                base_types=[base_request_type],
                fields=[
                    SemanticFieldDefinition(
                        field_name="requestId",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        runtime_required=True,
                        runtime_required_evidence=["jakarta.validation.constraints.NotBlank"],
                        source_ref=request_ref,
                    ),
                    SemanticFieldDefinition(
                        field_name="payload",
                        declared_type="AtomicPayload",
                        referenced_type=payload_type,
                        source_ref=request_ref,
                    ),
                ],
                source_ref=request_ref,
            ),
            SemanticTypeDefinition(
                symbol_id=base_request_type,
                qualified_class_name=base_request_type,
                simple_name="BaseRequest",
                fields=[
                    SemanticFieldDefinition(
                        field_name="traceId",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        source_ref=base_request_ref,
                    )
                ],
                source_ref=base_request_ref,
            ),
            SemanticTypeDefinition(
                symbol_id=payload_type,
                qualified_class_name=payload_type,
                simple_name="AtomicPayload",
                fields=[
                    SemanticFieldDefinition(
                        field_name="itemCode",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        source_ref=payload_ref,
                    )
                ],
                source_ref=payload_ref,
            ),
            SemanticTypeDefinition(
                symbol_id=response_type,
                qualified_class_name=response_type,
                simple_name="AtomicResponse",
                base_types=(
                    [f"{generic_base_type}<java.lang.String>"]
                    if response_mode == "bound_generic"
                    else ([generic_base_type] if response_mode == "raw_generic" else [])
                ),
                fields=[
                    SemanticFieldDefinition(
                        field_name="referenceId",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        source_ref=response_ref,
                    )
                ],
                source_ref=response_ref,
            ),
            *(
                [
                    SemanticTypeDefinition(
                        symbol_id=generic_base_type,
                        qualified_class_name=generic_base_type,
                        simple_name="BaseResponse",
                        fields=[
                            SemanticFieldDefinition(
                                field_name="data",
                                declared_type="T",
                                referenced_type="T",
                                runtime_required=generic_field_required,
                                runtime_required_evidence=(
                                    ["sample.NotNull"] if generic_field_required else []
                                ),
                                source_ref=generic_base_ref,
                            )
                        ],
                        source_ref=generic_base_ref,
                    )
                ]
                if response_mode != "plain"
                else []
            ),
        ],
    )
    entry_source_id = f"{interface_type}#execute"
    entry = EntryPoint(
        entry_id=f"facade:{entry_source_id}",
        system_id=system_id,
        kind=KnowledgeNodeKind.FACADE,
        display_name="AtomicFacade#execute",
        source_id=entry_source_id,
        source_path=str(source_file),
        request_type=request_type,
        response_type=response_type,
    )
    provider_ref = implementation_ref.model_copy(update={"symbol": entry_source_id})
    manifest = ScanManifest(
        scan_id=f"scan-{system_id}-{commit}",
        system_id=system_id,
        baseline=baseline,
        entries=[entry],
        dsf_profile=DsfClientProfile(
            system_id=system_id,
            client_name=f"{system_id}-client",
            routing_environment="qa",
            target_environment="test",
            status=DsfProfileStatus.CONFIRMED,
            source_refs=[provider_ref],
        ),
        dsf_operations=[
            DsfOperationDefinition(
                operation_id=f"dsf:{system_id}:execute",
                provider_system_id=system_id,
                gs_name=f"{system_id}-service",
                service_name=interface_type,
                version="1.0.0",
                action="execute",
                request_type=request_type,
                response_type=response_type,
                mutability=DsfOperationMutability.WRITE,
                source_refs=[provider_ref],
            )
        ],
        semantic_analysis=analysis,
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_scan_bundle(manifest, ProgramCaseAnalysisBuilder().build(manifest))
    application.store.update_source_baseline(system_id, baseline)
    artifacts.publish_latest(system_id, manifest.scan_id)


def _entry_candidate(application: OpenTestApplication, system_id: str) -> CandidateOperation:
    """取得与Facade Entry唯一关联的具体实现Candidate。

    Args:
        application: 已发布通用扫描的应用。
        system_id: Candidate所属系统。

    Returns:
        带Entry、实现symbol和完整DTO定义的当前Candidate。
    """

    candidates = application.candidate_operation_catalog(system_id).candidates
    return next(candidate for candidate in candidates if candidate.entry_ids)


def _publish_closed_business_generic_scan(
    application: OpenTestApplication,
    system_id: str,
) -> None:
    """在通用扫描上发布一个Page<Payload>闭合对象响应字段。

    Args:
        application: 隔离知识仓库应用。
        system_id: 本次扫描独立所属系统。

    Side Effects:
        更新测试Java源码并原子发布一个新的latest scan bundle。
    """

    _publish_atomic_scan(application, system_id)
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read(system_id, "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    response_type = next(
        item for item in analysis.types if item.qualified_class_name == "sample.AtomicResponse"
    )
    page_type_name = "sample.Page"
    page_ref = response_type.source_ref.model_copy(update={"symbol": page_type_name})
    paged_response = response_type.model_copy(
        update={
            "fields": [
                *response_type.fields,
                SemanticFieldDefinition(
                    field_name="page",
                    declared_type="Page<AtomicPayload>",
                    referenced_type="sample.Page<sample.AtomicPayload>",
                    source_ref=response_type.source_ref,
                ),
            ]
        }
    )
    page_type = SemanticTypeDefinition(
        symbol_id=page_type_name,
        qualified_class_name=page_type_name,
        simple_name="Page",
        fields=[
            SemanticFieldDefinition(
                field_name="items",
                declared_type="java.util.List<T>",
                referenced_type="T",
                collection=True,
                source_ref=page_ref,
            ),
            SemanticFieldDefinition(
                field_name="pageNo",
                declared_type="int",
                source_ref=page_ref,
            ),
        ],
        source_ref=page_ref,
    )
    generic_analysis = analysis.model_copy(
        update={
            "types": [
                paged_response
                if item.qualified_class_name == paged_response.qualified_class_name
                else item
                for item in analysis.types
            ]
            + [page_type]
        }
    )
    generic_manifest = manifest.model_copy(
        update={
            "scan_id": f"scan-{system_id}-closed-business-generic",
            "semantic_analysis": generic_analysis,
        }
    )
    artifacts.write_scan_bundle(
        generic_manifest,
        ProgramCaseAnalysisBuilder().build(generic_manifest),
    )
    artifacts.publish_latest(system_id, generic_manifest.scan_id)


def _publish_generic_root_scan(
    application: OpenTestApplication,
    system_id: str,
    concrete_return_type: str,
) -> None:
    """Publish a scan whose facade returns one exact raw or unclosed generic use.

    Args:
        application: Isolated OpenTest application and knowledge root.
        system_id: System receiving the synthetic latest scan.
        concrete_return_type: Exact Java return type used by interface and implementation methods.

    Side Effects:
        Replaces the system latest scan with the requested generic root evidence.
    """

    _publish_atomic_scan(application, system_id, response_mode="raw_generic")
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read(system_id, "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None

    # 方法根类型不携带“具体子DTO继承raw父类”的兼容语义，必须单独验证失败关闭。
    generic_methods = [
        method.model_copy(
            update={
                "return_type": concrete_return_type.rsplit(".", 1)[-1],
                "return_qualified_type": concrete_return_type,
            }
        )
        for method in analysis.methods
    ]
    generic_manifest = manifest.model_copy(
        update={
            "scan_id": f"scan-{system_id}-generic-root",
            "semantic_analysis": analysis.model_copy(update={"methods": generic_methods}),
        }
    )
    artifacts.write_scan_bundle(
        generic_manifest,
        ProgramCaseAnalysisBuilder().build(generic_manifest),
    )
    artifacts.publish_latest(system_id, generic_manifest.scan_id)


def _publish_wildcard_generic_parent_scan(
    application: OpenTestApplication,
    system_id: str,
) -> None:
    """Publish a concrete response that inherits an unclosed wildcard generic parent.

    Args:
        application: Isolated OpenTest application and knowledge root.
        system_id: System receiving the synthetic latest scan.

    Side Effects:
        Replaces the system latest scan with ``AtomicResponse extends BaseResponse<?>`` evidence.
    """

    _publish_atomic_scan(application, system_id, response_mode="raw_generic")
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read(system_id, "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None

    # 通配父类不是raw兼容边界，不能借可选T字段省略而形成可发布响应。
    response_type = next(
        item for item in analysis.types if item.qualified_class_name == "sample.AtomicResponse"
    )
    wildcard_response = response_type.model_copy(
        update={"base_types": ["sample.BaseResponse<?>"]}
    )
    wildcard_manifest = manifest.model_copy(
        update={
            "scan_id": f"scan-{system_id}-wildcard-parent",
            "semantic_analysis": analysis.model_copy(
                update={
                    "types": [
                        wildcard_response
                        if item.qualified_class_name == wildcard_response.qualified_class_name
                        else item
                        for item in analysis.types
                    ]
                }
            ),
        }
    )
    artifacts.write_scan_bundle(
        wildcard_manifest,
        ProgramCaseAnalysisBuilder().build(wildcard_manifest),
    )
    artifacts.publish_latest(system_id, wildcard_manifest.scan_id)


def _publish_inherited_field_collision_scan(
    application: OpenTestApplication,
    system_id: str,
    child_trace_type: str,
) -> None:
    """发布子DTO重声明父字段的通用扫描，验证继承合并不会静默覆盖类型冲突。

    Args:
        application: 隔离知识仓库应用。
        system_id: 本次扫描独立所属系统。
        child_trace_type: 子DTO中重声明traceId使用的Java类型。

    Side Effects:
        在通用扫描的请求DTO中增加同名字段并原子替换latest scan bundle。
    """

    _publish_atomic_scan(application, system_id)
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read(system_id, "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    request_type = next(
        item for item in analysis.types if item.qualified_class_name == "sample.AtomicRequest"
    )
    trace_reference = "java.lang.String" if child_trace_type == "String" else ""
    # 子类同名字段保留自己的源码证据，Operation层再决定同形合并或冲突阻塞。
    shadowed_request = request_type.model_copy(
        update={
            "fields": [
                *request_type.fields,
                SemanticFieldDefinition(
                    field_name="traceId",
                    declared_type=child_trace_type,
                    referenced_type=trace_reference,
                    source_ref=request_type.source_ref,
                ),
            ]
        }
    )
    collision_analysis = analysis.model_copy(
        update={
            "types": [
                shadowed_request
                if item.qualified_class_name == shadowed_request.qualified_class_name
                else item
                for item in analysis.types
            ]
        }
    )
    collision_manifest = manifest.model_copy(
        update={
            "scan_id": f"scan-{system_id}-shadow-{child_trace_type.lower()}",
            "semantic_analysis": collision_analysis,
        }
    )
    artifacts.write_scan_bundle(
        collision_manifest,
        ProgramCaseAnalysisBuilder().build(collision_manifest),
    )
    artifacts.publish_latest(system_id, collision_manifest.scan_id)


def _publish_restricted_projection_scan(
    application: OpenTestApplication,
    system_id: str,
    include_typed_conversion: bool = False,
) -> None:
    """发布一个只有未选外部父类和枚举不完整的通用扫描。

    Args:
        application: Pytest隔离的应用与知识目录。
        system_id: 持有PARTIAL Candidate的注册系统。
        include_typed_conversion: 是否加入Analyzer证明的integer访问器转换。

    Side Effects:
        以新scan代际替换latest，不发布能力或访问QA。
    """

    _publish_atomic_scan(application, system_id)
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read(system_id, "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    response_type = next(
        item for item in analysis.types if item.qualified_class_name == "sample.AtomicResponse"
    )
    external_enum_name = "external.contract.ExternalStateEnum"
    external_enum_ref = response_type.source_ref.model_copy(update={"symbol": external_enum_name})
    partial_response = response_type.model_copy(
        update={
            "fields": [
                *response_type.fields,
                SemanticFieldDefinition(
                    field_name="externalState",
                    declared_type="ExternalStateEnum",
                    referenced_type=external_enum_name,
                    source_ref=response_type.source_ref,
                ),
            ]
        }
    )
    partial_enum = SemanticTypeDefinition(
        symbol_id=external_enum_name,
        qualified_class_name=external_enum_name,
        simple_name="ExternalStateEnum",
        kind="enum",
        source_ref=external_enum_ref,
        resolution_status=SemanticResolutionStatus.PARTIAL,
    )
    getter_symbol = "sample.AtomicResponse#getExternalState()"
    getter_ref = response_type.source_ref.model_copy(update={"symbol": getter_symbol, "line": 2})
    converter_ref = response_type.source_ref.model_copy(
        update={"symbol": "external.contract.ExternalStateEnum#getCode()", "line": 3}
    )
    conversion_methods = (
        [
            SemanticMethodDefinition(
                symbol_id=getter_symbol,
                qualified_class_name="sample.AtomicResponse",
                method_name="getExternalState",
                return_type="Integer",
                return_qualified_type="java.lang.Integer",
                owner_type_kind="class",
                has_executable_body=True,
                source_ref=getter_ref,
            )
        ]
        if include_typed_conversion
        else []
    )
    conversions = (
        [
            SemanticFieldConversionEvidence(
                evidence_id="field-conversion:atomic-response:external-state",
                mapper_method_symbol_id=getter_symbol,
                target_type="sample.AtomicResponse",
                target_field_path="externalState",
                conversion_kind="ACCESSOR_RETURN",
                serialized_java_type="java.lang.Integer",
                serialized_schema_type="integer",
                converter_method_symbol_id=(
                    "external.contract.ExternalStateEnum#getCode()"
                ),
                source_refs=[getter_ref, converter_ref],
            )
        ]
        if include_typed_conversion
        else []
    )
    partial_analysis = analysis.model_copy(
        update={
            "methods": [*analysis.methods, *conversion_methods],
            "types": [
                partial_response
                if item.qualified_class_name == partial_response.qualified_class_name
                else item
                for item in analysis.types
                if item.qualified_class_name != "sample.BaseRequest"
            ]
            + [partial_enum],
            "field_conversions": conversions,
        }
    )
    partial_manifest = manifest.model_copy(
        update={
            "scan_id": f"scan-{system_id}-restricted-projection",
            "semantic_analysis": partial_analysis,
        }
    )
    artifacts.write_scan_bundle(
        partial_manifest,
        ProgramCaseAnalysisBuilder().build(partial_manifest),
    )
    artifacts.publish_latest(system_id, partial_manifest.scan_id)


def _candidate_ref(candidate: CandidateOperation) -> CandidateRef:
    """冻结当前Candidate全部发布相关源码事实。

    Args:
        candidate: 当前latest具体方法Candidate。

    Returns:
        不省略DTO定义的V2 CandidateRef。
    """

    return CandidateRef(
        source_system_id=candidate.system_id,
        candidate_id=candidate.candidate_id,
        source_scan_id=candidate.source_scan_id,
        source_baseline=candidate.source_baseline,
        candidate_signature=candidate.method_signature,
        request_dto_types=candidate.request_dto_types,
        response_dto_type=candidate.response_dto_type,
        dto_definitions=candidate.dto_definitions,
        field_conversions=candidate.field_conversions,
    )


def _submission(
    application: OpenTestApplication,
    system_id: str,
    request_id: str = "publish-atomic-request-0001",
) -> CapabilityDraftSubmission:
    """基于当前Candidate和现有Operation构造完整通用V2草稿。

    Args:
        application: 已发布通用扫描的应用。
        system_id: Candidate与Operation共同所属系统。
        request_id: 幂等发布请求身份。

    Returns:
        输入输出根均与现有Operation路径和类型一致的草稿。
    """

    candidate = _entry_candidate(application, system_id)
    operation = next(
        item
        for item in application.operation_catalog.derive(system_id)
        if item.source_entry_ids
    )
    return CapabilityDraftSubmission(
        publication_request_id=request_id,
        candidate_ref=_candidate_ref(candidate),
        provider_operation_ref=ProviderOperationRef(
            source_system_id=system_id,
            operation_id=operation.operation_id,
            source_scan_id=operation.source_scan_id,
        ),
        business_name="执行通用原子操作",
        business_purpose="以程序验证的请求标识执行一个固定原子操作并输出引用事实。",
        input_schema={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
            "additionalProperties": False,
        },
        input_mapping={"request_id": "requestId"},
        output_fact_schema={
            "type": "object",
            "properties": {"reference_id": {"type": "string"}},
            "required": ["reference_id"],
            "additionalProperties": False,
        },
        output_mapping={"reference_id": "output.referenceId"},
    )


def _configure_real_local_binding(application: OpenTestApplication, system_id: str) -> None:
    """通过生产本地设置存储写入所属系统0600 QA绑定。

    Args:
        application: 隔离应用。
        system_id: Operation所属系统。

    Side Effects:
        写入Git忽略的本地QA文件，不写正式能力目录。
    """

    application.local_settings.write(system_id, "phase3-local-token", "http://qa.example/gateway")


def test_publish_uses_existing_operation_without_executing_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功发布只保存Operation引用，不能调用执行服务或泄露本地/provider值。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
        monkeypatch: 用于把任何意外执行立即转成测试失败。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")

    def reject_execution(*_args: object, **_kwargs: object) -> None:
        """Reject any accidental QA execution during publication.

        Raises:
            AssertionError: Always, because stage 3 is validation-only.
        """

        raise AssertionError("publication must not execute QA")

    monkeypatch.setattr(application.operations, "execute", reject_execution)
    result = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app"),
    )

    assert result.status == "PUBLISHED"
    assert result.capability is not None
    candidate = _entry_candidate(application, "atomic-app")
    assert {definition.qualified_type for definition in candidate.dto_definitions} == {
        "sample.AtomicRequest",
        "sample.AtomicPayload",
        "sample.BaseRequest",
        "sample.AtomicResponse",
    }
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    assert operation.input_schema == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert set(operation.publication_input_schema["properties"]) == {
        "requestId",
        "payload",
        "traceId",
    }
    assert "output" in operation.publication_output_schema["properties"]
    assert result.capability.provider_operation_ref.operation_id.startswith("facade:")
    registry_path = application.store.system_root("atomic-app") / "capabilities/published.yaml"
    registry_text = registry_path.read_text(encoding="utf-8")
    assert "phase3-local-token" not in registry_text
    assert "service_name:" not in registry_text
    assert "provider_system_id:" not in registry_text
    assert "provider_kind:" not in registry_text
    assert not (application.knowledge_root / ".opentest/operation-executions").exists()


def test_identical_inherited_field_declaration_is_coalesced(
    tmp_path: Path,
) -> None:
    """子父DTO重复声明同形JSON字段时应只保留一个可发布属性。

    Args:
        tmp_path: Pytest隔离知识、源码和扫描资产目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_inherited_field_collision_scan(application, "atomic-app", "String")

    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    request_properties = operation.publication_input_schema["properties"]

    assert request_properties["traceId"] == {"type": "string"}
    assert list(request_properties).count("traceId") == 1


def test_conflicting_inherited_field_declaration_remains_fail_closed(
    tmp_path: Path,
) -> None:
    """子父DTO同名字段形状冲突时必须阻止Operation发布Schema形成。

    Args:
        tmp_path: Pytest隔离知识、源码和扫描资产目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_inherited_field_collision_scan(application, "atomic-app", "int")

    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )

    assert operation.publication_input_schema == {}


def test_generic_parent_response_produces_closed_candidate_and_operation_schema(
    tmp_path: Path,
) -> None:
    """单形参泛型父响应应按具体实参冻结Candidate并通过正式发布门禁。

    Args:
        tmp_path: Pytest隔离知识、源码和能力注册表目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app", response_mode="bound_generic")
    _configure_real_local_binding(application, "atomic-app")

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    result = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app", "publish-generic-response-0001"),
    )

    # Candidate冻结专门化父DTO，不能以CURRENT状态继续携带未绑定类型变量。
    assert candidate.status.value == "CURRENT"
    assert "BLOCKED_CANDIDATE_DTO_UNRESOLVED:T" not in candidate.blockers
    generic_definition = next(
        definition
        for definition in candidate.dto_definitions
        if definition.qualified_type == "sample.BaseResponse<java.lang.String>"
    )
    assert generic_definition.fields[0].declared_type == "java.lang.String"
    assert generic_definition.fields[0].referenced_type == "java.lang.String"

    # Operation输出必须同时包含子响应字段和父响应中已专门化的数据字段。
    payload_properties = operation.publication_output_schema["properties"]["output"]["properties"]
    assert payload_properties["data"] == {"type": "string"}
    assert payload_properties["referenceId"] == {"type": "string"}
    assert result.status == "PUBLISHED"


def test_closed_business_generic_wrapper_is_published_as_recursive_object(
    tmp_path: Path,
) -> None:
    """Page<Payload>证据完整时应递归闭合为对象，不能当数组或透明Payload。

    Args:
        tmp_path: Pytest隔离知识、源码和能力注册表目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_closed_business_generic_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    result = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app", "publish-business-generic-0001"),
    )

    assert candidate.status.value == "CURRENT"
    page_definition = next(
        definition
        for definition in candidate.dto_definitions
        if definition.qualified_type == "sample.Page<sample.AtomicPayload>"
    )
    assert page_definition.fields[0].declared_type == "java.util.List<sample.AtomicPayload>"
    payload_schema = operation.publication_output_schema["properties"]["output"]
    page_schema = payload_schema["properties"]["page"]
    assert page_schema["type"] == "object"
    assert page_schema["properties"]["items"]["type"] == "array"
    assert page_schema["properties"]["items"]["items"]["properties"]["itemCode"] == {
        "type": "string"
    }
    assert result.status == "PUBLISHED"


def test_restricted_projection_traverses_closed_wrapper_and_inherited_selected_field() -> None:
    """受限投影可穿过闭合业务泛型，但仍拒绝选中的partial枚举字段。

    Returns:
        None；从Page<Entity>继承基类的resolved标识可证明，partial状态不可证明时通过。
    """

    reference = SourceReference(path="GenericProjection.java", symbol="sample.QueryFacade#queryList")
    response_type = "sample.OrderListResponse"
    page_type = "sample.Page<sample.Order>"
    order_type = "sample.Order"
    core_type = "sample.CoreOrder"
    generic_base_type = "sample.BaseVO<java.lang.Long>"
    enum_type = "external.OrderStateEnum"
    candidate = CandidateOperation(
        candidate_id="candidate:generic-app:sample.QueryFacadeImpl#queryList(sample.QueryRequest)",
        system_id="generic-app",
        source_scan_id="scan-generic-projection",
        source_baseline=SourceBaseline(source_path="/tmp/generic-source", commit="generic-v1"),
        kind=CandidateOperationKind.FACADE,
        status=CandidateOperationStatus.PARTIAL,
        qualified_name="sample.QueryFacadeImpl#queryList",
        method_signature="sample.QueryFacadeImpl#queryList(sample.QueryRequest): sample.OrderListResponse",
        parameter_names=["request"],
        parameter_types=["sample.QueryRequest"],
        return_type=response_type,
        request_dto_types=["sample.QueryRequest"],
        response_dto_type=response_type,
        dto_definitions=[
            CandidateDtoDefinition(
                qualified_type=response_type,
                fields=[
                    CandidateDtoField(
                        field_name="list",
                        declared_type="Page<Order>",
                        referenced_type=page_type,
                        source_ref=reference,
                    )
                ],
                source_ref=reference,
            ),
            CandidateDtoDefinition(
                qualified_type=page_type,
                fields=[
                    CandidateDtoField(
                        field_name="pageList",
                        declared_type="java.util.List<sample.Order>",
                        referenced_type=order_type,
                        collection=True,
                        source_ref=reference,
                    )
                ],
                source_ref=reference,
            ),
            CandidateDtoDefinition(
                qualified_type=order_type,
                base_types=[core_type],
                fields=[
                    CandidateDtoField(
                        field_name="orderState",
                        declared_type="OrderStateEnum",
                        referenced_type=enum_type,
                        source_ref=reference,
                        resolution_status=SemanticResolutionStatus.PARTIAL,
                    )
                ],
                source_ref=reference,
            ),
            CandidateDtoDefinition(
                qualified_type=core_type,
                base_types=[generic_base_type],
                fields=[
                    CandidateDtoField(
                        field_name="orderSerialNo",
                        declared_type="String",
                        referenced_type="java.lang.String",
                        source_ref=reference,
                    )
                ],
                source_ref=reference,
            ),
            CandidateDtoDefinition(
                qualified_type=generic_base_type,
                fields=[],
                source_ref=reference,
            ),
        ],
        source_ref=reference,
        implementation_symbol_id="sample.QueryFacadeImpl#queryList(sample.QueryRequest)",
        entry_ids=["facade:sample.QueryFacade#queryList"],
        blockers=[
            f"BLOCKED_CANDIDATE_DTO_FIELD_PARTIAL:{order_type}.orderState",
            f"BLOCKED_CANDIDATE_DTO_UNRESOLVED:{enum_type}",
            f"BLOCKED_CANDIDATE_DTO_GENERIC_BINDING_UNRESOLVED:{generic_base_type}",
        ],
    )
    identity_only_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"orderSerialNo": {"type": "string"}},
            "required": ["orderSerialNo"],
            "additionalProperties": False,
        },
    }
    stateful_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "orderSerialNo": {"type": "string"},
                "orderState": {"type": "integer"},
            },
            "required": ["orderSerialNo", "orderState"],
            "additionalProperties": False,
        },
    }

    # 未闭合的泛型基类不影响在其他resolved父类中声明的精确标识字段。
    restricted_surface = candidate_has_restricted_projection_surface(candidate)
    identity_evidence = candidate_projection_path_evidence(
        candidate,
        "output.list.pageList",
        identity_only_schema,
        "output",
    )
    state_evidence = candidate_projection_path_evidence(
        candidate,
        "output.list.pageList",
        stateful_schema,
        "output",
    )
    typed_candidate = candidate.model_copy(
        update={
            "field_conversions": [
                SemanticFieldConversionEvidence(
                    evidence_id="field-conversion:generic-order-state",
                    mapper_method_symbol_id=(
                        "sample.QueryFacadeImpl#queryList(sample.QueryRequest)"
                    ),
                    target_type=order_type,
                    target_field_path="orderState",
                    conversion_kind="MAPPER_SETTER",
                    serialized_java_type="java.lang.Integer",
                    serialized_schema_type="integer",
                    converter_method_symbol_id="sample.OrderStateConverter#toCode(sample.Order)",
                    source_refs=[
                        reference.model_copy(update={"symbol": "sample.OrderMapper#setOrderState"}),
                        reference.model_copy(update={"symbol": "sample.OrderStateConverter#toCode"}),
                    ],
                )
            ]
        }
    )
    typed_state_evidence = candidate_projection_path_evidence(
        typed_candidate,
        "output.list.pageList",
        stateful_schema,
        "output",
    )

    assert restricted_surface
    assert identity_evidence == reference
    assert state_evidence is None
    assert typed_state_evidence is not None


def test_optional_raw_generic_field_is_evidence_only_and_cannot_enter_mapping_schema(
    tmp_path: Path,
) -> None:
    """raw父类的可选裸变量字段可保留证据，但不得阻塞其他闭合输出字段发布。

    Args:
        tmp_path: Pytest隔离知识、源码和能力注册表目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app", response_mode="raw_generic")
    _configure_real_local_binding(application, "atomic-app")

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    result = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app", "publish-raw-generic-response-0001"),
    )

    # Candidate仍冻结raw字段源码证据，发布面只排除无法证明JSON形状的可选变量字段。
    assert candidate.status.value == "CURRENT"
    raw_definition = next(
        definition
        for definition in candidate.dto_definitions
        if definition.qualified_type == "sample.BaseResponse"
    )
    assert raw_definition.fields[0].declared_type == "T"
    payload_properties = operation.publication_output_schema["properties"]["output"]["properties"]
    assert "data" not in payload_properties
    assert payload_properties["referenceId"] == {"type": "string"}
    assert result.status == "PUBLISHED"


def test_required_raw_generic_field_remains_fail_closed(
    tmp_path: Path,
) -> None:
    """raw父类裸变量字段有运行时必填证据时必须阻塞Candidate和能力发布。

    Args:
        tmp_path: Pytest隔离知识、源码和能力注册表目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(
        application,
        "atomic-app",
        response_mode="raw_generic",
        generic_field_required=True,
    )
    _configure_real_local_binding(application, "atomic-app")

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    result = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app", "publish-required-raw-generic-0001"),
    )

    assert candidate.status.value == "PARTIAL"
    assert (
        "BLOCKED_CANDIDATE_DTO_FIELD_UNRESOLVED:sample.BaseResponse.data"
        in candidate.blockers
    )
    assert operation.publication_output_schema == {}
    assert result.status == "BLOCKED"
    assert "CANDIDATE_METADATA_PARTIAL" in {issue.code for issue in result.issues}


def test_partial_candidate_publishes_only_analyzer_proven_selected_paths(
    tmp_path: Path,
) -> None:
    """PARTIAL Candidate可发布受限投影，但不能改写候选整体状态。

    Args:
        tmp_path: Pytest隔离的知识、源码、环境和能力目录。

    Returns:
        None；未选外部父类/枚举保留PARTIAL，直接resolved字段可发布并重验时通过。

    Side Effects:
        只向临时Git真相发布一个Published能力，不执行QA。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_restricted_projection_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    result = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app", "publish-restricted-projection-0001"),
    )

    assert candidate.status.value == "PARTIAL"
    assert set(candidate.blockers) == {
        "BLOCKED_CANDIDATE_DTO_PARTIAL:external.contract.ExternalStateEnum",
        "BLOCKED_CANDIDATE_DTO_UNRESOLVED:sample.BaseRequest",
    }
    assert operation.publication_input_schema == {}
    assert operation.publication_output_schema == {}
    assert result.status == "PUBLISHED"
    assert result.capability is not None
    assert (
        application.published_capabilities.get_current(
            "atomic-app",
            result.capability.capability_id,
        )
        == result.capability
    )
    # 运行投影也只保留Published显式字段，未选外部字段不进入Fact。
    projected = project_value_to_schema(
        {
            "type": "object",
            "properties": {"referenceId": {"type": "string"}},
            "required": ["referenceId"],
            "additionalProperties": False,
        },
        {"referenceId": "ref-1", "externalState": "UNKNOWN"},
    )
    assert projected == {"referenceId": "ref-1"}


def test_partial_candidate_publishes_exact_typed_output_conversion(tmp_path: Path) -> None:
    """PARTIAL枚举字段只有携带current typed converter证据时才可投影为integer。

    Args:
        tmp_path: Pytest隔离源码、scan和Published目录。

    Side Effects:
        只发布临时受限能力；不读取Token值或执行QA。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_restricted_projection_scan(
        application,
        "atomic-app",
        include_typed_conversion=True,
    )
    base_submission = _submission(
        application,
        "atomic-app",
        "publish-typed-conversion-0001",
    )
    submission = base_submission.model_copy(
        update={
            "output_fact_schema": {
                "type": "object",
                "properties": {"external_state": {"type": "integer"}},
                "required": ["external_state"],
                "additionalProperties": False,
            },
            "output_mapping": {"external_state": "output.externalState"},
        }
    )

    result = application.publish_operation_capability("atomic-app", submission)

    assert result.status == "PUBLISHED"
    assert result.capability is not None
    assert result.capability.candidate_ref.field_conversions
    assert (
        application.published_capabilities.get_current(
            "atomic-app",
            result.capability.capability_id,
        )
        == result.capability
    )


def test_partial_candidate_rejects_unfrozen_typed_conversion_proof(tmp_path: Path) -> None:
    """草稿遗漏Analyzer conversion快照时不得靠current Candidate隐式补证。

    Args:
        tmp_path: Pytest隔离源码、scan和Published目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_restricted_projection_scan(
        application,
        "atomic-app",
        include_typed_conversion=True,
    )
    base_submission = _submission(
        application,
        "atomic-app",
        "publish-unfrozen-conversion-0001",
    )
    stale_reference = base_submission.candidate_ref.model_copy(
        update={"field_conversions": []}
    )
    submission = base_submission.model_copy(update={"candidate_ref": stale_reference})

    result = application.publish_operation_capability("atomic-app", submission)

    assert result.status == "BLOCKED"
    assert "CANDIDATE_DTO_DRIFT" in {issue.code for issue in result.issues}
    application.close()


@pytest.mark.parametrize(
    ("input_schema", "input_mapping", "output_schema", "output_mapping"),
    [
        (
            {
                "type": "object",
                "properties": {"trace_id": {"type": "string"}},
                "required": ["trace_id"],
                "additionalProperties": False,
            },
            {"trace_id": "traceId"},
            {
                "type": "object",
                "properties": {"reference_id": {"type": "string"}},
                "required": ["reference_id"],
                "additionalProperties": False,
            },
            {"reference_id": "output.referenceId"},
        ),
        (
            {
                "type": "object",
                "properties": {"request_id": {"type": "string"}},
                "required": ["request_id"],
                "additionalProperties": False,
            },
            {"request_id": "requestId"},
            {
                "type": "object",
                "properties": {"state": {"type": "string"}},
                "required": ["state"],
                "additionalProperties": False,
            },
            {"state": "output.externalState"},
        ),
    ],
)
def test_partial_candidate_rejects_unproven_selected_path(
    tmp_path: Path,
    input_schema: dict[str, object],
    input_mapping: dict[str, str],
    output_schema: dict[str, object],
    output_mapping: dict[str, str],
) -> None:
    """受限投影必须拒绝落在未解析外部父类或枚举上的选中路径。

    Args:
        tmp_path: Pytest隔离知识、源码和能力目录。
        input_schema: 本轮草稿选中的逻辑输入形状。
        input_mapping: 逻辑输入到provider的精确路径。
        output_schema: 本轮草稿选中的逻辑输出形状。
        output_mapping: provider结果到逻辑输出的精确路径。

    Returns:
        None；任一selected path不可程序证明时发布保持BLOCKED。

    Side Effects:
        只校验临时草稿，不写Published真相或访问QA。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_restricted_projection_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")
    base = _submission(application, "atomic-app", "publish-unproven-projection-0001")
    submission = base.model_copy(
        update={
            "input_schema": input_schema,
            "input_mapping": input_mapping,
            "output_fact_schema": output_schema,
            "output_mapping": output_mapping,
        }
    )

    result = application.publish_operation_capability("atomic-app", submission)

    assert result.status == "BLOCKED"
    assert "CANDIDATE_SELECTED_PATH_UNPROVEN" in {issue.code for issue in result.issues}
    assert not (
        application.store.system_root("atomic-app") / "capabilities/published.yaml"
    ).exists()
    application.close()


@pytest.mark.parametrize(
    "concrete_return_type",
    [
        "sample.BaseResponse",
        "sample.BaseResponse<?>",
        "sample.BaseResponse<java.util.List<java.lang.String>>",
        "sample.BaseResponse<java.lang.String,java.lang.Integer>",
    ],
)
def test_raw_or_unclosed_generic_method_root_remains_fail_closed(
    tmp_path: Path,
    concrete_return_type: str,
) -> None:
    """Method roots cannot use the raw-parent compatibility path to hide generic uncertainty.

    Args:
        tmp_path: Pytest isolated knowledge, source, and scan root.
        concrete_return_type: Raw, wildcard, nested, or multi-argument generic return use.
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_generic_root_scan(application, "atomic-app", concrete_return_type)

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )

    assert candidate.status.value == "PARTIAL"
    assert operation.publication_output_schema == {}


def test_wildcard_generic_parent_remains_fail_closed(tmp_path: Path) -> None:
    """A wildcard parent is not equivalent to a deliberately raw inherited compatibility DTO.

    Args:
        tmp_path: Pytest isolated knowledge, source, and scan root.
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_wildcard_generic_parent_scan(application, "atomic-app")

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )

    assert candidate.status.value == "PARTIAL"
    assert operation.publication_output_schema == {}


def test_closed_business_generic_reference_requires_matching_owner_and_argument() -> None:
    """Closed business wrappers accept simple-to-FQN resolution but reject package drift."""

    assert java_closed_business_generic_reference(
        "Page<Payload>",
        "sample.Page<sample.Payload>",
    )
    assert not java_closed_business_generic_reference(
        "a.Page<a.Payload>",
        "b.Page<b.Other>",
    )
    assert not java_closed_business_generic_reference(
        "a.Page<a.Payload>",
        "a.Page<b.Other>",
    )


def test_top_level_unbound_type_variable_remains_unresolved(
    tmp_path: Path,
) -> None:
    """方法顶层返回变量没有具体owner绑定时不得借Entry展示类型猜测响应Schema。

    Args:
        tmp_path: Pytest隔离知识、源码和扫描资产目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read("atomic-app", "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    unbound_methods = [
        (
            method.model_copy(update={"return_type": "T", "return_qualified_type": "T"})
            if method.owner_type_kind == "class"
            else method
        )
        for method in analysis.methods
    ]
    unbound_manifest = manifest.model_copy(
        update={
            "scan_id": "scan-atomic-app-unbound-top-level",
            "semantic_analysis": analysis.model_copy(update={"methods": unbound_methods}),
        }
    )
    artifacts.write_scan_bundle(
        unbound_manifest,
        ProgramCaseAnalysisBuilder().build(unbound_manifest),
    )
    artifacts.publish_latest("atomic-app", unbound_manifest.scan_id)

    candidate = _entry_candidate(application, "atomic-app")

    assert candidate.status.value == "PARTIAL"
    assert "BLOCKED_CANDIDATE_DTO_UNRESOLVED:T" in candidate.blockers


def test_publication_request_is_idempotent_and_conflicting_retry_is_blocked(tmp_path: Path) -> None:
    """相同请求重试返回原能力，修改载荷则阻塞且不覆盖Git。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")
    submission = _submission(application, "atomic-app")

    first = application.publish_operation_capability("atomic-app", submission)
    repeated = application.publish_operation_capability("atomic-app", submission)
    conflict = application.publish_operation_capability(
        "atomic-app",
        submission.model_copy(update={"business_purpose": "使用同一ID提交不同语义。"}),
    )

    assert first.capability is not None
    assert repeated.capability == first.capability
    assert conflict.status == "BLOCKED"
    assert [issue.code for issue in conflict.issues] == [
        "CAPABILITY_PUBLICATION_REQUEST_CONFLICT"
    ]
    assert len(application.published_capability_registry("atomic-app").capabilities) == 1


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda draft: draft.model_copy(
                update={
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "request_id": {"type": "string", "default": "sample"}
                        },
                        "required": ["request_id"],
                        "additionalProperties": False,
                    }
                }
            ),
            "CAPABILITY_SCHEMA_INVALID",
        ),
        (
            lambda draft: draft.model_copy(
                update={"input_mapping": {"request_id": "missingPath"}}
            ),
            "CAPABILITY_MAPPING_TARGET_UNKNOWN",
        ),
        (
            lambda draft: draft.model_copy(
                update={
                    "candidate_ref": draft.candidate_ref.model_copy(
                        update={"source_scan_id": "scan-atomic-app-stale"}
                    )
                }
            ),
            "CANDIDATE_SOURCE_DRIFT",
        ),
    ],
)
def test_schema_mapping_and_source_drift_block_publication(
    tmp_path: Path,
    mutator: object,
    expected_code: str,
) -> None:
    """样本Schema、未知映射和旧源码引用均不能写入正式目录。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
        mutator: 只改变一个受检边界的草稿转换函数。
        expected_code: 对应确定性阻塞码。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")
    submission = _submission(application, "atomic-app")

    changed = mutator(submission)  # type: ignore[operator]
    result = application.publish_operation_capability("atomic-app", changed)

    assert result.status == "BLOCKED"
    assert expected_code in {issue.code for issue in result.issues}
    assert not (
        application.store.system_root("atomic-app") / "capabilities/published.yaml"
    ).exists()


def test_missing_local_value_does_not_block_publication_but_unproven_operation_does(
    tmp_path: Path,
) -> None:
    """离线发布只冻结安全绑定路径，而无共同Entry/symbol仍不得借用Operation。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    submission = _submission(application, "atomic-app")

    offline_publication = application.publish_operation_capability("atomic-app", submission)
    inspect_candidate = next(
        candidate
        for candidate in application.candidate_operation_catalog("atomic-app").candidates
        if "#inspect" in candidate.qualified_name
    )
    _configure_real_local_binding(application, "atomic-app")
    unproven = application.publish_operation_capability(
        "atomic-app",
        submission.model_copy(
            update={
                "publication_request_id": "publish-atomic-request-0002",
                "candidate_ref": _candidate_ref(inspect_candidate),
            }
        ),
    )

    assert offline_publication.status == "PUBLISHED"
    assert offline_publication.capability is not None
    assert offline_publication.capability.required_local_bindings == [
        "values.tool_environment.LABRADOR_TOKEN"
    ]
    assert "CAPABILITY_OPERATION_UNPROVEN" in {issue.code for issue in unproven.issues}
    assert len(application.published_capability_registry("atomic-app").capabilities) == 1


def test_missing_nested_dto_keeps_candidate_partial_and_blocks_publication(tmp_path: Path) -> None:
    """缺失嵌套DTO不能被猜成string或空object后发布。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read("atomic-app", "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    incomplete_analysis = analysis.model_copy(
        update={
            "types": [
                item
                for item in analysis.types
                if item.qualified_class_name != "sample.AtomicPayload"
            ]
        }
    )
    incomplete_manifest = manifest.model_copy(
        update={
            "scan_id": "scan-atomic-app-incomplete-dto",
            "semantic_analysis": incomplete_analysis,
        }
    )
    artifacts.write_scan_bundle(
        incomplete_manifest,
        ProgramCaseAnalysisBuilder().build(incomplete_manifest),
    )
    artifacts.publish_latest("atomic-app", incomplete_manifest.scan_id)
    _configure_real_local_binding(application, "atomic-app")
    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    submission = CapabilityDraftSubmission(
        **_submission(application, "atomic-app").model_dump(
            exclude={"candidate_ref", "provider_operation_ref"}
        ),
        candidate_ref=_candidate_ref(candidate),
        provider_operation_ref=ProviderOperationRef(
            source_system_id="atomic-app",
            operation_id=operation.operation_id,
            source_scan_id=operation.source_scan_id,
        ),
    )

    result = application.publish_operation_capability("atomic-app", submission)

    assert candidate.status.value == "PARTIAL"
    assert "BLOCKED_CANDIDATE_DTO_UNRESOLVED:sample.AtomicPayload" in candidate.blockers
    assert operation.publication_input_schema == {}
    assert "CANDIDATE_METADATA_PARTIAL" in {issue.code for issue in result.issues}
    assert "CAPABILITY_OPERATION_SCHEMA_INCOMPLETE" in {
        issue.code for issue in result.issues
    }
    assert not (
        application.store.system_root("atomic-app") / "capabilities/published.yaml"
    ).exists()


def test_map_and_mismatched_generic_wrapper_references_remain_fail_closed(
    tmp_path: Path,
) -> None:
    """Map与声明/解析不一致的业务包装即使标resolved也必须失败关闭。

    Args:
        tmp_path: Pytest隔离知识、源码和V2注册表目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest = artifacts.read("atomic-app", "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    request_type = next(
        item
        for item in analysis.types
        if item.qualified_class_name == "sample.AtomicRequest"
    )
    source_ref = request_type.source_ref
    unsafe_request_type = request_type.model_copy(
        update={
            "fields": [
                *request_type.fields,
                SemanticFieldDefinition(
                    field_name="payloadById",
                    declared_type="java.util.Map<java.lang.String, sample.AtomicPayload>",
                    referenced_type="sample.AtomicPayload",
                    collection=True,
                    source_ref=source_ref,
                ),
                SemanticFieldDefinition(
                    field_name="payloadPage",
                    declared_type="sample.Page<sample.AtomicPayload>",
                    referenced_type="sample.AtomicPayload",
                    source_ref=source_ref,
                ),
            ]
        }
    )
    unsafe_analysis = analysis.model_copy(
        update={
            "types": [
                unsafe_request_type
                if item.qualified_class_name == unsafe_request_type.qualified_class_name
                else item
                for item in analysis.types
            ]
        }
    )
    unsafe_manifest = manifest.model_copy(
        update={
            "scan_id": "scan-atomic-app-unsupported-generics",
            "semantic_analysis": unsafe_analysis,
        }
    )
    artifacts.write_scan_bundle(
        unsafe_manifest,
        ProgramCaseAnalysisBuilder().build(unsafe_manifest),
    )
    artifacts.publish_latest("atomic-app", unsafe_manifest.scan_id)
    _configure_real_local_binding(application, "atomic-app")

    candidate = _entry_candidate(application, "atomic-app")
    operation = next(
        item for item in application.operation_catalog.derive("atomic-app") if item.source_entry_ids
    )
    blockers = set(candidate.blockers)
    result = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app"),
    )

    assert candidate.status.value == "PARTIAL"
    assert blockers.issuperset(
        {
            "BLOCKED_CANDIDATE_DTO_FIELD_UNSUPPORTED:sample.AtomicRequest.payloadById",
            "BLOCKED_CANDIDATE_DTO_FIELD_UNSUPPORTED:sample.AtomicRequest.payloadPage",
        }
    )
    assert operation.publication_input_schema == {}
    assert result.status == "BLOCKED"
    assert "CAPABILITY_OPERATION_SCHEMA_INCOMPLETE" in {
        issue.code for issue in result.issues
    }
    assert not (
        application.store.system_root("atomic-app") / "capabilities/published.yaml"
    ).exists()


def test_direct_dependency_does_not_grant_cross_system_publication(tmp_path: Path) -> None:
    """consumer即使能搜索provider Candidate也只能由provider系统路由发布。

    Args:
        tmp_path: Pytest隔离多系统知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "consumer-app", "consumer-v1")
    _publish_atomic_scan(application, "provider-app", "provider-v1")
    provider_submission = _submission(application, "provider-app")

    result = application.publish_operation_capability("consumer-app", provider_submission)

    assert [issue.code for issue in result.issues] == ["CAPABILITY_SYSTEM_SCOPE_MISMATCH"]
    assert not (
        application.store.system_root("consumer-app") / "capabilities/published.yaml"
    ).exists()
    assert not (
        application.store.system_root("provider-app") / "capabilities/published.yaml"
    ).exists()


def test_legacy_registry_is_display_only_and_cannot_be_published_or_fetched(tmp_path: Path) -> None:
    """V1只返回摘要，不能混入V2 get或被阶段3原位追加。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")
    registry_path = application.store.system_root("atomic-app") / "capabilities/published.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        yaml.safe_dump(
            {
                "contract_version": "published-capability-registry/v1",
                "system_id": "atomic-app",
                "capabilities": [
                    {
                        "contract_version": "published-operation-capability/v1",
                        "capability_id": "published:legacy:one",
                        "system_id": "atomic-app",
                        "provider": {"service_name": "legacy-only"},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    registry = application.published_capability_registry("atomic-app")
    blocked = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app"),
    )

    assert registry.capabilities == []
    assert [item.status for item in registry.legacy_capabilities] == ["LEGACY_READ_ONLY"]
    assert [issue.code for issue in blocked.issues] == [
        "CAPABILITY_REGISTRY_LEGACY_READ_ONLY"
    ]
    with pytest.raises(KnowledgeNotFoundError, match="published V2 capability not found"):
        application.get_published_capability("atomic-app", "published:legacy:one")


def test_malformed_v2_registry_never_selects_duplicate_or_cross_system_records(tmp_path: Path) -> None:
    """手写V2重复请求或跨系统引用必须使整个正式目录读取失败。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    _configure_real_local_binding(application, "atomic-app")
    published = application.publish_operation_capability(
        "atomic-app",
        _submission(application, "atomic-app"),
    ).capability
    assert published is not None
    registry_path = application.store.system_root("atomic-app") / "capabilities/published.yaml"
    malformed = {
        "contract_version": "published-capability-registry/v2",
        "system_id": "atomic-app",
        "capabilities": [
            published.model_dump(mode="json"),
            published.model_copy(
                update={"capability_id": "published:atomic-app:another-id"}
            ).model_dump(mode="json"),
        ],
        "legacy_capabilities": [],
    }
    registry_path.write_text(yaml.safe_dump(malformed, sort_keys=False), encoding="utf-8")

    with pytest.raises(KnowledgeValidationError, match="invalid V2"):
        application.published_capability_registry("atomic-app")


def test_real_registered_refund_and_booking_sources_enforce_current_publication_gates(
    tmp_path: Path,
) -> None:
    """在正式registered/latest隔离副本中验证退款可发布且Booking仍服从真实门禁。

    Args:
        tmp_path: 承载正式知识、扫描与0600本地绑定的原样隔离副本。

    Side Effects:
        只向临时副本提交两个真实草稿；正式知识仓库始终只读且不执行QA。
    """

    project_root = Path(__file__).resolve().parents[2]
    formal_knowledge_root = project_root / "open-test-knowledge"
    isolated_knowledge_root = tmp_path / "open-test-knowledge"
    shutil.copytree(
        formal_knowledge_root,
        isolated_knowledge_root,
        ignore=shutil.ignore_patterns(".opentest", ".git", "__pycache__"),
    )
    # 只复制发布验证实际消费的正式latest、本地绑定和知识状态，不复制运行记录或Agent输出。
    for local_directory in ("scans", "environments", "knowledge-drafts"):
        source_directory = formal_knowledge_root / ".opentest" / local_directory
        if source_directory.exists():
            shutil.copytree(
                source_directory,
                isolated_knowledge_root / ".opentest" / local_directory,
            )
    application = OpenTestApplication(isolated_knowledge_root)
    refund_system_id = "ifightchainsaas.java.refund.core"
    booking_system_id = "ifightchainsaas.java.booking.core"
    execution_root = isolated_knowledge_root / ".opentest/operation-executions"
    executions_before = {
        path.relative_to(execution_root).as_posix(): path.read_bytes()
        for path in execution_root.rglob("*")
        if path.is_file()
    } if execution_root.exists() else {}
    refund_system = application.store.get_system(refund_system_id)
    booking_system = application.store.get_system(booking_system_id)
    if not Path(refund_system.source_path).is_dir() or not Path(booking_system.source_path).is_dir():
        pytest.skip("真实退款或Booking注册源码在当前机器不可用")

    # 正式latest必须直接提供三个被测入口；这里只读扫描产物，不向manifest注入目标名称。
    refund_candidates = application.candidate_operation_catalog(refund_system_id).candidates
    expected_refund_methods = {
        "com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel",
        "com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder",
        "com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshopSubmit",
    }
    selected_refund_candidates = {
        candidate.qualified_name: candidate
        for candidate in refund_candidates
        if candidate.qualified_name in expected_refund_methods
    }
    assert set(selected_refund_candidates) == expected_refund_methods
    assert all(candidate.entry_ids for candidate in selected_refund_candidates.values())

    # cancel的raw父类可选T保留证据但不再遮蔽其余闭合输入输出字段。
    refund_operations = {
        operation.operation_id: operation
        for operation in application.operation_catalog.derive(refund_system_id)
    }
    cancel_candidate = selected_refund_candidates[
        "com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel"
    ]
    cancel_operation = refund_operations[cancel_candidate.entry_ids[0]]
    assert cancel_candidate.status.value == "CURRENT"
    assert cancel_candidate.blockers == []
    assert cancel_operation.publication_output_schema["properties"]["output"]["properties"]
    refund_registry_path = (
        application.store.system_root(refund_system_id) / "capabilities/published.yaml"
    )
    refund_registry_before = (
        refund_registry_path.read_bytes() if refund_registry_path.exists() else None
    )
    refund_submission = CapabilityDraftSubmission(
        publication_request_id="real-refund-blocked-phase3",
        candidate_ref=_candidate_ref(cancel_candidate),
        provider_operation_ref=ProviderOperationRef(
            source_system_id=refund_system_id,
            operation_id=cancel_operation.operation_id,
            source_scan_id=cancel_operation.source_scan_id,
        ),
        business_name="真实退款取消原子操作",
        business_purpose="使用正式退款Candidate发布取消Action，不执行QA。",
        input_schema={
            "type": "object",
            "properties": {"refund_serial_no": {"type": "string"}},
            "required": ["refund_serial_no"],
            "additionalProperties": False,
        },
        input_mapping={"refund_serial_no": "refundSerialNo"},
        output_fact_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "code": {"type": "string"},
            },
            "required": ["success", "code"],
            "additionalProperties": False,
        },
        output_mapping={"success": "output.success", "code": "output.code"},
    )
    refund_result = application.publish_operation_capability(
        refund_system_id,
        refund_submission,
    )
    assert refund_result.status == "PUBLISHED"
    assert refund_result.issues == []
    assert (
        refund_registry_path.read_bytes() if refund_registry_path.exists() else None
    ) != refund_registry_before

    # Booking同样读取正式latest；本地Token缺失只影响显式Attempt，不阻止离线发布。
    booking_candidates = application.candidate_operation_catalog(booking_system_id).candidates
    booking_operations = {
        operation.operation_id: operation
        for operation in application.operation_catalog.derive(booking_system_id)
    }
    booking_candidate = next(
        candidate
        for candidate in booking_candidates
        if candidate.entry_ids and candidate.entry_ids[0] in booking_operations
    )
    booking_operation = booking_operations[booking_candidate.entry_ids[0]]
    booking_registry_path = (
        application.store.system_root(booking_system_id) / "capabilities/published.yaml"
    )
    booking_registry_before = (
        booking_registry_path.read_bytes() if booking_registry_path.exists() else None
    )
    booking_submission = refund_submission.model_copy(
        update={
            "publication_request_id": "real-booking-blocked-phase3",
            "candidate_ref": _candidate_ref(booking_candidate),
            "provider_operation_ref": ProviderOperationRef(
                source_system_id=booking_system_id,
                operation_id=booking_operation.operation_id,
                source_scan_id=booking_operation.source_scan_id,
            ),
            "business_name": "真实Booking原子操作",
            "business_purpose": "验证正式Booking离线发布只冻结本地绑定路径。",
        }
    )
    booking_result = application.publish_operation_capability(
        booking_system_id,
        booking_submission,
    )
    assert booking_result.status == "BLOCKED"
    assert "CAPABILITY_LOCAL_BINDING_MISSING" not in {
        issue.code for issue in booking_result.issues
    }
    assert "CAPABILITY_LOCAL_ENVIRONMENT_MISSING" not in {
        issue.code for issue in booking_result.issues
    }
    assert (
        booking_registry_path.read_bytes() if booking_registry_path.exists() else None
    ) == booking_registry_before
    executions_after = {
        path.relative_to(execution_root).as_posix(): path.read_bytes()
        for path in execution_root.rglob("*")
        if path.is_file()
    } if execution_root.exists() else {}
    assert executions_after == executions_before
