"""以真实 MySQL 验证覆盖报告小终态、恢复候选和材料永久保留。"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import Mock

import pytest

from opentest.adapters.coverage import CoverageUnavailable
from opentest.adapters.coverage_store import CoverageStore
from opentest.adapters.mysql_metadata import decode_json, unpack_json
from opentest.domain.coverage_workflow import CoverageMeasurement, INTERNAL_REPORT_RETENTION_PENDING
from opentest.domain.errors import ScopeViolationError
from opentest.domain.models import TaskRecord, TaskStatus, utc_now
from tests.v2.test_coverage_store import LockConnection, report_for, stores, workflow


def test_report_status_update_preserves_gzip_and_read_uses_column_status(stores, monkeypatch) -> None:
    """报告终态只写小列，读取以同一行状态覆盖旧压缩包，不重编码原始 exec。"""

    owner, _ = stores
    current = owner.create(workflow("status-only"))
    owner.save_report(report_for(current))
    before = owner.metadata.fetch_one(
        "SELECT status,summary_json,payload_gzip FROM ot_execution WHERE execution_kind='coverage' AND execution_id=%s",
        (current.enhancement_id,),
    )
    terminal = current.model_copy(update={"status": "COMPLETED", "stage": "FINISHED"})
    # 状态接口若退回整包保存会触发此断言；真实数据库仍负责列/摘要写入。
    monkeypatch.setattr(owner, "save_report", Mock(side_effect=AssertionError("status update must not rewrite report")))
    assert owner.set_report_status(terminal) == "RUNNING"
    after = owner.metadata.fetch_one(
        "SELECT status,summary_json,payload_gzip FROM ot_execution WHERE execution_kind='coverage' AND execution_id=%s",
        (current.enhancement_id,),
    )
    assert after["status"] == "COMPLETED"
    assert decode_json(after["summary_json"])["status"] == "COMPLETED"
    assert after["payload_gzip"] == before["payload_gzip"]
    assert unpack_json(after["payload_gzip"])["status"] == "RUNNING"
    restored = owner.report(current.enhancement_id)
    assert restored.status == "COMPLETED"
    assert restored.result["baseline"].exec_base64 == "Zml4dHVyZQ=="
    assert owner.set_report_status(terminal) == "COMPLETED"
    assert owner.set_report_status(workflow("missing-report")) is None


def test_report_status_and_workflow_share_outer_transaction(stores) -> None:
    """终态更新必须服从最外层提交，后续任务写失败时不能留下半收尾报告。"""

    owner, _ = stores
    current = owner.create(workflow("rollback-status"))
    owner.save_report(report_for(current))
    task = TaskRecord(task_id=current.task_id, operation="coverage-enhancement",
                      system_id=current.system_id, trace_id="fixture", status=TaskStatus.RUNNING)
    owner.metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    terminal = current.model_copy(update={"status": "COMPLETED", "stage": "FINISHED"})
    with pytest.raises(RuntimeError, match="injected finalization failure"):
        with owner.metadata.transaction():
            owner.save(terminal)
            owner.set_report_status(terminal)
            finished_task = task.model_copy(update={"status": TaskStatus.COMPLETED, "ended_at": utc_now()})
            owner.metadata.put_workflow("task", task.task_id, finished_task.model_dump(mode="json"))
            # 三次真实写入完成后模拟外围异常，应由同一事务统一回滚。
            raise RuntimeError("injected finalization failure")
    assert owner.get(current.enhancement_id).status == "RUNNING"
    assert owner.report(current.enhancement_id).status == "RUNNING"
    assert owner.metadata.get_workflow("task", task.task_id)["status"] == "running"


def test_report_status_cannot_cross_workspace(stores) -> None:
    """状态小写入仍保留报告所有权，另一工作台不能修改或读取原始报告。"""

    owner, foreign = stores
    current = owner.create(workflow("private-status"))
    owner.save_report(report_for(current))
    terminal = current.model_copy(update={"status": "COMPLETED"})
    with pytest.raises(ScopeViolationError, match="another workspace"):
        foreign.set_report_status(terminal)
    with pytest.raises(ScopeViolationError, match="another workspace"):
        foreign.report(current.enhancement_id)
    assert owner.report(current.enhancement_id).status == "RUNNING"


def test_late_status_updates_preserve_permanent_historical_material(stores) -> None:
    """持有旧工作流的迟到收尾只能改状态，遗留维护调用前后历史材料保持完整。"""

    owner, _ = stores
    started = utc_now() - timedelta(minutes=1)
    older = workflow("pruned-status").model_copy(update={
        "status": "COMPLETED", "stage": "FINISHED", "created_at": started,
        "baseline": CoverageMeasurement(status="VALID"),
    })
    newer = workflow("retained-status").model_copy(update={
        "status": "COMPLETED", "stage": "FINISHED",
        "baseline": CoverageMeasurement(status="VALID"),
    })
    for current in (older, newer):
        owner.create(current)
        owner.save_report(report_for(current))
    old_in_memory = owner.report(older.enhancement_id)
    before_maintenance = owner.metadata.fetch_one(
        "SELECT payload_gzip FROM ot_execution WHERE execution_kind='coverage' AND execution_id=%s",
        (older.enhancement_id,),
    )["payload_gzip"]
    # 旧保留策略入口必须为无损操作，不能清除或重编码历史原始材料。
    owner.prune(newer)
    assert old_in_memory.result
    assert owner.report(older.enhancement_id) == old_in_memory
    # 重入终态更新只改小列，永久保存的材料不能被迟到回调覆盖。
    for _ in range(2):
        assert owner.set_report_status(older) == "COMPLETED"
    assert owner.report(older.enhancement_id) == old_in_memory
    assert owner.report(newer.enhancement_id).result
    assert owner.metadata.fetch_one(
        "SELECT payload_gzip FROM ot_execution WHERE execution_kind='coverage' AND execution_id=%s",
        (older.enhancement_id,),
    )["payload_gzip"] == before_maintenance


def test_candidates_isolate_bad_payload_and_include_incomplete_finalization(stores, caplog) -> None:
    """坏聚合不阻塞健康记录；终态缺任务同步、报告同步或裁剪仍进入恢复候选。"""

    owner, foreign = stores
    broken = owner.create(workflow("broken-payload"))
    active = owner.create(workflow("healthy-active"))
    pending_task = owner.create(workflow("pending-task").model_copy(update={"status": "COMPLETED", "stage": "FINISHED"}))
    pending_report = owner.create(workflow("pending-report").model_copy(update={"status": "COMPLETED", "stage": "FINISHED"}))
    pending_prune = owner.create(workflow("pending-prune").model_copy(update={
        "status": "PARTIAL", "stage": "FINISHED", "reason_codes": [INTERNAL_REPORT_RETENTION_PENDING],
    }))
    complete = owner.create(workflow("fully-finished").model_copy(update={"status": "COMPLETED", "stage": "FINISHED"}))
    foreign.create(workflow("foreign-pending"))
    task = TaskRecord(task_id=pending_task.task_id, operation="coverage-enhancement",
                      system_id=pending_task.system_id, trace_id="fixture", status=TaskStatus.RUNNING)
    owner.metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    owner.save_report(report_for(pending_report).model_copy(update={"status": "RUNNING"}))
    # 模拟升级遗留的未知字段，SQL 查询仍命中但严格领域解析必然失败。
    owner.metadata.execute(
        "UPDATE ot_workflow_record SET payload_json=JSON_SET(payload_json,'$.unsupported_field',%s) "
        "WHERE record_kind='coverage_enhancement' AND record_id=%s",
        ("private-invalid-value", broken.enhancement_id),
    )
    candidates = {item.enhancement_id for item in owner.candidates()}
    assert candidates == {
        active.enhancement_id, pending_task.enhancement_id,
        pending_report.enhancement_id, pending_prune.enhancement_id,
    }
    assert complete.enhancement_id not in candidates
    assert "broken-payload" in caplog.text
    assert "private-invalid-value" not in caplog.text


def test_candidates_stop_selecting_completed_maintenance(stores) -> None:
    """任务、报告和裁剪均已补齐后应退出候选，避免维护反复写终态记录。"""

    owner, _ = stores
    current = owner.create(workflow("settled-maintenance").model_copy(update={
        "status": "PARTIAL", "stage": "FINISHED", "reason_codes": [INTERNAL_REPORT_RETENTION_PENDING],
    }))
    task = TaskRecord(task_id=current.task_id, operation="coverage-enhancement",
                      system_id=current.system_id, trace_id="fixture", status=TaskStatus.RUNNING)
    owner.metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    owner.save_report(report_for(current).model_copy(update={"status": "RUNNING"}))
    assert {item.enhancement_id for item in owner.candidates()} == {current.enhancement_id}
    with owner.metadata.transaction():
        current = owner.save(current.model_copy(update={"reason_codes": []}))
        owner.set_report_status(current)
        task = task.model_copy(update={"status": TaskStatus.PARTIAL, "ended_at": utc_now()})
        owner.metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    assert owner.candidates() == []


def test_execution_lookup_respects_requested_system(stores) -> None:
    """精确执行查找先限制系统；异常跨系统重复绑定也不能选中更晚的其他记录。"""

    owner, _ = stores
    first = owner.create(workflow("bound-refund").model_copy(update={
        "baseline_case_execution_id": "same-execution",
        "created_at": utc_now() - timedelta(seconds=1),
    }))
    second = owner.create(workflow("bound-other").model_copy(update={
        "system_id": "other", "baseline_case_execution_id": "same-execution",
    }))
    assert owner.for_execution("same-execution", "refund").enhancement_id == first.enhancement_id
    assert owner.for_execution("same-execution", "other").enhancement_id == second.enhancement_id
    assert owner.for_execution("same-execution", "missing") is None
    assert owner.for_execution("same-execution").enhancement_id == second.enhancement_id


@pytest.mark.parametrize(("acquired", "reason"), [
    (None, "COVERAGE_LOCK_UNAVAILABLE"), (0, "COVERAGE_LOCK_BUSY"),
])
def test_get_lock_null_is_failure_and_zero_is_contention(acquired, reason) -> None:
    """驱动的 NULL 不能冒充已有测量；两种失败都必须关闭独占连接。"""

    connection = LockConnection(acquired=acquired)
    metadata = Mock()
    metadata._connect.return_value = connection
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageStore(metadata).measurement_lock("refund", time.monotonic() + 10)
    assert failure.value.reason_code == reason
    assert connection.closed == 1
    assert any("GET_LOCK" in command[0] for command in connection.commands)
