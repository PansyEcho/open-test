"""验证系统级天网配置及按需读取的覆盖连接，不访问业务系统或真实凭据。"""

from pathlib import Path
import stat

import pytest
import yaml

from opentest.adapters.environment_config import LocalEnvironmentLoader, LocalSystemSettingsStore
from opentest.domain.errors import KnowledgeValidationError


def test_system_settings_preserve_environment_and_omitted_token(tmp_path: Path) -> None:
    """局部更新只改当前系统；省略保留凭据、显式空串清除且文件权限为 0600。

    Args:
        tmp_path: 隔离本地配置目录。
    """

    store = LocalSystemSettingsStore(tmp_path)
    system_root = tmp_path / "refund"
    system_root.mkdir()
    (system_root / "qa.yaml").write_text("resource_config_environment: test\n", encoding="utf-8")
    (system_root / "uat.yaml").write_text("resource_config_environment: uat\n", encoding="utf-8")
    (system_root / "system.yaml").write_text("other_setting: preserved\n", encoding="utf-8")
    # 多次保存模拟只改名称/appId、凭据轮换与清除，QA/UAT 原文件不得被重写。
    store.write_skyeye_settings("refund", "101", "fake-token")
    saved = store.write_skyeye_settings("refund", "102")
    assert saved.skyeye_app_id == "102"
    assert saved.skyeye_api_token == "fake-token"
    assert "fake-token" not in repr(saved)
    assert "skyeye_api_token" not in saved.model_dump()
    assert store.read_skyeye_settings("other").skyeye_api_token == ""
    assert not (tmp_path / "other").exists()
    assert stat.S_IMODE((system_root / "system.yaml").stat().st_mode) == 0o600
    payload = yaml.safe_load((system_root / "system.yaml").read_text(encoding="utf-8"))
    assert payload["other_setting"] == "preserved"
    assert (system_root / "qa.yaml").read_text(encoding="utf-8") == "resource_config_environment: test\n"
    assert (system_root / "uat.yaml").read_text(encoding="utf-8") == "resource_config_environment: uat\n"
    assert store.write_skyeye_settings("refund", skyeye_api_token="").skyeye_api_token == ""


def test_environment_reference_stays_private_and_is_not_rewritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境引用在内存解析；修改 appId 后仍保存引用，缺失变量表示未就绪。

    Args:
        tmp_path: 隔离设置根目录。
        monkeypatch: 只注入测试专用环境变量。
    """

    store = LocalSystemSettingsStore(tmp_path)
    monkeypatch.setenv("TEST_SKYEYE_TOKEN", "fake-resolved-token")
    saved = store.write_skyeye_settings("refund", "101", "${ENV:TEST_SKYEYE_TOKEN}")
    assert saved.skyeye_api_token == "fake-resolved-token"
    assert "fake-resolved-token" not in saved.model_dump_json()
    # 非凭据更新不得把解析后的明文写回引用文件。
    store.write_skyeye_settings("refund", "102")
    content = (tmp_path / "refund" / "system.yaml").read_text(encoding="utf-8")
    assert "${ENV:TEST_SKYEYE_TOKEN}" in content
    assert "fake-resolved-token" not in content
    monkeypatch.delenv("TEST_SKYEYE_TOKEN")
    assert store.read_skyeye_settings("refund").skyeye_api_token == ""


def test_skyeye_settings_reject_unsafe_paths_and_bad_private_values(tmp_path: Path) -> None:
    """悬空链接和非法类型不能绕过本地配置边界，错误不得包含原始私有输入。

    Args:
        tmp_path: 隔离配置与链接目标目录。
    """

    store = LocalSystemSettingsStore(tmp_path)
    system_root = tmp_path / "refund"
    system_root.mkdir()
    path = system_root / "system.yaml"
    path.symlink_to(tmp_path / "missing.yaml")
    # 即使链接目标不存在，也不能当成空设置或覆盖链接目标。
    with pytest.raises(KnowledgeValidationError, match="regular file"):
        store.read_skyeye_settings("refund")
    with pytest.raises(KnowledgeValidationError):
        store.write_skyeye_settings("../escape", "101", "fake-token")
    path.unlink()
    path.write_text("skyeye_api_token: {secret: fake-sensitive-input}\n", encoding="utf-8")
    with pytest.raises(KnowledgeValidationError) as failure:
        store.read_skyeye_settings("refund")
    assert "fake-sensitive-input" not in str(failure.value)


def test_coverage_connection_is_opt_in_and_preserves_archive_references(tmp_path: Path) -> None:
    """覆盖配置只有增强读取时校验，归档引用不在设置层解析。

    Args:
        tmp_path: 隔离 QA 配置目录。
    """

    store = LocalSystemSettingsStore(tmp_path)
    root = tmp_path / "refund"
    root.mkdir()
    path = root / "qa.yaml"
    path.write_text("resource_config_environment: qa\ncoverage_connection:\n  archive_password_ref: ${ENV:NOT_SET}\n", encoding="utf-8")
    connection = store.read_coverage_connection("refund")
    assert connection is not None
    assert connection.archive_password_ref == "${ENV:NOT_SET}"
    assert store.read_coverage_connection("refund", "uat") is None
    # 与覆盖无关的普通资源设置，不能因私有连接填写错误而失效。
    path.write_text("resource_config_environment: qa\ncoverage_connection:\n  jacoco_port: invalid\n", encoding="utf-8")
    assert store.read_resource_settings("refund").resource_config_environment == "qa"
    assert LocalEnvironmentLoader(tmp_path).load("refund", "qa").coverage_connection is None
    with pytest.raises(KnowledgeValidationError, match="invalid local coverage connection"):
        store.read_coverage_connection("refund")
