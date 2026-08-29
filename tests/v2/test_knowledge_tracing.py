"""验证createOrder纵向知识追踪、确认保护、索引发布和Agent安全边界。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from opentest.adapters.agent_runner import AgentRunner, AgentRunnerConfig
from opentest.adapters.codex_app_server import (
    CodexAppServerClient,
    CodexAppServerConfig,
    CodexThreadCreationRequest,
    CodexThreadStartWire,
    _resolve_codex_app_server_executable,
)
from opentest.adapters.knowledge_store import AUTO_END, AUTO_START, GitKnowledgeStore
from opentest.adapters.knowledge_tracing import JavaKnowledgeTracer
from opentest.adapters.registered_source_mcp import RegisteredSourceReader
from opentest.adapters import registered_source_mcp
from opentest.adapters.setup_contract_store import SetupContractRuleStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.application.knowledge import KnowledgeGenerationService
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import LocalTaskManager, report_task_progress
from opentest.domain.errors import ExecutionFailure, KnowledgeValidationError, ScopeViolationError, TaskCancelledError
from opentest.domain.models import (
    AgentKnowledgeEnvelope,
    AgentKnowledgeCompleteness,
    AgentKnowledgeSourceReference,
    AgentRunEvidence,
    AgentRunRequest,
    EntryFactAssertion,
    EntryFactCandidateConfirmation,
    EntryFactCandidateReplacement,
    EntryFactCandidateSet,
    EntryFactKnowledge,
    EntryPoint,
    KnowledgeConfirmation,
    KnowledgeDraft,
    KnowledgeGenerationRequest,
    KnowledgeGenerationBatchRequest,
    KnowledgeGenerationWorkflowBatch,
    KnowledgeConclusionSource,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeClientCandidateEnvelope,
    KnowledgeInvocationContract,
    KnowledgeQuestion,
    KnowledgeStatus,
    OperationMutability,
    ScanManifest,
    SemanticAnalysisResult,
    SemanticCaseEvidence,
    SemanticCallEdge,
    SemanticFieldDefinition,
    SemanticMethodDefinition,
    SemanticResolutionStatus,
    SemanticTypeDefinition,
    SourceBaseline,
    SourceReference,
    SetupAvailabilityRule,
    SetupContractRuleSet,
    SetupFactContractDefinition,
    SetupFactOrigin,
    SetupFactRequiredField,
    SetupStatePredicateDefinition,
    StateMachineDefinition,
    StateTransition,
    SystemDefinition,
    TaskProgressUpdate,
    TaskStatus,
)


def _assert_codex_strict_schema(schema: dict[str, object]) -> None:
    """递归核对Codex结构化输出要求的对象闭合性和必填字段完整性。

    Args:
        schema: Pydantic生成或假CLI从命令参数读取的JSON Schema节点。

    Raises:
        AssertionError: 任一对象允许额外字段、漏列必填字段或使用动态Map时抛出。
    """

    # 每个对象都必须关闭额外字段，并把properties中的全部字段列入required。
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        assert isinstance(properties, dict)
        assert schema.get("additionalProperties") is False
        required = schema.get("required")
        assert isinstance(required, list)
        assert len(required) == len(properties)
        assert set(required) == set(properties)
    # 递归覆盖属性、数组项、联合分支和模型定义，避免只验证根对象造成假通过。
    for key in ("properties", "$defs"):
        children = schema.get(key, {})
        if isinstance(children, dict):
            for child in children.values():
                if isinstance(child, dict):
                    _assert_codex_strict_schema(child)
    items = schema.get("items")
    if isinstance(items, dict):
        _assert_codex_strict_schema(items)
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key, [])
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict):
                    _assert_codex_strict_schema(branch)


class FixedBaselineRepository:
    """为知识服务测试返回与扫描完全相同的稳定源码基线。"""

    def __init__(self, baseline: SourceBaseline):
        """保存后续capture调用应返回的基线。"""

        self.baseline = baseline

    def capture(self, _: Path | str) -> SourceBaseline:
        """返回仅采集时间可不同的固定源码状态。"""

        return self.baseline.model_copy()


def _write_create_order_sources(source: Path) -> dict[str, Path]:
    """写入包含真实分析标记的最小createOrder Java证据集。"""

    files = {
        "facade": source / "TradeFacadeImpl.java",
        "validator": source / "CreateOrderValidator.java",
        "invoker": source / "CreateOrderServiceInvoker.java",
        "builder": source / "OrderBuilder.java",
        "state": source / "TicketingActor.java",
    }
    source.mkdir(parents=True)
    files["facade"].write_text(
        "class TradeFacadeImpl { Result createOrder(CreateOrderRequest request) { return execute(ApiServiceEnum.CREATE_ORDER); } }\n",
        encoding="utf-8",
    )
    files["validator"].write_text(
        'class CreateOrderValidator { void validate() { String passengerSerialId = ""; throw new Error("invalid connectType"); } }\n',
        encoding="utf-8",
    )
    files["invoker"].write_text(
        "class CreateOrderServiceInvoker { void invokeInner() { // 联程 | 港铁\n"
        " PassengerTypeEnum type = PassengerTypeEnum.Children; orderStateDelegate.setState(); } }\n",
        encoding="utf-8",
    )
    files["builder"].write_text(
        "class OrderBuilder { private boolean verifyHkPayment() { mtrTicketPriceService.getPrice(); return true; }\n"
        " private boolean fillPlanForeignPrice() { baseDataRepository.findTargetTicketPrice(); passenger.getForeignTicketPrice(); return true; } }\n",
        encoding="utf-8",
    )
    files["state"].write_text("@State class TicketingActor {}\n", encoding="utf-8")
    return files


def _manifest(source: Path, files: dict[str, Path]) -> ScanManifest:
    """构造绑定createOrder入口和订单状态机的最小扫描manifest。"""

    baseline = SourceBaseline(source_path=str(source), commit="abc123", dirty=False)
    source_id = "com.ly.travel.train.supplychain.bookingcore.facade.TradeFacade#createOrder"
    return ScanManifest(
        scan_id="scan-20260811000000-abc123-test",
        system_id="train-booking-core",
        baseline=baseline,
        entries=[
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id="train-booking-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="TradeFacade#createOrder",
                source_id=source_id,
                source_path=str(files["facade"]),
                tool_id="facade.trade.create_order",
            )
        ],
        state_machines=[
            StateMachineDefinition(
                machine_id="state-machine:order_state_enum",
                system_id="train-booking-core",
                state_enum="OrderStateEnum",
                title="订单状态机",
                transitions=[
                    StateTransition(
                        transition_id="transition:ticketing",
                        actor="TicketingActor",
                        from_states=["INIT"],
                        to_states=["TICKETING"],
                        source_ref=SourceReference(path="TicketingActor.java", symbol="TicketingActor", line=1),
                    )
                ],
            )
        ],
    )


def _knowledge_service(tmp_path: Path) -> tuple[KnowledgeGenerationService, GitKnowledgeStore, ScanManifest]:
    """创建已注册系统、latest扫描和可重建索引的知识服务夹具。"""

    source = tmp_path / "source"
    files = _write_create_order_sources(source)
    manifest = _manifest(source, files)
    knowledge_root = tmp_path / "knowledge"
    store = GitKnowledgeStore(knowledge_root)
    store.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    artifacts = SourceScanArtifactStore(knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(manifest.system_id, manifest.scan_id)
    index = SqliteKnowledgeIndex(knowledge_root / ".opentest" / "index.sqlite")
    service = KnowledgeGenerationService(
        store,
        index,
        artifacts,
        git_repository=FixedBaselineRepository(manifest.baseline),
    )
    return service, store, manifest


def _entry_fact_confirmation_fixture(
    tmp_path: Path,
) -> tuple[
    KnowledgeGenerationService,
    GitKnowledgeStore,
    ScanManifest,
    KnowledgeGenerationWorkflowBatch,
    EntryFactAssertion,
    EntryFactAssertion,
]:
    """准备含两个隔离AI候选和一个正式Fact契约的入口知识批次。

    Args:
        tmp_path: Pytest隔离的源码、知识和索引目录。

    Returns:
        知识服务、存储、latest扫描、候选批次及两条可独立确认的候选断言。

    Side Effects:
        生成临时正式入口节点，并写入临时Setup契约和候选草稿批次。
    """

    service, store, manifest = _knowledge_service(tmp_path)
    generated = service.generate(
        KnowledgeGenerationRequest(
            system_id=manifest.system_id,
            entry_id=manifest.entries[0].entry_id,
        )
    )
    entry_node = next(
        node for node in generated.nodes if node.kind == KnowledgeNodeKind.FACADE
    )
    entry_id = entry_node.aliases[0]
    contract_id = "ticket-order/v1"
    SetupContractRuleStore(store).write(
        SetupContractRuleSet(
            system_id=manifest.system_id,
            fact_contracts=[
                SetupFactContractDefinition(
                    fact_contract_id=contract_id,
                    display_name="通用出票单",
                    required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
                    required_fields=[
                        SetupFactRequiredField(
                            path="order_no",
                            schema_type="string",
                        ),
                        SetupFactRequiredField(
                            path="state",
                            schema_type="string",
                        ),
                    ],
                    business_identity_paths=["order_no"],
                    state_path="state",
                    state_predicates=[
                        SetupStatePredicateDefinition(
                            name="ISSUED",
                            display_name="已出票",
                            allowed_values=["ISSUED"],
                        )
                    ],
                )
            ],
        )
    )
    evidence = entry_node.source_refs[0]
    required = EntryFactAssertion(
        assertion_id="entry-fact:generic-ticket-required",
        assertion_type="REQUIRES_FACT",
        slot_id="ticket_order",
        fact_contract_id=contract_id,
        required_state="ISSUED",
        acquisition_policy="QUERY_ONLY",
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[evidence],
    )
    produced = EntryFactAssertion(
        assertion_id="entry-fact:generic-ticket-produced",
        assertion_type="PRODUCES_FACT",
        slot_id="created_ticket_order",
        fact_contract_id=contract_id,
        produced_state="ISSUED",
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[evidence],
    )
    candidates = EntryFactCandidateSet(
        system_id=manifest.system_id,
        entry_id=entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        assertions=[required, produced],
    )
    draft = KnowledgeDraft(
        draft_id="draft-entry-fact-confirmation",
        system_id=manifest.system_id,
        target_id=entry_id,
        node=entry_node,
        content="仅包含待确认结构化入口事实的通用草稿。",
        entry_fact_candidates=candidates,
    )
    batch = KnowledgeGenerationWorkflowBatch(
        batch_id="knowledge-workflow-entry-fact-confirmation",
        system_id=manifest.system_id,
        scan_id=manifest.scan_id,
        target_ids=[entry_id],
        status="PENDING_CONFIRMATION",
        drafts=[draft],
    )
    store.write_draft_batch(batch)
    return service, store, manifest, batch, required, produced


def test_create_order_tracer_builds_deep_hk_rules_with_source_lines(tmp_path: Path) -> None:
    """createOrder应沿Invoker到港币规则、数据源和状态机生成可追溯关系。"""

    source = tmp_path / "source"
    files = _write_create_order_sources(source)
    manifest = _manifest(source, files)
    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)
    nodes = {node.node_id: node for node in batch.nodes}

    assert nodes["rule:create-order:hk-payment-verify"].source_refs[0].path == "OrderBuilder.java"
    assert nodes["rule:create-order:hk-payment-verify"].source_refs[0].line == 1
    assert nodes["rule:create-order:hk-plan-price"].source_refs[0].line == 2
    assert "state-machine:OrderStateEnum" in nodes
    edge_pairs = {(edge.source_node_id, edge.target_node_id) for edge in batch.edges}
    assert ("facade:TradeFacade#createOrder", "logic:CreateOrderServiceInvoker#invokeInner") in edge_pairs
    assert ("logic:CreateOrderServiceInvoker#invokeInner", "rule:create-order:hk-payment-verify") in edge_pairs
    assert len(batch.questions) == 2


def test_shallow_tracer_uses_source_symbol_instead_of_display_name(tmp_path: Path) -> None:
    """其他Facade显示名不在源码中时仍应按完整source_id方法名定位证据。

    Args:
        tmp_path: Pytest提供的隔离接口源码目录。

    Returns:
        None；抽象尾部方法形成唯一最小入口事实且证据身份准确即通过。
    """

    # 接口方法没有实现体，扫描器只能发布方法存在这一最小事实。
    source = tmp_path / "source"
    source.mkdir()
    facade = source / "TradeFacade.java"
    facade.write_text("interface TradeFacade { void cancel(CancelRequest request); }\n", encoding="utf-8")
    source_id = "com.example.TradeFacade#cancel"
    manifest = ScanManifest(
        scan_id="scan-20260811000000-abc123-shallow",
        system_id="train-booking-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id="train-booking-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="trade / cancel",
                source_id=source_id,
                source_path=str(facade),
            )
        ],
    )

    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)

    assert len(batch.nodes) == 1
    assert batch.nodes[0].summary.startswith("当前源码仅能证明")
    assert batch.nodes[0].source_refs[0].line == 1
    assert batch.nodes[0].source_refs[0].symbol == source_id


def _write_dependency_sources(source: Path) -> dict[str, Path]:
    """写入可证明Facade路由、共享方法和两条取消流转的最小Java源码。

    Args:
        source: Pytest隔离的注册源码根。

    Returns:
        供Manifest证据和行号构造使用的命名源码路径。

    Side Effects:
        在隔离目录创建Java文件，不访问真实项目源码。
    """

    source.mkdir(parents=True)
    files = {
        "facade": source / "RefundFacade.java",
        "implementation": source / "RefundFacadeImpl.java",
        "validator": source / "RefundCancelValidator.java",
        "invoker": source / "RefundCancelServiceInvoker.java",
        "shared": source / "SharedRefundRules.java",
        "entity": source / "RefundOrder.java",
        "cancel_actor": source / "RefundOrderCancelPostActor.java",
        "manual_actor": source / "RefundOrderManualCancelPostActor.java",
        "other_actor": source / "OtherCancelPostActor.java",
    }
    files["facade"].write_text(
        "package demo; interface RefundFacade { Object cancel(Object request); }\n",
        encoding="utf-8",
    )
    files["implementation"].write_text(
        "package demo; class RefundFacadeImpl implements RefundFacade {\n"
        "  Object cancel(Object request) { return execute(request, RefundOrderServiceEnum.CANCEL); }\n"
        "}\n",
        encoding="utf-8",
    )
    files["validator"].write_text(
        "package demo; @TradeService(name = RefundOrderServiceEnum.CANCEL)\n"
        "class RefundCancelValidator { void validate(Object request) { if (request == null) throw new Error(); } }\n",
        encoding="utf-8",
    )
    files["invoker"].write_text(
        "package demo; @TradeService(name = RefundOrderServiceEnum.CANCEL)\n"
        "class RefundCancelServiceInvoker {\n"
        "  Object invoke(Object request) { return doInvoke(request); }\n"
        "  Object doInvoke(Object request) {\n"
        "    sharedRefundRules.evaluate(request);\n"
        "    created.setState(RefundOrderStateEnum.PENDING_APPLY);\n"
        "    refundOrderDao.insert(created);\n"
        "    orderStateDelegate.setState(request, RefundOrderStateEnum.REFUND_CANCEL);\n"
        "    return request;\n"
        "  }\n"
        "  void unrelated(Object request) { orderStateDelegate.setState(request, OtherStateEnum.REFUND_CANCEL); }\n"
        "}\n",
        encoding="utf-8",
    )
    files["shared"].write_text(
        "package demo; class SharedRefundRules { Object evaluate(Object request) { if (request == null) throw new Error(); return request; } }\n",
        encoding="utf-8",
    )
    files["entity"].write_text(
        "package demo; class RefundOrder { String refund_no; RefundOrderStateEnum state; }\n",
        encoding="utf-8",
    )
    files["cancel_actor"].write_text(
        "package demo; @State class RefundOrderCancelPostActor {\n"
        "  void addTask() { if (enabled) addReason(); }\n"
        "  void addReason() { refundRepository.update(); }\n"
        "}\n",
        encoding="utf-8",
    )
    files["manual_actor"].write_text(
        "package demo; @State class RefundOrderManualCancelPostActor { void addTask() { noticeService.send(); } }\n",
        encoding="utf-8",
    )
    files["other_actor"].write_text(
        "package demo; @State class OtherCancelPostActor { void addTask() { noticeService.send(); } }\n",
        encoding="utf-8",
    )
    return files


def _dependency_source_ref(source: Path, path: Path, symbol: str, marker: str) -> SourceReference:
    """构造指向隔离Java声明或调用行的相对源码引用。

    Args:
        source: 注册源码根。
        path: 需要引用的Java文件。
        symbol: 完整语义符号或类型身份。
        marker: 必须唯一出现于证据行的源码文本。

    Returns:
        带精确一基行号的SourceReference。
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    line = next(index for index, content in enumerate(lines, start=1) if marker in content)
    return SourceReference(path=path.relative_to(source).as_posix(), symbol=symbol, line=line)


def _dependency_manifest(source: Path, files: dict[str, Path]) -> ScanManifest:
    """构造包含可达语义图、精确状态枚举和不可达干扰项的Manifest。

    Args:
        source: 注册源码根。
        files: `_write_dependency_sources`生成的源码路径。

    Returns:
        可供Tracer和客户端批次规划共同使用的稳定扫描结果。
    """

    entry_id = "facade:demo.RefundFacade#cancel"
    implementation_symbol = "demo.RefundFacadeImpl#cancel(java.lang.Object)"
    validator_symbol = "demo.RefundCancelValidator#validate(java.lang.Object)"
    invoke_symbol = "demo.RefundCancelServiceInvoker#invoke(java.lang.Object)"
    do_invoke_symbol = "demo.RefundCancelServiceInvoker#doInvoke(java.lang.Object)"
    unrelated_symbol = "demo.RefundCancelServiceInvoker#unrelated(java.lang.Object)"
    shared_symbol = "demo.SharedRefundRules#evaluate(java.lang.Object)"
    methods = [
        SemanticMethodDefinition(
            symbol_id=implementation_symbol,
            qualified_class_name="demo.RefundFacadeImpl",
            method_name="cancel",
            source_ref=_dependency_source_ref(source, files["implementation"], implementation_symbol, "Object cancel"),
        ),
        SemanticMethodDefinition(
            symbol_id=validator_symbol,
            qualified_class_name="demo.RefundCancelValidator",
            method_name="validate",
            source_ref=_dependency_source_ref(source, files["validator"], validator_symbol, "void validate"),
        ),
        SemanticMethodDefinition(
            symbol_id=invoke_symbol,
            qualified_class_name="demo.RefundCancelServiceInvoker",
            method_name="invoke",
            source_ref=_dependency_source_ref(source, files["invoker"], invoke_symbol, "Object invoke"),
        ),
        SemanticMethodDefinition(
            symbol_id=do_invoke_symbol,
            qualified_class_name="demo.RefundCancelServiceInvoker",
            method_name="doInvoke",
            source_ref=_dependency_source_ref(source, files["invoker"], do_invoke_symbol, "Object doInvoke"),
        ),
        SemanticMethodDefinition(
            symbol_id=unrelated_symbol,
            qualified_class_name="demo.RefundCancelServiceInvoker",
            method_name="unrelated",
            source_ref=_dependency_source_ref(source, files["invoker"], unrelated_symbol, "void unrelated"),
        ),
        SemanticMethodDefinition(
            symbol_id=shared_symbol,
            qualified_class_name="demo.SharedRefundRules",
            method_name="evaluate",
            reuse_entry_count=2,
            entry_point_ids=[implementation_symbol, "demo.TimeoutCancelJob#process(java.lang.Object)"],
            source_ref=_dependency_source_ref(source, files["shared"], shared_symbol, "Object evaluate"),
        ),
    ]
    call_edges = [
        SemanticCallEdge(
            caller_symbol_id=invoke_symbol,
            callee_symbol_id=do_invoke_symbol,
            callee_expression="doInvoke",
            source_ref=_dependency_source_ref(source, files["invoker"], invoke_symbol, "return doInvoke"),
            resolution_status=SemanticResolutionStatus.RESOLVED,
        ),
        SemanticCallEdge(
            caller_symbol_id=do_invoke_symbol,
            callee_symbol_id=shared_symbol,
            callee_expression="evaluate",
            source_ref=_dependency_source_ref(source, files["invoker"], do_invoke_symbol, "sharedRefundRules.evaluate"),
            resolution_status=SemanticResolutionStatus.RESOLVED,
        ),
        SemanticCallEdge(
            caller_symbol_id=do_invoke_symbol,
            callee_symbol_id="demo.StateDelegate#setState(java.lang.Object,java.lang.Object)",
            callee_expression="setState",
            source_ref=_dependency_source_ref(source, files["invoker"], do_invoke_symbol, "RefundOrderStateEnum.REFUND_CANCEL"),
            resolution_status=SemanticResolutionStatus.RESOLVED,
        ),
        SemanticCallEdge(
            caller_symbol_id=unrelated_symbol,
            callee_symbol_id="demo.StateDelegate#setState(java.lang.Object,java.lang.Object)",
            callee_expression="setState",
            source_ref=_dependency_source_ref(source, files["invoker"], unrelated_symbol, "OtherStateEnum.REFUND_CANCEL"),
            resolution_status=SemanticResolutionStatus.RESOLVED,
        ),
    ]
    return ScanManifest(
        scan_id="scan-deterministic-dependencies",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id="refund-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="RefundFacade#cancel",
                source_id="demo.RefundFacade#cancel",
                source_path=str(files["facade"]),
            )
        ],
        state_machines=[
            StateMachineDefinition(
                machine_id="state-machine:refund",
                system_id="refund-core",
                state_enum="RefundOrderStateEnum",
                title="退款状态机",
                transitions=[
                    StateTransition(
                        transition_id="transition:refund-cancel",
                        actor="RefundOrderCancelPostActor",
                        from_states=["PENDING_APPLY", "WAIT_REFUND", "RESHOPING", "REFUND_FAIL"],
                        to_states=["REFUND_CANCEL"],
                        source_ref=_dependency_source_ref(
                            source,
                            files["cancel_actor"],
                            "RefundOrderCancelPostActor",
                            "class RefundOrderCancelPostActor",
                        ),
                    ),
                    StateTransition(
                        transition_id="transition:refund-manual-cancel",
                        actor="RefundOrderManualCancelPostActor",
                        from_states=["AUDITED"],
                        to_states=["REFUND_CANCEL"],
                        source_ref=_dependency_source_ref(
                            source,
                            files["manual_actor"],
                            "RefundOrderManualCancelPostActor",
                            "class RefundOrderManualCancelPostActor",
                        ),
                    ),
                ],
            ),
            StateMachineDefinition(
                machine_id="state-machine:other",
                system_id="refund-core",
                state_enum="OtherStateEnum",
                title="其他状态机",
                transitions=[
                    StateTransition(
                        transition_id="transition:other-cancel",
                        actor="OtherCancelPostActor",
                        from_states=["INIT"],
                        to_states=["REFUND_CANCEL"],
                        source_ref=_dependency_source_ref(
                            source,
                            files["other_actor"],
                            "OtherCancelPostActor",
                            "class OtherCancelPostActor",
                        ),
                    )
                ],
            ),
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id="refund-core",
            methods=methods,
            call_edges=call_edges,
        ),
    )


def test_facade_business_dependencies_are_determined_by_code_scan(tmp_path: Path) -> None:
    """Facade依赖必须由可达语义边和精确状态枚举稳定确定。

    Args:
        tmp_path: Pytest隔离的源码与Manifest目录。

    Returns:
        None；两条退款取消流转和复用业务方法被选中、不可达其他状态机被排除时通过。
    """

    source = tmp_path / "source"
    files = _write_dependency_sources(source)
    manifest = _dependency_manifest(source, files)
    tracer = JavaKnowledgeTracer()

    first = tracer.business_dependency_target_ids(manifest, manifest.entries[0].entry_id)
    second = tracer.business_dependency_target_ids(manifest, manifest.entries[0].entry_id)
    shared_symbol = "demo.SharedRefundRules#evaluate(java.lang.Object)"
    shared_target = "semantic:" + hashlib.sha256(shared_symbol.encode("utf-8")).hexdigest()[:20]

    assert first == ["transition:refund-cancel", "transition:refund-manual-cancel", shared_target]
    assert second == first
    assert "transition:other-cancel" not in first


def test_facade_route_scan_uses_only_supported_dispatch_calls(tmp_path: Path) -> None:
    """Facade路由扫描应忽略普通条件枚举并覆盖目标方法内的多个execute分支。

    Args:
        tmp_path: Pytest隔离的Facade和业务路由源码根。

    Returns:
        None；两个真实派发路由被关联而条件噪声路由未进入分析时通过。
    """

    source = tmp_path / "source"
    source.mkdir()
    facade = source / "RefundFacade.java"
    implementation = source / "RefundFacadeImpl.java"
    facade.write_text("package demo; interface RefundFacade { Object cancel(Object request); }\n", encoding="utf-8")
    implementation.write_text(
        "package demo; class RefundFacadeImpl implements RefundFacade { Object cancel(Object request) {\n"
        " if (request == NoiseServiceEnum.IGNORE) return null;\n"
        " auditExecutor.execute(request, AuditServiceEnum.LOG);\n"
        " execute(request, helper(NestedServiceEnum.NOISE));\n"
        " if (request != null) return execute(request, RefundServiceEnum.CANCEL);\n"
        " return this.execute(request, RefundServiceEnum.MANUAL_CANCEL);\n"
        "} }\n",
        encoding="utf-8",
    )
    (source / "CancelValidator.java").write_text(
        "package demo;\n"
        "@TradeService(name = RefundServiceEnum.CANCEL)\n"
        "class CancelValidator {\n"
        "  void validate() {}\n"
        "}\n",
        encoding="utf-8",
    )
    (source / "ManualServiceInvoker.java").write_text(
        "package demo;\n"
        "@ApiService(name = RefundServiceEnum.MANUAL_CANCEL)\n"
        "class ManualServiceInvoker {\n"
        "  void invoke() {}\n"
        "}\n",
        encoding="utf-8",
    )
    (source / "NoiseValidator.java").write_text(
        "package demo;\n"
        "@TradeService(name = NoiseServiceEnum.IGNORE)\n"
        "class NoiseValidator {\n"
        "  void validate() {}\n"
        "}\n",
        encoding="utf-8",
    )
    (source / "AuditValidator.java").write_text(
        "package demo;\n"
        "@TradeService(name = AuditServiceEnum.LOG)\n"
        "class AuditValidator { void validate() {} }\n",
        encoding="utf-8",
    )
    (source / "NestedValidator.java").write_text(
        "package demo;\n"
        "@TradeService(name = NestedServiceEnum.NOISE)\n"
        "class NestedValidator { void validate() {} }\n",
        encoding="utf-8",
    )
    entry = EntryPoint(
        entry_id="facade:demo.RefundFacade#cancel",
        system_id="refund-core",
        kind=KnowledgeNodeKind.FACADE,
        display_name="RefundFacade#cancel",
        source_id="demo.RefundFacade#cancel",
        source_path=str(facade),
    )

    # 路由来源限定在execute参数后，目标分支的Validator与Invoker均应稳定成为种子。
    symbols = {analysis.symbol for analysis in JavaKnowledgeTracer()._facade_analyses(entry, source)}

    assert "demo.CancelValidator#validate" in symbols
    assert "demo.ManualServiceInvoker#invoke" in symbols
    assert "demo.NoiseValidator#validate" not in symbols
    assert "demo.AuditValidator#validate" not in symbols
    assert "demo.NestedValidator#validate" not in symbols


def test_facade_scan_rejects_cross_package_same_name_implementation(tmp_path: Path) -> None:
    """Facade扫描不得按文件名绑定另一个包的同名接口实现。

    Args:
        tmp_path: Pytest隔离的多包Java源码根。

    Returns:
        None；错误包Impl未成为入口分析且其路由未进入候选时通过。
    """

    source = tmp_path / "source"
    interface = source / "demo" / "RefundFacade.java"
    wrong_interface = source / "other" / "RefundFacade.java"
    wrong_implementation = source / "other" / "RefundFacadeImpl.java"
    interface.parent.mkdir(parents=True)
    wrong_interface.parent.mkdir(parents=True)
    interface.write_text(
        "package demo; public interface RefundFacade { Object cancel(Object request); }\n",
        encoding="utf-8",
    )
    wrong_interface.write_text(
        "package other; interface RefundFacade { Object cancel(Object request); }\n",
        encoding="utf-8",
    )
    wrong_implementation.write_text(
        "package other; class RefundFacadeImpl implements RefundFacade {\n"
        " Object cancel(Object request) { return execute(request, WrongServiceEnum.CANCEL); }\n"
        "}\n",
        encoding="utf-8",
    )
    entry = EntryPoint(
        entry_id="facade:demo.RefundFacade#cancel",
        system_id="refund-core",
        kind=KnowledgeNodeKind.FACADE,
        display_name="RefundFacade#cancel",
        source_id="demo.RefundFacade#cancel",
        source_path=str(interface),
    )

    # 文件名相同但implements解析为other.RefundFacade，扫描只能保留目标公开接口。
    analyses = JavaKnowledgeTracer()._facade_analyses(entry, source)

    assert len(analyses) == 1
    assert analyses[0].path == interface
    assert analyses[0].symbol == "demo.RefundFacade#cancel"


def test_semantic_seed_requires_exact_source_path_and_high_confidence(tmp_path: Path) -> None:
    """语义种子必须精确匹配模块路径并达到高置信解析门槛。

    Args:
        tmp_path: Pytest隔离的多模块同名Java源码根。

    Returns:
        None；后缀相同的另一模块和低置信方法均不会命中路由分析时通过。
    """

    source = tmp_path / "source"
    route_path = source / "module-a" / "src" / "RefundService.java"
    other_path = source / "src" / "RefundService.java"
    route_path.parent.mkdir(parents=True)
    other_path.parent.mkdir(parents=True)
    route_path.write_text("class RefundService { void cancel() {} }\n", encoding="utf-8")
    other_path.write_text("class RefundService { void cancel() {} }\n", encoding="utf-8")
    tracer = JavaKnowledgeTracer()
    route = tracer._analyze_java_file(route_path, "demo.RefundService#cancel", "cancel")
    wrong_module = SemanticMethodDefinition(
        symbol_id="other.RefundService#cancel()",
        qualified_class_name="other.RefundService",
        method_name="cancel",
        source_ref=SourceReference(path="src/RefundService.java", symbol="other.RefundService#cancel", line=1),
    )
    low_confidence = wrong_module.model_copy(
        update={
            "symbol_id": "demo.RefundService#cancel()",
            "qualified_class_name": "demo.RefundService",
            "source_ref": SourceReference(
                path="module-a/src/RefundService.java",
                symbol="demo.RefundService#cancel",
                line=1,
            ),
            "confidence": 0.5,
        }
    )

    assert not tracer._semantic_method_matches_analysis(wrong_module, route, source)
    assert not tracer._semantic_method_matches_analysis(low_confidence, route, source)


def test_set_state_target_supports_multiline_receiver_location(tmp_path: Path) -> None:
    """状态调用边落在跨行接收者时仍应从同一Java语句提取目标状态。

    Args:
        tmp_path: Pytest隔离的跨行setState源码根。

    Returns:
        None；调用边首行能够稳定映射到精确状态枚举与常量时通过。
    """

    source = tmp_path / "source"
    source.mkdir()
    invoker = source / "RefundInvoker.java"
    invoker.write_text(
        "class RefundInvoker { void cancel(Object request) {\n"
        "  orderStateDelegate\n"
        "    .setState(request,\n"
        "      RefundOrderStateEnum.REFUND_CANCEL);\n"
        "} }\n",
        encoding="utf-8",
    )
    reference = SourceReference(
        path="RefundInvoker.java",
        symbol="demo.RefundInvoker#cancel",
        line=2,
    )

    assert JavaKnowledgeTracer()._set_state_target(reference, source) == (
        "RefundOrderStateEnum",
        "REFUND_CANCEL",
    )


def test_low_confidence_semantic_dependencies_are_excluded(tmp_path: Path) -> None:
    """依赖闭包不得使用低置信方法或调用边扩展Agent候选范围。

    Args:
        tmp_path: Pytest隔离的依赖源码和Manifest。

    Returns:
        None；低置信状态边和复用方法均不再形成公共依赖时通过。
    """

    source = tmp_path / "source"
    files = _write_dependency_sources(source)
    manifest = _dependency_manifest(source, files)
    analysis = manifest.semantic_analysis
    assert analysis is not None
    low_methods = [
        method.model_copy(update={"confidence": 0.5})
        if method.qualified_class_name == "demo.SharedRefundRules"
        else method
        for method in analysis.methods
    ]
    low_edges = [
        edge.model_copy(update={"confidence": 0.5})
        if edge.callee_expression in {"evaluate", "setState"}
        else edge
        for edge in analysis.call_edges
    ]
    low_manifest = manifest.model_copy(
        update={
            "semantic_analysis": analysis.model_copy(
                update={"methods": low_methods, "call_edges": low_edges}
            )
        }
    )

    assert JavaKnowledgeTracer().business_dependency_target_ids(
        low_manifest,
        low_manifest.entries[0].entry_id,
    ) == []


def test_client_dependency_plan_skips_only_complete_current_nodes(tmp_path: Path) -> None:
    """客户端批次只跳过当前scan完整生成且没有开放问题的依赖闭包。

    Args:
        tmp_path: Pytest隔离的源码、知识真相和索引目录。

    Returns:
        None；完整依赖被引用但不重写，出现开放问题后同一闭包重新进入候选时通过。
    """

    source = tmp_path / "source"
    files = _write_dependency_sources(source)
    manifest = _dependency_manifest(source, files)
    knowledge_root = tmp_path / "knowledge"
    store = GitKnowledgeStore(knowledge_root)
    store.register_system(SystemDefinition(system_id="refund-core", name="退款核心", source_path=str(source)))
    artifacts = SourceScanArtifactStore(knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(manifest.system_id, manifest.scan_id)
    service = KnowledgeGenerationService(
        store,
        SqliteKnowledgeIndex(knowledge_root / ".opentest" / "index.sqlite"),
        artifacts,
        git_repository=FixedBaselineRepository(manifest.baseline),
    )

    initial = service._plan_client_generation_batch(manifest, manifest.entries[0].entry_id)
    cancel_batch = service.tracer.trace(manifest, "transition:refund-cancel")
    for node in cancel_batch.nodes:
        # 只有Agent推断或人工确认且绑定当前scan的全部子节点才构成可跳过的完整依赖。
        store.write_node(node.model_copy(update={"status": KnowledgeStatus.INFERRED}), cancel_batch.content_by_node[node.node_id])

    skipped = service._plan_client_generation_batch(manifest, manifest.entries[0].entry_id)
    skipped_ids = {node.node_id for node in skipped.nodes}
    assert cancel_batch.nodes[0].node_id in {edge.target_node_id for edge in skipped.edges}
    assert skipped_ids.isdisjoint({node.node_id for node in cancel_batch.nodes})
    assert len(initial.nodes) > len(skipped.nodes)

    store.write_questions(
        manifest.system_id,
        [
            KnowledgeQuestion(
                question_id="question:refund-cancel",
                system_id=manifest.system_id,
                title="取消原因是否必填",
                detail="源码无法确定产品口径。",
                affected_node_ids=[cancel_batch.nodes[0].node_id],
                status="open",
            )
        ],
    )
    reopened = service._plan_client_generation_batch(manifest, manifest.entries[0].entry_id)
    reopened_ids = {node.node_id for node in reopened.nodes}
    assert {node.node_id for node in cancel_batch.nodes}.issubset(reopened_ids)


def test_facade_trace_accepts_interface_or_implementation_and_return_assembly(tmp_path: Path) -> None:
    """Facade核心trace应接受接口/实现入口并忽略边界后的返回组装回退。

    Args:
        tmp_path: Pytest隔离的Java源码和知识服务目录。

    Returns:
        None；接口实现关系、实现直入和DAO后Service组装均通过，错误方法仍被拒绝时通过。
    """

    source = tmp_path / "source"
    source.mkdir()
    interface_path = source / "RefundFacade.java"
    implementation_path = source / "RefundFacadeImpl.java"
    invoker_path = source / "RefundCancelServiceInvoker.java"
    service_path = source / "RefundService.java"
    dao_path = source / "RefundDAO.java"
    interface_path.write_text(
        "package demo; public interface RefundFacade { Object cancel(Object request); Object refund(Object request); }\n",
        encoding="utf-8",
    )
    implementation_path.write_text(
        "package demo; public class RefundFacadeImpl implements RefundFacade {\n"
        "  RefundService service;\n"
        "  public Object cancel(Object request) { return service.cancel(request); }\n"
        "  public Object refund(Object request) { return request; }\n"
        "}\n",
        encoding="utf-8",
    )
    invoker_path.write_text(
        "package demo; public class RefundCancelServiceInvoker {\n"
        "  RefundService service;\n"
        "  public Object invoke(Object request) { return service.cancel(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    service_path.write_text(
        "package demo; public class RefundService {\n"
        "  RefundDAO refundDAO;\n"
        "  public Object cancel(Object request) { Object order = refundDAO.find(request); return assemble(order); }\n"
        "}\n",
        encoding="utf-8",
    )
    dao_path.write_text(
        "package demo; public class RefundDAO { public Object find(Object request) { return null; } }\n",
        encoding="utf-8",
    )
    refs = {
        "interface": AgentKnowledgeSourceReference(path="RefundFacade.java", symbol="demo.RefundFacade#cancel", line=1),
        "implementation": AgentKnowledgeSourceReference(path="RefundFacadeImpl.java", symbol="demo.RefundFacadeImpl#cancel", line=3),
        "invoker": AgentKnowledgeSourceReference(path="RefundCancelServiceInvoker.java", symbol="demo.RefundCancelServiceInvoker#invoke", line=3),
        "service": AgentKnowledgeSourceReference(path="RefundService.java", symbol="demo.RefundService#cancel", line=3),
        "dao": AgentKnowledgeSourceReference(path="RefundDAO.java", symbol="demo.RefundDAO#find", line=1),
    }
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#cancel",
        system_id="refund-core",
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#cancel",
        source_refs=[SourceReference.model_validate(refs["implementation"].model_dump())],
        status=KnowledgeStatus.CODE_VERIFIED,
    )
    request = KnowledgeGenerationBatchRequest(
        system_id="refund-core",
        target_ids=["facade:demo.RefundFacade#cancel"],
        agent="codex",
        confirmed=True,
    )
    steps = [
        {"sequence": 1, "role": "entry", "source_ref": refs["interface"], "summary": "公开取消入口。"},
        {"sequence": 2, "role": "entry", "source_ref": refs["implementation"], "summary": "进入取消实现。"},
        {"sequence": 3, "role": "service", "source_ref": refs["service"], "summary": "执行取消业务。"},
        {"sequence": 4, "role": "data_access", "source_ref": refs["dao"], "summary": "读取退票单。"},
        {"sequence": 5, "role": "service", "source_ref": refs["service"], "summary": "组装取消结果。"},
    ]
    envelope = AgentKnowledgeEnvelope(
        status="completed",
        system_id="refund-core",
        target_ids=request.target_ids,
        summaries=[{"node_id": node.node_id, "summary": "取消退票单并返回结果。"}],
        questions=[],
        source_refs=list(refs.values()),
        trace_steps=steps,
    )
    knowledge_root = tmp_path / "knowledge"
    service = KnowledgeGenerationService(
        GitKnowledgeStore(knowledge_root),
        SqliteKnowledgeIndex(knowledge_root / ".opentest" / "index.sqlite"),
        SourceScanArtifactStore(knowledge_root),
    )
    source_lines = {
        path.name: path.read_text(encoding="utf-8").splitlines()
        for path in (interface_path, implementation_path, invoker_path, service_path, dao_path)
    }

    service._validate_agent_trace(request, [node], envelope)
    service._validate_agent_trace_links(envelope, source_lines)
    implementation_envelope = envelope.model_copy(update={"trace_steps": envelope.trace_steps[1:]})
    implementation_envelope = implementation_envelope.model_copy(
        update={
            "trace_steps": [
                step.model_copy(update={"sequence": index})
                for index, step in enumerate(implementation_envelope.trace_steps, start=1)
            ]
        }
    )
    service._validate_agent_trace(request, [node], implementation_envelope)
    service._validate_agent_trace_links(implementation_envelope, source_lines)

    route_node = KnowledgeNode(
        node_id="logic:demo.RefundCancelServiceInvoker#invoke",
        system_id="refund-core",
        kind=KnowledgeNodeKind.COMMON_LOGIC,
        title="RefundCancelServiceInvoker#invoke",
        source_refs=[SourceReference.model_validate(refs["invoker"].model_dump())],
        status=KnowledgeStatus.CODE_VERIFIED,
    )
    routed_steps = [
        envelope.trace_steps[0],
        envelope.trace_steps[0].model_copy(
            update={"sequence": 2, "role": "invoker", "source_ref": refs["invoker"]}
        ),
        envelope.trace_steps[2].model_copy(update={"sequence": 3}),
        envelope.trace_steps[3].model_copy(update={"sequence": 4}),
    ]
    routed_envelope = envelope.model_copy(update={"trace_steps": routed_steps})
    # 公开接口到扫描固化的ServiceInvoker由execute路由证明，之后仍要求真实直接调用。
    service._validate_agent_trace(request, [node, route_node], routed_envelope)
    service._validate_agent_trace_links(routed_envelope, source_lines, [node, route_node])

    wrong_reference = AgentKnowledgeSourceReference(
        path="RefundFacade.java",
        symbol="demo.RefundFacade#refund",
        line=1,
    )
    wrong_envelope = envelope.model_copy(
        update={
            "source_refs": [wrong_reference, *list(refs.values())[1:]],
            "trace_steps": [
                envelope.trace_steps[0].model_copy(update={"source_ref": wrong_reference}),
                *envelope.trace_steps[1:],
            ],
        }
    )
    with pytest.raises(KnowledgeValidationError, match="requested entry"):
        service._validate_agent_trace(request, [node], wrong_envelope)

    other_package_reference = AgentKnowledgeSourceReference(
        path="other/RefundFacade.java",
        symbol="other.RefundFacade#cancel",
        line=1,
    )
    other_package_envelope = envelope.model_copy(
        update={
            "source_refs": [other_package_reference, *list(refs.values())[1:]],
            "trace_steps": [
                envelope.trace_steps[0].model_copy(update={"source_ref": other_package_reference}),
                *envelope.trace_steps[1:],
            ],
        }
    )
    # 全限定请求不能由其他包的同名Facade满足，即使方法名和简单类名完全一致。
    with pytest.raises(KnowledgeValidationError, match="requested entry"):
        service._validate_agent_trace(request, [node], other_package_envelope)

    unrelated_service_reference = AgentKnowledgeSourceReference(
        path="OtherRefundService.java",
        symbol="demo.OtherRefundService#assemble",
        line=1,
    )
    unrelated_return_envelope = envelope.model_copy(
        update={
            "source_refs": [*list(refs.values()), unrelated_service_reference],
            "trace_steps": [
                *envelope.trace_steps[:4],
                envelope.trace_steps[4].model_copy(
                    update={"source_ref": unrelated_service_reference}
                ),
            ],
        }
    )
    # 数据边界后的返回步骤只能回放核心路径已出现的Service或Invoker。
    with pytest.raises(KnowledgeValidationError, match="unrelated return stage"):
        service._validate_agent_trace(request, [node], unrelated_return_envelope)

    false_boundary_envelope = envelope.model_copy(
        update={
            "trace_steps": [
                *envelope.trace_steps[:3],
                envelope.trace_steps[3].model_copy(
                    update={"source_ref": refs["service"]}
                ),
            ]
        }
    )
    # data_access标签不能把普通Service包装方法伪装为DAO/Mapper/Repository边界。
    with pytest.raises(KnowledgeValidationError, match="real DAO/Mapper/Repository boundary"):
        service._validate_agent_trace(request, [node], false_boundary_envelope)

    wrong_impl_path = source / "other" / "RefundFacadeImpl.java"
    wrong_impl_path.parent.mkdir()
    wrong_impl_path.write_text(
        "package other; interface RefundFacade { Object cancel(Object request); }\n"
        "class RefundFacadeImpl implements RefundFacade { public Object cancel(Object request) { return request; } }\n",
        encoding="utf-8",
    )
    wrong_impl_reference = AgentKnowledgeSourceReference(
        path="other/RefundFacadeImpl.java",
        symbol="RefundFacadeImpl#cancel",
        line=2,
    )
    wrong_impl_envelope = envelope.model_copy(
        update={
            "source_refs": [refs["interface"], wrong_impl_reference, refs["service"], refs["dao"]],
            "trace_steps": [
                envelope.trace_steps[0],
                envelope.trace_steps[1].model_copy(update={"source_ref": wrong_impl_reference}),
                envelope.trace_steps[2],
                envelope.trace_steps[3],
            ],
        }
    )
    source_lines[wrong_impl_reference.path] = wrong_impl_path.read_text(encoding="utf-8").splitlines()
    # Agent使用简称时仍须按源码package解析接口身份，other包同名Impl不能冒充demo入口实现。
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(wrong_impl_envelope, source_lines)


def test_facade_trace_accepts_service_interface_to_declared_implementation(tmp_path: Path) -> None:
    """依赖注入调用可由Service接口连续过渡到其明确implements实现。

    Args:
        tmp_path: Pytest隔离的Facade、Service接口实现和DAO源码根。

    Returns:
        None；接口声明、实现关系和DAO调用形成连续核心trace时通过。
    """

    source = tmp_path / "source"
    source.mkdir()
    files = {
        "facade": source / "RefundFacadeImpl.java",
        "service_interface": source / "OrderService.java",
        "service_implementation": source / "OrderServiceImpl.java",
        "dao": source / "RefundOrderDAO.java",
    }
    files["facade"].write_text(
        "package demo; class RefundFacadeImpl {\n"
        " OrderService orderService; Object cancel(Object request) { return orderService.query(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    files["service_interface"].write_text(
        "package demo; interface OrderService { Object query(Object request); }\n",
        encoding="utf-8",
    )
    files["service_implementation"].write_text(
        "package demo; class OrderServiceImpl implements OrderService {\n"
        " RefundOrderDAO dao; public Object query(Object request) { return dao.find(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    files["dao"].write_text(
        "package demo; class RefundOrderDAO { Object find(Object request) { return null; } }\n",
        encoding="utf-8",
    )
    references = {
        "facade": AgentKnowledgeSourceReference(
            path="RefundFacadeImpl.java", symbol="demo.RefundFacadeImpl#cancel", line=2
        ),
        "service_interface": AgentKnowledgeSourceReference(
            path="OrderService.java", symbol="demo.OrderService#query", line=1
        ),
        "service_implementation": AgentKnowledgeSourceReference(
            path="OrderServiceImpl.java", symbol="demo.OrderServiceImpl#query", line=2
        ),
        "dao": AgentKnowledgeSourceReference(
            path="RefundOrderDAO.java", symbol="demo.RefundOrderDAO#find", line=1
        ),
    }
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#cancel",
        system_id="refund-core",
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#cancel",
        source_refs=[SourceReference.model_validate(references["facade"].model_dump())],
        status=KnowledgeStatus.CODE_VERIFIED,
    )
    request = KnowledgeGenerationBatchRequest(
        system_id="refund-core",
        target_ids=["facade:demo.RefundFacade#cancel"],
        agent="codex",
        confirmed=True,
    )
    trace_steps = [
        {"sequence": 1, "role": "entry", "source_ref": references["facade"], "summary": "取消入口。"},
        {
            "sequence": 2,
            "role": "service",
            "source_ref": references["service_interface"],
            "summary": "订单查询接口。",
        },
        {
            "sequence": 3,
            "role": "service",
            "source_ref": references["service_implementation"],
            "summary": "订单查询实现。",
        },
        {"sequence": 4, "role": "data_access", "source_ref": references["dao"], "summary": "订单DAO。"},
    ]
    envelope = AgentKnowledgeEnvelope(
        status="completed",
        system_id="refund-core",
        target_ids=request.target_ids,
        summaries=[{"node_id": node.node_id, "summary": "取消前读取退票订单。"}],
        questions=[],
        source_refs=list(references.values()),
        trace_steps=trace_steps,
    )
    service = KnowledgeGenerationService(
        GitKnowledgeStore(tmp_path / "knowledge"),
        SqliteKnowledgeIndex(tmp_path / "knowledge" / ".opentest" / "index.sqlite"),
        SourceScanArtifactStore(tmp_path / "knowledge"),
    )
    source_lines = {
        path.name: path.read_text(encoding="utf-8").splitlines()
        for path in files.values()
    }

    service._validate_agent_trace(request, [node], envelope)
    service._validate_agent_trace_links(envelope, source_lines)


def test_dynamic_facade_route_requires_code_scanned_handler_even_when_skipped(tmp_path: Path) -> None:
    """动态枚举路由只接受绑定scan确认的处理器，且已生成处理器仍保留在允许集合。

    Args:
        tmp_path: Pytest隔离的Facade路由、处理器、Service和DAO源码根。

    Returns:
        None；跳过生成的真实Invoker可通过，同注解伪Invoker被拒绝时通过。
    """

    source = tmp_path / "source"
    source.mkdir()
    facade_interface = source / "RefundFacade.java"
    facade_implementation = source / "RefundFacadeImpl.java"
    real_invoker = source / "RefundCancelServiceInvoker.java"
    rogue_invoker = source / "RogueCancelService.java"
    service_path = source / "RefundService.java"
    dao_path = source / "RefundDAO.java"
    facade_interface.write_text(
        "package demo; interface RefundFacade { Object cancel(Object request); }\n",
        encoding="utf-8",
    )
    facade_implementation.write_text(
        "package demo; class RefundFacadeImpl implements RefundFacade {\n"
        " Object cancel(Object request) { return execute(request, RefundServiceEnum.CANCEL); }\n"
        "}\n",
        encoding="utf-8",
    )
    real_invoker.write_text(
        "package demo; @TradeService(name = RefundServiceEnum.CANCEL)\n"
        "class RefundCancelServiceInvoker { RefundService service; Object invoke(Object request) { return service.cancel(request); } }\n",
        encoding="utf-8",
    )
    rogue_invoker.write_text(
        "package demo; @TradeService(name = RefundServiceEnum.CANCEL)\n"
        "class RogueCancelService { RefundService service; Object invoke(Object request) { return service.cancel(request); } }\n",
        encoding="utf-8",
    )
    service_path.write_text(
        "package demo; class RefundService { RefundDAO dao; Object cancel(Object request) { return dao.find(request); } }\n",
        encoding="utf-8",
    )
    dao_path.write_text(
        "package demo; class RefundDAO { Object find(Object request) { return null; } }\n",
        encoding="utf-8",
    )
    target_id = "facade:demo.RefundFacade#cancel"
    manifest = ScanManifest(
        scan_id="scan-route-allow-list",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=target_id,
                system_id="refund-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="RefundFacade#cancel",
                source_id="demo.RefundFacade#cancel",
                source_path=str(facade_interface),
            )
        ],
    )
    knowledge_root = tmp_path / "knowledge"
    generation_service = KnowledgeGenerationService(
        GitKnowledgeStore(knowledge_root),
        SqliteKnowledgeIndex(knowledge_root / ".opentest" / "index.sqlite"),
        SourceScanArtifactStore(knowledge_root),
    )
    full_batch = generation_service.tracer.trace(manifest, target_id)
    main_node = full_batch.nodes[0]
    request = KnowledgeGenerationBatchRequest(
        system_id="refund-core", target_ids=[target_id], agent="codex", confirmed=True
    )
    # candidate_nodes仅含主接口，模拟真实Invoker已完整发布而被本轮生成范围跳过。
    validation_nodes = generation_service._agent_trace_validation_nodes(manifest, request, [main_node])
    references = {
        "entry": AgentKnowledgeSourceReference(
            path="RefundFacadeImpl.java", symbol="demo.RefundFacadeImpl#cancel", line=2
        ),
        "real": AgentKnowledgeSourceReference(
            path="RefundCancelServiceInvoker.java", symbol="demo.RefundCancelServiceInvoker#invoke", line=2
        ),
        "rogue": AgentKnowledgeSourceReference(
            path="RogueCancelService.java", symbol="demo.RogueCancelService#invoke", line=2
        ),
        "service": AgentKnowledgeSourceReference(
            path="RefundService.java", symbol="demo.RefundService#cancel", line=1
        ),
        "dao": AgentKnowledgeSourceReference(path="RefundDAO.java", symbol="demo.RefundDAO#find", line=1),
    }
    base_steps = [
        {"sequence": 1, "role": "entry", "source_ref": references["entry"], "summary": "取消入口。"},
        {"sequence": 2, "role": "invoker", "source_ref": references["real"], "summary": "取消路由。"},
        {"sequence": 3, "role": "service", "source_ref": references["service"], "summary": "取消服务。"},
        {"sequence": 4, "role": "data_access", "source_ref": references["dao"], "summary": "退票DAO。"},
    ]
    envelope = AgentKnowledgeEnvelope(
        status="completed",
        system_id="refund-core",
        target_ids=[target_id],
        summaries=[{"node_id": main_node.node_id, "summary": "取消退票单。"}],
        questions=[],
        source_refs=list(references.values()),
        trace_steps=base_steps,
    )
    source_lines = {
        path.name: path.read_text(encoding="utf-8").splitlines()
        for path in (
            facade_interface,
            facade_implementation,
            real_invoker,
            rogue_invoker,
            service_path,
            dao_path,
        )
    }

    assert any(node.node_id.endswith("RefundCancelServiceInvoker#invoke") for node in validation_nodes)
    generation_service._validate_agent_trace(request, validation_nodes, envelope)
    generation_service._validate_agent_trace_links(envelope, source_lines, validation_nodes)

    rogue_envelope = envelope.model_copy(
        update={
            "trace_steps": [
                envelope.trace_steps[0],
                envelope.trace_steps[1].model_copy(update={"source_ref": references["rogue"]}),
                *envelope.trace_steps[2:],
            ]
        }
    )
    # 相同枚举注解不能让Agent自选未被扫描纳入的普通Service作为动态路由目标。
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        generation_service._validate_agent_trace_links(
            rogue_envelope,
            source_lines,
            validation_nodes,
        )


def test_facade_method_annotation_braces_do_not_truncate_business_body(tmp_path: Path) -> None:
    """监控注解数组不得抢占同名Facade方法的方法体边界。

    Args:
        tmp_path: Pytest提供的隔离源码目录。

    Returns:
        None；入口摘要能识别真实返回阶段即通过。
    """

    # 同名文本和数组花括号都位于真实声明之前，用于复现原批量任务截断条件。
    source = tmp_path / "source"
    source.mkdir()
    facade = source / "OuterRefundFacade.java"
    implementation = source / "OuterRefundFacadeImpl.java"
    facade.write_text(
        "package demo; interface OuterRefundFacade { Object pageBusinessLog(Object request); }\n",
        encoding="utf-8",
    )
    implementation.write_text(
        "package demo; class OuterRefundFacadeImpl implements OuterRefundFacade {\n"
        " @Indicator(name = \"pageBusinessLog\", rtScopes = { @Scope(from = 0, to = 1) })\n"
        " public Object pageBusinessLog(Object request) {\n"
        "  try { return this.execute(request); } catch (RuntimeException error) { return failed(error); }\n"
        " }\n"
        "}\n",
        encoding="utf-8",
    )
    source_id = "demo.OuterRefundFacade#pageBusinessLog"
    manifest = ScanManifest(
        scan_id="scan-20260822000000-annotation-braces",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id="refund-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="退票业务日志查询",
                source_id=source_id,
                source_path=str(facade),
            )
        ],
    )

    # 追踪结果必须来自第三行真实方法声明，而不是第二行监控注解。
    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)

    assert "可观察业务阶段" in batch.nodes[0].summary
    assert "this.execute(request)" in batch.content_by_node[batch.nodes[0].node_id]
    assert batch.nodes[0].source_refs[0].line == 3


def test_method_locator_skips_earlier_call_and_parameter_annotation_array(tmp_path: Path) -> None:
    """更早调用点和参数注解数组不得替代目标Facade方法声明。

    Args:
        tmp_path: Pytest提供的隔离Facade源码目录。

    Returns:
        None；正文与行号均来自真实目标声明即通过。
    """

    # 第一处同名marker是调用，真实声明参数又包含数组花括号，覆盖两个历史误截断边界。
    source = tmp_path / "source"
    source.mkdir()
    facade = source / "OuterRefundFacade.java"
    implementation = source / "OuterRefundFacadeImpl.java"
    facade.write_text(
        "package demo; interface OuterRefundFacade { Object pageBusinessLog(Object request); }\n",
        encoding="utf-8",
    )
    implementation.write_text(
        "package demo; class OuterRefundFacadeImpl implements OuterRefundFacade {\n"
        " Object wrapper() { return pageBusinessLog(null); }\n"
        " public Object pageBusinessLog(@Scope(values = {\"A\", \"B\"}) Object request) {\n"
        "  return actualBusinessLog(request);\n"
        " }\n"
        "}\n",
        encoding="utf-8",
    )
    source_id = "demo.OuterRefundFacade#pageBusinessLog"
    manifest = ScanManifest(
        scan_id="scan-20260823000000-call-before-declaration",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id="refund-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="退票业务日志查询",
                source_id=source_id,
                source_path=str(facade),
            )
        ],
    )

    # 追踪器必须越过第二行调用，并在参数括号配平后才寻找第三行方法体。
    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)
    content = batch.content_by_node[batch.nodes[0].node_id]

    assert "actualBusinessLog(request)" in content
    assert "pageBusinessLog(null)" not in content
    assert batch.nodes[0].source_refs[0].line == 3


def test_method_locator_rejects_lambda_comparison_and_explicit_generic_calls(tmp_path: Path) -> None:
    """以大于号结尾的三类表达式调用不得冒充泛型返回类型声明。

    Args:
        tmp_path: Pytest提供的隔离Facade源码目录。

    Returns:
        None；三处更早调用均被跳过且正文绑定真实声明即通过。
    """

    # Lambda箭头、比较运算和显式泛型调用都包含`>`，但全部位于方法体深度而非类型成员深度。
    source = tmp_path / "source"
    source.mkdir()
    facade = source / "OuterRefundFacade.java"
    implementation = source / "OuterRefundFacadeImpl.java"
    facade.write_text(
        "package demo; interface OuterRefundFacade { Object pageBusinessLog(Object request); }\n",
        encoding="utf-8",
    )
    implementation.write_text(
        "package demo; class OuterRefundFacadeImpl implements OuterRefundFacade {\n"
        " Object lambdaCall() { return stream.map(x -> pageBusinessLog(x)); }\n"
        " boolean comparisonCall() { return amount > pageBusinessLog(null); }\n"
        " Object genericCall() { return this.<Object>pageBusinessLog(null); }\n"
        " public Object pageBusinessLog(Object request) { return actualBusinessLog(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    source_id = "demo.OuterRefundFacade#pageBusinessLog"
    manifest = ScanManifest(
        scan_id="scan-20260823000000-greater-than-calls",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id="refund-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="退票业务日志查询",
                source_id=source_id,
                source_path=str(facade),
            )
        ],
    )

    # 声明深度门禁应越过前三个表达式，并固定到第五行目标方法。
    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)
    content = batch.content_by_node[batch.nodes[0].node_id]

    assert "actualBusinessLog(request)" in content
    assert "stream.map" not in content
    assert batch.nodes[0].source_refs[0].line == 5


def test_empty_update_facade_does_not_treat_declaration_as_side_effect(tmp_path: Path) -> None:
    """空update方法的声明名称不得冒充真实更新副作用。

    Args:
        tmp_path: Pytest提供的隔离Facade源码目录。

    Returns:
        None；只生成最小入口节点且副作用保持未证明即通过。
    """

    # 方法名刻意命中副作用关键词，正文为空才能证明声明与调用已分离。
    source = tmp_path / "source"
    source.mkdir()
    facade = source / "RefundFacade.java"
    implementation = source / "RefundFacadeImpl.java"
    facade.write_text("interface RefundFacade { void update(); }\n", encoding="utf-8")
    implementation.write_text("class RefundFacadeImpl { public void update() {} }\n", encoding="utf-8")
    source_id = "demo.RefundFacade#update"
    manifest = ScanManifest(
        scan_id="scan-20260823000000-empty-update",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id="refund-core",
                kind=KnowledgeNodeKind.FACADE,
                display_name="更新退票信息",
                source_id=source_id,
                source_path=str(facade),
            )
        ],
    )

    # 空正文应落到最小事实，不得生成update共享节点或副作用计数。
    batch = JavaKnowledgeTracer().trace(manifest, manifest.entries[0].entry_id)

    assert len(batch.nodes) == 1
    assert batch.nodes[0].summary.startswith("当前源码仅能证明")
    assert "产生1项状态或数据副作用" not in batch.nodes[0].summary


def test_state_actor_constructor_does_not_replace_type_body(tmp_path: Path) -> None:
    """状态Actor显式构造器不得缩短类型正文或生成构造器共享节点。

    Args:
        tmp_path: Pytest提供的隔离状态Actor源码目录。

    Returns:
        None；状态分支和保存副作用被识别且没有构造器节点即通过。
    """

    # Actor在业务方法前声明构造器，类型模式必须继续分析整个类体。
    source = tmp_path / "source"
    source.mkdir()
    actor = source / "RefundActor.java"
    actor.write_text(
        "class RefundActor {\n"
        " public RefundActor() {}\n"
        " void onEnter() { if (ready) { saveOrder(); } }\n"
        "}\n",
        encoding="utf-8",
    )
    transition = StateTransition(
        transition_id="transition:refund-ready",
        actor="RefundActor",
        from_states=["INIT"],
        to_states=["READY"],
        source_ref=SourceReference(path="RefundActor.java", symbol="RefundActor", line=1),
    )
    manifest = ScanManifest(
        scan_id="scan-20260823000000-actor-constructor",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        state_machines=[
            StateMachineDefinition(
                machine_id="state-machine:refund",
                system_id="refund-core",
                state_enum="RefundState",
                title="退票状态机",
                transitions=[transition],
            )
        ],
    )

    # 状态目标必须保留构造器之后的条件和保存副作用，且只产生真实状态节点。
    batch = JavaKnowledgeTracer().trace(manifest, transition.transition_id)

    assert len(batch.nodes) == 1
    assert "条件分支" in batch.nodes[0].summary
    assert "状态或数据副作用" in batch.nodes[0].summary
    assert all("RefundActor#RefundActor" not in node.node_id for node in batch.nodes)


def test_entry_without_detectable_behavior_generates_minimal_code_fact(tmp_path: Path) -> None:
    """合法透传入口缺少可提取维度时生成最小事实且不制造业务口径问题。

    Args:
        tmp_path: Pytest提供的隔离源码目录。

    Returns:
        None；追踪不抛错、声明代码证据边界且问题为空即通过。
    """

    # 空方法刻意不提供分支、调用和副作用，验证最小事实不会制造共享逻辑。
    source = tmp_path / "source"
    source.mkdir()
    job = source / "NoopJob.java"
    job.write_text("class NoopJob { void execute() {} }\n", encoding="utf-8")
    entry_id = "job:demo.NoopJob"
    manifest = ScanManifest(
        scan_id="scan-20260822000000-minimal-entry",
        system_id="refund-core",
        baseline=SourceBaseline(source_path=str(source), commit="abc123"),
        entries=[
            EntryPoint(
                entry_id=entry_id,
                system_id="refund-core",
                kind=KnowledgeNodeKind.JOB,
                display_name="空任务入口",
                source_id="demo.NoopJob",
                source_path=str(job),
            )
        ],
    )

    # 浅层源码只发布证据边界，是否需要提问由指定Agent结合业务背景判断。
    batch = JavaKnowledgeTracer().trace(manifest, entry_id)

    assert len(batch.nodes) == 1
    assert batch.nodes[0].status == KnowledgeStatus.CODE_VERIFIED
    assert batch.nodes[0].summary.startswith("当前源码仅能证明")
    assert batch.questions == []


def test_generation_preserves_manual_content_and_answered_questions(tmp_path: Path) -> None:
    """重复发布应刷新自动证据，同时保留人工正文、答案和确认状态。"""

    service, store, manifest = _knowledge_service(tmp_path)
    request = KnowledgeGenerationRequest(
        system_id=manifest.system_id,
        entry_id=manifest.entries[0].entry_id,
    )
    first_batch = service.generate(request)
    hk_node = next(node for node in first_batch.nodes if node.node_id == "rule:create-order:hk-payment-verify")
    node_path = store.node_path(hk_node)
    node_path.write_text(node_path.read_text(encoding="utf-8") + "\n人工口径：异常需要记录风险。\n", encoding="utf-8")
    confirmation = KnowledgeConfirmation(
        question_id="question:create-order:hk-verify-exception",
        answer="当前是兼容性容错，但必须保留风险证据。",
        confirmed_node_ids=[hk_node.node_id],
    )
    service.confirm(manifest.system_id, confirmation)

    second_batch = service.generate(request)
    regenerated = next(node for node in second_batch.nodes if node.node_id == hk_node.node_id)
    questions = {item.question_id: item for item in store.list_questions(manifest.system_id)}
    document = node_path.read_text(encoding="utf-8")
    assert regenerated.status == KnowledgeStatus.USER_CONFIRMED
    assert "人工口径：异常需要记录风险。" in document
    assert questions[confirmation.question_id].status == "answered"
    assert questions[confirmation.question_id].answer == confirmation.answer


def test_direct_generation_preserves_formal_entry_facts_only_for_exact_source_generation(
    tmp_path: Path,
) -> None:
    """直接知识重生成只可在同scan和baseline保留已确认结构化入口事实。

    Args:
        tmp_path: Pytest隔离的知识、扫描与源码目录。

    Returns:
        None；同代重建保留正式Fact，新源码代际不继承时通过。

    Side Effects:
        只写临时知识资产和两个不可变扫描Manifest，不访问QA。
    """

    service, store, manifest = _knowledge_service(tmp_path)
    request = KnowledgeGenerationRequest(
        system_id=manifest.system_id,
        entry_id=manifest.entries[0].entry_id,
    )
    first_batch = service.generate(request)
    entry_node = next(
        node for node in first_batch.nodes if node.kind == KnowledgeNodeKind.FACADE
    )
    formal_entry_id = entry_node.aliases[0]
    evidence = entry_node.source_refs[0]
    assertion = EntryFactAssertion(
        assertion_id="entry-fact:generic-required-order",
        assertion_type="REQUIRES_FACT",
        slot_id="ticket_order",
        fact_contract_id="ticket-order/v1",
        required_state="ISSUED",
        acquisition_policy="QUERY_ONLY",
        source=KnowledgeConclusionSource.USER_CONFIRMED,
        evidence_refs=[evidence],
    )
    formal = EntryFactKnowledge(
        entry_id=formal_entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        requires_facts=[assertion],
        evidence_refs=[evidence],
    )
    confirmed = entry_node.model_copy(
        update={
            "status": KnowledgeStatus.USER_CONFIRMED,
            "entry_fact_knowledge": formal,
        }
    )
    store.write_node(confirmed, "已确认的结构化入口事实。")

    same_generation = service.generate(request)
    same_entry = next(node for node in same_generation.nodes if node.node_id == entry_node.node_id)
    assert same_entry.entry_fact_knowledge == formal

    new_baseline = manifest.baseline.model_copy(update={"commit": "def456"})
    new_manifest = manifest.model_copy(
        update={
            "scan_id": "scan-20260827000000-def456-test",
            "baseline": new_baseline,
        }
    )
    service.artifacts.write_manifest(new_manifest)
    service.artifacts.publish_latest(new_manifest.system_id, new_manifest.scan_id)
    service.git_repository = FixedBaselineRepository(new_baseline)
    new_generation = service.generate(
        request.model_copy(update={"scan_id": new_manifest.scan_id})
    )
    new_entry = next(node for node in new_generation.nodes if node.node_id == entry_node.node_id)
    assert new_entry.entry_fact_knowledge is None


def test_entry_fact_candidates_require_exact_confirmation_and_survive_auto_publish(
    tmp_path: Path,
) -> None:
    """自动发布不得升级AI候选，逐ID确认也不得连带发布同草稿兄弟项。

    Args:
        tmp_path: Pytest隔离的知识、扫描、Fact契约和草稿目录。

    Returns:
        None；正式节点只含精确确认断言且未选候选仍隔离保留时通过。

    Side Effects:
        仅在临时知识库发布通用入口节点并确认一条typed候选，不访问QA。
    """

    service, store, manifest, batch, required, produced = (
        _entry_fact_confirmation_fixture(tmp_path)
    )
    service.publish_ready_drafts(manifest.system_id, batch.batch_id)
    published_node = next(
        node
        for node, _path, _body in store.list_nodes(manifest.system_id)
        if node.node_id == batch.drafts[0].node.node_id
    )
    assert published_node.entry_fact_knowledge is None
    node_path = store.node_path(published_node)
    node_path.write_text(
        node_path.read_text(encoding="utf-8") + "\n人工确认说明：保留既有业务口径。\n",
        encoding="utf-8",
    )

    confirmed = service.confirm_entry_fact_candidates(
        manifest.system_id,
        batch.batch_id,
        EntryFactCandidateConfirmation(
            draft_id=batch.drafts[0].draft_id,
            fact_candidate_ids=[required.assertion_id],
        ),
    )
    assert confirmed.entry_fact_knowledge is not None
    assert [
        assertion.assertion_id
        for assertion in confirmed.entry_fact_knowledge.requires_facts
    ] == [required.assertion_id]
    assert confirmed.entry_fact_knowledge.produces_facts == []
    assert confirmed.entry_fact_knowledge.requires_facts[0].source == (
        KnowledgeConclusionSource.USER_CONFIRMED
    )
    confirmed_document = node_path.read_text(encoding="utf-8")
    assert confirmed_document.count(AUTO_START) == 1
    assert confirmed_document.count(AUTO_END) == 1
    assert "人工确认说明：保留既有业务口径。" in confirmed_document
    remaining_batch = store.read_draft_batch(manifest.system_id, batch.batch_id)
    remaining_candidates = remaining_batch.drafts[0].entry_fact_candidates
    assert remaining_candidates is not None
    assert [item.assertion_id for item in remaining_candidates.assertions] == [
        produced.assertion_id
    ]

    with pytest.raises(
        KnowledgeValidationError,
        match="unknown candidates",
    ):
        service.confirm_entry_fact_candidates(
            manifest.system_id,
            batch.batch_id,
            EntryFactCandidateConfirmation(
                draft_id=batch.drafts[0].draft_id,
                fact_candidate_ids=["entry-fact:generic-unknown-candidate"],
            ),
        )


def test_entry_fact_confirmation_replaces_only_exact_same_target_assertions(
    tmp_path: Path,
) -> None:
    """逐Fact确认可以迁移同一业务槽位，同时保留无关正式事实和兄弟候选。

    Args:
        tmp_path: Pytest隔离的知识、扫描、Fact契约和草稿目录。

    Returns:
        None；旧断言被精确替换、其他候选仍隔离且跨目标删除被拒绝时通过。

    Side Effects:
        仅在临时知识库确认两次typed候选，不访问AI或QA。
    """

    service, store, manifest, batch, required, produced = (
        _entry_fact_confirmation_fixture(tmp_path)
    )
    service.publish_ready_drafts(manifest.system_id, batch.batch_id)
    service.confirm_entry_fact_candidates(
        manifest.system_id,
        batch.batch_id,
        EntryFactCandidateConfirmation(
            draft_id=batch.drafts[0].draft_id,
            fact_candidate_ids=[required.assertion_id],
        ),
    )
    remaining_batch = store.read_draft_batch(manifest.system_id, batch.batch_id)
    remaining_draft = remaining_batch.drafts[0]
    replacement = required.model_copy(
        update={
            "assertion_id": "entry-fact:generic-ticket-required-v2",
            "acquisition_policy": "QUERY_THEN_CREATE",
        }
    )
    replacement_candidates = remaining_draft.entry_fact_candidates.model_copy(
        update={"assertions": [replacement, produced]}
    )
    store.write_draft_batch(
        remaining_batch.model_copy(
            update={
                "drafts": [
                    remaining_draft.model_copy(
                        update={"entry_fact_candidates": replacement_candidates}
                    )
                ]
            }
        )
    )

    # 替换命令只删除同slot旧断言，并把新结论按本次用户确认来源发布。
    migrated = service.confirm_entry_fact_candidates(
        manifest.system_id,
        batch.batch_id,
        EntryFactCandidateConfirmation(
            draft_id=batch.drafts[0].draft_id,
            fact_candidate_ids=[replacement.assertion_id],
            replacements=[
                EntryFactCandidateReplacement(
                    candidate_assertion_id=replacement.assertion_id,
                    superseded_assertion_ids=[required.assertion_id],
                )
            ],
        ),
    )
    formal_requirements = migrated.entry_fact_knowledge.requires_facts
    assert [item.assertion_id for item in formal_requirements] == [
        replacement.assertion_id
    ]
    assert formal_requirements[0].acquisition_policy == "QUERY_THEN_CREATE"
    remaining_candidates = store.read_draft_batch(
        manifest.system_id,
        batch.batch_id,
    ).drafts[0].entry_fact_candidates
    assert remaining_candidates is not None
    assert [item.assertion_id for item in remaining_candidates.assertions] == [
        produced.assertion_id
    ]

    invalid_batch = store.read_draft_batch(manifest.system_id, batch.batch_id)
    invalid_draft = invalid_batch.drafts[0]
    with pytest.raises(
        KnowledgeValidationError,
        match="preserve the semantic assertion target",
    ):
        service.confirm_entry_fact_candidates(
            manifest.system_id,
            batch.batch_id,
            EntryFactCandidateConfirmation(
                draft_id=invalid_draft.draft_id,
                fact_candidate_ids=[produced.assertion_id],
                replacements=[
                    EntryFactCandidateReplacement(
                        candidate_assertion_id=produced.assertion_id,
                        superseded_assertion_ids=[replacement.assertion_id],
                    )
                ],
            ),
        )


def test_entry_fact_confirmation_code_proof_basis_fails_closed(
    tmp_path: Path,
) -> None:
    """显式CODE_PROOF_REQUIRED不能把仅有AI引用的候选升级为正式事实。

    Args:
        tmp_path: Pytest隔离的知识、扫描、Fact契约和草稿目录。

    Returns:
        None；缺少完整程序证明的候选仍保留隔离时通过。

    Side Effects:
        只尝试发布临时候选，不访问AI或QA，也不改正式入口事实。
    """

    service, store, manifest, batch, required, _produced = (
        _entry_fact_confirmation_fixture(tmp_path)
    )
    service.publish_ready_drafts(manifest.system_id, batch.batch_id)

    with pytest.raises(
        KnowledgeValidationError,
        match="lack complete code proof",
    ):
        service.confirm_entry_fact_candidates(
            manifest.system_id,
            batch.batch_id,
            EntryFactCandidateConfirmation(
                draft_id=batch.drafts[0].draft_id,
                fact_candidate_ids=[required.assertion_id],
                promotion_basis="CODE_PROOF_REQUIRED",
            ),
        )
    remaining = store.read_draft_batch(manifest.system_id, batch.batch_id)
    assert remaining.drafts[0].entry_fact_candidates is not None
    assert remaining.drafts[0].entry_fact_candidates.assertions[0].source == (
        KnowledgeConclusionSource.AI_CANDIDATE
    )


def test_auto_publish_promotes_only_exact_state_machine_entry_facts(
    tmp_path: Path,
) -> None:
    """自动发布只提升被current可达状态机完整证明的前置和迁移断言。

    Args:
        tmp_path: Pytest隔离的源码、latest扫描、Fact契约和知识草稿目录。

    Returns:
        None；精确状态闭包成为CODE_PROVEN，产出和不完整状态候选继续隔离时通过。

    Side Effects:
        只在临时知识库发布结构化入口知识，不确认候选、不访问AI或QA。
    """

    source = tmp_path / "source"
    files = _write_dependency_sources(source)
    manifest = _dependency_manifest(source, files)
    analysis = manifest.semantic_analysis
    assert analysis is not None
    entity_type = "demo.RefundOrder"
    do_invoke_symbol = "demo.RefundCancelServiceInvoker#doInvoke(java.lang.Object)"
    entity_reference = _dependency_source_ref(
        source,
        files["entity"],
        entity_type,
        "class RefundOrder",
    )
    assignment_reference = _dependency_source_ref(
        source,
        files["invoker"],
        do_invoke_symbol + ":state-assignment",
        "created.setState(RefundOrderStateEnum.PENDING_APPLY)",
    )
    persistence_reference = _dependency_source_ref(
        source,
        files["invoker"],
        "demo.RefundOrderDao#insert(demo.RefundOrder)",
        "refundOrderDao.insert(created)",
    )
    orchestration_reference = _dependency_source_ref(
        source,
        files["invoker"],
        do_invoke_symbol + ":entity-lifecycle",
        "Object doInvoke",
    )
    manifest = manifest.model_copy(
        update={
            "semantic_analysis": analysis.model_copy(
                update={
                    "schema_version": 7,
                    "types": [
                        SemanticTypeDefinition(
                            symbol_id=entity_type,
                            qualified_class_name=entity_type,
                            simple_name="RefundOrder",
                            fields=[
                                SemanticFieldDefinition(
                                    field_name="refund_no",
                                    declared_type="String",
                                    source_ref=entity_reference,
                                ),
                                SemanticFieldDefinition(
                                    field_name="state",
                                    declared_type="RefundOrderStateEnum",
                                    referenced_type="demo.RefundOrderStateEnum",
                                    source_ref=entity_reference,
                                ),
                            ],
                            source_ref=entity_reference,
                        )
                    ],
                    "case_evidence": [
                        SemanticCaseEvidence(
                            evidence_id="semantic-proof:refund-order-pending-persisted",
                            method_symbol_id=do_invoke_symbol,
                            kind="entity_lifecycle",
                            entity_type=entity_type,
                            state_path="state",
                            state_value="PENDING_APPLY",
                            persistence_operation_id=(
                                "demo.RefundOrderDao#insert(demo.RefundOrder)"
                            ),
                            operation_ids=[
                                "demo.RefundOrderDao#insert(demo.RefundOrder)"
                            ],
                            control_flow_path=[do_invoke_symbol],
                            binding_kind="same_path_resolved_calls",
                            source_ref=orchestration_reference,
                            related_source_refs=[
                                assignment_reference,
                                persistence_reference,
                            ],
                        )
                    ],
                }
            )
        }
    )
    knowledge_root = tmp_path / "knowledge"
    store = GitKnowledgeStore(knowledge_root)
    store.register_system(
        SystemDefinition(
            system_id=manifest.system_id,
            name="退款状态证明系统",
            source_path=str(source),
        )
    )
    artifacts = SourceScanArtifactStore(knowledge_root)
    artifacts.write_manifest(manifest)
    artifacts.publish_latest(manifest.system_id, manifest.scan_id)
    service = KnowledgeGenerationService(
        store,
        SqliteKnowledgeIndex(knowledge_root / ".opentest" / "index.sqlite"),
        artifacts,
        git_repository=FixedBaselineRepository(manifest.baseline),
    )
    cancellable_states = [
        "PENDING_APPLY",
        "WAIT_REFUND",
        "RESHOPING",
        "REFUND_FAIL",
        "AUDITED",
    ]
    SetupContractRuleStore(store).write(
        SetupContractRuleSet(
            system_id=manifest.system_id,
            fact_contracts=[
                SetupFactContractDefinition(
                    fact_contract_id="stateful-refund/v1",
                    display_name="通用退款实体",
                    required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
                    required_fields=[
                        SetupFactRequiredField(path="refund_no", schema_type="string"),
                        SetupFactRequiredField(path="state", schema_type="string"),
                    ],
                    business_identity_paths=["refund_no"],
                    state_path="state",
                    state_predicates=[
                        SetupStatePredicateDefinition(
                            name="CANCELLABLE",
                            display_name="可取消",
                            allowed_values=cancellable_states,
                        ),
                        SetupStatePredicateDefinition(
                            name="CANCELLED",
                            display_name="已取消",
                            allowed_values=["REFUND_CANCEL"],
                        ),
                    ],
                ),
                SetupFactContractDefinition(
                    fact_contract_id="incomplete-refund/v1",
                    display_name="含未证明状态的退款实体",
                    required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
                    required_fields=[
                        SetupFactRequiredField(path="refund_no", schema_type="string"),
                        SetupFactRequiredField(path="state", schema_type="string"),
                    ],
                    business_identity_paths=["refund_no"],
                    state_path="state",
                    state_predicates=[
                        SetupStatePredicateDefinition(
                            name="CANCELLABLE",
                            allowed_values=[*cancellable_states, "UNPROVEN"],
                        ),
                        SetupStatePredicateDefinition(
                            name="CANCELLED",
                            allowed_values=["REFUND_CANCEL"],
                        ),
                    ],
                ),
            ],
        )
    )
    entry = manifest.entries[0]
    candidate_evidence = SourceReference(
        path=entry.source_path,
        symbol=entry.source_id,
        line=1,
    )
    exact_requirement = EntryFactAssertion(
        assertion_id="entry-fact:stateful-refund-required",
        assertion_type="REQUIRES_FACT",
        slot_id="refund_order",
        fact_contract_id="stateful-refund/v1",
        required_state="CANCELLABLE",
        acquisition_policy="QUERY_THEN_CREATE",
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[candidate_evidence],
    )
    exact_transition = EntryFactAssertion(
        assertion_id="entry-fact:stateful-refund-transition",
        assertion_type="STATE_TRANSITION",
        fact_contract_id="stateful-refund/v1",
        from_state="CANCELLABLE",
        to_state="CANCELLED",
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[candidate_evidence],
    )
    unproven_product = EntryFactAssertion(
        assertion_id="entry-fact:stateful-refund-product",
        assertion_type="PRODUCES_FACT",
        slot_id="cancelled_refund_order",
        fact_contract_id="stateful-refund/v1",
        produced_state="CANCELLED",
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[candidate_evidence],
    )
    proven_product = unproven_product.model_copy(
        update={
            "assertion_id": "entry-fact:stateful-refund-pending-product",
            "slot_id": "created_refund_order",
            "produced_state": "CANCELLABLE",
        }
    )
    incomplete_requirement = exact_requirement.model_copy(
        update={
            "assertion_id": "entry-fact:incomplete-refund-required",
            "slot_id": "incomplete_refund_order",
            "fact_contract_id": "incomplete-refund/v1",
        }
    )
    candidates = EntryFactCandidateSet(
        system_id=manifest.system_id,
        entry_id=entry.entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        assertions=[
            exact_requirement,
            exact_transition,
            proven_product,
            unproven_product,
            incomplete_requirement,
        ],
    )
    node = KnowledgeNode(
        node_id="entry:demo.RefundFacade#cancel",
        system_id=manifest.system_id,
        kind=KnowledgeNodeKind.FACADE,
        title=entry.display_name,
        aliases=[entry.entry_id, entry.source_id, entry.display_name],
        status=KnowledgeStatus.INFERRED,
        source_refs=[candidate_evidence],
    )
    draft = KnowledgeDraft(
        draft_id="draft-state-machine-code-proof",
        system_id=manifest.system_id,
        target_id=entry.entry_id,
        node=node,
        content="Agent提出的状态实体候选，等待程序证据分类。",
        entry_fact_candidates=candidates,
    )
    batch = KnowledgeGenerationWorkflowBatch(
        batch_id="knowledge-workflow-state-machine-code-proof",
        system_id=manifest.system_id,
        scan_id=manifest.scan_id,
        target_ids=[entry.entry_id],
        status="PENDING_CONFIRMATION",
        drafts=[draft],
    )
    store.write_draft_batch(batch)

    # 自动发布必须重新沿current源码关系求证，不能把INFERRED节点本身当作程序证据。
    service.publish_ready_drafts(manifest.system_id, batch.batch_id, rebuild_index=False)

    published = store.get_node(manifest.system_id, node.node_id)[0]
    assert published.entry_fact_knowledge is not None
    assert [item.assertion_id for item in published.entry_fact_knowledge.requires_facts] == [
        exact_requirement.assertion_id
    ]
    assert [item.assertion_id for item in published.entry_fact_knowledge.state_transitions] == [
        exact_transition.assertion_id
    ]
    assert [item.assertion_id for item in published.entry_fact_knowledge.produces_facts] == [
        proven_product.assertion_id
    ]
    formal_assertions = [
        *published.entry_fact_knowledge.requires_facts,
        *published.entry_fact_knowledge.produces_facts,
        *published.entry_fact_knowledge.state_transitions,
    ]
    assert {item.source for item in formal_assertions} == {
        KnowledgeConclusionSource.CODE_PROVEN
    }
    state_machine_symbols = {
        reference.symbol
        for item in [
            *published.entry_fact_knowledge.requires_facts,
            *published.entry_fact_knowledge.state_transitions,
        ]
        for reference in item.evidence_refs
    }
    assert state_machine_symbols == {
        "RefundOrderCancelPostActor",
        "RefundOrderManualCancelPostActor",
    }
    produced_refs = published.entry_fact_knowledge.produces_facts[0].evidence_refs
    assert {reference.symbol for reference in produced_refs} == {
        do_invoke_symbol + ":entity-lifecycle",
        do_invoke_symbol + ":state-assignment",
        "demo.RefundOrderDao#insert(demo.RefundOrder)",
    }
    assert {reference.commit for reference in produced_refs} == {
        manifest.baseline.commit
    }
    assert candidate_evidence not in produced_refs
    remaining = store.read_draft_batch(manifest.system_id, batch.batch_id)
    remaining_candidates = remaining.drafts[0].entry_fact_candidates
    assert remaining_candidates is not None
    assert [item.assertion_id for item in remaining_candidates.assertions] == [
        unproven_product.assertion_id,
        incomplete_requirement.assertion_id,
    ]
    assert all(
        item.source == KnowledgeConclusionSource.AI_CANDIDATE
        for item in remaining_candidates.assertions
    )

    # 同一业务slot升级时显式要求current代码证明，旧正式断言才会被原子替换。
    replacement_requirement = exact_requirement.model_copy(
        update={
            "assertion_id": "entry-fact:stateful-refund-required-v2",
        }
    )
    replacement_set = remaining_candidates.model_copy(
        update={
            "assertions": [
                replacement_requirement,
                *remaining_candidates.assertions,
            ]
        }
    )
    replacement_draft = remaining.drafts[0].model_copy(
        update={"entry_fact_candidates": replacement_set}
    )
    store.write_draft_batch(
        remaining.model_copy(update={"drafts": [replacement_draft]})
    )
    migrated = service.confirm_entry_fact_candidates(
        manifest.system_id,
        batch.batch_id,
        EntryFactCandidateConfirmation(
            draft_id=draft.draft_id,
            fact_candidate_ids=[replacement_requirement.assertion_id],
            promotion_basis="CODE_PROOF_REQUIRED",
            replacements=[
                EntryFactCandidateReplacement(
                    candidate_assertion_id=replacement_requirement.assertion_id,
                    superseded_assertion_ids=[exact_requirement.assertion_id],
                )
            ],
        ),
    )
    migrated_facts = migrated.entry_fact_knowledge
    assert [item.assertion_id for item in migrated_facts.requires_facts] == [
        replacement_requirement.assertion_id
    ]
    assert migrated_facts.requires_facts[0].source == KnowledgeConclusionSource.CODE_PROVEN
    assert [item.assertion_id for item in migrated_facts.state_transitions] == [
        exact_transition.assertion_id
    ]


def test_auto_publish_binding_requires_exact_current_published_mapping(
    tmp_path: Path,
) -> None:
    """Binding只有被current Published逻辑到provider映射及Fact字段共同证明才自动发布。

    Args:
        tmp_path: Pytest隔离的latest扫描、Published、Fact契约和知识草稿目录。

    Returns:
        None；精确物理字段映射成为CODE_PROVEN，类型兼容但目标不一致的候选仍隔离时通过。

    Side Effects:
        复用通用编译夹具在临时知识库发布能力和入口知识，不访问AI或QA。
    """

    from test_typed_case_compiler_phase5 import ENTRY_ID, SYSTEM_ID, _compiler_harness

    harness = _compiler_harness(tmp_path, [])
    application = harness.application
    manifest = application.source_analysis.artifacts.read(SYSTEM_ID, "latest")
    SetupContractRuleStore(application.store).write(
        SetupContractRuleSet(
            system_id=SYSTEM_ID,
            fact_contracts=[
                SetupFactContractDefinition(
                    fact_contract_id="generic-action-input/v1",
                    display_name="通用Action输入实体",
                    required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
                    required_fields=[
                        SetupFactRequiredField(path="mode", schema_type="string"),
                        SetupFactRequiredField(path="state", schema_type="string"),
                    ],
                    business_identity_paths=["mode"],
                    state_path="state",
                    state_predicates=[
                        SetupStatePredicateDefinition(
                            name="READY",
                            allowed_values=["READY"],
                        )
                    ],
                )
            ],
        )
    )
    entry = manifest.entries[0]
    formal_evidence = SourceReference(
        path=entry.source_path,
        symbol=entry.source_id,
        line=1,
        commit=manifest.baseline.commit,
    )
    requirement = EntryFactAssertion(
        assertion_id="entry-fact:generic-action-required",
        assertion_type="REQUIRES_FACT",
        slot_id="action_input",
        fact_contract_id="generic-action-input/v1",
        required_state="READY",
        acquisition_policy="QUERY_THEN_CREATE",
        source=KnowledgeConclusionSource.USER_CONFIRMED,
        evidence_refs=[formal_evidence],
    )
    existing_formal = EntryFactKnowledge(
        entry_id=entry.entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        requires_facts=[requirement],
        evidence_refs=[formal_evidence],
    )
    existing_node = KnowledgeNode(
        node_id="entry:sample.AtomicFacade#inspect",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        title=entry.display_name,
        aliases=[entry.entry_id, entry.source_id, entry.display_name],
        status=KnowledgeStatus.USER_CONFIRMED,
        source_refs=[formal_evidence],
        entry_fact_knowledge=existing_formal,
    )
    application.store.write_node(existing_node, "已确认通用Action所需实体。")
    untrusted_reference = SourceReference(
        path="AgentSuggested.java",
        symbol="agent.suggestion",
        line=999,
    )
    exact_binding = EntryFactAssertion(
        assertion_id="entry-fact:generic-action-mode-binding",
        assertion_type="BINDING_PATH",
        slot_id="action_input",
        fact_contract_id="generic-action-input/v1",
        request_path="mode",
        fact_path="mode",
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[untrusted_reference],
    )
    mismatched_binding = exact_binding.model_copy(
        update={
            "assertion_id": "entry-fact:generic-action-state-binding",
            "fact_path": "state",
        }
    )
    candidates = EntryFactCandidateSet(
        system_id=SYSTEM_ID,
        entry_id=entry.entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        assertions=[exact_binding, mismatched_binding],
    )
    draft = KnowledgeDraft(
        draft_id="draft-current-published-binding-proof",
        system_id=SYSTEM_ID,
        target_id=entry.entry_id,
        node=existing_node.model_copy(
            update={
                "status": KnowledgeStatus.INFERRED,
                "entry_fact_knowledge": None,
            }
        ),
        content="Agent提出的字段绑定候选，等待current Published映射证明。",
        entry_fact_candidates=candidates,
    )
    batch = KnowledgeGenerationWorkflowBatch(
        batch_id="knowledge-workflow-current-published-binding-proof",
        system_id=SYSTEM_ID,
        scan_id=manifest.scan_id,
        target_ids=[entry.entry_id],
        status="PENDING_CONFIRMATION",
        drafts=[draft],
    )
    application.store.write_draft_batch(batch)

    # Published逻辑mode映射到provider mode，只有同一provider形状的Fact字段可自动建立绑定。
    application.knowledge.publish_ready_drafts(
        SYSTEM_ID,
        batch.batch_id,
        rebuild_index=False,
    )

    published = application.store.get_node(SYSTEM_ID, existing_node.node_id)[0]
    assert published.entry_fact_knowledge is not None
    assert [item.assertion_id for item in published.entry_fact_knowledge.binding_paths] == [
        exact_binding.assertion_id
    ]
    formal_binding = published.entry_fact_knowledge.binding_paths[0]
    assert formal_binding.source == KnowledgeConclusionSource.CODE_PROVEN
    assert untrusted_reference not in formal_binding.evidence_refs
    assert formal_binding.evidence_refs
    remaining = application.store.read_draft_batch(SYSTEM_ID, batch.batch_id)
    remaining_candidates = remaining.drafts[0].entry_fact_candidates
    assert remaining_candidates is not None
    assert [item.assertion_id for item in remaining_candidates.assertions] == [
        mismatched_binding.assertion_id
    ]
    assert remaining_candidates.assertions[0].source == (
        KnowledgeConclusionSource.AI_CANDIDATE
    )
    application.close()


@pytest.mark.parametrize(
    ("operation_role", "mutability", "availability"),
    [
        (
            "QUERY",
            OperationMutability.READ_ONLY,
            SetupAvailabilityRule(type="VALUE_NOT_NULL", path="reference_id"),
        ),
        ("CREATE", OperationMutability.WRITE, None),
    ],
)
def test_auto_publish_candidate_operation_requires_current_published_closure(
    tmp_path: Path,
    operation_role: str,
    mutability: OperationMutability,
    availability: SetupAvailabilityRule | None,
) -> None:
    """查询和创建候选只有与current Published完整闭合时才能成为CODE_PROVEN。

    Args:
        tmp_path: Pytest隔离的latest扫描、Published、Fact契约和知识草稿目录。
        operation_role: 本次验证的QUERY或CREATE知识角色。
        mutability: 与角色对应的Published读写分类。
        availability: QUERY必须提供的结构型存在性规则；CREATE为空。

    Returns:
        None；正确角色自动提升，读写不符或业务型miss语义仍隔离时通过。

    Side Effects:
        复用通用编译夹具在临时知识库发布能力和入口知识，不访问AI或QA。
    """

    from test_typed_case_compiler_phase5 import ENTRY_ID, SYSTEM_ID, _compiler_harness

    harness = _compiler_harness(
        tmp_path / operation_role.lower(),
        [],
        mutability=mutability,
    )
    application = harness.application
    manifest = application.source_analysis.artifacts.read(SYSTEM_ID, "latest")
    SetupContractRuleStore(application.store).write(
        SetupContractRuleSet(
            system_id=SYSTEM_ID,
            fact_contracts=[
                SetupFactContractDefinition(
                    fact_contract_id="generic-operation-result/v1",
                    display_name="通用操作实体",
                    required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
                    required_fields=[
                        SetupFactRequiredField(path="entity_id", schema_type="string"),
                        SetupFactRequiredField(path="state", schema_type="string"),
                    ],
                    business_identity_paths=["entity_id"],
                    state_path="state",
                    state_predicates=[
                        SetupStatePredicateDefinition(
                            name="READY",
                            allowed_values=["READY"],
                        )
                    ],
                )
            ],
        )
    )
    entry = manifest.entries[0]
    untrusted_reference = SourceReference(
        path="AgentSuggestedOperation.java",
        symbol="agent.operation.suggestion",
        line=999,
    )
    exact_operation = EntryFactAssertion(
        assertion_id=f"entry-fact:generic-{operation_role.lower()}-operation",
        assertion_type="CANDIDATE_OPERATION",
        fact_contract_id="generic-operation-result/v1",
        operation_role=operation_role,
        candidate_system_id=SYSTEM_ID,
        candidate_operation_id=harness.action.provider_operation_ref.operation_id,
        query_availability=availability,
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[untrusted_reference],
    )
    wrong_role = "CREATE" if operation_role == "QUERY" else "QUERY"
    wrong_role_availability = (
        SetupAvailabilityRule(type="VALUE_NOT_NULL", path="reference_id")
        if wrong_role == "QUERY"
        else None
    )
    mismatched_operation = exact_operation.model_copy(
        update={
            "assertion_id": f"entry-fact:generic-{wrong_role.lower()}-operation-mismatch",
            "operation_role": wrong_role,
            "query_availability": wrong_role_availability,
        }
    )
    assertions = [exact_operation, mismatched_operation]
    if operation_role == "QUERY":
        # 布尔字段类型本身不能证明true代表“找到实体”，仍须保留为AI语义候选。
        assertions.append(
            exact_operation.model_copy(
                update={
                    "assertion_id": "entry-fact:generic-query-semantic-availability",
                    "query_availability": SetupAvailabilityRule(
                        type="BOOLEAN_EQUALS",
                        path="accepted",
                        expected_boolean=True,
                    ),
                }
            )
        )
    candidates = EntryFactCandidateSet(
        system_id=SYSTEM_ID,
        entry_id=entry.entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        assertions=assertions,
    )
    node = KnowledgeNode(
        node_id="entry:sample.AtomicFacade#inspect-operation-proof",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        title=entry.display_name,
        aliases=[entry.entry_id, entry.source_id, entry.display_name],
        status=KnowledgeStatus.INFERRED,
        source_refs=[untrusted_reference],
    )
    draft = KnowledgeDraft(
        draft_id=f"draft-current-published-{operation_role.lower()}-proof",
        system_id=SYSTEM_ID,
        target_id=ENTRY_ID,
        node=node,
        content="Agent提出的操作候选，等待current Published闭环证明。",
        entry_fact_candidates=candidates,
    )
    batch = KnowledgeGenerationWorkflowBatch(
        batch_id=f"knowledge-workflow-current-published-{operation_role.lower()}-proof",
        system_id=SYSTEM_ID,
        scan_id=manifest.scan_id,
        target_ids=[ENTRY_ID],
        status="PENDING_CONFIRMATION",
        drafts=[draft],
    )
    application.store.write_draft_batch(batch)

    # 自动发布重新读取Published、Candidate及provider operation，不采用Agent来源引用。
    application.knowledge.publish_ready_drafts(
        SYSTEM_ID,
        batch.batch_id,
        rebuild_index=False,
    )

    published = application.store.get_node(SYSTEM_ID, node.node_id)[0]
    assert published.entry_fact_knowledge is not None
    assert [item.assertion_id for item in published.entry_fact_knowledge.candidate_operations] == [
        exact_operation.assertion_id
    ]
    formal_operation = published.entry_fact_knowledge.candidate_operations[0]
    assert formal_operation.source == KnowledgeConclusionSource.CODE_PROVEN
    assert untrusted_reference not in formal_operation.evidence_refs
    assert formal_operation.evidence_refs
    remaining = application.store.read_draft_batch(SYSTEM_ID, batch.batch_id)
    remaining_candidates = remaining.drafts[0].entry_fact_candidates
    assert remaining_candidates is not None
    assert [item.assertion_id for item in remaining_candidates.assertions] == [
        item.assertion_id for item in assertions[1:]
    ]
    assert all(
        item.source == KnowledgeConclusionSource.AI_CANDIDATE
        for item in remaining_candidates.assertions
    )
    application.close()


def test_auto_publish_candidate_operation_accepts_exact_current_restricted_projection(
    tmp_path: Path,
) -> None:
    """知识CODE_PROVEN应重验PARTIAL Candidate的精确Published选中路径。

    Args:
        tmp_path: Pytest隔离的扫描、知识、能力和本地环境目录。

    Returns:
        None；受限投影仍current时操作候选成为CODE_PROVEN，Candidate保持PARTIAL。

    Side Effects:
        只在临时Git真相中发布能力与知识，不访问AI或QA。
    """

    from test_published_operation_capabilities_phase3 import (
        _configure_real_local_binding,
        _entry_candidate,
        _publish_restricted_projection_scan,
        _submission,
    )

    application = OpenTestApplication(tmp_path / "knowledge")
    system_id = "atomic-app"
    _publish_restricted_projection_scan(application, system_id)
    _configure_real_local_binding(application, system_id)
    publication = application.publish_operation_capability(
        system_id,
        _submission(application, system_id, "publish-knowledge-projection-0001"),
    )
    assert publication.status == "PUBLISHED"
    assert publication.capability is not None
    candidate = _entry_candidate(application, system_id)
    assert candidate.status.value == "PARTIAL"
    manifest = application.source_analysis.artifacts.read(system_id, "latest")
    entry = manifest.entries[0]
    SetupContractRuleStore(application.store).write(
        SetupContractRuleSet(
            system_id=system_id,
            fact_contracts=[
                SetupFactContractDefinition(
                    fact_contract_id="restricted-result/v1",
                    display_name="受限投影操作结果",
                    required_origin=SetupFactOrigin.PUBLISHED_OUTPUT,
                    required_fields=[
                        SetupFactRequiredField(path="reference_id", schema_type="string")
                    ],
                    business_identity_paths=["reference_id"],
                )
            ],
        )
    )
    assertion = EntryFactAssertion(
        assertion_id="entry-fact:restricted-create-operation",
        assertion_type="CANDIDATE_OPERATION",
        fact_contract_id="restricted-result/v1",
        operation_role="CREATE",
        candidate_system_id=system_id,
        candidate_operation_id=publication.capability.provider_operation_ref.operation_id,
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[
            SourceReference(path="AgentSuggested.java", symbol="agent.suggestion", line=999)
        ],
    )
    candidate_set = EntryFactCandidateSet(
        system_id=system_id,
        entry_id=entry.entry_id,
        source_scan_id=manifest.scan_id,
        source_baseline=manifest.baseline,
        assertions=[assertion],
    )
    node = KnowledgeNode(
        node_id="entry:sample.AtomicFacade#restricted-projection-proof",
        system_id=system_id,
        kind=KnowledgeNodeKind.FACADE,
        title=entry.display_name,
        aliases=[entry.entry_id, entry.source_id, entry.display_name],
        status=KnowledgeStatus.INFERRED,
        source_refs=[candidate.source_ref],
    )
    draft = KnowledgeDraft(
        draft_id="draft-current-restricted-published-proof",
        system_id=system_id,
        target_id=entry.entry_id,
        node=node,
        content="受限投影操作候选等待程序闭环证明。",
        entry_fact_candidates=candidate_set,
    )
    batch = KnowledgeGenerationWorkflowBatch(
        batch_id="knowledge-workflow-current-restricted-published-proof",
        system_id=system_id,
        scan_id=manifest.scan_id,
        target_ids=[entry.entry_id],
        status="PENDING_CONFIRMATION",
        drafts=[draft],
    )
    application.store.write_draft_batch(batch)

    application.knowledge.publish_ready_drafts(
        system_id,
        batch.batch_id,
        rebuild_index=False,
    )

    published_node = application.store.get_node(system_id, node.node_id)[0]
    assert published_node.entry_fact_knowledge is not None
    assert [
        item.assertion_id
        for item in published_node.entry_fact_knowledge.candidate_operations
    ] == [assertion.assertion_id]
    assert (
        published_node.entry_fact_knowledge.candidate_operations[0].source
        == KnowledgeConclusionSource.CODE_PROVEN
    )
    application.close()


def test_auto_publish_repairs_only_exact_legacy_double_wrapping(tmp_path: Path) -> None:
    """后续自动发布应修复旧版确认造成的精确双层包装但拒绝歧义嵌套。

    Args:
        tmp_path: Pytest隔离的知识、扫描和源码目录。

    Returns:
        None；精确重复正文被折叠且不相同的人工后缀仍被拒绝时通过。

    Side Effects:
        仅构造并改写临时知识Markdown，不访问QA或真实知识资产。
    """

    service, store, manifest = _knowledge_service(tmp_path)
    batch = service.generate(
        KnowledgeGenerationRequest(
            system_id=manifest.system_id,
            entry_id=manifest.entries[0].entry_id,
        )
    )
    entry_node = next(node for node in batch.nodes if node.kind == KnowledgeNodeKind.FACADE)
    node_path = store.node_path(entry_node)
    _stored_node, body = store.read_node(node_path)

    # 精确模拟旧调用把完整正文传给write_node后形成的双层包装。
    outer_start = body.index(AUTO_START)
    outer_end = body.index(AUTO_END)
    prefix = body[:outer_start]
    suffix = body[outer_end + len(AUTO_END) :]
    duplicated_body = f"{prefix.rstrip()}\n{AUTO_START}\n{body.strip()}\n{AUTO_END}{suffix}"
    document = node_path.read_text(encoding="utf-8")
    node_path.write_text(
        document[: -len(body)] + duplicated_body,
        encoding="utf-8",
    )

    store.write_node(entry_node, "重新生成的可信正文。")
    repaired_document = node_path.read_text(encoding="utf-8")
    assert repaired_document.count(AUTO_START) == 1
    assert repaired_document.count(AUTO_END) == 1
    assert "重新生成的可信正文。" in repaired_document

    # 人工区域不一致时无法证明来自旧缺陷，必须继续拒绝自动猜测边界。
    _repaired_node, repaired_body = store.read_node(node_path)
    ambiguous_body = (
        f"{AUTO_START}\n{repaired_body.strip()}\n{AUTO_END}\n\n"
        "## 与内层不一致的人工说明\n"
    )
    ambiguous_document = node_path.read_text(encoding="utf-8")
    node_path.write_text(
        ambiguous_document[: -len(repaired_body)] + ambiguous_body,
        encoding="utf-8",
    )
    with pytest.raises(
        KnowledgeValidationError,
        match="invalid or ambiguous knowledge auto-region markers",
    ):
        store.write_node(entry_node, "不得覆盖歧义正文。")


def test_metadata_update_preserves_legacy_markerless_knowledge_body(tmp_path: Path) -> None:
    """逐Fact元数据更新必须兼容尚未迁入自动区域的旧知识正文。

    Args:
        tmp_path: Pytest隔离的知识、扫描和源码目录。

    Returns:
        None；旧正文逐字保留且只更新frontmatter时通过。

    Side Effects:
        仅把临时知识节点改写为旧格式并执行一次元数据更新，不访问QA。
    """

    service, store, manifest = _knowledge_service(tmp_path)
    batch = service.generate(
        KnowledgeGenerationRequest(
            system_id=manifest.system_id,
            entry_id=manifest.entries[0].entry_id,
        )
    )
    entry_node = next(node for node in batch.nodes if node.kind == KnowledgeNodeKind.FACADE)
    node_path = store.node_path(entry_node)
    _stored_node, body = store.read_node(node_path)
    legacy_body = "旧版人工知识正文，没有自动区域标记。\n"
    document = node_path.read_text(encoding="utf-8")
    node_path.write_text(document[: -len(body)] + legacy_body, encoding="utf-8")

    updated_node = entry_node.model_copy(update={"status": KnowledgeStatus.USER_CONFIRMED})
    store.write_node_metadata(updated_node)
    persisted_node, persisted_body = store.read_node(node_path)

    assert persisted_node.status == KnowledgeStatus.USER_CONFIRMED
    assert persisted_body.strip() == legacy_body.strip()
    assert AUTO_START not in persisted_body
    assert AUTO_END not in persisted_body


def test_entry_fact_confirmation_rejects_stale_scan_and_invalid_evidence(
    tmp_path: Path,
) -> None:
    """候选确认必须重验latest扫描、状态谓词和源码证据而非信任草稿。

    Args:
        tmp_path: Pytest隔离的知识、扫描、Fact契约和源码目录。

    Returns:
        None；旧扫描、未知状态和越界证据均被正式发布边界拒绝时通过。

    Side Effects:
        只改写临时latest扫描和候选草稿，不发布断言或访问QA。
    """

    service, store, manifest, batch, required, _produced = (
        _entry_fact_confirmation_fixture(tmp_path)
    )
    newer_manifest = manifest.model_copy(
        update={"scan_id": "scan-20260827000000-entry-fact-newer"}
    )
    service.artifacts.write_manifest(newer_manifest)
    service.artifacts.publish_latest(newer_manifest.system_id, newer_manifest.scan_id)
    confirmation = EntryFactCandidateConfirmation(
        draft_id=batch.drafts[0].draft_id,
        fact_candidate_ids=[required.assertion_id],
    )
    with pytest.raises(KnowledgeValidationError, match="source scope is stale"):
        service.confirm_entry_fact_candidates(
            manifest.system_id,
            batch.batch_id,
            confirmation,
        )

    # 恢复候选所属代际后，未知业务状态仍不能借用户确认绕过Fact契约。
    service.artifacts.publish_latest(manifest.system_id, manifest.scan_id)
    unknown_state = required.model_copy(update={"required_state": "UNKNOWN_STATE"})
    unknown_state_candidates = batch.drafts[0].entry_fact_candidates.model_copy(
        update={"assertions": [unknown_state]}
    )
    unknown_state_batch = batch.model_copy(
        update={
            "drafts": [
                batch.drafts[0].model_copy(
                    update={"entry_fact_candidates": unknown_state_candidates}
                )
            ]
        }
    )
    store.write_draft_batch(unknown_state_batch)
    with pytest.raises(KnowledgeValidationError, match="unknown state predicate"):
        service.confirm_entry_fact_candidates(
            manifest.system_id,
            batch.batch_id,
            confirmation,
        )

    # 合法状态也必须重新读取注册源码，越界行号不能被视为有效证据。
    invalid_evidence = required.model_copy(
        update={
            "evidence_refs": [
                required.evidence_refs[0].model_copy(update={"line": 99_999})
            ]
        }
    )
    invalid_candidates = unknown_state_candidates.model_copy(
        update={"assertions": [invalid_evidence]}
    )
    store.write_draft_batch(
        batch.model_copy(
            update={
                "drafts": [
                    batch.drafts[0].model_copy(
                        update={"entry_fact_candidates": invalid_candidates}
                    )
                ]
            }
        )
    )
    with pytest.raises(KnowledgeValidationError, match="evidence is no longer valid"):
        service.confirm_entry_fact_candidates(
            manifest.system_id,
            batch.batch_id,
            confirmation,
        )


def test_candidate_operation_evidence_uses_provider_latest_registered_root(
    tmp_path: Path,
) -> None:
    """跨系统候选操作证据必须从provider current源码而不是consumer同名路径读取。

    Args:
        tmp_path: Pytest隔离的consumer、provider源码和知识目录。

    Returns:
        None；consumer同路径证据被拒绝、provider真实证据和操作身份同时通过时成立。

    Side Effects:
        注册一个临时provider系统并发布其latest Manifest，不访问AI或QA。
    """

    service, store, consumer_manifest = _knowledge_service(tmp_path)
    provider_system_id = "flight-provider-core"
    provider_source = tmp_path / "provider-source"
    provider_source.mkdir()
    provider_facade = provider_source / "TradeFacadeImpl.java"
    provider_facade.write_text(
        "class TradeFacadeImpl { Object queryList(Object request) { return request; } }\n",
        encoding="utf-8",
    )
    provider_entry_id = "facade:demo.TradeFacade#queryList"
    provider_manifest = ScanManifest(
        scan_id="scan-20260828000000-provider-test",
        system_id=provider_system_id,
        baseline=SourceBaseline(
            source_path=str(provider_source),
            commit="provider-current",
        ),
        entries=[
            EntryPoint(
                entry_id=provider_entry_id,
                system_id=provider_system_id,
                kind=KnowledgeNodeKind.FACADE,
                display_name="TradeFacade#queryList",
                source_id="demo.TradeFacade#queryList",
                source_path="TradeFacadeImpl.java",
            )
        ],
    )
    store.register_system(
        SystemDefinition(
            system_id=provider_system_id,
            name="航班查询Provider",
            source_path=str(provider_source),
            baseline=provider_manifest.baseline,
        )
    )
    service.artifacts.write_manifest(provider_manifest)
    service.artifacts.publish_latest(provider_system_id, provider_manifest.scan_id)
    provider_candidate_id = f"candidate:{provider_system_id}:{provider_entry_id}"

    # consumer根恰好也存在同名文件和createOrder方法，不能借相对路径相同冒充provider证据。
    consumer_only_evidence = SourceReference(
        path="TradeFacadeImpl.java",
        symbol="TradeFacadeImpl#createOrder",
        line=1,
        commit=consumer_manifest.baseline.commit,
    )
    assertion = EntryFactAssertion(
        assertion_id="entry-fact:provider-query-operation",
        assertion_type="CANDIDATE_OPERATION",
        fact_contract_id="ticket-order/v1",
        operation_role="QUERY",
        candidate_system_id=provider_system_id,
        candidate_operation_id=provider_candidate_id,
        source=KnowledgeConclusionSource.AI_CANDIDATE,
        evidence_refs=[consumer_only_evidence],
    )
    with pytest.raises(KnowledgeValidationError, match="evidence is no longer valid"):
        service._revalidate_entry_fact_evidence(
            consumer_manifest.system_id,
            assertion,
        )

    # provider current文件中的精确方法和latest操作身份共同闭合后才允许确认边界继续。
    provider_evidence = SourceReference(
        path="TradeFacadeImpl.java",
        symbol="TradeFacadeImpl#queryList",
        line=1,
    )
    validated = service._revalidate_entry_fact_evidence(
        consumer_manifest.system_id,
        assertion.model_copy(update={"evidence_refs": [provider_evidence]}),
    )
    assert validated.candidate_source_scan_id == provider_manifest.scan_id
    assert validated.candidate_source_baseline == provider_manifest.baseline
    assert validated.evidence_refs[0].repository == provider_system_id
    assert validated.evidence_refs[0].commit == provider_manifest.baseline.commit
    with pytest.raises(KnowledgeValidationError, match="absent from provider latest"):
        service._revalidate_entry_fact_evidence(
            consumer_manifest.system_id,
            assertion.model_copy(
                update={
                    "candidate_operation_id": "facade:demo.TradeFacade#missing",
                    "evidence_refs": [provider_evidence],
                }
            ),
        )

    # 已确认断言冻结provider scan/baseline；provider推进后旧正式证据必须显式失效。
    provider_next = provider_manifest.model_copy(
        update={
            "scan_id": "scan-20260828000001-provider-next",
            "baseline": provider_manifest.baseline.model_copy(
                update={"commit": "provider-next"}
            ),
        }
    )
    service.artifacts.write_manifest(provider_next)
    service.artifacts.publish_latest(provider_system_id, provider_next.scan_id)
    store.update_system(
        provider_system_id,
        store.get_system(provider_system_id).model_copy(
            update={"baseline": provider_next.baseline}
        ),
    )
    with pytest.raises(KnowledgeValidationError, match="provider source scope is stale"):
        service._revalidate_entry_fact_evidence(
            consumer_manifest.system_id,
            validated,
        )


def test_generation_rebuilds_search_and_relation_index(tmp_path: Path) -> None:
    """发布后中文术语和入口一跳关系应立即从SQLite查询。"""

    service, _, manifest = _knowledge_service(tmp_path)
    service.generate(
        KnowledgeGenerationRequest(system_id=manifest.system_id, entry_id=manifest.entries[0].entry_id)
    )
    matches = service.index.search("港币支付", manifest.system_id)
    relations = service.index.related("facade:TradeFacade#createOrder", "outgoing", depth=3)

    assert any(item["node_id"] == "rule:create-order:hk-payment-verify" for item in matches)
    assert {item["target_node_id"] for item in relations} >= {
        "logic:CreateOrderValidator#validate",
        "logic:CreateOrderServiceInvoker#invokeInner",
        "rule:create-order:hk-payment-verify",
        "data-source:mtr-ticket-price",
    }
    assert max(item["depth"] for item in relations) == 3


def test_confirmation_rejects_nodes_outside_question_scope(tmp_path: Path) -> None:
    """用户回答不得借问题确认其影响范围之外的知识结论。"""

    service, _, manifest = _knowledge_service(tmp_path)
    service.generate(
        KnowledgeGenerationRequest(system_id=manifest.system_id, entry_id=manifest.entries[0].entry_id)
    )
    with pytest.raises(ScopeViolationError, match="outside question scope"):
        service.confirm(
            manifest.system_id,
            KnowledgeConfirmation(
                question_id="question:create-order:hk-verify-exception",
                answer="确认",
                confirmed_node_ids=["rule:create-order:adult-required"],
            ),
        )


def test_generation_rejects_stale_source_baseline(tmp_path: Path) -> None:
    """扫描后源码状态变化时不得把旧证据发布成当前知识。"""

    service, _, manifest = _knowledge_service(tmp_path)
    service.git_repository = FixedBaselineRepository(
        manifest.baseline.model_copy(update={"dirty": True, "dirty_digest": "changed"})
    )
    with pytest.raises(KnowledgeValidationError, match="source changed after scan"):
        service.generate(
            KnowledgeGenerationRequest(system_id=manifest.system_id, entry_id=manifest.entries[0].entry_id)
        )


def test_agent_runner_uses_allowlisted_environment_and_local_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """受控Agent命令应无shell执行并只在本地证据目录保存输出。"""

    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nprintf 'cwd=%s\\nargs=%s' \"$PWD\" \"$*\"\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("OPENTEST_SECRET_SHOULD_NOT_LEAK", "secret")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "knowledge" / ".opentest" / "agent-runs"
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))

    evidence = runner.run(
        AgentRunRequest(system_id="train-booking-core", agent="codex", prompt="只读分析"),
        source,
        evidence_root,
    )

    output_path = Path(evidence.output_path)
    assert output_path.is_relative_to(evidence_root.resolve())
    output = output_path.read_text(encoding="utf-8")
    assert f"cwd={output_path.parent}" in output
    assert "-a never exec" in output
    assert "--sandbox read-only" in output
    assert "--disable shell_tool" in output
    assert "--disable unified_exec" in output
    # 只开放OpenTest自带的注册源码读取服务；用户MCP、原生Shell和源码根外读取仍不可用。
    assert "mcp_servers.opentest_source.command" in output
    assert "mcp_servers.opentest_source.args" in output
    assert "mcp_servers={}" not in output
    assert str(source.resolve()) in output
    assert "source-access.jsonl" in output
    assert "--disable hooks" in output
    assert evidence.prompt_digest
    # 提示和输出都可能包含未确认业务内容，目录与三类证据文件必须显式限制为当前用户。
    run_root = output_path.parent
    assert evidence_root.stat().st_mode & 0o077 == 0
    assert run_root.stat().st_mode & 0o077 == 0
    for evidence_path in [run_root / "prompt.txt", output_path, run_root / "evidence.json"]:
        assert evidence_path.stat().st_mode & 0o077 == 0


def test_agent_runner_accepts_official_codex_javascript_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """官方npm `codex` 符号链接解析为codex.js时仍应通过允许列表。"""

    package_entry = tmp_path / "codex.js"
    package_entry.write_text("#!/bin/sh\nprintf '{}\\n'\n", encoding="utf-8")
    package_entry.chmod(0o755)
    command_link = tmp_path / "codex"
    command_link.symlink_to(package_entry)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()

    evidence = AgentRunner(AgentRunnerConfig(codex_executable="codex")).run(
        AgentRunRequest(system_id="train-booking-core", agent="codex", prompt="只读分析"),
        source,
        tmp_path / "evidence",
    )

    assert evidence.exit_code == 0


def test_agent_runner_keeps_codex_resume_session_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex续接原会话时仍应通过配置强制只读沙箱。

    Args:
        tmp_path: pytest隔离的假Codex、源码和证据目录。
        monkeypatch: 把假Codex放到本测试PATH首位。

    Returns:
        None；续接命令同时包含原会话ID和只读配置时通过。
    """

    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nprintf 'args=%s' \"$*\"\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()

    # resume子命令没有独立的--sandbox参数，因此必须由忽略用户配置后的显式配置保持只读。
    evidence = AgentRunner(AgentRunnerConfig(codex_executable="codex")).run(
        AgentRunRequest(
            system_id="train-booking-core",
            agent="codex",
            prompt="继续只读分析",
            resume_session_id="019c-stream-resume-test",
        ),
        source,
        tmp_path / "evidence",
    )
    output = Path(evidence.output_path).read_text(encoding="utf-8")

    assert "-a never exec resume 019c-stream-resume-test" in output
    assert 'sandbox_mode="read-only"' in output
    assert "--ignore-user-config" in output
    assert "mcp_servers.opentest_source.command" in output


def test_agent_runner_limits_claude_to_registered_source_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude Code必须忽略用户配置并且只允许OpenTest注册源码工具。

    Args:
        tmp_path: pytest隔离的假Claude、注册源码根和运行证据目录。
        monkeypatch: 把假Claude命令放到当前测试PATH首位。

    Returns:
        None；命令关闭原生工具、固定MCP并保留注册源码根时通过。
    """

    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\nprintf 'args=%s' \"$*\"\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()

    # 使用假CLI只检查最终参数，不启动真实Claude Code或产生外部费用。
    evidence = AgentRunner(AgentRunnerConfig(claude_executable="claude")).run(
        AgentRunRequest(system_id="train-booking-core", agent="claude", prompt="只读分析"),
        source,
        tmp_path / "evidence",
    )
    output = Path(evidence.output_path).read_text(encoding="utf-8")

    assert "--permission-mode dontAsk" in output
    assert "--setting-sources" in output
    assert "--strict-mcp-config" in output
    assert '"opentest_source"' in output
    assert str(source.resolve()) in output
    assert "--tools  --allowedTools mcp__opentest_source__list_source_files" in output
    assert "mcp__opentest_source__search_source" in output
    assert "mcp__opentest_source__read_source" in output
    assert "--safe-mode" not in output


def test_registered_source_reader_scans_only_main_source_and_audits_access(tmp_path: Path) -> None:
    """受控源码工具应读取主源码、记录轨迹并拒绝根外与Fixture目录。

    Args:
        tmp_path: pytest隔离的注册源码根和Agent运行目录。

    Returns:
        None；列举、搜索、读取和边界拒绝均符合契约时通过。
    """

    source = tmp_path / "source"
    main_file = source / "src/main/java/demo/QueryInvoker.java"
    protected_file = source / "src/test/fixtures/QueryFixture.java"
    fixture_named_file = source / "src/main/java/demo/RefundFixture.java"
    qa_client_file = source / "src/main/java/demo/QAClient.java"
    qa_fixture_file = source / "src/main/java/demo/QAFixture.java"
    qa_config_file = source / "src/main/resources/application-qa.yml"
    qa_variant_file = source / "src/qa-config/RefundClient.java"
    qa_acronym_file = source / "src/RefundQAConfig/RefundClient.java"
    qa_tools_file = source / "src/QATools/RefundClient.java"
    test_data_file = source / "src/testdata/RefundOrder.java"
    redacted_config_file = source / "src/main/resources/application.yml"
    secret_named_config = source / "src/main/resources/SecretConfig.yml"
    secret_xml_config = source / "src/main/resources/SecretConfig.xml"
    auth_java_config = source / "src/main/java/demo/AuthConfig.java"
    api_key_java_config = source / "src/main/java/demo/ApiKeyConfig.java"
    access_key_xml_config = source / "src/main/resources/AccessKeyConfig.xml"
    camel_case_config = source / "src/main/resources/ordinary.xml"
    main_file.parent.mkdir(parents=True)
    protected_file.parent.mkdir(parents=True)
    qa_config_file.parent.mkdir(parents=True)
    qa_variant_file.parent.mkdir(parents=True)
    qa_acronym_file.parent.mkdir(parents=True)
    qa_tools_file.parent.mkdir(parents=True)
    test_data_file.parent.mkdir(parents=True)
    main_file.write_text("class QueryInvoker { void invoke() { orderService.queryList(); } }\n", encoding="utf-8")
    protected_file.write_text("class QueryFixture {}\n", encoding="utf-8")
    fixture_named_file.write_text("class RefundFixture {}\n", encoding="utf-8")
    qa_client_file.write_text("class QAClient {}\n", encoding="utf-8")
    qa_fixture_file.write_text("class QAFixture {}\n", encoding="utf-8")
    qa_config_file.write_text("password: fake-secret-for-test\n", encoding="utf-8")
    qa_variant_file.write_text("class RefundClient {}\n", encoding="utf-8")
    qa_acronym_file.write_text("class RefundClient {}\n", encoding="utf-8")
    qa_tools_file.write_text("class RefundClient {}\n", encoding="utf-8")
    test_data_file.write_text("class RefundOrder {}\n", encoding="utf-8")
    redacted_config_file.write_text(
        "password: fake-secret-for-test\nauthToken:\nfake-multiline-assignment\nmode: local\n",
        encoding="utf-8",
    )
    secret_named_config.write_text("mode: fake-secret-for-test\n", encoding="utf-8")
    secret_xml_config.write_text("<configuration/>\n", encoding="utf-8")
    auth_java_config.write_text("class AuthConfig {}\n", encoding="utf-8")
    api_key_java_config.write_text("class ApiKeyConfig {}\n", encoding="utf-8")
    access_key_xml_config.write_text("<configuration/>\n", encoding="utf-8")
    camel_case_config.write_text(
        "<clientSecret>fake-inline-secret</clientSecret>\n"
        "<refreshToken>\n"
        "fake-multiline-token\n"
        "</refreshToken>\n"
        "<mode>local</mode>\n",
        encoding="utf-8",
    )
    run_root = tmp_path / "run"
    run_root.mkdir()
    audit_path = run_root / "source-access.jsonl"
    reader = RegisteredSourceReader(source, audit_path)

    files = reader.list_source_files(query="Query")
    all_files = reader.list_source_files()
    matches = reader.search_source("orderService.queryList", file_glob="*.java")
    literal_matches = reader.search_source("orderService.+queryList", file_glob="*.java")
    content = reader.read_source("src/main/java/demo/QueryInvoker.java", 1, 1)
    redacted_config = reader.read_source("src/main/resources/application.yml", 1, 4)
    redacted_camel_case = reader.read_source("src/main/resources/ordinary.xml", 1, 5)

    assert files["files"] == ["src/main/java/demo/QueryInvoker.java"]
    assert all_files["files"] == [
        "src/main/java/demo/QueryInvoker.java",
        "src/main/resources/application.yml",
        "src/main/resources/ordinary.xml",
    ]
    assert matches["matches"][0]["path"] == "src/main/java/demo/QueryInvoker.java"
    assert literal_matches["matches"] == []
    assert "orderService.queryList" in content["content"]
    assert "fake-secret-for-test" not in redacted_config["content"]
    assert "fake-multiline-assignment" not in redacted_config["content"]
    assert "[REDACTED_SENSITIVE_VALUE]" in redacted_config["content"]
    assert "fake-inline-secret" not in redacted_camel_case["content"]
    assert "fake-multiline-token" not in redacted_camel_case["content"]
    assert "<mode>local</mode>" in redacted_camel_case["content"]
    assert len(audit_path.read_text(encoding="utf-8").splitlines()) == 7
    assert audit_path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="registered root"):
        reader.read_source("../outside.java")
    with pytest.raises(ValueError, match="protected directory"):
        reader.read_source("src/test/fixtures/QueryFixture.java")
    for protected_path in (
        "src/main/java/demo/RefundFixture.java",
        "src/main/java/demo/QAClient.java",
        "src/main/java/demo/QAFixture.java",
        "src/main/resources/application-qa.yml",
        "src/qa-config/RefundClient.java",
        "src/RefundQAConfig/RefundClient.java",
        "src/QATools/RefundClient.java",
        "src/testdata/RefundOrder.java",
        "src/main/resources/SecretConfig.yml",
        "src/main/resources/SecretConfig.xml",
        "src/main/java/demo/AuthConfig.java",
        "src/main/java/demo/ApiKeyConfig.java",
        "src/main/resources/AccessKeyConfig.xml",
    ):
        # 文件名和连字符目录也属于固定安全边界，不能只依赖精确父目录名称。
        with pytest.raises(ValueError, match="protected|not allowed"):
            reader.read_source(protected_path)


def test_registered_source_reader_refuses_a_symlink_at_open_time(tmp_path: Path) -> None:
    """源码读取最终打开文件时必须再次拒绝符号链接，避免校验后替换逃逸。

    Args:
        tmp_path: pytest隔离的注册源码、根外文件和审计目录。

    Returns:
        None；最终文件已变为根外符号链接时不返回任何正文。
    """

    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "QueryService.java"
    outside_file = tmp_path / "Outside.java"
    source_file.write_text("class QueryService {}\n", encoding="utf-8")
    outside_file.write_text("class OutsideSecret {}\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    reader = RegisteredSourceReader(source, run_root / "source-access.jsonl")
    source_file.unlink()
    source_file.symlink_to(outside_file)

    # 直接覆盖最终打开阶段，确保即使前置解析已发生也不会跟随新出现的链接。
    with pytest.raises(ValueError, match="symbolic link|could not be read"):
        reader._read_lines(source_file)


def test_global_index_transaction_serializes_independent_store_instances(tmp_path: Path) -> None:
    """不同系统/应用实例的全局索引发布与回滚必须共用跨进程锁。

    Args:
        tmp_path: pytest隔离的共享知识根与锁文件目录。

    Returns:
        None；第二实例只在第一实例释放全局索引事务后进入时通过。
    """

    first_store = GitKnowledgeStore(tmp_path / "knowledge")
    second_store = GitKnowledgeStore(tmp_path / "knowledge")
    first_store.initialize()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def hold_first_transaction() -> None:
        """持有第一实例全局索引锁直到主测试明确释放。

        Returns:
            None；事件仅用于确定性协调测试线程。
        """

        with first_store.index_transaction():
            first_entered.set()
            assert release_first.wait(timeout=2)

    def enter_second_transaction() -> None:
        """等待同一全局索引锁并记录真正进入临界区的时刻。

        Returns:
            None；取得第二实例锁后设置完成事件。
        """

        with second_store.index_transaction():
            second_entered.set()

    first_thread = threading.Thread(target=hold_first_transaction)
    second_thread = threading.Thread(target=enter_second_transaction)
    first_thread.start()
    assert first_entered.wait(timeout=2)
    second_thread.start()
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)
    assert second_entered.is_set()


def test_registered_source_mcp_serves_tools_over_stdio_without_source_writes(tmp_path: Path) -> None:
    """Codex和Claude启动的stdio服务应列出并执行唯一受控源码工具集。

    Args:
        tmp_path: pytest隔离的源码文件、运行日志和stdio进程目录。

    Returns:
        None；初始化、工具发现和读取调用都返回标准JSON-RPC且源码保持不变。
    """

    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "QueryService.java"
    source_file.write_text("class QueryService {}\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    audit_path = run_root / "source-access.jsonl"
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "read_source",
                "arguments": {"path": "QueryService.java", "start_line": 1, "end_line": 1},
            },
        },
    ]
    input_text = "\n".join(json.dumps(item) for item in requests) + "\n"

    # 直接运行生产MCP入口，验证协议布线而不启动或计费任何真实Agent。
    completed = subprocess.run(
        [sys.executable, str(Path(registered_source_mcp.__file__).resolve()), str(source), str(audit_path)],
        input=input_text,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert {tool["name"] for tool in responses[1]["result"]["tools"]} == {
        "list_source_files",
        "search_source",
        "read_source",
    }
    assert "class QueryService" in responses[2]["result"]["content"][0]["text"]
    assert source_file.read_text(encoding="utf-8") == "class QueryService {}\n"


def test_agent_diagnostics_marks_oversized_final_output_as_truncated(tmp_path: Path) -> None:
    """诊断材料超过页面上限时必须报告原始长度，不能静默冒充完整输出。

    Args:
        tmp_path: pytest隔离的私有Agent运行证据目录。

    Returns:
        None；Prompt保持精确且过大最终输出携带显式截断标记时通过。
    """

    evidence_root = tmp_path / "agent-runs"
    run_root = evidence_root / "agent-2222222222222222"
    run_root.mkdir(parents=True)
    (run_root / "worker-request.json").write_text(
        json.dumps({"agent": "codex", "target_id": "facade:demo.Query#list"}),
        encoding="utf-8",
    )
    (run_root / "state.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (run_root / "prompt.txt").write_text("完整Prompt", encoding="utf-8")
    (run_root / "output.txt").write_text("x" * 200_001, encoding="utf-8")

    diagnostics = AgentRunner().read_diagnostics(run_root.name, evidence_root)

    assert diagnostics.prompt == "完整Prompt"
    assert diagnostics.prompt_truncated is False
    assert diagnostics.final_output_chars == 200_001
    assert len(diagnostics.final_output) == 200_000
    assert diagnostics.final_output_truncated is True


def test_dynamic_facade_agent_must_read_and_publish_downstream_source_refs(tmp_path: Path) -> None:
    """动态Facade不得只解释接口契约，完整结果必须包含实际读取的下游业务路径。

    Args:
        tmp_path: pytest隔离的源码、知识证据和索引目录。

    Returns:
        None；仅到Invoker时拒绝，读取Service和DAO边界后允许合并到发布节点。
    """

    service, store, manifest = _knowledge_service(tmp_path)
    source_root = Path(store.get_system(manifest.system_id).source_path)
    facade_path = source_root / "DynamicRefundFacadeImpl.java"
    invoker_path = source_root / "RefundOrderListQueryInvoker.java"
    service_path = source_root / "OrderServiceImpl.java"
    dao_path = source_root / "SaasRefundOrderDAOProxy.java"
    facade_path.write_text(
        "class DynamicRefundFacadeImpl { Object queryList(Object request) { return execute(RefundOrderServiceEnum.QUERY_LIST); } }\n",
        encoding="utf-8",
    )
    invoker_path.write_text(
        "@RefundOrderService(RefundOrderServiceEnum.QUERY_LIST) class RefundOrderListQueryInvoker {\n"
        "  OrderServiceImpl orderService; Object invoke(Object request) { return orderService.queryOrderList(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  SaasRefundOrderDAOProxy orderDAO; Object queryOrderList(Object request) { return orderDAO.listPage(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    dao_path.write_text(
        "class SaasRefundOrderDAOProxy {\n"
        "  Object listPage(Object request) { return mapper.listPage(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    target_id = "facade:demo.DynamicRefundFacade#queryList"
    node = KnowledgeNode(
        node_id="entry:dynamic-refund-query-list",
        system_id=manifest.system_id,
        kind=KnowledgeNodeKind.FACADE,
        title="DynamicRefundFacade#queryList",
        source_refs=[
            SourceReference(
                path=facade_path.relative_to(source_root).as_posix(),
                symbol="DynamicRefundFacadeImpl#queryList",
                line=1,
            )
        ],
    )
    invoker_node = KnowledgeNode(
        node_id="logic:refund-order-list-query",
        system_id=manifest.system_id,
        kind=KnowledgeNodeKind.COMMON_LOGIC,
        title="RefundOrderListQueryInvoker#invoke",
        source_refs=[
            SourceReference(
                path=invoker_path.relative_to(source_root).as_posix(),
                symbol="RefundOrderListQueryInvoker#invoke",
                line=2,
            )
        ],
    )
    nodes = [node, invoker_node]
    request = KnowledgeGenerationBatchRequest(
        system_id=manifest.system_id,
        target_ids=[target_id],
        scan_id=manifest.scan_id,
        agent="codex",
        confirmed=True,
    )
    run_root = store.root / ".opentest/agent-runs/agent-1111111111111111"
    run_root.mkdir(parents=True)
    output_path = run_root / "output.txt"
    source_access_path = run_root / "source-access.jsonl"
    envelope = {
        "status": "completed",
        "system_id": manifest.system_id,
        "target_ids": [target_id],
        "summaries": [
            {
                "node_id": node.node_id,
                "summary": "沿动态分发进入退款单列表查询并返回查询结果。",
                "test_points": [
                    {
                        "kind": "main_flow",
                        "title": "查询退款单列表",
                        "condition": "请求满足列表查询条件",
                        "expected_outcome": "返回符合条件的退款单分页结果",
                    }
                ],
            },
            {
                "node_id": invoker_node.node_id,
                "summary": "调用订单服务执行列表查询并组装Facade响应。",
                "test_points": [
                    {
                        "kind": "common_rule",
                        "title": "列表查询调用规则",
                        "condition": "动态路由命中列表查询Invoker",
                        "expected_outcome": "调用订单服务并组装Facade响应",
                    }
                ],
            },
        ],
        "questions": [],
        "source_refs": [],
        "trace_steps": [],
    }
    output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    source_access_path.write_text("", encoding="utf-8")
    evidence = AgentRunEvidence(
        run_id=run_root.name,
        system_id=manifest.system_id,
        agent="codex",
        prompt_digest="0" * 64,
        output_path=str(output_path),
        source_access_path=str(source_access_path),
        exit_code=0,
        elapsed_seconds=1,
    )

    # 多节点Facade也必须形成结构化执行路径，不能因确定性闭包节点数大于1而绕过完成门禁。
    with pytest.raises(KnowledgeValidationError, match="structured business trace"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    facade_relative_path = facade_path.relative_to(source_root).as_posix()
    downstream_path = invoker_path.relative_to(source_root).as_posix()
    service_relative_path = service_path.relative_to(source_root).as_posix()
    dao_relative_path = dao_path.relative_to(source_root).as_posix()
    facade_reference = {"path": facade_relative_path, "symbol": "DynamicRefundFacadeImpl#queryList", "line": 1}
    invoker_reference = {"path": downstream_path, "symbol": "RefundOrderListQueryInvoker#invoke", "line": 2}
    service_reference = {"path": service_relative_path, "symbol": "OrderServiceImpl#queryOrderList", "line": 2}
    dao_reference = {"path": dao_relative_path, "symbol": "SaasRefundOrderDAOProxy#listPage", "line": 2}
    envelope["source_refs"] = [
        facade_reference,
        invoker_reference,
    ]
    envelope["trace_steps"] = [
        {"sequence": 1, "role": "entry", "source_ref": facade_reference, "summary": "进入退款列表Facade。"},
        {"sequence": 2, "role": "invoker", "source_ref": invoker_reference, "summary": "动态分发到列表Invoker。"},
    ]
    output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    source_access_path.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                {
                    "sequence": 1,
                    "tool": "read_source",
                    "path": facade_relative_path,
                    "start_line": 1,
                    "end_line": 1,
                    "result_count": 1,
                    "created_at": "2026-08-23T00:00:00Z",
                },
                {
                    "sequence": 2,
                    "tool": "read_source",
                    "path": downstream_path,
                    "start_line": 2,
                    "end_line": 2,
                    "result_count": 1,
                    "created_at": "2026-08-23T00:00:00Z",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="core service"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    envelope["source_refs"] = [
        facade_reference,
        invoker_reference,
        service_reference,
        dao_reference,
    ]
    envelope["trace_steps"] = [
        {"sequence": 1, "role": "entry", "source_ref": facade_reference, "summary": "进入退款列表Facade。"},
        {"sequence": 2, "role": "invoker", "source_ref": invoker_reference, "summary": "动态分发到列表Invoker。"},
        {"sequence": 3, "role": "service", "source_ref": service_reference, "summary": "执行列表过滤和分页。"},
        {"sequence": 4, "role": "data_access", "source_ref": dao_reference, "summary": "通过DAO进入分页数据查询。"},
    ]
    output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    source_access_path.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                {
                    "sequence": 1,
                    "tool": "read_source",
                    "path": facade_relative_path,
                    "start_line": 1,
                    "end_line": 1,
                    "result_count": 1,
                    "created_at": "2026-08-23T00:00:00Z",
                },
                {
                    "sequence": 2,
                    "tool": "read_source",
                    "path": downstream_path,
                    "start_line": 2,
                    "end_line": 2,
                    "result_count": 1,
                    "created_at": "2026-08-23T00:00:00Z",
                },
                {
                    "sequence": 3,
                    "tool": "read_source",
                    "path": service_relative_path,
                    "start_line": 2,
                    "end_line": 2,
                    "result_count": 1,
                    "created_at": "2026-08-23T00:00:00Z",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not read through the registered source tool"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    source_access_path.write_text(
        source_access_path.read_text(encoding="utf-8")
        + json.dumps(
            {
                "sequence": 4,
                "tool": "read_source",
                "path": dao_relative_path,
                "start_line": 1,
                "end_line": 1,
                "result_count": 1,
                "created_at": "2026-08-23T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="referenced line was not read"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    # 最后一条DAO审计补到实际引用行，前面三段已读路径保持不变。
    access_records = [
        json.loads(line)
        for line in source_access_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    access_records[-1]["start_line"] = 2
    access_records[-1]["end_line"] = 2
    source_access_path.write_text(
        "\n".join(json.dumps(item) for item in access_records) + "\n",
        encoding="utf-8",
    )

    validated = service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))
    merged = service._merge_agent_source_refs(nodes, validated)

    assert downstream_path in {reference.path for reference in merged[0].source_refs}

    # 并列Service方法必须各自拥有真实read_source证据；只读取列表方法不能夹带计数方法。
    invoker_path.write_text(
        "@RefundOrderService(RefundOrderServiceEnum.QUERY_LIST) class RefundOrderListQueryInvoker {\n"
        "  OrderServiceImpl orderService; Object invoke(Object request) { orderService.queryOrderList(request); return orderService.queryOrderListCount(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  SaasRefundOrderDAOProxy orderDAO; Object queryOrderList(Object request) { return orderDAO.listPage(request); }\n"
        "  Object queryOrderListCount(Object request) { return request; }\n"
        "}\n",
        encoding="utf-8",
    )
    combined_service_reference = {
        "path": service_relative_path,
        "symbol": "OrderServiceImpl#queryOrderList/queryOrderListCount",
        "line": 2,
    }
    count_service_reference = {
        "path": service_relative_path,
        "symbol": "OrderServiceImpl#queryOrderListCount",
        "line": 3,
    }
    combined_envelope = json.loads(json.dumps(envelope))
    combined_envelope["source_refs"] = [
        facade_reference,
        invoker_reference,
        combined_service_reference,
        service_reference,
        count_service_reference,
        dao_reference,
    ]
    combined_envelope["trace_steps"][2]["source_ref"] = combined_service_reference
    output_path.write_text(json.dumps(combined_envelope, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="referenced line was not read"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    # 第二个方法的独立声明行补入访问审计后，组合Service步骤及其线性主路径可以发布。
    source_access_path.write_text(
        source_access_path.read_text(encoding="utf-8")
        + json.dumps(
            {
                "sequence": 5,
                "tool": "read_source",
                "path": service_relative_path,
                "start_line": 3,
                "end_line": 3,
                "result_count": 1,
                "created_at": "2026-08-23T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))
    output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    invoker_path.write_text(
        "@RefundOrderService(RefundOrderServiceEnum.QUERY_LIST) class RefundOrderListQueryInvoker {\n"
        "  OrderServiceImpl orderService; Object invoke(Object request) { return orderService.queryOrderList(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  SaasRefundOrderDAOProxy orderDAO; Object queryOrderList(Object request) { return orderDAO.listPage(request); }\n"
        "}\n",
        encoding="utf-8",
    )

    # 同一Facade实现文件的其他真实方法即使拥有完整下游链，也不能冒充当前queryList入口。
    facade_path.write_text(
        "class DynamicRefundFacadeImpl { Object queryList(Object request) { return execute(RefundOrderServiceEnum.QUERY_LIST); } Object queryDetailByRefundNo(Object request) { return execute(RefundOrderServiceEnum.QUERY_LIST); } }\n",
        encoding="utf-8",
    )
    wrong_entry_envelope = json.loads(json.dumps(envelope))
    wrong_entry_reference = {
        **facade_reference,
        "symbol": "DynamicRefundFacadeImpl#queryDetailByRefundNo",
    }
    wrong_entry_envelope["source_refs"][0] = wrong_entry_reference
    wrong_entry_envelope["trace_steps"][0]["source_ref"] = wrong_entry_reference
    output_path.write_text(json.dumps(wrong_entry_envelope, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="requested entry"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))
    output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    facade_path.write_text(
        "class DynamicRefundFacadeImpl { Object queryList(Object request) { return execute(RefundOrderServiceEnum.QUERY_LIST); } }\n",
        encoding="utf-8",
    )

    # 前一无关类型出现相同路由常量，不能替没有绑定注解的目标Invoker建立动态连接。
    invoker_path.write_text(
        "class UnrelatedRouteHolder { Object other() { return execute(RefundOrderServiceEnum.QUERY_LIST); } }\n"
        "class RefundOrderListQueryInvoker { OrderServiceImpl orderService; Object invoke(Object request) { return orderService.queryOrderList(request); } }\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))
    invoker_path.write_text(
        "@RefundOrderService(RefundOrderServiceEnum.QUERY_LIST) class RefundOrderListQueryInvoker {\n"
        "  OrderServiceImpl orderService; Object invoke(Object request) { return orderService.queryOrderList(request); }\n"
        "}\n",
        encoding="utf-8",
    )

    # 常见方法名和若干相似业务词不能替代真实类型绑定；错误接收器的listPage必须被拒绝。
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  RefundDetailQueryInvoker refundDetailQueryInvoker; Object queryOrderList(Object request) { return refundDetailQueryInvoker.listPage(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  SaasRefundOrderDAOProxy orderDAO; Object queryOrderList(Object request) { return orderDAO.listPage(request); }\n"
        "}\n",
        encoding="utf-8",
    )

    # 其他方法里的同名正确类型不能替当前方法的错误字段伪造调用关系。
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  RefundDetailQueryInvoker orderDAO; Object queryOrderList(Object request) { return orderDAO.listPage(request); }\n"
        "  void unrelated() { SaasRefundOrderDAOProxy orderDAO = new SaasRefundOrderDAOProxy(); orderDAO.listPage(null); }\n"
        "}\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    # 当前方法的同名局部变量必须遮蔽正确字段，不能让字段类型误证局部变量调用。
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  SaasRefundOrderDAOProxy orderDAO; Object queryOrderList(Object request) { RefundDetailQueryInvoker orderDAO; return orderDAO.listPage(request); }\n"
        "}\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    # 注释和字符串中的伪调用必须在结构匹配前被屏蔽。
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  SaasRefundOrderDAOProxy orderDAO; Object queryOrderList(Object request) { String hint = \"orderDAO.listPage(request)\"; /* orderDAO.listPage(request); */ return request; }\n"
        "}\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    # 动态路由常量只出现在注释时也不能连接Facade和Invoker。
    facade_path.write_text(
        "class DynamicRefundFacadeImpl { Object queryList(Object request) { /* RefundOrderServiceEnum.QUERY_LIST */ return request; } }\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))
    facade_path.write_text(
        "class DynamicRefundFacadeImpl { Object queryList(Object request) { return execute(RefundOrderServiceEnum.QUERY_LIST); } }\n",
        encoding="utf-8",
    )
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  SaasRefundOrderDAOProxy orderDAO; Object queryOrderList(Object request) { return orderDAO.listPage(request); }\n"
        "}\n",
        encoding="utf-8",
    )

    # 真实读取过文件和行号仍不足以证明Agent填写的符号；伪造Service名称必须被拒绝。
    forged_symbol_envelope = json.loads(json.dumps(envelope))
    forged_service_reference = {
        **service_reference,
        "symbol": "FakeService#queryOrderList",
    }
    forged_symbol_envelope["source_refs"][2] = forged_service_reference
    forged_symbol_envelope["trace_steps"][2]["source_ref"] = forged_service_reference
    output_path.write_text(json.dumps(forged_symbol_envelope, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="source symbol"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))

    # 每个符号分别存在也不能组成虚构链；Service没有调用DAO时必须拒绝相邻步骤。
    output_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    service_path.write_text(
        "class OrderServiceImpl {\n"
        "  Object queryOrderList(Object request) { return request; }\n"
        "}\n",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_evidence(request, manifest, nodes, evidence, str(source_root))


def test_agent_java_reference_binds_declared_type_line_and_overload(tmp_path: Path) -> None:
    """Java证据必须绑定指定类型中由引用行选中的唯一同名重载。

    Args:
        tmp_path: Pytest提供的隔离知识存储和源码目录。

    Returns:
        None；跨类型伪造被拒绝且第二个重载的真实正文被精确提取时通过。
    """

    service, _, _ = _knowledge_service(tmp_path)

    # 同文件另一个类型拥有同名方法时，不能把它冒充为目标类型的方法证据。
    wrong_type_lines = [
        "class TargetType { Object other(Object input) { return input; } }",
        "class OtherType { Object invoke(Object input) { return input; } }",
    ]
    with pytest.raises(KnowledgeValidationError, match="method is absent"):
        service._validate_agent_source_symbol(
            SourceReference(path="TargetType.java", symbol="TargetType#invoke", line=2),
            wrong_type_lines,
        )

    # 引用行落在第二个重载时，符号校验和相邻链证明必须复用同一个方法体。
    overloaded_lines = [
        "class TargetType {",
        "  Object invoke(Object input) { return input; }",
        "  Object invoke(String input) { return downstream.listPage(input); }",
        "}",
    ]
    reference = SourceReference(path="TargetType.java", symbol="TargetType#invoke", line=3)
    service._validate_agent_source_symbol(reference, overloaded_lines)
    reference_block = service._agent_reference_block(reference, overloaded_lines)

    assert "downstream.listPage" in reference_block
    assert "return input" not in reference_block


def test_agent_trace_accepts_single_word_qualified_route_and_rejects_other_enum(tmp_path: Path) -> None:
    """动态分发应接受同枚举的CANCEL路由并拒绝其他枚举下的同名常量。

    Args:
        tmp_path: Pytest提供的隔离知识存储目录。

    Returns:
        None；精确枚举身份连接成功且同名跨枚举连接被拒绝时通过。
    """

    service, _, _ = _knowledge_service(tmp_path)
    entry_reference = SourceReference(
        path="RefundFacadeImpl.java",
        symbol="RefundFacadeImpl#cancel",
        line=1,
    )
    invoker_reference = SourceReference(
        path="RefundCancelServiceInvoker.java",
        symbol="RefundCancelServiceInvoker#invoke",
        line=2,
    )
    entry_agent_reference = {
        "path": entry_reference.path,
        "symbol": entry_reference.symbol,
        "line": entry_reference.line,
    }
    invoker_agent_reference = {
        "path": invoker_reference.path,
        "symbol": invoker_reference.symbol,
        "line": invoker_reference.line,
    }
    envelope = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": ["facade:demo.RefundFacade#cancel"],
            "summaries": [],
            "questions": [],
            "source_refs": [
                entry_agent_reference,
                invoker_agent_reference,
            ],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "entry",
                    "source_ref": entry_agent_reference,
                    "summary": "取消入口按退款服务枚举选择动态处理器。",
                },
                {
                    "sequence": 2,
                    "role": "invoker",
                    "source_ref": invoker_agent_reference,
                    "summary": "取消处理器声明相同的退款服务路由。",
                },
            ],
        }
    )
    caller_lines = [
        "class RefundFacadeImpl { Object cancel(Object request) { "
        "return execute(request, RefundOrderServiceEnum.CANCEL); } }"
    ]
    matching_invoker_lines = [
        "@TradeService(name = RefundOrderServiceEnum.CANCEL)",
        "class RefundCancelServiceInvoker { Object invoke(Object request) { return request; } }",
    ]
    route_node = KnowledgeNode(
        node_id="logic:RefundCancelServiceInvoker#invoke",
        system_id="demo-system",
        kind=KnowledgeNodeKind.COMMON_LOGIC,
        title="RefundCancelServiceInvoker#invoke",
        source_refs=[invoker_reference],
        status=KnowledgeStatus.CODE_VERIFIED,
    )

    # 相同枚举类型和代码扫描固化的处理器身份共同证明Facade到Invoker的动态分发边。
    service._validate_agent_trace_links(
        envelope,
        {
            entry_reference.path: caller_lines,
            invoker_reference.path: matching_invoker_lines,
        },
        [route_node],
    )

    # 常量名称相同但枚举类型不同不能建立路由，避免COMMON、CANCEL等短值误连。
    mismatched_reference = SourceReference(
        path="OtherCancelServiceInvoker.java",
        symbol="OtherCancelServiceInvoker#invoke",
        line=2,
    )
    mismatched_envelope = envelope.model_copy(
        update={
            "trace_steps": [
                envelope.trace_steps[0],
                envelope.trace_steps[1].model_copy(update={"source_ref": mismatched_reference}),
            ]
        }
    )
    mismatched_invoker_lines = [
        "@TradeService(name = OtherServiceEnum.CANCEL)",
        "class OtherCancelServiceInvoker { Object invoke(Object request) { return request; } }",
    ]
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            mismatched_envelope,
            {
                entry_reference.path: caller_lines,
                mismatched_reference.path: mismatched_invoker_lines,
            },
            [route_node],
        )


def test_agent_trace_accepts_proven_inheritance_and_interface_dispatch(tmp_path: Path) -> None:
    """相邻链应接受已证明的继承、接口分派和同类辅助方法压缩。

    Args:
        tmp_path: Pytest提供的隔离知识存储目录。

    Returns:
        None；Java多态连接和真实可达的包装方法均无需插入虚假步骤即可通过。
    """

    service, _, _ = _knowledge_service(tmp_path)
    inherited_entry = SourceReference(path="RefundFacadeImpl.java", symbol="RefundFacadeImpl#queryList", line=1)
    inherited_target = SourceReference(path="AbstractFacade.java", symbol="AbstractFacade#execute", line=1)
    inherited_envelope = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": ["facade:demo.RefundFacade#queryList"],
            "summaries": [],
            "questions": [],
            "source_refs": [
                {"path": inherited_entry.path, "symbol": inherited_entry.symbol, "line": inherited_entry.line},
                {"path": inherited_target.path, "symbol": inherited_target.symbol, "line": inherited_target.line},
            ],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "entry",
                    "source_ref": {
                        "path": inherited_entry.path,
                        "symbol": inherited_entry.symbol,
                        "line": inherited_entry.line,
                    },
                    "summary": "实现入口调用父类执行重载。",
                },
                {
                    "sequence": 2,
                    "role": "invoker",
                    "source_ref": {
                        "path": inherited_target.path,
                        "symbol": inherited_target.symbol,
                        "line": inherited_target.line,
                    },
                    "summary": "父类提供受保护执行方法。",
                },
            ],
        }
    )
    service._validate_agent_trace_links(
        inherited_envelope,
        {
            inherited_entry.path: [
                "class RefundFacadeImpl extends AbstractFacade { Object queryList(Object request) { return this.execute(request); } }"
            ],
            inherited_target.path: ["class AbstractFacade { Object execute(Object request) { return request; } }"],
        },
    )

    interface_entry = SourceReference(path="AbstractFacade.java", symbol="AbstractFacade#execute", line=1)
    implementation_target = SourceReference(
        path="DefaultTradeServiceProxy.java",
        symbol="DefaultTradeServiceProxy#invoke",
        line=1,
    )
    interface_envelope = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": ["facade:demo.RefundFacade#queryList"],
            "summaries": [],
            "questions": [],
            "source_refs": [
                {"path": interface_entry.path, "symbol": interface_entry.symbol, "line": interface_entry.line},
                {
                    "path": implementation_target.path,
                    "symbol": implementation_target.symbol,
                    "line": implementation_target.line,
                },
            ],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "invoker",
                    "source_ref": {
                        "path": interface_entry.path,
                        "symbol": interface_entry.symbol,
                        "line": interface_entry.line,
                    },
                    "summary": "父类通过代理接口字段调用。",
                },
                {
                    "sequence": 2,
                    "role": "invoker",
                    "source_ref": {
                        "path": implementation_target.path,
                        "symbol": implementation_target.symbol,
                        "line": implementation_target.line,
                    },
                    "summary": "默认代理实现接口并处理调用。",
                },
            ],
        }
    )
    service._validate_agent_trace_links(
        interface_envelope,
        {
            interface_entry.path: [
                "class AbstractFacade { TradeServiceProxy proxy; Object execute(Object request) { return proxy.invoke(request); } }"
            ],
            implementation_target.path: [
                "class DefaultTradeServiceProxy implements TradeServiceProxy { Object invoke(Object request) { return request; } }"
            ],
        },
    )

    inherited_field_entry = SourceReference(
        path="OrderServiceImpl.java",
        symbol="OrderServiceImpl#queryOrderList",
        line=1,
    )
    inherited_field_owner = SourceReference(
        path="AbstractOrderService.java",
        symbol="AbstractOrderService",
        line=1,
    )
    dao_target = SourceReference(
        path="SaasRefundOrderDAOProxy.java",
        symbol="SaasRefundOrderDAOProxy#listPage",
        line=1,
    )
    inherited_field_envelope = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": ["facade:demo.RefundFacade#queryList"],
            "summaries": [],
            "questions": [],
            "source_refs": [
                {
                    "path": inherited_field_entry.path,
                    "symbol": inherited_field_entry.symbol,
                    "line": inherited_field_entry.line,
                },
                {
                    "path": inherited_field_owner.path,
                    "symbol": inherited_field_owner.symbol,
                    "line": inherited_field_owner.line,
                },
                {"path": dao_target.path, "symbol": dao_target.symbol, "line": dao_target.line},
            ],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "service",
                    "source_ref": {
                        "path": inherited_field_entry.path,
                        "symbol": inherited_field_entry.symbol,
                        "line": inherited_field_entry.line,
                    },
                    "summary": "实现服务通过继承字段读取订单数据。",
                },
                {
                    "sequence": 2,
                    "role": "data_access",
                    "source_ref": {
                        "path": dao_target.path,
                        "symbol": dao_target.symbol,
                        "line": dao_target.line,
                    },
                    "summary": "DAO执行分页读取。",
                },
            ],
        }
    )
    service._validate_agent_trace_links(
        inherited_field_envelope,
        {
            inherited_field_entry.path: [
                "class OrderServiceImpl extends AbstractOrderService { Object queryOrderList(Object request) { return orderDAO.listPage(request); } }"
            ],
            inherited_field_owner.path: [
                'class AbstractOrderService { @Resource(name="orderDAO") '
                "SaasRefundOrderDAOProxy orderDAO; }"
            ],
            dao_target.path: [
                "class SaasRefundOrderDAOProxy { Object listPage(Object request) { return request; } }"
            ],
        },
    )

    compressed_entry = SourceReference(
        path="RefundCancelServiceInvoker.java",
        symbol="RefundCancelServiceInvoker#invoke",
        line=2,
    )
    compressed_target = SourceReference(
        path="AbstractOrderServiceInvoker.java",
        symbol="AbstractOrderServiceInvoker#queryOrderByRefundSerialNo",
        line=2,
    )
    compressed_envelope = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": ["facade:demo.RefundFacade#cancel"],
            "summaries": [],
            "questions": [],
            "source_refs": [
                {
                    "path": compressed_entry.path,
                    "symbol": compressed_entry.symbol,
                    "line": compressed_entry.line,
                },
                {
                    "path": compressed_target.path,
                    "symbol": compressed_target.symbol,
                    "line": compressed_target.line,
                },
            ],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "invoker",
                    "source_ref": {
                        "path": compressed_entry.path,
                        "symbol": compressed_entry.symbol,
                        "line": compressed_entry.line,
                    },
                    "summary": "加锁入口经同类包装方法查询订单。",
                },
                {
                    "sequence": 2,
                    "role": "service",
                    "source_ref": {
                        "path": compressed_target.path,
                        "symbol": compressed_target.symbol,
                        "line": compressed_target.line,
                    },
                    "summary": "父类服务方法执行订单查询。",
                },
            ],
        }
    )
    # invoke到父类查询间的innerInvoke/doInvoke只是同类转发，trace可压缩但仍由源码证明可达。
    service._validate_agent_trace_links(
        compressed_envelope,
        {
            compressed_entry.path: [
                "class RefundCancelServiceInvoker extends AbstractOrderServiceInvoker {",
                "  Object invoke(Object request) { return innerInvoke(request); }",
                "  Object innerInvoke(Object request) { return doInvoke(request); }",
                "  Object doInvoke(Object request) { return queryOrderByRefundSerialNo(request); }",
                "}",
            ],
            compressed_target.path: [
                "class AbstractOrderServiceInvoker {",
                "  Object queryOrderByRefundSerialNo(Object request) { return request; }",
                "}",
            ],
        },
    )


def test_agent_trace_rejects_generic_arguments_suffix_guess_and_uninvoked_override(tmp_path: Path) -> None:
    """泛型实参、实现后缀和未调用的同名override不能伪造多态连接。

    Args:
        tmp_path: Pytest提供的隔离知识存储目录。

    Returns:
        None；三类名称相似但无真实调用或声明关系的路径均被拒绝时通过。
    """

    service, _, _ = _knowledge_service(tmp_path)

    def envelope_for(
        previous_path: str,
        previous_symbol: str,
        next_path: str,
        next_symbol: str,
    ) -> AgentKnowledgeEnvelope:
        """构造只用于相邻多态负例的两步严格信封。

        Args:
            previous_path: 调用方测试文件名。
            previous_symbol: 调用方精确类型与方法。
            next_path: 被声称下游的测试文件名。
            next_symbol: 被声称下游的精确类型与方法。

        Returns:
            两步源码引用均完整但尚未验证连接关系的Agent信封。
        """

        previous_reference = {"path": previous_path, "symbol": previous_symbol, "line": 1}
        next_reference = {"path": next_path, "symbol": next_symbol, "line": 1}
        return AgentKnowledgeEnvelope.model_validate(
            {
                "status": "completed",
                "system_id": "demo-system",
                "target_ids": ["facade:demo.Query#list"],
                "summaries": [],
                "questions": [],
                "source_refs": [previous_reference, next_reference],
                "trace_steps": [
                    {
                        "sequence": 1,
                        "role": "service",
                        "source_ref": previous_reference,
                        "summary": "调用方测试步骤。",
                    },
                    {
                        "sequence": 2,
                        "role": "data_access",
                        "source_ref": next_reference,
                        "summary": "被声称的下游测试步骤。",
                    },
                ],
            }
        )

    generic_envelope = envelope_for("Caller.java", "Caller#call", "Impl.java", "Impl#invoke")
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            generic_envelope,
            {
                "Caller.java": [
                    "class Caller { WrongType receiver; Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "Impl.java": [
                    "class Impl implements Port<Key, WrongType> { Object invoke(Object value) { return value; } }"
                ],
            },
        )

    suffix_envelope = envelope_for(
        "Caller.java",
        "Caller#call",
        "OrderServiceImpl.java",
        "OrderServiceImpl#invoke",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            suffix_envelope,
            {
                "Caller.java": [
                    "class Caller { OrderService receiver; Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "OrderServiceImpl.java": [
                    "class OrderServiceImpl { Object invoke(Object value) { return value; } }"
                ],
            },
        )

    static_shadow_envelope = envelope_for(
        "StaticShadowCaller.java",
        "StaticShadowCaller#call",
        "OrderServiceImpl.java",
        "OrderServiceImpl#invoke",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            static_shadow_envelope,
            {
                "StaticShadowCaller.java": [
                    "class StaticShadowCaller { Object OrderServiceImpl; "
                    "Object call(Object value) { return OrderServiceImpl.invoke(value); } }"
                ],
                "OrderServiceImpl.java": [
                    "class OrderServiceImpl { Object invoke(Object value) { return value; } }"
                ],
            },
        )

    inherited_suffix_envelope = envelope_for(
        "ChildCaller.java",
        "ChildCaller#call",
        "OrderServiceProxy.java",
        "OrderServiceProxy#invoke",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            inherited_suffix_envelope,
            {
                "ChildCaller.java": [
                    "class ChildCaller extends ParentCaller { "
                    "Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "ParentCaller.java": ["class ParentCaller { OrderService receiver; }"],
                "OrderServiceProxy.java": [
                    "class OrderServiceProxy { Object invoke(Object value) { return value; } }"
                ],
            },
        )

    package_collision_envelope = envelope_for(
        "PackageCaller.java",
        "PackageCaller#call",
        "Impl.java",
        "Impl#invoke",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            package_collision_envelope,
            {
                "PackageCaller.java": [
                    "package caller; class PackageCaller { a.Port receiver; "
                    "Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "Impl.java": [
                    "package target; class Impl implements b.Port { "
                    "Object invoke(Object value) { return value; } }"
                ],
            },
        )

    nested_package_collision = envelope_for(
        "NestedPackageCaller.java",
        "NestedPackageCaller#call",
        "NestedImpl.java",
        "NestedImpl#invoke",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            nested_package_collision,
            {
                "NestedPackageCaller.java": [
                    "package caller; import a.Outer; class NestedPackageCaller { Outer.Port receiver; "
                    "Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "NestedImpl.java": [
                    "package target; import b.Outer; class NestedImpl implements Outer.Port { "
                    "Object invoke(Object value) { return value; } }"
                ],
            },
        )

    nested_declaration_collision = envelope_for(
        "NestedDeclarationCaller.java",
        "NestedDeclarationCaller#call",
        "Outer.java",
        "Inner#invoke",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            nested_declaration_collision,
            {
                "NestedDeclarationCaller.java": [
                    "package a; class NestedDeclarationCaller { a.Inner receiver; "
                    "Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "Outer.java": [
                    "package a; class Outer { class Inner { "
                    "Object invoke(Object value) { return value; } } }"
                ],
            },
        )

    multi_method_without_evidence = envelope_for(
        "MultiMethodCaller.java",
        "MultiMethodCaller#call",
        "MultiMethodService.java",
        "MultiMethodService#invoke/deleteEverything",
    )
    # 即使两个调用都存在，组合步骤也不能凭单个trace引用声称已经读取另一个方法。
    with pytest.raises(KnowledgeValidationError, match="independently read"):
        service._validate_agent_trace_links(
            multi_method_without_evidence,
            {
                "MultiMethodCaller.java": [
                    "class MultiMethodCaller { MultiMethodService receiver; "
                    "Object call(Object value) { receiver.invoke(value); "
                    "receiver.deleteEverything(); return value; } }"
                ],
                "MultiMethodService.java": [
                    "class MultiMethodService { Object invoke(Object value) { return value; } "
                    "void deleteEverything() { } }"
                ],
            },
        )

    multi_method_envelope = multi_method_without_evidence.model_copy(
        update={
            "source_refs": [
                *multi_method_without_evidence.source_refs,
                AgentKnowledgeSourceReference(
                    path="MultiMethodService.java",
                    symbol="MultiMethodService#invoke",
                    line=1,
                ),
                AgentKnowledgeSourceReference(
                    path="MultiMethodService.java",
                    symbol="MultiMethodService#deleteEverything",
                    line=1,
                ),
            ]
        }
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            multi_method_envelope,
            {
                "MultiMethodCaller.java": [
                    "class MultiMethodCaller { MultiMethodService receiver; "
                    "Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "MultiMethodService.java": [
                    "class MultiMethodService { Object invoke(Object value) { return value; } "
                    "void deleteEverything() { } }"
                ],
            },
        )

    # 组合服务步骤允许表达同一Invoker真实并列调用，但每个方法都要有独立声明证据。
    service._validate_agent_trace_links(
        multi_method_envelope,
        {
            "MultiMethodCaller.java": [
                "class MultiMethodCaller { MultiMethodService receiver; "
                "Object call(Object value) { receiver.invoke(value); "
                "receiver.deleteEverything(); return value; } }"
            ],
            "MultiMethodService.java": [
                "class MultiMethodService { Object invoke(Object value) { return value; } "
                "void deleteEverything() { } }"
            ],
        },
    )

    inherited_package_collision = envelope_for(
        "PackageChild.java",
        "PackageChild#call",
        "Impl.java",
        "Impl#invoke",
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            inherited_package_collision,
            {
                "PackageChild.java": [
                    "package caller; class PackageChild extends com.real.AbstractBase { "
                    "Object call(Object value) { return receiver.invoke(value); } }"
                ],
                "WrongBase.java": [
                    "package com.other; class AbstractBase { b.Port receiver; }"
                ],
                "Impl.java": [
                    "package target; class Impl implements b.Port { "
                    "Object invoke(Object value) { return value; } }"
                ],
            },
        )

    override_envelope = envelope_for("Child.java", "Child#execute", "Base.java", "Base#execute")
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            override_envelope,
            {
                "Child.java": [
                    "class Child extends Base { Object execute(Object value) { return value; } }"
                ],
                "Base.java": ["class Base { Object execute(Object value) { return value; } }"],
            },
        )

    shadowed_parent_envelope = envelope_for("Child.java", "Child#call", "Base.java", "Base#execute")
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            shadowed_parent_envelope,
            {
                "Child.java": [
                    "class Child extends Base { Object call(Object value) { return execute(value); } "
                    "Object execute(Object value) { return value; } }"
                ],
                "Base.java": ["class Base { Object execute(Object value) { return value; } }"],
            },
        )

    # 显式super调用是由源码证明的真实父类边，不能与未调用override一起误拒绝。
    service._validate_agent_trace_links(
        override_envelope,
        {
            "Child.java": [
                "class Child extends Base { Object execute(Object value) { return super.execute(value); } }"
            ],
            "Base.java": ["class Base { Object execute(Object value) { return value; } }"],
        },
    )


def test_agent_trace_accepts_java_dao_call_to_xml_mapper_boundary(tmp_path: Path) -> None:
    """Java DAO调用真实Mapper方法时应连接到已验证XML声明而不是触发服务器异常。

    Args:
        tmp_path: Pytest提供的隔离知识存储目录。

    Returns:
        None；真实调用通过且缺少调用的伪边界被明确拒绝时通过。
    """

    service, _, _ = _knowledge_service(tmp_path)
    envelope = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": ["facade:demo.QueryFacade#queryList"],
            "summaries": [],
            "questions": [],
            "source_refs": [
                {"path": "QueryDAO.java", "symbol": "QueryDAO#listPage", "line": 1},
                {"path": "QueryMapper.xml", "symbol": "listPage", "line": 2},
            ],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "data_access",
                    "source_ref": {"path": "QueryDAO.java", "symbol": "QueryDAO#listPage", "line": 1},
                    "summary": "DAO调用Mapper执行分页查询。",
                },
                {
                    "sequence": 2,
                    "role": "data_access",
                    "source_ref": {"path": "QueryMapper.xml", "symbol": "listPage", "line": 2},
                    "summary": "Mapper声明真实分页SQL。",
                },
            ],
        }
    )
    mapper_lines = ["<mapper>", '  <select id="listPage">select 1</select>', "</mapper>"]

    service._validate_agent_trace_links(
        envelope,
        {
            "QueryDAO.java": [
                "class QueryDAO { QueryMapper mapper; Object listPage(Object query) { return mapper.listPage(query); } }"
            ],
            "QueryMapper.xml": mapper_lines,
        },
    )
    with pytest.raises(KnowledgeValidationError, match="not connected"):
        service._validate_agent_trace_links(
            envelope,
            {
                "QueryDAO.java": [
                    "class QueryDAO { Object listPage(Object query) { return query; } }"
                ],
                "QueryMapper.xml": mapper_lines,
            },
        )


def test_mapper_reference_requires_one_real_id_declaration(tmp_path: Path) -> None:
    """Mapper引用不能把include、注释或重复id规范化成唯一声明。

    Args:
        tmp_path: Pytest提供的隔离知识存储目录。

    Returns:
        None；只有一个真实Mapper元素id可通过，其他相似文本均被拒绝时通过。
    """

    service, _, _ = _knowledge_service(tmp_path)
    include_lines = [
        '<mapper namespace="demo.Mapper">',
        '  <!-- <select id="listPage">ignored</select> -->',
        '  <include refid="listPage"/>',
        "</mapper>",
    ]
    include_reference = SourceReference(path="DemoMapper.xml", symbol="DemoMapper#listPage", line=3)
    normalized_include = service._normalize_client_source_reference(
        include_reference,
        include_lines,
        [(1, 4)],
    )

    assert normalized_include.symbol == include_reference.symbol
    assert normalized_include.line == include_reference.line
    with pytest.raises(KnowledgeValidationError, match="Mapper"):
        service._validate_agent_source_symbol(
            SourceReference(path="DemoMapper.xml", symbol="listPage", line=3),
            include_lines,
        )

    duplicate_lines = [
        '<mapper namespace="demo.Mapper">',
        '  <select id="listPage">select 1</select>',
        '  <sql id="listPage">id</sql>',
        "</mapper>",
    ]
    normalized_duplicate = service._normalize_client_source_reference(
        SourceReference(path="DemoMapper.xml", symbol="DemoMapper#listPage", line=2),
        duplicate_lines,
        [(1, 4)],
    )

    assert normalized_duplicate.symbol == "DemoMapper#listPage"
    with pytest.raises(KnowledgeValidationError, match="Mapper"):
        service._validate_agent_source_symbol(
            SourceReference(path="DemoMapper.xml", symbol="listPage", line=2),
            duplicate_lines,
        )

    disguised_lines = [
        '<mapper namespace="demo.Mapper">',
        '  <![CDATA[ <select id="listPage"> ]]>',
        '  <select-item id="listPage">not a mapper statement</select-item>',
        "</mapper>",
    ]
    normalized_disguised = service._normalize_client_source_reference(
        SourceReference(path="DemoMapper.xml", symbol="DemoMapper#listPage", line=2),
        disguised_lines,
        [(1, 4)],
    )

    assert normalized_disguised.symbol == "DemoMapper#listPage"
    with pytest.raises(KnowledgeValidationError, match="Mapper"):
        service._validate_agent_source_symbol(
            SourceReference(path="DemoMapper.xml", symbol="listPage", line=2),
            disguised_lines,
        )

    fake_root_lines = [
        '<mapper-item namespace="demo.Mapper">',
        '  <select id="listPage">not inside a mapper root</select>',
        "</mapper-item>",
    ]
    fake_root_reference = SourceReference(path="DemoMapper.xml", symbol="DemoMapper#listPage", line=2)

    normalized_fake_root = service._normalize_client_source_reference(
        fake_root_reference,
        fake_root_lines,
        [(1, 3)],
    )

    assert normalized_fake_root == fake_root_reference

    truncated_lines = [
        '<mapper namespace="demo.Mapper">',
        '  <select id="listPage"',
        "</mapper>",
    ]
    truncated_reference = SourceReference(path="DemoMapper.xml", symbol="DemoMapper#listPage", line=2)

    normalized_truncated = service._normalize_client_source_reference(
        truncated_reference,
        truncated_lines,
        [(1, 3)],
    )

    assert normalized_truncated == truncated_reference
    with pytest.raises(KnowledgeValidationError, match="Mapper"):
        service._validate_agent_source_symbol(
            SourceReference(path="DemoMapper.xml", symbol="listPage", line=2),
            truncated_lines,
        )

    processing_instruction_lines = [
        '<mapper namespace="demo.Mapper">',
        '  <?demo text="<select id=\'listPage\'/>"?>',
        "</mapper>",
    ]
    processing_instruction_reference = SourceReference(
        path="DemoMapper.xml",
        symbol="DemoMapper#listPage",
        line=2,
    )

    normalized_processing_instruction = service._normalize_client_source_reference(
        processing_instruction_reference,
        processing_instruction_lines,
        [(1, 3)],
    )

    assert normalized_processing_instruction == processing_instruction_reference

    quoted_attribute_lines = [
        '<mapper namespace="demo.Mapper">',
        '  <select note=" id=\'listPage\' ">select 1</select>',
        "</mapper>",
    ]
    quoted_attribute_reference = SourceReference(
        path="DemoMapper.xml",
        symbol="DemoMapper#listPage",
        line=2,
    )

    normalized_quoted_attribute = service._normalize_client_source_reference(
        quoted_attribute_reference,
        quoted_attribute_lines,
        [(1, 3)],
    )

    assert normalized_quoted_attribute == quoted_attribute_reference


def test_java_reference_requires_one_method_declaration_on_evidence_line(tmp_path: Path) -> None:
    """Java简称与完整符号都不能把单行重载自动绑定为唯一成员。

    Args:
        tmp_path: Pytest提供的隔离知识存储目录。

    Returns:
        None；简称保持未补全且严格完整符号因重载歧义被拒绝时通过。
    """

    service, _, _ = _knowledge_service(tmp_path)
    source_lines = [
        "class DemoService { Object execute(String value) { return value; } "
        "Object execute(Integer value) { return value; } }"
    ]
    shorthand = SourceReference(path="DemoService.java", symbol="execute", line=1)

    normalized = service._normalize_client_java_reference(shorthand, source_lines, [(1, 1)])

    assert normalized == shorthand
    with pytest.raises(KnowledgeValidationError, match="multiple overloaded"):
        service._validate_agent_source_symbol(
            SourceReference(path="DemoService.java", symbol="DemoService#execute", line=1),
            source_lines,
        )

    same_name_type_lines = [
        "package demo;",
        "class Outer { class Inner { Object execute(String value) { return value; } } }",
        "class Inner { Object execute(Integer value) { return value; } }",
    ]
    with pytest.raises(KnowledgeValidationError, match="type is absent"):
        service._validate_agent_source_symbol(
            SourceReference(path="Inner.java", symbol="demo.Inner#execute", line=2),
            same_name_type_lines,
        )

    unread_declaration_lines = [
        "class SplitService {",
        "  Object execute(String value) {",
        "    return value;",
        "  }",
        "}",
    ]
    body_reference = SourceReference(path="SplitService.java", symbol="execute", line=3)

    body_only_normalized = service._normalize_client_java_reference(
        body_reference,
        unread_declaration_lines,
        [(3, 3)],
    )

    assert body_only_normalized == body_reference

    wrong_package_lines = [
        "package com.real;",
        "class DemoService { Object execute(String value) { return value; } }",
    ]
    with pytest.raises(KnowledgeValidationError, match="package"):
        service._validate_agent_source_symbol(
            SourceReference(
                path="DemoService.java",
                symbol="com.fake.DemoService#execute",
                line=2,
            ),
            wrong_package_lines,
        )


def test_plain_text_reference_requires_one_accessed_occurrence(tmp_path: Path) -> None:
    """普通非Java文本中的重复词不能按距离被自动改写为唯一符号证据。

    Args:
        tmp_path: Pytest提供的隔离知识存储目录。

    Returns:
        None；重复出现保持原引用并在严格符号校验中被拒绝时通过。
    """

    service, _, _ = _knowledge_service(tmp_path)
    source_lines = ["value: first", "value: second"]
    original = SourceReference(path="notes.yaml", symbol="Demo#value", line=2)

    normalized = service._normalize_client_source_reference(original, source_lines, [(1, 2)])

    assert normalized == original
    with pytest.raises(KnowledgeValidationError, match="absent"):
        service._validate_agent_source_symbol(original, source_lines)


def test_agent_runner_streams_codex_jsonl_and_closes_standard_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex JSONL应逐条落盘，且关闭stdin后不会等待额外输入。

    Args:
        tmp_path: pytest隔离的假Codex、源码和私有事件目录。
        monkeypatch: 把假Codex放到本测试PATH首位。

    Returns:
        None；会话、推理摘要、公开消息、用量和完成证据均可读取时通过。
    """

    executable = tmp_path / "codex"
    executable.write_text(
        "#!/bin/sh\n"
        "if IFS= read -r unexpected; then exit 91; fi\n"
        "printf '%s\\n' "
        "'{\"type\":\"thread.started\",\"thread_id\":\"thread-stream-test\"}' "
        "'{\"type\":\"item.completed\",\"item\":{\"type\":\"reasoning\",\"summary\":\"正在核对分支\"}}' "
        "'{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"{\\\"status\\\":\\\"completed\\\"}\"}}' "
        "'{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":12,\"output_tokens\":4,\"request_id\":\"private-provider-id\"}}'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))

    evidence = runner.run(
        AgentRunRequest(
            system_id="train-booking-core",
            agent="codex",
            prompt="只读分析",
            target_id="facade:demo.Query#list",
        ),
        source,
        evidence_root,
    )
    events = runner.list_events(evidence.run_id, evidence_root)

    assert evidence.session_id == "thread-stream-test"
    assert evidence.timed_out is False
    assert {event.event_type for event in events} >= {
        "run_started",
        "reasoning_summary",
        "agent_message",
        "usage",
        "phase",
    }
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert "private-provider-id" not in " ".join(event.text for event in events)
    assert Path(evidence.output_path).read_text(encoding="utf-8") == '{"status":"completed"}'


def test_agent_runner_passes_a_fully_strict_schema_to_fake_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """假Codex必须先验证实际命令中的严格Schema，再返回一份完整结构化信封。

    Args:
        tmp_path: pytest隔离的假Codex、源码和运行证据目录。
        monkeypatch: 把只读假Codex放到本测试PATH首位。

    Returns:
        None；Schema递归闭合且最终输出完整落盘时通过。
    """

    executable = tmp_path / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "schema_path = sys.argv[sys.argv.index('--output-schema') + 1]\n"
        "schema = json.load(open(schema_path, encoding='utf-8'))\n"
        "def check(node):\n"
        "    if node.get('type') == 'object':\n"
        "        props = node.get('properties', {})\n"
        "        assert node.get('additionalProperties') is False\n"
        "        assert set(node.get('required', [])) == set(props)\n"
        "        assert len(node.get('required', [])) == len(props)\n"
        "    for key in ('properties', '$defs'):\n"
        "        for child in node.get(key, {}).values(): check(child)\n"
        "    if isinstance(node.get('items'), dict): check(node['items'])\n"
        "    for key in ('anyOf', 'oneOf'):\n"
        "        for child in node.get(key, []): check(child)\n"
        "check(schema)\n"
        "payload = {'status':'completed','system_id':'train-booking-core','target_ids':['facade:demo.Query#list'],"
        "'summaries':[],'questions':[],'source_refs':[],'trace_steps':[]}\n"
        "print(json.dumps({'type':'thread.started','thread_id':'thread-strict-schema'}), flush=True)\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(payload)}}), flush=True)\n"
        "print(json.dumps({'type':'turn.completed','usage':{}}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"

    # 传入生产模型生成的真实Schema，假CLI会在输出任何成功事件前自行递归校验。
    evidence = AgentRunner(AgentRunnerConfig(codex_executable="codex")).run(
        AgentRunRequest(
            system_id="train-booking-core",
            agent="codex",
            prompt="只读分析",
            target_id="facade:demo.Query#list",
            output_schema=AgentKnowledgeEnvelope.model_json_schema(),
        ),
        source,
        evidence_root,
    )

    assert evidence.session_id == "thread-strict-schema"
    assert json.loads(Path(evidence.output_path).read_text(encoding="utf-8"))["summaries"] == []


def test_codex_app_server_prefers_desktop_bundled_executable(tmp_path: Path) -> None:
    """客户端接管必须优先使用桌面同版本二进制，避免旧PATH CLI缺少新模型。

    Args:
        tmp_path: pytest隔离的可执行候选目录。

    Returns:
        None；可执行桌面候选被选择且候选缺失时回落``codex``即通过。
    """

    bundled = tmp_path / "ChatGPT.app" / "Contents" / "Resources" / "codex"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    bundled.chmod(0o755)

    assert _resolve_codex_app_server_executable((bundled,)) == str(bundled)
    assert _resolve_codex_app_server_executable((tmp_path / "missing-codex",)) == "codex"


@pytest.mark.parametrize("reasoning_effort", ["medium", "low"])
def test_codex_app_server_accepts_luna_only_when_local_catalog_lists_effort(
    reasoning_effort: str,
) -> None:
    """Luna只能在本机模型目录明确列出目标档位时通过启动前门禁。

    Args:
        reasoning_effort: 页面允许选择的Medium或Low档位。

    Returns:
        None；两个合法档位通过，目录未声明的档位仍被明确拒绝时通过。
    """

    client = CodexAppServerClient()
    payload = {
        "data": [
            {
                "id": "gpt-5.6-luna",
                "supportedReasoningEfforts": ["low", "medium"],
            }
        ]
    }

    client._require_model_effort(payload, "gpt-5.6-luna", reasoning_effort)
    with pytest.raises(ExecutionFailure, match="does not support reasoning effort"):
        client._require_model_effort(payload, "gpt-5.6-luna", "high")


def test_codex_app_server_creates_and_injects_thread_without_starting_a_turn(
    tmp_path: Path,
) -> None:
    """客户端接管只应创建持久线程和聊天历史，不得自动发送模型turn。

    Args:
        tmp_path: pytest隔离的假Codex App Server、协议记录和工作目录。

    Returns:
        None；线程可深链打开、Prompt已注入且协议中没有turn/start时通过。
    """

    executable = tmp_path / "codex"
    request_log = tmp_path / "app-server-requests.jsonl"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log_path = {str(request_log)!r}\n"
        "for raw in sys.stdin:\n"
        "    request = json.loads(raw)\n"
        "    with open(log_path, 'a', encoding='utf-8') as handle:\n"
        "        handle.write(json.dumps(request, ensure_ascii=False) + '\\n')\n"
        "    if 'id' not in request:\n"
        "        continue\n"
        "    method = request.get('method')\n"
        "    if 'jsonrpc' in request:\n"
        "        print(json.dumps({'id':request.get('id'),'error':{'code':-32600,'message':'jsonrpc header forbidden'}}), flush=True)\n"
        "        continue\n"
        "    if method == 'initialize':\n"
        "        result = {'userAgent':'fake-app-server'}\n"
        "    elif method == 'model/list':\n"
        "        result = {'data':[{'id':'gpt-5.6-sol','supportedReasoningEfforts':[{'reasoningEffort':'low'},{'reasoningEffort':'medium'}]}]}\n"
        "    elif method == 'thread/start':\n"
        "        if request['params'].get('approvalPolicy') != 'never' or request['params'].get('sandbox') != 'readOnly':\n"
        "            print(json.dumps({'id':request['id'],'error':{'code':-32602,'message':'bad enums'}}), flush=True)\n"
        "            continue\n"
        "        result = {'thread':{'id':'01a-client-handoff-test'},'model':'gpt-test','modelProvider':'openai','cwd':request['params']['cwd'],'approvalPolicy':'onRequest','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}\n"
        "    elif method == 'mcpServerStatus/list':\n"
        "        names = ['get_knowledge_handoff','list_source_files','search_source','read_source','submit_knowledge_candidate','get_case_generation_handoff','submit_case_generation_drafts']\n"
        "        result = {'data':[{'name':'opentest_knowledge','authStatus':'unsupported','resources':[],'resourceTemplates':[],'tools':{name:{'name':name,'inputSchema':{}} for name in names}}],'nextCursor':None}\n"
        "    else:\n"
        "        result = {}\n"
        "    response = json.dumps({'id':request['id'],'result':result})\n"
        "    if method == 'thread/start':\n"
        "        notification = json.dumps({'method':'thread/started','params':{'thread':result['thread']}})\n"
        "        sys.stdout.write(notification + '\\n' + response + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    else:\n"
        "        print(response, flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    thread = CodexAppServerClient(
        CodexAppServerConfig(
            executable=str(executable),
            thread_start_wire=CodexThreadStartWire(approval_policy="never", sandbox="readOnly"),
        )
    ).create_thread(
        "请分析当前OpenTest知识目标。",
        "OpenTest · QueryFacade#queryList",
        workspace,
        "只能通过OpenTest插件回写候选。",
        "gpt-5.6-sol",
        "medium",
    )
    requests = [
        json.loads(line)
        for line in request_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert thread.thread_id == "01a-client-handoff-test"
    assert thread.deep_link == "codex://threads/01a-client-handoff-test"
    assert [request.get("method") for request in requests if "method" in request] == [
        "initialize",
        "initialized",
        "model/list",
        "thread/start",
        "mcpServerStatus/list",
        "thread/name/set",
        "thread/inject_items",
    ]
    assert all("jsonrpc" not in request for request in requests)
    assert all(request.get("method") != "turn/start" for request in requests)
    initialized = next(request for request in requests if request.get("method") == "initialized")
    assert initialized == {"method": "initialized", "params": {}}
    started = next(request for request in requests if request.get("method") == "thread/start")
    assert set(started) == {"id", "method", "params"}
    assert started["params"] == {
        "cwd": str(workspace.resolve()),
        "developerInstructions": "只能通过OpenTest插件回写候选。",
        "model": "gpt-5.6-sol",
        "config": {"model_reasoning_effort": "medium"},
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "sandbox": "readOnly",
        "ephemeral": False,
    }
    status = next(request for request in requests if request.get("method") == "mcpServerStatus/list")
    assert status["params"] == {
        "threadId": "01a-client-handoff-test",
        "detail": "toolsAndAuthOnly",
        "limit": 100,
    }
    injected = next(request for request in requests if request.get("method") == "thread/inject_items")
    assert injected["params"]["items"][0]["role"] == "user"
    assert "OpenTest知识目标" in injected["params"]["items"][0]["content"][0]["text"]


def test_codex_app_server_case_thread_has_machine_enforced_case_only_tools(
    tmp_path: Path,
) -> None:
    """Case线程必须关闭已安装插件并只注入两个Case MCP工具。

    Args:
        tmp_path: pytest隔离的假App Server、协议日志和工作目录。

    Returns:
        None；启动配置只含Case桥接且额外knowledge/QA工具会被线程门禁拒绝时通过。

    Side Effects:
        只创建假本地线程协议记录，不调用真实Codex、HTTP、QA或模型。
    """

    executable = tmp_path / "codex"
    request_log = tmp_path / "case-app-server-requests.jsonl"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log_path = {str(request_log)!r}\n"
        "for raw in sys.stdin:\n"
        "    request = json.loads(raw)\n"
        "    with open(log_path, 'a', encoding='utf-8') as handle:\n"
        "        handle.write(json.dumps(request, ensure_ascii=False) + '\\n')\n"
        "    if 'id' not in request:\n"
        "        continue\n"
        "    method = request.get('method')\n"
        "    if method == 'initialize':\n"
        "        result = {'userAgent':'fake-case-app-server'}\n"
        "    elif method == 'model/list':\n"
        "        result = {'data':[{'id':'gpt-5.6-luna','supportedReasoningEfforts':['low','medium']}]}\n"
        "    elif method == 'thread/start':\n"
        "        result = {'thread':{'id':'01a-case-only-thread'}}\n"
        "    elif method == 'mcpServerStatus/list':\n"
        "        names = ['get_case_generation_handoff','submit_case_generation_drafts']\n"
        "        result = {'data':[{'name':'opentest_case','tools':{name:{'name':name} for name in names}}]}\n"
        "    else:\n"
        "        result = {}\n"
        "    print(json.dumps({'id':request['id'],'result':result}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = CodexAppServerClient(
        CodexAppServerConfig(
            executable=str(executable),
            thread_start_wire=CodexThreadStartWire(
                approval_policy="never",
                sandbox="readOnly",
            ),
        )
    )

    thread = client.create_scoped_thread(
        CodexThreadCreationRequest(
            prompt="处理Case handoff。",
            title="OpenTest Case · cancel",
            cwd=workspace,
            developer_instructions="只允许Case typed工具。",
            model="gpt-5.6-luna",
            reasoning_effort="low",
            tool_scope="case_only",
        )
    )

    assert thread.thread_id == "01a-case-only-thread"
    requests = [
        json.loads(line)
        for line in request_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = next(request for request in requests if request.get("method") == "thread/start")
    config = started["params"]["config"]
    assert config["features"]["plugins"] is False
    assert config["features"]["shell_tool"] is False
    assert set(config["mcp_servers"]) == {"node_repl", "opentest_case"}
    assert config["mcp_servers"]["node_repl"]["enabled"] is False
    assert config["mcp_servers"]["opentest_case"]["args"][-1] == "--case-only"
    with pytest.raises(ExecutionFailure, match="MCP tools are unavailable"):
        client._require_handoff_tools(
            {
                "data": [
                    {
                        "name": "opentest_case",
                        "tools": {
                            "get_case_generation_handoff": {},
                            "submit_case_generation_drafts": {},
                            "execute_case": {},
                        },
                    }
                ]
            },
            "case_only",
        )


def test_codex_app_server_case_turn_ignores_user_tools_and_reuses_thread(
    tmp_path: Path,
) -> None:
    """Case模型turn必须复用线程、移除用户工具面并保留延迟退出事实。

    Args:
        tmp_path: pytest隔离的假Codex CLI、参数记录和工作目录。

    Returns:
        None；命令复用原线程、只注入Case MCP且延迟失败可被轮询识别时通过。

    Side Effects:
        启动一个短暂假CLI子进程并等待回收，不调用真实Codex、HTTP、QA或模型。
    """

    executable = tmp_path / "codex"
    argument_log = tmp_path / "case-turn-arguments.json"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        f"open({str(argument_log)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
        "time.sleep(0.8)\n"
        "sys.exit(17)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    client = CodexAppServerClient(CodexAppServerConfig(executable=str(executable)))

    process_id = client.start_case_turn(
        "01a-case-only-existing-thread",
        "继续Case typed handoff。",
        workspace,
        "gpt-5.6-luna",
        "low",
    )
    # 启动窗口之后的失败必须由后台watcher收割并保留，不能成为页面永久运行的假回执。
    deadline = time.monotonic() + 5
    process = client.inspect_case_turn_process(process_id)
    while process.state == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.05)
        process = client.inspect_case_turn_process(process_id)
    arguments = json.loads(argument_log.read_text(encoding="utf-8"))

    assert arguments[-3:] == [
        "--json",
        "01a-case-only-existing-thread",
        "继续Case typed handoff。",
    ]
    assert "--ignore-user-config" in arguments
    assert "--case-only" in " ".join(arguments)
    assert 'mcp_servers.opentest_case.env_vars=["OPENTEST_LOCAL_API"]' in arguments
    assert arguments.count("--disable") == 10
    assert "plugins" in arguments
    assert "shell_tool" in arguments
    assert "unified_exec" in arguments
    assert process.state == "EXITED"
    assert process.return_code == 17


def test_codex_app_server_inspects_persisted_turn_without_resuming_thread(tmp_path: Path) -> None:
    """协调器应只读检查已有turn并立即回收短生命周期App Server。

    Args:
        tmp_path: pytest隔离的假App Server、协议日志和进程关闭标记。

    Returns:
        None；只调用thread/read并返回最新turn身份和状态时通过。
    """

    executable = tmp_path / "codex"
    request_log = tmp_path / "thread-inspect-requests.jsonl"
    process_closed = tmp_path / "thread-inspect-process-closed.txt"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"request_log = pathlib.Path({str(request_log)!r})\n"
        f"process_closed = pathlib.Path({str(process_closed)!r})\n"
        "for raw in sys.stdin:\n"
        "    request = json.loads(raw)\n"
        "    request_log.open('a', encoding='utf-8').write(json.dumps(request) + '\\n')\n"
        "    if 'id' not in request:\n"
        "        continue\n"
        "    method = request.get('method')\n"
        "    if method == 'thread/read':\n"
        "        turns = [{'id':'turn-finished','status':'completed'}, {'id':'turn-active','status':'inProgress'}]\n"
        "        result = {'thread':{'id':request['params']['threadId'],'turns':turns}}\n"
        "    else:\n"
        "        result = {}\n"
        "    print(json.dumps({'id':request['id'],'result':result}), flush=True)\n"
        "process_closed.write_text('closed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    client = CodexAppServerClient(CodexAppServerConfig(executable=str(executable)))

    snapshot = client.inspect_thread("01a-client-handoff-test")
    requests = [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]
    methods = [request.get("method") for request in requests]

    assert snapshot.turn_count == 2
    assert snapshot.latest_turn_id == "turn-active"
    assert snapshot.latest_turn_status == "inProgress"
    assert process_closed.read_text(encoding="utf-8") == "closed"
    assert methods == ["initialize", "initialized", "thread/read"]
    read_request = next(request for request in requests if request.get("method") == "thread/read")
    assert read_request["params"] == {
        "threadId": "01a-client-handoff-test",
        "includeTurns": True,
    }


def test_codex_app_server_inspects_empty_thread_without_starting_turn(tmp_path: Path) -> None:
    """尚无turn的持久线程只返回空快照，不得恢复线程或取得writer。

    Args:
        tmp_path: pytest隔离的假App Server与协议日志。

    Returns:
        None；快照数量为零且协议只有thread/read时通过。
    """

    executable = tmp_path / "codex"
    request_log = tmp_path / "existing-turn-requests.jsonl"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"request_log = pathlib.Path({str(request_log)!r})\n"
        "for raw in sys.stdin:\n"
        "    request = json.loads(raw)\n"
        "    request_log.open('a', encoding='utf-8').write(json.dumps(request) + '\\n')\n"
        "    if 'id' not in request:\n"
        "        continue\n"
        "    if request.get('method') == 'thread/read':\n"
        "        result = {'thread':{'id':request['params']['threadId'],'turns':[]}}\n"
        "    else:\n"
        "        result = {}\n"
        "    print(json.dumps({'id':request['id'],'result':result}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    snapshot = CodexAppServerClient(CodexAppServerConfig(executable=str(executable))).inspect_thread(
        "01a-client-handoff-test"
    )
    methods = [
        json.loads(line).get("method")
        for line in request_log.read_text(encoding="utf-8").splitlines()
    ]

    assert snapshot.turn_count == 0
    assert snapshot.latest_turn_id == ""
    assert snapshot.latest_turn_status == ""
    assert methods == ["initialize", "initialized", "thread/read"]


def test_codex_app_server_rejects_thread_without_ready_opentest_mcp_tools(tmp_path: Path) -> None:
    """客户端线程未装载全部OpenTest工具时必须在任何turn之前失败关闭。

    Args:
        tmp_path: pytest隔离的假App Server和工作目录。

    Returns:
        None；缺少确认工具时抛出精确失败且协议中没有注入或turn/start时通过。
    """

    executable = tmp_path / "codex"
    request_log = tmp_path / "missing-mcp-requests.jsonl"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log_path = {str(request_log)!r}\n"
        "for raw in sys.stdin:\n"
        "    request = json.loads(raw)\n"
        "    with open(log_path, 'a', encoding='utf-8') as handle:\n"
        "        handle.write(json.dumps(request) + '\\n')\n"
        "    if 'id' not in request:\n"
        "        continue\n"
        "    if request['method'] == 'model/list':\n"
        "        result = {'data':[{'id':'gpt-5.6-sol','supportedReasoningEfforts':['low','medium']}]}\n"
        "    elif request['method'] == 'thread/start':\n"
        "        result = {'thread':{'id':'01a-missing-mcp'}}\n"
        "    elif request['method'] == 'mcpServerStatus/list':\n"
        "        result = {'data':[{'name':'opentest_knowledge','tools':{'read_source':{'name':'read_source'}}}]}\n"
        "    else:\n"
        "        result = {}\n"
        "    print(json.dumps({'id':request['id'],'result':result}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ExecutionFailure, match="MCP tools are unavailable"):
        CodexAppServerClient(
            CodexAppServerConfig(
                executable=str(executable),
                thread_start_wire=CodexThreadStartWire(approval_policy="never", sandbox="readOnly"),
            )
        ).create_thread(
            "请分析当前OpenTest知识目标。",
            "OpenTest · QueryFacade#queryList",
            workspace,
            "只能通过OpenTest插件回写候选。",
            "gpt-5.6-sol",
            "low",
        )

    methods = [
        json.loads(line).get("method")
        for line in request_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "thread/inject_items" not in methods
    assert "turn/start" not in methods


def test_codex_app_server_uses_local_schema_wire_before_side_effectful_thread_start(tmp_path: Path) -> None:
    """真实Codex旧枚举必须在创建线程前由本机Schema确定且不得失败后重试。

    Args:
        tmp_path: Pytest隔离的假Codex、Schema输出、请求日志和工作目录。

    Returns:
        None；只生成一次Schema并以旧枚举创建唯一线程且不启动turn时通过。
    """

    executable = tmp_path / "codex"
    request_log = tmp_path / "schema-wire-requests.jsonl"
    schema_log = tmp_path / "schema-wire-count.txt"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"request_log = pathlib.Path({str(request_log)!r})\n"
        f"schema_log = pathlib.Path({str(schema_log)!r})\n"
        "if 'generate-json-schema' in sys.argv:\n"
        "    out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1]) / 'v2'\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        "    schema_log.write_text('generated', encoding='utf-8')\n"
        "    schema = {'definitions': {'AskForApproval': {'type':'string','enum':['never']}, 'SandboxMode': {'type':'string','enum':['readOnly']}}}\n"
        "    (out / 'ThreadStartParams.json').write_text(json.dumps(schema), encoding='utf-8')\n"
        "    raise SystemExit(0)\n"
        "for raw in sys.stdin:\n"
        "    request = json.loads(raw)\n"
        "    request_log.open('a', encoding='utf-8').write(json.dumps(request) + '\\n')\n"
        "    if 'id' not in request:\n"
        "        continue\n"
        "    method = request.get('method')\n"
        "    if method == 'model/list':\n"
        "        result = {'data':[{'id':'gpt-5.6-sol','supportedReasoningEfforts':['low','medium']}]}\n"
        "    elif method == 'thread/start':\n"
        "        params = request['params']\n"
        "        if params.get('approvalPolicy') != 'never' or params.get('sandbox') != 'readOnly':\n"
        "            print(json.dumps({'id':request['id'],'error':{'code':-32602,'message':'bad local enums'}}), flush=True)\n"
        "            continue\n"
        "        result = {'thread':{'id':'01a-schema-wire-thread'}}\n"
        "    elif method == 'mcpServerStatus/list':\n"
        "        names = ['get_knowledge_handoff','list_source_files','search_source','read_source','submit_knowledge_candidate','get_case_generation_handoff','submit_case_generation_drafts']\n"
        "        result = {'data':[{'name':'opentest_knowledge','tools':{name:{'name':name} for name in names}}]}\n"
        "    else:\n"
        "        result = {}\n"
        "    print(json.dumps({'id':request['id'],'result':result}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    thread = CodexAppServerClient(CodexAppServerConfig(executable=str(executable))).create_thread(
        "请分析当前OpenTest知识目标。",
        "OpenTest · QueryFacade#queryList",
        workspace,
        "只能通过OpenTest插件回写候选。",
        "gpt-5.6-sol",
        "medium",
    )
    requests = [json.loads(line) for line in request_log.read_text(encoding="utf-8").splitlines()]
    starts = [request for request in requests if request.get("method") == "thread/start"]

    assert schema_log.read_text(encoding="utf-8") == "generated"
    assert len(starts) == 1
    assert starts[0]["params"]["approvalPolicy"] == "never"
    assert starts[0]["params"]["sandbox"] == "readOnly"
    assert thread.thread_id == "01a-schema-wire-thread"
    assert all(request.get("method") != "turn/start" for request in requests)


def test_codex_app_server_requires_installed_opentest_plugin_before_thread_creation(tmp_path: Path) -> None:
    """客户端接管必须确认插件已安装启用，仓库源码存在不能替代Codex安装状态。

    Args:
        tmp_path: pytest隔离的假Codex插件清单命令。

    Returns:
        None；正确插件通过、空安装清单被阻止且没有创建线程时通过。
    """

    executable = tmp_path / "codex-plugin-list"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'installed':[{'pluginId':'open-test-knowledge@opentest-local','installed':True,'enabled':True}]}))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    client = CodexAppServerClient(CodexAppServerConfig(executable=str(executable)))

    client.require_knowledge_plugin()

    executable.write_text(
        "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'installed':[]}))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    with pytest.raises(KnowledgeValidationError, match="安装并启用OpenTest Codex插件"):
        client.require_knowledge_plugin()


def test_agent_knowledge_envelope_schema_is_fully_codex_strict() -> None:
    """Agent信封、问题、摘要和源码引用的所有对象都必须满足Codex严格契约。

    Returns:
        None；不存在动态摘要Map，且所有对象闭合并全字段必填时通过。
    """

    schema = AgentKnowledgeEnvelope.model_json_schema()

    assert schema["type"] == "object"
    assert "summaries" in schema["properties"]
    assert "summaries_by_node" not in schema["properties"]
    _assert_codex_strict_schema(schema)


def test_client_candidate_keeps_inherited_field_as_evidence_not_trace_step(tmp_path: Path) -> None:
    """客户端候选应自动把继承注入字段从执行trace降为连接证据。

    Args:
        tmp_path: Pytest提供的隔离源码与知识服务目录。

    Returns:
        None；字段仍保留在source_refs、trace只剩真实方法且直接调用链通过时成功。
    """

    service, _store, _index = _knowledge_service(tmp_path / "knowledge")
    source_root = tmp_path / "source"
    implementation_path = "demo/biz/impl/OrderServiceImpl.java"
    parent_path = "demo/biz/service/AbstractOrderService.java"
    dao_path = "demo/dal/SaasRefundOrderDAOProxy.java"
    source_files = {
        implementation_path: [
            "package demo.biz.impl;",
            "import demo.biz.service.AbstractOrderService;",
            "class OrderServiceImpl extends AbstractOrderService {",
            "  Object query(String serialNo) { return orderDAO.query(serialNo); }",
            "}",
        ],
        parent_path: [
            "package demo.biz.service;",
            "import demo.dal.*;",
            "abstract class AbstractOrderService {",
            "  protected SaasRefundOrderDAOProxy orderDAO;",
            "}",
        ],
        dao_path: [
            "package demo.dal;",
            "class SaasRefundOrderDAOProxy {",
            "  Object query(String serialNo) { return serialNo; }",
            "}",
        ],
    }
    for relative_path, source_lines in source_files.items():
        # 用三个真实Java文件复现子类方法经父类字段调用DAO的生产结构。
        source_file = source_root / relative_path
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("\n".join(source_lines), encoding="utf-8")
    implementation_reference = {
        "path": implementation_path,
        "symbol": "OrderServiceImpl#query",
        "line": 4,
    }
    field_reference = {
        "path": parent_path,
        "symbol": "AbstractOrderService#orderDAO",
        "line": 4,
    }
    dao_reference = {
        "path": dao_path,
        "symbol": "SaasRefundOrderDAOProxy#query",
        "line": 3,
    }
    candidate = KnowledgeClientCandidateEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": ["facade:demo.RefundFacade#cancel"],
            "summaries": [],
            "questions": [],
            "source_refs": [implementation_reference, field_reference, dao_reference],
            "trace_steps": [
                {
                    "sequence": 1,
                    "role": "service",
                    "source_ref": implementation_reference,
                    "summary": "订单服务查询。",
                },
                {
                    "sequence": 2,
                    "role": "service",
                    "source_ref": field_reference,
                    "summary": "父类注入DAO字段。",
                },
                {
                    "sequence": 3,
                    "role": "data_access",
                    "source_ref": dao_reference,
                    "summary": "DAO执行查询。",
                },
            ],
        }
    )
    accessed_ranges = {
        path: [(1, len(source_lines))]
        for path, source_lines in source_files.items()
    }

    normalized = service._normalize_client_candidate_references(
        candidate,
        source_root,
        accessed_ranges,
    )

    assert [step.source_ref.symbol for step in normalized.trace_steps] == [
        "OrderServiceImpl#query",
        "SaasRefundOrderDAOProxy#query",
    ]
    assert [step.sequence for step in normalized.trace_steps] == [1, 2]
    assert any(reference.symbol == "AbstractOrderService#orderDAO" for reference in normalized.source_refs)
    service._validate_agent_trace_links(normalized, source_files)


def test_facade_client_candidate_requires_complete_sections_and_immutable_contract(tmp_path: Path) -> None:
    """Facade候选缺少业务章节时不得发布，且模型不能改写确定性调用身份。

    Args:
        tmp_path: Pytest提供的隔离知识服务目录。

    Returns:
        None；缺口逐项返回、完整候选无缺口且契约改写被安全拒绝时通过。
    """

    service, _store, _index = _knowledge_service(tmp_path)
    entry = EntryPoint(
        entry_id="facade:demo.RefundFacade#queryList",
        system_id="demo-system",
        kind=KnowledgeNodeKind.FACADE,
        display_name="查询退票单",
        source_id="demo.RefundFacade#queryList",
        source_path="RefundFacade.java",
        request_type="RefundQueryRequest",
        response_type="RefundPage",
        tool_id="refund-query-list",
    )
    contract = service._deterministic_invocation_contract(entry).model_copy(
        update={
            "field_meanings": {"refundType": "退票类型筛选条件"},
            "date_dimensions": {"applyTime": "退票申请时间"},
            "pagination_semantics": "pageNo从1开始，pageSize限制单页条数。",
            "error_semantics": ["参数错误返回业务异常，不产生写入。"],
            "usage_examples": ["查询七月申请的自愿退退票单列表。"],
        }
    )
    reference = {"path": "RefundFacade.java", "symbol": "RefundFacade#queryList", "line": 1}
    shallow = KnowledgeClientCandidateEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": "demo-system",
            "target_ids": [entry.entry_id],
            "summaries": [],
            "questions": [],
            "source_refs": [reference],
            "trace_steps": [{"sequence": 1, "role": "entry", "source_ref": reference, "summary": "入口"}],
            "completeness": AgentKnowledgeCompleteness().model_dump(),
            "invocation_contract": contract.model_dump(),
        }
    )

    gaps = service._client_completion_gaps(entry, shallow)

    assert "missing_or_shallow:input_semantics" in gaps
    assert "missing:service_trace" in gaps
    assert "missing:data_or_remote_boundary" in gaps
    complete_text = "已结合真实源码读取完整解释该章节的业务语义和可验证结果。"
    complete = shallow.model_copy(
        update={
            "completeness": AgentKnowledgeCompleteness(
                business_purpose="用于按运营筛选条件查询退票单分页列表，不创建或修改任何退票业务状态。",
                applicable_scenarios="适用于运营后台按退票类型和时间范围检索订单，并核对列表与总数。",
                input_semantics="请求包含退票类型、时间范围和分页参数；空筛选按源码默认规则处理。",
                output_semantics="返回分页退票单及总数；没有匹配记录时返回空集合而不是伪造错误。",
                business_flow="入口转换请求后调用列表业务服务，再分别读取明细集合和符合条件的总数。",
                important_branches="自愿退等类型条件会改变查询过滤；分页边界和空条件分支影响最终数据库条件。",
                failure_handling="非法筛选参数产生业务参数异常，数据访问失败按现有异常边界向上返回。",
                test_oracles="验证列表元素满足全部过滤条件、总数一致、分页稳定，并覆盖空结果与非法参数。",
            ),
            "trace_steps": [
                shallow.trace_steps[0],
                shallow.trace_steps[0].model_copy(update={"sequence": 2, "role": "service"}),
                shallow.trace_steps[0].model_copy(update={"sequence": 3, "role": "data_access"}),
            ],
        }
    )

    assert service._client_completion_gaps(entry, complete) == []
    concise = complete.model_copy(
        update={
            "completeness": AgentKnowledgeCompleteness(
                business_purpose="查询退票单",
                applicable_scenarios="运营后台查询",
                input_semantics="类型、日期和分页",
                output_semantics="返回列表与总数",
                business_flow="入口调用服务后查询DAO",
                important_branches="按退票类型过滤",
                failure_handling="无重试，异常直接上抛",
                test_oracles="列表符合条件且总数一致",
            )
        }
    )
    concise_gaps = service._client_completion_gaps(entry, concise)
    assert not any(gap.startswith("missing_or_shallow:") for gap in concise_gaps)
    for placeholder_text in ("待补充", "待确认", "待分析", "待完善"):
        placeholder = concise.model_copy(
            update={
                "completeness": concise.completeness.model_copy(
                    update={"failure_handling": placeholder_text}
                )
            }
        )
        assert "missing_or_shallow:failure_handling" in service._client_completion_gaps(entry, placeholder)
    repeated = complete.model_copy(
        update={
            "completeness": AgentKnowledgeCompleteness(
                **{
                    name: f"{name}：{complete_text}"
                    for name in AgentKnowledgeCompleteness.model_fields
                }
            )
        }
    )
    assert any(
        gap.startswith("duplicate_or_overlapping_content:")
        for gap in service._client_completion_gaps(entry, repeated)
    )
    empty_contract_candidate = complete.model_copy(
        update={
            "invocation_contract": contract.model_copy(
                update={
                    "field_meanings": {"refundType": ""},
                    "pagination_semantics": "",
                    "error_semantics": [""],
                    "usage_examples": [""],
                }
            )
        }
    )
    empty_contract_gaps = service._client_completion_gaps(entry, empty_contract_candidate)
    assert "missing:invocation_field_meanings" in empty_contract_gaps
    assert "missing:invocation_usage_examples" in empty_contract_gaps
    assert "missing:pagination_semantics" in empty_contract_gaps
    assert "missing:invocation_error_semantics" in empty_contract_gaps
    with pytest.raises(KnowledgeValidationError, match="changed deterministic"):
        service._validate_deterministic_invocation_contract(
            entry,
            contract.model_copy(update={"tool_id": "forged-write-tool"}),
        )
    write_entry = entry.model_copy(
        update={
            "entry_id": "facade:demo.RefundFacade#createOrder",
            "source_id": "demo.RefundFacade#createOrder",
            "tool_id": "refund-create-order",
        }
    )

    # 明确写接口只生成业务知识，不能被Agent包装为可调用的只读能力。
    assert service._deterministic_invocation_contract(write_entry) is None
    with pytest.raises(KnowledgeValidationError, match="write or unknown Facade"):
        service._validate_deterministic_invocation_contract(write_entry, contract)


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_agent_runner_rejects_invalid_schema_before_starting_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent: str,
) -> None:
    """Codex与Claude必须共用本地Schema预检，失败时不得启动供应商或创建运行证据。

    Args:
        tmp_path: pytest隔离的假供应商、源码和未创建证据目录。
        monkeypatch: 把假供应商命令放到本测试PATH首位。
        agent: 当前验证的明确供应商名称。

    Returns:
        None；无进程执行哨兵且无运行目录时通过。
    """

    sentinel = tmp_path / "provider-started"
    executable = tmp_path / agent
    executable.write_text(f"#!/bin/sh\ntouch '{sentinel}'\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"
    config = (
        AgentRunnerConfig(codex_executable="codex")
        if agent == "codex"
        else AgentRunnerConfig(claude_executable="claude")
    )
    invalid_schema = {
        "type": "object",
        "properties": {
            "summaries": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": [],
        "additionalProperties": False,
    }

    # 预检位于证据目录和供应商工作进程创建之前，避免无效请求产生任何API费用。
    with pytest.raises(KnowledgeValidationError, match="require every property"):
        AgentRunner(config).run(
            AgentRunRequest(
                system_id="train-booking-core",
                agent=agent,
                prompt="只读分析",
                output_schema=invalid_schema,
            ),
            source,
            evidence_root,
        )

    assert not sentinel.exists()
    assert not evidence_root.exists()


def test_agent_runner_only_stops_a_slow_run_after_explicit_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """静默慢Agent应保持运行，直到用户对当前运行发送取消标记。

    Args:
        tmp_path: pytest隔离的慢速假Codex、源码和私有状态目录。
        monkeypatch: 把假Codex放到本测试PATH首位。

    Returns:
        None；运行先保持存活、显式取消后形成取消事件和对应异常时通过。
    """

    executable = tmp_path / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        "print(json.dumps({'type':'thread.started','thread_id':'thread-cancel-test'}), flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"
    run_id = "agent-aaaaaaaaaaaaaaaa"
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))
    failures: list[BaseException] = []

    def run_slow_agent() -> None:
        """在线程中运行慢速替身并收集预期的取消异常。

        Side Effects:
            启动一个仅测试使用的独立工作进程；异常保存在外层列表供主线程断言。
        """

        try:
            runner.run(
                AgentRunRequest(
                    system_id="train-booking-core",
                    agent="codex",
                    prompt="持续只读分析",
                    run_id=run_id,
                ),
                source,
                evidence_root,
            )
        except BaseException as exc:  # noqa: BLE001 - 测试线程需把预期取消异常交回主线程核对
            failures.append(exc)

    thread = threading.Thread(target=run_slow_agent, daemon=True)
    thread.start()
    state: dict[str, object] = {}
    for _ in range(100):
        if (evidence_root / run_id / "state.json").is_file():
            state = runner.read_state(run_id, evidence_root)
            if state.get("status") == "running" and state.get("session_id") == "thread-cancel-test":
                break
        time.sleep(0.01)

    # 会话事件必须立即形成恢复锚点；后续静默且没有截止时间时只能由显式取消终止。
    assert state.get("status") == "running"
    assert state.get("session_id") == "thread-cancel-test"
    assert thread.is_alive()
    runner.cancel(run_id, evidence_root)
    thread.join(timeout=8)

    assert not thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], TaskCancelledError)
    assert any(event.event_type == "cancelled" for event in runner.list_events(run_id, evidence_root))


def test_agent_runner_streams_claude_public_text_without_thinking_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude stream-json只展示公开text增量，不展示thinking块。

    Args:
        tmp_path: pytest隔离的假Claude、源码和证据目录。
        monkeypatch: 把假Claude放到PATH首位。

    Returns:
        None；公开增量和会话ID存在且隐藏推理未进入事件日志时通过。
    """

    executable = tmp_path / "claude"
    executable.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in *\" --output-format stream-json --include-partial-messages --verbose \"*) ;; *) exit 92 ;; esac\n"
        "printf '%s\\n' "
        "'{\"type\":\"system\",\"session_id\":\"claude-stream-test\"}' "
        "'{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"thinking\",\"thinking\":\"hidden raw thought\"}]}}' "
        "'{\"type\":\"stream_event\",\"event\":{\"delta\":{\"type\":\"text_delta\",\"text\":\"{\\\"status\\\":\"}}}' "
        "'{\"type\":\"stream_event\",\"event\":{\"delta\":{\"type\":\"text_delta\",\"text\":\"\\\"completed\\\"}\"}}}' "
        "'{\"type\":\"result\",\"session_id\":\"claude-stream-test\",\"result\":\"{\\\"status\\\":\\\"completed\\\"}\",\"usage\":{\"input_tokens\":8}}'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"
    runner = AgentRunner(AgentRunnerConfig(claude_executable="claude"))

    evidence = runner.run(
        AgentRunRequest(system_id="train-booking-core", agent="claude", prompt="只读分析"),
        source,
        evidence_root,
    )
    events = runner.list_events(evidence.run_id, evidence_root)
    public_text = " ".join(event.text for event in events)

    assert evidence.session_id == "claude-stream-test"
    assert "hidden raw thought" not in public_text
    assert any(event.event_type == "agent_message" for event in events)
    assert any(event.event_type == "usage" for event in events)


def test_agent_runner_preserves_large_claude_final_result_outside_public_event_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude最终结构化结果不得被页面单事件5KB上限截断。

    Args:
        tmp_path: pytest隔离的假Claude、源码和私有输出目录。
        monkeypatch: 把假Claude放到当前测试PATH首位。

    Returns:
        None；完整私有结果超过5KB且所有公开事件仍满足长度契约时通过。
    """

    executable = tmp_path / "claude"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "summary = '业务分支' * 1600\n"
        "result = json.dumps({'status':'completed','summary':summary}, ensure_ascii=False)\n"
        "print(json.dumps({'type':'system','session_id':'claude-large-result'}), flush=True)\n"
        "print(json.dumps({'type':'result','session_id':'claude-large-result','result':result}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"
    runner = AgentRunner(AgentRunnerConfig(claude_executable="claude"))

    evidence = runner.run(
        AgentRunRequest(system_id="train-booking-core", agent="claude", prompt="只读分析"),
        source,
        evidence_root,
    )
    private_result = json.loads(Path(evidence.output_path).read_text(encoding="utf-8"))
    events = runner.list_events(evidence.run_id, evidence_root)

    assert len(private_result["summary"]) > 5_000
    assert private_result["summary"].endswith("业务分支")
    assert all(len(event.text) <= 5_000 for event in events)


def test_agent_worker_start_failure_writes_stable_failed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """供应商进程启动失败时应形成稳定失败证据而非永久RUNNING。

    Args:
        tmp_path: pytest隔离的假命令、源码和运行证据目录。
        monkeypatch: 把父Runner解析出的命令替换为工作进程内不存在的路径。

    Returns:
        None；Runner收到明确失败且状态、证据、事件均可恢复读取时通过。
    """

    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"
    run_id = "agent-bbbbbbbbbbbbbbbb"
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))

    def missing_command(*_: object) -> list[str]:
        """返回工作进程内必然不存在的供应商可执行文件路径。"""

        return [str(tmp_path / "missing-codex")]

    monkeypatch.setattr(runner, "_build_command", missing_command)
    with pytest.raises(ExecutionFailure):
        runner.run(
            AgentRunRequest(
                system_id="train-booking-core",
                agent="codex",
                prompt="只读分析",
                run_id=run_id,
            ),
            source,
            evidence_root,
        )

    state = runner.read_state(run_id, evidence_root)
    events = runner.list_events(run_id, evidence_root)
    evidence_payload = json.loads((evidence_root / run_id / "evidence.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert evidence_payload["status"] == "failed"
    assert any(event.event_type == "failed" for event in events)


def test_task_manager_close_detaches_observer_and_allows_free_restart_takeover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务关闭应快速放弃观察权，并让新实例接管同一付费Agent运行。

    Args:
        tmp_path: pytest隔离的慢速Agent、任务心跳和运行证据目录。
        monkeypatch: 把慢速假Codex放到当前测试PATH首位。

    Returns:
        None；旧线程池快速关闭、任务保持RUNNING且新Runner读取原证据时通过。

    Side Effects:
        仅启动无网络的临时假Agent进程，不访问真实认证、源码或外部服务。
    """

    executable = tmp_path / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        "print(json.dumps({'type':'thread.started','thread_id':'thread-restart-test'}), flush=True)\n"
        "time.sleep(1.0)\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{\\\"status\\\":\\\"completed\\\"}'}}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    local_root = tmp_path / "knowledge" / ".opentest"
    evidence_root = local_root / "agent-runs"
    task_root = local_root / "tasks"
    run_id = "agent-cccccccccccccccc"
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))
    manager = LocalTaskManager(task_root)

    def observe_agent() -> dict[str, object]:
        """把慢速Agent绑定到可恢复任务进度并等待原运行证据。"""

        report_task_progress(
            TaskProgressUpdate(
                stage_code="agent_analysis",
                stage_name="AI分析",
                stage_index=2,
                stage_total=3,
                completed_units=0,
                total_units=1,
                agent="codex",
                agent_run_id=run_id,
                knowledge_batch_id="knowledge-workflow-restarttest",
            )
        )
        evidence = runner.run(
            AgentRunRequest(
                system_id="train-booking-core",
                agent="codex",
                prompt="慢速只读分析",
                run_id=run_id,
            ),
            source,
            evidence_root,
        )
        return {"run_id": evidence.run_id}

    task = manager.submit("knowledge-target-generation", "train-booking-core", observe_agent, exclusive=True)
    for _ in range(300):
        if (evidence_root / run_id / "state.json").is_file():
            break
        time.sleep(0.01)
    assert runner.read_state(run_id, evidence_root).get("status") == "running"

    started = time.monotonic()
    runner.detach_observers()
    manager.close()
    elapsed = time.monotonic() - started
    preserved = manager.get(task.task_id)

    assert elapsed < 2
    assert preserved.status == TaskStatus.RUNNING
    takeover_runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))
    restarted_manager = LocalTaskManager(task_root)
    recoverable = restarted_manager.recoverable_agent_tasks({"knowledge-target-generation"})
    evidence = takeover_runner.attach(run_id, evidence_root)
    restarted_manager.close()

    assert [record.task_id for record in recoverable] == [task.task_id]
    assert evidence.session_id == "thread-restart-test"


def test_application_close_waits_for_non_recoverable_conversation_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """共享Runner上的聊天Agent没有接管能力时，关闭应用不得把它分离。

    Args:
        tmp_path: pytest隔离的假Codex、应用任务和证据目录。
        monkeypatch: 把无网络假Codex放到当前测试PATH首位。

    Returns:
        None；聊天任务正常完成且Runner未进入分离状态时通过。

    Side Effects:
        启动一个短暂本地替身进程，不创建真实Agent调用或访问QA。
    """

    executable = tmp_path / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        "print(json.dumps({'type':'thread.started','thread_id':'thread-chat-close'}), flush=True)\n"
        "time.sleep(0.4)\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{}'}}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))
    application.agent_runner = runner
    evidence_root = application.knowledge_root / ".opentest" / "agent-runs"
    run_id = "agent-eeeeeeeeeeeeeeee"

    def analyze_conversation() -> dict[str, object]:
        """执行没有服务重启接管实现的短暂聊天Agent任务。"""

        evidence = runner.run(
            AgentRunRequest(
                system_id="train-booking-core",
                agent="codex",
                prompt="聊天只读分析",
                run_id=run_id,
            ),
            source,
            evidence_root,
        )
        return {"run_id": evidence.run_id}

    task = application.tasks.submit(
        "knowledge-conversation-analysis",
        "train-booking-core",
        analyze_conversation,
        exclusive=True,
    )
    for _ in range(200):
        if (evidence_root / run_id / "state.json").is_file():
            break
        time.sleep(0.01)
    application.close()
    completed = application.tasks.get(task.task_id)

    assert completed.status == TaskStatus.COMPLETED
    assert runner._observer_detached.is_set() is False


def test_overlapping_service_startup_adopts_handoff_and_blocks_duplicate_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新服务先启动时也应在旧服务声明handoff后接管并阻止第二个付费任务。

    Args:
        tmp_path: pytest隔离的两个应用实例、慢Agent和共享任务目录。
        monkeypatch: 把无网络假Codex放到两个实例共享的测试PATH首位。

    Returns:
        None；孤儿门禁拒绝新任务且原任务所有权转移到新实例时通过。

    Side Effects:
        仅运行一个临时假Agent；恢复任务因刻意缺少测试批次而安全结束为失败。
    """

    executable = tmp_path / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        "print(json.dumps({'type':'thread.started','thread_id':'thread-overlap'}), flush=True)\n"
        "time.sleep(0.8)\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{}'}}), flush=True)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    knowledge_root = tmp_path / "knowledge"
    old_application = OpenTestApplication(knowledge_root)
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))
    old_application.agent_runner = runner
    evidence_root = knowledge_root / ".opentest" / "agent-runs"
    run_id = "agent-ffffffffffffffff"

    def observe_generation() -> dict[str, object]:
        """保存可恢复运行检查点并等待慢速独立Agent。"""

        report_task_progress(
            TaskProgressUpdate(
                stage_code="agent_analysis",
                stage_name="AI分析",
                stage_index=2,
                stage_total=3,
                completed_units=0,
                total_units=1,
                agent="codex",
                agent_run_id=run_id,
                knowledge_batch_id="knowledge-workflow-overlaptest",
            )
        )
        evidence = runner.run(
            AgentRunRequest(
                system_id="train-booking-core",
                agent="codex",
                prompt="重叠重启只读分析",
                run_id=run_id,
            ),
            tmp_path,
            evidence_root,
        )
        return {"run_id": evidence.run_id}

    task = old_application.tasks.submit(
        "knowledge-target-generation",
        "train-booking-core",
        observe_generation,
        exclusive=True,
    )
    for _ in range(200):
        if (evidence_root / run_id / "state.json").is_file():
            break
        time.sleep(0.01)
    # 新实例在旧所有权心跳仍存在时启动，首次扫描应安全跳过而不是抢占。
    new_application = OpenTestApplication(knowledge_root)
    assert new_application.tasks.get(task.task_id).owner_instance_id != new_application.tasks._owner_instance_id
    old_application.close()

    def duplicate_agent_job() -> dict[str, object]:
        """表示不应越过孤儿Agent门禁启动的第二个任务。"""

        return {}

    with pytest.raises(ScopeViolationError, match="takeover|active"):
        new_application.tasks.submit(
            "duplicate-agent",
            "train-booking-core",
            duplicate_agent_job,
            exclusive=True,
        )
    for _ in range(300):
        current = new_application.get_task(task.task_id)
        if current.owner_instance_id == new_application.tasks._owner_instance_id:
            break
        time.sleep(0.01)
    for _ in range(300):
        current = new_application.tasks.get(task.task_id)
        if current.status in {TaskStatus.FAILED, TaskStatus.INTERRUPTED, TaskStatus.COMPLETED}:
            break
        time.sleep(0.01)
    new_application.close()

    assert current.owner_instance_id == new_application.tasks._owner_instance_id
    assert current.status != TaskStatus.RUNNING
