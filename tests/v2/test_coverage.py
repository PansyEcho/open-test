"""覆盖采集仅用本地材料验证，不调用测试环境或实际 reset。"""

from __future__ import annotations

import io
import ftplib
import socket
import socketserver
import subprocess
import tarfile
import time
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
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


def test_classinfo_retains_method_lines_and_rejects_conflicting_duplicates() -> None:
    """同字节类的重复 CLI 输出可合并；不同 ID 必须继续阻止模糊报告。"""

    text = "class 0xaaaaaaaaaaaaaaaa demo/Service\n +- method run()V\n 1 0 +- line 12\n 1 0 +- line 18"
    # 完整字节比较由物化阶段负责，CLI 同 ID 的重复条目不能清空已有方法行集合。
    classes, lines = CoverageAnalyzer._class_details(text + "\n" + text)
    assert classes == {"demo/Service": "a" * 16}
    assert lines[("demo/Service", "run", "()V")] == {12, 18}
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageAnalyzer._class_details(text + "\nclass 0xbbbbbbbbbbbbbbbb demo/Service")
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


def test_scope_includes_uniquely_bound_partial_signature_edge() -> None:
    """目标方法已唯一确定、仅参数描述符缺失时仍纳入范围，供实际字节码绑定。"""

    start = _method("run")
    child = _method("child", "SaasOrderVO").model_copy(
        update={"resolution_status": SemanticResolutionStatus.PARTIAL, "confidence": 0.65})
    edge = SemanticCallEdge(caller_symbol_id=start.symbol_id, callee_symbol_id=child.symbol_id,
                            callee_expression="child", source_ref=start.source_ref,
                            resolution_status=SemanticResolutionStatus.PARTIAL, confidence=0.75,
                            unresolved_reason="dependency_method_signature_unavailable")
    manifest = ScanManifest(scan_id="scan-one", system_id="demo", baseline=SourceBaseline(source_path="/tmp", commit=COMMIT),
        entries=[EntryPoint(entry_id="facade:run", system_id="demo", kind=KnowledgeNodeKind.FACADE,
                            display_name="run", source_id="demo.Service#run", source_path="src/main/java/demo/Service.java")],
        semantic_analysis=SemanticAnalysisResult(system_id="demo", methods=[start, child], call_edges=[edge]))
    scope = scope_from_manifest(manifest, "facade:run")
    assert [(item.method.method_name, item.distance) for item in scope.methods] == [("run", 0), ("child", 1)]
    assert "部分参数描述符" in scope.scope_reason
    assert [(item.caller_method, item.expression) for item in scope.scope_limitations] == [("run", "child")]
    untrusted = edge.model_copy(update={"unresolved_reason": "symbol_solver_unresolved"})
    manifest.semantic_analysis.call_edges = [untrusted]
    assert [item.method.method_name for item in scope_from_manifest(manifest, "facade:run").methods] == ["run"]


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
        ("METHOD", 10, 11), ("BRANCH_LINE", 20, None), ("LINE_BLOCK", 21, 22)]
    assert result.candidate_gap_count == 3 and result.deferred_gap_count == 0
    assert result.scope_counts.line.covered == 2 and result.scope_counts.line.missed == 4


def test_whole_method_gap_precedes_shallow_branch_gap(tmp_path: Path) -> None:
    """整方法未执行优先于浅层分支碎片，避免深层业务方法被挤出行动清单。"""

    root = ET.Element("report")
    package = ET.SubElement(root, "package", name="demo")
    klass = ET.SubElement(package, "class", name="demo/Service", sourcefilename="Service.java")
    shallow = ET.SubElement(klass, "method", name="shallow", desc="()V", line="10")
    ET.SubElement(shallow, "counter", type="METHOD", missed="0", covered="1")
    deep = ET.SubElement(klass, "method", name="deep", desc="()V", line="30")
    ET.SubElement(deep, "counter", type="METHOD", missed="1", covered="0")
    source = ET.SubElement(package, "sourcefile", name="Service.java")
    ET.SubElement(source, "line", nr="10", mi="0", ci="3", mb="1", cb="1")
    ET.SubElement(source, "line", nr="30", mi="2", ci="0", mb="0", cb="0")
    ET.SubElement(root, "counter", type="METHOD", missed="1", covered="1")
    ET.SubElement(root, "counter", type="LINE", missed="1", covered="1")
    ET.SubElement(root, "counter", type="BRANCH", missed="1", covered="1")
    scope = CoverageAnalysisScope(commit=COMMIT, methods=[
        CoverageScopeMethod(method=_method("shallow"), distance=1),
        CoverageScopeMethod(method=_method("deep"), distance=3)])
    analyzer = CoverageAnalyzer(JacocoCollector("java", "unused.jar"))
    result = analyzer._analyze_xml(root, {("demo/Service", "shallow", "()V"): {10},
        ("demo/Service", "deep", "()V"): {30}}, _artifact(tmp_path), scope, (1, 0))
    assert [(gap.kind, gap.location.method_name) for gap in result.gaps] == [("METHOD", "deep"), ("BRANCH_LINE", "shallow")]


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


@pytest.mark.parametrize("server_ip,legacy_ip,expected_ip", [
    ("10.0.0.4", "container-demo-123", "10.0.0.4"),
    ("10.0.0.4", "10.0.0.5", "10.0.0.4"),
    (None, "10.0.0.5", "10.0.0.5"),
    ("", "10.0.0.5", "10.0.0.5"),
    ("not-an-address", "10.0.0.5", None),
    (" ", "10.0.0.5", None),
    (None, "container-demo-123", None),
])
def test_discovery_uses_instance_address_and_only_falls_back_for_missing_server_ip(
    server_ip: str | None, legacy_ip: str, expected_ip: str | None,
) -> None:
    """验证容器地址与旧日志兼容边界，不连接实际采集服务。

    server_ip 为待验证地址，None 模拟缺少字段；legacy_ip 是旧地址或容器名，
    expected_ip 为允许采集的地址，None 表示整条候选必须被拒绝。
    """

    now = utc_now()
    row = {"appId": "123", "appUk": "demo.app", "env": "uat", "ip": legacy_ip,
           "id": "current", "timestamp": now.timestamp() * 1000}
    # None 模拟旧日志根本没有 serverIp；空串与非法值分别验证兼容和拒绝边界。
    if server_ip is not None:
        row["serverIp"] = server_ip
    config = SkyeyeDiscoverySettings(app_id="123", environment="uat", jacoco_port=6311)
    candidate = SkyeyeInstanceDiscovery._candidate(row, config, (now - timedelta(minutes=1), now), "uat")
    if expected_ip is None:
        assert candidate is None
    else:
        assert candidate is not None
        assert candidate.ip == expected_ip
        assert candidate.port == 6311


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


def _business_jar(entries: list[tuple[str, bytes]]) -> bytes:
    """按给定成员顺序制作筛选测试用 JAR，允许有意重复的 ZIP 类名。"""

    content = io.BytesIO()
    names = [name for name, _ in entries]
    # 重复成员是需要覆盖的真实归档形式，显式接收 zipfile 的构建警告。
    warning = pytest.warns(UserWarning, match="Duplicate name") if len(set(names)) != len(names) else nullcontext()
    with warning, ZipFile(content, "w") as archive:
        for name, bytecode in entries:
            archive.writestr(name, bytecode)
    return content.getvalue()


@pytest.mark.parametrize("layout", ["WEB-INF", "BOOT-INF"])
@pytest.mark.parametrize("location", ["direct_and_jar", "different_jars", "same_jar_name", "inside_jar"])
@pytest.mark.parametrize("identical", [False, True])
def test_selected_business_classes_compare_complete_bytes(
    tmp_path: Path, layout: str, location: str, identical: bool,
) -> None:
    """两种部署布局的实际分析输入须一致，业务 JAR 中未在源码列出的类也检查。"""

    # 沿用筛选测试的类字节夹具，不交给 JaCoCo；差异位于第二块以验证完整字节比较。
    original = b"class-fixture" + b"x" * (64 * 1024)
    other = original if identical else original[:-1] + b"y"
    artifact = tmp_path / "application.jar"
    sources = {"demo/Service", "demo/Other"}
    with ZipFile(artifact, "w") as archive:
        if location == "direct_and_jar":
            archive.writestr(f"{layout}/classes/demo/Service.class", original)
            archive.writestr(f"{layout}/lib/business.jar", _business_jar([("demo/Service.class", other)]))
        elif location in {"different_jars", "same_jar_name"}:
            # 两个 JAR 各由不同源码类入选，冲突类却不在源码集内，不能只验证源码交集。
            first = "first/business.jar" if location == "same_jar_name" else "first.jar"
            second = "second/business.jar" if location == "same_jar_name" else "second.jar"
            archive.writestr(f"{layout}/lib/{first}", _business_jar([
                ("demo/Service.class", b"service"), ("common/Unloaded.class", original)]))
            archive.writestr(f"{layout}/lib/{second}", _business_jar([
                ("demo/Other.class", b"other"), ("common/Unloaded.class", other)]))
        else:
            archive.writestr(f"{layout}/lib/business.jar", _business_jar([
                ("demo/Service.class", b"service"),
                ("common/Unloaded.class", original), ("common/Unloaded.class", other)]))

    if not identical:
        with pytest.raises(CoverageUnavailable) as failure:
            CoverageArtifactReader._extract_business_classes(artifact, tmp_path / "classes", sources)
        assert failure.value.reason_code == "ARTIFACT_DUPLICATE_CLASS"
        return
    selected = CoverageArtifactReader._extract_business_classes(artifact, tmp_path / "classes", sources)
    libraries = [path for path in selected if path.is_file()]
    assert len(libraries) == (2 if location in {"different_jars", "same_jar_name"} else 1)
    if location != "direct_and_jar":
        # 相同重复无需裁掉业务 JAR 的其他类，未加载类仍会交给 JaCoCo。
        with ZipFile(libraries[0]) as archive:
            assert "common/Unloaded.class" in archive.namelist()


@pytest.mark.parametrize("layout", ["WEB-INF", "BOOT-INF"])
def test_identical_direct_classes_across_layouts_are_allowed(tmp_path: Path, layout: str) -> None:
    """同一类同时位于应用类目录与根目录时，相同字节只物化一次。"""

    artifact = tmp_path / "application.jar"
    # 两种物理路径归一到同一直接类路径，不应仅因布局重复就拒绝有效材料。
    with ZipFile(artifact, "w") as archive:
        archive.writestr(f"{layout}/classes/demo/Service.class", b"class-fixture")
        archive.writestr("demo/Service.class", b"class-fixture")
    selected = CoverageArtifactReader._extract_business_classes(artifact, tmp_path / "classes", {"demo/Service"})
    assert len(selected) == 1
    assert (selected[0] / "demo/Service.class").read_bytes() == b"class-fixture"


def test_business_jar_members_cannot_escape_workspace(tmp_path: Path) -> None:
    """完整业务 JAR 被选入分析后，其内部越界成员也不能绕过路径检查。"""

    artifact = tmp_path / "application.war"
    # 正常源码类使整个 JAR 入选，越界类没有源码匹配也必须被路径检查拦截。
    with ZipFile(artifact, "w") as archive:
        archive.writestr("WEB-INF/lib/business.jar", _business_jar([
            ("demo/Service.class", b"class-fixture"), ("../outside.class", b"unsafe")]))
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader._extract_business_classes(artifact, tmp_path / "classes", {"demo/Service"})
    assert failure.value.reason_code == "ARTIFACT_PATH_INVALID"
    assert not (tmp_path / "outside.class").exists()


@pytest.mark.parametrize("descriptor", ["module-info.class", "META-INF/versions/9/module-info.class"])
def test_distinct_business_modules_may_have_different_descriptors(tmp_path: Path, descriptor: str) -> None:
    """两个已选业务模块的描述符允许不同，互不重名的业务类仍完整保留。"""

    artifact = tmp_path / "application.jar"
    # 每个 JAR 由本项目源码类入选，描述符只用于声明各自模块，不是覆盖冲突。
    with ZipFile(artifact, "w") as archive:
        for module in ("First", "Second"):
            archive.writestr(f"BOOT-INF/lib/{module}.jar", _business_jar([
                (f"demo/{module}.class", module.encode()),
                (descriptor, f"module {module}".encode()),
            ]))
    selected = CoverageArtifactReader._extract_business_classes(
        artifact, tmp_path / "classes", {"demo/First", "demo/Second"},
    )
    assert len(selected) == 2
    # 描述符可以随完整 JAR 交给 JaCoCo 自行跳过，不裁掉其他尚未加载的类。
    for path in selected:
        with ZipFile(path) as archive:
            assert descriptor in archive.namelist()


def test_direct_module_descriptor_is_not_a_coverage_class(tmp_path: Path) -> None:
    """混合布局中的不同模块描述符不覆盖同一个直接文件，也不阻断业务类分析。"""

    artifact = tmp_path / "application.jar"
    # 模拟归档中同时存在两种类布局；只保留真正需要计数的业务类。
    with ZipFile(artifact, "w") as archive:
        archive.writestr("WEB-INF/classes/module-info.class", b"module first")
        archive.writestr("module-info.class", b"module second")
        archive.writestr("demo/Service.class", b"service")
    selected = CoverageArtifactReader._extract_business_classes(
        artifact, tmp_path / "classes", {"demo/Service", "module-info"},
    )
    assert len(selected) == 1
    assert sorted(path.name for path in selected[0].rglob("*.class")) == ["Service.class"]


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


def _archive_ftp(monkeypatch: pytest.MonkeyPatch, directories: dict, files: dict,
                 modified: dict[str, str] | None = None) -> Mock:
    """以独立会话替代 FTP 传输，保留真实连接边界的错误分类。

    directories 将绝对目录映射到直属条目或读取异常，files 将文件映射到大小或异常，
    modified 可选地按路径覆盖 MDTM；未覆盖时使用固定时间，便于构造唯一或并列候选。
    返回聚合调用记录和 connections 列表验证访问范围及关闭；不连接网络。
    """

    client = Mock()
    client.connections = []

    def file_size(path: str) -> int:
        """读取文件清单中的大小；缺文件与预置故障均走真实错误分类。"""

        if path not in files:
            raise ftplib.error_perm("550 file unavailable")
        size = files[path]
        if isinstance(size, Exception):
            raise size
        return size

    def file_modified(command: str) -> str:
        """按路径返回可控 MDTM，未指定文件使用固定时间避免测试依赖执行时刻。"""

        path = command.removeprefix("MDTM ")
        return f"213 {modified.get(path, '20261022030000') if modified else '20261022030000'}"

    client.size.side_effect = file_size
    client.sendcmd.side_effect = file_modified

    def connect(**kwargs) -> Mock:
        """模拟 ftplib.FTP 的构造契约，各连接的当前目录互不影响并集中记录调用。"""

        connection = Mock()
        connection.sock = None
        current_directory = ""

        def change_directory(path: str) -> None:
            """切换当前会话目录，未知路径按真实 FTP 错误处理。"""

            nonlocal current_directory
            client.cwd(path)
            if path not in directories:
                raise ftplib.error_perm("550 directory unavailable")
            current_directory = path

        def list_directory() -> list[str]:
            """返回会话当前目录或预置错误，不隐藏其他并发批次的不可读目录。"""

            client.nlst()
            entries = directories[current_directory]
            if isinstance(entries, Exception):
                raise entries
            return entries

        # 一个 FTP 对象只拥有一份 CWD 状态，避免用共享 Mock 掩盖并发目录串扰。
        connection.cwd.side_effect = change_directory
        connection.nlst.side_effect = list_directory
        connection.size = client.size
        connection.sendcmd = client.sendcmd
        client.connections.append(connection)
        return connection

    # 仍通过 _ftp 进入，证明网络错误不会被自动发现误判为不存在的候选。
    monkeypatch.setattr("opentest.adapters.coverage.ftplib.FTP", connect)
    monkeypatch.setenv("OPENTEST_FTP_USER", "fixture-user")
    monkeypatch.setenv("OPENTEST_FTP_PASSWORD", "fixture-password")
    return client


@pytest.mark.parametrize("environment", ["qa", "uat"])
def test_ftp_auto_selection_is_unique_and_stays_in_selected_environment(
    environment: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只读取所选环境的固定 commit，跳过不含该 commit 的版本并固定唯一完整构建。"""

    base = f"/archive/demo.app/war/{environment}"
    candidate = f"{base}/feature-current-2/{COMMIT}"
    source = f"/archive/demo.app/{environment}/feature-current-2/{COMMIT}/out.tar.gz"
    directories = {base: ["feature-older-1", "feature-current-2"],
        base + "/feature-older-1": ["b" * 40], base + "/feature-current-2": [COMMIT],
        candidate: ["actual.war", "notes.txt"]}
    client = _archive_ftp(monkeypatch, directories, {candidate + "/actual.war": 42, source: 12})
    selection = CoverageArtifactSelection(app_uk="demo.app", environment=environment,
        archive_environment=environment, archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    reader = CoverageArtifactReader()

    def prepare_request(operation: str, payload: dict, deadline: float) -> dict:
        """模拟只读子进程的序列化边界，检查公开入口允许省略版本并返回已固定材料。"""

        assert operation == "artifact_prepare"
        request = CoverageArtifactSelection.model_validate(payload["selection"])
        prepared = reader._prepare_ftp_direct(request, payload["commit"], deadline)
        return prepared.model_dump(mode="json")

    monkeypatch.setattr("opentest.adapters.coverage._read_network", prepare_request)
    frozen = reader.prepare(selection, COMMIT, time.monotonic() + 10)
    assert frozen.selection.archive_version == "feature-current-2"
    assert selection.archive_version == ""
    assert frozen.artifact.path == candidate + "/actual.war"
    assert frozen.source.path == source
    # 不列应用根、其他环境或生产目录；后续下载只使用本次冻结的唯一文件。
    assert all(call.args[0] == base or call.args[0].startswith(base + "/") for call in client.cwd.call_args_list)


def test_ftp_large_directory_uses_bounded_independent_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """190 个版本必须查全且最多八个连接并发，不能只找首批或共享 CWD 会话。"""

    base = "/archive/demo.app/war/qa"
    versions = [f"version-{index}" for index in range(190)]
    candidate = f"{base}/{versions[-1]}/{COMMIT}"
    source = f"/archive/demo.app/qa/{versions[-1]}/{COMMIT}/out.tar.gz"
    directories = {base: versions, candidate: ["actual.war"]}
    directories.update({f"{base}/{version}": [COMMIT] if version == versions[-1] else ["b" * 40]
                        for version in versions})
    client = _archive_ftp(monkeypatch, directories, {candidate + "/actual.war": 42, source: 12})
    reader = CoverageArtifactReader()
    list_directory = reader._list_ftp_directory
    first_queries = Barrier(8, timeout=3)
    state_lock = Lock()
    seen_connections = set()

    def synchronized_listing(ftp, directory: str, deadline: float) -> list[str]:
        """让每批首次读取汇合，证明真实并发且连接数有界，不依赖耗时断言。"""

        if directory in {f"{base}/{version}" for version in versions}:
            with state_lock:
                first = id(ftp) not in seen_connections
                seen_connections.add(id(ftp))
            # 顺序执行或不足八个 worker 会在屏障超时，避免用瞬时 Mock 假证明并发。
            if first:
                first_queries.wait()
        return list_directory(ftp, directory, deadline)

    monkeypatch.setattr(reader, "_list_ftp_directory", synchronized_listing)
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    frozen = reader._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    assert frozen.selection.archive_version == versions[-1]
    assert len(seen_connections) == 8
    assert len(client.connections) == 10  # 父目录连接、八个查询连接、固定材料连接，三阶段不重叠。
    visited = [call.args[0] for call in client.cwd.call_args_list]
    assert sorted(visited) == sorted([base, candidate, *(f"{base}/{version}" for version in versions)])
    for connection in client.connections:
        connection.close.assert_called_once_with()


def test_ftp_empty_environment_does_not_start_query_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境没有版本时只读取父目录，明确缺失且不创建零工作者线程池。"""

    client = _archive_ftp(monkeypatch, {"/archive/demo.app/war/qa": []}, {})
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader()._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    assert failure.value.reason_code == "DEPLOYED_ARTIFACT_UNAVAILABLE"
    assert len(client.connections) == 1
    client.connections[0].close.assert_called_once_with()


def test_local_artifact_wrong_commit_cannot_fall_back_to_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """显式本地包版本不符时拒绝，不能因同时配置 FTP 而悄悄切换另一材料来源。"""

    selection = _make_materials(tmp_path).model_copy(update={"archive_host": "fixture.invalid"})
    network = Mock()
    monkeypatch.setattr("opentest.adapters.coverage._read_network", network)
    # 本地材料优先级保持兼容，自动归档仅适用于未选择本地实际包的配置。
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader().prepare(selection, "b" * 40, time.monotonic() + 10)
    assert failure.value.reason_code == "ARTIFACT_REVISION_MISMATCH"
    network.assert_not_called()


@pytest.mark.parametrize("matches,expected_reason", [(0, "DEPLOYED_ARTIFACT_UNAVAILABLE"), (2, "ARTIFACT_BUILD_AMBIGUOUS")])
def test_ftp_auto_selection_rejects_absent_or_same_time_commit_builds(
    matches: int, expected_reason: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有匹配或同commit最新构建时间并列都跳过，不由目录顺序或构建号决出胜者。"""

    base = "/archive/demo.app/war/qa"
    commits = [COMMIT] if matches else ["b" * 40]
    directories = {base: ["version-1", "version-2"],
        base + "/version-1": commits, base + "/version-2": commits}
    files = {}
    if matches:
        for version in ("version-1", "version-2"):
            directories[base + f"/{version}/" + COMMIT] = ["actual.war"]
            files[base + f"/{version}/" + COMMIT + "/actual.war"] = 42
    client = _archive_ftp(monkeypatch, directories, files)
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader()._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    assert failure.value.reason_code == expected_reason
    if matches:
        assert client.size.call_count == 2
    else:
        client.size.assert_not_called()
    client.connections[0].close.assert_called_once_with()


@pytest.mark.parametrize("failure", [ftplib.error_perm("550 denied"), ftplib.error_temp("450 busy"), TimeoutError()])
def test_ftp_auto_selection_does_not_hide_unreadable_other_versions(
    failure: Exception, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已找到一个构建后另一目录不可读，不能把权限或超时当无匹配而宣布唯一。"""

    base = "/archive/demo.app/war/qa"
    client = _archive_ftp(monkeypatch, {base: ["version-1", "version-2"],
        base + "/version-1": [COMMIT], base + "/version-2": failure}, {})
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    with pytest.raises(CoverageUnavailable) as error:
        CoverageArtifactReader()._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    expected_reason = "COVERAGE_PREFLIGHT_TIMEOUT" if isinstance(failure, TimeoutError) else "ARTIFACT_ARCHIVE_UNAVAILABLE"
    assert error.value.reason_code == expected_reason
    client.size.assert_not_called()


@pytest.mark.parametrize("entry", ["../prod", "/prod", "version/../../prod", ".", "..", "version\\prod"])
def test_ftp_auto_selection_rejects_unsafe_directory_names(entry: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """不安全版本名在进入目录前拒绝，不能借远端目录条目离开当前环境。"""

    base = "/archive/demo.app/war/qa"
    client = _archive_ftp(monkeypatch, {base: [entry]}, {})
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader()._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    assert failure.value.reason_code == "ARTIFACT_PATH_INVALID"
    client.cwd.assert_called_once_with(base)


@pytest.mark.parametrize("source_exists", [False, True])
def test_ftp_auto_selection_requires_readable_matching_source(source_exists: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """唯一 WAR 也不能省略配套源码；缺失或无权限时保留明确失败，不返回半份材料。"""

    base = "/archive/demo.app/war/qa"
    candidate = f"{base}/version-1/{COMMIT}"
    files = {candidate + "/actual.war": 42}
    if source_exists:
        files[f"/archive/demo.app/qa/version-1/{COMMIT}/out.tar.gz"] = ftplib.error_perm("550 denied")
    client = _archive_ftp(monkeypatch, {base: ["version-1"], base + "/version-1": [COMMIT],
        candidate: ["actual.war"]}, files)
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader()._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    assert failure.value.reason_code == "ARTIFACT_ARCHIVE_UNAVAILABLE"
    assert client.size.call_count == 2


@pytest.mark.parametrize("changes", [
    {"archive_environment": "prod"}, {"archive_environment": "uat"}, {"archive_root": "/archive/../prod"},
    {"app_uk": "/"}, {"archive_version": "../prod"},
])
def test_ftp_prepare_rejects_cross_environment_or_escaping_configuration(changes: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """错误环境及根目录、应用或固定版本逃逸均在启动网络子进程前拒绝。"""

    network = Mock()
    monkeypatch.setattr("opentest.adapters.coverage._read_network", network)
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader().prepare(selection.model_copy(update=changes), COMMIT, time.monotonic() + 10)
    assert failure.value.reason_code == "ARTIFACT_PATH_INVALID"
    network.assert_not_called()


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
            """按测试阶段滴流，自动查找仅父目录正常返回，查询连接模拟超时。"""

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
                directory = ""
                try:
                    while not stop.is_set():
                        command, _, argument = self.rfile.readline().decode("ascii").strip().partition(" ")
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
                            directory = argument
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
                                # 自动查找先完成父目录清单，实际滴流发生在八个独立版本查询内。
                                if stage == "ftp_auto_nlst" and directory.endswith("/war/qa"):
                                    connection.sendall(b"".join(f"version-{index}\r\n".encode() for index in range(8)))
                                elif stage == "ftp_success":
                                    reached.set()
                                    connection.sendall(b"application.war\r\n")
                                else:
                                    reached.set()
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


@pytest.mark.parametrize("stage", ["http_headers", "http_body", "ftp_welcome", "ftp_nlst", "ftp_auto_nlst", "ftp_stages"])
def test_network_total_deadline_kills_and_reaps_slow_collection(stage: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """总预算中止串行或并发滴流并回收整个采集进程，不得执行迟到 reset。"""

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
                    archive_root="/archive", archive_version="" if stage == "ftp_auto_nlst" else "version-1",
                    archive_username_ref="${ENV:COVERAGE_TEST_FTP_USER}",
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


def test_ftp_multiple_commit_builds_selects_latest_war_mtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """同commit多构建按唯一WAR的MDTM选择最新，不按目录名、版本号或文件名猜测。"""

    base = "/archive/demo.app/war/qa"
    older = base + "/version-old/" + COMMIT
    newer = base + "/version-new/" + COMMIT
    directories = {base: ["version-old", "version-new"],
        base + "/version-old": [COMMIT], base + "/version-new": [COMMIT],
        older: ["refundcore.war"], newer: ["refundcore.war"]}
    files = {older + "/refundcore.war": 41, newer + "/refundcore.war": 42,
             "/archive/demo.app/qa/version-new/" + COMMIT + "/out.tar.gz": 12}
    modified = {older + "/refundcore.war": "20261016165635", newer + "/refundcore.war": "20261022145722"}
    client = _archive_ftp(monkeypatch, directories, files, modified)
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    frozen = CoverageArtifactReader()._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    assert frozen.selection.archive_version == "version-new"
    assert frozen.artifact.path == newer + "/refundcore.war"
    assert frozen.source.path == "/archive/demo.app/qa/version-new/" + COMMIT + "/out.tar.gz"
    # 多构建才读取候选WAR时间；选中的WAR和源码身份随后再次固定。
    assert client.size.call_count == 4
    assert client.sendcmd.call_count == 4


def test_ftp_multiple_commit_builds_with_same_war_mtime_stay_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    """最新构建时间并列时仍按歧义跳过，不能用版本名或目录顺序打破平局。"""

    base = "/archive/demo.app/war/qa"
    directories = {base: ["version-1", "version-2"],
        base + "/version-1": [COMMIT], base + "/version-2": [COMMIT],
        base + "/version-1/" + COMMIT: ["refundcore.war"], base + "/version-2/" + COMMIT: ["refundcore.war"]}
    files = {base + "/version-1/" + COMMIT + "/refundcore.war": 41,
             base + "/version-2/" + COMMIT + "/refundcore.war": 42}
    client = _archive_ftp(monkeypatch, directories, files)
    selection = CoverageArtifactSelection(app_uk="demo.app", archive_host="fixture.invalid", archive_root="/archive",
        archive_username_ref="${ENV:OPENTEST_FTP_USER}", archive_password_ref="${ENV:OPENTEST_FTP_PASSWORD}")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader()._prepare_ftp_direct(selection, COMMIT, time.monotonic() + 10)
    assert failure.value.reason_code == "ARTIFACT_BUILD_AMBIGUOUS"
    assert client.size.call_count == 2
    client.connections[0].close.assert_called_once_with()
