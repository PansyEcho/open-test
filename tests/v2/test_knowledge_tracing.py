"""验证createOrder纵向知识追踪、确认保护、索引发布和Agent安全边界。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentest.adapters.agent_runner import AgentRunner, AgentRunnerConfig
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.knowledge_tracing import JavaKnowledgeTracer
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.application.knowledge import KnowledgeGenerationService
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    AgentRunRequest,
    EntryPoint,
    KnowledgeConfirmation,
    KnowledgeGenerationRequest,
    KnowledgeNodeKind,
    KnowledgeStatus,
    ScanManifest,
    SourceBaseline,
    SourceReference,
    StateMachineDefinition,
    StateTransition,
    SystemDefinition,
)


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
    """其他Facade显示名不在源码中时仍应按完整source_id方法名定位证据。"""

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
    assert batch.nodes[0].source_refs[0].line == 1
    assert batch.nodes[0].source_refs[0].symbol == source_id


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
    executable.write_text("#!/bin/sh\nprintf 'agent-output:%s' \"$2\"\n", encoding="utf-8")
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
    assert "agent-output:--sandbox" in output_path.read_text(encoding="utf-8")
    assert evidence.prompt_digest


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
