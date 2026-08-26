"""验证知识所有权、Codex终态归档和一键Case替换的增量契约。"""

from __future__ import annotations

import stat
import time
from datetime import timedelta
from pathlib import Path

import pytest

from opentest.adapters.case_store import GitCaseStore
from opentest.adapters.environment_config import LocalSystemSettingsStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.scenarios import ScenarioGenerationService
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import LocalTaskManager
from opentest.domain.models import (
    CaseFixtureBindingUpdate,
    CaseGenerationCreateRequest,
    CaseGenerationExecutionRequest,
    CaseGenerationStatus,
    CoverageTarget,
    AgentKnowledgeEnvelope,
    EntryPoint,
    KnowledgeClientHandoff,
    KnowledgeClientHandoffStatus,
    KnowledgeEdge,
    KnowledgeEdgeKind,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeStatus,
    KnowledgeTestPoint,
    OracleRequest,
    ScanManifest,
    ScenarioDefinition,
    ScenarioGenerationBatch,
    ScenarioStep,
    ScenarioVariant,
    RunRecord,
    Snapshot,
    SourceBaseline,
    SystemDefinition,
    TaskRecord,
    TaskStatus,
    utc_now,
)
from opentest.domain.errors import KnowledgeValidationError


SYSTEM_ID = "refund-core"
ENTRY_ID = "facade:demo.RefundFacade#cancel"
ENTRY_NODE_ID = "entry:demo.RefundFacade#cancel"


def _handoff(task_id: str, suffix: str = "a") -> KnowledgeClientHandoff:
    """构造绑定稳定任务和知识目标的最小Codex handoff。

    Args:
        task_id: handoff必须反向绑定的任务ID。
        suffix: 用于避免测试记录身份冲突的十六进制尾标。

    Returns:
        可进入等待或终态的严格客户端接管记录。
    """

    return KnowledgeClientHandoff(
        handoff_id=f"handoff-{'a' * 23}{suffix}",
        task_id=task_id,
        attempt_id=f"attempt-{suffix}",
        system_id=SYSTEM_ID,
        target_id=ENTRY_ID,
        scan_id="scan-archive",
        batch_id=f"batch-{suffix}",
        agent_run_id=f"agent-{'b' * 15}{suffix}",
        thread_id=f"thread-{suffix}",
        deep_link=f"codex://threads/thread-{suffix}",
    )


def test_terminal_client_handoffs_archive_on_transition_and_restart(tmp_path: Path) -> None:
    """运行中终态应立即归档，启动时还要归档全部遗留终态且保持按ID查询。

    Args:
        tmp_path: pytest隔离的任务目录根。

    Returns:
        None；活动列表、归档列表和按ID读取契约全部成立时通过。
    """

    task_root = tmp_path / "tasks"
    manager = LocalTaskManager(task_root, max_workers=1)
    waiting = manager.create_waiting_task(
        "knowledge-codex-client-handoff",
        SYSTEM_ID,
        TaskStatus.WAITING_FOR_CLIENT,
        _handoff("task-aaaaaaaaaaaaaaaa"),
    )
    published_handoff = waiting.client_handoff.model_copy(
        update={"status": KnowledgeClientHandoffStatus.PUBLISHED, "updated_at": utc_now()}
    )
    completed = manager.transition_waiting_task(
        waiting.task_id,
        TaskStatus.COMPLETED,
        published_handoff,
    )

    # 即时归档后普通列表只含活动任务，但原任务ID和Codex聊天仍可恢复。
    assert manager.list_records(SYSTEM_ID, {"knowledge-codex-client-handoff"}) == []
    assert manager.get(completed.task_id).client_handoff.deep_link == published_handoff.deep_link
    assert (task_root / "archive" / f"{completed.task_id}.json").is_file()

    terminal_statuses = [TaskStatus.PARTIAL, TaskStatus.FAILED, TaskStatus.INTERRUPTED, TaskStatus.CANCELLED]
    for index, status in enumerate(terminal_statuses, start=1):
        suffix = f"{index:x}"
        task_id = f"task-{suffix * 16}"
        handoff = _handoff(task_id, suffix)
        record = TaskRecord(
            task_id=task_id,
            operation="knowledge-codex-client-handoff",
            system_id=SYSTEM_ID,
            status=status,
            trace_id=f"trace-{suffix}",
            client_handoff=handoff,
            result={"client_handoff": handoff.model_dump(mode="json")},
            ended_at=utc_now() + timedelta(seconds=index),
        )
        # 模拟旧版本遗留在活动目录的完整终态文件，重启负责移动而不改写内容。
        manager._write(record)
    manager.close()

    restarted = LocalTaskManager(task_root, max_workers=1)
    archived = restarted.list_archived_records(SYSTEM_ID, {"knowledge-codex-client-handoff"})
    restarted.close()

    assert {item.status for item in archived} == {
        TaskStatus.COMPLETED,
        TaskStatus.PARTIAL,
        TaskStatus.FAILED,
        TaskStatus.INTERRUPTED,
        TaskStatus.CANCELLED,
    }
    assert not list(task_root.glob("task-*.json"))


def test_task_get_follows_terminal_record_moved_during_poll(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """终态文件恰在轮询读取前移动时应自动转读归档文件。

    Args:
        tmp_path: pytest隔离的任务目录根。
        monkeypatch: 在首次活动文件读取前模拟原子归档移动。

    Returns:
        None；同一任务ID从归档文件读取成功时通过。
    """

    task_root = tmp_path / "tasks"
    manager = LocalTaskManager(task_root, max_workers=1)
    record = manager.create_waiting_task(
        "knowledge-codex-client-handoff",
        SYSTEM_ID,
        TaskStatus.WAITING_FOR_CLIENT,
        _handoff("task-bbbbbbbbbbbbbbbb", "b"),
    )
    active_path = task_root / f"{record.task_id}.json"
    archived_path = task_root / "archive" / active_path.name
    original_read_text = Path.read_text
    moved = False

    def move_before_read(path: Path, *args, **kwargs) -> str:
        """在活动记录首次读取前模拟另一个终态线程完成原子移动。

        Args:
            path: 当前准备读取的任务文件。
            args: 透传给Path.read_text的位置参数。
            kwargs: 透传给Path.read_text的关键字参数。

        Returns:
            原始Path.read_text读取结果；旧路径会按真实竞态抛出FileNotFoundError。

        Side Effects:
            仅第一次命中活动任务路径时把文件移动到归档目录。
        """

        nonlocal moved
        if path == active_path and not moved:
            moved = True
            active_path.replace(archived_path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", move_before_read)
    try:
        restored = manager.get(record.task_id)
    finally:
        manager.close()

    assert restored.task_id == record.task_id
    assert archived_path.is_file()


def _case_service(tmp_path: Path) -> tuple[ScenarioGenerationService, GitCaseStore, GitKnowledgeStore]:
    """构造带入口、公共规则、状态流转和另一个入口Case的隔离服务。

    Args:
        tmp_path: pytest隔离的源码与知识根。

    Returns:
        场景服务、Case存储和知识存储。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    source_path = source_root / "RefundFacade.java"
    source_path.write_text("package demo; interface RefundFacade { Object cancel(Object request); }", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    baseline = SourceBaseline(source_path=str(source_root), commit="case-ownership")
    store.register_system(
        SystemDefinition(system_id=SYSTEM_ID, name="退票核心", source_path=str(source_root), baseline=baseline)
    )
    artifacts = SourceScanArtifactStore(store.root)
    scan_id, tool_root = artifacts.allocate(SYSTEM_ID, baseline)
    tool_root.mkdir(parents=True)
    entry = KnowledgeNode(
        node_id=ENTRY_NODE_ID,
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        title="RefundFacade#cancel",
        summary="取消退票入口",
        aliases=[ENTRY_ID],
        status=KnowledgeStatus.USER_CONFIRMED,
        confidence=1,
        metadata={"scan_id": scan_id},
        test_points=[
            KnowledgeTestPoint(
                kind="main_flow",
                title="取消成功主流程",
                condition="退票单处于允许取消状态",
                expected_outcome="返回取消成功且状态进入REFUND_CANCEL",
            ),
            KnowledgeTestPoint(
                kind="validation",
                title="不可取消状态校验",
                condition="退票单处于终态",
                expected_outcome="返回稳定业务拒绝且状态不变",
            ),
        ],
    )
    shared = KnowledgeNode(
        node_id="logic:semantic:shared-cancel",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.COMMON_LOGIC,
        title="共享取消校验",
        summary="两个入口复用取消校验",
        status=KnowledgeStatus.USER_CONFIRMED,
        confidence=1,
        metadata={"scan_id": scan_id},
        test_points=[
            KnowledgeTestPoint(
                kind="common_rule",
                title="公共取消规则",
                condition="通过cancel入口触发共享校验",
                expected_outcome="共享规则对同一业务状态给出一致结果",
            )
        ],
    )
    transition = KnowledgeNode(
        node_id="state-transition:refund-cancel",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.STATE_TRANSITION,
        title="WAIT_REFUND → REFUND_CANCEL",
        summary="取消状态流转由状态节点维护",
        status=KnowledgeStatus.USER_CONFIRMED,
        confidence=1,
        metadata={"scan_id": scan_id},
        test_points=[
            KnowledgeTestPoint(
                kind="transition",
                title="取消状态流转",
                condition="WAIT_REFUND状态执行取消",
                expected_outcome="状态更新为REFUND_CANCEL",
            )
        ],
    )
    for node in (entry, shared, transition):
        store.write_node(node, f"## 业务结论\n\n{node.summary}")
    store.write_edges(
        SYSTEM_ID,
        [
            KnowledgeEdge(
                edge_id="edge:entry-shared",
                system_id=SYSTEM_ID,
                source_node_id=ENTRY_NODE_ID,
                target_node_id=shared.node_id,
                kind=KnowledgeEdgeKind.CALLS,
            ),
            KnowledgeEdge(
                edge_id="edge:entry-transition",
                system_id=SYSTEM_ID,
                source_node_id=ENTRY_NODE_ID,
                target_node_id=transition.node_id,
                kind=KnowledgeEdgeKind.TRANSITIONS,
            ),
        ],
    )
    artifacts.write_manifest(
        ScanManifest(
            scan_id=scan_id,
            system_id=SYSTEM_ID,
            baseline=baseline,
            entries=[
                EntryPoint(
                    entry_id=ENTRY_ID,
                    system_id=SYSTEM_ID,
                    kind=KnowledgeNodeKind.FACADE,
                    display_name="RefundFacade#cancel",
                    source_id="demo.RefundFacade#cancel",
                    source_path=str(source_path),
                )
            ],
            tool_root=str(tool_root),
        )
    )
    artifacts.publish_latest(SYSTEM_ID, scan_id)
    case_store = GitCaseStore(store)
    return ScenarioGenerationService(store, case_store, artifacts=artifacts), case_store, store


def _other_entry_batch() -> ScenarioGenerationBatch:
    """构造必须在cancel全量重生成期间保留的其他入口阻塞资产。

    Returns:
        只包含query入口的独立阻塞批次。
    """

    coverage = CoverageTarget(
        target_id="coverage:query",
        system_id=SYSTEM_ID,
        node_id="entry:demo.RefundFacade#query",
        kind="boundary",
        title="查询边界",
    )
    step = ScenarioStep(
        step_id="query",
        name="查询退票单",
        operation_id="facade:demo.RefundFacade#query",
        params={"arguments": {}},
    )
    scenario = ScenarioDefinition(
        scenario_id="scenario:query",
        system_id=SYSTEM_ID,
        entry_node_id="facade:demo.RefundFacade#query",
        title="查询退票单",
        coverage_target_ids=[coverage.target_id],
        steps=[step],
    )
    variant = ScenarioVariant(
        variant_id="variant:query",
        scenario_id=scenario.scenario_id,
        system_id=SYSTEM_ID,
        seed=0,
        inputs={},
        steps=[step],
        coverage_target_ids=[coverage.target_id],
        lifecycle="blocked",
    )
    return ScenarioGenerationBatch(
        batch_id="batch:query",
        system_id=SYSTEM_ID,
        entry_node_id=scenario.entry_node_id,
        coverage_targets=[coverage],
        scenarios=[scenario],
        variants=[variant],
    )


def _old_cancel_batch() -> ScenarioGenerationBatch:
    """构造同入口待替换的旧系统Case和必须保留的用户编辑Case。

    Returns:
        同时携带旧自动资产与`user_edited`资产的cancel批次。
    """

    generated_target = CoverageTarget(
        target_id="coverage:cancel:old-generated",
        system_id=SYSTEM_ID,
        node_id=ENTRY_NODE_ID,
        kind="boundary",
        title="旧自动取消Case",
    )
    user_target = CoverageTarget(
        target_id="coverage:cancel:user-edited",
        system_id=SYSTEM_ID,
        node_id=ENTRY_NODE_ID,
        kind="boundary",
        title="用户编辑取消Case",
    )
    execute = ScenarioStep(
        step_id="cancel-old-execute",
        name="执行取消",
        operation_id=ENTRY_ID,
        params={"arguments": {}},
    )
    assertion = ScenarioStep(
        step_id="cancel-user-assert",
        name="校验用户期望",
        action="assert",
        assertions={"$.code": 0},
    )
    generated_scenario = ScenarioDefinition(
        scenario_id="scenario:cancel:old-generated",
        system_id=SYSTEM_ID,
        entry_node_id=ENTRY_ID,
        title="旧自动取消Case",
        coverage_target_ids=[generated_target.target_id],
        steps=[execute],
    )
    user_scenario = ScenarioDefinition(
        scenario_id="scenario:cancel:user-edited",
        system_id=SYSTEM_ID,
        entry_node_id=ENTRY_ID,
        title="用户编辑取消Case",
        coverage_target_ids=[user_target.target_id],
        steps=[execute, assertion],
    )
    generated_variant = ScenarioVariant(
        variant_id="variant:cancel:old-generated",
        scenario_id=generated_scenario.scenario_id,
        system_id=SYSTEM_ID,
        seed=0,
        inputs={},
        steps=[execute],
        coverage_target_ids=[generated_target.target_id],
        lifecycle="blocked",
    )
    user_variant = ScenarioVariant(
        variant_id="variant:cancel:user-edited",
        scenario_id=user_scenario.scenario_id,
        system_id=SYSTEM_ID,
        seed=0,
        inputs={},
        steps=[execute, assertion],
        coverage_target_ids=[user_target.target_id],
        lifecycle="user_edited",
    )
    return ScenarioGenerationBatch(
        batch_id="batch:cancel:old",
        system_id=SYSTEM_ID,
        entry_node_id=ENTRY_ID,
        coverage_targets=[generated_target, user_target],
        scenarios=[generated_scenario, user_scenario],
        variants=[generated_variant, user_variant],
    )


def test_one_click_case_generation_normalizes_entry_and_replaces_only_system_assets(tmp_path: Path) -> None:
    """旧entry身份应唯一规范化，一次生成多Case，补绑定后替换旧自动资产且不泄露敏感值。

    Args:
        tmp_path: pytest隔离的知识、扫描和Case根。

    Returns:
        None；规范化、多Case、精确替换和敏感隔离均成立时通过。
    """

    service, case_store, store = _case_service(tmp_path)
    case_store.write_batch(_other_entry_batch(), mode="regression")
    case_store.write_batch(_old_cancel_batch(), mode="regression")
    custom_path = store.system_root(SYSTEM_ID) / "cases" / "custom" / "manual.yaml"
    custom_path.parent.mkdir(parents=True)
    custom_path.write_text("title: 人工取消Case\n", encoding="utf-8")
    first = service.create_case_generation(
        SYSTEM_ID,
        CaseGenerationCreateRequest(entry_node_id="entry:demo.RefundFacade#cancel"),
    )

    assert first.entry_node_id == ENTRY_ID
    assert first.status == CaseGenerationStatus.CASES_GENERATED
    assert first.batch is not None
    assert len(first.batch.variants) == 4
    assert all(variant.lifecycle == "blocked" for variant in first.batch.variants)

    bindings = []
    for index, matrix_item in enumerate(first.matrix_items):
        update = CaseFixtureBindingUpdate(
            test_point_id=matrix_item.matrix_item_id,
            arguments={"refund_id": f"secret-argument-{index}"},
            response_assertions={"$.code": f"secret-expected-{index}"},
            oracle=OracleRequest(
                oracle_id=f"oracle-cancel-{index}",
                system_id=SYSTEM_ID,
                kind="mysql",
                resource_id="mysql:refund",
                operation_id="refund.detail",
                assertions={"$.status": "REFUND_CANCEL"},
            ),
            cleanup_steps=[
                ScenarioStep(
                    step_id=f"cleanup-{index}",
                    name="清理测试退票单",
                    action="cleanup",
                    params={"refund_id": f"secret-cleanup-{index}"},
                )
            ],
        )
        bindings.append((ENTRY_ID, f"binding_{index}", update))
    service.bind_fixture_provider(lambda _system_id, _entry_id: bindings)
    second = service.create_case_generation(
        SYSTEM_ID,
        CaseGenerationCreateRequest(entry_node_id=ENTRY_ID),
    )

    assert second.generation_id == first.generation_id
    assert second.batch is not None
    assert all(variant.lifecycle == "generated" for variant in second.batch.variants)
    assert all(step.assertions_from for variant in second.batch.variants for step in variant.steps if step.action == "assert")
    assert {variant.variant_id for variant in case_store._list_variants_unlocked(SYSTEM_ID)} == {
        "variant:query",
        "variant:cancel:user-edited",
        *(variant.variant_id for variant in second.batch.variants),
    }
    assert "coverage:cancel:old-generated" not in {
        target.target_id for target in case_store.list_coverage_targets(SYSTEM_ID)
    }
    assert "coverage:cancel:user-edited" in {
        target.target_id for target in case_store.list_coverage_targets(SYSTEM_ID)
    }
    assert len(case_store.list_generation_records(SYSTEM_ID)) == 1
    assert custom_path.read_text(encoding="utf-8") == "title: 人工取消Case\n"

    # Git Case只保存本地运行键引用，Fixture、断言值和清理参数均不得泄露。
    case_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (store.system_root(SYSTEM_ID) / "cases").rglob("*.yaml")
        if "custom" not in path.parts
    )
    assert "secret-argument" not in case_text
    assert "secret-expected" not in case_text
    assert "secret-cleanup" not in case_text


def test_local_case_fixture_api_returns_only_safe_summary(tmp_path: Path) -> None:
    """本地Fixture存储应保留完整值但查询只返回配置状态并强制0600权限。

    Args:
        tmp_path: pytest隔离的本地QA配置根。

    Returns:
        None；原值仅存于0600文件且摘要无敏感值时通过。
    """

    settings = LocalSystemSettingsStore(tmp_path / "environments")
    update = CaseFixtureBindingUpdate(
        test_point_id="matrix:cancel-success",
        arguments={"refund_id": "sensitive-refund-id"},
        response_assertions={"$.code": "sensitive-code"},
        oracle=OracleRequest(
            oracle_id="oracle-sensitive-cancel",
            system_id=SYSTEM_ID,
            kind="mysql",
            resource_id="mysql:refund",
            operation_id="refund.detail",
            assertions={"$.status": "REFUND_CANCEL"},
        ),
        cleanup_steps=[
            ScenarioStep(
                step_id="cleanup",
                name="清理退票单",
                action="cleanup",
                params={"refund_id": "sensitive-refund-id"},
            )
        ],
    )
    summary = settings.write_case_fixture_binding(SYSTEM_ID, ENTRY_ID, update)
    summaries = settings.list_case_fixture_bindings(SYSTEM_ID, ENTRY_ID)
    path = tmp_path / "environments" / SYSTEM_ID / "qa.yaml"

    assert summary.ready
    assert summaries == [summary]
    assert "sensitive" not in summary.model_dump_json()
    assert "sensitive-refund-id" in path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_long_entry_fixture_keys_preserve_distinct_test_point_identity(tmp_path: Path) -> None:
    """长入口截断时仍应为不同测试点生成不同运行键并分别保存。

    Args:
        tmp_path: pytest隔离的本地QA配置根。

    Returns:
        None；两个共享超长入口前缀的测试点具有不同运行键时通过。
    """

    settings = LocalSystemSettingsStore(tmp_path / "environments")
    long_entry_id = f"facade:{'a' * 493}"
    for test_point_id in ("matrix:long-entry:success", "matrix:long-entry:validator"):
        settings.write_case_fixture_binding(
            SYSTEM_ID,
            long_entry_id,
            CaseFixtureBindingUpdate(
                test_point_id=test_point_id,
                arguments={"id": test_point_id},
                response_assertions={},
            ),
        )

    bindings = settings.case_fixture_bindings(SYSTEM_ID, long_entry_id)
    runtime_keys = {runtime_key for _entry_id, runtime_key, _binding in bindings}

    assert len(bindings) == 2
    assert len(runtime_keys) == 2
    assert all(len(runtime_key) <= 400 for runtime_key in runtime_keys)


def test_completed_agent_candidate_requires_node_test_points(tmp_path: Path) -> None:
    """当前Agent完成候选不得借用历史空测试点投影进入发布流程。

    Args:
        tmp_path: pytest隔离的完整知识根。

    Returns:
        None；没有结构化测试点的完成候选被业务门禁拒绝时通过。
    """

    _service, _case_store, store = _case_service(tmp_path)
    application = OpenTestApplication(store.root)
    candidate = AgentKnowledgeEnvelope.model_validate(
        {
            "status": "completed",
            "system_id": SYSTEM_ID,
            "target_ids": [ENTRY_ID],
            "summaries": [{"node_id": ENTRY_NODE_ID, "summary": "取消退票入口"}],
            "questions": [],
            "source_refs": [],
            "trace_steps": [],
        }
    )
    try:
        with pytest.raises(KnowledgeValidationError, match="required node test points"):
            application.knowledge._require_agent_test_points(candidate)
    finally:
        application.close()


def test_case_catalog_and_batch_execution_use_latest_entry_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """目录应按已发布入口显示最新Case，显式确认后只执行就绪变体并汇总阻塞。

    Args:
        tmp_path: pytest隔离的完整OpenTest根。
        monkeypatch: 把真实QA执行器替换为独立Run记录桩。

    Returns:
        None；目录计数、就绪执行和阻塞汇总都与最新生成一致时通过。
    """

    service, _case_store, store = _case_service(tmp_path)
    first = service.create_case_generation(
        SYSTEM_ID,
        CaseGenerationCreateRequest(entry_node_id=ENTRY_ID),
    )
    ready_item = first.matrix_items[0]
    binding = CaseFixtureBindingUpdate(
        test_point_id=ready_item.matrix_item_id,
        arguments={"refund_id": "local-only"},
        response_assertions={"$.code": 0},
        oracle=OracleRequest(
            oracle_id="oracle-ready-cancel",
            system_id=SYSTEM_ID,
            kind="mysql",
            resource_id="mysql:refund",
            operation_id="refund.detail",
            assertions={"$.status": "REFUND_CANCEL"},
        ),
        cleanup_steps=[
            ScenarioStep(
                step_id="cleanup-ready",
                name="清理就绪退票单",
                action="cleanup",
                params={"refund_id": "local-only"},
            )
        ],
    )
    service.bind_fixture_provider(
        lambda _system_id, _entry_id: [(ENTRY_ID, "cancel_ready", binding)]
    )
    generation = service.create_case_generation(
        SYSTEM_ID,
        CaseGenerationCreateRequest(entry_node_id=ENTRY_ID),
    )
    application = OpenTestApplication(store.root)
    executed_variant_ids: list[str] = []

    def execute_case(request) -> RunRecord:
        """记录就绪变体并返回独立通过Run。

        Args:
            request: 批量执行转换的单变体请求。

        Returns:
            与变体和Snapshot绑定的通过记录。

        Side Effects:
            向测试内存追加实际执行的变体ID。
        """

        executed_variant_ids.append(request.variant_id)
        return RunRecord(
            run_id=f"run-{len(executed_variant_ids)}",
            system_id=request.system_id,
            variant_id=request.variant_id,
            status="passed",
            snapshot_id=request.snapshot_id,
            step_results=[],
            started_at=utc_now(),
            ended_at=utc_now(),
        )

    monkeypatch.setattr(application.execution, "execute", execute_case)
    monkeypatch.setattr(
        application.snapshots,
        "get",
        lambda snapshot_id: Snapshot(
            snapshot_id=snapshot_id,
            system_id=SYSTEM_ID,
            source_baseline=SourceBaseline(source_path=str(tmp_path / "source")),
        ),
    )
    try:
        catalog = application.get_case_catalog(SYSTEM_ID)
        assert [entry.entry_id for entry in catalog["knowledge_entries"]] == [ENTRY_ID]
        assert catalog["knowledge_entries"][0].case_count == 4
        assert catalog["knowledge_entries"][0].ready_count == 1
        assert catalog["knowledge_entries"][0].blocked_count == 3

        task = application.submit_case_generation_execution(
            SYSTEM_ID,
            generation.generation_id,
            CaseGenerationExecutionRequest(snapshot_id="snapshot-case-current", confirmed=True),
        )
        for _ in range(200):
            completed = application.get_task(task.task_id)
            if completed.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                break
            time.sleep(0.01)
        result = application.get_task(task.task_id).result

        assert len(executed_variant_ids) == 1
        assert result["passed_count"] == 1
        assert result["failed_count"] == 0
        assert result["blocked_count"] == 3
        assert len(result["run_ids"]) == 1
    finally:
        application.close()
