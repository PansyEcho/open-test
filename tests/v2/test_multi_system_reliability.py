"""验证多系统隔离、可恢复归档、动态扫描器设置和全局任务门禁。"""

from __future__ import annotations

import stat
import threading
from pathlib import Path

import pytest

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.runtime_settings import RuntimeToolSettingsStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.adapters.system_archive import SystemArchiveStore
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import LocalTaskManager
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    KnowledgeNode,
    KnowledgeNodeKind,
    RuntimeToolSettings,
    SourceScanRequest,
    SystemDefinition,
    TaskStatus,
)


def _register_two_systems(tmp_path: Path) -> tuple[GitKnowledgeStore, SystemDefinition, SystemDefinition]:
    """创建两个源码目录并注册为互相隔离的系统。

    Args:
        tmp_path: Pytest隔离目录。

    Returns:
        知识存储和两个已注册系统定义。
    """

    first_source = tmp_path / "first-system"
    second_source = tmp_path / "second-system"
    first_source.mkdir()
    second_source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    first = store.register_system(SystemDefinition(system_id="first-system", name="系统一", source_path=str(first_source)))
    second = store.register_system(SystemDefinition(system_id="second-system", name="系统二", source_path=str(second_source)))
    return store, first, second


def test_update_one_system_preserves_other_registry_and_assets(tmp_path: Path) -> None:
    """更新系统一时不得覆盖系统二的路由、源码路径或知识文件。"""

    store, first, second = _register_two_systems(tmp_path)
    second_node = KnowledgeNode(
        node_id="facade:SecondFacade#query",
        system_id=second.system_id,
        kind=KnowledgeNodeKind.FACADE,
        title="查询系统二",
    )
    second_path = store.write_node(second_node, "系统二独立知识")

    store.update_system(
        first.system_id,
        first.model_copy(update={"name": "系统一新名称"}),
    )

    assert store.get_system(first.system_id).name == "系统一新名称"
    assert store.get_system(second.system_id).source_path == second.source_path
    assert "系统二独立知识" in second_path.read_text(encoding="utf-8")


def test_archive_and_restore_verifies_files_and_rebuilds_scope(tmp_path: Path) -> None:
    """归档应移走目标系统文件且可按摘要恢复，不影响另一系统。"""

    store, first, second = _register_two_systems(tmp_path)
    first_node = KnowledgeNode(
        node_id="facade:FirstFacade#create",
        system_id=first.system_id,
        kind=KnowledgeNodeKind.FACADE,
        title="创建系统一实体",
    )
    store.write_node(first_node, "系统一独立知识")
    local_environment = store.root / ".opentest/environments" / first.system_id / "qa.yaml"
    local_environment.parent.mkdir(parents=True)
    local_environment.write_text("system_id: first-system\nenvironment: qa\n", encoding="utf-8")
    local_environment.chmod(0o600)
    preview_path = store.root / ".opentest/natural-language-previews" / first.system_id / "preview-001.json"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_text('{"system_id":"first-system"}', encoding="utf-8")
    run_path = store.root / ".opentest/runs/run-001.json"
    run_path.parent.mkdir(parents=True)
    run_path.write_text('{"system_id":"first-system","run_id":"run-001"}', encoding="utf-8")
    archives = SystemArchiveStore(store)

    record = archives.archive(first.system_id, "验证混合数据可恢复归档")

    assert [item.system_id for item in store.list_systems()] == [second.system_id]
    assert not store.system_root(first.system_id).exists()
    assert record.files
    assert not preview_path.exists()
    assert not run_path.exists()
    assert {item.relative_path for item in record.files} >= {
        "natural-language-previews/first-system/preview-001.json",
        "runs/run-001.json",
    }
    assert record.derived_files[0].relative_path == "registry/systems.yaml"
    assert archives.list_archives()[0].archive_id == record.archive_id

    restored = archives.restore(record.archive_id)
    counts = SqliteKnowledgeIndex(store.root / ".opentest/index.sqlite").rebuild(store)

    assert restored.system.system_id == first.system_id
    assert [item.system_id for item in store.list_systems()] == [first.system_id, second.system_id]
    assert counts["systems"] == 2
    assert stat.S_IMODE(local_environment.stat().st_mode) == 0o600
    assert preview_path.is_file()
    assert run_path.is_file()


def test_restore_does_not_publish_derived_archive_registry(tmp_path: Path) -> None:
    """恢复系统不得用归档审计registry覆盖其他活动系统路由。

    Args:
        tmp_path: Pytest提供的隔离多系统知识目录。
    """

    store, first, second = _register_two_systems(tmp_path)
    archives = SystemArchiveStore(store)

    record = archives.archive(first.system_id, "验证派生registry不会参与恢复")
    archives.restore(record.archive_id)

    # 恢复只发布原系统注册，不移动审计registry，因此第二个活动系统仍然存在。
    assert [item.system_id for item in store.list_systems()] == [first.system_id, second.system_id]
    assert (store.root / "archives" / record.archive_id / "knowledge/registry/systems.yaml").is_file()


def test_runtime_settings_diagnose_real_scriptgen_without_restart(tmp_path: Path) -> None:
    """保存真实agent-harness路径后应立即就绪且文件权限固定0600。"""

    scriptgen_root = Path("/Users/user/data/code/other/CLI-Anything/scriptgen/agent-harness")
    if not scriptgen_root.is_dir():
        pytest.skip("本机scriptgen agent-harness不存在")
    store = RuntimeToolSettingsStore(tmp_path / ".opentest/settings.yaml")

    before = store.diagnose()
    saved = store.write(RuntimeToolSettings(scriptgen_pythonpath=str(scriptgen_root)))
    after = store.diagnose()

    assert before.status in {"MODULE_UNAVAILABLE", "READY"}
    assert saved.scriptgen_pythonpath == str(scriptgen_root.resolve())
    assert after.status == "READY"
    assert after.source == "local_settings"
    assert stat.S_IMODE(store.settings_path.stat().st_mode) == 0o600


def test_booking_core_scan_policy_derives_qa_job_url_without_token(tmp_path: Path) -> None:
    """Booking.Core自动扫描应补齐36个Job所需规则且只派生QA地址。

    Args:
        tmp_path: Pytest提供的隔离源码、知识和本地设置目录。
    """

    source = tmp_path / "travelsystem.java.dsf.supplychain.booking.core"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(
            system_id="travelsystem.java.dsf.supplychain.booking.core",
            name="Booking.Core",
            source_path=str(source),
        )
    )
    application.save_local_settings(
        "travelsystem.java.dsf.supplychain.booking.core",
        "must-not-enter-scan-request",
        "http://servicegw.qa.ly.com/gateway/train.supplychain.booking.core/v2",
    )

    effective = application._source_scan_request(
        SourceScanRequest(system_id="travelsystem.java.dsf.supplychain.booking.core")
    )

    assert effective.job_rules == [
        {
            "enabled": True,
            "http_url_prefix": "http://servicegw.qa.ly.com/gateway/train.supplychain.booking.core/job",
            "package_name": "com.ly.travel.train.supplychain.bookingcore.biz.job",
            "trigger_mode": "http",
        }
    ]
    assert effective.facade_http_prefix == "http://servicegw.qa.ly.com/gateway/train.supplychain.booking.core/v2"
    assert "must-not-enter-scan-request" not in effective.model_dump_json()


def test_generic_dsf_scan_uses_local_gateway_and_explicit_prefix_wins(tmp_path: Path) -> None:
    """普通DSF扫描应动态使用本地网关，同时保留CLI显式前缀优先级。

    Args:
        tmp_path: Pytest隔离的源码、知识与本地系统设置目录。
    """

    source = tmp_path / "ifightchainsaas.java.refund.core"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(
            system_id="ifightchainsaas.java.refund.core",
            name="SaaS退票核心",
            source_path=str(source),
        )
    )
    application.save_local_settings(
        "ifightchainsaas.java.refund.core",
        "must-not-enter-scan-request",
        "http://servicegw.qa.ly.com/gateway/saas.refund.core/qa",
    )

    local_request = application._source_scan_request(
        SourceScanRequest(system_id="ifightchainsaas.java.refund.core"),
    )
    explicit_request = application._source_scan_request(
        SourceScanRequest(
            system_id="ifightchainsaas.java.refund.core",
            facade_http_prefix="https://explicit.qa.example/refund/v2/",
        ),
    )

    assert local_request.facade_http_prefix == "http://servicegw.qa.ly.com/gateway/saas.refund.core/qa"
    assert explicit_request.facade_http_prefix == "https://explicit.qa.example/refund/v2"
    assert "must-not-enter-scan-request" not in local_request.model_dump_json()
    application.close()


def test_generic_dsf_scan_blocks_before_scriptgen_when_gateway_is_missing(tmp_path: Path) -> None:
    """普通DSF缺少显式及本地网关时应在scriptgen进程启动前给出可操作错误。

    Args:
        tmp_path: Pytest隔离的源码和知识目录。
    """

    source = tmp_path / "missing-gateway-system"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(system_id="missing-gateway-system", name="缺少网关", source_path=str(source)),
    )

    with pytest.raises(KnowledgeValidationError, match="QA Facade网关前缀"):
        application._source_scan_request(SourceScanRequest(system_id="missing-gateway-system"))

    application.close()


@pytest.mark.parametrize(
    "gateway_prefix",
    [
        "http://[::1",
        "http://gateway.qa.example:invalid/refund/v2",
        "http://gateway.qa.example:70000/refund/v2",
        "http://user:password@gateway.qa.example/refund/v2",
        "http://gateway.qa.example/refund/v2?debug=true",
        "http://gateway.qa.example/refund/v2#fragment",
    ],
)
def test_generic_dsf_scan_rejects_gateway_that_cannot_be_used_as_base_url(
    tmp_path: Path,
    gateway_prefix: str,
) -> None:
    """畸形或携带请求级信息的网关必须稳定转换为可操作配置错误。

    Args:
        tmp_path: Pytest隔离的源码和知识目录。
        gateway_prefix: 不能安全追加Facade接口后缀的网关输入。
    """

    source = tmp_path / "invalid-gateway-system"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(system_id="invalid-gateway-system", name="非法网关", source_path=str(source)),
    )

    # 所有畸形输入都应在scriptgen启动前收敛为同一领域错误，避免泄漏urllib实现异常。
    with pytest.raises(KnowledgeValidationError, match="QA Facade网关前缀"):
        application._source_scan_request(
            SourceScanRequest(
                system_id="invalid-gateway-system",
                facade_http_prefix=gateway_prefix,
            ),
        )

    application.close()


def test_global_exclusive_task_rejects_conflict_and_recovers_activity(tmp_path: Path) -> None:
    """排他长任务运行时第二次提交必须失败，结束后活动状态自动清除。"""

    manager = LocalTaskManager(tmp_path / "tasks", max_workers=2)
    started = threading.Event()
    release = threading.Event()

    def blocking_job() -> dict[str, bool]:
        """等待测试释放，保持全局门禁可被并发提交观察。"""

        started.set()
        release.wait(timeout=5)
        return {"released": True}

    first = manager.submit("source-scan", "first-system", blocking_job, exclusive=True)
    assert started.wait(timeout=2)
    assert manager.activity().task_id == first.task_id
    with pytest.raises(ScopeViolationError, match="another long task"):
        manager.submit("resource-probe", "second-system", lambda: {}, exclusive=True)

    release.set()
    manager.close()

    assert manager.get(first.task_id).status == TaskStatus.COMPLETED
    assert not manager.activity().active


def test_prepared_task_rolls_back_configuration_when_submission_fails(tmp_path: Path, monkeypatch) -> None:
    """准备阶段发布配置后若线程池拒绝任务，必须执行回滚且释放全局门禁。

    Args:
        tmp_path: Pytest隔离任务目录。
        monkeypatch: 模拟线程池提交失败。
    """

    manager = LocalTaskManager(tmp_path / "tasks")
    prepared = tmp_path / "prepared.txt"

    def prepare():
        """创建可观察配置，并返回删除该配置的回滚动作。"""

        prepared.write_text("published", encoding="utf-8")
        return lambda: prepared.unlink(missing_ok=True)

    def fail_submit(*_args, **_kwargs):
        """模拟配置发布后线程池不可接受新任务。"""

        raise RuntimeError("executor rejected")

    monkeypatch.setattr(manager._executor, "submit", fail_submit)
    with pytest.raises(RuntimeError, match="executor rejected"):
        manager.submit_prepared("source-scan", "first-system", lambda: {}, prepare)

    assert not prepared.exists()
    assert not manager.activity().active
    manager.close()


def test_prepared_update_restores_existing_local_qa_settings(tmp_path: Path, monkeypatch) -> None:
    """已有QA配置的系统更新提交失败时应精确恢复原始Token、前缀和业务Fixture。

    Args:
        tmp_path: Pytest隔离知识、源码和本地敏感设置目录。
        monkeypatch: 模拟线程池拒绝已完成准备阶段的扫描任务。
    """

    source = tmp_path / "existing-system"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    original_system = application.register_system(
        SystemDefinition(system_id="existing-system", name="原系统", source_path=str(source))
    )
    application.save_local_settings(
        original_system.system_id,
        "original-local-token",
        "http://servicegw.qa.ly.com/gateway/original/v2",
    )
    settings_path = application.store.root / ".opentest/environments/existing-system/qa.yaml"
    settings_path.write_text(
        settings_path.read_text(encoding="utf-8") + "fixture:\n  passenger_ref: local-only\n",
        encoding="utf-8",
    )
    settings_path.chmod(0o600)
    original_text = settings_path.read_text(encoding="utf-8")

    def fail_submit(*_args, **_kwargs):
        """在配置发布后模拟后台执行器拒绝任务。"""

        raise RuntimeError("executor rejected existing update")

    monkeypatch.setattr(application.tasks._executor, "submit", fail_submit)
    updated_system = original_system.model_copy(update={"name": "不应保留的新名称"})
    with pytest.raises(RuntimeError, match="executor rejected existing update"):
        application.submit_prepared_source_scan(
            SourceScanRequest(system_id=original_system.system_id),
            lambda: application.prepare_system_update(
                original_system.system_id,
                updated_system,
                "replacement-token",
                "http://servicegw.qa.ly.com/gateway/replacement/v2",
            ),
        )

    assert application.store.get_system(original_system.system_id).name == "原系统"
    assert settings_path.read_text(encoding="utf-8") == original_text
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
    assert not application.get_console_activity().active
    application.tasks.close()


def test_rollback_failure_keeps_original_error_and_releases_global_lock(tmp_path: Path, monkeypatch) -> None:
    """回滚自身异常不得掩盖提交根因，也不得阻塞下一进程获取全局门禁。

    Args:
        tmp_path: 两个任务管理器共享的本地任务目录。
        monkeypatch: 模拟第一个管理器的执行器拒绝任务。
    """

    task_root = tmp_path / "tasks"
    first = LocalTaskManager(task_root)

    def prepare():
        """返回一个故意失败的回滚动作以覆盖故障恢复边界。"""

        def fail_rollback() -> None:
            """模拟磁盘异常导致业务配置无法恢复。"""

            raise OSError("rollback disk failure")

        return fail_rollback

    def fail_submit(*_args, **_kwargs):
        """模拟任务活动已经发布后执行器拒绝接管。"""

        raise RuntimeError("original submit failure")

    monkeypatch.setattr(first._executor, "submit", fail_submit)
    with pytest.raises(RuntimeError, match="original submit failure"):
        first.submit_prepared("source-scan", "first-system", lambda: {}, prepare)

    # 新管理器能立刻提交排他任务，证明POSIX文件锁和活动摘要均已释放。
    second = LocalTaskManager(task_root)
    task = second.submit("source-scan", "second-system", lambda: {"ok": True}, exclusive=True)
    second.close()
    assert second.get(task.task_id).status == TaskStatus.COMPLETED
    first.close()


def test_booking_catalog_install_failure_leaves_no_orphan_directory(tmp_path: Path, monkeypatch) -> None:
    """Booking固定校验目录安装失败后不得留下阻止同ID重试的孤儿知识目录。

    Args:
        tmp_path: Pytest隔离源码和知识根目录。
        monkeypatch: 第一次注册时注入固定目录安装故障。
    """

    source = tmp_path / "travelsystem.java.dsf.supplychain.booking.core"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    system = SystemDefinition(
        system_id="travelsystem.java.dsf.supplychain.booking.core",
        name="Booking.Core",
        source_path=str(source),
    )
    original_installer = application._install_booking_core_validation_catalog

    def fail_catalog_install(_system_id: str) -> None:
        """模拟固定目录资产在系统骨架创建后无法安装。"""

        raise RuntimeError("catalog installation failed")

    monkeypatch.setattr(application, "_install_booking_core_validation_catalog", fail_catalog_install)
    with pytest.raises(RuntimeError, match="catalog installation failed"):
        application.register_system(system)

    assert application.store.list_systems() == []
    assert not application.store.system_root(system.system_id).exists()

    # 恢复真实安装器后，同一稳定ID必须能够重新注册并得到校验目录。
    monkeypatch.setattr(application, "_install_booking_core_validation_catalog", original_installer)
    registered = application.register_system(system)
    assert registered.system_id == system.system_id
    assert (application.store.system_root(system.system_id) / "oracles/catalog.yaml").is_file()
    application.tasks.close()
