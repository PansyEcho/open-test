from pathlib import Path

from ai_test_platform.services import Platform


def test_platform_completes_mvp_flow_without_llm(tmp_path: Path):
    source = tmp_path / "business-source"
    source.mkdir()
    (source / "pom.xml").write_text("<project />", encoding="utf-8")
    (source / "TradeFacade.java").write_text(
        "public interface TradeFacade { Object createOrder(Object request); }",
        encoding="utf-8",
    )
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Test skill\n", encoding="utf-8")

    platform = Platform(data_root=tmp_path / "platform-home")
    project = platform.create_project(
        {
            "name": "订单系统自动化测试项目",
            "project_key": "order-system",
            "source_path": str(source),
            "agent_profile": "codex-local",
            "execute_agent": False,
            "skill_dir": str(skill_dir),
            "facade_http_prefix": "http://qa.example/gateway/order/v1",
            "headers": {"LABRADOR_TRACE_LOG": "true"},
            "job_rules": [
                {
                    "package_name": "com.example.job",
                    "trigger_mode": "http",
                    "http_url_prefix": "http://qa.example/job",
                    "enabled": True,
                }
            ],
        }
    )

    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    cli_version = platform.confirm_draft(project["id"], cli_draft["draft_id"])
    assert cli_version["version_key"] == "cli-v1"
    assert (Path(cli_version["path"]) / "_meta" / "platform-tool-index.json").exists()

    catalog = platform.get_knowledge_catalog(project["id"])
    assert catalog["ready"] is True
    chat = platform.start_knowledge_chat(project["id"], "project_background")
    background_reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "project_background",
            "message": "输出最终文档：本项目是火车票预定系统。",
        },
    )
    platform.confirm_knowledge_chat(
        project["id"],
        {"session_id": chat["session_id"], "node_id": "project_background", "content": background_reply["draft_content"]},
    )
    chat = platform.start_knowledge_chat(project["id"], "facade.trade.create_order")
    create_order_reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "facade.trade.create_order",
            "message": "输出最终文档：生成创建订单知识。",
        },
    )
    platform.confirm_knowledge_chat(
        project["id"],
        {"session_id": chat["session_id"], "node_id": "facade.trade.create_order", "content": create_order_reply["draft_content"]},
    )
    kb_version = platform.get_project(project["id"])["active_versions"]["knowledge"]
    assert kb_version["version_key"] == "kb-v1"

    case_draft = platform.generate_cases(project["id"], "main-flow")
    case_version = platform.confirm_draft(project["id"], case_draft["draft_id"])
    assert case_version["version_key"] == "case-v1"

    snapshot = platform.create_snapshot(project["id"])
    assert snapshot["knowledge_version"] == "kb-v1"
    assert snapshot["cli_version"] == "cli-v1"
    assert snapshot["case_version"] == "case-v1"

    run = platform.run_regression(project["id"], snapshot["snapshot_id"])
    assert run["llm_invocations"] == 0
    assert run["total_count"] == 2
    assert run["passed_count"] == 1
    assert run["failed_count"] == 1
    failed_step = run["cases"][1]["steps"][-1]
    assert failed_step["status"] == "failed"
    assert failed_step["stdout_json"]["orderStatus"] == "支付中"
    assert failed_step["assertion_result"]["diffs"][0]["expected"] == "已支付"
