"""上线前显式补齐旧扫描页面投影及背景形态；不重新扫描，不改变固定Case和scan身份。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from opentest.application.foundation import OpenTestApplication
from opentest.application.log_context import bind_workflow_log_context, configure_logging


LOGGER = logging.getLogger(__name__)


def backfill(application: OpenTestApplication) -> int:
    """补齐应用共享库的缺失summary并幂等规范化背景，返回本次更新的扫描数量。

    完整产物仅由本命令读取；每份摘要独立提交，中断后可重跑。异常传播给部署调用方。
    """

    metadata = application.store.metadata
    if metadata is None:
        raise ValueError("backfill requires configured MySQL metadata")
    artifacts = application.knowledge.artifacts
    scans = metadata.fetch_all(
        "SELECT system_id,scan_id FROM ot_scan WHERE JSON_EXTRACT(summary_json,'$.console') IS NULL "
        "ORDER BY system_id,generated_at")
    updated = 0
    for scan in scans:
        with bind_workflow_log_context(scan["system_id"], "console-projection-upgrade", scan["scan_id"]):
            manifest = artifacts.read(scan["system_id"], scan["scan_id"])
            # 仅使用已有产物。旧扫描未捕获的资源保持未知，不以重新扫描替代历史事实。
            projection = artifacts.console_projection(manifest)
            updated += metadata.execute(
                "UPDATE ot_scan SET summary_json=JSON_SET(summary_json,'$.console',CAST(%s AS JSON)) "
                "WHERE scan_id=%s AND JSON_EXTRACT(summary_json,'$.console') IS NULL",
                (json.dumps(projection, ensure_ascii=False), scan["scan_id"]))
            LOGGER.info("扫描页面投影已补齐 system=%s scan=%s", scan["system_id"], scan["scan_id"])
    for system in application.store.list_systems():
        with bind_workflow_log_context(system.system_id, "console-context-upgrade"):
            application.knowledge_discovery.normalize_context(system.system_id)
    return updated


def main() -> None:
    """读取现有工作台配置执行显式升级；结束时释放任务线程及只读连接池。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=Path("open-test-knowledge"))
    arguments = parser.parse_args()
    configure_logging()
    application = OpenTestApplication(arguments.knowledge_root)
    try:
        print(json.dumps({"updated_scans": backfill(application)}, ensure_ascii=False))
    finally:
        application.close()


if __name__ == "__main__":
    main()
