"""验证Java QA Worker子进程协议、权限边界和稳定错误。"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from opentest.adapters.qa_worker import QaWorkerClient
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import LocalEnvironmentDefinition, OracleRequest


BOOKING_CORE_SYSTEM_ID = "travelsystem.java.dsf.supplychain.booking.core"


def _client_fixture(tmp_path: Path, runner: Any) -> QaWorkerClient:
    """创建最小Worker Jar、操作目录和可注入进程执行器。"""

    worker_jar = tmp_path / "worker.jar"
    worker_jar.write_bytes(b"test-worker")
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(f"system_id: {BOOKING_CORE_SYSTEM_ID}\noperations: []\n", encoding="utf-8")
    return QaWorkerClient(
        worker_jar,
        catalog,
        process_runner=runner,
        application_name=BOOKING_CORE_SYSTEM_ID,
    )


def _request(**overrides: Any) -> OracleRequest:
    """构造兼容当前Oracle契约的固定订单查询请求。"""

    payload = {
        "oracle_id": "oracle:order-primary",
        "system_id": BOOKING_CORE_SYSTEM_ID,
        "kind": "mysql",
        "connection": "booking-main-mysql",
        "operation": "order.primary_detail",
        "params": {"order_serial_no": "HT-TEST-1"},
        "assertions": {},
    }
    payload.update(overrides)
    return OracleRequest.model_validate(payload)


def _environment(name: str = "qa") -> LocalEnvironmentDefinition:
    """创建不含数据库连接参数的本地环境范围定义。"""

    return LocalEnvironmentDefinition(system_id=BOOKING_CORE_SYSTEM_ID, environment=name)


def test_worker_client_uses_file_protocol_and_returns_projected_value(tmp_path: Path, monkeypatch) -> None:
    """客户端应通过文件协议调用Worker并只返回响应中的白名单value。

    Args:
        tmp_path: Pytest提供的隔离Worker制品目录。
        monkeypatch: 用于注入必须被子进程环境白名单剔除的模拟云凭据。
    """

    captured: dict[str, Any] = {}
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-reach-worker")
    monkeypatch.setenv("OPENTEST_API_KEY", "must-not-reach-worker")

    def successful_runner(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        """读取请求并写入匹配request_id的成功响应。"""

        captured["command"] = command
        captured["options"] = options
        request_path = Path(command[command.index("--request-file") + 1])
        response_path = Path(command[command.index("--response-file") + 1])
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        captured["request"] = request_payload
        captured["response_precreated"] = response_path.is_file()
        captured["response_mode"] = stat.S_IMODE(response_path.stat().st_mode)
        response_path.write_text(
            json.dumps(
                {
                    "request_id": request_payload["request_id"],
                    "status": "success",
                    "value": {"order_state": "TICKETING"},
                    "elapsed_ms": 12,
                }
            ),
            encoding="utf-8",
        )
        response_path.chmod(0o600)
        return subprocess.CompletedProcess(command, 0, stdout="sdk-log", stderr="")

    client = _client_fixture(tmp_path, successful_runner)
    value = client.execute(_request(), _environment(), 10)

    assert value == {"order_state": "TICKETING"}
    assert captured["request"]["resource_id"] == "booking-main-mysql"
    assert captured["request"]["operation_id"] == "order.primary_detail"
    assert "sql" not in captured["request"]
    assert captured["options"]["check"] is False
    assert "AWS_ACCESS_KEY_ID" not in captured["options"]["env"]
    assert "OPENTEST_API_KEY" not in captured["options"]["env"]
    assert set(captured["options"]["env"]) <= {"PATH", "JAVA_HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR"}
    assert captured["command"][0] == "java"
    assert captured["response_precreated"] is True
    assert captured["response_mode"] == 0o600


def test_worker_client_rejects_non_qa_environment_before_process(tmp_path: Path) -> None:
    """非QA环境必须在启动Java前被拒绝。"""

    def unexpected_runner(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        """若安全校验错误地启动进程则立即暴露测试失败。"""

        raise AssertionError(f"worker must not start: {command} {options}")

    client = _client_fixture(tmp_path, unexpected_runner)
    with pytest.raises(KnowledgeValidationError, match="qa environment"):
        client.execute(_request(), _environment("prod"), 10)


def test_worker_client_requires_profile_application_identity_before_process(tmp_path: Path) -> None:
    """公开目录不能替代Capability Profile批准的远程配置应用身份。"""

    def unexpected_runner(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        """若缺少Profile身份仍启动进程则立即暴露测试失败。"""

        raise AssertionError(f"worker must not start: {command} {options}")

    configured = _client_fixture(tmp_path, unexpected_runner)
    client = QaWorkerClient(configured.worker_jar, configured.catalog_path)

    # 身份缺失必须在Java进程和任何远程配置初始化之前被拒绝。
    with pytest.raises(KnowledgeValidationError, match="application identity"):
        client.execute(_request(), _environment(), 10)


@pytest.mark.parametrize("forbidden_key", ["sql", "command", "host", "password", "token"])
def test_worker_client_rejects_infrastructure_parameters(tmp_path: Path, forbidden_key: str) -> None:
    """Case不得通过业务参数向Worker注入SQL、命令、连接或密钥。"""

    def unexpected_runner(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        """若禁用参数未在协议边界拦截则立即失败。"""

        raise AssertionError(f"worker must not start: {command} {options}")

    client = _client_fixture(tmp_path, unexpected_runner)
    request = _request(params={forbidden_key: "unsafe"})
    with pytest.raises(KnowledgeValidationError, match="forbidden"):
        client.execute(request, _environment(), 10)
