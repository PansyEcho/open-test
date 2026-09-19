"""验证内存投影、统一QA操作、系统Skill和Codex原任务恢复契约。"""

from __future__ import annotations

import gc
import importlib.util
import json
import subprocess
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.adapters.knowledge_interview import KnowledgeInterviewStore
from opentest.adapters.environment_config import LocalEnvironmentLoader, LocalSystemSettingsStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_execution_store import OperationExecutionStore
from opentest.adapters.qa_active_worker import QaActiveWorkerLauncher
from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.application.catalogs import ScanCatalogService
from opentest.application.foundation import OpenTestApplication
from opentest.application.knowledge_discovery import KnowledgeDiscoveryService
from opentest.application.knowledge_context import knowledge_context_digest
from opentest.application.log_context import current_log_context
from opentest.application.operations import (
    LocalQaOperationProvider,
    OperationCapabilityCatalog,
    OperationExecutionService,
)
from opentest.application.tasks import LocalTaskManager
from opentest.domain.errors import (
    KnowledgeNotFoundError,
    KnowledgeValidationError,
    OperationProviderFailure,
    ScopeViolationError,
)
from opentest.domain.models import (
    DsfClientProfile,
    DsfOperationDefinition,
    DsfOperationMutability,
    DsfProfileStatus,
    DsfExecutionResponse,
    DiscoveredResource,
    EntryPoint,
    KnowledgeGenerationWorkflowBatch,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeStatus,
    KnowledgeTargetGenerationOutcome,
    KnowledgeTargetStatus,
    OperationCapability,
    OperationExecutionRequest,
    OperationExecutionStatus,
    OperationKind,
    OperationMutability,
    OperationProviderKind,
    ResourceKind,
    ResourceRole,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticFieldDefinition,
    SemanticMethodDefinition,
    SemanticTypeDefinition,
    SourceBaseline,
    SourceReference,
    SystemDefinition,
    ToolDefinition,
)


SYSTEM_ID = "ifightchainsaas.java.refund.core"
FACADE_OPERATION_ID = "facade:com.example.refund.RefundFacade#createOrder"
JOB_OPERATION_ID = "job:com.example.refund.RefundRetryJob#execute"


class CountingArtifactStore(SourceScanArtifactStore):
    """统计完整Manifest解析次数并可模拟一次构建失败。"""

    def __init__(self, knowledge_root: Path, delay_seconds: float = 0.0):
        """绑定测试知识根和可选并发放大延迟。

        Args:
            knowledge_root: 隔离知识仓库根。
            delay_seconds: 每次完整Manifest读取前的延迟。
        """

        super().__init__(knowledge_root)
        self.delay_seconds = delay_seconds
        self.read_count = 0
        self.fail_next_read = False
        self._count_lock = threading.Lock()

    def read(self, system_id: str, scan_id: str = "latest") -> ScanManifest:
        """统计并返回一个完整Manifest。

        Args:
            system_id: 固定测试系统。
            scan_id: latest或历史扫描ID。

        Returns:
            父存储校验后的Manifest。

        Raises:
            KnowledgeValidationError: 测试显式安排本次构建失败。
        """

        with self._count_lock:
            self.read_count += 1
            should_fail = self.fail_next_read
            self.fail_next_read = False
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if should_fail:
            raise KnowledgeValidationError("simulated projection rebuild failure")
        return super().read(system_id, scan_id)


class FakeOperationProvider:
    """记录Facade与Job派发次数且不访问任何网络或QA。"""

    def __init__(self):
        """初始化线程安全的调用计数。"""

        self.facade_calls = 0
        self.job_calls = 0
        self.external_dsf_calls = 0
        self.mq_calls = 0
        self.database_calls = 0
        self.facade_arguments: list[dict[str, Any]] = []
        self.job_failure: OperationProviderFailure | None = None
        self._lock = threading.Lock()

    def execute_facade(self, capability: OperationCapability, request: OperationExecutionRequest) -> Any:
        """返回同时包含业务字段和凭据字段的假Facade结果。

        Args:
            capability: 已索引Facade操作。
            request: 通过必填字段校验的QA请求。

        Returns:
            不访问QA的结构化假结果。

        Side Effects:
            只增加一次内存调用计数。
        """

        with self._lock:
            self.facade_calls += 1
            # 保存隔离测试参数的副本，用于证明执行层没有添加或改写字段。
            self.facade_arguments.append(dict(request.arguments))
        return {
            "accepted": True,
            "token": "must-not-persist",
            "contact": {"phone": "13800000000"},
            "passengerName": "must-not-persist",
            "merchantId": "must-not-persist",
            "orderNo": "must-not-persist",
            "ht": "must-not-persist",
            "businessUrl": "https://qa-business.example/result/QA-ORDER-1",
        }

    def execute_job(self, capability: OperationCapability, request: OperationExecutionRequest) -> Any:
        """返回异步任务使用的假Job结果。

        Args:
            capability: 已索引Job操作。
            request: 通过QA门禁的Job请求。

        Returns:
            不访问QA的接受摘要。

        Side Effects:
            增加一次内存调用计数；测试指定失败时抛出结构化provider异常。

        Raises:
            OperationProviderFailure: 当前测试显式配置了Job失败。
        """

        with self._lock:
            self.job_calls += 1
        if self.job_failure is not None:
            # 失败桩复现Worker已有结构化业务输出但以非零状态结束的真实边界。
            raise self.job_failure
        return {"accepted": True}

    def execute_external_dsf(self, capability: OperationCapability, request: OperationExecutionRequest) -> Any:
        """返回外部DSF调用的完整假业务行。

        Args:
            capability: 已索引外部DSF操作。
            request: 通过Schema校验的QA请求。

        Returns:
            不访问QA的出票单查询结果。
        """

        self.external_dsf_calls += 1
        return {"orders": [{"orderNo": "QA-ORDER-1", "status": 4}]}

    def execute_mq(self, capability: OperationCapability, request: OperationExecutionRequest) -> Any:
        """返回Broker ACK形态的假MQ结果。

        Args:
            capability: 已索引消费者资源。
            request: 消息正文和可选Key。

        Returns:
            固定SEND_OK和message ID。
        """

        self.mq_calls += 1
        return {"send_status": "SEND_OK", "message_id": "MSG-1"}

    def execute_database(self, capability: OperationCapability, request: OperationExecutionRequest) -> Any:
        """返回参数化查询形态的假数据库结果。

        Args:
            capability: 已索引数据库资源。
            request: SQL、参数和允许原因。

        Returns:
            包含完整业务字段的单行结果。
        """

        self.database_calls += 1
        return {"rows": [{"refund_serial_no": "OPENTEST_DB_1", "is_delete": 1}], "row_count": 1}


class FailingFacadeProvider(FakeOperationProvider):
    """模拟DSF Worker完成协议但返回稳定provider失败。"""

    def execute_facade(self, capability: OperationCapability, request: OperationExecutionRequest) -> Any:
        """抛出带稳定错误码的假DSF失败。

        Args:
            capability: 已索引Facade操作。
            request: 已通过QA和Schema校验的请求。

        Returns:
            此测试替身不返回结果。

        Raises:
            OperationProviderFailure: 始终模拟QA路由失败。
        """

        # 先记录一次实际派发，证明失败状态传播没有触发自动重试。
        super().execute_facade(capability, request)
        raise OperationProviderFailure("DSF_ROUTING_FAILED", "QA DSF服务发现失败。")


def _registered_workspace(tmp_path: Path) -> tuple[GitKnowledgeStore, Path]:
    """创建一个已注册但不含Fixture的隔离知识工作区。

    Args:
        tmp_path: pytest隔离目录。

    Returns:
        Git知识存储与源码根。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.initialize()
    store.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="SaaS退票核心", source_path=str(source_root))
    )
    return store, source_root


def _local_provider_with_qa_profile(
    store: GitKnowledgeStore, artifacts: SourceScanArtifactStore,
    dsf_operations: Any, include_job: bool = False,
) -> LocalQaOperationProvider:
    """为本地Provider测试建立并绑定真实逻辑QA到实际test的项目配置。

    Args:
        store: 测试项目注册表，供正式运行绑定逻辑验证项目归属。
        artifacts: 固定扫描存储。
        dsf_operations: 仅替代远端DSF执行的测试服务。
        include_job: 当前测试是否需要Job的网关和Token。
    Returns:
        已完成一次Profile解析的本地Provider，不启动Worker或调用远端。
    """

    system = store.get_system(SYSTEM_ID)
    filters = Path(system.source_path) / "conf/filter"
    filters.mkdir(parents=True, exist_ok=True)
    (filters / "application.test").write_text(
        "dsf.service.config.registryhost=test-registry.invalid\n"
        "dsf.service.config.name=refund-qa-client\n"
        "dsf.service.config.env=qa\ndsf.service.config.targetenv=test\n",
        encoding="utf-8",
    )
    environment_root = store.root / ".opentest/environments"
    LocalSystemSettingsStore(environment_root).write(
        SYSTEM_ID, "test-job-token" if include_job else "",
        qa_gateway_prefix="https://qa-gateway.invalid/gateway/refund/v2",
        resource_config_environment="test",
    )
    # 只隔离外部调用，正式的环境读取与一次运行绑定必须由产品代码执行。
    dsf_operations.store = store
    provider = LocalQaOperationProvider(dsf_operations, artifacts, LocalEnvironmentLoader(environment_root))
    return provider.for_execution([SYSTEM_ID], "qa", job_system_ids=[SYSTEM_ID] if include_job else [])


def _manifest(source_root: Path, scan_id: str = "scan-codex-native-1") -> ScanManifest:
    """构造包含可写退票Facade、Job和一个不可绑定Facade的扫描。

    Args:
        source_root: 注册系统源码根。
        scan_id: 测试使用的不可变扫描ID。

    Returns:
        不含Fixture或真实业务请求的严格Manifest。
    """

    facade_ref = SourceReference(
        path="app/facade/RefundFacade.java",
        symbol="com.example.refund.RefundFacade#createOrder",
        line=20,
    )
    job_ref = SourceReference(
        path="app/job/RefundRetryJob.java",
        symbol="com.example.refund.RefundRetryJob#execute",
        line=15,
    )
    # 固定扫描同时保存Job代码与旧默认URL；运行测试可验证新Profile只改变部署前缀。
    return ScanManifest(
        scan_id=scan_id,
        system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path=str(source_root), dirty=True, dirty_digest=scan_id),
        entries=[
            EntryPoint(
                entry_id=FACADE_OPERATION_ID,
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.FACADE,
                display_name="RefundFacade#createOrder",
                source_id=facade_ref.symbol,
                source_path=str(source_root / facade_ref.path),
                metadata={
                    "request_template": {"refundDetailApiDTO": {}, "orderChannelSource": ""},
                    "required_fields": ["refundDetailApiDTO", "orderChannelSource"],
                },
            ),
            EntryPoint(
                entry_id=JOB_OPERATION_ID,
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.JOB,
                display_name="RefundRetryJob#execute",
                source_id=job_ref.symbol,
                source_path=str(source_root / job_ref.path),
                tool_id="job.refund_retry.execute",
                metadata={"job_code": "refund_retry"},
            ),
            EntryPoint(
                entry_id="facade:com.example.refund.UnboundFacade#unknownWrite",
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.FACADE,
                display_name="UnboundFacade#unknownWrite",
                source_id="com.example.refund.UnboundFacade#unknownWrite",
                source_path=str(source_root / "app/facade/UnboundFacade.java"),
            ),
        ],
        tools=[
            ToolDefinition(
                tool_id="job.refund_retry.execute",
                system_id=SYSTEM_ID,
                display_name="退款重试Job",
                script_path=str(source_root / "generated/refund-retry.sh"),
                source_id=job_ref.symbol,
                metadata={"tool_type": "job_http_trigger", "status": "ready",
                          "default_url": "https://scan-qa.invalid/gateway/refund/job/refund_retry"},
            )
        ],
        dsf_profile=DsfClientProfile(
            system_id=SYSTEM_ID,
            routing_environment="qa",
            target_environment="test",
            status=DsfProfileStatus.CONFIRMED,
        ),
        dsf_operations=[
            DsfOperationDefinition(
                operation_id=f"dsf:{SYSTEM_ID}:refund:createOrder",
                provider_system_id=SYSTEM_ID,
                gs_name="refund-core",
                service_name="RefundFacade",
                version="1.0.0",
                action="createOrder",
                request_type="RefundCreateRequest",
                response_type="RefundCreateResponse",
                mutability=DsfOperationMutability.WRITE,
                source_refs=[facade_ref],
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            schema_version=4,
            analyzer="test-semantic-analyzer",
            analyzer_version="operation-evidence-test",
            system_id=SYSTEM_ID,
            methods=[
                SemanticMethodDefinition(
                    symbol_id="com.example.refund.RefundFacade#createOrder(com.example.refund.RefundCreateRequest)",
                    qualified_class_name="com.example.refund.RefundFacade",
                    method_name="createOrder",
                    javadoc_summary="创建退票单",
                    parameter_names=["request"],
                    parameter_types=["RefundCreateRequest"],
                    parameter_qualified_types=["com.example.refund.RefundCreateRequest"],
                    return_type="RefundCreateResponse",
                    return_qualified_type="com.example.refund.RefundCreateResponse",
                    source_ref=facade_ref,
                )
            ],
            types=[
                SemanticTypeDefinition(
                    symbol_id="com.example.refund.RefundCreateRequest",
                    qualified_class_name="com.example.refund.RefundCreateRequest",
                    simple_name="RefundCreateRequest",
                    fields=[
                        SemanticFieldDefinition(
                            field_name="refundDetailApiDTO",
                            declared_type="RefundDetailApiDTO",
                            javadoc_summary="退票业务明细",
                            annotations=["NotNull"],
                            runtime_required=True,
                            runtime_required_evidence=["NotNull"],
                            source_ref=facade_ref,
                        ),
                        SemanticFieldDefinition(
                            field_name="orderChannelSource",
                            declared_type="String",
                            javadoc_summary="订单渠道来源",
                            annotations=["NotBlank"],
                            runtime_required=True,
                            runtime_required_evidence=["NotBlank"],
                            source_ref=facade_ref,
                        ),
                    ],
                    source_ref=facade_ref,
                ),
                SemanticTypeDefinition(
                    symbol_id="com.example.refund.RefundCreateResponse",
                    qualified_class_name="com.example.refund.RefundCreateResponse",
                    simple_name="RefundCreateResponse",
                    fields=[],
                    source_ref=facade_ref,
                ),
            ],
        ),
        tool_root=str(source_root / "generated"),
    )


def _query_list_manifest(source_root: Path) -> ScanManifest:
    """构造两个等价只读退票查询入口及证据型分页字段。

    Args:
        source_root: 隔离测试源码根。

    Returns:
        带旧scriptgen必填标记和v4真实运行时证据的Manifest。
    """

    entries: list[EntryPoint] = []
    operations: list[DsfOperationDefinition] = []
    methods: list[SemanticMethodDefinition] = []
    for facade_name in ("RefundFacade", "RefundDistributionFacade"):
        source_id = f"com.example.refund.{facade_name}#queryList"
        source_ref = SourceReference(
            path=f"app/facade/{facade_name}.java",
            symbol=source_id,
            line=20,
        )
        entries.append(
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id=SYSTEM_ID,
                kind=KnowledgeNodeKind.FACADE,
                display_name=f"{facade_name}#queryList",
                source_id=source_id,
                source_path=str(source_root / source_ref.path),
                metadata={
                    "request_template": {
                        "serialVersionUID": 0,
                        "page": 0,
                        "pageSize": 0,
                        "platFormId": "",
                        "ticketNo": "",
                    },
                    # 该旧字段故意保留错误来源，证明v2不会把scriptgen文档标记升级成运行时必填。
                    "required_fields": ["page", "pageSize", "platFormId"],
                },
            )
        )
        operations.append(
            DsfOperationDefinition(
                operation_id=f"dsf:{SYSTEM_ID}:{facade_name}:queryList",
                provider_system_id=SYSTEM_ID,
                gs_name="refund-core",
                service_name=facade_name,
                version="1.0.0",
                action="queryList",
                request_type="RefundOrderQueryRequest",
                response_type="RefundOrderListResponse",
                mutability=DsfOperationMutability.READ_ONLY,
                source_refs=[source_ref],
            )
        )
        methods.append(
            SemanticMethodDefinition(
                symbol_id=f"{source_id}(com.example.refund.RefundOrderQueryRequest)",
                qualified_class_name=f"com.example.refund.{facade_name}",
                method_name="queryList",
                javadoc_summary="按查询条件返回退票单列表",
                parameter_names=["request"],
                parameter_types=["RefundOrderQueryRequest"],
                parameter_qualified_types=["com.example.refund.RefundOrderQueryRequest"],
                return_type="RefundOrderListResponse",
                return_qualified_type="com.example.refund.RefundOrderListResponse",
                source_ref=source_ref,
            )
        )
    request_ref = SourceReference(path="app/facade/RefundOrderQueryRequest.java", symbol="RefundOrderQueryRequest", line=10)
    response_ref = SourceReference(path="app/facade/RefundOrderListResponse.java", symbol="RefundOrderListResponse", line=10)
    base = _manifest(source_root, "scan-query-list-evidence")
    return base.model_copy(
        update={
            "entries": entries,
            "tools": [],
            "dsf_operations": operations,
            "semantic_analysis": SemanticAnalysisResult(
                schema_version=4,
                analyzer="test-semantic-analyzer",
                analyzer_version="operation-evidence-test",
                system_id=SYSTEM_ID,
                methods=methods,
                types=[
                    SemanticTypeDefinition(
                        symbol_id="com.example.refund.RefundOrderQueryRequest",
                        qualified_class_name="com.example.refund.RefundOrderQueryRequest",
                        simple_name="RefundOrderQueryRequest",
                        fields=[
                            SemanticFieldDefinition(
                                field_name="page",
                                declared_type="int",
                                javadoc_summary="页码",
                                documentation_required=True,
                                has_declared_initializer=True,
                                declared_initializer=1,
                                initializer_expression="1",
                                source_ref=request_ref,
                            ),
                            SemanticFieldDefinition(
                                field_name="pageSize",
                                declared_type="int",
                                javadoc_summary="每页条数",
                                documentation_required=True,
                                has_declared_initializer=True,
                                declared_initializer=20,
                                initializer_expression="20",
                                source_ref=request_ref,
                            ),
                            SemanticFieldDefinition(
                                field_name="platFormId",
                                declared_type="String",
                                javadoc_summary="平台过滤条件",
                                documentation_required=True,
                                source_ref=request_ref,
                            ),
                            SemanticFieldDefinition(
                                field_name="ticketNo",
                                declared_type="String",
                                javadoc_summary="票号查询条件",
                                source_ref=request_ref,
                            ),
                        ],
                        source_ref=request_ref,
                    ),
                    SemanticTypeDefinition(
                        symbol_id="com.example.refund.RefundOrderListResponse",
                        qualified_class_name="com.example.refund.RefundOrderListResponse",
                        simple_name="RefundOrderListResponse",
                        fields=[
                            SemanticFieldDefinition(
                                field_name="refundSerialNo",
                                declared_type="String",
                                javadoc_summary="退票单号",
                                source_ref=response_ref,
                            )
                        ],
                        source_ref=response_ref,
                    ),
                ],
            ),
        }
    )


def _publish_manifest(artifacts: SourceScanArtifactStore, manifest: ScanManifest) -> None:
    """写入并发布一个测试Manifest。

    Args:
        artifacts: 隔离扫描产物存储。
        manifest: 要成为latest的完整扫描。

    Side Effects:
        写Manifest、latest指针并递增工作区revision。
    """

    artifacts.write_manifest(manifest)
    artifacts.publish_latest(manifest.system_id, manifest.scan_id)


def _operation_service(
    store: GitKnowledgeStore,
    artifacts: SourceScanArtifactStore,
    provider: FakeOperationProvider,
) -> tuple[OperationExecutionService, LocalTaskManager]:
    """组装使用假provider的统一操作服务。

    Args:
        store: 已注册知识工作区。
        artifacts: 已发布固定Manifest的扫描存储。
        provider: 不访问QA的调用计数provider。

    Returns:
        操作服务与需要由测试关闭的任务管理器。
    """

    catalog = OperationCapabilityCatalog(store, artifacts)
    index = SqliteKnowledgeIndex(store.root / ".opentest/index.sqlite")
    index.operation_capability_provider = catalog.derive
    tasks = LocalTaskManager(store.root / ".opentest/tasks", max_workers=1)
    service = OperationExecutionService(
        catalog,
        index,
        OperationExecutionStore(store.root / ".opentest"),
        tasks,
        provider,
    )
    return service, tasks


def _load_script_module(path: Path, module_name: str) -> Any:
    """加载一个插件脚本供纯函数契约测试使用。

    Args:
        path: Python脚本绝对路径。
        module_name: 测试隔离模块名。

    Returns:
        已执行但未启动main循环的模块。
    """

    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_prewarm_singleflight_revision_and_bounded_eviction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """预热后不得重复解析Manifest，并发、revision和LRU边界必须稳定。"""

    monkeypatch.setenv("OPENTEST_WORKSPACE_CACHE_MAX_ENTRIES", "2")
    store, source_root = _registered_workspace(tmp_path)
    artifacts = CountingArtifactStore(store.root, delay_seconds=0.03)
    first_manifest = _manifest(source_root, "scan-codex-native-1")
    _publish_manifest(artifacts, first_manifest)
    service = ScanCatalogService(store, artifacts)

    with ThreadPoolExecutor(max_workers=8) as executor:
        catalogs = list(executor.map(lambda _: service.build_catalog(SYSTEM_ID), range(8)))
    assert artifacts.read_count == 1
    assert len({id(catalog) for catalog in catalogs}) == 1
    assert service.prewarm_latest() == {"warmed": 1, "skipped": 0}
    assert artifacts.read_count == 1

    # 知识写入递增跨进程revision，下一次访问只重建一次且不返回旧代次。
    store.write_context(store.read_context(SYSTEM_ID))
    rebuilt = service.build_catalog(SYSTEM_ID)
    assert artifacts.read_count == 2
    assert rebuilt.scan_id == first_manifest.scan_id

    second_manifest = _manifest(source_root, "scan-codex-native-2")
    third_manifest = _manifest(source_root, "scan-codex-native-3")
    artifacts.write_manifest(second_manifest)
    artifacts.write_manifest(third_manifest)
    first_reference = weakref.ref(rebuilt)
    second_catalog = service.build_catalog(SYSTEM_ID, second_manifest.scan_id)
    second_reference = weakref.ref(second_catalog)
    service.build_catalog(SYSTEM_ID, third_manifest.scan_id)
    del rebuilt
    del second_catalog
    catalogs.clear()
    gc.collect()
    stats = service.cache_stats()
    assert stats["entries"] == 2
    assert stats["bytes"] <= stats["max_bytes"]
    assert stats["evictions"] >= 1
    assert first_reference() is not None
    assert second_reference() is None


def test_catalog_keeps_same_source_rescan_knowledge_and_stales_changed_source(tmp_path: Path) -> None:
    """重复扫描同一源码基线不应误伤知识，真实源码变化仍必须标记过期。

    Args:
        tmp_path: pytest隔离的注册系统、扫描历史和知识批次。

    Returns:
        None；同基线新scan显示GENERATED，dirty摘要变化后显示STALE时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    original_manifest = _manifest(source_root, "scan-compatible-original")
    _publish_manifest(artifacts, original_manifest)
    store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-compatible-rescan",
            system_id=SYSTEM_ID,
            scan_id=original_manifest.scan_id,
            target_ids=[FACADE_OPERATION_ID],
            status="PUBLISHED",
            context_digest=knowledge_context_digest(store.read_context(SYSTEM_ID)),
            outcomes=[
                KnowledgeTargetGenerationOutcome(
                    target_id=FACADE_OPERATION_ID,
                    status="AGENT_ENRICHED",
                    agent="codex",
                )
            ],
        )
    )

    # 新扫描ID沿用完全相同源码基线，只代表重新分析，不应使已完成目标立即过期。
    compatible_manifest = original_manifest.model_copy(update={"scan_id": "scan-compatible-latest"})
    _publish_manifest(artifacts, compatible_manifest)
    compatible_catalog = ScanCatalogService(store, artifacts).build_catalog(SYSTEM_ID)
    compatible_target = next(target for target in compatible_catalog.targets if target.target_id == FACADE_OPERATION_ID)
    assert compatible_target.knowledge_status == KnowledgeTargetStatus.GENERATED

    # 人工或审计流程显式撤销节点可信状态时，同基线规则不能把它恢复为已生成。
    store.write_node(
        KnowledgeNode(
            node_id="entry:com.example.refund.RefundFacade#createOrder",
            system_id=SYSTEM_ID,
            kind=KnowledgeNodeKind.FACADE,
            title="RefundFacade#createOrder",
            aliases=[FACADE_OPERATION_ID, "com.example.refund.RefundFacade#createOrder"],
            status=KnowledgeStatus.STALE,
            metadata={"scan_id": original_manifest.scan_id},
        ),
        "显式过期的测试知识。",
    )
    explicitly_stale_catalog = ScanCatalogService(store, artifacts).build_catalog(SYSTEM_ID)
    explicitly_stale_target = next(
        target for target in explicitly_stale_catalog.targets if target.target_id == FACADE_OPERATION_ID
    )
    assert explicitly_stale_target.knowledge_status == KnowledgeTargetStatus.STALE

    # dirty摘要变化代表源码内容真实变化，即使入口稳定也必须要求重新生成知识。
    changed_baseline = compatible_manifest.baseline.model_copy(update={"dirty_digest": "source-changed"})
    changed_manifest = compatible_manifest.model_copy(
        update={"scan_id": "scan-source-changed", "baseline": changed_baseline}
    )
    _publish_manifest(artifacts, changed_manifest)
    changed_catalog = ScanCatalogService(store, artifacts).build_catalog(SYSTEM_ID)
    changed_target = next(target for target in changed_catalog.targets if target.target_id == FACADE_OPERATION_ID)
    assert changed_target.knowledge_status == KnowledgeTargetStatus.STALE


def test_catalog_failure_and_oversize_fallback_do_not_leak_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败重建和单项超限不得安装半成品或留下无界缓存对象。"""

    monkeypatch.setenv("OPENTEST_WORKSPACE_CACHE_MAX_BYTES", "1")
    store, source_root = _registered_workspace(tmp_path)
    artifacts = CountingArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    service = ScanCatalogService(store, artifacts)
    artifacts.fail_next_read = True

    with pytest.raises(KnowledgeValidationError, match="simulated projection"):
        service.build_catalog(SYSTEM_ID)
    assert service.cache_stats()["entries"] == 0
    assert service.build_catalog(SYSTEM_ID).system_id == SYSTEM_ID
    assert service.cache_stats()["entries"] == 0
    service.build_catalog(SYSTEM_ID)
    assert artifacts.read_count == 3


def test_catalog_failed_singleflight_keeps_one_recovery_builder(tmp_path: Path) -> None:
    """首个并发构建失败后，全部等待者只能共享一次恢复重建。"""

    store, source_root = _registered_workspace(tmp_path)
    artifacts = CountingArtifactStore(store.root, delay_seconds=0.03)
    _publish_manifest(artifacts, _manifest(source_root))
    service = ScanCatalogService(store, artifacts)
    artifacts.fail_next_read = True

    def build_or_error(_: int) -> str:
        """执行一次并发目录读取并把预期失败转换为测试状态。"""

        try:
            return service.build_catalog(SYSTEM_ID).scan_id
        except KnowledgeValidationError:
            return "failed"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(build_or_error, range(8)))

    assert outcomes.count("failed") == 1
    assert artifacts.read_count == 2
    assert service.cache_stats()["entries"] == 1


def test_target_detail_reuses_projected_semantic_evidence_without_manifest_read(tmp_path: Path) -> None:
    """详情读取应复用投影中的语义证据而不重新读取完整Manifest。"""

    store, source_root = _registered_workspace(tmp_path)
    artifacts = CountingArtifactStore(store.root)
    manifest = _manifest(source_root)
    _publish_manifest(artifacts, manifest)
    catalog = ScanCatalogService(store, artifacts).build_catalog(SYSTEM_ID)
    discovery = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))

    detail = discovery.target_detail(
        SYSTEM_ID,
        FACADE_OPERATION_ID,
        catalog,
        include_questions=False,
        include_context=False,
    )
    assert detail.target.target_id == FACADE_OPERATION_ID
    assert artifacts.read_count == 1


def test_operation_search_required_fields_idempotency_and_redaction(tmp_path: Path) -> None:
    """注解未证明入口校验时不阻断缺省字段，同时保留结构门禁、幂等与凭据脱敏。

    Args:
        tmp_path: 隔离系统注册、扫描与Operation运行目录。
    Returns:
        None；未知必填不冒充约束，重复请求仍只派发一次时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    provider = FakeOperationProvider()
    service, tasks = _operation_service(store, artifacts, provider)
    try:
        matches = service.search(SYSTEM_ID, "帮我生成退票自愿退票单")
        assert matches[0].operation_id == FACADE_OPERATION_ID
        assert matches[0].mutability.value == "WRITE"

        missing_request = OperationExecutionRequest(
            operation_id=FACADE_OPERATION_ID,
            arguments={"orderChannelSource": "QA_TEST"},
            request_id="request-missing-fields-001",
        )
        # 扫描的runtime_required仅有DTO注解证据，不能据此假定当前Facade执行了校验。
        unknown_requirement = service.execute(SYSTEM_ID, missing_request)
        assert unknown_requirement.status == OperationExecutionStatus.COMPLETED
        assert matches[0].required_fields == []
        assert provider.facade_calls == 1

        invalid_schema_request = OperationExecutionRequest(
            operation_id=FACADE_OPERATION_ID,
            arguments={
                "refundDetailApiDTO": {},
                "orderChannelSource": 42,
                "arbitraryProvider": "forbidden",
            },
            request_id="request-invalid-schema-001",
        )
        with pytest.raises(KnowledgeValidationError, match="unsupported fields|must be string"):
            service.execute(SYSTEM_ID, invalid_schema_request)
        assert provider.facade_calls == 1

        request = OperationExecutionRequest(
            operation_id=FACADE_OPERATION_ID,
            arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
            request_id="request-create-refund-001",
        )
        first = service.execute(SYSTEM_ID, request)
        duplicate = service.execute(SYSTEM_ID, request)
        assert first.execution_id == duplicate.execution_id
        assert first.status == OperationExecutionStatus.COMPLETED
        assert provider.facade_calls == 2
        assert first.result["token"] == "<redacted>"
        assert first.result["contact"]["phone"] == "13800000000"
        assert first.result["passengerName"] == "must-not-persist"
        assert first.result["merchantId"] == "must-not-persist"
        assert first.result["orderNo"] == "must-not-persist"
        assert first.result["ht"] == "must-not-persist"
        assert first.result["businessUrl"] == "https://qa-business.example/result/QA-ORDER-1"
        assert current_log_context().trace_id == ""
        assert current_log_context().filter1 == ""
        assert current_log_context().filter2 == ""

        conflicting = request.model_copy(update={"arguments": {"refundDetailApiDTO": {}, "orderChannelSource": "OTHER"}})
        with pytest.raises(ScopeViolationError, match="reused"):
            service.execute(SYSTEM_ID, conflicting)
        assert provider.facade_calls == 2
    finally:
        tasks.close()


def test_unified_catalog_executes_external_dsf_mq_and_database_operations(tmp_path: Path) -> None:
    """统一目录对已接入的外部DSF和本项目MQ/数据库操作保存完整业务结果。

    Args:
        tmp_path: pytest提供的注册项目和固定扫描隔离目录。
    Returns:
        None；目标接入边界和各协议派发结果均符合契约时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    base = _manifest(source_root, "scan-unified-qa-operations")
    external_ref = SourceReference(
        path="app/integration/src/main/resources/external.xml",
        symbol="com.example.booking.TradeFacade#queryList",
        line=20,
    )
    manifest = base.model_copy(
        update={
            "dsf_profile": base.dsf_profile.model_copy(update={"client_name": "refund-qa-client"}),
            "dsf_operations": [
                *base.dsf_operations,
                DsfOperationDefinition(
                    operation_id="dsf:booking.core:trade:queryList",
                    provider_system_id="booking.core",
                    gs_name="dsf.booking.core",
                    service_name="trade",
                    version="latest",
                    action="queryList",
                    mutability=DsfOperationMutability.READ_ONLY,
                    source_refs=[external_ref],
                ),
            ],
            "resources": [
                DiscoveredResource(
                    resource_id=f"resource:{SYSTEM_ID}:mq:consumer:refundconsumer",
                    system_id=SYSTEM_ID,
                    kind=ResourceKind.MQ,
                    role=ResourceRole.CONSUMER,
                    logical_name="refundConsumer",
                    listener_ref="refundListener",
                    nameserver_config_key="mq.nameSrvAddress",
                    topic_config_key="mq.refund.topic",
                    source_refs=[external_ref],
                ),
                DiscoveredResource(
                    resource_id=f"resource:{SYSTEM_ID}:mysql:database:refunddatasource",
                    system_id=SYSTEM_ID,
                    kind=ResourceKind.MYSQL,
                    role=ResourceRole.DATABASE,
                    logical_name="refundDatasource",
                    database_config_key="uniform.dbName.refund",
                    database_project_config_key="uniform.skyCode",
                    database_environment_config_key="uniform.env",
                    source_refs=[external_ref],
                ),
            ],
        }
    )
    _publish_manifest(artifacts, manifest)
    provider = FakeOperationProvider()
    service, tasks = _operation_service(store, artifacts, provider)
    try:
        capabilities = {item.kind: item for item in service.search(SYSTEM_ID, "", 100)}
        assert {OperationKind.EXTERNAL_DSF, OperationKind.MQ, OperationKind.DATABASE} <= set(capabilities)

        # 旧External DSF引用不能替代远端项目接入，缺项目时必须先报告明确缺口。
        with pytest.raises(KnowledgeNotFoundError, match="booking.core"):
            service.execute(SYSTEM_ID, OperationExecutionRequest(
                operation_id=capabilities[OperationKind.EXTERNAL_DSF].operation_id,
                arguments={"status": 4}, request_id="request-external-unregistered",
            ))
        booking_source = tmp_path / "booking-source"
        booking_source.mkdir()
        store.register_system(SystemDefinition(system_id="booking.core", name="Booking", source_path=str(booking_source)))
        external = service.execute(
            SYSTEM_ID,
            OperationExecutionRequest(
                operation_id=capabilities[OperationKind.EXTERNAL_DSF].operation_id,
                arguments={"status": 4},
                request_id="request-external-dsf-001",
            ),
        )
        mq = service.execute(
            SYSTEM_ID,
            OperationExecutionRequest(
                operation_id=capabilities[OperationKind.MQ].operation_id,
                arguments={"message": {"refundSerialNo": "QA-1"}, "keys": "QA-1"},
                request_id="request-mq-send-0001",
            ),
        )
        database = service.execute(
            SYSTEM_ID,
            OperationExecutionRequest(
                operation_id=capabilities[OperationKind.DATABASE].operation_id,
                arguments={
                    "statement": "SELECT refund_serial_no, is_delete FROM saas_refund_order_psi WHERE refund_serial_no = ?",
                    "parameters": ["OPENTEST_DB_1"],
                    "purpose": "user_requested",
                },
                request_id="request-database-read-001",
            ),
        )

        assert external.result["orders"][0]["orderNo"] == "QA-ORDER-1"
        assert mq.result["send_status"] == "SEND_OK" and mq.result["message_id"] == "MSG-1"
        assert database.result["rows"][0]["refund_serial_no"] == "OPENTEST_DB_1"
        assert (provider.external_dsf_calls, provider.mq_calls, provider.database_calls) == (1, 1, 1)
    finally:
        tasks.close()


def test_facade_provider_failure_is_terminal_and_preserves_safe_error_code(tmp_path: Path) -> None:
    """DSF内层failed必须成为外层failed且相同请求不得再次派发。

    Args:
        tmp_path: Pytest隔离知识、索引和执行记录根。

    Side Effects:
        仅写入本地脱敏失败记录，不访问QA。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    provider = FailingFacadeProvider()
    service, tasks = _operation_service(store, artifacts, provider)
    request = OperationExecutionRequest(
        operation_id=FACADE_OPERATION_ID,
        arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
        request_id="request-failed-refund-facade-001",
    )
    try:
        failed = service.execute(SYSTEM_ID, request)
        duplicate = service.execute(SYSTEM_ID, request)

        assert failed.status == OperationExecutionStatus.FAILED
        assert failed.error_code == "DSF_ROUTING_FAILED"
        assert failed.message == "QA DSF服务发现失败。"
        assert duplicate.execution_id == failed.execution_id
        assert provider.facade_calls == 1
    finally:
        tasks.close()


def test_query_list_semantic_contract_does_not_promote_defaults_or_documentation(tmp_path: Path) -> None:
    """票号查询应自动得到等价只读候选，契约和执行均不得注入分页或平台字段。"""

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _query_list_manifest(source_root))
    provider = FakeOperationProvider()
    service, tasks = _operation_service(store, artifacts, provider)
    try:
        matches = service.search(SYSTEM_ID, "查询票号为SYNTHETIC-TICKET-001的退票单号有哪些")
        assert len(matches) == 2
        selected = matches[0]
        assert selected.mutability.value == "READ_ONLY"
        assert selected.required_fields == []
        assert "required" not in selected.input_schema
        assert "safe_defaults" not in selected.model_dump(mode="json")
        evidence = {field.field_name: field for field in selected.input_fields}
        assert evidence["page"].declared_initializer == 1
        assert evidence["pageSize"].declared_initializer == 20
        assert evidence["platFormId"].documentation_required is True
        assert evidence["platFormId"].runtime_required is False
        assert any(field.description == "退票单号" for field in selected.output_fields)

        nested_schema = {
            "type": "object",
            "properties": {
                "optionalFilter": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        }
        service.catalog._mark_required_path(nested_schema, ["optionalFilter", "code"])
        assert "required" not in nested_schema
        assert nested_schema["properties"]["optionalFilter"]["required"] == ["code"]

        request = OperationExecutionRequest(
            operation_id=selected.operation_id,
            arguments={"ticketNo": "SYNTHETIC-TICKET-001"},
            request_id="request-query-refund-ticket-001",
        )
        completed = service.execute(SYSTEM_ID, request)
        duplicate = service.execute(SYSTEM_ID, request)

        assert completed.execution_id == duplicate.execution_id
        assert provider.facade_calls == 1
        assert provider.facade_arguments == [{"ticketNo": "SYNTHETIC-TICKET-001"}]
    finally:
        tasks.close()


def test_pre_v4_manifest_derives_v2_evidence_without_rewriting_history(tmp_path: Path) -> None:
    """旧Manifest应按原基线派生v2证据，且历史JSON保持逐字节不变。"""

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    current = _query_list_manifest(source_root)
    assert current.semantic_analysis is not None
    legacy_analysis = current.semantic_analysis.model_copy(
        update={"schema_version": 3, "methods": [], "types": []}
    )
    legacy_manifest = current.model_copy(
        update={"scan_id": "scan-query-list-legacy", "semantic_analysis": legacy_analysis}
    )
    manifest_path = artifacts.write_manifest(legacy_manifest)
    artifacts.publish_latest(SYSTEM_ID, legacy_manifest.scan_id)
    store.update_source_baseline(SYSTEM_ID, legacy_manifest.baseline)
    original_bytes = manifest_path.read_bytes()
    analyzer = MagicMock()
    analyzer.analyze.return_value = current.semantic_analysis
    catalog = OperationCapabilityCatalog(store, artifacts, semantic_analyzer=analyzer)

    # 重建只安装内存/SQLite派生结果，不回写旧扫描或触发知识生成任务。
    capabilities = [item for item in catalog.derive(SYSTEM_ID) if item.operation_id.endswith("#queryList")]
    assert len(capabilities) == 2
    assert all(item.contract_version == "operation-capability/v2" for item in capabilities)
    assert all(item.required_fields == [] for item in capabilities)
    assert any(field.field_name == "page" and field.declared_initializer == 1 for field in capabilities[0].input_fields)
    assert manifest_path.read_bytes() == original_bytes
    analyzer.analyze.assert_called_once_with(SYSTEM_ID, legacy_manifest.baseline.source_path)


def test_local_facade_provider_executes_the_capability_source_scan(tmp_path: Path) -> None:
    """Facade派发保持固定源码契约，同时使用运行开始绑定的项目Profile。

    Args:
        tmp_path: pytest固定扫描和项目Profile的隔离目录。
    Returns:
        None；派发使用原scan及该项目实际test路由时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    source_scan_id = "scan-codex-native-fixed-provider"
    _publish_manifest(artifacts, _manifest(source_root, source_scan_id))
    capability = OperationCapabilityCatalog(store, artifacts).derive(SYSTEM_ID)[0]
    assert capability.required_local_bindings == []
    dsf_operations = MagicMock()
    dsf_operations.execute_indexed.return_value = DsfExecutionResponse(
        request_id="worker-request-1",
        operation_id=capability.provider_operation_id,
        status="success",
        output={"accepted": True},
    )
    # 使用真实本地Profile绑定，测试仅替换DSF远端调用而不跳过环境解析。
    provider = _local_provider_with_qa_profile(store, artifacts, dsf_operations)
    request = OperationExecutionRequest(
        operation_id=capability.operation_id,
        arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
        request_id="request-fixed-scan-001",
    )

    provider.execute_facade(capability, request)

    call = dsf_operations.execute_indexed.call_args
    assert call.args[0] == SYSTEM_ID
    assert call.args[1] == source_scan_id
    assert call.args[2].operation_id == capability.provider_operation_id
    assert call.kwargs["profile"].environment == "qa"
    assert call.kwargs["profile"].target_environment == "test"


def test_active_resource_provider_materializes_legacy_commit_instead_of_current_tree(
    tmp_path: Path,
) -> None:
    """旧干净Git扫描执行资源操作时必须读取记录commit而非当前工作树。

    Args:
        tmp_path: Pytest隔离的Git源码与托管快照目录。

    Returns:
        None；返回快照保留旧filter且当前工作树修改不进入执行范围时通过。

    Side Effects:
        创建一个本地Git提交并物化对应的OpenTest源码快照。
    """

    source_root = tmp_path / "legacy-git-source"
    filter_path = source_root / "conf/filter/dsf_application.properties.test"
    filter_path.parent.mkdir(parents=True)
    filter_path.write_text("uniform.env=test\nrefund.database=legacy_refund\n", encoding="utf-8")
    subprocess.run(["git", "init", str(source_root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source_root), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "-c",
            "user.name=OpenTest",
            "-c",
            "user.email=opentest@example.invalid",
            "commit",
            "-m",
            "legacy scan baseline",
        ],
        check=True,
        capture_output=True,
    )
    baseline = GitSourceRepository().capture_revision(source_root)
    filter_path.write_text("uniform.env=uat\nrefund.database=current_refund\n", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.initialize()
    store.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="SaaS退票核心", source_path=str(source_root))
    )
    artifacts = SourceScanArtifactStore(store.root)
    provider = LocalQaOperationProvider(MagicMock(), artifacts, MagicMock())
    manifest = _manifest(source_root).model_copy(update={"baseline": baseline})

    snapshot_root = provider._active_resource_source_root(
        SYSTEM_ID,
        str(source_root),
        manifest,
    )

    snapshot_filter = snapshot_root / "conf/filter/dsf_application.properties.test"
    assert snapshot_filter.read_text(encoding="utf-8") == (
        "uniform.env=test\nrefund.database=legacy_refund\n"
    )
    assert filter_path.read_text(encoding="utf-8").startswith("uniform.env=uat")


def test_active_resource_provider_rejects_unowned_declared_snapshot(tmp_path: Path) -> None:
    """Manifest声明非本系统commit目录时不得作为资源配置快照使用。

    Args:
        tmp_path: Pytest隔离的注册源码和伪造快照目录。

    Returns:
        None；快照在Worker启动前被归属校验拒绝时通过。

    Side Effects:
        创建本地测试目录，不执行QA操作。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    provider = LocalQaOperationProvider(MagicMock(), artifacts, MagicMock())
    baseline = SourceBaseline(
        source_path=str(source_root),
        commit="a" * 40,
        dirty=False,
        snapshot_path=str(tmp_path / "unowned-snapshot"),
    )
    manifest = _manifest(source_root).model_copy(update={"baseline": baseline})

    with pytest.raises(KnowledgeValidationError, match="does not belong"):
        provider._active_resource_source_root(SYSTEM_ID, str(source_root), manifest)


def test_local_facade_provider_raises_stable_failure_for_failed_worker_response(tmp_path: Path) -> None:
    """Worker文件协议成功但DSF结果失败时provider必须抛出结构化异常。

    Args:
        tmp_path: Pytest隔离知识和扫描根。
    Returns:
        None；真实Profile绑定后仍保留Worker业务失败时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    capability = OperationCapabilityCatalog(store, artifacts).derive(SYSTEM_ID)[0]
    dsf_operations = MagicMock()
    dsf_operations.execute_indexed.return_value = DsfExecutionResponse(
        request_id="worker-request-failed-1",
        operation_id=capability.provider_operation_id,
        status="failed",
        error_code="DSF_ROUTING_FAILED",
        message="QA DSF服务发现失败。",
    )
    # 环境解析成功后才模拟DSF失败，避免缺少绑定提前掩盖被测错误传播。
    provider = _local_provider_with_qa_profile(store, artifacts, dsf_operations)
    request = OperationExecutionRequest(
        operation_id=capability.operation_id,
        arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
        request_id="request-fixed-scan-failed-001",
    )

    with pytest.raises(OperationProviderFailure) as captured:
        provider.execute_facade(capability, request)

    assert captured.value.error_code == "DSF_ROUTING_FAILED"
    dsf_operations.execute_indexed.assert_called_once()


def test_local_job_provider_rejects_retired_http_before_configuration_or_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """历史HTTP Job能力必须在读取配置或启动执行器之前明确拒绝。

    Args:
        tmp_path: Pytest隔离知识和源码目录。
        monkeypatch: 记录扫描读取及进程派发，证明退役边界没有副作用。

    Returns:
        None；返回退役原因且没有读取配置、扫描或派发执行时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    # 旧Generation仍可保存此能力；直接调用旧Provider边界也不能重新激活HTTP。
    capability = OperationCapability(
        operation_id=JOB_OPERATION_ID,
        system_id=SYSTEM_ID,
        business_name="历史退票重试Job",
        kind=OperationKind.JOB,
        mutability=OperationMutability.JOB,
        provider_kind=OperationProviderKind.JOB_HTTP_TRIGGER,
        provider_operation_id="refund_retry",
        source_scan_id="scan-codex-native-1",
        executable=True,
    )
    scan_reader = MagicMock()
    process_factory = MagicMock()
    monkeypatch.setattr(artifacts, "read", scan_reader)
    monkeypatch.setattr(subprocess, "Popen", process_factory)
    environment = MagicMock()
    dsf_operations = MagicMock()
    provider = LocalQaOperationProvider(dsf_operations, artifacts, environment)
    request = OperationExecutionRequest(
        operation_id=JOB_OPERATION_ID,
        arguments={"reason": "manual QA verification"},
        request_id="request-job-provider-failure-001",
    )

    with pytest.raises(KnowledgeValidationError, match="HTTP Job已退役"):
        provider.execute_job(capability, request)

    scan_reader.assert_not_called()
    process_factory.assert_not_called()
    assert environment.mock_calls == []
    assert dsf_operations.mock_calls == []


def test_operation_request_reservation_repairs_without_a_second_execution_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """execution文件写入中断后，同一request_id只能修复原reservation。"""

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    capability = OperationCapabilityCatalog(store, artifacts).derive(SYSTEM_ID)[0]
    records = OperationExecutionStore(store.root / ".opentest")
    request = OperationExecutionRequest(
        operation_id=capability.operation_id,
        arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
        request_id="request-reservation-repair-001",
    )
    request_digest = "a" * 64
    original_write = records.write
    monkeypatch.setattr(records, "write", MagicMock(side_effect=OSError("simulated record failure")))

    with pytest.raises(OSError, match="record failure"):
        records.create_or_get(SYSTEM_ID, capability, request, request_digest)
    monkeypatch.setattr(records, "write", original_write)
    repaired, created = records.create_or_get(SYSTEM_ID, capability, request, request_digest)
    duplicate, duplicate_created = records.create_or_get(
        SYSTEM_ID,
        capability,
        request,
        request_digest,
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.execution_id == repaired.execution_id


def test_operation_retired_job_unknown_and_invalid_environment_never_dispatch(tmp_path: Path) -> None:
    """退役HTTP Job不进入目录，未知能力和非法环境也不能形成执行。

    Args:
        tmp_path: Pytest隔离的扫描、索引及操作记录目录。
    Returns:
        None；所有拒绝分支都没有派发Provider、创建执行记录或异步任务时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    provider = FakeOperationProvider()
    service, tasks = _operation_service(store, artifacts, provider)
    try:
        # 旧扫描仍含Job条目，但当前执行目录必须过滤掉退役HTTP入口。
        operations = service.catalog.derive(SYSTEM_ID)
        assert JOB_OPERATION_ID not in {item.operation_id for item in operations}
        with pytest.raises(KnowledgeNotFoundError):
            service.get(SYSTEM_ID, JOB_OPERATION_ID)
        unknown = service.get(SYSTEM_ID, "facade:com.example.refund.UnboundFacade#unknownWrite")
        assert unknown.executable is False
        with pytest.raises(KnowledgeValidationError, match="无法唯一绑定"):
            service.execute(
                SYSTEM_ID,
                OperationExecutionRequest(
                    operation_id=unknown.operation_id,
                    arguments={},
                    request_id="request-unknown-write-001",
                ),
            )
        with pytest.raises(KnowledgeNotFoundError):
            service.get(SYSTEM_ID, "facade:arbitrary.Provider#write")
        with pytest.raises(ValidationError):
            OperationExecutionRequest.model_validate(
                {
                    "operation_id": FACADE_OPERATION_ID,
                    "arguments": {},
                    "request_id": "request-nonqa-001",
                    "environment": "prod",
                }
            )

        request = OperationExecutionRequest(
            operation_id=JOB_OPERATION_ID,
            arguments={"reason": "manual QA verification"},
            request_id="request-refund-job-001",
        )
        # 连续重试不能使已退役身份产生幂等占位或后台任务。
        for _ in range(2):
            with pytest.raises(KnowledgeNotFoundError):
                service.execute(SYSTEM_ID, request)
        assert provider.job_calls == provider.facade_calls == 0
        assert list(service.records.root.glob("operation-execution-*.json")) == []
        assert list(tasks.task_root.glob("task-*.json")) == []
    finally:
        tasks.close()


def test_operation_facade_failure_persists_real_reason_and_structured_business_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仍受支持的Facade失败记录保留业务原因与输出，只清理凭据。

    Args:
        tmp_path: Pytest隔离的操作记录与任务目录。
        monkeypatch: 让Facade替身返回结构化业务拒绝，不访问DSF远端。

    Returns:
        None；最终FAILED记录可供Codex诊断且凭据未持久化时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    provider = FakeOperationProvider()
    failure = OperationProviderFailure(
        "DSF_BUSINESS_REJECTED",
        "refund business rejected",
        {
            "message": "refund business rejected",
            "orderNo": "QA-ORDER-1",
            "token": "local-secret",
            "businessUrl": "https://qa-business.example/refunds/QA-ORDER-1",
        },
    )
    # HTTP Job退出后，错误持久化和凭据处理的公共契约仍由受支持的DSF路径验证。
    facade_dispatch = MagicMock(side_effect=failure)
    monkeypatch.setattr(provider, "execute_facade", facade_dispatch)
    service, tasks = _operation_service(store, artifacts, provider)
    request = OperationExecutionRequest(
        operation_id=FACADE_OPERATION_ID,
        arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
        request_id="request-refund-facade-failure-001",
    )

    try:
        execution = service.execute(SYSTEM_ID, request)
        duplicate = service.execute(SYSTEM_ID, request)
        failed = service.get_execution(execution.execution_id)
        assert duplicate.execution_id == execution.execution_id
    finally:
        tasks.close()

    assert failed.status == OperationExecutionStatus.FAILED
    assert failed.error_code == "DSF_BUSINESS_REJECTED"
    assert failed.message == "refund business rejected"
    assert failed.result["message"] == "refund business rejected"
    assert failed.result["orderNo"] == "QA-ORDER-1"
    assert failed.result["token"] == "<redacted>"
    assert failed.result["businessUrl"] == "https://qa-business.example/refunds/QA-ORDER-1"
    facade_dispatch.assert_called_once()
    assert provider.job_calls == 0


def test_operation_http_api_searches_and_executes_through_loopback(tmp_path: Path) -> None:
    """四个本地API应返回统一能力并通过回环幂等执行一次假Facade。"""

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.initialize()
    application.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="SaaS退票核心", source_path=str(source_root))
    )
    # 执行契约必须来自测试隔离目录中的显式环境，不能依赖真实配置或默认猜测。
    application.save_local_settings(SYSTEM_ID, "", "")
    _publish_manifest(application.source_analysis.artifacts, _manifest(source_root))
    provider = FakeOperationProvider()
    application.operations.provider = provider

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        searched = client.get(
            f"/api/v2/systems/{SYSTEM_ID}/operations",
            params={"query": "帮我生成退票自愿退票单"},
        )
        assert searched.status_code == 200
        assert searched.json()["operations"][0]["operation_id"] == FACADE_OPERATION_ID
        fetched = client.get(
            f"/api/v2/systems/{SYSTEM_ID}/operations/{quote(FACADE_OPERATION_ID, safe='')}",
        )
        assert fetched.status_code == 200
        executed = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/operation-executions",
            json={
                "operation_id": FACADE_OPERATION_ID,
                    "arguments": {"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
                    "request_id": "request-http-refund-001",
                    "environment": "qa",
                },
        )
        repeated = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/operation-executions",
            json={
                "operation_id": FACADE_OPERATION_ID,
                    "arguments": {"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
                    "request_id": "request-http-refund-001",
                    "environment": "qa",
                },
        )
        execution_id = executed.json()["execution"]["execution_id"]
        status = client.get(f"/api/v2/operation-executions/{execution_id}")

    assert executed.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["execution"]["execution_id"] == execution_id
    assert status.status_code == 200
    assert status.json()["execution"]["status"] == "completed"
    assert provider.facade_calls == 1


def test_operation_plugin_and_generated_skill_are_explicit_and_fixed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP应暴露共享数据与原生Agent闭环，默认QA且保留明确环境，不搬运旧凭据。

    Args:
        tmp_path: Pytest隔离的应用与源码目录。
        monkeypatch: 拦截回环API，证明工具只传业务参数与默认或显式环境。
    """

    plugin_root = Path(__file__).parents[2] / "opentest-plugin-marketplace/plugins/open-test-knowledge"
    operations = _load_script_module(plugin_root / "scripts/opentest_operations_mcp.py", "operations_mcp_test")
    generator = _load_script_module(plugin_root / "scripts/sync_system_skills.py", "skill_sync_test")
    # 固定工具目录新增共享定义与任务桥接，仍禁止调用者传入凭据或任意服务绑定。
    tools = operations._tool_definitions()
    assert {tool["name"] for tool in tools} == {
        "search_operations",
        "get_operation",
        "execute_operation",
        "get_operation_execution",
        "list_systems",
        "list_environments",
        "register_system",
        "update_system",
        "start_system_scan",
        "get_task",
        "list_tasks",
        "read_task_context",
        "answer_task_question",
        "sync_system_skills",
        "list_system_source",
        "search_system_source",
        "read_system_source",
        "prepare_knowledge_target",
        "generate_interface_cases",
        "get_case_handoff",
        "list_case_source",
        "search_case_source",
        "read_case_source",
        "read_case_outer_api",
        "revise_case_draft",
        "publish_case_generation",
        "continue_case_task",
        "get_case_generation",
        "execute_case_generation",
        "get_case_execution",
        "search_data_capabilities",
        "read_data_capability",
        "prepare_data_capability",
        "execute_data_capability",
        "list_data_executions",
        "get_data_execution",
        "list_task_agent_tools",
        "call_task_agent_tool",
    }
    execute_tool = next(tool for tool in tools if tool["name"] == "execute_operation")
    assert execute_tool["annotations"]["destructiveHint"] is True
    assert execute_tool["annotations"]["idempotentHint"] is True
    assert "environment_id" not in execute_tool["inputSchema"]["required"]
    assert execute_tool["inputSchema"]["properties"]["environment_id"]["default"] == "qa"
    register_tool = next(tool for tool in tools if tool["name"] == "register_system")
    update_tool = next(tool for tool in tools if tool["name"] == "update_system")
    forbidden_secret_fields = {"qa_labrador_token", "qa_gateway_prefix"}
    assert forbidden_secret_fields.isdisjoint(register_tool["inputSchema"]["properties"])
    assert forbidden_secret_fields.isdisjoint(update_tool["inputSchema"]["properties"])

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    api_calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_api_request(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录MCP回环请求并返回不含真实副作用的固定响应。

        Args:
            method: 固定HTTP方法。
            path: V2回环路由。
            payload: 可选的严格请求体。

        Returns:
            不启动扫描、Operation或QA调用的固定本地响应。

        Side Effects:
            只向测试内存追加一次调用记录。
        """

        api_calls.append((method, path, payload))
        return {"system": {"system_id": "new-system"}}

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        monkeypatch.setattr(operations, "_api_request", fake_api_request)
        registration = operations._call_tool(
            "register_system",
            {
                "system_id": "new-system",
                "name": "新系统",
                "source_path": "/registered/source",
            },
        )
        update = operations._call_tool(
            "update_system",
            {
                "system_id": SYSTEM_ID,
                "name": "SaaS退票核心",
                "source_path": str(source_root),
            },
        )
        environments = operations._call_tool("list_environments", {"system_id": SYSTEM_ID})
        execution = operations._call_tool(
            "execute_operation",
            {
                "system_id": SYSTEM_ID,
                "operation_id": "facade:demo.RefundFacade#cancel",
                "arguments": {},
                "request_id": "operation-request-0001",
                "environment_id": "QA1",
            },
        )
        scan = operations._call_tool("start_system_scan", {"system_id": SYSTEM_ID})

    assert [call[:2] for call in api_calls] == [
        ("POST", "/systems"),
        ("PUT", f"/systems/{SYSTEM_ID}"),
        ("GET", f"/systems/{SYSTEM_ID}/environments"),
        ("POST", f"/systems/{SYSTEM_ID}/operation-executions"),
        ("POST", f"/systems/{SYSTEM_ID}/scans"),
    ]
    assert all(
        not ({"qa_labrador_token", "qa_gateway_prefix"} & set(payload or {}))
        for _, _, payload in api_calls
    )
    assert api_calls[3][2] is not None
    assert api_calls[3][2]["environment"] == "QA1"
    assert api_calls[4][2] is not None
    assert "environment" not in api_calls[4][2]
    assert all(result.get("isError") is not True for result in (registration, update, environments, execution, scan))

    names = generator.skill_names(
        [
            SYSTEM_ID,
            "collision.system",
            "collision-system",
            "very.long." + "component." * 20 + "core",
        ]
    )
    assert names[SYSTEM_ID] == "open-test-ifightchainsaas-java-refund-core"
    assert len(set(names.values())) == len(names)
    assert all(len(name) <= 63 and name.replace("-", "").isalnum() for name in names.values())

    skill_root = plugin_root / "skills/open-test-ifightchainsaas-java-refund-core"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    metadata = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")
    assert f"`{SYSTEM_ID}`" in skill
    assert "新任务先调用`search_data_capabilities`" in skill
    assert "不同Case与自然语言任务复用同一方法" in skill
    assert "不批量生成接口内部流程、公共函数长文或回归点库" in skill
    assert "仅调用Skill或要求生成知识/Case不构成执行授权" in skill
    assert "只有用户明确要求执行某个READY/PARTIAL Generation时" in skill
    assert "同系统对外Facade优先，外部DSF次之" in skill
    assert "DELETE" in skill and "不重复询问" in skill
    assert "allow_implicit_invocation: false" in metadata


def test_active_worker_preserves_structured_failure_after_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """逻辑QA使用实际test配置后，Worker非零退出仍保留已写出的业务错误。

    Args:
        tmp_path: Worker与配置的隔离目录。
        monkeypatch: 替换Java调用以验证文件协议而不访问QA。

    Returns:
        None；失败类型及消息与Worker响应一致时通过。
    """

    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-worker")
    source_root = tmp_path / "source"
    filter_root = source_root / "conf/filter"
    filter_root.mkdir(parents=True)
    # 测试配置只包含当前MQ操作引用的三个键，证明启动器不会传递无关配置。
    (filter_root / "dubbo.properties.test").write_text(
        "mq.nameSrvAddress=qa-mq.example.test:9876\n"
        "refund.topic=refund-test-topic\n"
        "refund.tag=refund-test-tag\n",
        encoding="utf-8",
    )
    launcher = QaActiveWorkerLauncher(worker_jar)
    profile = DsfClientProfile(
        system_id=SYSTEM_ID,
        environment="qa",
        config_environment="test",
        client_name=f"dsf.{SYSTEM_ID}",
        routing_environment="qa",
        target_environment="test",
        status=DsfProfileStatus.CANDIDATE,
    )
    resource = DiscoveredResource(
        resource_id=f"resource:{SYSTEM_ID}:mq:consumer:test",
        system_id=SYSTEM_ID,
        kind=ResourceKind.MQ,
        role=ResourceRole.CONSUMER,
        logical_name="testConsumer",
        source_refs=[SourceReference(path="src/main/resources/mq.xml", symbol="testConsumer")],
        nameserver_config_key="mq.nameSrvAddress",
        topic_config_key="refund.topic",
        tag_config_key="refund.tag",
    )

    def fake_run_worker(
        application_name: str,
        worker_environment: str,
        request_path: Path,
        response_path: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        """写入安全失败响应并模拟Worker非零退出。

        Args:
            application_name: 扫描资源绑定的配置应用名。
            worker_environment: 扫描时冻结的Java与SDK运行环境。
            request_path: 启动器创建的请求文件。
            response_path: 假Worker响应目标。
            timeout_seconds: 调用超时。

        Returns:
            返回码为3的假进程结果。
        """

        assert application_name == SYSTEM_ID
        assert worker_environment == "test"
        assert request_path.is_file()
        assert timeout_seconds == 60
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        # 响应只回显随机协议身份和已安全处理的真实业务原因。
        response_path.write_text(
            json.dumps(
                {
                    "request_id": request_payload["request_id"],
                    "status": "failed",
                    "error_code": "QA_ACTIVE_OPERATION_FAILED",
                    "message": "current QA topic configuration is missing",
                }
            ),
            encoding="utf-8",
        )
        response_path.chmod(0o600)
        return subprocess.CompletedProcess(args=["java"], returncode=3, stdout="", stderr="")

    monkeypatch.setattr(launcher, "_run_worker", fake_run_worker)
    request = OperationExecutionRequest(
        operation_id=f"mq:{SYSTEM_ID}:test",
        arguments={"message": {"refundSerialNo": "OPENTEST_MQ_TEST"}},
        request_id="request-active-worker-test",
        environment="qa",
    )

    with pytest.raises(OperationProviderFailure, match="current QA topic configuration is missing"):
        launcher.execute(profile, OperationKind.MQ, resource, request, source_root)


@pytest.mark.parametrize(
    ("filter_suffix", "expected_environment"),
    [("qa", "qa"), ("test", "test")],
)
def test_legacy_manifest_mq_uses_the_filter_environment_actually_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filter_suffix: str,
    expected_environment: str,
) -> None:
    """旧Manifest通过逻辑QA执行时，MQ JVM仍使用auto实际选中的filter环境。

    Args:
        tmp_path: Pytest隔离的Worker与filter目录。
        monkeypatch: 替换Java进程，捕获启动环境且不访问MQ。
        filter_suffix: 本次唯一存在的qa或test配置后缀。
        expected_environment: Java和MQ SDK应共同使用的环境。

    Returns:
        None；即使旧Profile的targetenv为test，qa filter仍以qa启动时通过。

    Side Effects:
        只在临时目录交换一次0600 Worker JSON，不启动Java或访问MQ。
    """

    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-worker")
    source_root = tmp_path / "source"
    filter_root = source_root / "conf/filter"
    filter_root.mkdir(parents=True)
    (filter_root / f"dsf_application.properties.{filter_suffix}").write_text(
        "mq.nameSrvAddress=qa-mq.example.test:9876\n"
        "refund.topic=refund-topic\n",
        encoding="utf-8",
    )
    launcher = QaActiveWorkerLauncher(worker_jar)
    profile = DsfClientProfile(
        system_id=SYSTEM_ID,
        environment="qa",
        client_name=f"dsf.{SYSTEM_ID}",
        routing_environment="qa",
        target_environment="test",
        status=DsfProfileStatus.CANDIDATE,
    )
    resource = DiscoveredResource(
        resource_id=f"resource:{SYSTEM_ID}:mq:consumer:legacy",
        system_id=SYSTEM_ID,
        kind=ResourceKind.MQ,
        role=ResourceRole.CONSUMER,
        logical_name="legacyConsumer",
        source_refs=[SourceReference(path="src/main/resources/mq.xml", symbol="legacyConsumer")],
        nameserver_config_key="mq.nameSrvAddress",
        topic_config_key="refund.topic",
    )

    def fake_run_worker(
        application_name: str,
        worker_environment: str,
        request_path: Path,
        response_path: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        """回写成功协议并断言旧扫描实际filter环境。

        Args:
            application_name: 扫描资源所属系统ID。
            worker_environment: 启动Java和公司SDK的环境。
            request_path: 启动器生成的私有请求文件。
            response_path: 假Worker响应目标。
            timeout_seconds: 业务调用超时。

        Returns:
            返回码为零的假进程结果。

        Side Effects:
            创建一个0600成功响应文件。
        """

        assert application_name == SYSTEM_ID
        assert worker_environment == expected_environment
        assert timeout_seconds == 60
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        response_path.write_text(
            json.dumps(
                {
                    "request_id": request_payload["request_id"],
                    "status": "completed",
                    "result": {"status": "accepted"},
                }
            ),
            encoding="utf-8",
        )
        response_path.chmod(0o600)
        return subprocess.CompletedProcess(args=["java"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(launcher, "_run_worker", fake_run_worker)
    # 用户选择始终是逻辑QA，auto解析出的实际test只用于Worker路由。
    response = launcher.execute(
        profile,
        OperationKind.MQ,
        resource,
        OperationExecutionRequest(
            operation_id=f"mq:{SYSTEM_ID}:legacy",
            arguments={"message": {"refundSerialNo": "LEGACY_FILTER_TEST"}},
            request_id=f"request-legacy-filter-{filter_suffix}",
            environment="qa",
        ),
        source_root,
    )

    assert response == {"status": "accepted"}
