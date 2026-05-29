from pathlib import Path

from ai_test_platform.services import Platform
from ai_test_platform.execution import write_json


def create_demo_project(tmp_path: Path) -> tuple[Platform, dict]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pom.xml").write_text("<project />", encoding="utf-8")
    facade_dir = source / "app" / "facade" / "src" / "main" / "java" / "com" / "ly" / "travel" / "train" / "supplychain" / "bookingcore" / "facade"
    facade_dir.mkdir(parents=True)
    (facade_dir / "TradeFacade.java").write_text(
        """
package com.ly.travel.train.supplychain.bookingcore.facade;

import javax.ws.rs.POST;
import javax.ws.rs.Path;

/**
 * 交易相关的
 */
@Path("trade")
public interface TradeFacade {
    /**
     * 下单
     */
    @POST
    @Path("createOrder")
    CreateOrderResponse createOrder(CreateOrderRequest request);

    /**
     * 取消订单
     */
    @POST
    @Path("cancel")
    CancelOrderResponse cancel(CancelOrderRequest request);
}
""".strip(),
        encoding="utf-8",
    )
    (facade_dir / "TicketFacade.java").write_text(
        """
package com.ly.travel.train.supplychain.bookingcore.facade;

import javax.ws.rs.POST;
import javax.ws.rs.Path;

@Path("ticket")
public interface TicketFacade {
    /**
     * 出票
     */
    @POST
    @Path("issueTicket")
    IssueTicketResponse issueTicket(IssueTicketRequest request);
}
""".strip(),
        encoding="utf-8",
    )
    actor_dir = source / "app" / "biz" / "src" / "main" / "java" / "com" / "ly" / "travel" / "train" / "supplychain" / "bookingcore" / "biz" / "actor" / "pre"
    actor_dir.mkdir(parents=True)
    (actor_dir / "TicketSuccessPreActor.java").write_text(
        """
package com.ly.travel.train.supplychain.bookingcore.biz.actor.pre;

import com.ly.travel.train.supplychain.bookingcore.biz.annotations.State;
import com.ly.travel.train.supplychain.bookingcore.model.enums.OrderStateEnum;

/**
 * 出票成功前置处理
 */
@State(from = { OrderStateEnum.TICKETING }, to = { OrderStateEnum.ISSUE_SUCCESS })
public class TicketSuccessPreActor {
}
""".strip(),
        encoding="utf-8",
    )
    (actor_dir / "OrderCancelPreActor.java").write_text(
        """
package com.ly.travel.train.supplychain.bookingcore.biz.actor.pre;

import com.ly.travel.train.supplychain.bookingcore.biz.annotations.State;
import com.ly.travel.train.supplychain.bookingcore.model.enums.OrderStateEnum;

/**
 * 订单取消前置处理
 */
@State(from = { OrderStateEnum.INIT, OrderStateEnum.TICKETING },
        to = { OrderStateEnum.CANCEL })
public class OrderCancelPreActor {
}
""".strip(),
        encoding="utf-8",
    )
    skill_dir = tmp_path / "knowledge-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# knowledge builder\n", encoding="utf-8")
    platform = Platform(data_root=tmp_path / "home")
    project = platform.create_project(
        {
            "name": "订单系统",
            "project_key": "order-system",
            "source_path": str(source),
            "agent_profile": "codex-local",
            "execute_agent": False,
            "skill_dir": str(skill_dir),
            "knowledge_skill_dir": str(skill_dir),
            "facade_http_prefix": "http://qa.example/gateway/order/v1",
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
    return platform, project


def test_knowledge_catalog_requires_cli_before_background(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)

    catalog = platform.get_knowledge_catalog(project["id"])

    assert catalog["ready"] is False
    assert catalog["empty_message"] == "请先扫描项目生成 CLI。"
    assert catalog["tree"][0]["id"] == "project_background"
    assert catalog["tree"][0]["status"] == "missing"


def test_knowledge_catalog_is_seeded_from_confirmed_cli(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])

    catalog = platform.get_knowledge_catalog(project["id"])

    assert catalog["ready"] is True
    assert catalog["tree"][0]["title"] == "项目背景"
    trade_group = next(group for group in catalog["tree"] if group["title"] == "TradeFacade")
    create_order = next(child for child in trade_group["children"] if child["title"] == "createOrder【下单】")
    assert create_order["status"] == "missing"
    assert create_order["source"]["source_id"].endswith("TradeFacade#createOrder")
    assert create_order["source"]["facade_name"] == "TradeFacade"
    assert create_order["source"]["facade_title"] == "TradeFacade"
    assert create_order["source"]["method_name"] == "createOrder"
    assert create_order["source"]["method_title"] == "下单"
    assert any(child["title"] == "cancel【取消订单】" for child in trade_group["children"])

    ticket_group = next(group for group in catalog["tree"] if group["title"] == "TicketFacade")
    assert any(child["title"] == "issueTicket【出票】" for child in ticket_group["children"])


def test_knowledge_catalog_includes_state_machine_nodes_from_actor_annotations(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])

    catalog = platform.get_knowledge_catalog(project["id"])

    machine_group = next(group for group in catalog["tree"] if group["title"] == "状态机")
    order_machine = next(child for child in machine_group["children"] if child["id"] == "state_machine.order_state_enum")
    assert order_machine["title"] == "OrderStateEnum 状态流转"
    assert order_machine["type"] == "state_machine"
    assert order_machine["source"]["transition_count"] == 2
    assert {
        "from": ["TICKETING"],
        "to": ["ISSUE_SUCCESS"],
        "actor": "TicketSuccessPreActor",
        "phase": "pre",
    } in [
        {
            "from": item["from"],
            "to": item["to"],
            "actor": item["actor"],
            "phase": item["phase"],
        }
        for item in order_machine["source"]["transitions"]
    ]


def test_state_machine_knowledge_content_summarizes_transitions(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])

    node = platform.get_knowledge_node(project["id"], "state_machine.order_state_enum")
    content = platform._generate_knowledge_content(project, node, "输出最终文档：生成状态机知识")

    assert "# OrderStateEnum 状态流转" in content
    assert "TICKETING -> ISSUE_SUCCESS" in content
    assert "TicketSuccessPreActor" in content


def test_state_machine_scanner_accepts_refund_style_annotation_order(tmp_path: Path):
    source = tmp_path / "refund-source"
    actor_dir = source / "app" / "biz" / "src" / "main" / "java" / "com" / "example" / "actor" / "post"
    actor_dir.mkdir(parents=True)
    (actor_dir / "RefundOrderSuccessPostActor.java").write_text(
        """
import com.example.State;

@State(from = { RefundOrderStateEnum.WAIT_REFUND, RefundOrderStateEnum.REFUNDING },
        to = { RefundOrderStateEnum.REFUND_SUCCESS })
@Service
public class RefundOrderSuccessPostActor {
}
""".strip(),
        encoding="utf-8",
    )
    platform = Platform(tmp_path / "home")

    machines = platform._scan_state_machines(source)

    assert machines[0]["node_id"] == "state_machine.refund_order_state_enum"
    assert machines[0]["transitions"][0]["actor"] == "RefundOrderSuccessPostActor"
    assert machines[0]["transitions"][0]["from"] == ["WAIT_REFUND", "REFUNDING"]


def test_platform_tool_index_enriches_facade_comments_from_scan_manifest(tmp_path: Path):
    platform, _project = create_demo_project(tmp_path)
    cli_dir = tmp_path / "cli"
    meta_dir = cli_dir / "_meta"
    meta_dir.mkdir(parents=True)
    source_file = tmp_path / "TradeFacade.java"
    source_file.write_text(
        """
package com.example;

/**
 * 交易相关的
 */
public interface TradeFacade {
    /**
     * 下单
     */
    CreateOrderResponse createOrder(CreateOrderRequest request);
}
""".strip(),
        encoding="utf-8",
    )
    (meta_dir / "scan-manifest.json").write_text(
        """
{
  "facades": [
    {
      "facade_id": "com.example.TradeFacade#createOrder",
      "interface_name": "TradeFacade",
      "method_name": "createOrder",
      "base_path": "trade",
      "method_path": "createOrder",
      "source_path": "%s"
    }
  ]
}
""".strip()
        % str(source_file),
        encoding="utf-8",
    )
    (meta_dir / "tool-manifest.json").write_text(
        """
{
  "generated_tools": [
    {
      "tool_id": "facade_raw.trade.createOrder",
      "tool_type": "facade_raw",
      "display_name": "trade / createOrder",
      "source_id": "com.example.TradeFacade#createOrder",
      "script_rel_path": "facade/trade/create-order-raw.sh",
      "status": "ready"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    index = platform._build_platform_tool_index(cli_dir)

    tool = index["facade.trade.create_order"]
    assert tool["facade_name"] == "TradeFacade"
    assert tool["facade_title"] == "TradeFacade"
    assert tool["method_name"] == "createOrder"
    assert tool["method_title"] == "下单"


def test_knowledge_catalog_reenriches_legacy_confirmed_cli_index(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    workspace = Path(project["workspace_path"])
    cli_dir = workspace / "versions" / "cli" / "legacy-cli"
    meta_dir = cli_dir / "_meta"
    meta_dir.mkdir(parents=True)
    source_dir = tmp_path / "legacy-source"
    source_dir.mkdir()
    trade_file = source_dir / "TradeFacade.java"
    trade_file.write_text(
        """
package com.example;

/**
 * 交易接口
 */
public interface TradeFacade {
    /**
     * 下单
     */
    CreateOrderResponse createOrder(CreateOrderRequest request);
}
""".strip(),
        encoding="utf-8",
    )
    ticket_file = source_dir / "TicketFacade.java"
    ticket_file.write_text(
        """
package com.example;

/**
 * 出票接口
 */
public interface TicketFacade {
    /**
     * 出票
     */
    IssueTicketResponse issueTicket(IssueTicketRequest request);
}
""".strip(),
        encoding="utf-8",
    )
    write_json(
        meta_dir / "scan-manifest.json",
        {
            "facades": [
                {
                    "facade_id": "com.example.TradeFacade#createOrder",
                    "interface_name": "TradeFacade",
                    "method_name": "createOrder",
                    "base_path": "trade",
                    "method_path": "createOrder",
                    "source_path": str(trade_file),
                },
                {
                    "facade_id": "com.example.TicketFacade#issueTicket",
                    "interface_name": "TicketFacade",
                    "method_name": "issueTicket",
                    "base_path": "ticket",
                    "method_path": "issueTicket",
                    "source_path": str(ticket_file),
                },
            ]
        },
    )
    write_json(
        meta_dir / "platform-tool-index.json",
        {
            "tools": [
                {
                    "tool_id": "facade.trade.create_order",
                    "display_name": "trade / createOrder",
                    "kind": "facade",
                    "script_path": "facade/trade/create-order-raw.sh",
                    "source_id": "com.example.TradeFacade#createOrder",
                    "status": "ready",
                    "facade_title": "交易接口",
                    "knowledge_title": "batch Query Order Info",
                },
                {
                    "tool_id": "facade.ticket.issue_ticket",
                    "display_name": "ticket / issueTicket",
                    "kind": "facade",
                    "script_path": "facade/ticket/issue-ticket-raw.sh",
                    "source_id": "com.example.TicketFacade#issueTicket",
                    "status": "ready",
                    "facade_title": "交易接口",
                    "knowledge_title": "finish",
                },
            ]
        },
    )
    project.setdefault("active_versions", {})["cli"] = {"id": "legacy-cli", "path": str(cli_dir)}
    platform.save_project(project)

    catalog = platform.get_knowledge_catalog(project["id"])

    assert not any(group["title"] == "交易接口" for group in catalog["tree"])
    trade_group = next(group for group in catalog["tree"] if group["title"] == "TradeFacade")
    ticket_group = next(group for group in catalog["tree"] if group["title"] == "TicketFacade")
    assert any(child["title"] == "createOrder【下单】" for child in trade_group["children"])
    assert any(child["title"] == "issueTicket【出票】" for child in ticket_group["children"])


def test_forced_knowledge_chat_invokes_codex_like_open_design(monkeypatch, tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    project["execute_agent"] = False
    platform.save_project(project)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])
    calls = []

    def fake_which(binary: str) -> str:
        assert binary == "codex"
        return "/usr/local/bin/codex"

    class Completed:
        returncode = 0
        stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"# Codex 生成知识\\n\\n真实 Codex 回复。"}}\n'
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr("ai_test_platform.services.shutil.which", fake_which)
    monkeypatch.setattr("ai_test_platform.services.subprocess.run", fake_run)
    chat = platform.start_knowledge_chat(project["id"], "facade.trade.create_order")

    reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "facade.trade.create_order",
            "message": "请真实调用 Codex 生成下单知识。",
            "force_agent": True,
        },
    )

    command, kwargs = calls[0]
    assert command[:3] == ["/usr/local/bin/codex", "exec", "--json"]
    assert "--skip-git-repo-check" in command
    assert "--sandbox" in command
    assert "workspace-write" in command
    assert "--add-dir" in command
    assert "请真实调用 Codex" in kwargs["input"]
    assert "请真实调用 Codex" not in command
    assert reply["agent_run"]["status"] == "completed"
    assert "真实 Codex 回复" in reply["reply"]
    assert reply["node"]["content"] == ""
    assert reply["draft_content"] == ""


def test_knowledge_agent_prompt_is_bounded_for_interactive_chat(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])
    node = platform.get_knowledge_node(project["id"], "facade.trade.create_order")

    prompt = platform._build_knowledge_agent_prompt(project, node, "请生成下单知识")

    assert "多轮聊天" in prompt
    assert "KNOWLEDGE_DOCUMENT" in prompt
    assert "除非信息足够或用户明确要求最终文档，否则请继续追问" in prompt
    assert "TradeFacade#createOrder" in prompt


def test_interactive_chat_keeps_agent_reply_in_session_without_auto_write(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])

    platform.update_knowledge_skill(project["id"], str(tmp_path / "knowledge-skill"))
    chat = platform.start_knowledge_chat(project["id"], "facade.trade.create_order")
    reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "facade.trade.create_order",
            "message": "你好",
        },
    )

    assert reply["node"]["status"] == "missing"
    assert reply["node"]["content"] == ""
    assert reply["draft_content"] == ""
    assert "请先补充" in reply["reply"]
    assert reply["session"]["messages"][-1]["role"] == "assistant"
    assert reply["session"]["messages"][-1]["content"] == reply["reply"]
    node = platform.get_knowledge_node(project["id"], "facade.trade.create_order")
    assert node["status"] == "missing"


def test_chat_final_document_requires_confirm_before_write(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])

    chat = platform.start_knowledge_chat(project["id"], "project_background")
    reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "project_background",
            "message": "输出最终文档：本项目是火车票预定系统。",
        },
    )

    assert reply["node"]["status"] == "missing"
    assert "# 项目背景" in reply["draft_content"]
    assert platform.get_knowledge_node(project["id"], "project_background")["content"] == ""

    confirmed = platform.confirm_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "project_background",
            "content": reply["draft_content"],
        },
    )

    assert confirmed["node"]["status"] == "generated"
    assert "# 项目背景" in confirmed["node"]["content"]
    assert confirmed["session"]["status"] == "confirmed"


def test_extract_knowledge_document_sanitizes_auto_markers_and_keeps_reply_concise(tmp_path: Path):
    platform, _project = create_demo_project(tmp_path)

    reply, draft = platform._extract_knowledge_document(
        "项目背景文档如下：\n"
        "<<<KNOWLEDGE_DOCUMENT>>>\n"
        "# 项目背景\n\n"
        "<!-- kb:auto-start -->\n"
        "booking-core 是火车票预定系统。## 核心流程\n"
        "<<<END_KNOWLEDGE_DOCUMENT>>>\n"
        "请在右侧确认。"
    )

    assert "booking-core 是火车票预定系统" in draft
    assert "kb:auto-start" not in draft
    assert "系统。\n\n##" in draft
    assert "booking-core 是火车票预定系统" not in reply
    assert "右侧草稿" in reply


def test_confirm_knowledge_chat_stores_sanitized_draft_content(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    chat = platform.start_knowledge_chat(project["id"], "project_background")

    confirmed = platform.confirm_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "project_background",
            "content": "# 项目背景\n\nbooking-core 是火车票预定系统。<!-- kb:auto-start -->## 核心流程",
        },
    )

    assert "kb:auto-start" not in confirmed["node"]["content"]
    assert "kb:auto-start" not in confirmed["session"]["draft_content"]
    assert "系统。\n\n## 核心流程" in confirmed["session"]["draft_content"]


def test_knowledge_chat_history_is_scoped_by_node(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    bg_chat = platform.start_knowledge_chat(project["id"], "project_background")
    trade_chat = platform.start_knowledge_chat(project["id"], "facade.trade.create_order")

    bg_history = platform.list_knowledge_chats(project["id"], "project_background")
    trade_history = platform.list_knowledge_chats(project["id"], "facade.trade.create_order")

    assert [item["session_id"] for item in bg_history] == [bg_chat["session_id"]]
    assert [item["session_id"] for item in trade_history] == [trade_chat["session_id"]]
    assert bg_history[0]["message_count"] == 1
    assert "准备生成" in bg_history[0]["preview"]


def test_cli_catalog_groups_tools_like_knowledge_tree(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})

    catalog = platform.get_cli_catalog(project["id"], cli_draft["draft_id"])

    trade_group = next(group for group in catalog["tree"] if group["title"] == "TradeFacade")
    ticket_group = next(group for group in catalog["tree"] if group["title"] == "TicketFacade")
    assert any(child["title"] == "createOrder【下单】" for child in trade_group["children"])
    assert any(child["title"] == "issueTicket【出票】" for child in ticket_group["children"])
    assert catalog["tool_count"] >= 2


def test_knowledge_agent_prompt_includes_skill_context_and_existing_background(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])
    platform.update_knowledge_node(project["id"], "project_background", "# 项目背景\n\n本项目是火车票预定系统。")
    node = platform.get_knowledge_node(project["id"], "facade.trade.create_order")

    prompt = platform._build_knowledge_agent_prompt(
        project,
        node,
        "请继续追问港币支付订单。",
        [{"role": "user", "content": "本项目是火车票预定系统。"}],
    )

    assert "## Active Skill" in prompt
    assert "知识采访式对话" in prompt
    assert "## Node Mode\nFacade 接口知识" in prompt
    assert "本项目是火车票预定系统" in prompt
    assert "createOrder【下单】" in prompt
    assert "请继续追问港币支付订单" in prompt

    edited = platform.update_knowledge_node(
        project["id"],
        "facade.trade.create_order",
        "人工编辑后的创建订单知识，依赖 [[计算最晚出票时间]]。",
    )

    assert edited["status"] == "generated"
    assert edited["edited_manually"] is True
    assert "人工编辑后" in platform.get_knowledge_node(project["id"], "facade.trade.create_order")["content"]


def test_new_knowledge_chat_creates_custom_node(tmp_path: Path):
    platform, project = create_demo_project(tmp_path)
    cli_draft = platform.generate_cli(project["id"], {"types": "facade,job"})
    platform.confirm_draft(project["id"], cli_draft["draft_id"])

    chat = platform.start_knowledge_chat(project["id"], "__new__")
    reply = platform.send_knowledge_chat(
        project["id"],
        {
            "session_id": chat["session_id"],
            "node_id": "__new__",
            "message": "新增一个关于退款前置校验的知识。",
        },
    )

    assert reply["node"]["id"].startswith("custom.")
    assert reply["node"]["title"] == "退款前置校验"
    catalog = platform.get_knowledge_catalog(project["id"])
    custom_group = next(group for group in catalog["tree"] if group["title"] == "自定义知识")
    assert any(child["id"] == reply["node"]["id"] for child in custom_group["children"])
