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
from opentest.adapters.codex_app_server import CodexAppServerClient
from opentest.adapters.knowledge_interview import KnowledgeInterviewStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_execution_store import OperationExecutionStore
from opentest.adapters.qa_active_worker import QaActiveWorkerLauncher
from opentest.adapters.source_analysis import SourceScanArtifactStore
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
                metadata={"tool_type": "job_http_trigger", "status": "ready"},
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
    """自愿退票意图应命中createOrder，缺字段不执行，重复request_id只写一次。"""

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
        with pytest.raises(KnowledgeValidationError, match="refundDetailApiDTO"):
            service.execute(SYSTEM_ID, missing_request)
        assert provider.facade_calls == 0

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
        assert provider.facade_calls == 0

        request = OperationExecutionRequest(
            operation_id=FACADE_OPERATION_ID,
            arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
            request_id="request-create-refund-001",
        )
        first = service.execute(SYSTEM_ID, request)
        duplicate = service.execute(SYSTEM_ID, request)
        assert first.execution_id == duplicate.execution_id
        assert first.status == OperationExecutionStatus.COMPLETED
        assert provider.facade_calls == 1
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
        assert provider.facade_calls == 1
    finally:
        tasks.close()


def test_unified_catalog_executes_external_dsf_mq_and_database_operations(tmp_path: Path) -> None:
    """统一目录应从同一扫描生成外部DSF、消费者MQ和数据库操作并持久化完整业务结果。"""

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
    """Facade派发必须固定到能力来源扫描，不能在执行时重新解析latest。"""

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    source_scan_id = "scan-codex-native-fixed-provider"
    _publish_manifest(artifacts, _manifest(source_root, source_scan_id))
    capability = OperationCapabilityCatalog(store, artifacts).derive(SYSTEM_ID)[0]
    dsf_operations = MagicMock()
    dsf_operations.execute_indexed.return_value = DsfExecutionResponse(
        request_id="worker-request-1",
        operation_id=capability.provider_operation_id,
        status="success",
        output={"accepted": True},
    )
    provider = LocalQaOperationProvider(dsf_operations, artifacts, MagicMock())
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


def test_local_facade_provider_raises_stable_failure_for_failed_worker_response(tmp_path: Path) -> None:
    """Worker文件协议成功但DSF结果失败时provider必须抛出结构化异常。

    Args:
        tmp_path: Pytest隔离知识和扫描根。
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
    provider = LocalQaOperationProvider(dsf_operations, artifacts, MagicMock())
    request = OperationExecutionRequest(
        operation_id=capability.operation_id,
        arguments={"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
        request_id="request-fixed-scan-failed-001",
    )

    with pytest.raises(OperationProviderFailure) as captured:
        provider.execute_facade(capability, request)

    assert captured.value.error_code == "DSF_ROUTING_FAILED"
    dsf_operations.execute_indexed.assert_called_once()


def test_local_job_provider_keeps_nonzero_business_error_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job工具非零退出时应抛出真实业务原因并携带已解析输出。

    Args:
        tmp_path: Pytest隔离知识、扫描和生成工具根。
        monkeypatch: 用不访问进程的执行器替身返回结构化失败。

    Returns:
        None；provider异常同时保留业务message和完整输出时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    capability = next(
        item for item in OperationCapabilityCatalog(store, artifacts).derive(SYSTEM_ID)
        if item.operation_id == JOB_OPERATION_ID
    )
    tool_execution = MagicMock(
        exit_code=7,
        output={"message": "job business rejected", "orderNo": "QA-ORDER-1"},
        stderr="",
        elapsed_seconds=0.1,
    )
    executor = MagicMock()
    executor.execute.return_value = tool_execution
    monkeypatch.setattr("opentest.application.operations.DsfExecutor", MagicMock(return_value=executor))
    environment_loader = MagicMock()
    environment_loader.load.return_value.values = {"tool_environment": {}}
    provider = LocalQaOperationProvider(MagicMock(), artifacts, environment_loader)
    request = OperationExecutionRequest(
        operation_id=JOB_OPERATION_ID,
        arguments={"reason": "manual QA verification"},
        request_id="request-job-provider-failure-001",
    )

    with pytest.raises(OperationProviderFailure) as captured:
        provider.execute_job(capability, request)

    assert captured.value.error_code == "JOB_TRIGGER_FAILED"
    assert captured.value.safe_message == "job business rejected"
    assert captured.value.business_result == tool_execution.output


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


def test_operation_job_is_async_once_and_unknown_or_non_qa_is_rejected(tmp_path: Path) -> None:
    """Job只异步派发一次，UNKNOWN、任意ID和非QA请求均不得调用provider。"""

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    provider = FakeOperationProvider()
    service, tasks = _operation_service(store, artifacts, provider)
    try:
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
        running = service.execute(SYSTEM_ID, request)
        duplicate = service.execute(SYSTEM_ID, request)
        assert running.execution_id == duplicate.execution_id
        assert running.status == OperationExecutionStatus.RUNNING
        assert running.task_id
        tasks.close()
        completed = service.get_execution(running.execution_id)
        assert completed.status == OperationExecutionStatus.COMPLETED
        assert provider.job_calls == 1
    finally:
        tasks.close()


def test_operation_job_failure_persists_real_reason_and_structured_business_result(tmp_path: Path) -> None:
    """异步Job失败记录应保留真实原因和业务输出，只清理明确凭据字段。

    Args:
        tmp_path: Pytest隔离的操作记录与任务目录。

    Returns:
        None；最终FAILED记录可供Codex诊断且凭据未持久化时通过。
    """

    store, source_root = _registered_workspace(tmp_path)
    artifacts = SourceScanArtifactStore(store.root)
    _publish_manifest(artifacts, _manifest(source_root))
    provider = FakeOperationProvider()
    provider.job_failure = OperationProviderFailure(
        "JOB_TRIGGER_FAILED",
        "job business rejected",
        {
            "message": "job business rejected",
            "orderNo": "QA-ORDER-1",
            "token": "local-secret",
            "businessUrl": "https://qa-business.example/jobs/QA-ORDER-1",
        },
    )
    service, tasks = _operation_service(store, artifacts, provider)
    request = OperationExecutionRequest(
        operation_id=JOB_OPERATION_ID,
        arguments={"reason": "manual QA verification"},
        request_id="request-refund-job-failure-001",
    )

    try:
        running = service.execute(SYSTEM_ID, request)
        tasks.close()
        failed = service.get_execution(running.execution_id)
    finally:
        tasks.close()

    assert failed.status == OperationExecutionStatus.FAILED
    assert failed.error_code == "JOB_TRIGGER_FAILED"
    assert failed.message == "job business rejected"
    assert failed.result["message"] == "job business rejected"
    assert failed.result["orderNo"] == "QA-ORDER-1"
    assert failed.result["token"] == "<redacted>"
    assert failed.result["businessUrl"] == "https://qa-business.example/jobs/QA-ORDER-1"
    assert provider.job_calls == 1


def test_operation_http_api_searches_and_executes_through_loopback(tmp_path: Path) -> None:
    """四个本地API应返回统一能力并通过回环幂等执行一次假Facade。"""

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.initialize()
    application.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="SaaS退票核心", source_path=str(source_root))
    )
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
            },
        )
        repeated = client.post(
            f"/api/v2/systems/{SYSTEM_ID}/operation-executions",
            json={
                "operation_id": FACADE_OPERATION_ID,
                "arguments": {"refundDetailApiDTO": {}, "orderChannelSource": "QA_TEST"},
                "request_id": "request-http-refund-001",
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
    """MCP应暴露完整工作流，凭据不进入工具参数且系统Skill禁止隐式调用。

    Args:
        tmp_path: Pytest隔离的真实FastAPI本机设置存储。
        monkeypatch: 拦截回环API，证明凭据仅从本机安全设置内部转交。
    """

    plugin_root = Path(__file__).parents[2] / "opentest-plugin-marketplace/plugins/open-test-knowledge"
    operations = _load_script_module(plugin_root / "scripts/opentest_operations_mcp.py", "operations_mcp_test")
    generator = _load_script_module(plugin_root / "scripts/sync_system_skills.py", "skill_sync_test")
    tools = operations._tool_definitions()
    assert {tool["name"] for tool in tools} == {
        "search_operations",
        "get_operation",
        "execute_operation",
        "get_operation_execution",
        "list_systems",
        "register_system",
        "update_system",
        "start_system_scan",
        "get_task",
        "sync_system_skills",
        "list_system_source",
        "search_system_source",
        "read_system_source",
        "prepare_knowledge_target",
        "generate_interface_cases",
        "execute_case",
    }
    execute_tool = next(tool for tool in tools if tool["name"] == "execute_operation")
    assert execute_tool["annotations"]["destructiveHint"] is True
    assert execute_tool["annotations"]["idempotentHint"] is True
    register_tool = next(tool for tool in tools if tool["name"] == "register_system")
    update_tool = next(tool for tool in tools if tool["name"] == "update_system")
    forbidden_secret_fields = {"qa_labrador_token", "qa_gateway_prefix"}
    assert forbidden_secret_fields.isdisjoint(register_tool["inputSchema"]["properties"])
    assert forbidden_secret_fields.isdisjoint(update_tool["inputSchema"]["properties"])

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="SaaS退票核心", source_path=str(source_root))
    )
    application.save_local_settings(
        SYSTEM_ID,
        "fake-local-token",
        "https://qa-gateway.invalid",
    )
    api_calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_api_request(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录MCP回环请求并只在本机设置读取时提供假凭据。

        Args:
            method: 固定HTTP方法。
            path: V2回环路由。
            payload: 可选的严格请求体。

        Returns:
            真实FastAPI本机设置响应，或不启动扫描的注册成功假响应。
        """

        api_calls.append((method, path, payload))
        if path.endswith("/local-settings"):
            # 直接读取真实路由形状，防止MCP与FastAPI再次发生字段名漂移。
            response = client.request(method, f"/api/v2{path}")
            assert response.status_code == 200
            return response.json()
        return {"system": {"system_id": "new-system"}}

    with TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        monkeypatch.setattr(operations, "_api_request", fake_api_request)
        registration = operations._call_tool(
            "register_system",
            {
                "system_id": "new-system",
                "name": "新系统",
                "source_path": "/registered/source",
                "settings_source_system_id": SYSTEM_ID,
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

    assert api_calls[0][0:2] == ("GET", f"/systems/{SYSTEM_ID}/local-settings")
    assert api_calls[1][2] is not None
    assert api_calls[1][2]["qa_labrador_token"] == "fake-local-token"
    assert api_calls[2][0:2] == ("GET", f"/systems/{SYSTEM_ID}/local-settings")
    assert api_calls[3][2] is not None
    assert "qa_labrador_token" not in api_calls[3][2]
    assert api_calls[3][2]["qa_gateway_prefix"] == "https://qa-gateway.invalid"
    assert "fake-local-token" not in registration["content"][0]["text"]
    assert "fake-local-token" not in update["content"][0]["text"]

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
    assert "严格按用户给出的顺序逐个处理" in skill
    assert "有效知识已存在" in skill
    assert "知识不完整不阻止生成" in skill
    assert "同系统对外Facade优先，外部DSF次之" in skill
    assert "env=qa" in skill and "targetenv=test" in skill
    assert "DELETE和DDL" in skill
    assert "allow_implicit_invocation: false" in metadata


def test_active_worker_preserves_structured_failure_after_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker非零退出但已写响应时应返回真实错误，不改写为通用启动失败。"""

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
        request_path: Path,
        response_path: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        """写入安全失败响应并模拟Worker非零退出。

        Args:
            application_name: 扫描资源绑定的配置应用名。
            request_path: 启动器创建的请求文件。
            response_path: 假Worker响应目标。
            timeout_seconds: 调用超时。

        Returns:
            返回码为3的假进程结果。
        """

        assert application_name == SYSTEM_ID
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
    )

    with pytest.raises(OperationProviderFailure, match="current QA topic configuration is missing"):
        launcher.execute(profile, OperationKind.MQ, resource, request, source_root)


def test_codex_thread_recovery_uses_read_without_resume_or_new_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """持久线程核对应只调用thread/read，不恢复、创建或启动模型turn。"""

    client = CodexAppServerClient()
    calls: list[str] = []
    process = object()

    def fake_start_process() -> object:
        """返回无需子进程的测试占位对象。"""

        return process

    def fake_request(
        supplied_process: object,
        request_id: int,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """记录App Server方法并返回固定线程。

        Args:
            supplied_process: 测试占位进程。
            request_id: JSON-RPC请求ID。
            method: App Server方法名。
            params: 方法参数。

        Returns:
            initialize空结果或固定thread/read结果。
        """

        assert supplied_process is process
        assert request_id in {1, 2}
        calls.append(method)
        if method == "thread/read":
            return {"thread": {"id": params["threadId"]}}
        return {}

    def fake_notify(supplied_process: object, method: str, params: dict[str, Any]) -> None:
        """记录初始化通知且不产生外部副作用。

        Args:
            supplied_process: 测试占位进程。
            method: 初始化通知方法。
            params: 空通知参数。
        """

        assert supplied_process is process
        assert params == {}
        calls.append(method)

    def fake_close(supplied_process: object) -> None:
        """验证测试占位进程被无条件关闭。

        Args:
            supplied_process: 测试占位进程。
        """

        assert supplied_process is process
        calls.append("closed")

    monkeypatch.setattr(client, "_start_process", fake_start_process)
    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "_notify", fake_notify)
    monkeypatch.setattr(client, "_close_process", fake_close)

    thread = client.read_thread("01a03270-708f-79d1-80a6-62491ecb863d")
    assert thread.deep_link == "codex://threads/01a03270-708f-79d1-80a6-62491ecb863d"
    assert calls == ["initialize", "initialized", "thread/read", "closed"]
    assert "thread/resume" not in calls
    assert "thread/start" not in calls
    assert "turn/start" not in calls
