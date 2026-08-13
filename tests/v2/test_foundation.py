"""验证V2领域、日志、任务、Git知识和SQLite派生索引的基础闭环。"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.application.foundation import OpenTestApplication
from opentest.application.log_context import bind_workflow_log_context, current_log_context
from opentest.application.tasks import LocalTaskManager
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    KnowledgeEdge,
    KnowledgeEdgeKind,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeStatus,
    SourceReference,
    SystemDefinition,
    TaskRecord,
    TaskStatus,
)


def _registered_store(tmp_path: Path) -> tuple[GitKnowledgeStore, Path]:
    """创建带一个真实源码目录和已注册系统的测试知识仓库。"""

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    return store, source


def _write_sample_graph(store: GitKnowledgeStore) -> tuple[KnowledgeNode, KnowledgeNode]:
    """写入createOrder入口、港币规则以及二者之间的调用关系。"""

    facade = KnowledgeNode(
        node_id="facade:TradeFacade#createOrder",
        system_id="train-booking-core",
        kind=KnowledgeNodeKind.FACADE,
        title="创建订单",
        summary="创建火车票订单的DSF入口",
        aliases=["createOrder"],
        source_refs=[
            SourceReference(
                path="app/api/TradeFacade.java",
                symbol="TradeFacade#createOrder",
                line=42,
            )
        ],
        status=KnowledgeStatus.CODE_VERIFIED,
        confidence=1,
    )
    rule = KnowledgeNode(
        node_id="rule:hk-payment",
        system_id="train-booking-core",
        kind=KnowledgeNodeKind.BUSINESS_RULE,
        title="港币支付校验",
        summary="港币支付订单要求外币价格完整",
        aliases=["港币订单"],
        status=KnowledgeStatus.USER_CONFIRMED,
        confidence=1,
    )
    store.write_node(facade, "## 流程\n\n校验乘客后创建订单。")
    store.write_node(rule, "## 规则\n\n创建港币支付订单时校验每名乘客的外币票价。")
    store.write_edges(
        "train-booking-core",
        [
            KnowledgeEdge(
                edge_id="edge:create-order-hk-payment",
                system_id="train-booking-core",
                source_node_id=facade.node_id,
                target_node_id=rule.node_id,
                kind=KnowledgeEdgeKind.DEPENDS_ON,
            )
        ],
    )
    return facade, rule


def test_strict_models_reject_unknown_fields(tmp_path: Path) -> None:
    """领域模型应拒绝未知字段并规范化源码绝对路径。"""

    source = tmp_path / "source"
    source.mkdir()
    system = SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source))
    assert system.source_path == str(source.resolve())

    with pytest.raises(ValidationError):
        SystemDefinition.model_validate(
            {
                "system_id": "train-booking-core",
                "name": "火车票预订",
                "source_path": str(source),
                "unexpected": True,
            }
        )


def test_log_context_is_restored_after_exception() -> None:
    """工作流异常退出后不得向复用线程泄漏trace和过滤字段。"""

    with bind_workflow_log_context("outer-system", "outer-task", "outer-trace"):
        with pytest.raises(RuntimeError):
            with bind_workflow_log_context("train-booking-core", "task-1", "trace-1"):
                context = current_log_context()
                assert context.filter1 == "train-booking-core"
                assert context.filter2 == "task-1"
                raise RuntimeError("expected")

        restored = current_log_context()
        assert restored.trace_id == "outer-trace"
        assert restored.filter1 == "outer-system"
        assert restored.filter2 == "outer-task"

    assert current_log_context().trace_id == ""
    assert current_log_context().filter1 == ""
    assert current_log_context().filter2 == ""


def test_task_manager_persists_success_failure_and_restart(tmp_path: Path) -> None:
    """任务管理器应记录成功、失败，并在重启时终止遗留running任务。"""

    task_root = tmp_path / "tasks"
    manager = LocalTaskManager(task_root, max_workers=1)

    def successful_job() -> dict[str, object]:
        """返回线程内观察到的日志上下文用于验证任务绑定。"""

        context = current_log_context()
        return {"ok": True, "filter1": context.filter1, "filter2": context.filter2}

    def failed_job() -> dict[str, object]:
        """模拟业务失败以验证失败边界能够落盘。"""

        raise RuntimeError("boom")

    successful = manager.submit("scan", "train-booking-core", successful_job)
    failed = manager.submit("scan", "train-booking-core", failed_job)
    manager.close()

    completed_record = manager.get(successful.task_id)
    failed_record = manager.get(failed.task_id)
    assert completed_record.status == TaskStatus.COMPLETED
    assert completed_record.ended_at is not None
    assert completed_record.result["filter1"] == "train-booking-core"
    assert completed_record.result["filter2"] == successful.task_id
    assert failed_record.status == TaskStatus.FAILED
    assert failed_record.ended_at is not None
    assert failed_record.error == "RuntimeError: boom"

    orphan = TaskRecord(task_id="task-orphaned", operation="scan", system_id="train-booking-core", trace_id="trace")
    (task_root / "task-orphaned.json").write_text(orphan.model_dump_json(indent=2), encoding="utf-8")
    restarted = LocalTaskManager(task_root, max_workers=1)
    interrupted = restarted.get(orphan.task_id)
    restarted.close()
    assert interrupted.status == TaskStatus.INTERRUPTED
    assert interrupted.ended_at is not None


def test_second_task_manager_does_not_interrupt_live_owner(tmp_path: Path) -> None:
    """共享目录中的第二个API或CLI实例不得把活进程任务误标为interrupted。"""

    task_root = tmp_path / "tasks"
    started = threading.Event()
    release = threading.Event()
    first = LocalTaskManager(task_root, max_workers=1)

    def blocking_job() -> dict[str, object]:
        """保持任务处于running，直到测试完成第二实例恢复检查。"""

        started.set()
        release.wait(timeout=5)
        return {"released": True}

    task = first.submit("scan", "train-booking-core", blocking_job)
    assert started.wait(timeout=2)
    second = LocalTaskManager(task_root, max_workers=1)
    try:
        assert second.get(task.task_id).status == TaskStatus.RUNNING
    finally:
        release.set()
        first.close()
        second.close()

    assert first.get(task.task_id).status == TaskStatus.COMPLETED


def test_store_supports_second_system_and_preserves_manual_markdown(tmp_path: Path) -> None:
    """存储应隔离注册第二系统，并在自动更新时保留人工补充内容。"""

    store, _ = _registered_store(tmp_path)
    second_source = tmp_path / "second-source"
    second_source.mkdir()
    second = store.register_system(
        SystemDefinition(system_id="settlement-core", name="结算", source_path=str(second_source))
    )
    assert [item.system_id for item in store.list_systems()] == ["settlement-core", "train-booking-core"]
    assert second.source_path == str(second_source.resolve())

    facade, _ = _write_sample_graph(store)
    path = store.node_path(facade)
    original = path.read_text(encoding="utf-8")
    path.write_text(f"{original.rstrip()}\n\n人工确认：儿童乘客必须携带证件。\n", encoding="utf-8")
    store.write_node(facade, "## 流程\n\n更新后的自动流程。")

    updated = path.read_text(encoding="utf-8")
    assert "更新后的自动流程" in updated
    assert "校验乘客后创建订单" not in updated
    assert "人工确认：儿童乘客必须携带证件" in updated
    assert updated.count("<!-- kb:auto-start -->") == 1


def test_store_reads_manual_multi_system_registry_and_indexes_each_scope(tmp_path: Path) -> None:
    """人工加入合法第二系统时，读取和索引应保持每个系统独立范围。"""

    store, source = _registered_store(tmp_path)
    second_source = tmp_path / "second-source"
    second_source.mkdir()
    registry_payload = {
        "systems": [
            SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)).model_dump(mode="json"),
            SystemDefinition(system_id="settlement-core", name="结算", source_path=str(second_source)).model_dump(mode="json"),
        ]
    }
    store.registry_path.write_text(json.dumps(registry_payload, ensure_ascii=False), encoding="utf-8")

    systems = store.list_systems()
    counts = SqliteKnowledgeIndex(store.root / ".opentest" / "index.sqlite").rebuild(store)

    assert [item.system_id for item in systems] == ["settlement-core", "train-booking-core"]
    assert counts["systems"] == 2


def test_node_paths_are_collision_safe_and_legacy_body_is_preserved(tmp_path: Path) -> None:
    """有损slug不能覆盖其他节点，无标记旧正文应全部作为人工内容迁移保留。"""

    store, _ = _registered_store(tmp_path)
    first = KnowledgeNode(
        node_id="rule:a:b",
        system_id="train-booking-core",
        kind=KnowledgeNodeKind.BUSINESS_RULE,
        title="规则A",
    )
    second = KnowledgeNode(
        node_id="rule:a-b",
        system_id="train-booking-core",
        kind=KnowledgeNodeKind.BUSINESS_RULE,
        title="规则B",
    )
    assert store.node_path(first) != store.node_path(second)

    path = store.write_node(first, "第一版自动规则")
    metadata_text = path.read_text(encoding="utf-8").split("---", 2)[1]
    path.write_text(f"---{metadata_text}---\n\n这是旧版人工正文，不包含自动标记。\n", encoding="utf-8")
    store.write_node(first, "第二版自动规则")
    updated = path.read_text(encoding="utf-8")
    assert "第二版自动规则" in updated
    assert "这是旧版人工正文" in updated


@pytest.mark.parametrize(
    "broken_body",
    [
        "<!-- kb:auto-start -->\n缺少结束标记",
        "<!-- kb:auto-end -->\n结束标记在前\n<!-- kb:auto-start -->",
        "<!-- kb:auto-start -->\n<!-- kb:auto-end -->\n<!-- kb:auto-start -->\n<!-- kb:auto-end -->",
    ],
)
def test_store_rejects_ambiguous_auto_region_markers(tmp_path: Path, broken_body: str) -> None:
    """损坏、逆序或重复自动标记必须中止更新，避免误删无法判定的人工正文。"""

    store, _ = _registered_store(tmp_path)
    node = KnowledgeNode(
        node_id="rule:broken-markers",
        system_id="train-booking-core",
        kind=KnowledgeNodeKind.BUSINESS_RULE,
        title="损坏标记规则",
    )
    path = store.write_node(node, "初始自动内容")
    metadata_text = path.read_text(encoding="utf-8").split("---", 2)[1]
    broken_document = f"---{metadata_text}---\n\n{broken_body}\n人工内容"
    path.write_text(broken_document, encoding="utf-8")

    with pytest.raises(KnowledgeValidationError, match="auto-region"):
        store.write_node(node, "不得写入的新内容")
    assert path.read_text(encoding="utf-8") == broken_document


def test_sqlite_index_is_deletable_rebuildable_and_searchable(tmp_path: Path) -> None:
    """删除SQLite后应可完整重建，并支持符号、中文和关系检索。"""

    store, _ = _registered_store(tmp_path)
    facade, rule = _write_sample_graph(store)
    database_path = store.root / ".opentest" / "index.sqlite"
    index = SqliteKnowledgeIndex(database_path)

    first_counts = index.rebuild(store)
    assert first_counts == {"systems": 1, "nodes": 2, "edges": 1, "aliases": 2, "source_refs": 1}
    assert index.search("createOrder")[0]["node_id"] == facade.node_id
    assert index.search("TradeFacade#createOrder")[0]["node_id"] == facade.node_id
    assert index.search("TradeFacade#createOrder")[0]["match_type"] == "exact"
    assert index.search("港币支付")[0]["node_id"] == rule.node_id
    assert index.related(facade.node_id)[0]["target_node_id"] == rule.node_id

    database_path.unlink()
    with pytest.raises(KnowledgeNotFoundError):
        index.related(facade.node_id)
    second_counts = index.rebuild(store)
    assert second_counts == first_counts
    assert index.search("港币订单")[0]["match_type"] == "exact"


def test_concurrent_index_rebuilds_use_independent_temporary_files(tmp_path: Path) -> None:
    """同一应用实例的并发重建不能相互删除临时库，最终索引仍应完整可查。"""

    store, _ = _registered_store(tmp_path)
    facade, _ = _write_sample_graph(store)
    index = SqliteKnowledgeIndex(store.root / ".opentest" / "index.sqlite")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(index.rebuild, store) for _ in range(2)]
        counts = [future.result() for future in futures]

    assert counts[0] == counts[1]
    assert index.search("createOrder")[0]["node_id"] == facade.node_id
    assert not list(index.database_path.parent.glob("*.building"))


def test_application_falls_back_to_git_exact_search_without_sqlite(tmp_path: Path) -> None:
    """派生索引缺失时应用服务仍应从Git文件精确查找ID、别名和源码符号。"""

    store, _ = _registered_store(tmp_path)
    facade, _ = _write_sample_graph(store)
    application = OpenTestApplication(store.root)
    try:
        matches = application.search_knowledge("TradeFacade#createOrder", "train-booking-core")
    finally:
        application.close()

    assert matches[0]["node_id"] == facade.node_id
    assert matches[0]["match_type"] == "git_exact"


def test_background_rebuild_preserves_task_id_log_context(tmp_path: Path) -> None:
    """后台索引工作流应沿用任务ID作为filter2，而不是被内部固定操作名覆盖。"""

    store, _ = _registered_store(tmp_path)
    application = OpenTestApplication(store.root)
    observed_filter2: list[str] = []

    def record_context(_: GitKnowledgeStore) -> dict[str, int]:
        """记录索引适配器被调用时的filter2并返回空索引计数。"""

        observed_filter2.append(current_log_context().filter2)
        return {"systems": 1, "nodes": 0, "edges": 0, "aliases": 0, "source_refs": 0}

    application.index.rebuild = record_context  # type: ignore[method-assign]
    task = application.submit_index_rebuild("train-booking-core")
    application.close()

    assert application.get_task(task.task_id).status == TaskStatus.COMPLETED
    assert observed_filter2 == [task.task_id]
