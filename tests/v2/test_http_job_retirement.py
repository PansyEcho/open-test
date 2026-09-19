"""验证HTTP Job退役不会删除通过DSF发布的同名业务入口。"""

from pathlib import Path

import pytest

from opentest.adapters.environment_config import LocalSystemSettingsStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.operations import LocalQaOperationProvider, OperationCapabilityCatalog
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    DsfOperationDefinition, DsfOperationMutability, EntryPoint, KnowledgeNodeKind,
    OperationCapability, OperationExecutionRequest, OperationKind, OperationMutability,
    ScanManifest, SourceBaseline, SourceReference, SystemDefinition,
)


def test_resource_settings_preserve_inert_legacy_keys_without_resolving_them(tmp_path: Path) -> None:
    """资源配置更新不消费、回显或清除历史Labrador值。

    Args:
        tmp_path: 隔离本地环境目录。
    """

    store = LocalSystemSettingsStore(tmp_path)
    store.write("refund", "${ENV:ABSENT_LEGACY_SECRET}", "http://legacy/job", "test")
    before = store.snapshot("refund")
    settings = store.write_resource_settings("refund", "uat")
    after = store.snapshot("refund")
    # 新入口只改变资源选择，旧配置不会因不可解析环境变量阻断保存。
    assert after == before.replace("resource_config_environment: test", "resource_config_environment: uat")
    assert settings.qa_labrador_token == ""
    assert settings.qa_gateway_prefix == ""
    assert store.read_resource_settings("refund").resource_config_environment == "uat"


def test_catalog_keeps_dsf_execute_job_and_omits_http_job(tmp_path: Path) -> None:
    """同名Job业务通过Facade DSF保留，旧HTTP Job入口退出活动能力目录。

    Args:
        tmp_path: 隔离注册系统与历史扫描。
    """

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="refund", name="refund", source_path=str(source)))
    baseline = SourceBaseline(source_path=str(source), commit="fixed-source")
    facade = EntryPoint(entry_id="facade:demo.CommonFacade#executeJob", system_id="refund", kind=KnowledgeNodeKind.FACADE,
                        display_name="CommonFacade#executeJob", source_id="demo.CommonFacade#executeJob", source_path=str(source / "CommonFacade.java"))
    job = EntryPoint(entry_id="job:legacy", system_id="refund", kind=KnowledgeNodeKind.JOB,
                     display_name="legacy", source_id="legacy", source_path=str(source / "Job.java"))
    operation = DsfOperationDefinition(operation_id="dsf:refund:common:executeJob", provider_system_id="refund",
                                       gs_name="dsf.refund", service_name="common", version="1", action="executeJob",
                                       mutability=DsfOperationMutability.WRITE,
                                       source_refs=[SourceReference(path="CommonFacade.java", symbol=facade.source_id)])
    manifest = ScanManifest(scan_id="scan-refund", system_id="refund", baseline=baseline, entries=[facade, job], dsf_operations=[operation])
    artifacts = SourceScanArtifactStore(store.root)
    artifacts.write_manifest(manifest)
    # 固定scan投影仍能执行DSF入口，历史HTTP工具无需存在或配置Token。
    capabilities = OperationCapabilityCatalog(store, artifacts).derive("refund", manifest.scan_id)
    assert [item.operation_id for item in capabilities] == [facade.entry_id]
    assert capabilities[0].executable is True
    assert capabilities[0].required_local_bindings == []


def test_legacy_http_job_execution_stops_before_configuration_or_subprocess() -> None:
    """历史Job调用在provider边界立即拒绝，不读取任何配置或启动脚本。"""

    provider = LocalQaOperationProvider(None, None, None)
    capability = OperationCapability(operation_id="job:legacy", system_id="refund", business_name="old job",
                                     kind=OperationKind.JOB, mutability=OperationMutability.JOB, source_scan_id="scan-old")
    request = OperationExecutionRequest(operation_id=capability.operation_id, request_id="retired-job-request")
    # 空依赖刻意证明拒绝发生在读取任何历史存储之前。
    with pytest.raises(KnowledgeValidationError, match="HTTP Job已退役"):
        provider.execute_job(capability, request)
    with pytest.raises(KnowledgeValidationError, match="HTTP Job已退役"):
        provider.for_execution(["refund"], "qa", ["refund"])
