"""验证真实Operation工作流固定各项目Profile，最终远端派发使用本地替身。"""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from opentest.adapters.environment_config import LocalEnvironmentLoader, LocalSystemSettingsStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_execution_store import OperationExecutionStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.dsf_operations import DsfOperationService
from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4
from opentest.application.operations import LocalQaOperationProvider, OperationExecutionService
from opentest.application.tasks import LocalTaskManager
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.case_template_v4 import (
    CaseTemplateGenerationV4, CaseTemplateSubmission, CaseVariantV4,
    RuntimeFunctionDescriptor, RuntimeFunctionRegistry,
)
from opentest.domain.models import (
    DsfClientProfile,
    DsfExecutionRequest,
    DsfExecutionResponse,
    DsfOperationDefinition,
    DsfOperationMutability,
    EntryPoint,
    KnowledgeNodeKind,
    OperationCapability,
    OperationExecutionRequest,
    OperationExecutionStatus,
    OperationInputKnowledgeContract,
    OperationKind,
    OperationMutability,
    ScanManifest,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
    ToolDefinition,
    ToolExecutionResult,
)


def _write_filter(source: Path, system_id: str, actual: str) -> None:
    """写入测试项目自己的DSF及资源配置，模拟实际test/dev部署。

    Args:
        source: 已注册项目的临时源码目录。
        system_id: 拥有该filter的项目。
        actual: 实际配置、路由及资源环境名称。
    Returns:
        None；只写入隔离测试目录，不访问远端服务。
    """

    filters = source / "conf/filter"
    filters.mkdir(parents=True, exist_ok=True)
    # 同一项目Profile提供完整DSF身份，避免Mock配置解析掩盖跨项目混用。
    (filters / f"application.{actual}").write_text(
        f"dsf.service.config.registryhost={system_id}-{actual}.invalid\n"
        f"dsf.service.config.name={system_id}-client\n"
        f"dsf.service.config.env={actual}\n"
        f"dsf.service.config.targetenv={actual}\n"
        f"uniform.env={actual}\n",
        encoding="utf-8",
    )


def _worker_response(
    system_id: str, profile: DsfClientProfile,
    operation: DsfOperationDefinition, request: DsfExecutionRequest,
) -> DsfExecutionResponse:
    """提供最终DSF Worker响应，保留应用层真实派发与结果持久化。

    Args:
        system_id: 派发归属项目。
        profile: 应用层本次运行解析的环境Profile。
        operation: 固定源码扫描的操作坐标。
        request: 当前业务参数和逻辑环境。
    Returns:
        本地成功响应；不启动Worker或发起网络请求。
    """

    # 回显业务身份即可；连接地址和凭据不作为模拟业务数据返回。
    assert profile.system_id == system_id
    assert request.environment == profile.environment
    return DsfExecutionResponse(
        request_id="local-worker-response", operation_id=operation.operation_id,
        status="success", output={"systemId": system_id},
    )


@pytest.fixture
def profile_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """建立真实注册、固定扫描、Profile、异步任务及Operation结果存储。

    Args:
        tmp_path: pytest隔离目录。
        monkeypatch: 观察旧脚本适配器，验证退役Job从未调用它。
    Yields:
        两项目工作流服务、固定能力、配置及最终派发观察替身。
    Side Effects:
        创建临时文件及任务线程，退出时等待任务结束并释放线程。
    """

    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.initialize()
    artifacts = SourceScanArtifactStore(store.root)
    settings = LocalSystemSettingsStore(tmp_path / "environments")
    capabilities = {}
    sources = {}
    # 固定A只包含调用坐标；执行Profile来自当前注册项目，且不发布latest。
    for system_id, actual in (("refund", "test"), ("supplement", "dev")):
        source = tmp_path / system_id
        _write_filter(source, system_id, actual)
        sources[system_id] = source
        store.register_system(SystemDefinition(system_id=system_id, name=system_id, source_path=str(source)))
        settings.write(system_id, "", resource_config_environment=actual, environment="qa")
        operation = DsfOperationDefinition(
            operation_id=f"dsf:{system_id}:report:query", provider_system_id=system_id,
            gs_name=f"{system_id}-baseline-a", service_name="report", version="version-a", action="query",
            mutability=DsfOperationMutability.READ_ONLY,
            source_refs=[SourceReference(path="Report.java", symbol="query")],
        )
        manifest = ScanManifest(
            scan_id=f"scan-{system_id}-a", system_id=system_id,
            baseline=SourceBaseline(source_path=str(source), commit="baseline-a"), dsf_operations=[operation],
        )
        artifacts.write_manifest(manifest)
        capabilities[system_id] = OperationCapability(
            operation_id=f"facade:{system_id}.ReportFacade#query", system_id=system_id,
            business_name="查询关联报表", kind=OperationKind.FACADE, mutability=OperationMutability.READ_ONLY,
            executable=True, provider_operation_id=operation.operation_id, source_scan_id=manifest.scan_id,
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )

    # Job身份及生成脚本属于固定扫描；后续Profile只允许替换部署网关。
    tool_root = tmp_path / "fixed-tools"
    tool_root.mkdir()
    script = tool_root / "retry.sh"
    script.write_text("#!/bin/sh\n# frozen QA URL: https://old-qa.invalid/refund/job/retry-refund\n", encoding="utf-8")
    tool = ToolDefinition(
        tool_id="job.retry-refund", system_id="refund", display_name="退票重试Job",
        script_path=str(script), source_id="demo.RefundJob#retry",
        metadata={"tool_type": "job_http_trigger", "default_url": "https://old-qa.invalid/refund/job/retry-refund"},
    )
    entry = EntryPoint(
        entry_id="job:demo.RefundJob#retry", system_id="refund", kind=KnowledgeNodeKind.JOB,
        display_name="退票重试Job", source_id=tool.source_id, source_path="RefundJob.java",
        tool_id=tool.tool_id, metadata={"job_code": "retry-refund"},
    )
    job_manifest = ScanManifest(
        scan_id="scan-refund-job-a", system_id="refund",
        baseline=SourceBaseline(source_path=str(sources["refund"]), commit="baseline-a"),
        tools=[tool], entries=[entry], tool_root=str(tool_root),
    )
    artifacts.write_manifest(job_manifest)
    job = OperationCapability(
        operation_id=entry.entry_id, system_id="refund", business_name=entry.display_name,
        kind=OperationKind.JOB, mutability=OperationMutability.WRITE, executable=True,
        provider_operation_id=tool.tool_id, source_scan_id=job_manifest.scan_id,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )
    dsf_worker = Mock()
    dsf_worker.execute.side_effect = _worker_response
    job_dispatch = Mock(return_value=ToolExecutionResult(
        tool_id=tool.tool_id, exit_code=0, command=[], output={"accepted": True}, elapsed_seconds=0,
    ))
    monkeypatch.setattr("opentest.adapters.dsf_executor.DsfExecutor.execute", job_dispatch)
    dsf = DsfOperationService(store, artifacts, Mock(), Mock(), dsf_worker)
    provider = LocalQaOperationProvider(dsf, artifacts, LocalEnvironmentLoader(settings.environment_root))
    catalog = SimpleNamespace(store=store, artifacts=artifacts, derive=Mock(side_effect=AssertionError("latest forbidden")))
    tasks = LocalTaskManager(tmp_path / "tasks")
    records = OperationExecutionStore(tmp_path / "runs")
    service = OperationExecutionService(catalog, Mock(), records, tasks, provider)
    try:
        yield SimpleNamespace(
            service=service, settings=settings, sources=sources, records=records, tasks=tasks,
            catalog=catalog, artifacts=artifacts, capabilities=capabilities,
            dsf_worker=dsf_worker, job=job, job_manifest=job_manifest, job_dispatch=job_dispatch, script=script,
        )
    finally:
        tasks.close()


def test_one_qa_run_uses_each_project_profile_and_persists_actual_environment(profile_workflow: SimpleNamespace) -> None:
    """同一逻辑QA运行分别使用退票test与补单dev，并持久化各自实际环境。

    Args:
        profile_workflow: 两项目真实本地工作流及最终Worker替身。
    Returns:
        None；固定操作、项目配置与落盘记录均一致时通过。
    """

    bound = profile_workflow.service.for_execution(["refund", "supplement"], "qa")
    for system_id, actual in (("refund", "test"), ("supplement", "dev")):
        capability = profile_workflow.capabilities[system_id]
        request = OperationExecutionRequest(
            operation_id=capability.operation_id, request_id=f"qa-{system_id}-001", environment="qa",
        )
        record = bound.execute_resolved("refund", capability, request)
        assert record.status == OperationExecutionStatus.COMPLETED
        # 使用新存储实例重读，避免只验证内存对象而遗漏持久化。
        persisted = OperationExecutionStore(profile_workflow.records.root.parent).get(record.execution_id)
        assert persisted.environment == "qa"
        assert persisted.source_scan_id == f"scan-{system_id}-a"
        assert persisted.environment_details == {
            "config_environment": actual, "routing_environment": actual,
            "target_environment": actual, "resource_environment": "",
        }
        dispatched_system, profile, operation, dispatched_request = profile_workflow.dsf_worker.execute.call_args.args
        assert dispatched_system == system_id
        assert profile.target_environment == actual
        assert dispatched_request.environment == "qa"
        assert operation.gs_name == f"{system_id}-baseline-a"
        assert operation.version == "version-a"
    assert profile_workflow.dsf_worker.execute.call_count == 2
    profile_workflow.catalog.derive.assert_not_called()


def test_profile_update_only_affects_the_next_run(profile_workflow: SimpleNamespace) -> None:
    """运行绑定后修改补单Profile，只影响下次新运行，后续步骤仍使用dev。

    Args:
        profile_workflow: 两项目服务、配置文件及派发观察替身。
    Returns:
        None；本次运行配置稳定且新运行读取更新时通过。
    """

    bound = profile_workflow.service.for_execution(["refund", "supplement"], "qa")
    _write_filter(profile_workflow.sources["supplement"], "supplement", "test")
    profile_workflow.settings.write("supplement", "", resource_config_environment="test", environment="qa")
    capability = profile_workflow.capabilities["supplement"]
    # 内部数据准备再次绑定相同范围，仍复用外层运行；显式新运行才读取test。
    nested = bound.for_execution(["supplement"], "qa")
    next_run = profile_workflow.service.for_execution(["refund", "supplement"], "qa")
    for index, (service, actual) in enumerate(((bound, "dev"), (nested, "dev"), (next_run, "test"))):
        record = service.execute_resolved("refund", capability, OperationExecutionRequest(
            operation_id=capability.operation_id, request_id=f"profile-run-{index}", environment="qa",
        ))
        assert record.status == OperationExecutionStatus.COMPLETED
        assert record.environment_details["target_environment"] == actual
        assert record.source_scan_id == capability.source_scan_id
    assert [call.args[1].target_environment for call in profile_workflow.dsf_worker.execute.call_args_list] == ["dev", "dev", "test"]
    profile_workflow.catalog.derive.assert_not_called()


def test_missing_project_profile_stops_before_any_business_dispatch(profile_workflow: SimpleNamespace) -> None:
    """有限跨系统运行缺少补单QA配置时，在退票或补单调用发生前报告缺口。

    Args:
        profile_workflow: 已注册两项目，随后删除一个必需Profile的测试范围。
    Returns:
        None；缺口具体且没有业务派发或半绑定运行时通过。
    """

    (profile_workflow.settings.environment_root / "supplement/qa.yaml").unlink()
    # 全范围预解析失败必须发生在第一个操作写记录和派发之前。
    with pytest.raises(KnowledgeValidationError, match="supplement: qa"):
        profile_workflow.service.for_execution(["refund", "supplement"], "qa")
    profile_workflow.dsf_worker.execute.assert_not_called()
    profile_workflow.job_dispatch.assert_not_called()
    assert not profile_workflow.records.root.exists()
    assert not profile_workflow.service.provider._execution_profiles


def test_missing_required_dsf_fields_stops_the_complete_plan_before_dispatch(profile_workflow: SimpleNamespace) -> None:
    """补单QA文件存在但实际dev缺少DSF字段时，整个有限计划不得先调用退票。

    Args:
        profile_workflow: 两项目真实服务、固定能力和Worker观察替身。
    Returns:
        None；完整操作范围预检报告项目/逻辑环境缺口且零派发时通过。
    """

    (profile_workflow.sources['supplement'] / 'conf/filter/application.dev').write_text(
        'uniform.env=dev\n', encoding='utf-8',
    )
    # Profile文件存在不代表能执行计划中的DSF；仅检查本次实际使用的两项操作。
    with pytest.raises(KnowledgeValidationError, match='supplement/qa'):
        profile_workflow.service.for_execution(
            ['refund', 'supplement'], 'qa', capabilities=list(profile_workflow.capabilities.values()),
        )
    profile_workflow.dsf_worker.execute.assert_not_called()
    profile_workflow.job_dispatch.assert_not_called()
    assert not profile_workflow.records.root.exists()


def test_blocked_variant_observer_profile_does_not_block_runnable_case(profile_workflow: SimpleNamespace) -> None:
    """编译阻塞Case独有的补单观察配置缺失，不阻断只调用退票的可运行Case。

    Args:
        profile_workflow: 两项目真实Operation服务、Profile与最终Worker替身。
    Returns:
        None；退票正常执行一次、阻塞Case原样保留且未读取补单环境时通过。
    """

    (profile_workflow.settings.environment_root / 'supplement/qa.yaml').unlink()
    target = profile_workflow.capabilities['refund'].model_copy(update={'input_schema': {
        'type': 'object', 'properties': {'id': {'type': 'integer'}}, 'additionalProperties': False,
    }})
    observer = profile_workflow.capabilities['supplement']
    assertion = {'actual_path': 'systemId', 'operator': 'eq', 'expected': {'kind': 'literal', 'value': 'refund'}}
    template = {
        'template_id': 'local_query', 'title': '退票查询', 'coverage_kind': 'business',
        'request_bindings': [{'field': 'id', 'source': {'kind': 'literal', 'value': 1}}],
        'combination': 'each', 'oracles': [{'oracle_id': 'response_owner', 'channel': 'response', 'assertions': [assertion]}],
        'evidence': [{'source_system_id': 'refund', 'path': 'Report.java'}],
    }
    # 独立模板只对应编译阻塞Variant，用于防止遍历全部模板时误把该观察项目纳入预检。
    blocked_template = {**template, 'template_id': 'blocked_observer', 'oracles': [{
        'oracle_id': 'remote_observer', 'channel': 'operation', 'function_id': 'runtime.supplement_query',
        'assertions': [assertion],
    }]}
    submission = CaseTemplateSubmission(data_functions=[], case_templates=[template, blocked_template], unresolved=[])
    variants = [CaseVariantV4(
        variant_id='case-variant-v4-' + f'{index:020x}', template_id=item.template_id, ordinal=index,
        parameter_values={}, request_values={}, data_calls=[], oracles=item.oracles,
        blocked_reason='编译时观察条件未确认' if index == 2 else '',
    ) for index, item in enumerate(submission.case_templates, 1)]
    generation = CaseTemplateGenerationV4(
        generation_id='case-template-generation-' + 'c' * 20, system_id='refund', operation_id=target.operation_id,
        source_scan_id=target.source_scan_id, coverage_id='coverage:refund-query', status='PARTIAL',
        runtime_registry_version='runtime-functions/v1', value_registry_version='value-functions/v1',
        input_contract=OperationInputKnowledgeContract(
            target_id=target.operation_id, source_scan_id=target.source_scan_id, status='READY',
            request_schema=target.input_schema,
            fields=[{'path': 'id', 'field_name': 'id', 'schema': {'type': 'integer'}}],
        ), submission=submission, variants=variants,
    )
    registry = RuntimeFunctionRegistry(functions=[RuntimeFunctionDescriptor(
        function_id='runtime.supplement_query', kind='dsf', description='补单只读观察', input_schema=observer.input_schema,
        output_schema={'type': 'object'}, allowed_phases=['ORACLE'], source_system_id='supplement',
        provider_ref=observer.operation_id,
    )])
    executor = CaseTemplateExecutorV4(
        profile_workflow.service, consumer_system_id='refund', capabilities=[target, observer],
    )
    completed, blocked = executor.execute('case-generation-execution-' + 'c' * 20, generation, registry, 'qa')
    assert completed.status == 'COMPLETED', completed.error
    assert completed.assertions[0].passed
    assert completed.operations[0].environment_details['target_environment'] == 'test'
    assert blocked.status == 'BLOCKED'
    assert blocked.error == '编译时观察条件未确认'
    assert not blocked.operations
    profile_workflow.dsf_worker.execute.assert_called_once()
    assert profile_workflow.dsf_worker.execute.call_args.args[0] == 'refund'


def test_retired_uat_job_does_not_read_gateway_or_change_fixed_script(profile_workflow: SimpleNamespace) -> None:
    """即使旧UAT配置完整，退役HTTP Job也必须在环境解析前停止。

    Args:
        profile_workflow: 固定Job扫描、真实Provider及脚本派发替身。
    Returns:
        None；旧脚本和派发替身均未被调用时通过。
    """

    _write_filter(profile_workflow.sources["refund"], "refund", "dev")
    profile_workflow.settings.write(
        "refund", "uat-fixture-token", "https://uat.invalid/current-refund/v2",
        resource_config_environment="dev", environment="uat",
    )
    frozen_script = profile_workflow.script.read_bytes()
    # 历史配置的完整性不意味着用户重新启用了HTTP Job能力。
    with pytest.raises(KnowledgeValidationError, match="HTTP Job已退役"):
        profile_workflow.service.for_execution(["refund"], "uat", ["refund"])
    profile_workflow.job_dispatch.assert_not_called()
    assert profile_workflow.script.read_bytes() == frozen_script
    profile_workflow.catalog.derive.assert_not_called()


@pytest.mark.parametrize("gateway", [
    "", "https://uat.invalid", "https://uat.invalid/refund?override=qa",
    "https://user:password@uat.invalid/refund", "https://uat.invalid:invalid/refund",
])
def test_missing_or_invalid_job_gateway_never_dispatches(profile_workflow: SimpleNamespace, gateway: str) -> None:
    """缺失或无效UAT网关不被解析，历史Job统一在退役边界拒绝。

    Args:
        profile_workflow: 真实Profile和异步Job工作流。
        gateway: 本地配置可能留下的缺失或非法地址。
    Returns:
        None；退役原因明确且最终脚本从未执行时通过。
    """

    path = profile_workflow.settings.environment_root / "refund/uat.yaml"
    # 直接模拟已有本地配置，验证执行入口独立防守而非只依赖设置表单。
    path.write_text(yaml.safe_dump({
        "system_id": "refund", "environment": "uat", "resource_config_environment": "test",
        "qa_gateway_prefix": gateway,
    }), encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="HTTP Job已退役"):
        profile_workflow.service.for_execution(["refund"], "uat", ["refund"])
    profile_workflow.job_dispatch.assert_not_called()
    profile_workflow.dsf_worker.execute.assert_not_called()


def test_job_source_identity_mismatch_never_dispatches(profile_workflow: SimpleNamespace) -> None:
    """不一致的历史Job扫描也不能越过退役边界启动脚本。

    Args:
        profile_workflow: 可执行Job工作流及固定扫描存储。
    Returns:
        None；无论旧绑定内容如何都拒绝HTTP派发时通过。
    """

    profile_workflow.settings.write(
        "refund", "", "https://uat.invalid/refund/v2", resource_config_environment="test", environment="uat",
    )
    manifest = profile_workflow.job_manifest.model_copy(deep=True)
    manifest.entries[0].metadata["job_code"] = "different-job"
    # 故意保留坏扫描夹具，退役拒绝必须先于旧工具URL解析。
    profile_workflow.artifacts.write_manifest(manifest)
    with pytest.raises(KnowledgeValidationError, match="HTTP Job已退役"):
        profile_workflow.service.for_execution(["refund"], "uat", ["refund"])
    profile_workflow.job_dispatch.assert_not_called()


def test_shared_case_uat_materializes_fixed_source_for_target_and_external_owner(profile_workflow, tmp_path, monkeypatch):
    """无原仓库的新电脑执行共享Case时，目标及外部提供方都从共享固定源码解析真实UAT配置。"""

    import shutil
    import tarfile
    from opentest.adapters.shared_workspace_store import SharedWorkspaceStore
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.domain.case_template_v4 import CaseGenerationExecutionV4, CaseTemplateSourceScope
    from opentest.domain.shared_workspace import CreateCodeBaseline, StoredArtifact
    from test_case_template_v4_revision import _handoff
    from test_shared_baselines import BaselineDatabase

    database = BaselineDatabase()
    workspace = SharedWorkspaceStore(database)
    manifests, archives, scopes = {}, {}, []
    target = profile_workflow.capabilities["refund"].model_copy(update={"input_schema": {
        "type": "object", "properties": {"id": {"type": "integer"}}, "additionalProperties": False}})
    external_definition = DsfOperationDefinition(operation_id="dsf:external:supplement:query", provider_system_id="supplement",
        gs_name="supplement-baseline-a", service_name="report", version="version-a", action="query",
        request_schema={"type": "object", "properties": {}}, response_schema={"type": "object"},
        mutability=DsfOperationMutability.READ_ONLY, source_refs=[SourceReference(path="Report.java", symbol="query")])
    external = OperationCapability(operation_id="external:supplement:query", system_id="refund", business_name="补单观察",
        kind=OperationKind.EXTERNAL_DSF, mutability=OperationMutability.READ_ONLY, executable=True,
        source_scan_id=target.source_scan_id, provider_operation_id=external_definition.operation_id,
        provider_definition=external_definition, input_schema={"type": "object", "properties": {}})
    for system_id, actual, digit in [("refund", "test", "a"), ("supplement", "dev", "b")]:
        database.execute("INSERT INTO ot_system(system_id) VALUES(%s)", (system_id,))
        baseline = workspace.create_baseline(CreateCodeBaseline(system_id=system_id, source_commit=digit * 40,
            selected_revision="shared-release", user_id="employee-a"))
        original = profile_workflow.sources[system_id]
        archive = tmp_path / f"{system_id}-source.tar.gz"
        # 归档包含真实filter文件；删除作者目录后，测试只能从实际归档字节恢复。
        with tarfile.open(archive, "w:gz") as output:
            output.add(original / "conf", arcname="conf")
        artifact = StoredArtifact(artifact_id=f"source-{system_id}", artifact_kind="SOURCE", bucket="test",
            object_key=f"{system_id}.tar.gz", byte_size=archive.stat().st_size, content_type="application/gzip")
        workspace.register_artifact(artifact)
        workspace.attach_source(baseline.baseline_id, artifact.artifact_id, "employee-a")
        archives[artifact.artifact_id] = archive
        manifest = profile_workflow.artifacts.read(system_id, f"scan-{system_id}-a")
        manifest = manifest.model_copy(update={"baseline": SourceBaseline(source_path=str(original),
            snapshot_path=str(original / "author-snapshot"), commit=digit * 40)})
        if system_id == "refund":
            manifest = manifest.model_copy(update={"dsf_operations": [*manifest.dsf_operations, external_definition]})
        manifests[(system_id, manifest.scan_id)] = manifest
        scopes.append(CaseTemplateSourceScope(source_system_id=system_id, source_scan_id=manifest.scan_id,
            source_baseline=manifest.baseline, selected_operation_ids=[target.operation_id, external.operation_id]
            if system_id == "refund" else [profile_workflow.capabilities["supplement"].operation_id]))
        profile_workflow.settings.write(system_id, "", resource_config_environment=actual, environment="uat")
        shutil.rmtree(original)
    artifacts = SourceScanArtifactStore(tmp_path / "fresh-computer", database)

    def download(reference, destination):
        """对象存储仅提供原包真实字节，不能从错误本机绑定补全源码。"""

        shutil.copyfile(archives[reference.artifact_id], destination)
        return destination

    def read_manifest(system_id, scan_id):
        """仅接受固定scan读取，latest会在此直接失败。"""

        return manifests[(system_id, scan_id)]

    store = profile_workflow.catalog.store
    original_get = store.get_system
    wrong_root = tmp_path / "unrelated-checkout"
    _write_filter(wrong_root, "wrong-project", "dev")

    def local_system(system_id):
        """模拟目标未绑定、提供方绑定错误checkout，两者都不能影响共享Case配置来源。"""

        return original_get(system_id).model_copy(update={"source_path": "" if system_id == "refund" else str(wrong_root)})

    artifacts.object_storage = SimpleNamespace(download_file=download)
    monkeypatch.setattr(artifacts, "read", read_manifest)
    monkeypatch.setattr(store, "get_system", local_system)
    # 同批未选Case可能还登记其他系统，其源码包缺失不能阻塞当前实际调用集合。
    store.register_system(SystemDefinition(system_id="unused", name="未选Case的系统", source_path=""))
    scopes.append(CaseTemplateSourceScope(source_system_id="unused", source_scan_id="scan-unused",
        source_baseline=SourceBaseline(source_path="", commit="c" * 40), selected_operation_ids=["unused-operation"]))
    profile_workflow.service.provider.artifacts = artifacts
    profile_workflow.service.provider.dsf_operations.artifacts = artifacts
    assert not artifacts.source_snapshot_root.exists()
    oracle = {"oracle_id": "external-owner", "channel": "operation", "function_id": "external:supplement:query",
        "assertions": [{"actual_path": "systemId", "operator": "eq", "expected": {"kind": "literal", "value": "supplement"}}]}
    template = {"template_id": "single-query", "title": "共享查询", "coverage_kind": "business",
        "request_bindings": [{"field": "id", "source": {"kind": "literal", "value": 1}}],
        "combination": "each", "oracles": [oracle], "evidence": [{"source_system_id": "refund", "path": "Report.java"}]}
    submission = CaseTemplateSubmission(data_functions=[], case_templates=[template], unresolved=[])
    variant = CaseVariantV4(variant_id="case-variant-v4-" + "a" * 20, template_id="single-query", ordinal=1,
        parameter_values={}, request_values={"id": 1}, data_calls=[], oracles=submission.case_templates[0].oracles)
    handoff = _handoff(tmp_path).model_copy(update={"system_id": "refund", "entry_id": target.operation_id,
        "source_scan_id": target.source_scan_id, "baseline_id": "shared-baseline", "source_scopes": scopes})
    generation = CaseTemplateGenerationV4(generation_id="case-template-generation-" + "a" * 20,
        handoff_id=handoff.handoff_id, system_id="refund", operation_id=target.operation_id, source_scan_id=target.source_scan_id,
        baseline_id="shared-baseline", source_scopes=scopes, environment_id="uat", coverage_id="coverage:shared",
        status="READY", runtime_registry_version="runtime-functions/v1", value_registry_version="value-functions/v1",
        input_contract=OperationInputKnowledgeContract(target_id=target.operation_id, source_scan_id=target.source_scan_id,
            status="READY", request_schema=target.input_schema,
            fields=[{"path": "id", "field_name": "id", "schema": {"type": "integer"}}]), submission=submission, variants=[variant])
    registry = RuntimeFunctionRegistry(functions=[RuntimeFunctionDescriptor(function_id=external.operation_id,
        kind="dsf", description="外部观察", input_schema=external.input_schema, output_schema={"type": "object"},
        allowed_phases=["ORACLE"], source_system_id="refund", provider_ref=external.operation_id)])
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store = store
    engine.handoffs = SimpleNamespace(get=Mock(return_value=handoff))
    engine.runtime = SimpleNamespace(operation_service=profile_workflow.service, environment_provider=None,
        operation_catalog=SimpleNamespace(derive=Mock(side_effect=lambda system_id, *_args, **_kwargs:
            [target, external] if system_id == "refund" else [profile_workflow.capabilities["supplement"]])))
    engine.data_capabilities = None
    engine.executions = SimpleNamespace(update=lambda execution: execution)
    running = CaseGenerationExecutionV4(execution_id="case-generation-execution-" + "a" * 20,
        generation_id=generation.generation_id, system_id="refund", baseline_id="shared-baseline", environment_id="uat", status="RUNNING")
    completed = engine._run_execution(running, generation, registry, "fixed-source-run")
    assert completed.status == "PASSED", completed.model_dump_json()
    assert {call.args[0]: call.args[1].registry_host for call in profile_workflow.dsf_worker.execute.call_args_list} == {
        "refund": "refund-test.invalid", "supplement": "supplement-dev.invalid"}
    assert all(call.args[1].environment == "uat" for call in profile_workflow.dsf_worker.execute.call_args_list)
    assert profile_workflow.service.provider._fixed_source_scopes is None
    assert profile_workflow.service.provider._execution_profiles == {}
    assert store.get_system("refund").source_path == ""
    assert store.get_system("supplement").source_path == str(wrong_root)
    assert not artifacts.source_snapshot_path("unused", "c" * 40).exists()
    # 外部提供方必须持有自己的冻结范围；不能在缺失时偷偷读取错误本机checkout。
    incomplete = profile_workflow.service.for_fixed_sources([scopes[0]])
    with pytest.raises(KnowledgeValidationError, match="执行项目缺少固定源码"):
        incomplete.for_execution(["refund", "supplement"], "uat", capabilities=[target, external])
