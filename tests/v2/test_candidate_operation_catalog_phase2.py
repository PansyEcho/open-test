"""验证阶段2候选发现面不扩大为跨系统执行权限。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml
from fastapi.testclient import TestClient

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.semantic_analysis import default_semantic_analyzer_path
from opentest.adapters.source_analysis import JavaStructureScanner, SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    CandidateOperation,
    CandidateRef,
    CaseVariantExecutionRequest,
    CapabilityDraftSubmission,
    EntryPoint,
    KnowledgeNodeKind,
    MqEntryFrameworkRule,
    ProviderOperationRef,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticFieldDefinition,
    SemanticMethodDefinition,
    SemanticTypeDefinition,
    SourceBaseline,
    SourceReference,
    SourceScanRequest,
    SystemDefinition,
    SystemDependencyBindingSubmission,
    SystemDependencyPurpose,
    SystemDependencyRole,
)


def _publish_generic_scan(
    application: OpenTestApplication,
    system_id: str,
    method_prefix: str,
    commit: str,
) -> None:
    """发布一个含真实接口/实现和DTO结构关系的通用扫描bundle。

    Args:
        application: 隔离知识仓库应用。
        system_id: 独立注册和扫描的系统ID。
        method_prefix: 用于区分consumer与provider候选的通用方法前缀。
        commit: 当前系统自己的源码基线标识。

    Side Effects:
        创建通用Java源码文件，并原子发布Manifest、Program Catalog、baseline和latest。
    """

    source_root = application.knowledge_root.parent / f"source-{system_id}"
    source_root.mkdir(parents=True)
    source_file = source_root / f"{method_prefix}FacadeImpl.java"
    source_file.write_text(
        f"class {method_prefix}FacadeImpl {{ Object execute(Object request) {{ return request; }} }}\n",
        encoding="utf-8",
    )
    baseline = SourceBaseline(source_path=str(source_root), commit=commit)
    application.register_system(
        SystemDefinition(system_id=system_id, name=system_id, source_path=str(source_root))
    )
    interface_name = f"sample.{method_prefix}Facade"
    implementation_name = f"sample.{method_prefix}FacadeImpl"
    request_type = f"sample.{method_prefix}Request"
    response_type = f"sample.{method_prefix}Response"
    interface_symbol = f"{interface_name}#execute({request_type})"
    implementation_symbol = f"{implementation_name}#execute({request_type})"
    source_ref = SourceReference(path=str(source_file), symbol=implementation_symbol, line=1, commit=commit)
    request_ref = source_ref.model_copy(update={"symbol": request_type})
    response_ref = source_ref.model_copy(update={"symbol": response_type})
    analysis = SemanticAnalysisResult(
        schema_version=5,
        analyzer="phase2-test",
        analyzer_version="1",
        system_id=system_id,
        methods=[
            SemanticMethodDefinition(
                symbol_id=interface_symbol,
                qualified_class_name=interface_name,
                method_name="execute",
                parameter_names=["request"],
                parameter_types=[f"{method_prefix}Request"],
                parameter_qualified_types=[request_type],
                return_type=f"{method_prefix}Response",
                return_qualified_type=response_type,
                owner_type_kind="interface",
                source_ref=source_ref.model_copy(update={"symbol": interface_symbol}),
            ),
            SemanticMethodDefinition(
                symbol_id=implementation_symbol,
                qualified_class_name=implementation_name,
                method_name="execute",
                parameter_names=["request"],
                parameter_types=[f"{method_prefix}Request"],
                parameter_qualified_types=[request_type],
                return_type=f"{method_prefix}Response",
                return_qualified_type=response_type,
                owner_interfaces=[interface_name],
                owner_type_kind="class",
                has_executable_body=True,
                source_ref=source_ref,
            ),
        ],
        types=[
            SemanticTypeDefinition(
                symbol_id=request_type,
                qualified_class_name=request_type,
                simple_name=f"{method_prefix}Request",
                fields=[
                    SemanticFieldDefinition(
                        field_name="items",
                        declared_type="List<String>",
                        referenced_type="java.lang.String",
                        collection=True,
                        annotations=["NotEmpty"],
                        source_ref=request_ref,
                    )
                ],
                source_ref=request_ref,
            ),
            SemanticTypeDefinition(
                symbol_id=response_type,
                qualified_class_name=response_type,
                simple_name=f"{method_prefix}Response",
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
    entry = EntryPoint(
        entry_id=f"facade:{interface_name}#execute",
        system_id=system_id,
        kind=KnowledgeNodeKind.FACADE,
        display_name=f"{method_prefix}Facade#execute",
        source_id=f"{interface_name}#execute",
        source_path=str(source_file),
        request_type=request_type,
        response_type=response_type,
    )
    manifest = ScanManifest(
        scan_id=f"scan-{system_id}-phase2",
        system_id=system_id,
        baseline=baseline,
        entries=[entry],
        semantic_analysis=analysis,
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    program_catalog = ProgramCaseAnalysisBuilder().build(manifest)
    # 正式bundle和注册baseline先就绪，最后切换latest，复现生产发布顺序。
    artifacts.write_scan_bundle(manifest, program_catalog)
    application.store.update_source_baseline(system_id, baseline)
    artifacts.publish_latest(system_id, manifest.scan_id)


def _capability_submission(candidate: CandidateOperation) -> CapabilityDraftSubmission:
    """构造用于验证跨系统发现不授予发布权限的V2草稿。

    Args:
        candidate: consumer通过直接绑定读取到的provider Candidate。

    Returns:
        引用provider系统Candidate和Operation、应被consumer路由拒绝的草稿。
    """

    return CapabilityDraftSubmission(
        publication_request_id="phase2-cross-system-publication",
        candidate_ref=CandidateRef(
            source_system_id=candidate.system_id,
            candidate_id=candidate.candidate_id,
            source_scan_id=candidate.source_scan_id,
            source_baseline=candidate.source_baseline,
            candidate_signature=candidate.method_signature,
            request_dto_types=candidate.request_dto_types,
            response_dto_type=candidate.response_dto_type,
            dto_definitions=candidate.dto_definitions,
        ),
        provider_operation_ref=ProviderOperationRef(
            source_system_id=candidate.system_id,
            operation_id="facade:sample.ProvisionFacade#execute",
            source_scan_id=candidate.source_scan_id,
        ),
        business_name="通用原子操作",
        business_purpose="验证直接依赖绑定不能扩大跨系统发布权限。",
        input_schema={
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "string"}}},
            "required": ["items"],
            "additionalProperties": False,
        },
        input_mapping={"items": "items"},
        output_fact_schema={
            "type": "object",
            "properties": {"reference_id": {"type": "string"}},
            "required": ["reference_id"],
            "additionalProperties": False,
        },
        output_mapping={"reference_id": "referenceId"},
    )


def _system_mq_rule_path(tmp_path: Path) -> tuple[Path, Path]:
    """创建符合生产固定相对位置的隔离系统Git规则路径。

    Args:
        tmp_path: 当前测试自己的隔离根目录。

    Returns:
        当前系统Git根和其中固定的MQ规则文件路径。

    Side Effects:
        创建`source-rules`目录，但不写入任何规则内容。
    """

    system_root = tmp_path / "system-git"
    rules_path = system_root / "source-rules" / "mq-framework-rules.yaml"
    rules_path.parent.mkdir(parents=True)
    return system_root, rules_path


def test_direct_binding_controls_cross_system_search_detail_and_drift(tmp_path: Path) -> None:
    """未绑定、直接绑定、漂移和删除必须即时改变provider Candidate可见性。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_generic_scan(application, "consumer-app", "Consume", "consumer-v1")
    _publish_generic_scan(application, "provider-app", "Provision", "provider-v1")

    unbound = application.search_candidate_operations("consumer-app", "ProvisionRequest")
    assert unbound.complete is True
    assert unbound.total == 0
    binding = application.put_system_dependency_binding(
        "consumer-app",
        SystemDependencyBindingSubmission(
            provider_system_id="provider-app",
            role=SystemDependencyRole.UPSTREAM,
            purposes=[SystemDependencyPurpose.SETUP],
        ),
    )
    bound = application.search_candidate_operations("consumer-app", "ProvisionRequest")
    provider_candidate = next(
        candidate
        for candidate in bound.candidates
        if candidate.implementation_symbol_id.endswith("ProvisionRequest)")
    )

    assert bound.complete is True
    assert {source.system_id for source in bound.sources} == {"consumer-app", "provider-app"}
    assert next(source for source in bound.sources if source.system_id == "provider-app").binding_id == binding.binding_id
    assert provider_candidate.system_id == "provider-app"
    assert provider_candidate.executable is False
    assert provider_candidate.contract_symbol_ids == [
        "sample.ProvisionFacade#execute(sample.ProvisionRequest)"
    ]
    assert provider_candidate.dto_definitions[0].fields[0].collection is True
    assert application.get_candidate_operation("consumer-app", provider_candidate.candidate_id) == provider_candidate

    drifted = application.store.get_system("provider-app").baseline.model_copy(update={"commit": "provider-v2"})
    application.store.update_source_baseline("provider-app", drifted)
    drift_result = application.search_candidate_operations("consumer-app", "ProvisionRequest")
    assert drift_result.complete is False
    assert drift_result.blockers == ["BLOCKED_CANDIDATE_SOURCE_DRIFT:provider-app"]
    with pytest.raises(KnowledgeNotFoundError):
        application.get_candidate_operation("consumer-app", provider_candidate.candidate_id)

    # 恢复真实scan基线只为验证删除绑定立即撤销授权，不创建新Candidate或Manifest。
    application.store.update_source_baseline("provider-app", provider_candidate.source_baseline)
    application.delete_system_dependency_binding("consumer-app", "provider-app")
    with pytest.raises(KnowledgeNotFoundError):
        application.get_candidate_operation("consumer-app", provider_candidate.candidate_id)


def test_entry_binding_requires_one_exact_concrete_implementation(tmp_path: Path) -> None:
    """同一接口签名存在多个具体实现时Entry必须保持PARTIAL并公开稳定原因。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_generic_scan(application, "consumer-app", "Consume", "consumer-v1")
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest, _ = artifacts.read_scan_bundle("consumer-app", "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    original_implementation = analysis.methods[1]
    alternate_implementation = original_implementation.model_copy(
        update={
            "symbol_id": "sample.AlternateConsumeFacadeImpl#execute(sample.ConsumeRequest)",
            "qualified_class_name": "sample.AlternateConsumeFacadeImpl",
            "source_ref": original_implementation.source_ref.model_copy(
                update={
                    "symbol": "sample.AlternateConsumeFacadeImpl#execute(sample.ConsumeRequest)"
                }
            ),
        }
    )
    ambiguous_analysis = analysis.model_copy(
        update={"methods": [*analysis.methods, alternate_implementation]}
    )
    ambiguous_manifest = manifest.model_copy(
        update={
            "scan_id": "scan-consumer-app-ambiguous",
            "semantic_analysis": ambiguous_analysis,
        }
    )
    artifacts.write_scan_bundle(
        ambiguous_manifest,
        ProgramCaseAnalysisBuilder().build(ambiguous_manifest),
    )
    artifacts.publish_latest("consumer-app", ambiguous_manifest.scan_id)

    catalog = application.candidate_operation_catalog("consumer-app")
    entry_candidate = next(
        candidate
        for candidate in catalog.candidates
        if candidate.candidate_id == "candidate:consumer-app:facade:sample.ConsumeFacade#execute"
    )
    implementation_candidates = [
        candidate
        for candidate in catalog.candidates
        if candidate.implementation_symbol_id
    ]

    assert entry_candidate.status.value == "PARTIAL"
    assert entry_candidate.blockers == ["BLOCKED_CANDIDATE_IMPLEMENTATION_AMBIGUOUS"]
    assert all(candidate.entry_ids == [] for candidate in implementation_candidates)
    assert all(candidate.kind.value == "method" for candidate in implementation_candidates)


def test_duplicate_candidate_identity_blocks_whole_source_snapshot(tmp_path: Path) -> None:
    """多模块重复symbol ID不得让搜索或详情按列表顺序选择一个Candidate。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_generic_scan(application, "consumer-app", "Consume", "consumer-v1")
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    manifest, _ = artifacts.read_scan_bundle("consumer-app", "latest")
    analysis = manifest.semantic_analysis
    assert analysis is not None
    duplicate_analysis = analysis.model_copy(
        update={"methods": [*analysis.methods, analysis.methods[-1]]}
    )
    duplicate_manifest = manifest.model_copy(
        update={
            "scan_id": "scan-consumer-app-duplicate",
            "semantic_analysis": duplicate_analysis,
        }
    )
    artifacts.write_scan_bundle(
        duplicate_manifest,
        ProgramCaseAnalysisBuilder().build(duplicate_manifest),
    )
    artifacts.publish_latest("consumer-app", duplicate_manifest.scan_id)

    search = application.search_candidate_operations("consumer-app", "")

    assert search.complete is False
    assert search.candidates == []
    assert search.blockers == ["BLOCKED_CANDIDATE_SOURCE_DRIFT:consumer-app"]
    with pytest.raises(KnowledgeValidationError, match="identity validation"):
        application.candidate_operation_catalog("consumer-app")


def test_v3_execution_rejects_unknown_generation_before_attempt_or_qa(tmp_path: Path) -> None:
    """阶段8执行入口遇到未知Generation时必须在Attempt和QA之前失败。

    Args:
        tmp_path: Pytest隔离知识、源码和潜在后续阶段资产目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_generic_scan(application, "consumer-app", "Consume", "consumer-v1")
    system_root = application.store.system_root("consumer-app")
    before_files = sorted(
        str(path.relative_to(system_root)) for path in system_root.rglob("*") if path.is_file()
    )
    with pytest.raises(KnowledgeNotFoundError, match="hybrid case generation not found"):
        # 不存在的Generation无法解析Variant，因此不得创建Attempt或访问provider。
        application.execute_hybrid_case_variant(
            "consumer-app",
            "variant-any",
            CaseVariantExecutionRequest(
                generation_id="hybrid-generation-00000000000000000000"
            ),
        )

    after_files = sorted(
        str(path.relative_to(system_root)) for path in system_root.rglob("*") if path.is_file()
    )
    assert after_files == before_files
    assert application.list_hybrid_case_attempts("consumer-app") == []

def test_dependency_api_is_direct_only_and_cross_system_publication_is_blocked(tmp_path: Path) -> None:
    """HTTP绑定不得传递，provider Candidate也不得由consumer路由发布。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    _publish_generic_scan(application, "consumer-app", "Consume", "consumer-v1")
    _publish_generic_scan(application, "provider-app", "Provision", "provider-v1")
    _publish_generic_scan(application, "third-app", "Third", "third-v1")
    application.put_system_dependency_binding(
        "provider-app",
        SystemDependencyBindingSubmission(
            provider_system_id="third-app",
            role=SystemDependencyRole.DOWNSTREAM,
            purposes=[SystemDependencyPurpose.ORACLE],
        ),
    )
    binding_payload = {
        "provider_system_id": "provider-app",
        "role": "UPSTREAM",
        "purposes": ["SETUP"],
    }
    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        put_response = client.put(
            "/api/v2/systems/consumer-app/dependency-bindings/provider-app",
            json=binding_payload,
        )
        search_response = client.get(
            "/api/v2/systems/consumer-app/candidate-operations",
            params={"query": "Request"},
        )
        provider_candidate = next(
            item
            for item in search_response.json()["result"]["candidates"]
            if item["system_id"] == "provider-app" and item["implementation_symbol_id"]
        )
        detail_response = client.get(
            "/api/v2/systems/consumer-app/candidate-operations/"
            + quote(provider_candidate["candidate_id"], safe="")
        )
        candidate = application.get_candidate_operation(
            "consumer-app",
            provider_candidate["candidate_id"],
        )
        blocked_response = client.post(
            "/api/v2/systems/consumer-app/capability-drafts",
            json=_capability_submission(candidate).model_dump(mode="json"),
        )

    assert put_response.status_code == 200
    assert detail_response.status_code == 200
    visible_systems = {
        item["system_id"] for item in search_response.json()["result"]["candidates"]
    }
    assert visible_systems == {"consumer-app", "provider-app"}
    assert "third-app" not in visible_systems
    assert blocked_response.status_code == 200
    result = blocked_response.json()["result"]
    assert result["status"] == "BLOCKED"
    assert [issue["code"] for issue in result["issues"]] == [
        "CAPABILITY_SYSTEM_SCOPE_MISMATCH"
    ]
    assert not (application.store.system_root("consumer-app") / "capabilities" / "published.yaml").exists()


def test_mq_framework_rule_selects_real_handler_and_rejects_ambiguity(tmp_path: Path) -> None:
    """继承型MQ Entry只能由系统规则唯一匹配到具体类声明的handler。

    Args:
        tmp_path: Pytest隔离源码和规则目录。
    """

    source = tmp_path / "source"
    java_root = source / "module" / "src" / "main" / "java"
    java_root.mkdir(parents=True)
    handler = java_root / "InventoryEventHandler.java"
    single_handler_source = """
        package sample.listener;
        import sample.framework.FrameworkConsumer;
        public class InventoryEventHandler extends FrameworkConsumer<InventoryPayload> {
            public boolean dispatch(InventoryPayload payload) { return true; }
        }
        """
    handler.write_text(
        single_handler_source,
        encoding="utf-8",
    )
    rules_root, rules_path = _system_mq_rule_path(tmp_path)
    rules_path.write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "rule_id": "sample-framework-dispatch",
                        "owner_types": ["sample.framework.FrameworkConsumer"],
                        "handler_methods": ["dispatch"],
                        "parameter_count": 1,
                        "payload_parameter_index": 0,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    scanner = JavaStructureScanner()
    entries, _, warnings = scanner.scan("sample-app", source, rules_path, rules_root)

    assert warnings == []
    assert [entry.source_id for entry in entries] == [
        "sample.listener.InventoryEventHandler#dispatch"
    ]
    assert entries[0].request_type == "sample.listener.InventoryPayload"
    assert entries[0].metadata["framework_rule_id"] == "sample-framework-dispatch"
    assert entries[0].metadata["matched_owner"] == "sample.framework.FrameworkConsumer"

    handler.write_text(
        """
        package sample.listener;
        import sample.framework.FrameworkConsumer;
        public class InventoryEventHandler extends FrameworkConsumer<InventoryPayload> {
            public boolean dispatch(InventoryPayload payload) { return true; }
            public boolean dispatch(AlternatePayload payload) { return false; }
        }
        """,
        encoding="utf-8",
    )
    overloaded_entries, _, overloaded_warnings = scanner.scan(
        "sample-app", source, rules_path, rules_root
    )
    assert overloaded_entries == []
    assert "ambiguous overloaded MQ handler" in overloaded_warnings[0]

    rules_path.write_text("rules: []\n", encoding="utf-8")
    without_rule, _, _ = scanner.scan("sample-app", source, rules_path, rules_root)
    assert without_rule == []

    # 两条不同ID的规则声称同一handler时不能以排序结果伪造唯一入口。
    handler.write_text(single_handler_source, encoding="utf-8")
    rules_path.write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "rule_id": f"ambiguous-rule-{index}",
                        "owner_types": ["sample.framework.FrameworkConsumer"],
                        "handler_methods": ["dispatch"],
                        "parameter_count": 1,
                    }
                    for index in (1, 2)
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ambiguous_entries, _, ambiguous_warnings = scanner.scan(
        "sample-app", source, rules_path, rules_root
    )
    assert ambiguous_entries == []
    assert "ambiguous MQ framework rules" in ambiguous_warnings[0]


def test_mq_scanner_rejects_non_production_and_non_structural_matches(tmp_path: Path) -> None:
    """测试源码、同名框架、嵌套类、注释和方法调用均不得制造MQ Entry。

    Args:
        tmp_path: Pytest隔离生产、测试源码和系统规则目录。
    """

    source = tmp_path / "source"
    main_root = source / "module" / "src" / "main" / "java"
    test_root = source / "module" / "src" / "test" / "java"
    main_root.mkdir(parents=True)
    test_root.mkdir(parents=True)
    rules_root, rules_path = _system_mq_rule_path(tmp_path)
    rules_path.write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "rule_id": "sample-framework-dispatch",
                        "owner_types": ["sample.framework.FrameworkConsumer"],
                        "handler_methods": ["dispatch"],
                        "parameter_count": 1,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (test_root / "TestOnlyListener.java").write_text(
        """
        package sample.listener;
        import sample.framework.FrameworkConsumer;
        public class TestOnlyListener extends FrameworkConsumer<TestPayload> {
            public boolean dispatch(TestPayload payload) { return true; }
        }
        """,
        encoding="utf-8",
    )
    generated_root = source / "build" / "generated" / "src" / "main" / "java"
    generated_root.mkdir(parents=True)
    (generated_root / "GeneratedListener.java").write_text(
        """
        package sample.listener;
        import sample.framework.FrameworkConsumer;
        public class GeneratedListener extends FrameworkConsumer<GeneratedPayload> {
            public boolean dispatch(GeneratedPayload payload) { return true; }
        }
        """,
        encoding="utf-8",
    )
    external_listener = tmp_path / "ExternalListener.java"
    external_listener.write_text(
        """
        package sample.listener;
        import sample.framework.FrameworkConsumer;
        public class ExternalListener extends FrameworkConsumer<ExternalPayload> {
            public boolean dispatch(ExternalPayload payload) { return true; }
        }
        """,
        encoding="utf-8",
    )
    (main_root / "ExternalListener.java").symlink_to(external_listener)
    misleading = main_root / "MisleadingHandler.java"
    misleading.write_text(
        """
        package sample.listener;
        import other.framework.FrameworkConsumer;
        public class MisleadingHandler extends FrameworkConsumer<RealPayload> {
            // public boolean dispatch(CommentPayload payload) { return true; }
            public boolean helper(RealPayload payload) { return dispatch(payload); }
            class Nested { public boolean dispatch(NestedPayload payload) { return true; } }
        }
        """,
        encoding="utf-8",
    )
    (main_root / "NestedOnlyContainer.java").write_text(
        """
        package sample.listener;
        import sample.framework.FrameworkConsumer;
        public interface NestedOnlyContainer {
            class NestedListener extends FrameworkConsumer<NestedPayload> {
                public boolean dispatch(NestedPayload payload) { return true; }
            }
        }
        """,
        encoding="utf-8",
    )

    entries, _, warnings = JavaStructureScanner().scan(
        "sample-app", source, rules_path, rules_root
    )

    assert entries == []
    assert warnings == []


def test_mq_rule_rejects_missing_payload_parameter() -> None:
    """固定零参数或运行时payload索引越界的规则不得产生空请求MQ Entry。

    Raises:
        ValueError: 固定零参数规则在模型边界被拒绝即通过。
    """

    with pytest.raises(ValueError, match="payload parameter index"):
        MqEntryFrameworkRule(
            rule_id="zero-parameter-handler",
            owner_types=["sample.framework.FrameworkConsumer"],
            handler_methods=["dispatch"],
            parameter_count=0,
        )


def test_mq_scanner_blocks_runtime_payload_index_overflow(tmp_path: Path) -> None:
    """未固定参数数量的规则也必须按真实handler签名校验payload位置。

    Args:
        tmp_path: Pytest隔离生产源码和系统规则目录。
    """

    source = tmp_path / "source"
    java_root = source / "src" / "main" / "java"
    java_root.mkdir(parents=True)
    (java_root / "InventoryHandler.java").write_text(
        """
        package sample.listener;
        import sample.framework.FrameworkConsumer;
        public class InventoryHandler extends FrameworkConsumer<Payload> {
            public boolean dispatch(Payload payload) { return true; }
        }
        """,
        encoding="utf-8",
    )
    rules_root, rules_path = _system_mq_rule_path(tmp_path)
    rules_path.write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "rule_id": "overflow-payload-index",
                        "owner_types": ["sample.framework.FrameworkConsumer"],
                        "handler_methods": ["dispatch"],
                        "payload_parameter_index": 1,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    entries, _, warnings = JavaStructureScanner().scan(
        "sample-app", source, rules_path, rules_root
    )

    assert entries == []
    assert warnings == ["MQ framework evidence has no unique handler: src/main/java/InventoryHandler.java"]


def test_mq_system_rule_path_rejects_symlink_escape(tmp_path: Path) -> None:
    """系统Git规则自身或祖先符号链接不得读取根目录外未版本化内容。

    Args:
        tmp_path: Pytest隔离允许根和外部规则目录。
    """

    source = tmp_path / "source"
    (source / "src" / "main" / "java").mkdir(parents=True)
    system_root = tmp_path / "system-git"
    system_root.mkdir()
    external_rules = tmp_path / "external-rules"
    external_rules.mkdir()
    (external_rules / "mq-framework-rules.yaml").write_text("rules: []\n", encoding="utf-8")
    (system_root / "source-rules").symlink_to(external_rules, target_is_directory=True)
    escaped_path = system_root / "source-rules" / "mq-framework-rules.yaml"

    with pytest.raises(KnowledgeValidationError, match="symbolic links"):
        JavaStructureScanner().scan(
            "sample-app",
            source,
            escaped_path,
            system_root,
        )


@pytest.mark.skipif(
    not Path("/Users/user/data/code/tc/ifightchainsaas.java.refund.core").is_dir(),
    reason="本地真实退款源码未绑定",
)
def test_local_real_refund_listener_requires_system_rule(tmp_path: Path) -> None:
    """本地验收规则应识别真实process入口，删除规则后目标Entry必须消失。

    Args:
        tmp_path: 只保存本次系统规则的隔离目录。
    """

    source = Path("/Users/user/data/code/tc/ifightchainsaas.java.refund.core")
    rules_root, rules_path = _system_mq_rule_path(tmp_path)
    rules_path.write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "rule_id": "ly-refund-abstract-mq-process",
                        "owner_types": [
                            "com.ly.flight.chainsaas.refund.biz.mq.AbstractMqMessageListener"
                        ],
                        "handler_methods": ["process"],
                        "parameter_count": 1,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    scanner = JavaStructureScanner()
    entries, _, warnings = scanner.scan("local-refund", source, rules_path, rules_root)
    target_ids = {entry.source_id for entry in entries}

    assert not [warning for warning in warnings if "TradeOrderSyncMessageListener" in warning]
    assert (
        "com.ly.flight.chainsaas.refund.biz.mq.listener."
        "TradeOrderSyncMessageListener#process"
    ) in target_ids
    rules_path.write_text("rules: []\n", encoding="utf-8")
    without_rule, _, _ = scanner.scan("local-refund", source, rules_path, rules_root)
    assert not any("TradeOrderSyncMessageListener#process" in entry.source_id for entry in without_rule)


def test_dependency_models_reject_self_binding_at_store_boundary(tmp_path: Path) -> None:
    """自绑定不得借同系统身份伪装跨系统授权。

    Args:
        tmp_path: Pytest隔离Git知识目录。
    """

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="single-app", name="single", source_path=str(source)))

    with pytest.raises(ScopeViolationError):
        # Pydantic用途有效，自绑定必须由了解活动注册表的存储边界拒绝。
        store.put_system_dependency_binding(
            "single-app",
            SystemDependencyBindingSubmission(
                provider_system_id="single-app",
                role=SystemDependencyRole.UPSTREAM,
                purposes=[SystemDependencyPurpose.SETUP],
            ),
        )


def test_default_semantic_sidecar_path_does_not_follow_knowledge_root(tmp_path: Path) -> None:
    """外置知识仓库不得让源码扫描静默退化为无Java语义目录。

    Args:
        tmp_path: 与OpenTest代码目录无关的模拟知识仓库位置。
    """

    analyzer_path = default_semantic_analyzer_path(tmp_path / "external-knowledge")

    assert analyzer_path == (
        Path(__file__).resolve().parents[2]
        / "workers"
        / "java-semantic-analyzer"
        / "target"
        / "opentest-java-semantic-analyzer.jar"
    )
    assert analyzer_path.is_file()


@pytest.mark.skipif(
    os.environ.get("OPENTEST_REAL_PHASE2_ACCEPTANCE") != "1",
    reason="仅在显式真实源码验收时运行",
)
def test_real_two_system_scan_and_direct_candidate_binding(tmp_path: Path) -> None:
    """正式扫描退款与Booking源码并验证直接绑定前后的真实候选范围。

    Args:
        tmp_path: 隔离知识、工具和扫描产物根目录。
    """

    refund_source = Path("/Users/user/data/code/tc/ifightchainsaas.java.refund.core")
    booking_source = Path("/Users/user/data/code/tc/ifightchainsaas.java.booking.core")
    scriptgen_path = Path("/Users/user/data/code/other/CLI-Anything/scriptgen/agent-harness")
    if not all(path.is_dir() for path in (refund_source, booking_source, scriptgen_path)):
        pytest.skip("本地真实退款、Booking或scriptgen源码不可用")
    application = OpenTestApplication(
        tmp_path / "knowledge",
        scriptgen_pythonpath=scriptgen_path,
    )
    application.register_system(
        SystemDefinition(
            system_id="refund-real",
            name="真实退款系统",
            source_path=str(refund_source),
        )
    )
    application.register_system(
        SystemDefinition(
            system_id="booking-real",
            name="真实Booking系统",
            source_path=str(booking_source),
        )
    )
    refund_rule_path = (
        application.store.system_root("refund-real")
        / "source-rules"
        / "mq-framework-rules.yaml"
    )
    refund_rule_path.parent.mkdir(parents=True)
    refund_rule_path.write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "rule_id": "ly-refund-abstract-mq-process",
                        "owner_types": [
                            "com.ly.flight.chainsaas.refund.biz.mq.AbstractMqMessageListener"
                        ],
                        "handler_methods": ["process"],
                        "parameter_count": 1,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    scan_request_values = {
        "environment": "qa",
        "entry_types": "facade,job",
        "facade_http_prefix": "http://127.0.0.1:18080",
        "timeout_seconds": 600,
    }
    # 两个系统分别执行完整正式事务，任何一个都不能借另一个Manifest或baseline。
    refund_manifest = application.source_analysis.analyze(
        SourceScanRequest(system_id="refund-real", **scan_request_values)
    )
    booking_manifest = application.source_analysis.analyze(
        SourceScanRequest(system_id="booking-real", **scan_request_values)
    )
    listener_id = (
        "com.ly.flight.chainsaas.refund.biz.mq.listener."
        "TradeOrderSyncMessageListener#process"
    )
    assert any(entry.source_id == listener_id for entry in refund_manifest.entries)
    assert application.store.get_system("refund-real").baseline == refund_manifest.baseline
    assert application.store.get_system("booking-real").baseline == booking_manifest.baseline

    unbound = application.search_candidate_operations(
        "refund-real",
        "com.ly.flight.chainsaas.booking.facade.TradeFacade",
        limit=200,
    )
    assert unbound.complete is True
    assert unbound.total == 0
    application.put_system_dependency_binding(
        "refund-real",
        SystemDependencyBindingSubmission(
            provider_system_id="booking-real",
            role=SystemDependencyRole.UPSTREAM,
            purposes=[SystemDependencyPurpose.SETUP],
        ),
    )
    bound = application.search_candidate_operations(
        "refund-real",
        "com.ly.flight.chainsaas.booking.facade.TradeFacade",
        limit=200,
    )
    booking_candidates = [
        candidate for candidate in bound.candidates if candidate.system_id == "booking-real"
    ]
    implementation_candidates = [
        candidate for candidate in booking_candidates if candidate.implementation_symbol_id
    ]
    assert implementation_candidates, [
        (
            candidate.qualified_name,
            candidate.status,
            candidate.source_ref.path,
            candidate.contract_symbol_ids,
        )
        for candidate in booking_candidates
    ]
    booking_candidate = implementation_candidates[0]

    assert bound.complete is True
    assert booking_candidate.source_scan_id == booking_manifest.scan_id
    assert booking_candidate.source_baseline == booking_manifest.baseline
    assert booking_candidate.executable is False
    assert application.get_candidate_operation("refund-real", booking_candidate.candidate_id)
    application.delete_system_dependency_binding("refund-real", "booking-real")
    with pytest.raises(KnowledgeNotFoundError):
        application.get_candidate_operation("refund-real", booking_candidate.candidate_id)
    assert not (
        application.store.system_root("refund-real") / "capabilities" / "published.yaml"
    ).exists()
