"""验证单系统源码基线、真实manifest解析、Java结构扫描和产物编排。"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.source_analysis import (
    GitSourceRepository,
    JavaStructureScanner,
    ScriptgenConfig,
    ScriptgenSourceScanner,
    SourceScanArtifactStore,
)
from opentest.application.source_analysis import SourceAnalysisService
from opentest.application.foundation import OpenTestApplication
from opentest.cli import dispatch
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.models import (
    EntryPoint,
    KnowledgeNodeKind,
    SemanticAnalysisResult,
    SemanticCallEdge,
    SemanticMethodDefinition,
    SemanticResolutionStatus,
    SourceBaseline,
    SourceReference,
    SourceScanRequest,
    StateMachineDefinition,
    StateTransition,
    SystemDefinition,
    ToolDefinition,
)


def _run_git(repository: Path, *arguments: str) -> None:
    """在临时仓库执行测试所需Git命令并要求成功。"""

    subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True, text=True)


def _write_scriptgen_output(output_dir: Path, source_root: Path, include_platform_shim: bool = False) -> None:
    """写入与真实scriptgen契约一致且源码证据位于注册根内的最小产物。

    Args:
        output_dir: 待创建的隔离工具和 `_meta` 目录。
        source_root: 待创建的Facade与Job证据源码根。
        include_platform_shim: 是否额外注入必须被拒绝的固定shim。

    Side Effects:
        创建测试源码、脚本、scan manifest和tool manifest。
    """

    metadata_root = output_dir / "_meta"
    facade_script = output_dir / "facade" / "trade" / "create-order-raw.sh"
    job_script = output_dir / "jobs" / "http" / "job" / "cancel-order.sh"
    metadata_root.mkdir(parents=True)
    source_root.mkdir(parents=True, exist_ok=True)
    facade_source = source_root / "TradeFacade.java"
    job_source = source_root / "CancelOrderJob.java"
    facade_source.write_text("interface TradeFacade {}\n", encoding="utf-8")
    job_source.write_text("class CancelOrderJob {}\n", encoding="utf-8")
    facade_script.parent.mkdir(parents=True)
    job_script.parent.mkdir(parents=True)
    facade_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    job_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    scan_manifest = {
        "success": True,
        "manifest_version": "v1",
        "facades": [
            {
                "facade_id": "com.example.TradeFacade#createOrder",
                "interface_name": "TradeFacade",
                "method_name": "createOrder",
                "source_path": str(facade_source),
                "request_type": "CreateOrderRequest",
                "response_type": "CreateOrderResponse",
                "base_path": "trade",
                "method_path": "createOrder",
                "required_fields": ["passengers"],
                "request_template": {"passengers": []},
            }
        ],
        "jobs": [
            {
                "job_id": "com.example.CancelOrderJob",
                "class_name": "CancelOrderJob",
                "job_name": "取消订单",
                "job_code": "CANCEL_ORDER",
                "source_path": str(job_source),
            }
        ],
        "warnings": [],
    }
    generated_tools = [
        {
            "tool_id": "facade_raw.trade.createOrder",
            "tool_type": "facade_raw",
            "display_name": "trade / createOrder",
            "source_id": "com.example.TradeFacade#createOrder",
            "script_rel_path": "facade/trade/create-order-raw.sh",
            "status": "ready",
        },
        {
            "tool_id": "job_http_trigger.job.CANCEL_ORDER",
            "tool_type": "job_http_trigger",
            "display_name": "job / CANCEL_ORDER",
            "source_id": "com.example.CancelOrderJob",
            "script_rel_path": "jobs/http/job/cancel-order.sh",
            "status": "ready",
        },
    ]
    if include_platform_shim:
        shim = output_dir / "platform" / "create-order.sh"
        shim.parent.mkdir()
        shim.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        generated_tools.append(
            {
                "tool_id": "facade_raw.platform.createOrder",
                "tool_type": "facade_raw",
                "display_name": "fixed shim",
                "source_id": "fixed#createOrder",
                "script_rel_path": "platform/create-order.sh",
                "status": "ready",
            }
        )
    (metadata_root / "scan-manifest.json").write_text(json.dumps(scan_manifest), encoding="utf-8")
    (metadata_root / "tool-manifest.json").write_text(
        json.dumps({"success": True, "generated_tools": generated_tools, "warnings": []}),
        encoding="utf-8",
    )


class FakeScriptgenScanner:
    """为应用编排测试提供不启动外部进程的结构化扫描替身。"""

    def scan(
        self,
        request: SourceScanRequest,
        source_path: Path,
        output_dir: Path,
    ) -> tuple[list[EntryPoint], list[ToolDefinition], list[str]]:
        """创建隔离工具目录并返回一个可追溯Facade和真实工具。

        Args:
            request: 提供一期系统ID的扫描请求。
            source_path: 已由应用基线确认的测试源码根。
            output_dir: 本轮唯一工具目录。

        Returns:
            单个Facade入口、对应工具和空warning。

        Side Effects:
            创建最小可执行脚本，模拟真实scriptgen产物。
        """

        output_dir.mkdir(parents=True)
        script = output_dir / "facade" / "trade" / "create-order.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        source_file = source_path / "TradeFacade.java"
        source_id = "TradeFacade#createOrder"
        tool = ToolDefinition(
            tool_id="facade.trade.create_order",
            system_id=request.system_id,
            display_name="创建订单",
            script_path=str(script),
            source_id=source_id,
        )
        entry = EntryPoint(
            entry_id=f"facade:{source_id}",
            system_id=request.system_id,
            kind=KnowledgeNodeKind.FACADE,
            display_name=source_id,
            source_id=source_id,
            source_path=str(source_file),
            tool_id=tool.tool_id,
            script_path=tool.script_path,
        )
        return [entry], [tool], []


class ChangingBaselineRepository:
    """依次返回两个不同基线，用于模拟扫描期间源码被用户修改。"""

    def __init__(self, source_path: Path):
        """为同一路径准备扫描前后不同的dirty摘要。"""

        self.baselines = [
            SourceBaseline(source_path=str(source_path), dirty=True, dirty_digest="before"),
            SourceBaseline(source_path=str(source_path), dirty=True, dirty_digest="after"),
        ]

    def capture(self, _: Path | str) -> SourceBaseline:
        """返回下一个预设基线，超过两次调用时保持最后状态。"""

        if len(self.baselines) > 1:
            return self.baselines.pop(0)
        return self.baselines[0]

    def capture_revision(
        self,
        source_path: Path | str,
        revision: str = "",
    ) -> SourceBaseline:
        """兼容新版扫描入口并继续模拟非Git目录前后变化。

        Args:
            source_path: 测试源码目录；由``capture``忽略其具体值。
            revision: 测试未选择Git revision，保留参数以匹配生产接口。

        Returns:
            ``capture``队列中的下一项预设基线。
        """

        del revision
        return self.capture(source_path)


class FailingGitRepository(GitSourceRepository):
    """模拟Git因权限而非非仓库原因失败的基线捕获器。"""

    def _run_git(self, source: Path, *arguments: str, text: bool) -> subprocess.CompletedProcess[object]:
        """返回权限失败，验证调用方不会把它误判为普通目录。"""

        output: object = "" if text else b""
        error: object = "permission denied" if text else b"permission denied"
        return subprocess.CompletedProcess(["git", "-C", str(source), *arguments], 1, output, error)


class ConcurrentFakeScriptgenScanner(FakeScriptgenScanner):
    """记录同时进入scan的数量，用于验证应用发布锁覆盖完整扫描。"""

    def __init__(self):
        """初始化线程安全的活动调用计数。"""

        self._lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def scan(
        self,
        request: SourceScanRequest,
        source_path: Path,
        output_dir: Path,
    ) -> tuple[list[EntryPoint], list[ToolDefinition], list[str]]:
        """短暂保持活动状态并委托父类生成隔离工具。"""

        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            # 留出另一线程竞争窗口；业务代码的扫描锁应使其无法同时进入本方法。
            time.sleep(0.03)
            return super().scan(request, source_path, output_dir)
        finally:
            with self._lock:
                self.active -= 1


def test_git_baseline_changes_with_tracked_and_untracked_content(tmp_path: Path) -> None:
    """Git基线应区分干净commit、已跟踪修改和未跟踪文件内容变化。"""

    repository = tmp_path / "repository"
    repository.mkdir()
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.email", "opentest@example.invalid")
    _run_git(repository, "config", "user.name", "OpenTest")
    source_file = repository / "TradeFacade.java"
    source_file.write_text("class TradeFacade {}\n", encoding="utf-8")
    _run_git(repository, "add", "TradeFacade.java")
    _run_git(repository, "commit", "-q", "-m", "baseline")

    scanner = GitSourceRepository()
    clean = scanner.capture(repository)
    assert clean.commit
    assert clean.dirty is False
    assert clean.dirty_digest == ""

    source_file.write_text("class TradeFacade { void createOrder() {} }\n", encoding="utf-8")
    dirty = scanner.capture(repository)
    assert dirty.dirty is True
    assert dirty.dirty_digest

    untracked = repository / "CreateOrderRequest.java"
    untracked.write_text("class CreateOrderRequest {}\n", encoding="utf-8")
    with_untracked = scanner.capture(repository)
    assert with_untracked.dirty_digest != dirty.dirty_digest


def test_non_git_baseline_uses_directory_digest(tmp_path: Path) -> None:
    """普通源码目录应以内容摘要建立显式dirty基线而不是伪造Git commit。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "TradeFacade.java").write_text("class TradeFacade {}\n", encoding="utf-8")
    baseline = GitSourceRepository().capture(source)
    assert baseline.commit == ""
    assert baseline.branch == ""
    assert baseline.dirty is True
    assert baseline.dirty_digest


def test_git_revision_snapshot_ignores_working_tree_changes(tmp_path: Path) -> None:
    """Git扫描应按branch/tag/commit展开快照且不读取后续working tree修改。

    Args:
        tmp_path: pytest隔离的Git仓库和知识缓存目录。

    Returns:
        None；tag固定旧提交、HEAD固定新提交且两个快照内容都不随工作区变化。

    Side Effects:
        在临时目录创建Git提交、tag和OpenTest托管源码快照。
    """

    repository = tmp_path / "repository"
    repository.mkdir()
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.email", "opentest@example.invalid")
    _run_git(repository, "config", "user.name", "OpenTest")
    source_file = repository / "TradeFacade.java"
    source_file.write_text("class TradeFacade { int version = 1; }\n", encoding="utf-8")
    _run_git(repository, "add", "TradeFacade.java")
    _run_git(repository, "commit", "-q", "-m", "version one")
    _run_git(repository, "tag", "case-baseline-v1")
    # 保存tag应固定的真实提交，避免仅比较文件内容而漏掉revision解析错误。
    first_commit_process = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    first_commit = first_commit_process.stdout.strip()

    source_file.write_text("class TradeFacade { int version = 2; }\n", encoding="utf-8")
    _run_git(repository, "add", "TradeFacade.java")
    _run_git(repository, "commit", "-q", "-m", "version two")
    source_file.write_text("class TradeFacade { int version = 3; }\n", encoding="utf-8")

    source_repository = GitSourceRepository()
    artifacts = SourceScanArtifactStore(tmp_path / "knowledge")
    tagged = source_repository.capture_revision(repository, "case-baseline-v1")
    current = source_repository.capture_revision(repository)
    tagged_snapshot = source_repository.materialize_revision(
        tagged,
        artifacts.source_snapshot_path("train-booking-core", tagged.commit),
        artifacts.source_snapshot_root,
    )
    current_snapshot = source_repository.materialize_revision(
        current,
        artifacts.source_snapshot_path("train-booking-core", current.commit),
        artifacts.source_snapshot_root,
    )

    assert tagged.commit == first_commit
    assert tagged.revision == "case-baseline-v1"
    assert tagged.dirty is False
    assert current.revision == "HEAD"
    assert "version = 1" in (tagged_snapshot / "TradeFacade.java").read_text(encoding="utf-8")
    assert "version = 2" in (current_snapshot / "TradeFacade.java").read_text(encoding="utf-8")
    assert "version = 3" in source_file.read_text(encoding="utf-8")


def test_git_revision_snapshot_rejects_prebuilt_empty_directory(tmp_path: Path) -> None:
    """预建空目录不能冒充一个已经完整展开的commit快照。

    Args:
        tmp_path: pytest隔离的Git仓库、托管快照根和伪造目录。

    Returns:
        None；缺少原子发布完成标记的目录被拒绝时通过。

    Side Effects:
        在临时目录创建Git提交和一个不可信的预建快照目录。
    """

    repository = tmp_path / "source"
    repository.mkdir()
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.email", "opentest@example.invalid")
    _run_git(repository, "config", "user.name", "OpenTest")
    (repository / "TradeFacade.java").write_text("interface TradeFacade {}\n", encoding="utf-8")
    _run_git(repository, "add", "TradeFacade.java")
    _run_git(repository, "commit", "-q", "-m", "source")

    source_repository = GitSourceRepository()
    artifacts = SourceScanArtifactStore(tmp_path / "knowledge")
    baseline = source_repository.capture_revision(repository)
    snapshot_path = artifacts.source_snapshot_path("train-booking-core", baseline.commit)
    # 模拟外部进程抢先创建同名空目录；仅凭is_dir不得把它当成commit内容。
    snapshot_path.mkdir(parents=True)

    with pytest.raises(KnowledgeValidationError, match="completion marker"):
        source_repository.materialize_revision(
            baseline,
            snapshot_path,
            artifacts.source_snapshot_root,
        )


def test_git_revision_snapshot_rejects_symlink_target(tmp_path: Path) -> None:
    """托管快照目标为符号链接时不得跟随到OpenTest目录之外。

    Args:
        tmp_path: pytest隔离的Git仓库、托管快照根和外部伪造目录。

    Returns:
        None；快照路径符号链接被归属门禁拒绝时通过。

    Side Effects:
        在临时目录创建Git提交、外部目录和指向该目录的符号链接。
    """

    repository = tmp_path / "source"
    repository.mkdir()
    _run_git(repository, "init", "-q")
    _run_git(repository, "config", "user.email", "opentest@example.invalid")
    _run_git(repository, "config", "user.name", "OpenTest")
    (repository / "TradeFacade.java").write_text("interface TradeFacade {}\n", encoding="utf-8")
    _run_git(repository, "add", "TradeFacade.java")
    _run_git(repository, "commit", "-q", "-m", "source")

    source_repository = GitSourceRepository()
    artifacts = SourceScanArtifactStore(tmp_path / "knowledge")
    baseline = source_repository.capture_revision(repository)
    snapshot_path = artifacts.source_snapshot_path("train-booking-core", baseline.commit)
    external_source = tmp_path / "forged-source"
    external_source.mkdir()
    (external_source / "Wrong.java").write_text("class Wrong {}\n", encoding="utf-8")
    snapshot_path.parent.mkdir(parents=True)
    # 复现审查发现的逃逸：canonical system/commit路径实际指向不受控目录。
    snapshot_path.symlink_to(external_source, target_is_directory=True)

    with pytest.raises(KnowledgeValidationError, match="symbolic links"):
        source_repository.materialize_revision(
            baseline,
            snapshot_path,
            artifacts.source_snapshot_root,
        )


def test_git_operational_failure_is_not_treated_as_non_git_directory(tmp_path: Path) -> None:
    """Git权限或超时类错误必须中止扫描，不能生成看似正常的目录基线。"""

    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(KnowledgeValidationError, match="permission denied"):
        FailingGitRepository().capture(source)


def test_git_detection_forces_stable_c_locale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git子进程必须固定C locale，使非仓库分类不受用户系统语言影响。"""

    source = tmp_path / "source"
    source.mkdir()
    observed_environment: dict[str, str] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """记录Git环境并返回C locale下的标准非仓库错误。"""

        environment = kwargs.get("env")
        if isinstance(environment, dict):
            observed_environment.update({str(key): str(value) for key, value in environment.items()})
        return subprocess.CompletedProcess(command, 128, "", "fatal: not a git repository")

    monkeypatch.setattr(subprocess, "run", fake_run)
    baseline = GitSourceRepository().capture(source)
    assert baseline.dirty is True
    assert observed_environment["LC_ALL"] == "C"
    assert observed_environment["LANG"] == "C"


def test_scriptgen_manifest_maps_real_tools_without_shims(tmp_path: Path) -> None:
    """manifest解析应一一映射Facade/Job工具并生成稳定逻辑ID。"""

    output_dir = tmp_path / "tools"
    source_root = tmp_path / "source"
    _write_scriptgen_output(output_dir, source_root)
    scanner = ScriptgenSourceScanner(ScriptgenConfig.from_value(None))
    entries, tools, warnings = scanner.parse_output("train-booking-core", source_root, output_dir)

    assert warnings == []
    assert [tool.tool_id for tool in tools] == ["facade.trade.create_order", "job.cancel_order"]
    assert {entry.kind for entry in entries} == {KnowledgeNodeKind.FACADE, KnowledgeNodeKind.JOB}
    facade = next(entry for entry in entries if entry.kind == KnowledgeNodeKind.FACADE)
    assert facade.source_id == "com.example.TradeFacade#createOrder"
    assert facade.request_type == "CreateOrderRequest"
    assert facade.tool_id == "facade.trade.create_order"
    assert all("platform" not in Path(tool.script_path).parts for tool in tools)


def test_scriptgen_manifest_rejects_fixed_platform_shim(tmp_path: Path) -> None:
    """任何 `platform/*` 固定脚本都不得进入V2真实工具集合。"""

    output_dir = tmp_path / "tools"
    source_root = tmp_path / "source"
    _write_scriptgen_output(output_dir, source_root, include_platform_shim=True)
    scanner = ScriptgenSourceScanner(ScriptgenConfig.from_value(None))
    with pytest.raises(KnowledgeValidationError, match="fixed shim"):
        scanner.parse_output("train-booking-core", source_root, output_dir)


@pytest.mark.parametrize(
    ("manifest_name", "field", "value", "message"),
    [
        ("scan-manifest.json", "success", False, "unsuccessful"),
        ("tool-manifest.json", "success", False, "unsuccessful"),
        ("scan-manifest.json", "manifest_version", "v99", "unsupported"),
    ],
)
def test_scriptgen_manifest_rejects_failure_and_unknown_version(
    tmp_path: Path,
    manifest_name: str,
    field: str,
    value: object,
    message: str,
) -> None:
    """返回码为0也不得接收内部失败标志或未知scan manifest版本。

    五个测试参数分别表示隔离目录、目标manifest、待破坏字段、值和期望错误，属于同一契约变体。
    """

    output_dir = tmp_path / "tools"
    source_root = tmp_path / "source"
    _write_scriptgen_output(output_dir, source_root)
    manifest_path = output_dir / "_meta" / manifest_name
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload[field] = value
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    scanner = ScriptgenSourceScanner(ScriptgenConfig.from_value(None))
    with pytest.raises(KnowledgeValidationError, match=message):
        scanner.parse_output("train-booking-core", source_root, output_dir)


def test_scriptgen_manifest_rejects_duplicate_and_incomplete_mapping(tmp_path: Path) -> None:
    """工具身份重复或scan/tool source集合不一致时不得静默覆盖或发布。"""

    output_dir = tmp_path / "tools"
    source_root = tmp_path / "source"
    _write_scriptgen_output(output_dir, source_root)
    tool_path = output_dir / "_meta" / "tool-manifest.json"
    payload = json.loads(tool_path.read_text(encoding="utf-8"))
    payload["generated_tools"].append(dict(payload["generated_tools"][0]))
    tool_path.write_text(json.dumps(payload), encoding="utf-8")
    scanner = ScriptgenSourceScanner(ScriptgenConfig.from_value(None))
    with pytest.raises(KnowledgeValidationError, match="duplicate"):
        scanner.parse_output("train-booking-core", source_root, output_dir)

    payload["generated_tools"] = payload["generated_tools"][:1]
    tool_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="one-to-one"):
        scanner.parse_output("train-booking-core", source_root, output_dir)


def test_scriptgen_manifest_rejects_source_evidence_outside_registered_root(tmp_path: Path) -> None:
    """scriptgen返回其他项目或系统文件时必须阻止后续知识生成越界读取。"""

    output_dir = tmp_path / "tools"
    source_root = tmp_path / "source"
    outside = tmp_path / "outside.java"
    outside.write_text("interface Outside {}\n", encoding="utf-8")
    _write_scriptgen_output(output_dir, source_root)
    scan_path = output_dir / "_meta" / "scan-manifest.json"
    payload = json.loads(scan_path.read_text(encoding="utf-8"))
    payload["facades"][0]["source_path"] = str(outside)
    scan_path.write_text(json.dumps(payload), encoding="utf-8")

    scanner = ScriptgenSourceScanner(ScriptgenConfig.from_value(None))
    with pytest.raises(KnowledgeValidationError, match="escapes registered root"):
        scanner.parse_output("train-booking-core", source_root, output_dir)


def test_scriptgen_manifest_rejects_swapped_tool_type_and_empty_logical_id(tmp_path: Path) -> None:
    """入口必须绑定语义匹配的工具类型，原始ID也必须能规范为非空逻辑ID。"""

    output_dir = tmp_path / "tools"
    source_root = tmp_path / "source"
    _write_scriptgen_output(output_dir, source_root)
    tool_path = output_dir / "_meta" / "tool-manifest.json"
    payload = json.loads(tool_path.read_text(encoding="utf-8"))
    payload["generated_tools"][0]["tool_type"] = "job_http_trigger"
    tool_path.write_text(json.dumps(payload), encoding="utf-8")
    scanner = ScriptgenSourceScanner(ScriptgenConfig.from_value(None))
    with pytest.raises(KnowledgeValidationError, match="non-facade"):
        scanner.parse_output("train-booking-core", source_root, output_dir)

    payload["generated_tools"][0]["tool_type"] = "facade_raw"
    payload["generated_tools"][0]["tool_id"] = "..."
    tool_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="empty logical"):
        scanner.parse_output("train-booking-core", source_root, output_dir)


def test_java_structure_scanner_finds_state_machine_and_mq_consumer(tmp_path: Path) -> None:
    """Java扫描应区分状态转换和可触发MQ Consumer入口。"""

    source = tmp_path / "source"
    java_root = source / "module" / "src" / "main" / "java"
    actor = java_root / "app" / "actor" / "pre" / "TicketingPreActor.java"
    consumer = java_root / "app" / "mq" / "consumer" / "OrderConsumer.java"
    actor.parent.mkdir(parents=True)
    consumer.parent.mkdir(parents=True)
    actor.write_text(
        """
        package com.example.actor;
        @State(from = { OrderStateEnum.INIT }, to = { OrderStateEnum.TICKETING })
        public class TicketingPreActor {}
        """,
        encoding="utf-8",
    )
    consumer.write_text(
        """
        package com.example.mq;
        import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
        @RocketMQMessageListener(topic = "order-events", consumerGroup = "booking")
        public class OrderConsumer {
            public void onMessage(String payload) {}
        }
        """,
        encoding="utf-8",
    )

    mq_entries, machines, warnings = JavaStructureScanner().scan("train-booking-core", source)
    assert warnings == []
    assert mq_entries[0].source_id == "com.example.mq.OrderConsumer#onMessage"
    assert mq_entries[0].metadata["destinations"] == ["order-events"]
    assert machines[0].state_enum == "OrderStateEnum"
    assert machines[0].transitions[0].from_states == ["INIT"]
    assert machines[0].transitions[0].to_states == ["TICKETING"]
    assert machines[0].transitions[0].phase == "pre"


def test_java_structure_scanner_ignores_state_text_in_exception_message(tmp_path: Path) -> None:
    """日志或异常字符串中的 `@State` 提示不得被误报为损坏注解。"""

    source = tmp_path / "source"
    java_root = source / "src" / "main" / "java"
    java_root.mkdir(parents=True)
    framework = java_root / "AbstractStateQueue.java"
    framework.write_text(
        'abstract class AbstractStateQueue { String hint = "place annotation @State on service"; }\n',
        encoding="utf-8",
    )

    mq_entries, machines, warnings = JavaStructureScanner().scan("train-booking-core", source)
    assert mq_entries == []
    assert machines == []
    assert warnings == []


def test_java_structure_scanner_maps_multiple_arbitrary_listener_methods(tmp_path: Path) -> None:
    """方法级监听注解应按实际方法逐个建入口并忽略consumerGroup等非目的地值。"""

    source = tmp_path / "source"
    java_root = source / "src" / "main" / "java"
    java_root.mkdir(parents=True)
    consumer = java_root / "MultiConsumer.java"
    consumer.write_text(
        """
        package com.example.mq;
        import org.springframework.kafka.annotation.KafkaListener;
        import org.springframework.amqp.rabbit.annotation.RabbitListener;
        public class MultiConsumer {
            @KafkaListener(topics = {"created", "changed"}, groupId = "booking")
            public void handleOrderEvent(String payload) {}

            @RabbitListener(queues = "refund")
            public boolean processRefund(String payload) { return true; }
        }
        """,
        encoding="utf-8",
    )

    entries, machines, warnings = JavaStructureScanner().scan("train-booking-core", source)
    assert machines == []
    assert warnings == []
    assert [entry.display_name for entry in entries] == [
        "MultiConsumer#handleOrderEvent",
        "MultiConsumer#processRefund",
    ]
    assert entries[0].metadata["destinations"] == ["created", "changed"]
    assert entries[1].metadata["destinations"] == ["refund"]


def test_semantic_reuse_counts_distinct_state_transition_owners(tmp_path: Path) -> None:
    """公共方法复用数应同时包含代码入口和独立状态流转所有者。

    Args:
        tmp_path: pytest隔离的知识根。

    Returns:
        None；公共方法所有者合并一个入口和两条流转时通过。
    """

    store = GitKnowledgeStore(tmp_path / "knowledge")
    service = SourceAnalysisService(
        store,
        SourceScanArtifactStore(store.root),
        FakeScriptgenScanner(),  # type: ignore[arg-type]
    )
    actor_reference = SourceReference(
        path="src/RefundCancelActor.java",
        symbol="demo.RefundCancelActor#execute(java.lang.Object)",
        line=20,
    )
    shared_reference = SourceReference(
        path="src/SharedRefundRules.java",
        symbol="demo.SharedRefundRules#evaluate(java.lang.Object)",
        line=12,
    )
    actor_method = SemanticMethodDefinition(
        symbol_id=actor_reference.symbol,
        qualified_class_name="demo.RefundCancelActor",
        method_name="execute",
        parameter_qualified_types=["java.lang.Object"],
        source_ref=actor_reference,
    )
    helper_reference = SourceReference(
        path="src/RefundCancelActor.java",
        symbol="demo.RefundCancelActor#validate(java.lang.Object)",
        line=5,
    )
    helper_method = SemanticMethodDefinition(
        symbol_id=helper_reference.symbol,
        qualified_class_name="demo.RefundCancelActor",
        method_name="validate",
        parameter_qualified_types=["java.lang.Object"],
        source_ref=helper_reference,
    )
    shared_method = SemanticMethodDefinition(
        symbol_id=shared_reference.symbol,
        qualified_class_name="demo.SharedRefundRules",
        method_name="evaluate",
        parameter_qualified_types=["java.lang.Object"],
        source_ref=shared_reference,
        entry_point_ids=["demo.RefundFacadeImpl#cancel(java.lang.Object)"],
        reuse_entry_count=1,
    )
    semantic = SemanticAnalysisResult(
        system_id="refund-core",
        methods=[helper_method, actor_method, shared_method],
        call_edges=[
            SemanticCallEdge(
                caller_symbol_id=actor_method.symbol_id,
                callee_symbol_id=shared_method.symbol_id,
                callee_expression="evaluate",
                source_ref=actor_reference,
                resolution_status=SemanticResolutionStatus.RESOLVED,
            )
        ],
    )
    transitions = [
        StateTransition(
            transition_id=f"transition:refund-cancel:{index}",
            actor="RefundCancelActor",
            from_states=[from_state],
            to_states=["REFUND_CANCEL"],
            source_ref=actor_reference.model_copy(update={"symbol": "RefundCancelActor"}),
        )
        for index, from_state in enumerate(["WAIT_REFUND", "REFUND_FAIL"], start=1)
    ]
    enriched = service._enrich_semantic_knowledge_owners(
        [
            StateMachineDefinition(
                machine_id="state-machine:refund",
                system_id="refund-core",
                state_enum="RefundState",
                title="退票状态机",
                transitions=transitions,
            )
        ],
        semantic,
    )
    shared = next(method for method in enriched.methods if method.symbol_id == shared_method.symbol_id)

    assert shared.reuse_entry_count == 3
    assert shared.entry_point_ids == [
        "demo.RefundFacadeImpl#cancel(java.lang.Object)",
        "transition:refund-cancel:1",
        "transition:refund-cancel:2",
    ]


def test_source_analysis_persists_manifest_and_updates_baseline(tmp_path: Path) -> None:
    """应用编排成功后应同时发布本地manifest和Git source baseline。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "TradeFacade.java").write_text("class TradeFacade {}\n", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    artifacts = SourceScanArtifactStore(store.root)
    service = SourceAnalysisService(store, artifacts, FakeScriptgenScanner())  # type: ignore[arg-type]

    manifest = service.analyze(SourceScanRequest(system_id="train-booking-core"))
    restored = service.get_manifest("train-booking-core", manifest.scan_id)
    latest = service.get_manifest("train-booking-core")
    updated_system = store.get_system("train-booking-core")

    assert restored == manifest
    assert latest.scan_id == manifest.scan_id
    assert updated_system.baseline == manifest.baseline
    assert manifest.entries[0].source_id == "TradeFacade#createOrder"
    assert manifest.tools[0].script_path.startswith(manifest.tool_root)


def test_source_analysis_scans_selected_commit_instead_of_dirty_working_tree(
    tmp_path: Path,
) -> None:
    """Git源码扫描应固定HEAD commit并让全部扫描器读取托管快照。

    Args:
        tmp_path: pytest隔离的Git源码仓库、知识根和扫描产物目录。

    Returns:
        None；Manifest绑定commit快照且入口证据未读取未提交改动时通过。

    Side Effects:
        在临时Git仓库创建一次提交和未提交修改，并发布一份扫描Manifest。
    """

    source = tmp_path / "source"
    source.mkdir()
    _run_git(source, "init", "-q")
    _run_git(source, "config", "user.email", "opentest@example.invalid")
    _run_git(source, "config", "user.name", "OpenTest")
    source_file = source / "TradeFacade.java"
    source_file.write_text("class TradeFacade { int committed = 1; }\n", encoding="utf-8")
    _run_git(source, "add", "TradeFacade.java")
    _run_git(source, "commit", "-q", "-m", "committed source")
    source_file.write_text("class TradeFacade { int uncommitted = 2; }\n", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(
        SystemDefinition(
            system_id="train-booking-core",
            name="火车票预订",
            source_path=str(source),
        )
    )
    artifacts = SourceScanArtifactStore(store.root)
    service = SourceAnalysisService(
        store,
        artifacts,
        FakeScriptgenScanner(),  # type: ignore[arg-type]
    )

    manifest = service.analyze(SourceScanRequest(system_id="train-booking-core"))
    snapshot_source = Path(manifest.baseline.readable_source_path)

    assert manifest.baseline.commit
    assert manifest.baseline.revision == "HEAD"
    assert manifest.baseline.snapshot_path == str(snapshot_source)
    assert manifest.baseline.dirty is False
    assert snapshot_source.is_relative_to(artifacts.source_snapshot_root)
    committed_source = (snapshot_source / "TradeFacade.java").read_text(
        encoding="utf-8"
    )
    assert "committed = 1" in committed_source
    assert "uncommitted = 2" in source_file.read_text(encoding="utf-8")
    assert Path(manifest.entries[0].source_path).is_relative_to(snapshot_source)


def test_source_analysis_rejects_source_changes_before_publishing_latest(tmp_path: Path) -> None:
    """扫描期间源码基线变化时应保留诊断工具但不得更新baseline或latest。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "TradeFacade.java").write_text("class TradeFacade {}\n", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    artifacts = SourceScanArtifactStore(store.root)
    service = SourceAnalysisService(
        store,
        artifacts,
        FakeScriptgenScanner(),  # type: ignore[arg-type]
        ChangingBaselineRepository(source),  # type: ignore[arg-type]
    )

    with pytest.raises(KnowledgeValidationError, match="source changed"):
        service.analyze(SourceScanRequest(system_id="train-booking-core"))
    assert store.get_system("train-booking-core").baseline is None
    with pytest.raises(KnowledgeNotFoundError):
        service.get_manifest("train-booking-core")


def test_source_analysis_serializes_concurrent_scans_and_publishes_complete_latest(tmp_path: Path) -> None:
    """并发任务必须串行进入扫描发布事务，latest最终指向完整可读取manifest。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "TradeFacade.java").write_text("class TradeFacade {}\n", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    second_store = GitKnowledgeStore(store.root)
    scanner = ConcurrentFakeScriptgenScanner()
    first_service = SourceAnalysisService(store, SourceScanArtifactStore(store.root), scanner)  # type: ignore[arg-type]
    second_service = SourceAnalysisService(second_store, SourceScanArtifactStore(store.root), scanner)  # type: ignore[arg-type]
    request = SourceScanRequest(system_id="train-booking-core")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(first_service.analyze, request), executor.submit(second_service.analyze, request)]
        manifests = [future.result() for future in futures]

    latest = first_service.get_manifest("train-booking-core")
    assert scanner.maximum_active == 1
    assert latest.scan_id in {manifest.scan_id for manifest in manifests}
    assert store.get_system("train-booking-core").baseline == latest.baseline


def test_source_analysis_keeps_previous_latest_when_baseline_publish_fails(tmp_path: Path) -> None:
    """新基线写入失败时不得提前切换latest，查询仍返回上次完整成功扫描。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "TradeFacade.java").write_text("class TradeFacade {}\n", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    service = SourceAnalysisService(store, SourceScanArtifactStore(store.root), FakeScriptgenScanner())  # type: ignore[arg-type]
    request = SourceScanRequest(system_id="train-booking-core")
    previous = service.analyze(request)

    def fail_baseline_publish(_: str, __: SourceBaseline) -> SystemDefinition:
        """模拟source.yaml原子发布失败且不修改任何Git真相文件。"""

        raise OSError("disk unavailable")

    store.update_source_baseline = fail_baseline_publish  # type: ignore[method-assign]
    with pytest.raises(OSError, match="disk unavailable"):
        service.analyze(request)

    assert service.get_manifest("train-booking-core").scan_id == previous.scan_id


def test_source_analysis_rolls_back_baseline_when_latest_publish_fails(tmp_path: Path) -> None:
    """latest原子替换失败时应恢复旧基线，使旧latest与Git真相继续一致。"""

    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "TradeFacade.java"
    source_file.write_text("class TradeFacade {}\n", encoding="utf-8")
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    artifacts = SourceScanArtifactStore(store.root)
    service = SourceAnalysisService(store, artifacts, FakeScriptgenScanner())  # type: ignore[arg-type]
    request = SourceScanRequest(system_id="train-booking-core")
    previous = service.analyze(request)
    source_file.write_text("class TradeFacade { void changed() {} }\n", encoding="utf-8")

    def fail_latest_publish(_: str, __: str) -> Path:
        """模拟latest指针原子替换失败且不修改旧指针。"""

        raise OSError("latest unavailable")

    artifacts.publish_latest = fail_latest_publish  # type: ignore[method-assign]
    with pytest.raises(OSError, match="latest unavailable"):
        service.analyze(request)

    assert service.get_manifest("train-booking-core").scan_id == previous.scan_id
    assert store.get_system("train-booking-core").baseline == previous.baseline


def test_cli_scan_returns_task_id_and_persists_terminal_result(tmp_path: Path) -> None:
    """CLI scan应复用本地任务语义，返回task_id且最终manifest可查询。"""

    source = tmp_path / "source"
    source.mkdir()
    (source / "TradeFacade.java").write_text("class TradeFacade {}\n", encoding="utf-8")
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(SystemDefinition(system_id="train-booking-core", name="火车票预订", source_path=str(source)))
    application.source_analysis.scriptgen = FakeScriptgenScanner()  # type: ignore[assignment]
    arguments = Namespace(
        command="scan",
        system_id="train-booking-core",
        environment="qa",
        types="facade,job",
        facade_http_prefix="http://servicegw.qa.example/gateway/train.booking/v2",
        job_rule=[],
        timeout=30,
    )

    task = dispatch(application, arguments)
    application.close()
    terminal = application.get_task(task.task_id)
    manifest = application.get_scan_manifest("train-booking-core")

    assert task.task_id.startswith("task-")
    assert terminal.status.value == "completed"
    assert terminal.result["scan_id"] == manifest.scan_id
