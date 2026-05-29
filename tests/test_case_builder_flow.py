from pathlib import Path

from ai_test_platform.execution import read_json
from tests.test_knowledge_catalog_flow import create_demo_project


def prepare_project_with_knowledge(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])
    platform.update_knowledge_node(project["id"], "project_background", "# 项目背景\n\n订单系统背景。")
    platform.update_knowledge_node(project["id"], "facade.trade.create_order", "# createOrder【下单】\n\n创建订单知识。")
    return platform, platform.get_project(project["id"])


def test_generate_cases_for_selected_knowledge_node_creates_case_list_and_flow(tmp_path: Path):
    platform, project = prepare_project_with_knowledge(tmp_path)

    draft = platform.generate_cases(project["id"], "main-flow", node_id="facade.trade.create_order")
    suite = read_json(Path(draft["draft_path"]) / "suite.json", {})

    assert suite["source"]["node_id"] == "facade.trade.create_order"
    assert len(suite["cases"]) >= 4
    first = suite["cases"][0]
    assert first["node_id"] == "facade.trade.create_order"
    assert first["description"]
    assert first["assertions_count"] >= 1
    assert first["cli_tools"]
    steps = read_json(Path(draft["draft_path"]) / first["steps_file"], [])
    assert steps[0]["name"]
    assert steps[0]["execution_tool"].startswith("tool://")


def test_case_catalog_uses_knowledge_tree_and_reports_case_counts(tmp_path: Path):
    platform, project = prepare_project_with_knowledge(tmp_path)
    draft = platform.generate_cases(project["id"], "main-flow", node_id="facade.trade.create_order")

    catalog = platform.get_case_catalog(project["id"], draft_id=draft["draft_id"])

    trade_group = next(group for group in catalog["tree"] if group["title"] == "TradeFacade")
    create_order = next(child for child in trade_group["children"] if child["id"] == "facade.trade.create_order")
    assert create_order["case_count"] >= 4
    assert create_order["case_status_label"] == f"已有 {create_order['case_count']} 个 Case"


def test_case_detail_can_be_read_and_json_can_be_updated(tmp_path: Path):
    platform, project = prepare_project_with_knowledge(tmp_path)
    draft = platform.generate_cases(project["id"], "main-flow", node_id="facade.trade.create_order")
    suite = read_json(Path(draft["draft_path"]) / "suite.json", {})
    case_id = suite["cases"][0]["case_id"]

    detail = platform.get_case_detail(project["id"], case_id, draft_id=draft["draft_id"])
    assert detail["case"]["case_id"] == case_id
    assert detail["flow"][0]["index"] == 1

    updated = platform.upsert_case(
        project["id"],
        {
            "draft_id": draft["draft_id"],
            "case_id": case_id,
            "case": {**detail["case"], "name": "编辑后的 Case 名称"},
            "steps": detail["steps"],
        },
    )

    assert updated["case"]["name"] == "编辑后的 Case 名称"


def test_new_case_can_be_added_for_selected_node(tmp_path: Path):
    platform, project = prepare_project_with_knowledge(tmp_path)
    draft = platform.generate_cases(project["id"], "main-flow", node_id="facade.trade.create_order")

    created = platform.upsert_case(
        project["id"],
        {
            "draft_id": draft["draft_id"],
            "node_id": "facade.trade.create_order",
            "case": {
                "name": "人工新增参数缺失 Case",
                "description": "校验缺少必要参数时创建订单失败。",
                "priority": "P1",
            },
            "steps": [
                {
                    "step_index": 1,
                    "name": "缺少乘客创建订单",
                    "execution_type": "script",
                    "execution_tool": "tool://facade.trade.create_order",
                    "input_params": {"passengers": []},
                    "verification_type": "assertion",
                    "verification_assertion": {"success": False},
                }
            ],
        },
    )

    assert created["case"]["node_id"] == "facade.trade.create_order"
    assert created["case"]["name"] == "人工新增参数缺失 Case"
