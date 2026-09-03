"""验证 Codex 客户端接管任务的终态归档契约。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from opentest.application.tasks import LocalTaskManager
from opentest.domain.models import (
    KnowledgeClientHandoff,
    KnowledgeClientHandoffStatus,
    TaskRecord,
    TaskStatus,
    utc_now,
)


SYSTEM_ID = "refund-core"
ENTRY_ID = "facade:demo.RefundFacade#cancel"


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
