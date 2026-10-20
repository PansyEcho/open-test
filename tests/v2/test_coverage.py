"""覆盖采集仅用本地材料验证，不调用测试环境或实际 reset。"""

from __future__ import annotations

import io
import socket
import socketserver
import subprocess
import tarfile
import time
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from unittest.mock import Mock

import pytest

from opentest.adapters.coverage import (
    CoverageAnalyzer, CoverageArtifactReader, CoverageUnavailable, JacocoCollector,
    SkyeyeInstanceDiscovery, scope_from_manifest,
)
from opentest.domain.coverage import (
    CoverageAnalysisScope, CoverageArtifactSelection, CoverageScopeMethod,
    DiscoveredCoverageInstance, MaterializedCoverageArtifact, SkyeyeDiscoverySettings,
)
from opentest.domain.models import (
    EntryPoint, KnowledgeNodeKind, ScanManifest, SemanticAnalysisResult, SemanticCallEdge,
    SemanticMethodDefinition, SemanticResolutionStatus, SourceBaseline, SourceReference, utc_now,
)


COMMIT = "a" * 40


def _method(name: str, parameter: str | None = None) -> SemanticMethodDefinition:
    """创建明确完整类型的扫描方法，测试重载时保留参数类型。"""

    return SemanticMethodDefinition(symbol_id=f"demo.Service#{name}({parameter or ''})",
        qualified_class_name="demo.Service", method_name=name, has_executable_body=True,
        parameter_qualified_types=[parameter] if parameter else [],
        source_ref=SourceReference(path="src/main/java/demo/Service.java", commit=COMMIT))


def _artifact(tmp_path: Path) -> MaterializedCoverageArtifact:
    """准备仅供 XML 单测定位的本地源码，不编译或模拟真实 QA 材料。"""

    source = tmp_path / "source/demo/Service.java"
    source.parent.mkdir(parents=True)
    source.write_text("package demo; class Service {}")
    return MaterializedCoverageArtifact(commit=COMMIT, classfiles=[tmp_path / "classes"],
                                         source_roots=[tmp_path / "source"], workspace=tmp_path)


def test_class_match_requires_real_intersection() -> None:
    """没有类名交集不能因为没有 mismatch 警告就产生有效报告。"""

    with pytest.raises(CoverageUnavailable, match="没有可验证") as failure:
        CoverageAnalyzer._match_classes({"demo/Service": "a" * 16}, "bbbbbbbbbbbbbbbb 1 of 3 other/Type")
    assert failure.value.reason_code == "JACOCO_CLASS_NO_INTERSECTION"
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageAnalyzer._match_classes({"demo/Service": "a" * 16}, "bbbbbbbbbbbbbbbb 1 of 3 demo/Service")
    assert failure.value.reason_code == "JACOCO_CLASS_MISMATCH"
    assert CoverageAnalyzer._match_classes({"demo/Service": "a" * 16}, "aaaaaaaaaaaaaaaa 1 of 3 demo/Service") == (1, 0)


def test_classinfo_retains_method_lines_and_rejects_duplicates() -> None:
    """原生 classinfo 的逐方法行集合用于精确排除未执行方法内部缺口。"""

    text = "class 0xaaaaaaaaaaaaaaaa demo/Service\n +- method run()V\n 1 0 +- line 12\n 1 0 +- line 18"
    classes, lines = CoverageAnalyzer._class_details(text)
    assert classes == {"demo/Service": "a" * 16}
    assert lines[("demo/Service", "run", "()V")] == {12, 18}
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageAnalyzer._class_details(text + "\nclass 0xaaaaaaaaaaaaaaaa demo/Service")
    assert failure.value.reason_code == "ARTIFACT_DUPLICATE_CLASS"


def test_scope_follows_resolved_edges_and_does_not_expand_overloads() -> None:
    """闭包只跟随可信边；结构入口无法区分重载时不将多个同名方法当入口。"""

    start, child, ignored = _method("run"), _method("child"), _method("ignored")
    edge = SemanticCallEdge(caller_symbol_id=start.symbol_id, callee_symbol_id=child.symbol_id,
                            callee_expression="child", source_ref=start.source_ref,
                            resolution_status=SemanticResolutionStatus.RESOLVED)
    uncertain = edge.model_copy(update={"callee_symbol_id": ignored.symbol_id, "confidence": 0.8})
    manifest = ScanManifest(scan_id="scan-one", system_id="demo", baseline=SourceBaseline(source_path="/tmp", commit=COMMIT),
        entries=[EntryPoint(entry_id="facade:run", system_id="demo", kind=KnowledgeNodeKind.FACADE,
                            display_name="run", source_id="demo.Service#run", source_path="src/main/java/demo/Service.java")],
        semantic_analysis=SemanticAnalysisResult(system_id="demo", methods=[start, child, ignored], call_edges=[edge, uncertain]))
    scope = scope_from_manifest(manifest, "facade:run")
    assert [(item.method.method_name, item.distance) for item in scope.methods] == [("run", 0), ("child", 1)]
    assert scope.scope_status == "PARTIAL"
    manifest.semantic_analysis.methods.append(_method("run", "java.lang.String"))
    assert scope_from_manifest(manifest, "facade:run").methods == []


def test_descriptor_unknown_never_binds_all_overloads() -> None:
    """扫描类型变量无法解析时，两个重载必须保持未知。"""

    member = CoverageScopeMethod(method=_method("run", "T"), distance=0)
    methods = {("demo/Service", "run", "(I)V"): ET.Element("method"),
               ("demo/Service", "run", "(Ljava/lang/String;)V"): ET.Element("method")}
    assert CoverageAnalyzer._bind_method(member, methods) is None


def test_gap_units_are_mutually_exclusive(tmp_path: Path) -> None:
    """整方法、分支行及连续未执行行块分别成项，且不重复覆盖相同行。"""

    root = ET.fromstring('''<report><package name="demo"><class name="demo/Service" sourcefilename="Service.java">
      <method name="missed" desc="()V" line="10"><counter type="METHOD" missed="1" covered="0"/></method>
      <method name="partial" desc="()V" line="20"><counter type="METHOD" missed="0" covered="1"/></method>
      </class><sourcefile name="Service.java">
      <line nr="10" mi="3" ci="0" mb="2" cb="0"/><line nr="11" mi="2" ci="0" mb="0" cb="0"/>
      <line nr="20" mi="0" ci="3" mb="1" cb="1"/><line nr="21" mi="2" ci="0" mb="0" cb="0"/>
      <line nr="22" mi="2" ci="0" mb="0" cb="0"/><line nr="23" mi="0" ci="3" mb="0" cb="0"/>
      </sourcefile></package><counter type="METHOD" missed="1" covered="1"/>
      <counter type="LINE" missed="4" covered="2"/><counter type="BRANCH" missed="3" covered="1"/></report>''')
    scope = CoverageAnalysisScope(commit=COMMIT, methods=[CoverageScopeMethod(method=_method(name), distance=0)
                                                          for name in ("missed", "partial")])
    method_lines = {("demo/Service", "missed", "()V"): {10, 11},
                    ("demo/Service", "partial", "()V"): {20, 21, 22, 23}}
    analyzer = CoverageAnalyzer(JacocoCollector("java", "unused.jar"))
    result = analyzer._analyze_xml(root, method_lines, _artifact(tmp_path), scope, (1, 0))
    assert [(gap.kind, gap.location.line, gap.location.end_line) for gap in result.gaps] == [
        ("METHOD", 10, None), ("BRANCH_LINE", 20, None), ("LINE_BLOCK", 21, 22)]
    assert result.candidate_gap_count == 3 and result.deferred_gap_count == 0
    assert result.scope_counts.line.covered == 2 and result.scope_counts.line.missed == 4


def test_gap_limit_preserves_deferred_count(tmp_path: Path) -> None:
    """超过预算的真实缺口只计 deferred，不伪装成已经覆盖。"""

    root = ET.Element("report")
    package = ET.SubElement(root, "package", name="demo")
    klass = ET.SubElement(package, "class", name="demo/Service", sourcefilename="Service.java")
    scope = CoverageAnalysisScope(commit=COMMIT)
    lines = {}
    # 多个明确未执行的方法构成独立行动单元，用于验证三十项截断。
    for index in range(35):
        name = f"run{index:02d}"
        element = ET.SubElement(klass, "method", name=name, desc="()V", line=str(index + 1))
        ET.SubElement(element, "counter", type="METHOD", missed="1", covered="0")
        scope.methods.append(CoverageScopeMethod(method=_method(name), distance=0))
        lines[("demo/Service", name, "()V")] = {index + 1}
    ET.SubElement(root, "counter", type="METHOD", missed="35", covered="0")
    analyzer = CoverageAnalyzer(JacocoCollector("java", "unused.jar"))
    result = analyzer._analyze_xml(root, lines, _artifact(tmp_path), scope, (1, 0))
    assert len(result.gaps) == 30
    assert result.candidate_gap_count == 35 and result.deferred_gap_count == 5
    assert result.gaps[-1].gap_id == "gap-030"


def test_discovery_checks_identity_and_chooses_newest_without_assuming_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    """混合应用、错误环境及乱序日志不能直接取第一页首行。"""

    now = utc_now()
    old = now - timedelta(minutes=1)
    rows = [{"appId": 123, "appUk": "demo.app", "env": "qa", "ip": "10.0.0.2", "id": "old", "timestamp": old.timestamp() * 1000},
            {"appId": 999, "appUk": "other", "env": "qa", "ip": "10.0.0.8", "id": "wrong", "timestamp": now.timestamp() * 1000},
            {"appId": 123, "appUk": "demo.app", "env": "uat", "ip": "10.0.0.9", "id": "uat", "timestamp": now.timestamp() * 1000},
            {"appId": 123, "appUk": "demo.app", "env": "qa", "ip": "10.0.0.3", "id": "new", "timestamp": now.timestamp() * 1000}]
    discovery = SkyeyeInstanceDiscovery()
    monkeypatch.setattr(discovery, "_query", lambda *_: {"list": rows})
    found = discovery.discover(SkyeyeDiscoverySettings(app_id="123", token="private-token"), time.monotonic() + 10)
    assert found.ip == "10.0.0.3" and found.app_uk == "demo.app"
    assert "private-token" not in SkyeyeDiscoverySettings(app_id="123", token="private-token").model_dump_json()


def test_discovery_rejects_incomplete_page_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """重复游标时不能把已见到的某个 IP 宣称为全窗口最新。"""

    row = {"appId": 123, "appUk": "demo.app", "env": "qa", "ip": "10.0.0.2", "id": "same", "timestamp": utc_now().timestamp() * 1000}
    discovery = SkyeyeInstanceDiscovery()
    monkeypatch.setattr(discovery, "_query", lambda *_: {"list": [row] * 500})
    with pytest.raises(CoverageUnavailable) as failure:
        discovery.discover(SkyeyeDiscoverySettings(app_id="123", token="secret"), time.monotonic() + 10)
    assert failure.value.reason_code == "SKYEYE_PAGINATION_INCOMPLETE"


def test_expired_deadline_prevents_reset_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """预算到期后连 CLI 都不派发，避免迟到 reset 清除下一轮数据。"""

    collector = JacocoCollector("java", tmp_path / "unused.jar")
    calls = []
    monkeypatch.setattr(collector, "run", lambda *args: calls.append(args))
    target = DiscoveredCoverageInstance(ip="10.0.0.1", port=6300, app_uk="demo", log_time=utc_now())
    with pytest.raises(CoverageUnavailable):
        collector.reset(target, time.monotonic() - 1)
    assert calls == []


def _make_materials(tmp_path: Path, source_name: str = "app/biz/src/main/java/demo/Service.java") -> CoverageArtifactSelection:
    """建立小型归档验证路径/身份检查，类字节仅用于筛选而不交给 JaCoCo。"""

    jar_bytes = io.BytesIO()
    with ZipFile(jar_bytes, "w") as jar:
        jar.writestr("demo/Service.class", b"class-fixture")
        jar.writestr("demo/Unloaded.class", b"unloaded-class-fixture")
    war = tmp_path / "deployment.war"
    with ZipFile(war, "w") as archive:
        archive.writestr("WEB-INF/lib/business.jar", jar_bytes.getvalue())
    source = tmp_path / "source.tar.gz"
    content = b"package demo; class Service {}"
    with tarfile.open(source, "w:gz") as archive:
        info = tarfile.TarInfo(source_name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return CoverageArtifactSelection(app_uk="demo.app", artifact_path=str(war),
                                      source_archive_path=str(source), artifact_commit=COMMIT)


def test_materialization_keeps_unloaded_classes_and_detects_changed_package(tmp_path: Path) -> None:
    """固定包能保留同业务 JAR 未加载类；准备之后换包必须拒绝。"""

    selection = _make_materials(tmp_path)
    reader = CoverageArtifactReader()
    frozen = reader.prepare(selection, COMMIT, time.monotonic() + 10)
    materialized = reader.materialize(frozen, tmp_path / "analysis")
    with ZipFile(materialized.classfiles[0]) as jar:
        assert "demo/Unloaded.class" in jar.namelist()
    Path(selection.artifact_path).write_bytes(b"replaced deployment")
    with pytest.raises(CoverageUnavailable) as failure:
        reader.materialize(frozen, tmp_path / "changed")
    assert failure.value.reason_code == "ARTIFACT_CHANGED"


def test_source_archive_cannot_escape_workspace(tmp_path: Path) -> None:
    """源码归档中的路径穿越不能写入分析目录之外。"""

    selection = _make_materials(tmp_path, "../../outside.java")
    reader = CoverageArtifactReader()
    frozen = reader.prepare(selection, COMMIT, time.monotonic() + 10)
    with pytest.raises(CoverageUnavailable) as failure:
        reader.materialize(frozen, tmp_path / "analysis")
    assert failure.value.reason_code == "ARTIFACT_PATH_INVALID"
    assert not (tmp_path / "outside.java").exists()


def test_frozen_ftp_reference_retains_only_environment_names() -> None:
    """私有恢复引用保留环境变量名称，不接受可被持久化的 FTP 明文凭据。"""

    selection = CoverageArtifactSelection(app_uk="demo", archive_username_ref="${ENV:ARCHIVE_USER}",
                                          archive_password_ref="${ENV:ARCHIVE_PASSWORD}")
    assert selection.model_dump()["archive_password_ref"] == "${ENV:ARCHIVE_PASSWORD}"
    with pytest.raises(ValueError):
        CoverageArtifactSelection(app_uk="demo", archive_password_ref="plaintext-secret")


def test_ftp_actual_layout_separates_war_and_source_and_lists_current_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实构建布局使用 war/qa 的 WAR 与 qa 下 out.tar.gz，并兼容服务器 NLST 限制。"""

    reader = CoverageArtifactReader()
    ftp = Mock()
    ftp.nlst.return_value = ["application.war", "notes.txt"]
    ftp.size.return_value = 42
    ftp.sendcmd.return_value = "213 20261016165725"
    monkeypatch.setattr(reader, "_ftp", lambda *_: nullcontext(ftp))
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="archive.example",
        archive_root="/flight/accurate", archive_version="feature-example-8")
    frozen = reader._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    war_directory = f"/flight/accurate/demo.app/war/qa/feature-example-8/{COMMIT}"
    ftp.cwd.assert_called_once_with(war_directory)
    ftp.nlst.assert_called_once_with()
    assert frozen.artifact.path == war_directory + "/application.war"
    assert frozen.source.path == f"/flight/accurate/demo.app/qa/feature-example-8/{COMMIT}/out.tar.gz"
    assert ftp.voidcmd.call_count == 2


@contextmanager
def _slow_network_server(stage: str):
    """提供真实本地慢滴流或逐阶段延迟，退出时关闭全部监听和连接线程。

    Args:
        stage: HTTP 响应头/体，或 FTP 欢迎行、目录数据、累积阶段延迟。
    Yields:
        端口和已进入慢响应阶段的事件，供测试确认没有只测到进程启动超时。
    """

    stop, reached = Event(), Event()

    class SlowHandler(socketserver.StreamRequestHandler):
        """实现采集所需的最小协议，故意让每次 socket 等待都短于总预算。"""

        def handle(self):
            """按测试阶段滴流，连接关闭后退出；不保存请求正文或凭据。"""

            try:
                if stage.startswith("http"):
                    # urllib 可能等待完整头或 Content-Length；持续发送单字节不会触发 idle timeout。
                    while self.rfile.readline().strip():
                        pass
                    if stage == "http_success":
                        body = b'{"code":200,"result":{"list":[]}}'
                        self.wfile.write(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
                        reached.set()
                        return
                    if stage == "http_body":
                        self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
                    else:
                        self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    reached.set()
                    while not stop.wait(0.02):
                        self.wfile.write(b"x")
                    return
                if stage == "ftp_welcome":
                    reached.set()
                    self.wfile.write(b"220 ")
                    while not stop.wait(0.02):
                        self.wfile.write(b"x")
                    return
                self.wfile.write(b"220 ready\r\n")
                listener = None
                try:
                    while not stop.is_set():
                        command = self.rfile.readline().decode("ascii").split(" ", 1)[0].strip()
                        if not command:
                            return
                        if stage == "ftp_stages":
                            reached.set()
                            if stop.wait(0.22):
                                return
                        if command == "USER":
                            self.wfile.write(b"331 password\r\n")
                        elif command == "PASS":
                            self.wfile.write(b"230 logged in\r\n")
                        elif command == "CWD":
                            self.wfile.write(b"250 directory\r\n")
                        elif command == "TYPE":
                            self.wfile.write(b"200 type\r\n")
                        elif command == "PASV":
                            listener = socket.socket()
                            listener.bind(("127.0.0.1", 0))
                            listener.listen()
                            listener.settimeout(2)
                            port = listener.getsockname()[1]
                            self.wfile.write(f"227 passive (127,0,0,1,{port // 256},{port % 256})\r\n".encode())
                        elif command == "NLST":
                            self.wfile.write(b"150 listing\r\n")
                            connection, _ = listener.accept()
                            with connection:
                                reached.set()
                                if stage == "ftp_success":
                                    connection.sendall(b"application.war\r\n")
                                else:
                                    while not stop.wait(0.02):
                                        connection.sendall(b"x")
                                    return
                            self.wfile.write(b"226 complete\r\n")
                        elif command == "SIZE":
                            self.wfile.write(b"213 42\r\n")
                        elif command == "MDTM":
                            self.wfile.write(b"213 20261016165725\r\n")
                finally:
                    if listener is not None:
                        listener.close()
            except (OSError, ValueError):
                # 父进程超时会关闭工作进程所有 socket；服务端 BrokenPipe 正是预期收尾。
                return

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SlowHandler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    try:
        yield server.server_address[1], reached
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("stage", ["http_headers", "http_body", "ftp_welcome", "ftp_nlst", "ftp_stages"])
def test_network_total_deadline_kills_and_reaps_slow_collection(stage: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """短预算必须中止持续滴流与跨阶段累积等待，回收采集进程后不得执行迟到 reset。"""

    processes = []
    original_popen = subprocess.Popen

    def record_process(*args, **kwargs):
        """保留标准 subprocess 创建的实际句柄，用于断言超时已 kill 和 wait。

        Notes:
            保留标准库 Popen 回调签名以完整转发外部 API，并非业务参数包装。
        """
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", record_process)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("COVERAGE_TEST_FTP_USER", "test-user")
    monkeypatch.setenv("COVERAGE_TEST_FTP_PASSWORD", "test-password")
    collector = JacocoCollector("java", tmp_path / "unused.jar")
    monkeypatch.setattr(collector, "run", Mock())
    target = DiscoveredCoverageInstance(ip="127.0.0.1", port=6300, app_uk="demo", log_time=utc_now())
    with _slow_network_server(stage) as (port, reached):
        started = time.monotonic()
        deadline = started + 1.2
        with pytest.raises(CoverageUnavailable) as failure:
            if stage.startswith("http"):
                SkyeyeInstanceDiscovery(f"http://127.0.0.1:{port}/logs")._query({}, "test-token", deadline)
            else:
                selection = CoverageArtifactSelection(app_uk="demo", archive_host="127.0.0.1", archive_port=port,
                    archive_root="/archive", archive_version="version-1", archive_username_ref="${ENV:COVERAGE_TEST_FTP_USER}",
                    archive_password_ref="${ENV:COVERAGE_TEST_FTP_PASSWORD}")
                CoverageArtifactReader().prepare(selection, COMMIT, deadline)
            collector.reset(target, deadline)
        elapsed = time.monotonic() - started
    assert reached.is_set(), "test must reach actual slow network I/O"
    assert failure.value.reason_code == "COVERAGE_PREFLIGHT_TIMEOUT"
    assert elapsed < 1.9
    assert len(processes) == 1 and processes[0].poll() is not None
    collector.run.assert_not_called()


@pytest.mark.parametrize("stage", ["http_success", "ftp_success"])
def test_bounded_network_worker_returns_normal_protocol_result(stage: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """只读进程在正常响应时完整保留日志结果或 FTP 固定引用，没有改变业务成功契约。"""

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("COVERAGE_TEST_FTP_USER", "test-user")
    monkeypatch.setenv("COVERAGE_TEST_FTP_PASSWORD", "test-password")
    with _slow_network_server(stage) as (port, reached):
        deadline = time.monotonic() + 3
        if stage.startswith("http"):
            result = SkyeyeInstanceDiscovery(f"http://127.0.0.1:{port}/logs")._query({}, "test-token", deadline)
            assert result == {"list": []}
        else:
            selection = CoverageArtifactSelection(app_uk="demo", archive_host="127.0.0.1", archive_port=port,
                archive_root="/archive", archive_version="version-1", archive_username_ref="${ENV:COVERAGE_TEST_FTP_USER}",
                archive_password_ref="${ENV:COVERAGE_TEST_FTP_PASSWORD}")
            frozen = CoverageArtifactReader().prepare(selection, COMMIT, deadline)
            assert frozen.artifact.path == f"/archive/demo/war/qa/version-1/{COMMIT}/application.war"
            assert frozen.source.path == f"/archive/demo/qa/version-1/{COMMIT}/out.tar.gz"
            assert frozen.source.size == 42 and frozen.transport == "FTP"
        assert reached.is_set()


def test_total_deadline_also_interrupts_blocking_dns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """即使 socket 还没有建立，DNS 阻塞也由只读进程总预算中止，不依赖 socket timeout。"""

    # 在子解释器启动时只替换 DNS；标记证明请求已到解析阶段，再模拟无法自行超时的解析器。
    marker = tmp_path / "dns-entered"
    (tmp_path / "sitecustomize.py").write_text(
        "import socket, time\nfrom pathlib import Path\n"
        "def blocked_dns(*args, **kwargs):\n"
        "    \"\"\"测试中模拟标准 getaddrinfo 的外部签名和无超时阻塞。\"\"\"\n"
        f"    Path({str(marker)!r}).write_text('entered')\n"
        "    time.sleep(60)\n"
        "socket.getaddrinfo = blocked_dns\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("NO_PROXY", "*")
    started = time.monotonic()
    with pytest.raises(CoverageUnavailable) as failure:
        SkyeyeInstanceDiscovery("http://dns-test.invalid/logs")._query({}, "test-token", started + 1.2)
    assert marker.is_file()
    assert failure.value.reason_code == "COVERAGE_PREFLIGHT_TIMEOUT"
    assert time.monotonic() - started < 1.9
