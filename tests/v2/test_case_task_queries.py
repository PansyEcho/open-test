"""验证Case任务页按本人及固定业务范围先过滤，再分页。"""

from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime, timedelta, timezone

from opentest.application import foundation
from opentest.application.console_queries import ConsoleQueries, TaskListQuery
from opentest.domain.models import TaskProgress, TaskRecord, TaskStatus


def test_case_task_query_filters_scope_before_pagination(monkeypatch):
    """其他入口、基准、环境和员工的任务不得占用当前入口的分页位置。"""

    metadata = Mock()
    metadata.fetch_one.return_value = {"entries": None}
    monkeypatch.setattr("opentest.application.console_queries.current_identity",
                        lambda: SimpleNamespace(employee=SimpleNamespace(user_id="employee-a")))
    queries = ConsoleQueries(SimpleNamespace(store=SimpleNamespace(metadata=metadata)))
    response = queries.tasks(TaskListQuery(system_id="system-a", operation="case-generation",
        target_id="facade:Refund#cancel", baseline_id="baseline-a", environment_id="qa", page=2))
    sql, parameters = metadata.fetch_one.call_args.args
    # SQL使用参数绑定，业务范围进入WHERE而非读取完一页后再过滤。
    assert "owner_user_id=%s" in sql
    assert "payload_json->>'$.result.baseline_id'=%s" in sql
    assert "payload_json->>'$.result.environment_id'=%s" in sql
    assert parameters == ["employee-a", "system-a", "case-generation", "facade:Refund#cancel",
                          "baseline-a", "qa", 21, 20]
    assert response["tasks"] == []


def test_latest_case_task_query_orders_full_scope_before_limit(monkeypatch):
    """验证活动排序在员工过滤之后、分页之前，且只请求一条摘要。

    Args:
        monkeypatch: 绑定员工身份，使断言覆盖查询的授权范围和排序位置。
    """

    metadata = Mock()
    metadata.fetch_one.return_value = {"entries": None}
    monkeypatch.setattr("opentest.application.console_queries.current_identity",
                        lambda: SimpleNamespace(employee=SimpleNamespace(user_id="employee-a")))
    queries = ConsoleQueries(SimpleNamespace(store=SimpleNamespace(metadata=metadata)))
    queries.tasks(TaskListQuery(system_id="system-a", operation="case-generation",
        target_id="facade:Refund#cancel", baseline_id="baseline-a", environment_id="qa",
        order_by="activity", page_size=1))
    sql, parameters = metadata.fetch_one.call_args.args
    # 继续运行保留首次启动时间，因此必须包含进度时间，并在分页前由数据库决定第一项。
    assert "ORDER BY GREATEST(created_at," in sql
    assert "$.progress.updated_at" in sql and "$.client_handoff.updated_at" in sql
    assert sql.index("owner_user_id=%s") < sql.index("ORDER BY GREATEST") < sql.index("LIMIT %s")
    assert parameters[-2:] == [2, 0]


def test_latest_case_task_includes_resumed_history_beyond_first_page(tmp_path, monkeypatch):
    """真实隔离MySQL里，旧任务的新进度可超过首屏25条，同时不跨员工或业务范围。

    Args:
        tmp_path: 供既有fixture创建随机数据库，所有测试行在结束时自动清理。
        monkeypatch: 为读取绑定员工身份，验证其他员工不会占用唯一展示位置。
    """

    metadata = foundation.load_metadata_store(tmp_path / "knowledge")
    created = datetime(2026, 10, 20, tzinfo=timezone.utc)
    base = dict(system_id="system-a", operation="case-generation", target_id="facade:Refund#cancel",
                trace_id="latest-case-test", owner_user_id="employee-a",
                result={"baseline_id": "baseline-a", "environment_id": "qa"})
    # 同一范围造25条较新的创建记录，使恢复任务确定落在创建分页之外。
    for index in range(25):
        task = TaskRecord(**base, task_id=f"task-{index:016x}", status=TaskStatus.COMPLETED,
                          created_at=created + timedelta(minutes=index), ended_at=created + timedelta(minutes=index + 1))
        metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    resumed = TaskRecord(**base, task_id="task-ffffffffffffffff", status=TaskStatus.RUNNING,
        created_at=created - timedelta(days=1), started_at=created - timedelta(days=1),
        progress=TaskProgress(task_id="task-ffffffffffffffff", operation="case-generation",
                              status=TaskStatus.RUNNING, updated_at=created + timedelta(days=1, microseconds=123456)))
    metadata.put_workflow("task", resumed.task_id, resumed.model_dump(mode="json"))
    # 其他员工、系统、入口、基准或环境虽然活动更晚，也不能抢占选中范围的唯一位置。
    for index, override in enumerate(({"owner_user_id": "employee-b"}, {"system_id": "system-b"},
        {"target_id": "facade:Refund#query"}, {"result": {**base["result"], "baseline_id": "baseline-b"}},
        {"result": {**base["result"], "environment_id": "uat"}})):
        task = TaskRecord(**{**base, **override}, task_id=f"task-eeeeeeeeeeeeeee{index}",
            status=TaskStatus.COMPLETED, created_at=created + timedelta(days=2), ended_at=created + timedelta(days=2))
        metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    monkeypatch.setattr("opentest.application.console_queries.current_identity",
                        lambda: SimpleNamespace(employee=SimpleNamespace(user_id="employee-a")))
    queries = ConsoleQueries(SimpleNamespace(store=SimpleNamespace(metadata=metadata)))
    scope = dict(system_id="system-a", operation="case-generation", target_id="facade:Refund#cancel",
                 baseline_id="baseline-a", environment_id="qa")
    first_created_page = queries.tasks(TaskListQuery(**scope))
    latest_activity = queries.tasks(TaskListQuery(**scope, order_by="activity", page_size=1))
    assert resumed.task_id not in [item["task_id"] for item in first_created_page["tasks"]]
    assert [item["task_id"] for item in latest_activity["tasks"]] == [resumed.task_id]
    # 最近一次视图是查询投影，历史数据和任务中心默认创建排序不变。
    assert first_created_page["tasks"][0]["task_id"] == "task-0000000000000018"
    assert len(queries.tasks(TaskListQuery(**scope, page_size=100))["tasks"]) == 26
