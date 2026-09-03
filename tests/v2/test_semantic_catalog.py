"""验证语义公共逻辑目录、状态展示和三栏详情契约。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from opentest.adapters.knowledge_interview import KnowledgeInterviewStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.knowledge_tracing import JavaKnowledgeTracer
from opentest.application.catalogs import ScanCatalogService
from opentest.application.knowledge_discovery import KnowledgeDiscoveryService
from opentest.domain.errors import KnowledgeNotFoundError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeContextCandidateCreate,
    KnowledgeContextCandidateKind,
    KnowledgeContextNarrativeUpdate,
    KnowledgeDraft,
    KnowledgeEdgeKind,
    KnowledgeGenerationWorkflowBatch,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeStatus,
    SemanticAnalysisResult,
    SemanticEnumValue,
    SemanticMethodDefinition,
    SemanticPatternEvidence,
    SourceBaseline,
    SourceReference,
    ScanManifest,
    StateMachineDefinition,
    StateTransition,
    SystemDefinition,
)


SYSTEM_ID = "demo-semantic-system"


class FixedManifestArtifacts:
    """为目录测试返回一个不可变语义Manifest。"""

    def __init__(self, manifest: ScanManifest):
        """保存测试唯一Manifest。

        Args:
            manifest: 目录服务每次读取都应返回的扫描结果。
        """

        self.manifest = manifest

    def read(self, system_id: str, scan_id: str) -> ScanManifest:
        """校验系统和latest身份后返回固定Manifest。

        Args:
            system_id: 请求系统ID。
            scan_id: 仅允许latest或固定扫描ID。

        Returns:
            构造时传入的不可变Manifest。
        """

        assert system_id == self.manifest.system_id
        assert scan_id in {"latest", self.manifest.scan_id}
        return self.manifest

    def list_manifests(self, system_id: str) -> list[ScanManifest]:
        """返回轻量扫描历史投影所需的唯一Manifest。

        Args:
            system_id: 必须与固定Manifest所属系统一致。

        Returns:
            只包含固定Manifest的扫描历史。
        """

        assert system_id == self.manifest.system_id
        return [self.manifest]


def _manifest(source_root: Path) -> ScanManifest:
    """构造共享方法、责任链和中文状态标签组成的语义Manifest。

    Args:
        source_root: 注册系统源码根。

    Returns:
        可直接输入扫描目录服务的严格模型。
    """

    source_ref = SourceReference(path="src/OrderService.java", symbol="demo.OrderService#shared()", line=12)
    pending = SemanticEnumValue(
        enum_type="demo.OrderState",
        code="PENDING_APPLY",
        display_name="待申请",
        description_field="name",
        source_ref=source_ref,
    )
    done = SemanticEnumValue(
        enum_type="demo.OrderState",
        code="DONE",
        display_name="完成",
        description_field="name",
        source_ref=source_ref,
    )
    shared = SemanticMethodDefinition(
        symbol_id="demo.OrderService#shared()",
        qualified_class_name="demo.OrderService",
        method_name="shared",
        source_ref=source_ref,
        entry_point_ids=["entry:first", "entry:second"],
        reuse_entry_count=2,
    )
    shared_overload = SemanticMethodDefinition(
        symbol_id="demo.OrderService#shared(java.lang.String)",
        qualified_class_name="demo.OrderService",
        method_name="shared",
        parameter_types=["java.lang.String"],
        source_ref=source_ref.model_copy(
            update={"symbol": "demo.OrderService#shared(java.lang.String)"}
        ),
        entry_point_ids=["entry:first", "entry:second"],
        reuse_entry_count=2,
    )
    getter = SemanticMethodDefinition(
        symbol_id="demo.OrderDTO#getName()",
        qualified_class_name="demo.OrderDTO",
        method_name="getName",
        source_ref=source_ref,
        entry_point_ids=["entry:first", "entry:second"],
        reuse_entry_count=2,
    )
    chain = SemanticMethodDefinition(
        symbol_id="demo.CheckChain#check()",
        qualified_class_name="demo.CheckChain",
        method_name="check",
        source_ref=source_ref,
        entry_point_ids=["entry:first"],
        reuse_entry_count=1,
    )
    pattern = SemanticPatternEvidence(
        symbol_id=chain.symbol_id,
        pattern="responsibility_chain",
        evidence="Chain类型与有序委托共同证明责任链。",
        source_refs=[source_ref],
        confidence=0.95,
    )
    transition = StateTransition(
        transition_id="state-transition:apply-done",
        actor="demo.ApplyActor",
        from_states=["PENDING_APPLY"],
        to_states=["DONE"],
        from_state_labels=[pending],
        to_state_labels=[done],
        source_ref=source_ref,
    )
    return ScanManifest(
        scan_id="scan-semantic",
        system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path=str(source_root), dirty=True, dirty_digest="digest"),
        state_machines=[
            StateMachineDefinition(
                machine_id="state-machine:OrderState",
                system_id=SYSTEM_ID,
                state_enum="demo.OrderState",
                title="订单状态机",
                transitions=[transition],
            )
        ],
        semantic_analysis=SemanticAnalysisResult(
            system_id=SYSTEM_ID,
            methods=[shared, shared_overload, getter, chain],
            enum_values=[pending, done],
            patterns=[pattern],
        ),
    )


def test_semantic_method_identity_includes_fully_qualified_parameter_types(tmp_path: Path) -> None:
    """重载和签名变更应生成不同公共知识身份，单入口模式不能直接绕过门禁。

    Args:
        tmp_path: pytest隔离的语义知识根。

    Returns:
        None；两个重载目标身份不同且单所有者目标被拒绝时通过。
    """

    store, source_root = _store(tmp_path)
    source_path = source_root / "src/OrderService.java"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "package demo; class OrderService { void shared() {} void shared(String value) {} }",
        encoding="utf-8",
    )
    manifest = _manifest(source_root)
    catalog = ScanCatalogService(store, FixedManifestArtifacts(manifest)).build_catalog(SYSTEM_ID)
    parameterless_id = "semantic:" + hashlib.sha256(
        "demo.OrderService#shared()".encode("utf-8")
    ).hexdigest()[:20]
    overloaded_id = "semantic:" + hashlib.sha256(
        "demo.OrderService#shared(java.lang.String)".encode("utf-8")
    ).hexdigest()[:20]
    target_ids = {target.target_id for target in catalog.targets}

    assert parameterless_id in target_ids
    assert overloaded_id in target_ids
    assert parameterless_id != overloaded_id

    single_owner_id = "semantic:" + hashlib.sha256(
        "demo.CheckChain#check()".encode("utf-8")
    ).hexdigest()[:20]
    with pytest.raises(KnowledgeNotFoundError, match="not shared business logic"):
        JavaKnowledgeTracer().trace(manifest, single_owner_id)


def _store(tmp_path: Path) -> tuple[GitKnowledgeStore, Path]:
    """初始化一个带源码注册的空知识存储。

    Args:
        tmp_path: pytest隔离根。

    Returns:
        Git知识存储与源码根。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge-base")
    store.initialize()
    store.register_system(SystemDefinition(system_id=SYSTEM_ID, name="语义系统", source_path=str(source_root)))
    return store, source_root


def test_scan_history_exposes_fixed_git_revision_for_console(tmp_path: Path) -> None:
    """扫描历史应直接提供页面识别branch、tag或commit所需的revision。

    Args:
        tmp_path: pytest隔离的系统注册和源码目录。

    Returns:
        None；轻量历史中的scan、commit、branch与revision均来自同一Manifest时通过。
    """

    store, source_root = _store(tmp_path)
    manifest = _manifest(source_root)
    baseline = manifest.baseline.model_copy(
        update={"commit": "a" * 40, "branch": "release/refund", "revision": "refund-v4.1"}
    )
    versioned_manifest = manifest.model_copy(update={"baseline": baseline})

    # 页面列表只读取轻量历史；该投影必须保留用户扫描时选择的原始revision。
    history = ScanCatalogService(store, FixedManifestArtifacts(versioned_manifest)).list_history(SYSTEM_ID)

    assert history[0].scan_id == versioned_manifest.scan_id
    assert history[0].commit == baseline.commit
    assert history[0].branch == baseline.branch
    assert history[0].revision == baseline.revision


def test_catalog_groups_shared_logic_patterns_and_state_display(tmp_path: Path) -> None:
    """目录应过滤getter和单入口模式，只保留跨所有者公共节点及中文状态。"""

    store, source_root = _store(tmp_path)
    manifest = _manifest(source_root)
    catalog = ScanCatalogService(store, FixedManifestArtifacts(manifest)).build_catalog(SYSTEM_ID)

    by_name = {target.display_name: target for target in catalog.targets}
    assert by_name["业务背景"].category == "background"
    assert by_name["OrderService.shared"].group == "通用逻辑"
    assert "CheckChain.check" not in by_name
    assert "OrderDTO.getName" not in by_name
    assert "待申请（PENDING_APPLY） → 完成（DONE）" in by_name


def test_state_transition_generated_child_logic_stays_under_parent_target(tmp_path: Path) -> None:
    """状态流转生成的辅助逻辑应归属父目标，不能膨胀目录与批量范围。

    Args:
        tmp_path: pytest隔离的状态机Manifest与知识仓库。

    Returns:
        None；父目标吸收子节点且目录不再出现子节点身份时通过。
    """

    store, source_root = _store(tmp_path)
    manifest = _manifest(source_root)
    transition_id = manifest.state_machines[0].transitions[0].transition_id
    child = KnowledgeNode(
        node_id="logic:ApplyActor#addTask",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.COMMON_LOGIC,
        title="ApplyActor · addTask",
        status=KnowledgeStatus.CODE_VERIFIED,
        metadata={"scan_id": manifest.scan_id},
    )
    store.write_node(child, "状态流转执行时增加后置任务。")
    store.write_draft_batch(
        KnowledgeGenerationWorkflowBatch(
            batch_id="knowledge-workflow-state-parent",
            system_id=SYSTEM_ID,
            scan_id=manifest.scan_id,
            target_ids=[transition_id],
            status="PENDING_CONFIRMATION",
            drafts=[
                KnowledgeDraft(
                    draft_id="draft-state-child",
                    system_id=SYSTEM_ID,
                    target_id=transition_id,
                    node=child,
                    content="状态流转执行时增加后置任务。",
                )
            ],
        )
    )

    catalog = ScanCatalogService(store, FixedManifestArtifacts(manifest)).build_catalog(SYSTEM_ID)
    by_id = {target.target_id: target for target in catalog.targets}

    assert child.node_id not in by_id
    assert child.node_id in by_id[transition_id].knowledge_node_ids


def test_target_detail_uses_background_and_shared_logic_templates(tmp_path: Path) -> None:
    """背景详情应带唯一上下文，跨所有者公共逻辑应使用逻辑模板。

    Args:
        tmp_path: pytest隔离的语义知识根。

    Returns:
        None；背景和公共逻辑分别使用正确详情模板时通过。
    """

    store, source_root = _store(tmp_path)
    manifest = _manifest(source_root)
    scan_root = store.root / ".opentest/scans" / SYSTEM_ID
    scan_root.mkdir(parents=True)
    (scan_root / f"{manifest.scan_id}.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (scan_root / "latest.json").write_text(json.dumps({"scan_id": manifest.scan_id}), encoding="utf-8")
    artifacts = FixedManifestArtifacts(manifest)
    catalog = ScanCatalogService(store, artifacts).build_catalog(SYSTEM_ID)
    discovery = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))
    discovery.save_narrative(
        SYSTEM_ID,
        KnowledgeContextNarrativeUpdate(system_purpose="订单处理", upstream_entry_narrative="交易系统调用"),
    )
    background = discovery.target_detail(SYSTEM_ID, "background:system", catalog)
    shared_id = "semantic:" + hashlib.sha256("demo.OrderService#shared()".encode("utf-8")).hexdigest()[:20]
    # 人工术语只允许关联目录中真实存在的跨所有者公共目标。
    discovery.create_candidate(
        SYSTEM_ID,
        KnowledgeContextCandidateCreate(
            kind=KnowledgeContextCandidateKind.BUSINESS_TERM,
            name="共享订单规则",
            business_meaning="被两个订单入口共同复用",
            affected_target_ids=[shared_id],
        ),
    )
    shared = discovery.target_detail(SYSTEM_ID, shared_id, catalog)

    assert background.template_kind == "background"
    assert background.background_context is not None
    assert background.background_context.system_purpose == "订单处理"
    assert shared.template_kind == "logic"
    assert shared.semantic_evidence == []


def test_semantic_common_logic_target_generates_one_stable_shared_node(tmp_path: Path) -> None:
    """semantic目标应合并真实入口节点、CALLS边且发布后只有一个目录身份。

    Args:
        tmp_path: pytest隔离源码根。

    Side Effects:
        只创建语义Manifest引用的本地Java证据文件。
    """

    store, source_root = _store(tmp_path)
    source_path = source_root / "src/OrderService.java"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "package demo; class OrderService { void shared() {} }",
        encoding="utf-8",
    )
    entries: list[EntryPoint] = []
    semantic_entry_ids: list[str] = []
    for prefix in ("First", "Second"):
        facade_path = source_root / f"src/{prefix}Facade.java"
        implementation_path = source_root / f"src/{prefix}FacadeImpl.java"
        method_name = prefix.lower()
        facade_path.write_text(
            f"package demo; interface {prefix}Facade {{ void {method_name}(); }}",
            encoding="utf-8",
        )
        implementation_path.write_text(
            f"package demo; class {prefix}FacadeImpl {{ void {method_name}() {{ orderService.load(); }} }}",
            encoding="utf-8",
        )
        source_id = f"demo.{prefix}Facade#{method_name}"
        entries.append(
            EntryPoint(
                entry_id=f"facade:{source_id}",
                system_id=SYSTEM_ID,
                kind="facade",
                display_name=f"{prefix}Facade#{method_name}",
                source_id=source_id,
                source_path=str(facade_path),
            )
        )
        semantic_entry_ids.append(f"demo.{prefix}FacadeImpl#{method_name}()")
    manifest = _manifest(source_root)
    semantic_analysis = manifest.semantic_analysis
    assert semantic_analysis is not None
    methods = [
        method.model_copy(update={"entry_point_ids": semantic_entry_ids})
        if method.symbol_id == "demo.OrderService#shared()"
        else method
        for method in semantic_analysis.methods
    ]
    manifest = manifest.model_copy(
        update={
            "entries": entries,
            "semantic_analysis": semantic_analysis.model_copy(update={"methods": methods}),
        }
    )
    target_id = "semantic:" + hashlib.sha256("demo.OrderService#shared()".encode("utf-8")).hexdigest()[:20]

    batch = JavaKnowledgeTracer().trace(manifest, target_id)

    assert batch.entry_id == target_id
    semantic_nodes = [node for node in batch.nodes if node.node_id.startswith("logic:semantic:")]
    assert len(semantic_nodes) == 1
    node = semantic_nodes[0]
    assert node.node_id.startswith("logic:semantic:")
    assert node.aliases == [target_id, "demo.OrderService#shared()", *semantic_entry_ids]
    assert node.metadata["reuse_entry_count"] == 2
    assert semantic_entry_ids[0] in batch.content_by_node[node.node_id]
    entry_node_ids = {f"entry:{entry.source_id}" for entry in entries}
    assert entry_node_ids.issubset({item.node_id for item in batch.nodes})
    semantic_callers = {
        edge.source_node_id
        for edge in batch.edges
        if edge.target_node_id == node.node_id and edge.kind.value == "calls"
    }
    assert semantic_callers == entry_node_ids

    # 发布批次后，Manifest semantic target吸收共享节点状态，不能再出现logic:semantic目录副本。
    for published in batch.nodes:
        store.write_node(published, batch.content_by_node[published.node_id])
    store.write_edges(SYSTEM_ID, batch.edges)
    catalog = ScanCatalogService(store, FixedManifestArtifacts(manifest)).build_catalog(SYSTEM_ID)
    semantic_identities = [
        target.target_id
        for target in catalog.targets
        if target.target_id in {target_id, node.node_id}
    ]
    assert semantic_identities == [target_id]


def test_semantic_common_logic_links_state_transition_owners(tmp_path: Path) -> None:
    """两条状态流转复用的方法应独立发布，并从每条流转建立可跳转CALLS关系。

    Args:
        tmp_path: pytest隔离的Actor源码和知识根。

    Returns:
        None；公共节点、两条流转节点及CALLS边全部准确时通过。
    """

    _store_value, source_root = _store(tmp_path)
    actor_path = source_root / "src/RefundCancelActor.java"
    actor_path.parent.mkdir(parents=True)
    actor_path.write_text(
        "package demo; class RefundCancelActor { void execute() { helper(); } void helper() {} }",
        encoding="utf-8",
    )
    shared_path = source_root / "src/SharedRefundRules.java"
    shared_path.write_text(
        "package demo; class SharedRefundRules { void evaluate() {} }",
        encoding="utf-8",
    )
    transitions = [
        StateTransition(
            transition_id=f"transition:cancel:{index}",
            actor="RefundCancelActor",
            from_states=[from_state],
            to_states=["REFUND_CANCEL"],
            source_ref=SourceReference(
                path="src/RefundCancelActor.java",
                symbol="RefundCancelActor",
                line=1,
            ),
        )
        for index, from_state in enumerate(["WAIT_REFUND", "REFUND_FAIL"], start=1)
    ]
    symbol_id = "demo.SharedRefundRules#evaluate()"
    method = SemanticMethodDefinition(
        symbol_id=symbol_id,
        qualified_class_name="demo.SharedRefundRules",
        method_name="evaluate",
        source_ref=SourceReference(
            path="src/SharedRefundRules.java",
            symbol=symbol_id,
            line=1,
        ),
        entry_point_ids=[transition.transition_id for transition in transitions],
        reuse_entry_count=2,
    )
    manifest = ScanManifest(
        scan_id="scan-transition-owner",
        system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path=str(source_root), commit="transition-owner"),
        state_machines=[
            StateMachineDefinition(
                machine_id="state-machine:refund",
                system_id=SYSTEM_ID,
                state_enum="RefundState",
                title="退票状态机",
                transitions=transitions,
            )
        ],
        semantic_analysis=SemanticAnalysisResult(system_id=SYSTEM_ID, methods=[method]),
    )
    target_id = "semantic:" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[:20]
    batch = JavaKnowledgeTracer().trace(manifest, target_id)
    common_node = next(node for node in batch.nodes if node.kind == KnowledgeNodeKind.COMMON_LOGIC)

    assert {transition.transition_id for transition in transitions}.issubset(
        {node.node_id for node in batch.nodes}
    )
    assert {
        edge.source_node_id
        for edge in batch.edges
        if edge.target_node_id == common_node.node_id and edge.kind == KnowledgeEdgeKind.CALLS
    } == {transition.transition_id for transition in transitions}
