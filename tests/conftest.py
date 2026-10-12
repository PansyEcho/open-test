"""为构造完整应用的测试提供每个用例独立、用后删除的真实MySQL元数据库。"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest
import yaml

import opentest.application.foundation as foundation
from opentest.adapters.mysql_metadata import MySqlMetadataStore


TEST_MYSQL_CONFIG_ENV = "OPENTEST_MYSQL_TEST_CONFIG"
PRODUCTION_METADATA_LOADER = foundation.load_metadata_store
# 收集阶段（导入opentest.api构造模块级app）共用的会话级隔离资源，unconfigure时清除。
_COLLECTION_ISOLATION: dict = {"stores": [], "database": "", "root": None, "previous_root": None}


def _workspace_id(knowledge_root: Path | str) -> str:
    """按生产配置归属规则为知识根派生稳定测试workspace身份。

    Args:
        knowledge_root: 应用知识根；同一父目录共享工作台身份。

    Returns:
        `test-`前缀的稳定ASCII身份。
    """

    owner = str(Path(knowledge_root).expanduser().resolve().parent)
    return "test-" + hashlib.sha256(owner.encode("utf-8")).hexdigest()[:24]


def _test_mysql_configuration() -> dict:
    """读取测试专用MySQL配置；未配置时返回空映射。

    Returns:
        测试实例连接配置，不含工作台真实元数据配置。
    """

    configuration_path = os.environ.get(TEST_MYSQL_CONFIG_ENV, "")
    if not configuration_path:
        return {}
    return yaml.safe_load(Path(configuration_path).read_text(encoding="utf-8"))


def _collection_store(knowledge_root: Path | str) -> MySqlMetadataStore:
    """为测试收集阶段构造的应用返回会话级临时库，绝不读取工作台真实元数据配置。

    Args:
        knowledge_root: 收集阶段应用的知识根，已被重定向到会话临时目录。

    Returns:
        连接会话临时库的存储实例；首次调用时建库建表。

    Side Effects:
        首次调用在测试实例创建`ot_test_*`库；未配置测试MySQL时跳过触发导入的模块。
    """

    base_configuration = _test_mysql_configuration()
    if not base_configuration:
        pytest.skip(f"需要{TEST_MYSQL_CONFIG_ENV}指向测试专用MySQL配置", allow_module_level=True)
    first_store = not _COLLECTION_ISOLATION["database"]
    if first_store:
        database = f"ot_test_{uuid.uuid4().hex[:16]}"
        admin = MySqlMetadataStore(base_configuration, "test-admin")
        admin.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
        admin.close()
        # 建库成功即登记，建表失败时unconfigure仍会删除该随机库。
        _COLLECTION_ISOLATION["database"] = database
    store = MySqlMetadataStore(
        {**base_configuration, "database": _COLLECTION_ISOLATION["database"]}, _workspace_id(knowledge_root),
    )
    _COLLECTION_ISOLATION["stores"].append(store)
    if first_store:
        store.install_schema()
    return store


def pytest_configure(config):
    """登记用例标记，并在收集前隔离导入期构造的模块级应用。

    `opentest.api`导入时即构造默认app；若不在收集前替换，测试导入会连接工作台真实共享库，
    并以真实workspace身份执行启动恢复。

    Args:
        config: pytest全局配置。

    Side Effects:
        把`OPENTEST_KNOWLEDGE_ROOT`指向会话临时目录，并替换应用的元数据读取入口。
    """

    config.addinivalue_line(
        "markers",
        "production_metadata_loader: 不替换应用的MySQL配置读取，用于验证缺失配置时的启动失败",
    )
    session_root = Path(tempfile.mkdtemp(prefix="opentest-pytest-"))
    _COLLECTION_ISOLATION["root"] = session_root
    _COLLECTION_ISOLATION["previous_root"] = os.environ.get("OPENTEST_KNOWLEDGE_ROOT")
    os.environ["OPENTEST_KNOWLEDGE_ROOT"] = str(session_root / "knowledge")
    foundation.load_metadata_store = _collection_store


def pytest_unconfigure(config):
    """恢复环境与元数据读取入口，关闭并删除收集阶段的会话临时库和目录。

    Args:
        config: pytest全局配置。
    """

    foundation.load_metadata_store = PRODUCTION_METADATA_LOADER
    previous_root = _COLLECTION_ISOLATION["previous_root"]
    if previous_root is None:
        os.environ.pop("OPENTEST_KNOWLEDGE_ROOT", None)
    else:
        os.environ["OPENTEST_KNOWLEDGE_ROOT"] = previous_root
    for store in _COLLECTION_ISOLATION["stores"]:
        store.close()
    if _COLLECTION_ISOLATION["database"]:
        # 只删除本会话生成的随机库。
        admin = MySqlMetadataStore(_test_mysql_configuration(), "test-admin")
        admin.execute(f"DROP DATABASE IF EXISTS `{_COLLECTION_ISOLATION['database']}`")
        admin.close()
    if _COLLECTION_ISOLATION["root"] is not None:
        shutil.rmtree(_COLLECTION_ISOLATION["root"], ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_metadata_mysql(request, monkeypatch):
    """让应用启动连接本用例专属的临时数据库，用例结束后只删除该库。

    Args:
        request: 读取用例标记；带`production_metadata_loader`时保留生产读取逻辑。
        monkeypatch: 替换应用入口读取元数据配置的函数。

    Yields:
        None；首次构造`OpenTestApplication`时才建库，纯单元测试不访问数据库。

    Side Effects:
        在`OPENTEST_MYSQL_TEST_CONFIG`指向的测试实例中创建并删除`ot_test_*`库。
        未配置时构造应用的用例以明确原因跳过，不恢复文件或SQLite运行分支。
    """

    if request.node.get_closest_marker("production_metadata_loader"):
        # 会话级已替换为收集隔离读取，标记用例需显式换回生产实现。
        monkeypatch.setattr("opentest.application.foundation.load_metadata_store", PRODUCTION_METADATA_LOADER)
        yield
        return
    created: list[MySqlMetadataStore] = []
    database = f"ot_test_{uuid.uuid4().hex[:16]}"
    base_configuration = _test_mysql_configuration()

    def load_test_store(knowledge_root: Path | str) -> MySqlMetadataStore:
        """按生产规则为一个知识根返回元数据存储，首次调用时建库建表。

        Args:
            knowledge_root: 应用知识根；同一父目录共享工作台身份，与生产配置文件位置一致。

        Returns:
            连接本用例临时库的存储实例。
        """

        if not base_configuration:
            pytest.skip(f"需要{TEST_MYSQL_CONFIG_ENV}指向测试专用MySQL配置")
        # 生产配置位于知识根父目录，测试沿用同一归属规则派生稳定workspace身份。
        workspace_id = _workspace_id(knowledge_root)
        first_store = not database_created
        if first_store:
            admin = MySqlMetadataStore(base_configuration, "test-admin")
            admin.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
            admin.close()
            # 建库成功即登记，后续建表或连接失败时teardown仍会删除该随机库。
            database_created.append(database)
        store = MySqlMetadataStore({**base_configuration, "database": database}, workspace_id)
        created.append(store)
        if first_store:
            store.install_schema()
        return store

    database_created: list[str] = []
    monkeypatch.setattr("opentest.application.foundation.load_metadata_store", load_test_store)
    yield
    for store in created:
        store.close()
    if database_created:
        # 只删除本用例生成的随机库，测试实例上的其他库不受影响。
        admin = MySqlMetadataStore(base_configuration, "test-admin")
        admin.execute(f"DROP DATABASE IF EXISTS `{database}`")
        admin.close()
