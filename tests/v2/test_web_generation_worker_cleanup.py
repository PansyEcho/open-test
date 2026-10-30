"""独立验证网页worker首次持久化失败的退出边界，不组装MySQL或调用模型。"""

from types import SimpleNamespace
from unittest.mock import Mock

from opentest.application.tasks import LocalTaskManager
from opentest.application.web_generation import WebGenerationService
from opentest.domain.models import TaskRecord, TaskStatus


def test_initial_started_at_save_failure_settles_and_releases_worker(tmp_path, monkeypatch):
    """tmp_path隔离真实任务和门禁；首次保存故障后状态明确、模型未启动且本机占用释放。"""

    manager = LocalTaskManager(tmp_path / "tasks")
    task = TaskRecord(task_id="task-1234567890abcdef", system_id="test-system", operation="case-generation",
        trace_id="worker-start-failure", status=TaskStatus.RUNNING, web_run_active=True,
        web_run_id="agent-1234567890abcdef", interaction_mode="web")
    application = SimpleNamespace(tasks=manager, agent_runner=Mock(), knowledge_root=tmp_path,
        runtime_settings=Mock(), get_task_context=Mock(return_value={}), coverage_assistance=Mock())
    service = WebGenerationService(application)
    manager._write(task)
    manager._reserve_exclusive(task)
    service._observing.add(task.task_id)
    original_save = manager.save_business_record
    save_attempts = 0

    def fail_first_save(record):
        """只拒绝worker首次开始时间写入，随后使用真实存储验证现有异常收尾，不重试模型。"""

        nonlocal save_attempts
        save_attempts += 1
        if save_attempts == 1:
            raise RuntimeError("initial started_at save failed")
        return original_save(record)

    monkeypatch.setattr(manager, "save_business_record", fail_first_save)
    try:
        service._run_owned(task, False)
        stored = manager.get(task.task_id)
        assert stored.status == TaskStatus.FAILED and not stored.web_run_active
        assert "initial started_at save failed" in stored.error
        assert stored.ended_at is not None
        application.agent_runner.run.assert_not_called()
        application.agent_runner.attach.assert_not_called()
        application.runtime_settings.read.assert_not_called()
        assert task.task_id not in service._observing
        assert task.task_id not in manager._exclusive_handles
        # 真实POSIX门禁也必须释放，不能仅从内存集合移除任务造成虚假的空闲。
        other = task.model_copy(update={"task_id": "task-fedcba0987654321"})
        manager._reserve_exclusive(other)
        manager._release_exclusive(other.task_id)
    finally:
        manager.close()
