"""验证createOrder纵向知识追踪、确认保护、索引发布和Agent安全边界。"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from opentest.adapters.agent_runner import AgentRunner, AgentRunnerConfig
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.knowledge_tracing import JavaKnowledgeTracer
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.application.knowledge import KnowledgeGenerationService
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import LocalTaskManager, report_task_progress
from opentest.domain.errors import ExecutionFailure, KnowledgeValidationError, ScopeViolationError, TaskCancelledError
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
    TaskProgressUpdate,
    TaskStatus,
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
        "interface OuterRefundFacade { Object pageBusinessLog(Object request); }\n",
        encoding="utf-8",
    )
    implementation.write_text(
        "class OuterRefundFacadeImpl {\n"
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
        "interface OuterRefundFacade { Object pageBusinessLog(Object request); }\n",
        encoding="utf-8",
    )
    implementation.write_text(
        "class OuterRefundFacadeImpl {\n"
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
        "interface OuterRefundFacade { Object pageBusinessLog(Object request); }\n",
        encoding="utf-8",
    )
    implementation.write_text(
        "class OuterRefundFacadeImpl {\n"
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
    assert "--sandbox read-only" in output
    assert "--disable shell_tool" in output
    assert "--disable unified_exec" in output
    assert "mcp_servers={}" in output
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

    assert "exec resume 019c-stream-resume-test" in output
    assert 'sandbox_mode="read-only"' in output
    assert "--ignore-user-config" in output


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
