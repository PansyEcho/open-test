"""验证进度合并和真实生命周期，不依赖数据库或调用业务。"""

from datetime import timedelta

from opentest.application.tasks import LocalTaskManager, TaskProgressReporter
from opentest.domain.models import TaskProgressUpdate, TaskRecord, TaskStatus, utc_now


def test_reporter_preserves_concurrent_result_and_terminal(tmp_path):
    """旧报告器只合并进度，不能擦除新结果或把完成任务重新写成运行中。"""
    manager = LocalTaskManager(tmp_path)
    record = TaskRecord(task_id="task-1234567890abcdef", operation="case-generation",
                        trace_id="progress-test", status=TaskStatus.RUNNING)
    manager._write(record)
    reporter = TaskProgressReporter(manager, record)
    # 业务写入发生在报告器创建之后，模拟执行线程与草稿写入并发。
    manager._write(record.model_copy(update={"result": {"generation_id": "fixed-generation"}}))
    update = TaskProgressUpdate(stage_code="verify", stage_name="逐项验证", stage_index=1,
                                completed_units=3, total_units=10)
    reporter.update(update)
    assert manager.get(record.task_id).result == {"generation_id": "fixed-generation"}
    reporter.update(update.model_copy(update={"completed_units": 1}))
    assert manager.get(record.task_id).progress.completed_units == 3
    complete = manager.get(record.task_id).model_copy(update={"status": TaskStatus.COMPLETED, "ended_at": utc_now()})
    manager.save_business_record(complete)
    reporter.update(update.model_copy(update={"completed_units": 4}))
    assert manager.get(record.task_id).status == TaskStatus.COMPLETED
    manager.close()


def test_business_projection_preserves_counts_and_first_end(tmp_path):
    """任务状态重复同步保留细进度和第一次结束；等待状态不要求或展示结束时间。"""
    manager = LocalTaskManager(tmp_path)
    record = TaskRecord(task_id="task-abcdef1234567890", operation="case-generation",
                        trace_id="progress-test", status=TaskStatus.RUNNING)
    manager._write(record)
    TaskProgressReporter(manager, record).update(TaskProgressUpdate(
        stage_code="verify", stage_name="验证", stage_index=1, completed_units=2, total_units=5))
    manager.save_business_record(record)
    assert manager.get(record.task_id).progress.completed_units == 2
    end = utc_now()
    manager.save_business_record(manager.get(record.task_id).model_copy(update={
        "status": TaskStatus.COMPLETED, "ended_at": end}))
    manager.save_business_record(manager.get(record.task_id).model_copy(update={"ended_at": end + timedelta(seconds=20)}))
    assert manager.get(record.task_id).ended_at == end
    # 旧记录可能有等待结束时间；新投影清除它，但仍能兼容读取旧格式。
    waiting = manager.get(record.task_id).model_copy(update={"status": TaskStatus.WAITING_FOR_CLIENT})
    assert manager.save_business_record(waiting).ended_at is None
    manager.close()
