from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_test_platform.services import Platform


DEFAULT_SOURCE = "/Users/user/data/code/tc/travelsystem.java.dsf.supplychain.booking.core"
DEFAULT_SKILL = "/Users/user/temp/self-skill/code-knowledge-builder-cl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full AI test platform MVP flow.")
    parser.add_argument("--data-root", default="/private/tmp/ai-test-platform-mvp")
    parser.add_argument("--source-path", default=DEFAULT_SOURCE)
    parser.add_argument("--skill-dir", default=DEFAULT_SKILL)
    args = parser.parse_args()

    platform = Platform(data_root=Path(args.data_root))
    project = platform.create_project(
        {
            "name": "订单系统自动化测试项目",
            "project_key": "order-system",
            "source_path": args.source_path,
            "agent_profile": "codex-local",
            "execute_agent": False,
            "skill_dir": args.skill_dir,
            "env_name": "test",
            "facade_http_prefix": "http://servicegw.test.ly.com/gateway/travelsystem.supplychain.booking.core/v2",
            "headers": {"LABRADOR_TRACE_LOG": "true"},
            "job_rules": [
                {
                    "package_name": "com.ly.travel.train.supplychain.bookingcore.biz.job",
                    "trigger_mode": "http",
                    "http_url_prefix": "http://servicegw.test.ly.com/gateway/travelsystem.supplychain.booking.core/job",
                    "enabled": True,
                }
            ],
        }
    )
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job", "timeout": 240})
    cli_version = platform.confirm_draft(project["id"], cli_draft["draft_id"])
    background_chat = platform.start_knowledge_chat(project["id"], "project_background")
    background_reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": background_chat["session_id"],
            "node_id": "project_background",
            "message": "输出最终文档：请生成订单系统的项目背景与核心交易知识。",
        },
    )
    platform.confirm_knowledge_chat(
        project["id"],
        {
            "session_id": background_chat["session_id"],
            "node_id": "project_background",
            "content": background_reply["draft_content"],
        },
    )
    create_order_chat = platform.start_knowledge_chat(project["id"], "facade.trade.create_order")
    create_order_reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": create_order_chat["session_id"],
            "node_id": "facade.trade.create_order",
            "message": "输出最终文档：请生成创建订单知识，并关联项目背景和计算最晚出票时间。",
        },
    )
    platform.confirm_knowledge_chat(
        project["id"],
        {
            "session_id": create_order_chat["session_id"],
            "node_id": "facade.trade.create_order",
            "content": create_order_reply["draft_content"],
        },
    )
    kb_version = platform.get_project(project["id"])["active_versions"]["knowledge"]
    case_draft = platform.generate_cases(project["id"], "main-flow")
    case_version = platform.confirm_draft(project["id"], case_draft["draft_id"])
    snapshot = platform.create_snapshot(project["id"])
    run = platform.run_regression(project["id"], snapshot["snapshot_id"])

    print(
        json.dumps(
            {
                "project": project["project_key"],
                "data_root": str(platform.data_root),
                "knowledge_version": kb_version["version_key"],
                "cli_version": cli_version["version_key"],
                "case_version": case_version["version_key"],
                "snapshot_id": snapshot["snapshot_id"],
                "run_id": run["run_id"],
                "status": run["status"],
                "total_count": run["total_count"],
                "passed_count": run["passed_count"],
                "failed_count": run["failed_count"],
                "llm_invocations": run["llm_invocations"],
                "report_path": run["report_path"],
                "failed_detail": [
                    {
                        "case": case["case_name"],
                        "step": step["step_name"],
                        "command": step["command"],
                        "stdout_json": step["stdout_json"],
                        "assertion_diff": step["assertion_result"]["diffs"],
                    }
                    for case in run["cases"]
                    for step in case["steps"]
                    if step["status"] == "failed"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
