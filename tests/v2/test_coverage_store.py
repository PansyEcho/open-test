"""验证覆盖增强的 CAS、精确恢复绑定、报告保留与独立测量锁。"""

from datetime import timedelta
from pathlib import Path
import base64
import random
import time
from typing import Iterator

import pytest

import opentest.application.foundation as foundation
from opentest.adapters.coverage import CoverageUnavailable
from opentest.adapters.coverage_store import CoverageMeasurementLease, CoverageStore
from opentest.adapters.mysql_metadata import MySqlMetadataStore, decode_json
from opentest.domain.coverage import ArtifactFileIdentity, CoverageArtifactSelection, FrozenCoverageArtifact
from opentest.domain.coverage_workflow import CoverageEnhancement, CoverageMeasurement, CoverageRawCapture, CoverageReport
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import utc_now


def workflow(identity: str, operation_id: str = "Api#query") -> CoverageEnhancement:
    """构造稳定身份的测试增强，调用方可显式修改阶段或绑定。

    Args:
        identity: 区分本次测试各增强与执行的后缀。
        operation_id: 用于验证报告保留粒度的接口身份。
    Returns:
        不包含真实系统或凭据的初始模型。
    """

    return CoverageEnhancement(enhancement_id=identity, task_id=f"task-{identity}", system_id="refund",
                               operation_id=operation_id, base_generation_id=f"generation-{identity}",
                               source_scan_id="scan-fixture", source_commit="0" * 40)


def report_for(record: CoverageEnhancement) -> CoverageReport:
    """构造可裁剪的虚构测量包，保留真实报告的压缩和领域校验路径。

    Args:
        record: 报告所属增强。
    Returns:
        含一个原始 exec 测试标记的终态报告。
    """

    artifact = FrozenCoverageArtifact(selection=CoverageArtifactSelection(app_uk="fixture"), commit="0" * 40,
        transport="LOCAL", artifact=ArtifactFileIdentity(path="/fixture/app.war", size=1, modified="1"),
        source=ArtifactFileIdentity(path="/fixture/source.zip", size=1, modified="1"))
    return CoverageReport(execution_id=record.enhancement_id, system_id=record.system_id,
        generation_id=record.base_generation_id, operation_id=record.operation_id, status=record.status,
        created_at=record.created_at, result={"baseline": CoverageRawCapture(exec_base64="Zml4dHVyZQ==", artifact=artifact)})


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[tuple[CoverageStore, CoverageStore]]:
    """复用测试框架随机 MySQL 库，提供同库两工作台；未配置专用测试库时跳过。

    Args:
        tmp_path: 用于派生测试工作台身份的临时目录。
    Yields:
        两个共享数据但具有独立所有权的覆盖存储。
    """

    metadata = foundation.load_metadata_store(tmp_path / "knowledge")
    foreign = MySqlMetadataStore(metadata.configuration, metadata.workspace_id + "-other")
    # 第一连接由 autouse fixture 管理；额外工作台仅关闭自己的连接池。
    try:
        yield CoverageStore(metadata), CoverageStore(foreign)
    finally:
        foreign.close()


def test_revision_cas_and_foreign_workspace_are_enforced(stores) -> None:
    """覆盖更新必须满足原版本和工作台所有权，失败不会修改已有状态。

    Args:
        stores: 同一隔离 MySQL 库内的两工作台存储。
    """

    owner, foreign = stores
    original = owner.create(workflow("enhancement-cas"))
    saved = owner.save(original.model_copy(update={"stage": "BASELINE_EXECUTING"}))
    assert saved.revision == 1 and original.revision == 0
    # 迟到线程不能把新阶段覆盖回旧阶段，另一工作台也不能接管终态或活动态。
    with pytest.raises(KnowledgeValidationError, match="revision"):
        owner.save(original)
    with pytest.raises(ScopeViolationError, match="another workspace"):
        foreign.save(saved)
    assert owner.get(original.enhancement_id).stage == "BASELINE_EXECUTING"
    with pytest.raises(KnowledgeValidationError, match="already exists"):
        owner.create(original)


def test_queries_and_recovery_use_exact_generation_and_execution_bindings(stores) -> None:
    """恢复只捞本工作台活动增强或明确仍运行的绑定执行，不把同接口其他执行补进来。

    Args:
        stores: 隔离 MySQL 的两工作台存储。
    """

    owner, foreign = stores
    active = owner.create(workflow("active"))
    terminal = workflow("terminal").model_copy(update={"status": "FAILED", "baseline_case_execution_id": "case-bound"})
    owner.create(terminal)
    unrelated = owner.create(workflow("unrelated").model_copy(update={"status": "COMPLETED"}))
    foreign.create(workflow("foreign"))
    for case_id, generation_id in (("case-bound", terminal.base_generation_id), ("case-unrelated", unrelated.base_generation_id)):
        owner.metadata.save_execution("case", {"execution_id": case_id, "system_id": "refund", "generation_id": generation_id,
                                               "environment_id": "qa", "status": "RUNNING"})
    # 数据库先投影 record_id，完整聚合只为真正需要恢复的两条记录读取。
    assert {item.enhancement_id for item in owner.candidates()} == {active.enhancement_id, terminal.enhancement_id}
    assert owner.for_execution("case-unrelated") is None
    assert owner.for_execution("case-bound").enhancement_id == "terminal"
    enhanced = owner.save(active.model_copy(update={"enhanced_generation_id": "generation-enhanced", "verification_case_execution_id": "case-verification"}))
    assert owner.for_generation("refund", "generation-enhanced") == enhanced
    assert owner.for_generation("other", "generation-enhanced") is None
    assert owner.for_execution("case-verification") == enhanced
    assert owner.for_generation("refund", "") is None
    assert owner.for_execution("") is None


def test_report_retention_only_prunes_older_terminal_owner_material(stores) -> None:
    """新有效终态包按保留粒度清理旧原始材料，保留摘要、他机、其他系统与在途记录。

    Args:
        stores: 同库两个工作台的隔离覆盖存储。
    """

    owner, foreign = stores
    old_time = utc_now() - timedelta(days=1)
    saved_records = {}
    for identity, operation, status in (("old-same", "Api#query", "COMPLETED"), ("old-other", "Api#cancel", "COMPLETED"),
                                        ("in-flight", "Api#query", "RUNNING")):
        record = workflow(identity, operation).model_copy(update={"status": status, "created_at": old_time})
        owner.create(record)
        owner.save_report(report_for(record))
        saved_records[identity] = record
    foreign_record = workflow("foreign-report").model_copy(update={"status": "COMPLETED", "created_at": old_time})
    foreign.create(foreign_record)
    foreign.save_report(report_for(foreign_record))
    newest = workflow("new-report").model_copy(update={"status": "COMPLETED", "baseline": CoverageMeasurement(status="VALID"), "report_retention_scope": "OPERATION"})
    owner.create(newest)
    owner.save_report(report_for(newest))
    # 操作粒度只替换同接口材料；原摘要永远不带 exec 或私有制品路径。
    owner.prune(newest)
    assert owner.report("old-same").result == {}
    assert owner.report("old-other").result
    assert owner.report("in-flight").result
    assert foreign.report("foreign-report").result
    # 共享增强摘要可查看，但原始报告的本机路径和环境引用只能由采集 owner 消费。
    with pytest.raises(ScopeViolationError, match="another workspace"):
        owner.report("foreign-report")
    summary = owner.metadata.fetch_one("SELECT summary_json FROM ot_execution WHERE execution_id=%s", ("new-report",))
    assert "result" not in decode_json(summary["summary_json"])
    owner.prune(newest.model_copy(update={"report_retention_scope": "SYSTEM_ENVIRONMENT"}))
    assert owner.report("old-other").result == {}
    assert owner.get("old-other") is not None
    # 无有效测量或新包为空时，失败运行不应擦除上一次有效包。
    failed = workflow("failed").model_copy(update={"status": "FAILED"})
    owner.save_report(report_for(failed))
    owner.prune(failed)
    assert owner.report("new-report").result


@pytest.mark.parametrize("scope", ["SYSTEM_ENVIRONMENT", "OPERATION"])
def test_late_older_report_prunes_itself_after_newer_valid_completion(stores, scope: str) -> None:
    """旧窗口晚完成时按采集创建顺序保留最新有效包，不以完成回调顺序决定。

    Args:
        stores: 同库两个独立工作台，验证保留范围不越过 owner。
        scope: 系统环境或接口粒度，均需保持在途和最近有效材料。
    """

    owner, foreign = stores
    started = utc_now() - timedelta(minutes=10)
    older = workflow("older-window").model_copy(update={"created_at": started, "report_retention_scope": scope})
    owner.create(older)
    owner.save_report(report_for(older))
    newer = workflow("newer-window").model_copy(update={
        "status": "COMPLETED", "baseline": CoverageMeasurement(status="VALID"),
        "created_at": started + timedelta(minutes=1), "report_retention_scope": scope,
    })
    owner.create(newer)
    owner.save_report(report_for(newer))
    # 更晚的失败或空包不能挤掉有效窗口；更早仍活动、其他 owner 的材料不允许裁剪。
    invalid = workflow("invalid-latest").model_copy(update={
        "status": "FAILED", "baseline": CoverageMeasurement(status="INVALID"),
        "created_at": started + timedelta(minutes=2), "report_retention_scope": scope,
    })
    empty = workflow("empty-latest").model_copy(update={
        "status": "COMPLETED", "baseline": CoverageMeasurement(status="VALID"),
        "created_at": started + timedelta(minutes=3), "report_retention_scope": scope,
    })
    active = workflow("older-active").model_copy(update={"created_at": started - timedelta(minutes=1)})
    other_operation = workflow("older-other-operation", "Api#cancel").model_copy(update={
        "status": "COMPLETED", "baseline": CoverageMeasurement(status="VALID"),
        "created_at": started - timedelta(minutes=1),
    })
    foreign_record = workflow("older-other-owner").model_copy(update={
        "status": "COMPLETED", "baseline": CoverageMeasurement(status="VALID"),
        "created_at": started - timedelta(minutes=1),
    })
    for record in (invalid, empty, active, other_operation):
        owner.create(record)
        report = report_for(record)
        owner.save_report(report.model_copy(update={"result": {}}) if record.enhancement_id == empty.enhancement_id else report)
    foreign.create(foreign_record)
    foreign.save_report(report_for(foreign_record))
    owner.prune(invalid)
    owner.prune(empty)
    assert owner.report(newer.enhancement_id).result

    # B 先完成时 A 仍在分析，不能删除 A 的恢复材料。
    owner.prune(newer)
    assert owner.report(older.enhancement_id).result
    older = owner.save(older.model_copy(update={"status": "COMPLETED", "baseline": CoverageMeasurement(status="VALID")}))
    owner.save_report(report_for(older))
    owner.prune(older)
    assert owner.report(older.enhancement_id).result == {}
    assert owner.report(newer.enhancement_id).result
    assert owner.report(active.enhancement_id).result
    assert owner.report(invalid.enhancement_id).result
    assert foreign.report(foreign_record.enhancement_id).result
    assert bool(owner.report(other_operation.enhancement_id).result) is (scope == "OPERATION")
    assert owner.get(older.enhancement_id).baseline.status == "VALID"


def test_large_exec_roundtrip_uses_compressed_mysql_detail_without_summary_payload(stores) -> None:
    """真实 MySQL 保存并完整还原 4 MiB exec，列表摘要不携带原始材料。

    Args:
        stores: 随机隔离 MySQL 库内的覆盖存储，不访问真实业务数据。
    """

    owner, _ = stores
    record = workflow("large-exec").model_copy(update={"status": "COMPLETED", "baseline": CoverageMeasurement(status="VALID")})
    owner.create(record)
    # 固定伪随机内容避免极易压缩的重复字符串掩盖实际大包读写边界。
    exec_bytes = random.Random(19).randbytes(4 * 1024 * 1024)
    encoded = base64.b64encode(exec_bytes).decode("ascii")
    report = report_for(record)
    report.result["baseline"].exec_base64 = encoded
    owner.save_report(report)
    restored = owner.report(record.enhancement_id)
    assert base64.b64decode(restored.result["baseline"].exec_base64, validate=True) == exec_bytes
    assert restored.result["baseline"].artifact == report.result["baseline"].artifact
    # 检查数据库实际存储尺寸和摘要，而不是只对 pack/unpack 辅助函数做自证。
    row = owner.metadata.fetch_one(
        "SELECT OCTET_LENGTH(payload_gzip) AS compressed_bytes,summary_json FROM ot_execution WHERE execution_id=%s",
        (record.enhancement_id,),
    )
    assert 1024 * 1024 < row["compressed_bytes"] < len(encoded)
    assert "result" not in decode_json(row["summary_json"])


def test_real_measurement_lock_contends_across_workspaces_and_releases(stores) -> None:
    """真实 MySQL 命名锁跨工作台互斥、零等待，释放后同系统可再次测量。

    Args:
        stores: 同库两个不同所有者的覆盖存储。
    """

    owner, foreign = stores
    first = owner.measurement_lock("refund", time.monotonic() + 5)
    try:
        with pytest.raises(CoverageUnavailable) as failure:
            foreign.measurement_lock("refund", time.monotonic() + 5)
        assert failure.value.reason_code == "COVERAGE_LOCK_BUSY"
        # 不同系统不共享命名锁，也无需持有业务写事务。
        other = foreign.measurement_lock("other", time.monotonic() + 5)
        other.release()
    finally:
        first.release()
    second = foreign.measurement_lock("refund", time.monotonic() + 5)
    second.release()
    second.release()


class LockConnection:
    """模拟驱动失败边界，只记录连接生命周期，不代替真实 MySQL 互斥测试。"""

    def __init__(self, acquired: int = 1, fail_release: bool = False) -> None:
        """设置锁结果和释放失败分支，统计关闭次数供 finally 断言。

        Args:
            acquired: GET_LOCK 返回值。
            fail_release: RELEASE_LOCK 是否模拟驱动异常。
        """

        self.acquired = acquired
        self.fail_release = fail_release
        self.closed = 0
        self.commands = []

    def autocommit(self, enabled: bool) -> None:
        """记录租约连接是否脱离写事务，enabled 为驱动布尔参数。"""

        self.commands.append(("autocommit", enabled))

    def cursor(self):
        """返回自身作为无真实网络的游标。"""

        return self

    def __enter__(self):
        """进入模拟游标作用域并返回自身。"""

        return self

    def __exit__(self, exception_type, exception, traceback):
        """遵守上下文管理协议，不吞异常且不关闭所属连接。"""

        return None

    def execute(self, sql, parameters=()):
        """记录参数化锁 SQL，释放失败模拟只包含虚构敏感详情。"""

        self.commands.append((sql, parameters))
        if "RELEASE_LOCK" in sql and self.fail_release:
            raise RuntimeError("fake-private-detail")

    def fetchone(self):
        """返回预设的 GET_LOCK 结果。"""

        return {"acquired": self.acquired}

    def close(self):
        """统计连接关闭，便于证明异常路径也释放锁所属连接。"""

        self.closed += 1


def test_lease_closes_connection_when_unlock_raises_and_is_idempotent(caplog) -> None:
    """释放 SQL 报错仍关闭连接，重复清理无副作用且日志只记录异常类型。

    Args:
        caplog: 捕获安全清理日志。
    """

    connection = LockConnection(fail_release=True)
    lease = CoverageMeasurementLease(connection, "refund")
    lease.release()
    lease.release()
    assert connection.closed == 1
    assert "RuntimeError" in caplog.text
    assert "fake-private-detail" not in caplog.text


def test_measurement_lock_budget_and_failed_acquire_close_connection(monkeypatch) -> None:
    """过期准备不能连接，锁忙要关闭独立连接，并把剩余预算传给驱动。

    Args:
        monkeypatch: 注入不联网的连接工厂。
    """

    connection = LockConnection(acquired=0)
    metadata = MySqlMetadataStore({"host": "unused", "user": "fixture", "database": "fixture"}, "fixture")
    budgets = []

    def connect(timeout=None):
        """记录覆盖准备预算并返回锁忙连接，不执行网络访问。"""

        budgets.append(timeout)
        return connection

    monkeypatch.setattr(metadata, "_connect", connect)
    store = CoverageStore(metadata)
    with pytest.raises(CoverageUnavailable) as expired:
        store.measurement_lock("refund", time.monotonic() - 1)
    assert expired.value.reason_code == "COVERAGE_PREFLIGHT_TIMEOUT" and budgets == []
    with pytest.raises(CoverageUnavailable) as busy:
        store.measurement_lock("refund", time.monotonic() + 2)
    assert busy.value.reason_code == "COVERAGE_LOCK_BUSY"
    assert 0 < budgets[0] <= 2
    assert connection.closed == 1
    metadata.close()


def test_connect_timeout_override_preserves_default_and_caps_only_one_connection() -> None:
    """可选连接预算覆盖三类超时，后续默认连接不被修改。

    Returns:
        断言通过后结束；只使用捕获工厂，不访问数据库。
    """

    calls = []

    def connect(**configuration):
        """捕获 PyMySQL 参数并返回独立测试连接。"""

        calls.append(configuration)
        return LockConnection()

    metadata = MySqlMetadataStore({"host": "unused", "user": "fixture", "database": "fixture"}, "fixture", connect)
    metadata._connect(timeout=0.5).close()
    metadata._connect().close()
    assert all(calls[0][key] == 0.5 for key in ("connect_timeout", "read_timeout", "write_timeout"))
    assert calls[1]["connect_timeout"] == 10 and calls[1]["read_timeout"] == 60
    metadata.close()


def test_measurement_lock_does_not_query_after_connection_consumes_budget(monkeypatch) -> None:
    """连接刚完成时预算已耗尽，不能继续发起锁 SQL，且必须关闭独立连接。

    Args:
        monkeypatch: 用确定时钟和连接代替真实等待及网络。
    """

    connection = LockConnection()
    metadata = MySqlMetadataStore({"host": "unused", "user": "fixture", "database": "fixture"}, "fixture")
    ticks = iter((1.0, 3.0))
    monkeypatch.setattr("opentest.adapters.coverage_store.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr(metadata, "_connect", lambda timeout: connection)
    with pytest.raises(CoverageUnavailable) as expired:
        CoverageStore(metadata).measurement_lock("refund", 2.0)
    assert expired.value.reason_code == "COVERAGE_PREFLIGHT_TIMEOUT"
    assert connection.commands == [] and connection.closed == 1
    metadata.close()
