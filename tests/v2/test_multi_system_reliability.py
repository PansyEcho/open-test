"""验证多系统隔离、可恢复归档、动态扫描器设置和全局任务门禁。"""

from __future__ import annotations

import stat
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.runtime_settings import RuntimeToolSettingsStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.adapters.system_archive import SystemArchiveStore
from opentest.application.foundation import OpenTestApplication
from opentest.application.tasks import LocalTaskManager
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    KnowledgeInvocationContract,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeToolIntentRequest,
    RuntimeToolSettings,
    SourceBaseline,
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


def test_git_system_registration_persists_pin_and_ordinary_actions_cannot_switch_it(
    tmp_path: Path,
) -> None:
    """应用注册应固定Git版本，重启和普通保存沿用pin且普通扫描不能改用HEAD。

    Args:
        tmp_path: pytest隔离的Git源码、知识目录和替代源码路径。

    Returns:
        None；tag、持久化、扫描请求及显式切换边界全部满足时通过。

    Side Effects:
        在临时Git仓库创建两个提交和两个受管tag，并写隔离系统配置。
    """

    source = tmp_path / "refund-source"
    source.mkdir()
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "opentest@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "OpenTest"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "checkout", "-q", "-b", "feature/refund"],
        check=True,
    )
    source_file = source / "RefundFacade.java"
    source_file.write_text("interface RefundFacade { void cancel(); }\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "RefundFacade.java"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "first"], check=True)

    knowledge_root = tmp_path / "knowledge"
    application = OpenTestApplication(knowledge_root)
    registered = application.register_system(
        SystemDefinition(
            system_id="refund-core",
            name="退款核心",
            source_path=str(source),
        )
    )
    first_pin = registered.source_version

    assert first_pin is not None
    assert first_pin.selected_revision == "HEAD"
    assert first_pin.branch_hint == "feature/refund"
    assert application._source_scan_request(
        SourceScanRequest(system_id=registered.system_id)
    ).source_revision == first_pin.managed_tag

    # 用户继续开发后，普通扫描不能把最初选择的HEAD重新解释成当前HEAD。
    source_file.write_text("interface RefundFacade { void cancel(); void query(); }\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "RefundFacade.java"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "second"], check=True)
    second_commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_file.write_text("local edits stay outside the pin\n", encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="does not match the configured source pin"):
        application._source_scan_request(
            SourceScanRequest(system_id=registered.system_id, source_revision="HEAD")
        )

    updated = application.update_system(
        registered.system_id,
        registered.model_copy(update={"name": "退款核心新名称", "source_version": None}),
    )
    assert updated.source_version == first_pin
    other_source = tmp_path / "other-source"
    other_source.mkdir()
    with pytest.raises(KnowledgeValidationError, match="source path cannot change"):
        application.update_system(
            registered.system_id,
            updated.model_copy(update={"source_path": str(other_source)}),
        )

    # 新应用实例必须从source.yaml恢复pin；registry只保留空路由占位而不复制版本真相。
    restarted = OpenTestApplication(knowledge_root)
    assert restarted.store.get_system(registered.system_id).source_version == first_pin
    registry = yaml.safe_load((knowledge_root / "registry/systems.yaml").read_text(encoding="utf-8"))
    assert registry["systems"][0].get("source_version") is None

    explicitly_updated = restarted.update_source_version(registered.system_id, second_commit)
    assert explicitly_updated.source_version is not None
    assert explicitly_updated.source_version.commit == second_commit
    assert explicitly_updated.source_version.managed_tag.endswith(second_commit)
    application.close()
    restarted.close()


def test_legacy_git_system_without_pin_uses_last_complete_baseline_not_current_head(
    tmp_path: Path,
) -> None:
    """升级前Git系统首次普通扫描应固定已发布baseline，不得悄悄采用后来HEAD。

    Args:
        tmp_path: pytest隔离的两提交Git仓库与旧格式知识配置。

    Returns:
        None；兼容迁移创建的pin仍指向旧完整扫描commit时通过。

    Side Effects:
        通过底层store写入无pin历史配置，并在临时源码仓库创建受管tag。
    """

    source = tmp_path / "legacy-source"
    source.mkdir()
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "opentest@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "OpenTest"],
        check=True,
    )
    source_file = source / "RefundFacade.java"
    source_file.write_text("interface RefundFacade { void cancel(); }\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "RefundFacade.java"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "published baseline"], check=True)
    published_commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    knowledge_root = tmp_path / "knowledge"
    store = GitKnowledgeStore(knowledge_root)
    store.register_system(
        SystemDefinition(
            system_id="legacy-refund-core",
            name="历史退款核心",
            source_path=str(source),
            baseline=SourceBaseline(
                source_path=str(source),
                commit=published_commit,
                branch="old-feature",
                revision="HEAD",
                dirty=False,
            ),
        )
    )
    source_file.write_text("interface RefundFacade { void cancel(); void query(); }\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "RefundFacade.java"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "new head"], check=True)

    application = OpenTestApplication(knowledge_root)
    effective = application._source_scan_request(
        SourceScanRequest(system_id="legacy-refund-core")
    )
    migrated = application.store.get_system("legacy-refund-core")

    assert migrated.source_version is not None
    assert migrated.source_version.commit == published_commit
    assert effective.source_revision == f"opentest/baseline/{published_commit}"
    application.close()


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
    listed = archives.list_archives()[0]
    assert listed.archive_id == record.archive_id
    assert listed.integrity_status == "valid"

    restored = archives.restore(record.archive_id)
    counts = SqliteKnowledgeIndex(store.root / ".opentest/index.sqlite").rebuild(store)

    assert restored.system.system_id == first.system_id
    assert [item.system_id for item in store.list_systems()] == [first.system_id, second.system_id]
    assert counts["systems"] == 2
    assert stat.S_IMODE(local_environment.stat().st_mode) == 0o600
    assert preview_path.is_file()
    assert run_path.is_file()
    assert archives.list_archives()[0].integrity_status == "restored"
    assert archives.active_codex_client_handoff_count(record.archive_id) == 0
    with pytest.raises(ScopeViolationError, match="system already exists"):
        archives.restore(record.archive_id)


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


def test_active_handoff_count_ignores_unrelated_corrupt_archive_file(tmp_path: Path) -> None:
    """活动聊天统计不应被无关归档文件损坏阻断，完整恢复仍必须拒绝。

    Args:
        tmp_path: Pytest提供的隔离多系统知识目录。

    Returns:
        None；局部门禁返回零且完整恢复发现摘要错误时通过。
    """

    store, first, _second = _register_two_systems(tmp_path)
    node = KnowledgeNode(
        node_id="facade:FirstFacade#query",
        system_id=first.system_id,
        kind=KnowledgeNodeKind.FACADE,
        title="查询系统一",
    )
    node_path = store.write_node(node, "用于验证无关归档损坏的知识正文")
    archives = SystemArchiveStore(store)
    record = archives.archive(first.system_id, "验证局部门禁与完整恢复的校验边界")
    node_record = next(
        item
        for item in record.files
        if item.scope == "knowledge" and item.relative_path == str(node_path.relative_to(store.root))
    )
    archived_node = (
        archives.knowledge_archive_root
        / record.archive_id
        / "knowledge"
        / node_record.relative_path
    )

    # 模拟与活动聊天统计无关的历史知识文件损坏；不得修复或重算清单摘要。
    archived_node.write_text("corrupt", encoding="utf-8")

    assert archives.active_codex_client_handoff_count(record.archive_id) == 0
    listed = archives.list_archives()[0]
    assert listed.integrity_status == "damaged"
    assert "archive file digest mismatch" in listed.integrity_error
    with pytest.raises(KnowledgeValidationError, match="archive file digest mismatch"):
        archives.restore(record.archive_id)


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


def test_invocation_contract_is_not_searchable_in_normal_knowledge_fts(tmp_path: Path) -> None:
    """接口调用契约中的专用词不得污染普通全文知识检索。

    Args:
        tmp_path: Pytest提供的隔离知识仓库与SQLite索引路径。

    Returns:
        None；正文仍可搜索，而仅存在于调用契约的词无法命中时通过。
    """

    store, first, second = _register_two_systems(tmp_path)
    node = KnowledgeNode(
        node_id="facade:FirstFacade#query",
        system_id=first.system_id,
        kind=KnowledgeNodeKind.FACADE,
        title="查询退票单",
        summary="按业务条件查询退票单。",
        invocation_contract=KnowledgeInvocationContract(
            tool_id="refund-query-list",
            target_id="facade:FirstFacade#query",
            request_type="RefundOrderQueryRequest",
            response_type="RefundOrderPage",
            field_meanings={"secretCapabilityOnly": "只用于工具路由的字段"},
            usage_examples=["secretCapabilityOnly=JulyVoluntaryRefund", "查询7月自愿退退票单"],
        ),
    )
    store.write_node(node, "业务知识正文只解释查询退票单。")
    store.write_node(
        KnowledgeNode(
            node_id="facade:SecondFacade#query",
            system_id=second.system_id,
            kind=KnowledgeNodeKind.FACADE,
            title="另一系统查询",
            invocation_contract=KnowledgeInvocationContract(
                tool_id="refund-query-list",
                target_id="facade:SecondFacade#query",
                usage_examples=["SecondSystemCapability"],
            ),
        ),
        "另一系统的普通业务知识。",
    )
    index = SqliteKnowledgeIndex(store.root / ".opentest/index.sqlite")

    # 重建只把正文、标题与摘要写入普通FTS；结构化契约走独立能力索引。
    index.rebuild(store)

    assert index.search("查询退票单", first.system_id)
    assert index.search("JulyVoluntaryRefund", first.system_id) == []
    application = OpenTestApplication(store.root)

    # 只有显式工具意图路由读取独立能力索引；它只返回契约与合并澄清项，不执行真实接口。
    routed = application.resolve_knowledge_tool_intent(
        first.system_id,
        KnowledgeToolIntentRequest(query="查询7月自愿退退票单", intent="query"),
    )

    assert routed["matches"][0]["tool_id"] == "refund-query-list"
    assert routed["matches"][0]["node_id"] == node.node_id
    assert routed["clarifications"] == ["请确认日期指创建、申请、出发还是更新时间"]
    assert routed["executed"] is False


def test_runtime_prompt_and_codex_speed_settings_persist_with_0600(tmp_path: Path) -> None:
    """全局Prompt与Sol档位必须在本地0600设置中完整保存。

    Args:
        tmp_path: Pytest提供的隔离本地设置目录。

    Returns:
        None；模板、模型、档位与文件权限刷新后保持一致时通过。
    """

    store = RuntimeToolSettingsStore(tmp_path / ".opentest/settings.yaml")
    saved = store.write(
        RuntimeToolSettings(
            knowledge_agent="codex",
            codex_model="gpt-5.6-sol",
            codex_reasoning_effort="low",
            case_template_v4_model="company-case-model",
            case_template_v4_reasoning_effort="high",
            knowledge_agent_prompt_template="分析 {{target_id}} 的完整业务知识。",
        )
    )

    assert saved.codex_reasoning_effort == "low"
    assert store.read().case_template_v4_model == "company-case-model"
    assert store.read().case_template_v4_reasoning_effort == "high"
    assert store.read().knowledge_agent_prompt_template == "分析 {{target_id}} 的完整业务知识。"
    assert stat.S_IMODE(store.settings_path.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="unsupported knowledge prompt placeholder"):
        RuntimeToolSettings(
            knowledge_agent_prompt_template="分析 {{target_id}}，并保留 {{target-id}}。"
        )


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


def test_generic_dsf_scan_ignores_legacy_facade_gateway(tmp_path: Path) -> None:
    """普通DSF扫描不得再消费本地或请求中的旧Facade HTTP网关。

    Args:
        tmp_path: Pytest隔离的源码、知识与本地系统设置目录。

    Returns:
        None；只有资源环境按优先级生效，Facade前缀始终清空时通过。

    Side Effects:
        在隔离知识根写入系统和0600本地设置，不启动源码扫描。
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
        "test",
    )

    local_request = application._source_scan_request(
        SourceScanRequest(system_id="ifightchainsaas.java.refund.core"),
    )
    explicit_request = application._source_scan_request(
        SourceScanRequest(
            system_id="ifightchainsaas.java.refund.core",
            facade_http_prefix="https://explicit.qa.example/refund/v2/",
            resource_config_environment="uat",
        ),
    )

    assert local_request.facade_http_prefix == ""
    assert local_request.resource_config_environment == "test"
    assert explicit_request.facade_http_prefix == ""
    assert explicit_request.resource_config_environment == "uat"
    assert "must-not-enter-scan-request" not in local_request.model_dump_json()
    application.close()


def test_prepared_scan_freezes_environment_before_background_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """准备型扫描入队后修改本地设置不得改变该任务的资源环境。

    Args:
        tmp_path: Pytest隔离源码、知识和本地设置目录。
        monkeypatch: 替换扫描及派生阶段，避免启动外部分析器。

    Returns:
        None；后台扫描收到准备阶段冻结的test环境时通过。

    Side Effects:
        创建并完成一个本地后台任务，不访问QA或真实源码分析器。
    """

    source = tmp_path / "prepared-environment-source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    system = application.register_system(
        SystemDefinition(
            system_id="prepared-environment-system",
            name="准备型环境系统",
            source_path=str(source),
        )
    )
    scan_started = threading.Event()
    release_scan = threading.Event()
    captured_environments: list[str] = []
    manifest = MagicMock(
        scan_id="scan-prepared-environment",
        entries=[],
        tools=[],
        state_machines=[],
    )

    def analyze(frozen_request: SourceScanRequest):
        """记录任务冻结值并等待测试修改全局设置。

        Args:
            frozen_request: 准备阶段已补齐网关和资源环境的扫描请求。

        Returns:
            满足任务摘要读取的最小Manifest替身。

        Side Effects:
            同步测试线程并记录资源环境。
        """

        captured_environments.append(frozen_request.resource_config_environment)
        scan_started.set()
        assert release_scan.wait(timeout=5)
        return manifest

    monkeypatch.setattr(application.source_analysis, "analyze", analyze)
    # 测试替身不依赖生产scriptgen设置，避免后台任务在进入冻结值断言前执行环境诊断。
    application.source_analysis.scriptgen = MagicMock()
    monkeypatch.setattr(
        application.knowledge_discovery,
        "discover",
        MagicMock(return_value=MagicMock(candidates=[])),
    )
    monkeypatch.setattr(application, "rebuild_index", MagicMock(return_value={}))
    task = application.submit_prepared_source_scan(
        SourceScanRequest(system_id=system.system_id),
        lambda: application.prepare_system_update(
            system.system_id,
            system,
            "prepared-token",
            "http://servicegw.qa.example/prepared/v2",
            "test",
        ),
    )
    assert scan_started.wait(timeout=5)

    # 模拟任务排队或执行期间页面切换到uat；当前任务仍只能使用入队前冻结的test。
    application.save_local_settings(
        system.system_id,
        "prepared-token",
        resource_config_environment="uat",
    )
    release_scan.set()
    deadline = time.monotonic() + 5
    while application.get_task(task.task_id).status not in {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    } and time.monotonic() < deadline:
        time.sleep(0.01)

    assert application.get_task(task.task_id).status == TaskStatus.COMPLETED
    assert captured_environments == ["test"]
    application.close()


def test_http_job_scan_blocks_before_scriptgen_when_gateway_is_missing(tmp_path: Path) -> None:
    """保留的HTTP Job扫描缺少专用网关时应在scriptgen启动前失败。

    Args:
        tmp_path: Pytest隔离的源码和知识目录。
    """

    system_id = "travelsystem.java.dsf.supplychain.booking.core"
    source = tmp_path / system_id
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(system_id=system_id, name="缺少Job网关", source_path=str(source)),
    )

    with pytest.raises(KnowledgeValidationError, match="HTTP Job"):
        application._source_scan_request(SourceScanRequest(system_id=system_id))

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
def test_http_job_scan_rejects_gateway_that_cannot_be_used_as_base_url(
    tmp_path: Path,
    gateway_prefix: str,
) -> None:
    """HTTP Job的畸形网关必须稳定转换为可操作配置错误。

    Args:
        tmp_path: Pytest隔离的源码和知识目录。
        gateway_prefix: 不能安全追加Facade接口后缀的网关输入。
    """

    system_id = "travelsystem.java.dsf.supplychain.booking.core"
    source = tmp_path / system_id
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(system_id=system_id, name="非法Job网关", source_path=str(source)),
    )

    # 所有畸形输入都应在scriptgen启动前收敛为同一领域错误，避免泄漏urllib实现异常。
    with pytest.raises(KnowledgeValidationError, match="HTTP Job"):
        application._source_scan_request(
            SourceScanRequest(
                system_id=system_id,
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
                "test",
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
    original_installer = application._install_validation_catalog

    def fail_catalog_install(_system_id: str) -> None:
        """模拟固定目录资产在系统骨架创建后无法安装。"""

        raise RuntimeError("catalog installation failed")

    monkeypatch.setattr(application, "_install_validation_catalog", fail_catalog_install)
    with pytest.raises(RuntimeError, match="catalog installation failed"):
        application.register_system(system)

    assert application.store.list_systems() == []
    assert not application.store.system_root(system.system_id).exists()

    # 恢复真实安装器后，同一稳定ID必须能够重新注册并得到校验目录。
    monkeypatch.setattr(application, "_install_validation_catalog", original_installer)
    registered = application.register_system(system)
    assert registered.system_id == system.system_id
    assert (application.store.system_root(system.system_id) / "oracles/catalog.yaml").is_file()
    application.tasks.close()
