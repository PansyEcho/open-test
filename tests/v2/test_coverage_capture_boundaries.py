"""覆盖采集格式、凭据和异常边界测试；仅使用临时文件与内存 HTTP 响应。"""

from __future__ import annotations

import io
import subprocess
import tarfile
import time
from email.message import Message
from pathlib import Path
from unittest.mock import Mock
from urllib.request import HTTPHandler, build_opener
from urllib.response import addinfourl
from zipfile import ZipFile

import pytest

from opentest.adapters import coverage
from opentest.adapters.coverage import (
    CoverageArtifactReader, CoverageUnavailable, JacocoCollector, SkyeyeInstanceDiscovery,
)
from opentest.domain.coverage import (
    CoverageArtifactSelection, DiscoveredCoverageInstance,
)
from opentest.domain.models import utc_now


COMMIT = "a" * 40


def _selection(directory: Path, layout: str) -> CoverageArtifactSelection:
    """为指定部署布局建立同版本主源码和假类字节，供筛选测试而非 JaCoCo 执行。"""

    artifact = directory / ("application.war" if layout == "WAR" else "application.jar")
    prefix = {"WAR": "WEB-INF/", "BOOT": "BOOT-INF/", "PLAIN": ""}[layout]
    with ZipFile(artifact, "w") as archive:
        classes = prefix + "classes/" if prefix else ""
        archive.writestr(classes + "demo/Service.class", b"service")
        archive.writestr(classes + "demo/Service$Nested.class", b"nested")
        archive.writestr(classes + "thirdparty/Other.class", b"thirdparty")
        if prefix:
            # 入选业务依赖必须保留尚未加载的类，外部依赖及 Boot 启动器不进入业务范围。
            jar_bytes = io.BytesIO()
            with ZipFile(jar_bytes, "w") as library:
                library.writestr("demo/biz/Business.class", b"business")
                library.writestr("demo/biz/Unloaded.class", b"unloaded")
            archive.writestr(prefix + "lib/business.jar", jar_bytes.getvalue())
            external_bytes = io.BytesIO()
            with ZipFile(external_bytes, "w") as library:
                library.writestr("thirdparty/Dependency.class", b"external")
            archive.writestr(prefix + "lib/external.jar", external_bytes.getvalue())
            archive.writestr("org/springframework/boot/loader/Launcher.class", b"launcher")
    source = directory / "source.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        for class_name in ("demo/Service", "demo/biz/Business"):
            content = b"package demo; class Placeholder {}"
            member = tarfile.TarInfo(f"app/src/main/java/{class_name}.java")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return CoverageArtifactSelection(app_uk="demo.app", artifact_path=str(artifact),
        source_archive_path=str(source), artifact_commit=COMMIT)


@pytest.mark.parametrize("layout", ["WAR", "BOOT", "PLAIN"])
def test_local_materials_support_all_declared_layouts(tmp_path: Path, layout: str) -> None:
    """三种实际包均物化业务输入，保留内部类和业务依赖的未加载类。"""

    reader = CoverageArtifactReader()
    frozen = reader.prepare(_selection(tmp_path, layout), COMMIT, time.monotonic() + 10)
    artifact = reader.materialize(frozen, tmp_path / "analysis")
    direct = next(path for path in artifact.classfiles if path.is_dir())
    assert (direct / "demo/Service.class").read_bytes() == b"service"
    assert (direct / "demo/Service$Nested.class").read_bytes() == b"nested"
    assert not (direct / "thirdparty").exists()
    assert not (direct / "org").exists()
    libraries = [path for path in artifact.classfiles if path.is_file()]
    if layout == "PLAIN":
        assert libraries == []
    else:
        assert [path.name for path in libraries] == ["business.jar"]
        with ZipFile(libraries[0]) as library:
            assert "demo/biz/Unloaded.class" in library.namelist()


@pytest.mark.parametrize("member", [
    "BOOT-INF/classes/../../outside.class", "../outside.class", "/outside.class",
    "BOOT-INF/lib/../outside.jar",
])
def test_deployment_members_cannot_escape_output(tmp_path: Path, member: str) -> None:
    """新增布局沿用路径安全边界，连不属于源码的越界成员也不能被静默接受。"""

    artifact = tmp_path / "unsafe.jar"
    with ZipFile(artifact, "w") as archive:
        archive.writestr(member, b"unsafe")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader._extract_business_classes(artifact, tmp_path / "classes", {"demo/Service"})
    assert failure.value.reason_code == "ARTIFACT_PATH_INVALID"
    assert not (tmp_path / "outside.class").exists()


def test_duplicate_classes_across_layouts_are_rejected(tmp_path: Path) -> None:
    """混合归档含同一业务类时不得让后写内容静默替换先写字节码。"""

    artifact = tmp_path / "duplicate.jar"
    with ZipFile(artifact, "w") as archive:
        archive.writestr("BOOT-INF/classes/demo/Service.class", b"boot")
        archive.writestr("demo/Service.class", b"root")
    with pytest.raises(CoverageUnavailable) as failure:
        CoverageArtifactReader._extract_business_classes(artifact, tmp_path / "classes", {"demo/Service"})
    assert failure.value.reason_code == "ARTIFACT_DUPLICATE_CLASS"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("destination", ["http://other.example/collect", "http://logs.example/other"])
def test_skyeye_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch, status: int, destination: str,
) -> None:
    """使用真实 urllib 重定向分派和内存响应，确认 token 不产生第二次 HTTP 请求。"""

    requests = []

    class InMemoryHTTP(HTTPHandler):
        """代替网络传输返回 3xx，保留 urllib 的错误/重定向处理链。"""

        def http_open(self, request):
            """记录唯一请求并返回重定向响应；不建立 socket 或持久化凭据。"""

            requests.append(request)
            headers = Message()
            headers["Location"] = destination
            response = addinfourl(io.BytesIO(b""), headers, request.full_url, status)
            response.msg = "Redirect"
            return response

    opener = build_opener(InMemoryHTTP(), coverage._RejectSkyeyeRedirects())
    monkeypatch.setattr(coverage, "build_opener", lambda *_: opener)
    with pytest.raises(CoverageUnavailable) as failure:
        SkyeyeInstanceDiscovery("http://logs.example/query")._query_direct(
            {}, "private-test-token", time.monotonic() + 10)
    assert len(requests) == 1
    assert requests[0].full_url == "http://logs.example/query"
    assert requests[0].get_header("Token") == "private-test-token"
    assert failure.value.reason_code == "SKYEYE_QUERY_FAILED"
    assert "private-test-token" not in str(failure.value)


@pytest.mark.parametrize("error", [RuntimeError("failed"), KeyboardInterrupt(), SystemExit()])
def test_reset_failure_always_cleans_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException,
) -> None:
    """reset 未返回引用时，普通失败及中断均由采集器清理目录且不重复发送清零。"""

    workspace = tmp_path / "reset"
    workspace.mkdir()
    monkeypatch.setattr(coverage.tempfile, "mkdtemp", lambda **_: str(workspace))
    collector = JacocoCollector("java", tmp_path / "cli.jar")
    run = Mock(side_effect=error)
    monkeypatch.setattr(collector, "run", run)
    target = DiscoveredCoverageInstance(ip="127.0.0.1", port=6300, app_uk="demo", log_time=utc_now())
    with pytest.raises(type(error)):
        collector.reset(target, time.monotonic() + 10)
    assert not workspace.exists()
    run.assert_called_once()


@pytest.mark.parametrize(("arguments", "reason"), [
    (["dump", "--reset"], "COVERAGE_PREFLIGHT_TIMEOUT"),
    (["dump"], "COVERAGE_CAPTURE_TIMEOUT"),
    (["classinfo"], "COVERAGE_ANALYSIS_TIMEOUT"),
    (["report"], "COVERAGE_ANALYSIS_TIMEOUT"),
])
@pytest.mark.parametrize("expired_before_start", [True, False])
def test_cli_deadline_is_classified_by_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str],
    reason: str, expired_before_start: bool,
) -> None:
    """预算已过期和命令执行中超时使用同一阶段原因码，不把后置分析误报为准备超时。"""

    cli = tmp_path / "cli.jar"
    cli.touch()
    run = Mock(side_effect=subprocess.TimeoutExpired("java", 1))
    monkeypatch.setattr(coverage.subprocess, "run", run)
    deadline = time.monotonic() + (-1 if expired_before_start else 10)
    with pytest.raises(CoverageUnavailable) as failure:
        JacocoCollector("java", cli).run(arguments, deadline)
    assert failure.value.reason_code == reason
    assert run.call_count == (0 if expired_before_start else 1)


def test_materialization_expiry_is_not_preflight_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dump 后材料复制超时归为材料阶段，不能暗示十秒前置预算不足。"""

    reader = CoverageArtifactReader()
    frozen = reader.prepare(_selection(tmp_path, "PLAIN"), COMMIT, time.monotonic() + 10)
    clock = iter([0.0, 0.0, 181.0])
    monkeypatch.setattr(coverage.time, "monotonic", lambda: next(clock))
    with pytest.raises(CoverageUnavailable) as failure:
        reader.materialize(frozen, tmp_path / "analysis")
    assert failure.value.reason_code == "COVERAGE_ARTIFACT_TIMEOUT"


def test_ftp_download_socket_timeout_keeps_material_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """FTP 下载期间 socket 超时按材料阶段返回，并关闭连接且不暴露远端响应。"""

    client = Mock()
    client.connect.side_effect = TimeoutError("private server details")
    monkeypatch.setattr(coverage.ftplib, "FTP", Mock(return_value=client))
    selection = CoverageArtifactSelection(app_uk="demo", archive_host="archive.example")
    with pytest.raises(CoverageUnavailable) as failure:
        with CoverageArtifactReader()._ftp(selection, time.monotonic() + 10, "ARTIFACT"):
            pytest.fail("a failed connection cannot be yielded")
    assert failure.value.reason_code == "COVERAGE_ARTIFACT_TIMEOUT"
    assert "private server details" not in str(failure.value)
    client.close.assert_called_once()
