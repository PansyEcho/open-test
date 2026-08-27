"""验证阶段3只发布有真实源码与现有Operation证据的V2原子能力。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.foundation import OpenTestApplication
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.models import (
    CandidateOperation,
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
    SemanticMethodDefinition,
    SemanticTypeDefinition,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
)


def _publish_atomic_scan(
    application: OpenTestApplication,
    system_id: str,
    commit: str = "atomic-v1",
) -> None:
    """发布一个具有真实Java文件、完整DTO和唯一DSF Operation的通用扫描。

    Args:
        application: 隔离知识仓库应用。
        system_id: 本次扫描独立所属系统。
        commit: 用于漂移测试的源码基线标识。

    Side Effects:
        写入通用Java源码、注册系统并原子发布latest scan bundle。
    """

    source_root = application.knowledge_root.parent / f"source-{system_id}"
    source_file = source_root / "src/main/java/sample/AtomicFacadeImpl.java"
    source_file.parent.mkdir(parents=True)
    source_file.write_text(
        "package sample; "
        "interface AtomicFacade { AtomicResponse execute(AtomicRequest request); } "
        "class BaseRequest { String traceId; } "
        "class AtomicPayload { String itemCode; } "
        "class AtomicRequest extends BaseRequest { String requestId; AtomicPayload payload; } "
        "class AtomicResponse { String referenceId; } "
        "class AtomicFacadeImpl implements AtomicFacade { "
        "public AtomicResponse execute(AtomicRequest request) { return new AtomicResponse(); } "
        "public AtomicResponse inspect(AtomicRequest request) { return new AtomicResponse(); } }\n",
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


def test_missing_owner_local_binding_and_unproven_same_name_are_blocked(tmp_path: Path) -> None:
    """缺少所属系统绑定或无共同Entry/symbol时都不得借用现有Operation。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_atomic_scan(application, "atomic-app")
    submission = _submission(application, "atomic-app")

    missing_binding = application.publish_operation_capability("atomic-app", submission)
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

    assert "CAPABILITY_LOCAL_ENVIRONMENT_MISSING" in {
        issue.code for issue in missing_binding.issues
    }
    assert "CAPABILITY_OPERATION_UNPROVEN" in {issue.code for issue in unproven.issues}
    assert application.published_capability_registry("atomic-app").capabilities == []


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


def test_map_and_arbitrary_generic_wrappers_cannot_be_published_as_arrays(
    tmp_path: Path,
) -> None:
    """Map与Page等泛型包装即使旧分析标resolved也必须在发布端失败关闭。

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


def test_real_registered_refund_and_booking_sources_remain_truthfully_blocked(
    tmp_path: Path,
) -> None:
    """在正式registered/latest的隔离副本中验证真实系统不会被通用夹具冒充发布。

    Args:
        tmp_path: 承载正式知识、扫描与0600本地绑定的原样隔离副本。

    Side Effects:
        只向临时副本提交两个当前必然阻塞的真实草稿；正式知识仓库始终只读。
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
    assert all(
        candidate.status.value == "PARTIAL"
        and any("DTO_" in blocker for blocker in candidate.blockers)
        for candidate in selected_refund_candidates.values()
    )

    # 原始泛型T和未解析集合DTO使真实退款输出契约无法闭合，不能按方法名猜测后发布。
    refund_operations = {
        operation.operation_id: operation
        for operation in application.operation_catalog.derive(refund_system_id)
    }
    cancel_candidate = selected_refund_candidates[
        "com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel"
    ]
    cancel_operation = refund_operations[cancel_candidate.entry_ids[0]]
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
        business_purpose="验证正式退款Candidate在DTO证据不完整时保持阻塞。",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        input_mapping={},
        output_fact_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_mapping={},
    )
    refund_result = application.publish_operation_capability(
        refund_system_id,
        refund_submission,
    )
    assert refund_result.status == "BLOCKED"
    assert {issue.code for issue in refund_result.issues}.issuperset(
        {"CANDIDATE_METADATA_PARTIAL", "CAPABILITY_OPERATION_SCHEMA_INCOMPLETE"}
    )
    assert (
        refund_registry_path.read_bytes() if refund_registry_path.exists() else None
    ) == refund_registry_before

    # Booking同样读取正式latest；其本地Token缺失必须作为真实发布断点返回。
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
            "business_purpose": "验证正式Booking所属系统缺少本地Token时保持阻塞。",
        }
    )
    booking_result = application.publish_operation_capability(
        booking_system_id,
        booking_submission,
    )
    assert booking_result.status == "BLOCKED"
    assert "CAPABILITY_LOCAL_BINDING_MISSING" in {
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
