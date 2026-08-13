"""验证引导式系统接入、Token本地边界与真实扫描目录。"""

from __future__ import annotations

import logging
import stat
from pathlib import Path

import yaml
import pytest
from fastapi.testclient import TestClient

from opentest.adapters.environment_config import LocalSystemSettingsStore
from opentest.api import create_app
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import SystemDefinition


BOOKING_SYSTEM_ID = "train-booking-core"
EXPECTED_BOOKING_COUNTS = {
    "facade": 90,
    "job": 36,
    "mq_consumer": 5,
    "state_machine": 1,
    "state_transition": 19,
}


def test_registration_defaults_to_dotted_source_basename_and_never_echoes_token(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    """注册应使用源码目录名作为ID，并让Token只进入0600本地文件。

    Args:
        tmp_path: Pytest提供的隔离源码和知识目录。
        monkeypatch: 替换后台扫描提交，避免接入契约测试启动scriptgen。
        caplog: 捕获日志以验证Token不会进入诊断输出。
    """

    source = tmp_path / "travelsystem.java.dsf.example_core"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    token = "qa-token-guided-onboarding"

    def submit_scan_without_execution(request):
        """记录不含Token的扫描请求，并返回正常本地任务记录。"""

        return application.tasks.submit(
            "source-scan-contract",
            request.system_id,
            lambda: {"entry_types": request.entry_types},
        )

    monkeypatch.setattr(application, "submit_source_scan", submit_scan_without_execution)
    monkeypatch.setattr(application, "ensure_scanner_ready", lambda: None)
    with caplog.at_level(logging.INFO), TestClient(create_app(application), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v2/systems",
            json={
                "name": "示例DSF系统",
                "source_path": str(source),
                "service_type": "DSF",
                "qa_labrador_token": token,
                "qa_gateway_prefix": "http://servicegw.qa.example/gateway/example/v2",
            },
        )

    body = response.json()
    assert response.status_code == 201
    assert body["system"]["system_id"] == source.name
    assert body["scan_task"]["system_id"] == source.name
    assert token not in response.text
    assert token not in caplog.text

    settings_path = tmp_path / "knowledge/.opentest/environments" / source.name / "qa.yaml"
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
    assert token in settings_path.read_text(encoding="utf-8")
    task_text = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "knowledge/.opentest/tasks").glob("*.json"))
    assert token not in task_text


def test_local_settings_preserve_fixture_and_support_environment_reference(tmp_path: Path, monkeypatch) -> None:
    """页面保存Token不得覆盖Fixture，旧环境引用仍可安全回显解析值。

    Args:
        tmp_path: Pytest提供的隔离本地配置目录。
        monkeypatch: 注入兼容环境引用的测试Token。
    """

    environment_root = tmp_path / "environments"
    settings_path = environment_root / BOOKING_SYSTEM_ID / "qa.yaml"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        yaml.safe_dump(
            {
                "system_id": BOOKING_SYSTEM_ID,
                "environment": "qa",
                "values": {
                    "fixtures": {"supplier": "fixture-ebk"},
                    "tool_environment": {"LABRADOR_TOKEN": "${ENV:OPENTEST_QA_LABRADOR_TOKEN}"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTEST_QA_LABRADOR_TOKEN", "environment-token")
    store = LocalSystemSettingsStore(environment_root)

    assert store.read(BOOKING_SYSTEM_ID).qa_labrador_token == "environment-token"
    store.write(BOOKING_SYSTEM_ID, "page-token")
    payload = yaml.safe_load(settings_path.read_text(encoding="utf-8"))

    assert payload["values"]["fixtures"] == {"supplier": "fixture-ebk"}
    assert payload["values"]["tool_environment"]["LABRADOR_TOKEN"] == "page-token"
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600


def test_local_settings_api_rejects_non_loopback_client(tmp_path: Path) -> None:
    """非回环请求不得读取或覆盖允许完整回显的本地Token。"""

    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.register_system(
        SystemDefinition(system_id=BOOKING_SYSTEM_ID, name="火车票预订", source_path=str(source))
    )
    application.save_local_settings(BOOKING_SYSTEM_ID, "local-only-token")

    with TestClient(create_app(application), client=("10.20.30.40", 50000)) as client:
        read_response = client.get(f"/api/v2/systems/{BOOKING_SYSTEM_ID}/local-settings")
        write_response = client.put(
            f"/api/v2/systems/{BOOKING_SYSTEM_ID}/local-settings",
            json={"qa_labrador_token": "replacement"},
        )

    assert read_response.status_code == 409
    assert write_response.status_code == 409
    assert "local-only-token" not in read_response.text
    assert "replacement" not in write_response.text


def test_registration_and_update_reject_non_loopback_token_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """系统注册和更新只要包含Token就必须应用同一回环写门禁。

    Args:
        tmp_path: Pytest提供的隔离源码和知识目录。
        monkeypatch: 替换后台扫描提交，确保安全边界测试不启动scriptgen。
    """

    source = tmp_path / "remote-token-source"
    source.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")

    def submit_scan_without_execution(request):
        """返回不会启动外部进程的扫描任务记录。"""

        return application.tasks.submit("source-scan-contract", request.system_id, lambda: {})

    monkeypatch.setattr(application, "submit_source_scan", submit_scan_without_execution)
    monkeypatch.setattr(application, "ensure_scanner_ready", lambda: None)
    application.register_system(
        SystemDefinition(system_id=BOOKING_SYSTEM_ID, name="火车票预订", source_path=str(source))
    )
    with TestClient(create_app(application), client=("10.20.30.40", 50000)) as client:
        registration = client.post(
            "/api/v2/systems",
            json={
                "name": "远程系统",
                "source_path": str(source),
                "qa_labrador_token": "remote-registration-token",
                "qa_gateway_prefix": "http://servicegw.qa.example/gateway/remote/v2",
            },
        )
        update = client.put(
            f"/api/v2/systems/{BOOKING_SYSTEM_ID}",
            json={
                "name": "火车票预订",
                "source_path": str(source),
                "qa_labrador_token": "remote-update-token",
                "qa_gateway_prefix": "http://servicegw.qa.example/gateway/booking/v2",
            },
        )

    assert registration.status_code == 409
    assert update.status_code == 409
    environment_root = tmp_path / "knowledge/.opentest/environments"
    assert not environment_root.exists()


def test_existing_plaintext_settings_are_tightened_before_read(tmp_path: Path) -> None:
    """旧版0644明文配置必须在内容读取前自动收紧为0600。

    Args:
        tmp_path: Pytest提供的隔离本地环境目录。
    """

    environment_root = tmp_path / "environments"
    settings_path = environment_root / BOOKING_SYSTEM_ID / "qa.yaml"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        yaml.safe_dump(
            {
                "system_id": BOOKING_SYSTEM_ID,
                "environment": "qa",
                "values": {"tool_environment": {"LABRADOR_TOKEN": "legacy-plaintext-token"}},
            }
        ),
        encoding="utf-8",
    )
    settings_path.chmod(0o644)

    settings = LocalSystemSettingsStore(environment_root).read(BOOKING_SYSTEM_ID)

    assert settings.qa_labrador_token == "legacy-plaintext-token"
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("link_kind", ["file", "directory"])
def test_local_settings_reject_cross_system_symlinks(tmp_path: Path, link_kind: str) -> None:
    """文件或系统目录符号链接都不得跨系统读取Token与Fixture。

    Args:
        tmp_path: Pytest提供的隔离本地环境目录。
        link_kind: 本轮构造最终文件链接或系统目录链接。
    """

    environment_root = tmp_path / "environments"
    target_path = environment_root / "target-system/qa.yaml"
    target_path.parent.mkdir(parents=True)
    target_path.write_text(
        yaml.safe_dump(
            {
                "system_id": "target-system",
                "environment": "qa",
                "values": {"tool_environment": {"LABRADOR_TOKEN": "target-token"}},
            }
        ),
        encoding="utf-8",
    )
    source_directory = environment_root / BOOKING_SYSTEM_ID
    if link_kind == "file":
        source_directory.mkdir(parents=True)
        (source_directory / "qa.yaml").symlink_to(target_path)
    else:
        source_directory.symlink_to(target_path.parent, target_is_directory=True)

    store = LocalSystemSettingsStore(environment_root)
    with pytest.raises(KnowledgeValidationError, match="regular file|real directory"):
        store.read(BOOKING_SYSTEM_ID)
    with pytest.raises(KnowledgeValidationError, match="regular file|real directory"):
        store.write(BOOKING_SYSTEM_ID, "replacement-token")

    assert "target-token" in target_path.read_text(encoding="utf-8")
    assert "replacement-token" not in target_path.read_text(encoding="utf-8")


def test_real_booking_manifest_projects_complete_catalog_without_changing_legacy_id() -> None:
    """真实Booking Manifest必须向页面投影90/36/5/1/19且保留现有系统ID。"""

    repository_root = Path(__file__).parents[2]
    latest_pointer = repository_root / "open-test-knowledge/.opentest/scans/train-booking-core/latest.json"
    if not latest_pointer.exists():
        pytest.skip("真实Booking扫描产物是可重建本地索引，当前工作区尚未生成")
    application = OpenTestApplication(repository_root / "open-test-knowledge")
    try:
        system = application.store.get_system(BOOKING_SYSTEM_ID)
        catalog = application.get_scan_catalog(BOOKING_SYSTEM_ID, "latest")
        resources = application.list_resources(BOOKING_SYSTEM_ID)
    finally:
        application.close()

    assert system.system_id == BOOKING_SYSTEM_ID
    assert {key: catalog.counts[key] for key in EXPECTED_BOOKING_COUNTS} == EXPECTED_BOOKING_COUNTS
    assert len(catalog.targets) >= sum(EXPECTED_BOOKING_COUNTS.values())
    mq_clusters = [item["definition"] for item in resources if item["definition"]["kind"] == "mq"]
    assert len(mq_clusters) == 1
    assert len(mq_clusters[0]["interactions"]) == 19
    assert len(mq_clusters[0]["legacy_resource_ids"]) == 19


def test_registered_token_is_absent_from_snapshots_reports_and_agent_evidence(tmp_path: Path) -> None:
    """本地Token值不得出现在可共享Snapshot、报告或Agent证据文件中。"""

    token = "qa-token-never-share"
    knowledge_root = tmp_path / "knowledge"
    source = tmp_path / "source"
    source.mkdir()
    application = OpenTestApplication(knowledge_root)
    try:
        application.register_system(
            SystemDefinition(system_id=BOOKING_SYSTEM_ID, name="火车票预订", source_path=str(source))
        )
        application.save_local_settings(BOOKING_SYSTEM_ID, token)
    finally:
        application.close()

    # 本地环境目录是唯一允许含Token的区域；其余派生或Git资产全部检查原始文本。
    excluded_root = knowledge_root / ".opentest/environments"
    checked_texts: list[str] = []
    for path in knowledge_root.rglob("*"):
        if not path.is_file() or path.is_relative_to(excluded_root):
            continue
        try:
            checked_texts.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    assert token not in "\n".join(checked_texts)
