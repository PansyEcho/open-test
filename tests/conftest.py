"""为构造完整应用的测试提供每个用例独立、用后删除的真实MySQL元数据库。"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import pytest
import yaml

from opentest.adapters.mysql_metadata import MySqlMetadataStore


TEST_MYSQL_CONFIG_ENV = "OPENTEST_MYSQL_TEST_CONFIG"


def pytest_configure(config):
    """登记仍需验证生产配置读取逻辑的用例标记。

    Args:
        config: pytest全局配置。
    """

    config.addinivalue_line(
        "markers",
        "production_metadata_loader: 不替换应用的MySQL配置读取，用于验证缺失配置时的启动失败",
    )


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
        yield
        return
    configuration_path = os.environ.get(TEST_MYSQL_CONFIG_ENV, "")
    created: list[MySqlMetadataStore] = []
    database = f"ot_test_{uuid.uuid4().hex[:16]}"
    base_configuration: dict = {}
    if configuration_path:
        base_configuration = yaml.safe_load(Path(configuration_path).read_text(encoding="utf-8"))

    def load_test_store(knowledge_root: Path | str) -> MySqlMetadataStore:
        """按生产规则为一个知识根返回元数据存储，首次调用时建库建表。

        Args:
            knowledge_root: 应用知识根；同一父目录共享工作台身份，与生产配置文件位置一致。

        Returns:
            连接本用例临时库的存储实例。
        """

        if not configuration_path:
            pytest.skip(f"需要{TEST_MYSQL_CONFIG_ENV}指向测试专用MySQL配置")
        # 生产配置位于知识根父目录，测试沿用同一归属规则派生稳定workspace身份。
        owner = str(Path(knowledge_root).expanduser().resolve().parent)
        workspace_id = "test-" + hashlib.sha256(owner.encode("utf-8")).hexdigest()[:24]
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
