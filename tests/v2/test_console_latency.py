"""验证性能改造保留事务、跨工作台一致性与完整详情边界。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from opentest.application.console_queries import ConsoleQueries, TaskListQuery
from opentest.application.console_read_cache import ConsoleReadCache
from opentest.application.knowledge_discovery import KnowledgeDiscoveryService
from opentest.domain.models import KnowledgeContextProfile, TaskRecord, TaskStatus, utc_now
from tests.v2.test_mysql_workspace_integration import workspace


def test_pooled_reads_bound_connections_and_transactions_release_named_locks(workspace):
    """八个并发读只使用四条连接；显式事务隔离于读池，提交和回滚均释放命名锁。"""

    identity, first, second = workspace
    barrier = Barrier(8)

    def read_connection(index):
        """同时租用读会话并短暂持有，使测试实际观察并发上限。"""

        barrier.wait()
        return first.metadata.fetch_one("SELECT CONNECTION_ID() AS id,@@transaction_read_only AS readonly,SLEEP(0.05)")

    with ThreadPoolExecutor(max_workers=8) as workers:
        rows = list(workers.map(read_connection, range(8)))
    assert len({row["id"] for row in rows}) <= 4
    assert all(row["readonly"] == 1 for row in rows)
    assert first.metadata._read_pool.checkedout() == 0
    for fail in (False, True):
        try:
            with first.metadata.transaction():
                acquired = first.metadata.fetch_one("SELECT GET_LOCK(%s,0) AS acquired,@@transaction_read_only AS readonly", (identity,))
                assert acquired == {"acquired": 1, "readonly": 0}
                assert second.metadata.fetch_one("SELECT IS_FREE_LOCK(%s) AS free", (identity,))["free"] == 0
                if fail:
                    raise RuntimeError("rollback probe")
        except RuntimeError:
            assert fail
        assert second.metadata.fetch_one("SELECT IS_FREE_LOCK(%s) AS free", (identity,))["free"] == 1
    first.metadata.close()
    second.metadata.close()


def test_shared_task_summary_filters_pages_and_keeps_full_result(workspace):
    """真实MySQL分页没有重叠，历史失败按partial过滤，列表不下载大型结果，详情保留正文。"""

    identity, store, _ = workspace
    records = []
    with store.metadata.transaction():
        for index in range(23):
            task = TaskRecord(task_id=f"task-{index:016x}", system_id=identity, trace_id=identity,
                operation="knowledge-target-generation", target_id="entry:test", status=TaskStatus.COMPLETED,
                ended_at=utc_now(), result={"body": "大正文" * 10000, "outcomes": [{"status": "CODE_ONLY", "safe_error": "probe"}]})
            # UUID系统隔离；复合工作流主键中任务ID也必须与其他测试独立。
            task = task.model_copy(update={"task_id": "task-" + identity[-12:] + f"{index:04x}"})
            store.metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
            records.append(task)
    queries = ConsoleQueries(SimpleNamespace(store=store))
    first = queries.tasks(TaskListQuery(system_id=identity, view="summary", status=[TaskStatus.PARTIAL]))
    second = queries.tasks(TaskListQuery(system_id=identity, view="summary", status=[TaskStatus.PARTIAL], page=2))
    assert len(first["tasks"]) == 20 and first["pagination"]["has_more"]
    assert len(second["tasks"]) == 3 and not second["pagination"]["has_more"]
    assert not {item["task_id"] for item in first["tasks"]}.intersection(item["task_id"] for item in second["tasks"])
    assert all(item["status"] == "partial" and "body" not in item["result"] for item in first["tasks"])
    assert queries.tasks(TaskListQuery(system_id=identity, view="summary", status=[TaskStatus.COMPLETED]))["tasks"] == []
    assert store.metadata.get_workflow("task", records[0].task_id)["result"]["body"] == "大正文" * 10000
    assert len(json.dumps(first)) < 50000


def test_background_get_is_pure_read():
    """普通GET不能取得写锁、规范化枚举或读取扫描包。"""

    store = Mock()
    store.read_context.return_value = KnowledgeContextProfile(system_id="pure-read")
    service = KnowledgeDiscoveryService.__new__(KnowledgeDiscoveryService)
    service.store = store
    service.normalize_context = Mock(side_effect=AssertionError("GET must not migrate"))
    assert service.get_context("pure-read").system_id == "pure-read"
    store.system_transaction.assert_not_called()
    store.write_context.assert_not_called()


def test_projection_single_flight_preserves_model_and_remote_invalidation(tmp_path):
    """同版本并发未命中只构建一次，保留领域模型；跨工作台revision改变后重建。"""

    metadata = Mock()
    metadata._local = local()
    rows = [{"system_id": "cache-test", "latest_scan_id": "scan-a", "workspace_revision": 1, "is_archived": 0}]
    metadata.fetch_all.return_value = rows
    cache = ConsoleReadCache(metadata, tmp_path)
    entered, release = Event(), Event()
    builds = []

    @cache.cached
    def context(system_id):
        """模拟耗时投影，使第二个读者在同一版本构建期间到达。"""

        builds.append(system_id)
        entered.set()
        assert release.wait(2)
        return KnowledgeContextProfile(system_id=system_id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(context, "cache-test")
        assert entered.wait(2)
        second = workers.submit(context, "cache-test")
        release.set()
        assert isinstance(first.result(), KnowledgeContextProfile)
        assert isinstance(second.result(), KnowledgeContextProfile)
    assert builds == ["cache-test"] and cache._builds == {}
    rows[0]["workspace_revision"] += 1
    context("cache-test")
    assert builds == ["cache-test", "cache-test"]


def test_web_recovery_queries_only_owned_active_tasks(workspace):
    """周期维护只读本workspace活动任务；历史和他机任务不传输也不尝试接管。"""

    from opentest.application.mysql_tasks import MySqlTaskManager

    identity, local_store, remote_store = workspace
    expected = "task-" + identity[-12:] + "aaaa"
    for suffix, store, active in (("aaaa", local_store, True), ("bbbb", local_store, False), ("cccc", remote_store, True)):
        task = TaskRecord(task_id="task-" + identity[-12:] + suffix, system_id=identity, trace_id=identity,
                          operation="recovery-probe", status=TaskStatus.RUNNING, web_run_active=active,
                          owner_workspace_id=store.metadata.workspace_id)
        store.metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    # 只使用无副作用的查询方法，避免测试为了验证筛选而真的启动进程恢复。
    manager = MySqlTaskManager.__new__(MySqlTaskManager)
    manager.metadata = local_store.metadata
    assert [task.task_id for task in manager.web_recovery_records()] == [expected]


def test_mysql_json_transport_is_lossless(workspace):
    """MySQL实际压缩的中文、空值和长正文可无损还原，损坏包必须报错。"""

    from opentest.adapters.mysql_metadata import decode_mysql_compressed_json
    from opentest.domain.errors import KnowledgeValidationError

    _, store, _ = workspace
    payload = {"body": "生产基线与测试差异" * 10000, "unknown": None, "required": False, "fields": [1, "", {}]}
    row = store.metadata.fetch_one("SELECT COMPRESS(%s) AS payload", (json.dumps(payload, ensure_ascii=False),))
    assert decode_mysql_compressed_json(row["payload"]) == payload
    assert len(row["payload"]) < len(json.dumps(payload).encode()) / 10
    with pytest.raises(KnowledgeValidationError):
        decode_mysql_compressed_json(b"bad-packet")


def test_async_submission_returns_while_job_is_running(workspace, tmp_path, monkeypatch):
    """真实MySQL任务提交和状态HTTP不等待工作线程结束；受控worker不修改扫描或业务数据。"""

    from time import perf_counter
    from fastapi.testclient import TestClient
    from opentest.api import create_app
    from opentest.application.foundation import OpenTestApplication
    from opentest.application.mysql_tasks import MySqlTaskManager

    identity, store, _ = workspace
    application = OpenTestApplication(tmp_path / "probe-application")
    application.tasks.close()
    application.tasks = MySqlTaskManager(tmp_path / "probe-tasks", store.metadata)
    application.store = store
    release = Event()

    def controlled_job(system_id):
        """保持工作线程在运行态，直到测试完成读取；超时作为失败而非虚构成功。"""

        assert system_id == identity
        assert release.wait(10)
        return {"probe": True}

    monkeypatch.setattr(application, "rebuild_index", controlled_job)
    client = TestClient(create_app(application), client=("127.0.0.1", 51000))
    try:
        started = perf_counter()
        response = client.post(f"/api/v2/systems/{identity}/index/rebuild")
        assert response.status_code == 202, response.text
        assert perf_counter() - started < 3
        assert not release.is_set()
        task_id = response.json()["task"]["task_id"]
        started = perf_counter()
        progress = client.get(f"/api/v2/tasks/{task_id}?view=summary")
        assert progress.status_code == 200, progress.text
        assert progress.json()["task"]["status"] in {"pending", "running"}
        assert perf_counter() - started < 3
    finally:
        release.set()
        application.close()


def test_case_summary_filters_before_pagination(workspace):
    """超过一页的其他入口与环境不能遮蔽目标记录；摘要筛选在真实MySQL中先于LIMIT。"""

    from opentest.application.console_queries import CaseExecutionQuery, CaseGenerationQuery

    identity, store, _ = workspace
    queries = ConsoleQueries(SimpleNamespace(store=store))
    try:
        with store.metadata.transaction():
            for index in range(25):
                operation = "older-entry" if index < 2 else "recent-entry"
                environment = "uat" if index < 2 else "qa"
                generation_id = identity + f"-g{index:02d}"
                store.metadata.execute(
                    "INSERT INTO ot_case_generation(generation_id,system_id,operation_id,source_scan_id,status,generation_json,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (generation_id, identity, operation, "scan-probe", "READY", "{}", f"2026-09-{index + 1:02d} 00:00:00"))
                summary = {"execution_id": identity + f"-e{index:02d}", "generation_id": identity + "-g00", "environment_id": environment}
                summary.update(system_id=identity, status="COMPLETED", created_at=f"2026-09-{index + 1:02d}T00:00:00Z")
                store.metadata.save_execution("case", summary, create_only=True)
        # 若错误地先取全系统最近20条，这两个目标集合都会变成空列表。
        generations = queries.generations(identity, CaseGenerationQuery(view="summary", operation_id="older-entry"))
        reports = queries.executions(identity, "case", identity + "-g00", CaseExecutionQuery(view="summary", environment_id="uat"))
        assert len(generations["generations"]) == len(reports["executions"]) == 2
        assert not generations["pagination"]["has_more"] and not reports["pagination"]["has_more"]
    finally:
        store.metadata.execute("DELETE FROM ot_case_generation WHERE system_id=%s", (identity,))


@pytest.mark.parametrize("status", ["GENERATED", "STALE"])
def test_exact_target_preserves_catalog_contract_status(status):
    """精确目标读取保留目录的契约状态，不重建全系统目录。"""

    from opentest.application.foundation import OpenTestApplication
    from opentest.domain.models import KnowledgeTarget, KnowledgeTargetStatus

    application = OpenTestApplication.__new__(OpenTestApplication)
    application.store = Mock(metadata=Mock())
    target = KnowledgeTarget(target_id="entry:probe", category="facade", display_name="探针")
    catalog = SimpleNamespace(scan_id="scan-probe", targets=[target])
    application.scan_catalogs = Mock()
    application.scan_catalogs.build_console_catalog.return_value = catalog
    application.operation_contracts = Mock()
    application.operation_contracts.catalog_statuses.return_value = {target.target_id: KnowledgeTargetStatus(status)}
    application.knowledge_discovery = Mock()
    application._knowledge_generation_history = Mock(return_value=[])
    application.get_scan_catalog = Mock(side_effect=AssertionError("must not build all targets"))
    # 通过详情服务收到的目标核对语义，避免模拟返回值掩盖目标状态丢失。
    application.get_knowledge_target_detail("system-probe", target.target_id, False, False)
    projected = application.knowledge_discovery.target_detail.call_args.args[1]
    assert projected.knowledge_status.value == status


def test_workflow_summary_does_not_wait_for_full_background_or_catalog():
    """摘要状态从小字段读取，不读取完整背景、历史任务或目录投影。"""

    from opentest.application.foundation import OpenTestApplication

    application = OpenTestApplication.__new__(OpenTestApplication)
    application.store = Mock()
    application.store.metadata.fetch_one.return_value = {"latest_scan_id": "scan-probe", "completed": None, "skipped": "false"}
    application.store.metadata.fetch_all.return_value = [{"operation_id": "entry:probe"}]
    application.operation_contracts = Mock()
    application.operation_contracts.catalog_statuses.return_value = {}
    application.knowledge_discovery = Mock()
    application.tasks = Mock()
    application.get_scan_catalog = Mock(side_effect=AssertionError("summary must not read catalog"))
    snapshot = application.get_knowledge_workflow("probe", "summary")
    assert snapshot.target_counts["TOTAL"] == 1
    assert not snapshot.background_completed
    application.knowledge_discovery.get_context.assert_not_called()
    application.tasks.list_records.assert_not_called()


def test_context_summary_retains_facts_and_exact_candidate_evidence(workspace):
    """背景事实与目录完整保留，枚举证据仅在精确详情返回，摘要不能伪造空证据。"""

    identity, store, _ = workspace
    candidate = {"candidate_id": "candidate:business_term:0123456789abcdef", "system_id": identity,
                 "kind": "BUSINESS_TERM", "knowledge_form": "BUSINESS_ENUM", "name": "OrderStatus",
                 "business_name": "订单状态", "business_name_source": "CODE_VERIFIED", "status": "CODE_VERIFIED",
                 "enum_values": [{"code": "0", "business_meaning": "已创建", "source_refs": [{"path": "OrderStatus.java", "line": 7}]}],
                 "source_refs": [{"path": "OrderStatus.java", "line": 3}], "affected_target_ids": ["entry:probe"]}
    context = {"system_id": identity, "system_purpose": "完整业务用途", "interview_answers": {"purpose": "全部事实"}, "candidates": [candidate]}
    store.metadata.execute("UPDATE ot_system SET context_json=%s WHERE system_id=%s", (json.dumps(context), identity))
    queries = ConsoleQueries(SimpleNamespace(store=store))
    summary = queries.knowledge_context(identity)["context"]
    assert summary["system_purpose"] == context["system_purpose"]
    assert summary["interview_answers"] == context["interview_answers"]
    assert len(summary["candidates"]) == 1
    assert summary["candidates"][0]["detail_view"] == "summary"
    assert "enum_values" not in summary["candidates"][0]
    assert queries.knowledge_candidate(identity, candidate["candidate_id"])["candidate"] == candidate


def test_archive_summary_keeps_restore_status_without_file_payload(workspace):
    """归档摘要保留恢复状态与真实数量，完整恢复清单仍存在原记录中。"""

    from opentest.application.console_queries import ConsolePage

    identity, store, _ = workspace
    archive_id = "archive-" + identity
    archive = {"archive_id": archive_id, "system_id": identity, "system": {"system_id": identity, "name": "摘要探针"},
               "reason": "test", "integrity_status": "valid", "integrity_error": "",
               "created_at": "2099-01-01T00:00:00Z", "files": [{"path": "evidence"}], "derived_files": []}
    store.metadata.put_workflow("system_archive", archive_id, archive)
    queries = ConsoleQueries(SimpleNamespace(store=store))
    summaries = queries.archives(ConsolePage(view="summary"))["archives"]
    summary = next(item for item in summaries if item["archive_id"] == archive_id)
    assert summary["integrity_status"] == "valid" and summary["file_count"] == 1
    assert summary["derived_file_count"] == 0 and "files" not in summary
    assert store.metadata.get_workflow("system_archive", archive_id)["files"] == archive["files"]
