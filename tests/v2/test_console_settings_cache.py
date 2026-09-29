"""验证配置普通保存边界，以及远端目录缓存的版本、隔离与容量。"""

import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.application.console_read_cache import ConsoleReadCache
from opentest.application.foundation import OpenTestApplication
from opentest.domain.models import SystemDefinition


def test_metadata_save_does_not_require_scanner_or_submit_scan(tmp_path, monkeypatch):
    """名称更新经过真实HTTP及持久存储，不调用扫描器，也不允许偷偷修改源码路径。"""

    application = OpenTestApplication(tmp_path / "knowledge")
    source = tmp_path / "source"
    source.mkdir()
    application.store.register_system(SystemDefinition(system_id="demo", name="旧名称", source_path=str(source)))
    # 旧系统没有pin时改名不能顺便补建Git基线，扫描相关方法也必须保持零调用。
    monkeypatch.setattr(application, "_ensure_persisted_source_version", Mock(side_effect=AssertionError("改名不可补建pin")))
    scanner = Mock(side_effect=AssertionError("普通保存不可依赖扫描器"))
    monkeypatch.setattr(application, "ensure_scanner_ready", scanner)
    monkeypatch.setattr(application, "submit_prepared_source_scan", scanner)
    client = TestClient(create_app(application), client=("127.0.0.1", 51000))
    response = client.put("/api/v2/systems/demo", json={"name": "新名称", "source_path": str(source)})
    assert response.status_code == 200, response.text
    assert response.json()["system"]["name"] == "新名称"
    assert "scan_task" not in response.json()
    assert response.json()["system"]["source_version"] is None
    assert application.store.get_system("demo").name == "新名称"
    scanner.assert_not_called()
    rejected = client.put("/api/v2/systems/demo", json={"name": "不应保存", "source_path": str(tmp_path)})
    assert rejected.status_code == 400
    assert application.store.get_system("demo").name == "新名称"
    application.close()


def test_cache_reuses_payload_checks_remote_revision_and_does_not_mask_failure(tmp_path):
    """相同目录不重复构建；外部写入立即失效，数据库断开不能返回伪正常旧目录。"""

    metadata = Mock()
    metadata._local = threading.local()
    metadata.fetch_all.return_value = [{"system_id": "demo", "latest_scan_id": "scan-a", "workspace_revision": 1, "is_archived": 0}]
    cache = ConsoleReadCache(metadata, tmp_path)
    reads = []

    @cache.cached
    def directory(system_id: str):
        """记录真正目录加载次数，返回可变载荷以验证缓存副本隔离。"""

        reads.append(system_id)
        return {"systems": [system_id]}

    assert directory("demo") == {"systems": ["demo"]}
    directory("demo")["systems"].clear()
    assert directory("demo") == {"systems": ["demo"]}
    assert reads == ["demo"]
    # 观察其他工作台推进版本，不依靠本进程收到写通知。
    metadata.fetch_all.return_value[0]["workspace_revision"] = 2
    directory("demo")
    assert reads == ["demo", "demo"]
    metadata.fetch_all.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        directory("demo")


def test_cache_eviction_and_inflight_revision_change(tmp_path):
    """容量压力淘汰旧目录，构建期间版本变化不保留旧代响应。"""

    metadata = Mock()
    metadata._local = threading.local()
    first = [{"system_id": "demo", "latest_scan_id": "scan-a", "workspace_revision": 1, "is_archived": 0}]
    second = [{**first[0], "workspace_revision": 2}]
    metadata.fetch_all.return_value = first
    cache = ConsoleReadCache(metadata, tmp_path)
    cache.max_entries = 1
    reads = []

    @cache.cached
    def directory(system_id: str):
        """返回按系统隔离的小目录，供淘汰与版本竞争测试观察加载次数。"""

        reads.append(system_id)
        return {"system": system_id}

    directory("a")
    directory("b")
    directory("a")
    assert reads == ["a", "b", "a"]
    # 新key构建前后读到不同共享版本时，不能污染后续命中。
    metadata.fetch_all.side_effect = [first, second]
    directory("c")
    assert all(key[1] != ("c",) for key in cache._entries)
    metadata.fetch_all.side_effect = None
    cache.max_bytes = 1
    directory("d")
    directory("d")
    assert reads[-2:] == ["d", "d"]
