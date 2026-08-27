"""验证阶段4跨系统Setup Recipe只接受可信Published、规则和Fact来源。"""

from __future__ import annotations

import shutil
import threading
import time
import multiprocessing
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.published_capability_store import PublishedCapabilityStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    CandidateDtoDefinition,
    CandidateDtoField,
    CandidateRef,
    DataSetupRecipeSubmission,
    DataSetupStep,
    EntryPoint,
    KnowledgeNodeKind,
    OperationMutability,
    ProviderOperationRef,
    PublishedCapabilityRef,
    PublishedOperationCapability,
    RecipeFactOutputSubmission,
    ScanManifest,
    SetupContractRuleSet,
    SetupFactConstraintRequirement,
    SetupFactContractDefinition,
    SetupFactOrigin,
    SetupFactRequiredField,
    SetupInputBinding,
    SetupInputPolicy,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
    SystemDependencyBindingSubmission,
    SystemDependencyPurpose,
    SystemDependencyRole,
    TestFactConstraint as DomainTestFactConstraint,
)


CONSUMER_ID = "sample-consumer"
PROVIDER_ID = "sample-provider"
FACT_CONTRACT_ID = "upstream-resource/v1"


def _hold_system_lock(
    knowledge_root: str,
    system_id: str,
    ready: Any,
    release: Any,
) -> None:
    """在独立进程持有一个系统锁，验证POSIX flock而非仅线程锁。

    Args:
        knowledge_root: Pytest隔离知识根目录。
        system_id: 被模拟扫描写路径锁定的provider系统。
        ready: 通知父进程锁已经取得的进程事件。
        release: 允许子进程释放锁的进程事件。

    Side Effects:
        在独立进程打开并暂时持有provider系统锁文件。
    """

    store = GitKnowledgeStore(Path(knowledge_root))
    with store.system_transaction(system_id):
        # 父进程只有在文件锁确实持有后才启动Recipe发布，避免测试时序假阳性。
        ready.set()
        release.wait(timeout=10)


def _publish_scan(
    application: OpenTestApplication,
    system_id: str,
    suffix: str,
    register: bool = True,
) -> ScanManifest:
    """发布一个只含通用Facade入口的真实文件扫描bundle。

    Args:
        application: Pytest隔离知识应用。
        system_id: 本次独立源码系统。
        suffix: 区分源码代际的稳定测试后缀。
        register: 首次扫描时同时注册系统。

    Returns:
        已成为该系统latest的不可变Manifest。

    Side Effects:
        写入通用Java文件、系统source基线和本地scan bundle。
    """

    source_root = application.knowledge_root.parent / f"source-{system_id}"
    source_file = source_root / "src/main/java/sample/ResourceFacade.java"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(
        "package sample; public interface ResourceFacade { Object prepare(Object request); }\n",
        encoding="utf-8",
    )
    baseline = SourceBaseline(source_path=str(source_root), commit=f"{system_id}-{suffix}")
    if register:
        application.register_system(
            SystemDefinition(
                system_id=system_id,
                name=system_id,
                source_path=str(source_root),
            )
        )
    entry_source_id = f"sample.{system_id.replace('-', '')}.ResourceFacade#prepare"
    entry = EntryPoint(
        entry_id=f"facade:{entry_source_id}",
        system_id=system_id,
        kind=KnowledgeNodeKind.FACADE,
        display_name="ResourceFacade#prepare",
        source_id=entry_source_id,
        source_path=str(source_file),
        request_type="sample.ResourceRequest",
        response_type="sample.ResourceResponse",
    )
    manifest = ScanManifest(
        scan_id=f"scan-{system_id}-{suffix}",
        system_id=system_id,
        baseline=baseline,
        entries=[entry],
    )
    artifacts = SourceScanArtifactStore(application.knowledge_root)
    artifacts.write_scan_bundle(manifest, ProgramCaseAnalysisBuilder().build(manifest))
    application.store.update_source_baseline(system_id, baseline)
    artifacts.publish_latest(system_id, manifest.scan_id)
    return manifest


def _publish_resource_capability(
    application: OpenTestApplication,
    manifest: ScanManifest,
) -> PublishedOperationCapability:
    """写入一个与通用latest一致的V2 Published前置能力夹具。

    Args:
        application: Pytest隔离知识应用。
        manifest: 能力所属系统当前latest扫描。

    Returns:
        只提供安全模式输入和结构化资源输出的V2 Published能力。

    Side Effects:
        通过正式V2注册表存储写入隔离系统Git；不创建provider或执行记录。
    """

    system_id = manifest.system_id
    source_ref = SourceReference(
        path=manifest.entries[0].source_path,
        symbol=manifest.entries[0].source_id,
        commit=manifest.baseline.commit,
    )
    request_type = "sample.ResourceRequest"
    response_type = "sample.ResourceResponse"
    request_definition = CandidateDtoDefinition(
        qualified_type=request_type,
        fields=[
            CandidateDtoField(
                field_name="requestId",
                declared_type="java.lang.String",
                source_ref=source_ref,
            )
        ],
        source_ref=source_ref,
    )
    response_definition = CandidateDtoDefinition(
        qualified_type=response_type,
        fields=[
            CandidateDtoField(
                field_name="resourceId",
                declared_type="java.lang.String",
                source_ref=source_ref,
            ),
            CandidateDtoField(
                field_name="state",
                declared_type="java.lang.String",
                source_ref=source_ref,
            ),
            CandidateDtoField(
                field_name="items",
                declared_type="java.util.List<java.lang.String>",
                referenced_type="java.lang.String",
                collection=True,
                source_ref=source_ref,
            ),
        ],
        source_ref=source_ref,
    )
    candidate_ref = CandidateRef(
        source_system_id=system_id,
        candidate_id=f"candidate:{system_id}:resource-prepare",
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        candidate_signature=f"sample.ResourceResponse prepare({request_type} request)",
        request_dto_types=[request_type],
        response_dto_type=response_type,
        dto_definitions=[request_definition, response_definition],
    )
    resource_schema = {
        "type": "object",
        "properties": {
            "resourceId": {"type": "string"},
            "state": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["resourceId", "state", "items"],
        "additionalProperties": False,
    }
    capability = PublishedOperationCapability(
        capability_id=f"published:{system_id}:resource-prepare-v1",
        publication_request_id=f"{system_id}-resource-prepare-v1",
        draft_id=f"capability-draft:{system_id}-resource-prepare-v1",
        system_id=system_id,
        candidate_ref=candidate_ref,
        provider_operation_ref=ProviderOperationRef(
            source_system_id=system_id,
            operation_id=manifest.entries[0].entry_id,
            source_scan_id=manifest.scan_id,
        ),
        business_name="准备通用测试资源",
        business_purpose="为Setup Recipe提供带身份、状态和集合的通用上游资源。",
        input_schema={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
            "additionalProperties": False,
        },
        input_mapping={"request_id": "requestId"},
        output_fact_schema={
            "type": "object",
            "properties": {"resource": resource_schema},
            "required": ["resource"],
            "additionalProperties": False,
        },
        output_mapping={"resource": "output"},
        mutability=OperationMutability.WRITE,
    )
    return PublishedCapabilityStore(application.store).publish(capability)


def _write_rules(
    application: OpenTestApplication,
    provider_capability: PublishedOperationCapability,
    consumer_capability: PublishedOperationCapability,
) -> None:
    """安装通用上游资源事实契约与两个输入来源策略。

    Args:
        application: Pytest隔离知识应用。
        provider_capability: 允许安全literal选择资源分区的上游能力。
        consumer_capability: 业务身份输入只允许来自Fact的consumer能力。

    Side Effects:
        写入consumer系统Git的服务器Setup规则，不写Recipe或运行数据。
    """

    rules = SetupContractRuleSet(
        system_id=CONSUMER_ID,
        fact_contracts=[
            SetupFactContractDefinition(
                fact_contract_id=FACT_CONTRACT_ID,
                required_origin=SetupFactOrigin.UPSTREAM_PUBLISHED_OUTPUT,
                required_fields=[
                    SetupFactRequiredField(path="resourceId", schema_type="string"),
                    SetupFactRequiredField(path="state", schema_type="string"),
                    SetupFactRequiredField(path="items", schema_type="array"),
                ],
                business_identity_paths=["resourceId"],
                required_constraints=[
                    SetupFactConstraintRequirement(
                        path="state",
                        operator="eq",
                        allowed_expected=["READY"],
                    ),
                    SetupFactConstraintRequirement(
                        path="items",
                        operator="cardinality",
                        allowed_expected=["SINGLE", "MULTIPLE"],
                    ),
                ],
            )
        ],
        input_policies=[
            SetupInputPolicy(
                capability_ref=PublishedCapabilityRef(
                    system_id=provider_capability.system_id,
                    capability_id=provider_capability.capability_id,
                ),
                input_path="request_id",
                allowed_sources=["literal"],
                allowed_literal_values=["SINGLE", "MULTIPLE"],
            ),
            SetupInputPolicy(
                capability_ref=PublishedCapabilityRef(
                    system_id=consumer_capability.system_id,
                    capability_id=consumer_capability.capability_id,
                ),
                input_path="request_id",
                allowed_sources=["fact"],
                business_identity=True,
            ),
        ],
    )
    application.setup_contract_rules.write(rules)


def _prepare_workspace(
    tmp_path: Path,
) -> tuple[
    OpenTestApplication,
    ScanManifest,
    PublishedOperationCapability,
    PublishedOperationCapability,
]:
    """准备具有直接UPSTREAM绑定、V2 Published和服务器规则的通用工作区。

    Args:
        tmp_path: Pytest隔离根目录。

    Returns:
        应用、consumer manifest、provider能力和consumer能力。
    """

    application = OpenTestApplication(tmp_path / "knowledge")
    consumer_manifest = _publish_scan(application, CONSUMER_ID, "v1")
    provider_manifest = _publish_scan(application, PROVIDER_ID, "v1")
    consumer_capability = _publish_resource_capability(application, consumer_manifest)
    provider_capability = _publish_resource_capability(application, provider_manifest)
    application.put_system_dependency_binding(
        CONSUMER_ID,
        SystemDependencyBindingSubmission(
            provider_system_id=PROVIDER_ID,
            role=SystemDependencyRole.UPSTREAM,
            purposes=[SystemDependencyPurpose.SETUP],
        ),
    )
    _write_rules(application, provider_capability, consumer_capability)
    return application, consumer_manifest, provider_capability, consumer_capability


def _recipe_submission(
    consumer_manifest: ScanManifest,
    provider_capability: PublishedOperationCapability,
    consumer_capability: PublishedOperationCapability,
    suffix: str,
    cardinality: str,
) -> DataSetupRecipeSubmission:
    """构造一个先产出上游资源Fact、再传递其身份字段的双步骤Recipe。

    Args:
        consumer_manifest: 被测consumer当前latest和入口身份。
        provider_capability: 第一步上游Published资源能力。
        consumer_capability: 第二步消费前序Fact的同系统能力。
        suffix: Recipe不可变版本后缀。
        cardinality: SINGLE或MULTIPLE资源集合约束。

    Returns:
        不重复提交Fact Schema且不包含业务资源样本的Recipe草稿。
    """

    return DataSetupRecipeSubmission(
        recipe_id=f"setup:generic-resource-{suffix}",
        entry_id=consumer_manifest.entries[0].entry_id,
        entry_source_scan_id=consumer_manifest.scan_id,
        name=f"准备{cardinality}集合通用资源",
        steps=[
            DataSetupStep(
                step_id="prepare-upstream-resource",
                capability_ref=PublishedCapabilityRef(
                    system_id=provider_capability.system_id,
                    capability_id=provider_capability.capability_id,
                ),
                input_bindings={
                    "request_id": SetupInputBinding(
                        source="literal",
                        value=cardinality,
                    )
                },
            ),
            DataSetupStep(
                step_id="consume-resource-identity",
                capability_ref=PublishedCapabilityRef(
                    system_id=consumer_capability.system_id,
                    capability_id=consumer_capability.capability_id,
                ),
                input_bindings={
                    "request_id": SetupInputBinding(
                        source="fact",
                        path="prepared_resource.resourceId",
                    )
                },
            ),
        ],
        fact_outputs=[
            RecipeFactOutputSubmission(
                fact_name="prepared_resource",
                fact_contract_id=FACT_CONTRACT_ID,
                from_step_id="prepare-upstream-resource",
                output_path="resource",
                constraints=[
                    DomainTestFactConstraint(path="state", operator="eq", expected="READY"),
                    DomainTestFactConstraint(
                        path="items",
                        operator="cardinality",
                        expected=cardinality,
                    ),
                ],
            )
        ],
    )


def test_cross_system_recipes_derive_facts_and_keep_cardinality_versions(
    tmp_path: Path,
) -> None:
    """单/多集合Recipe应冻结二元Published引用、上游证明和程序派生Fact Schema。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    single = _recipe_submission(manifest, provider, consumer, "single", "SINGLE")
    multiple = _recipe_submission(manifest, provider, consumer, "multiple", "MULTIPLE")
    execution_root = application.knowledge_root / ".opentest/operation-executions"

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        single_response = client.post(
            f"/api/v2/systems/{CONSUMER_ID}/data-setup-recipes",
            json=single.model_dump(mode="json"),
        )
        multiple_response = client.post(
            f"/api/v2/systems/{CONSUMER_ID}/data-setup-recipes",
            json=multiple.model_dump(mode="json"),
        )
        catalog_response = client.get(
            f"/api/v2/systems/{CONSUMER_ID}/data-setup-recipes"
        )

    assert single_response.json()["result"]["status"] == "PUBLISHED"
    assert multiple_response.json()["result"]["status"] == "PUBLISHED"
    recipes = catalog_response.json()["catalog"]["recipes"]
    assert [recipe["recipe_id"] for recipe in recipes] == [
        "setup:generic-resource-multiple",
        "setup:generic-resource-single",
    ]
    single_recipe = next(
        recipe for recipe in recipes if recipe["recipe_id"].endswith("single")
    )
    assert single_recipe["steps"][0]["capability_ref"]["system_id"] == PROVIDER_ID
    assert single_recipe["fact_outputs"][0]["fact_schema"]["properties"]["items"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    dependency_proof = single_recipe["dependency_proofs"][0]
    assert dependency_proof.pop("binding_revision_id").startswith("dependency-revision:")
    assert dependency_proof == {
        "binding_id": f"dependency:{CONSUMER_ID}:{PROVIDER_ID}",
        "consumer_system_id": CONSUMER_ID,
        "provider_system_id": PROVIDER_ID,
        "role": "UPSTREAM",
        "purpose": "SETUP",
    }
    assert single_recipe["setup_rule_revision_id"].startswith("setup-rule-revision:")
    assert not execution_root.exists()


def test_recipe_blocks_unpublished_wrong_dependency_and_same_system_origin(
    tmp_path: Path,
) -> None:
    """Candidate引用、非SETUP依赖和同系统输出均不能冒充上游资源Fact。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    original = _recipe_submission(manifest, provider, consumer, "blocked", "SINGLE")
    candidate_step = original.steps[0].model_copy(
        update={
            "capability_ref": PublishedCapabilityRef(
                system_id=PROVIDER_ID,
                capability_id="candidate:sample-provider:resource-prepare",
            )
        }
    )
    unpublished = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-unpublished",
                "steps": [candidate_step, original.steps[1]],
            }
        ),
    )
    application.put_system_dependency_binding(
        CONSUMER_ID,
        SystemDependencyBindingSubmission(
            provider_system_id=PROVIDER_ID,
            role=SystemDependencyRole.UPSTREAM,
            purposes=[SystemDependencyPurpose.ACTION],
        ),
    )
    wrong_dependency = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(update={"recipe_id": "setup:generic-resource-wrong-dependency"}),
    )
    same_system_output = original.fact_outputs[0].model_copy(
        update={"from_step_id": "consume-resource-identity"}
    )
    same_system_origin = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-same-system",
                "fact_outputs": [same_system_output],
            }
        ),
    )

    assert "BLOCKED_UNPUBLISHED_CAPABILITY" in {
        issue.code for issue in unpublished.issues
    }
    assert "BLOCKED_SETUP_DEPENDENCY_MISSING" in {
        issue.code for issue in wrong_dependency.issues
    }
    assert "SETUP_FACT_ORIGIN_INVALID" in {
        issue.code for issue in same_system_origin.issues
    }
    assert application.data_setup_recipe_catalog(CONSUMER_ID).recipes == []


@pytest.mark.parametrize("source", ["literal", "fixture"])
def test_business_identity_input_rejects_literal_and_fixture(
    tmp_path: Path,
    source: str,
) -> None:
    """业务身份输入无论来自literal还是Fixture都必须在服务器策略处失败关闭。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
        source: 本次负例选择的非Fact来源。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    original = _recipe_submission(manifest, provider, consumer, source, "SINGLE")
    replacement = (
        SetupInputBinding(source="literal", value="RESOURCE_INPUT")
        if source == "literal"
        else SetupInputBinding(source="fixture", path="resource_input")
    )
    consumer_step = original.steps[1].model_copy(
        update={"input_bindings": {"request_id": replacement}}
    )
    fixture_schema = {
        "type": "object",
        "properties": {"resource_input": {"type": "string"}},
        "required": ["resource_input"],
        "additionalProperties": False,
    }
    submission = original.model_copy(
        update={
            "steps": [original.steps[0], consumer_step],
            "fixture_schema": fixture_schema,
        }
    )

    result = application.publish_data_setup_recipe(CONSUMER_ID, submission)

    assert "SETUP_INPUT_SOURCE_FORBIDDEN" in {issue.code for issue in result.issues}
    assert application.data_setup_recipe_catalog(CONSUMER_ID).recipes == []


def test_fact_subpath_and_constraint_failures_do_not_write_recipe(tmp_path: Path) -> None:
    """未知Fact子字段、资源身份值和矛盾基数均应返回独立确定性阻塞。

    Args:
        tmp_path: Pytest隔离知识与源码根目录。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    original = _recipe_submission(manifest, provider, consumer, "invalid", "SINGLE")
    unknown_step = original.steps[1].model_copy(
        update={
            "input_bindings": {
                "request_id": SetupInputBinding(
                    source="fact",
                    path="prepared_resource.missingIdentity",
                )
            }
        }
    )
    unknown = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-unknown-path",
                "steps": [original.steps[0], unknown_step],
            }
        ),
    )
    invalid_fact = original.fact_outputs[0].model_copy(
        update={
            "constraints": [
                *original.fact_outputs[0].constraints,
                DomainTestFactConstraint(
                    path="resourceId",
                    operator="eq",
                    expected="RESOURCE_SAMPLE",
                ),
                DomainTestFactConstraint(
                    path="items",
                    operator="cardinality",
                    expected="MULTIPLE",
                ),
            ]
        }
    )
    invalid_constraints = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-invalid-constraints",
                "fact_outputs": [invalid_fact],
            }
        ),
    )

    assert "SETUP_INPUT_TYPE_MISMATCH" in {issue.code for issue in unknown.issues}
    codes = {issue.code for issue in invalid_constraints.issues}
    assert "SETUP_FACT_IDENTITY_VALUE_FORBIDDEN" in codes
    assert "SETUP_FACT_CONSTRAINT_CONFLICT" in codes
    assert application.data_setup_recipe_catalog(CONSUMER_ID).recipes == []


def test_provider_latest_change_serializes_before_recipe_validation(tmp_path: Path) -> None:
    """并发provider扫描先提交时Recipe必须在多系统锁后观察到能力已过期。

    Args:
        tmp_path: Pytest隔离知识、源码和锁目录。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    submission = _recipe_submission(manifest, provider, consumer, "concurrent", "SINGLE")
    started = threading.Event()
    results = []

    def publish_recipe() -> None:
        """在线程中提交Recipe并保存锁释放后的确定性结果。"""

        started.set()
        results.append(application.publish_data_setup_recipe(CONSUMER_ID, submission))

    with application.store.system_transaction(PROVIDER_ID):
        worker = threading.Thread(target=publish_recipe)
        worker.start()
        assert started.wait(timeout=5)
        _publish_scan(application, PROVIDER_ID, "v2", register=False)
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert len(results) == 1
    assert "BLOCKED_STALE_CAPABILITY" in {issue.code for issue in results[0].issues}
    assert application.data_setup_recipe_catalog(CONSUMER_ID).recipes == []


@pytest.mark.parametrize(
    "tamper_kind",
    ["fact_schema", "dependency_proof", "dependency_history", "entry"],
)
def test_stored_recipe_rejects_forged_program_evidence(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    """手工篡改程序派生Schema或依赖证明后，读取API不得仍称其为已验证Recipe。

    Args:
        tmp_path: Pytest隔离知识、规则和Recipe目录。
        tamper_kind: 本轮篡改Fact Schema或跨系统依赖证明。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    submission = _recipe_submission(manifest, provider, consumer, tamper_kind, "SINGLE")
    published = application.publish_data_setup_recipe(CONSUMER_ID, submission)
    assert published.status == "PUBLISHED"

    # 绕开发布API直接模拟Git文件被人工或异常流程修改，验证读取边界会重新派生证据。
    recipe_path = (
        application.store.system_root(CONSUMER_ID)
        / "recipes"
        / "setup"
        / f"{submission.recipe_id.replace(':', '--')}.yaml"
    )
    payload = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    if tamper_kind == "fact_schema":
        payload["fact_outputs"][0]["fact_schema"]["properties"]["resourceId"]["type"] = "integer"
    elif tamper_kind == "dependency_proof":
        payload["dependency_proofs"][0]["role"] = "DOWNSTREAM"
    elif tamper_kind == "dependency_history":
        # 字段关系完全自洽但没有外部历史记录，不能冒充发布时真实UPSTREAM授权。
        payload["dependency_proofs"][0]["binding_revision_id"] = (
            "dependency-revision:00000000000000000000000000000000"
        )
    else:
        payload["entry_id"] = "facade:sample.missing.Entry#run"
    recipe_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeValidationError, match="data setup recipe"):
        application.get_data_setup_recipe(CONSUMER_ID, submission.recipe_id)


def test_fact_contract_versions_cannot_be_removed_or_redefined(tmp_path: Path) -> None:
    """已开放给Recipe的Fact contract必须通过新版本演进，不能同ID改写或删除。

    Args:
        tmp_path: Pytest隔离规则与系统目录。
    """

    application, _, _, _ = _prepare_workspace(tmp_path)
    original = application.setup_contract_rules.read(CONSUMER_ID)
    changed_contract = original.fact_contracts[0].model_copy(
        update={"required_origin": SetupFactOrigin.PUBLISHED_OUTPUT}
    )

    # 输入授权仍可替换，但事实语义版本一旦发布必须保持完整且逐字段不变。
    with pytest.raises(KnowledgeValidationError, match="immutable"):
        application.setup_contract_rules.write(
            original.model_copy(update={"fact_contracts": [changed_contract]})
        )
    with pytest.raises(KnowledgeValidationError, match="immutable"):
        application.setup_contract_rules.write(
            original.model_copy(update={"fact_contracts": []})
        )
    assert application.setup_contract_rules.read(CONSUMER_ID) == original


def test_fact_names_are_unambiguous_and_dependency_revocation_keeps_history(
    tmp_path: Path,
) -> None:
    """Fact名称不得含路径分隔符，依赖撤销后不可变历史Recipe仍应可读。

    Args:
        tmp_path: Pytest隔离知识与Recipe目录。
    """

    with pytest.raises(ValidationError):
        RecipeFactOutputSubmission(
            fact_name="seed.order",
            fact_contract_id=FACT_CONTRACT_ID,
            from_step_id="prepare-upstream-resource",
            output_path="resource",
        )

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    submission = _recipe_submission(manifest, provider, consumer, "history", "SINGLE")
    assert application.publish_data_setup_recipe(CONSUMER_ID, submission).status == "PUBLISHED"

    # 撤销SETUP用途只影响未来执行授权；阶段4目录继续展示当时冻结的真实证明。
    application.put_system_dependency_binding(
        CONSUMER_ID,
        SystemDependencyBindingSubmission(
            provider_system_id=PROVIDER_ID,
            role=SystemDependencyRole.DOWNSTREAM,
            purposes=[SystemDependencyPurpose.ACTION],
        ),
    )
    current_rules = application.setup_contract_rules.read(CONSUMER_ID)
    replaced_provider_policy = current_rules.input_policies[0].model_copy(
        update={"allowed_literal_values": ["OTHER_PARTITION"]}
    )
    application.setup_contract_rules.write(
        current_rules.model_copy(
            update={
                "input_policies": [
                    replaced_provider_policy,
                    current_rules.input_policies[1],
                ]
            }
        )
    )
    history = application.get_data_setup_recipe(CONSUMER_ID, submission.recipe_id)
    assert history.dependency_proofs[0].role == SystemDependencyRole.UPSTREAM
    assert history.dependency_proofs[0].purpose == SystemDependencyPurpose.SETUP


def test_unclassified_fixture_literal_and_forward_fact_fail_closed(tmp_path: Path) -> None:
    """未分类输入、Fixture错型、宽松布尔白名单和前向Fact均不得发布。

    Args:
        tmp_path: Pytest隔离规则、Published和Recipe目录。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    original = _recipe_submission(manifest, provider, consumer, "input-boundaries", "SINGLE")
    original_rules = application.setup_contract_rules.read(CONSUMER_ID)
    consumer_policy = original_rules.input_policies[1]

    # 删除provider输入分类后，程序必须明确返回缺策略而不是默认允许literal。
    application.setup_contract_rules.write(
        original_rules.model_copy(update={"input_policies": [consumer_policy]})
    )
    missing_policy = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(update={"recipe_id": "setup:generic-resource-missing-policy"}),
    )

    # Fixture只有形状可持久化；即使被授权，路径类型也必须能赋给Published输入。
    fixture_policy = SetupInputPolicy(
        capability_ref=PublishedCapabilityRef(
            system_id=provider.system_id,
            capability_id=provider.capability_id,
        ),
        input_path="request_id",
        allowed_sources=["fixture"],
    )
    application.setup_contract_rules.write(
        original_rules.model_copy(
            update={"input_policies": [fixture_policy, consumer_policy]}
        )
    )
    fixture_step = original.steps[0].model_copy(
        update={
            "input_bindings": {
                "request_id": SetupInputBinding(source="fixture", path="resource_partition")
            }
        }
    )
    fixture_mismatch = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-fixture-mismatch",
                "fixture_schema": {
                    "type": "object",
                    "properties": {"resource_partition": {"type": "integer"}},
                    "required": ["resource_partition"],
                    "additionalProperties": False,
                },
                "steps": [fixture_step, original.steps[1]],
            }
        ),
    )

    # Python中True等于1；类型敏感白名单必须仍将其视为不同规则值。
    numeric_literal_policy = fixture_policy.model_copy(
        update={"allowed_sources": ["literal"], "allowed_literal_values": [1]}
    )
    application.setup_contract_rules.write(
        original_rules.model_copy(
            update={"input_policies": [numeric_literal_policy, consumer_policy]}
        )
    )
    boolean_step = original.steps[0].model_copy(
        update={"input_bindings": {"request_id": SetupInputBinding(source="literal", value=True)}}
    )
    boolean_literal = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-boolean-literal",
                "steps": [boolean_step, original.steps[1]],
            }
        ),
    )

    # 第一步不能读取由自己或更后步骤产生的Fact，即使字段Schema最终能够匹配。
    application.setup_contract_rules.write(original_rules)
    forward_step = original.steps[0].model_copy(
        update={
            "input_bindings": {
                "request_id": SetupInputBinding(
                    source="fact",
                    path="prepared_resource.resourceId",
                )
            }
        }
    )
    provider_fact_policy = original_rules.input_policies[0].model_copy(
        update={"allowed_sources": ["fact"], "allowed_literal_values": []}
    )
    application.setup_contract_rules.write(
        original_rules.model_copy(
            update={"input_policies": [provider_fact_policy, consumer_policy]}
        )
    )
    forward_fact = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-forward-fact",
                "steps": [forward_step, original.steps[1]],
            }
        ),
    )

    assert "SETUP_INPUT_POLICY_MISSING" in {issue.code for issue in missing_policy.issues}
    assert "SETUP_INPUT_TYPE_MISMATCH" in {issue.code for issue in fixture_mismatch.issues}
    assert "SETUP_LITERAL_VALUE_FORBIDDEN" in {issue.code for issue in boolean_literal.issues}
    assert "SETUP_FACT_SEQUENCE_INVALID" in {issue.code for issue in forward_fact.issues}
    assert application.data_setup_recipe_catalog(CONSUMER_ID).recipes == []


def test_required_fact_constraint_and_cross_process_lock_are_enforced(tmp_path: Path) -> None:
    """缺少服务器必需约束时阻塞，跨进程provider锁也必须冻结Recipe发布。

    Args:
        tmp_path: Pytest隔离知识、规则和POSIX锁目录。
    """

    application, manifest, provider, consumer = _prepare_workspace(tmp_path)
    original = _recipe_submission(manifest, provider, consumer, "process-lock", "SINGLE")
    missing_state = original.fact_outputs[0].model_copy(
        update={"constraints": original.fact_outputs[0].constraints[1:]}
    )
    missing_constraint = application.publish_data_setup_recipe(
        CONSUMER_ID,
        original.model_copy(
            update={
                "recipe_id": "setup:generic-resource-missing-constraint",
                "fact_outputs": [missing_state],
            }
        ),
    )
    assert "SETUP_FACT_REQUIRED_CONSTRAINT_MISSING" in {
        issue.code for issue in missing_constraint.issues
    }

    # 子进程持有provider flock时，父进程中的跨系统发布线程不能越过锁完成校验写入。
    process_context = multiprocessing.get_context("spawn")
    ready = process_context.Event()
    release = process_context.Event()
    lock_holder = process_context.Process(
        target=_hold_system_lock,
        args=(str(application.knowledge_root), PROVIDER_ID, ready, release),
    )
    results = []

    def publish_after_process_lock() -> None:
        """在父进程线程中提交Recipe并保存跨进程锁释放后的结果。"""

        results.append(application.publish_data_setup_recipe(CONSUMER_ID, original))

    lock_holder.start()
    assert ready.wait(timeout=10)
    worker = threading.Thread(target=publish_after_process_lock)
    worker.start()
    time.sleep(0.2)
    assert worker.is_alive()
    release.set()
    lock_holder.join(timeout=10)
    worker.join(timeout=10)

    assert lock_holder.exitcode == 0
    assert not worker.is_alive()
    assert [result.status for result in results] == ["PUBLISHED"]


def test_real_refund_booking_recipe_is_blocked_in_formal_asset_copy(
    tmp_path: Path,
) -> None:
    """正式Refund/Booking没有Published时只在原样隔离副本返回真实阻塞。

    Args:
        tmp_path: 承载正式Git知识与latest扫描的只读来源副本。

    Side Effects:
        只向隔离副本提交无效Recipe；正式知识仓库不写Recipe、能力或运行记录。
    """

    project_root = Path(__file__).resolve().parents[2]
    formal_root = project_root / "open-test-knowledge"
    isolated_root = tmp_path / "open-test-knowledge"
    shutil.copytree(
        formal_root,
        isolated_root,
        ignore=shutil.ignore_patterns(".opentest", ".git", "__pycache__"),
    )
    shutil.copytree(
        formal_root / ".opentest" / "scans",
        isolated_root / ".opentest" / "scans",
    )
    application = OpenTestApplication(isolated_root)
    refund_system_id = "ifightchainsaas.java.refund.core"
    booking_system_id = "ifightchainsaas.java.booking.core"
    refund_system = application.store.get_system(refund_system_id)
    booking_system = application.store.get_system(booking_system_id)
    if not Path(refund_system.source_path).is_dir() or not Path(booking_system.source_path).is_dir():
        pytest.skip("真实退款或Booking注册源码在当前机器不可用")
    refund_manifest = application.source_analysis.artifacts.read(refund_system_id, "latest")
    create_order_entry = next(
        entry
        for entry in refund_manifest.entries
        if entry.display_name == "RefundFacade#createOrder"
    )
    booking_candidate = next(
        candidate
        for candidate in application.candidate_operation_catalog(booking_system_id).candidates
        if candidate.entry_ids
    )
    formal_recipe_root = (
        formal_root / "systems" / refund_system_id / "recipes" / "setup"
    )
    formal_files_before = sorted(formal_recipe_root.glob("*.yaml")) if formal_recipe_root.exists() else []
    submission = DataSetupRecipeSubmission(
        recipe_id="setup:real-ticketed-order-blocked",
        entry_id=create_order_entry.entry_id,
        entry_source_scan_id=refund_manifest.scan_id,
        name="真实上游出票订单前置",
        steps=[
            DataSetupStep(
                step_id="prepare-ticketed-order",
                capability_ref=PublishedCapabilityRef(
                    system_id=booking_system_id,
                    capability_id=booking_candidate.candidate_id,
                ),
            )
        ],
        fact_outputs=[
            RecipeFactOutputSubmission(
                fact_name="ticketed_order",
                fact_contract_id="ticketed-order/v1",
                from_step_id="prepare-ticketed-order",
                output_path="ticketed_order",
            )
        ],
    )

    result = application.publish_data_setup_recipe(refund_system_id, submission)

    assert result.status == "BLOCKED"
    assert "BLOCKED_UNPUBLISHED_CAPABILITY" in {issue.code for issue in result.issues}
    isolated_recipe_root = (
        isolated_root / "systems" / refund_system_id / "recipes" / "setup"
    )
    assert not isolated_recipe_root.exists()
    assert (
        sorted(formal_recipe_root.glob("*.yaml")) if formal_recipe_root.exists() else []
    ) == formal_files_before
