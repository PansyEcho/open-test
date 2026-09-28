"""为三组模型准备不同QA订单，并通过现有HTTP执行服务取消及独立回查。"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from scripts.benchmark_refund_models import ARMS, ROOT, NoRedirect, make_state, measure

SYSTEM = "ifightchainsaas.java.refund.core"
FACADE = "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#"
API = "http://127.0.0.1:8788/api/v2"
CANCELLABLE = {"PENDING_APPLY", "WAIT_REFUND", "AUDITED", "REFUND_FAIL", "RESHOPING"}
LOGGER = logging.getLogger(__name__)


def api_call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用固定回环API并返回JSON；禁用代理和跳转，HTTP异常只暴露状态码。"""
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = Request(API + path, method=method, data=body, headers={"Content-Type": "application/json"})
    # 业务身份和凭据只走本地服务，不继承系统代理或接受其他服务的重定向。
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=90) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"local_http_{exc.code}") from None


def known_execution(request_id: str) -> dict[str, Any] | None:
    """只读查找现有请求的执行记录；用于写入恢复，不通过新请求ID重放未知取消。"""
    root = ROOT / "open-test-knowledge/.opentest/operation-executions"
    # 直接比较已有记录的业务键，不为实验另建去重状态或派发恢复请求。
    for path in root.glob("operation-execution-*.json"):
        record = json.loads(path.read_text())
        if record.get("request_id") == request_id and record.get("system_id") == SYSTEM:
            return record
    return None


def execute(action: str, arguments: dict[str, Any], request_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """经现有去重服务执行一个固定Facade动作，返回业务输出及有界测量证据；失败不自动重试。"""
    if action not in {"queryList", "queryDetailByRefundNo", "cancel"}:
        raise ValueError("action_not_in_pilot")
    started = time.perf_counter()
    payload = {"environment": "qa", "operation_id": FACADE + action,
               "arguments": {"traceId": request_id, "operator": "OpenTest", **arguments},
               "request_id": request_id, "timeout_seconds": 60}
    # 已存在的写请求只读取记录；未知状态绝不能通过更换ID再次发送。
    record = known_execution(request_id) if action == "cancel" else None
    reused = record is not None
    if record is None:
        record = api_call("POST", f"/systems/{SYSTEM}/operation-executions", payload)["execution"]
    result = record.get("result") or {}
    output = result.get("output") or {}
    if record.get("status") != "completed" or result.get("status") != "success" or output.get("success") is not True:
        raise RuntimeError("business_operation_not_successful")
    return output, {"action": action, "request_id": request_id, "execution_id": record["execution_id"],
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "reused": reused,
                    "provider_elapsed_ms": result.get("elapsed_ms")}


def eligible_refund(output: dict[str, Any], expected_refund: str) -> dict[str, Any]:
    """从完整票号查询中校验唯一可取消退票单；历史终态可共存，多张可取消单必须拒绝。"""
    page = output.get("list") or {}
    orders = page.get("pageList") or []
    if not isinstance(orders, list) or page.get("totalCount") != len(orders):
        raise ValueError("incomplete_ticket_query")
    # 先检查全部可取消候选，再限制非SAPL；不能通过过滤渠道消除真实目标歧义。
    candidates = [order for order in orders if order.get("refundState") in CANCELLABLE]
    if len(candidates) != 1 or candidates[0].get("refundSerialNo") != expected_refund:
        raise ValueError("refund_target_not_unique")
    if candidates[0].get("gds") == "SAPL":
        raise ValueError("sapl_outside_pilot")
    return candidates[0]


def verified_readback(output: dict[str, Any], refund_no: str, ticket: str) -> bool:
    """核实详情的退票号、最终状态及真实票号关联；接口返回success本身不代表取消验证通过。"""
    order = output.get("saasRefundOrderVO") or {}
    # 必须在同一真实详情中证明票号关联，不能仅依赖查询参数或取消响应。
    tickets = {psi.get("item", {}).get("ticketNo") for psi in order.get("psis", [])}
    return (order.get("refundSerialNo") == refund_no and order.get("refundState") == "REFUND_CANCEL"
            and ticket in tickets)


def preflight() -> None:
    """读取QA环境和本次三个固定操作契约；环境不可用或操作受阻时在业务调用前失败。"""
    environments = api_call("GET", f"/systems/{SYSTEM}/environments")["environments"]
    if not any(item.get("environment") == "qa" and item.get("available") for item in environments):
        raise ValueError("qa_unavailable")
    for action in ("queryList", "queryDetailByRefundNo", "cancel"):
        # 详情路由使用path query参数，避免把operation ID的#变成URL fragment。
        capability = api_call("GET", f"/systems/{SYSTEM}/operations/{quote(FACADE + action, safe='')}")["operation"]
        if not capability.get("executable"):
            raise ValueError("operation_not_executable")


def prepare(args: argparse.Namespace) -> None:
    """按args.sample_count取得可唯一定位的非SAPL退票单，默认九张；只保存核对后的本地输入。"""
    preflight()
    args.output.mkdir(parents=True, exist_ok=False)
    os.chmod(args.output, 0o700)
    started = time.perf_counter()
    prefix = args.run_id
    sample_count = getattr(args, "sample_count", 9)
    # 优先真实运行已有版本；其首条样本不适用时继续用同一查询契约查找可验证的数据。
    prepared = api_call("POST", f"/systems/{SYSTEM}/data-capabilities/refund_cancel_state_data/executions",
                        {"version": 1, "environment_id": "qa", "inputs": {"state_name": "PENDING_APPLY"},
                         "allow_writes": False, "request_id": prefix + "-shared-data"})["execution"]
    deadline = time.monotonic() + 120
    while prepared["status"] == "RUNNING" and time.monotonic() < deadline:
        time.sleep(1)
        prepared = api_call("GET", f"/systems/{SYSTEM}/data-executions/{prepared['execution_id']}")["execution"]
    if prepared["status"] != "COMPLETED" or not all(check["passed"] for check in prepared["checks"]):
        raise ValueError("shared_data_not_verified")
    listing, listing_evidence = execute("queryList", {"page": 1, "pageSize": 1000}, prefix + "-candidates")
    page = listing.get("list") or {}
    if page.get("totalCount") != len(page.get("pageList", [])):
        raise ValueError("incomplete_candidate_query")
    orders = [order for order in page["pageList"] if order.get("refundState") in CANCELLABLE and order.get("gds") != "SAPL"]
    selected = []
    skipped = []
    used_tickets = set()
    for index, order in enumerate(orders):
        refund_no = order["refundSerialNo"]
        try:
            detail, detail_evidence = execute("queryDetailByRefundNo", {"refundSerialNo": refund_no}, f"{prefix}-prepare-detail-{index}")
            current = detail.get("saasRefundOrderVO") or {}
            tickets = list(dict.fromkeys(psi.get("item", {}).get("ticketNo") for psi in current.get("psis", [])))
            if current.get("refundSerialNo") != refund_no or len(tickets) != 1 or not tickets[0] or tickets[0] in used_tickets:
                raise ValueError("prepare_ticket_not_unique")
            ticket = tickets[0]
            _, mapping = make_state("票号" + ticket)
            if list(mapping.values()) != [ticket]:
                raise ValueError("unsupported_ticket_format")
            response, query_evidence = execute("queryList", {"ticketNo": ticket, "page": 1, "pageSize": 1000}, f"{prefix}-prepare-ticket-{index}")
            target = eligible_refund(response, refund_no)
            selected.append({"refund_no": refund_no, "ticket": ticket, "state": target["refundState"],
                             "preparation_evidence": [detail_evidence, query_evidence]})
            used_tickets.add(ticket)
            LOGGER.info("QA数据核对通过 count=%s", len(selected))
            if len(selected) == sample_count:
                break
        except (ValueError, RuntimeError) as exc:
            skipped.append({"candidate_index": index, "reason": str(exc)})
    payload = {"run_id": prefix, "system_id": SYSTEM, "shared_data_execution": prepared["execution_id"],
               "listing_evidence": listing_evidence, "preparation_ms": round((time.perf_counter() - started) * 1000, 3),
               "orders": selected, "skipped": skipped, "ready": len(selected) == sample_count}
    (args.output / "qa-inputs.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    if len(selected) != sample_count:
        raise ValueError(f"only_{len(selected)}_verified_orders")


def run_one(arm: str, order: dict[str, Any], prefix: str, key_file: Path) -> dict[str, Any]:
    """对一个已准备目标测量决策、查询、取消及回查；所有失败留在结果，未知取消只读查证。"""
    started = time.perf_counter()
    report = {"arm": arm, "verified": False, "calls": [], "request_prefix": prefix}
    ticket = order["ticket"]
    refund_no = order["refund_no"]
    text = f"取消票号是{ticket}的退票单，取消原因你帮我自动填写。"
    try:
        measurement = measure(arm, text, key_file)
        report["model"] = measurement
        expected = {"intent": "cancel_refund", "action": "execute", "target": "t1", "reason": "automatic"}
        if not measurement["ok"] or measurement.get("decision") != expected:
            raise ValueError("model_did_not_select_supported_request")
        # 重启同一试验槽位只能查证旧取消结果，不能再次进入写请求。
        previous = known_execution(prefix + "-cancel")
        if previous is None:
            queried, evidence = execute("queryList", {"ticketNo": ticket, "page": 1, "pageSize": 1000}, prefix + "-query")
            report["calls"].append(evidence)
            target = eligible_refund(queried, refund_no)
            report["before_state"] = target["refundState"]
            _, evidence = execute("cancel", {"refundSerialNo": refund_no, "traceId": prefix,
                                            "operator": "OpenTest", "cancelReasonId": "OTHER", "cancelReason": "用户要求取消",
                                            "cancelRemark": "OpenTest QA：Jev三组模型对照实验"}, prefix + "-cancel")
            report["calls"].append(evidence)
        else:
            report["recovered_execution_id"] = previous["execution_id"]
            report["recovered"] = True
        observed, evidence = execute("queryDetailByRefundNo", {"refundSerialNo": refund_no}, prefix + "-verify")
        report["calls"].append(evidence)
        report["verified"] = verified_readback(observed, refund_no, ticket)
        if not report["verified"]:
            raise ValueError("readback_not_cancelled")
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        if isinstance(exc, (ValueError, RuntimeError)):
            report["error_code"] = str(exc)
        # 写调用返回未知时核对执行记录和业务状态，保留失败性质而非重新取消。
        record = known_execution(prefix + "-cancel")
        if record is not None:
            report["observed_execution"] = {"execution_id": record["execution_id"], "status": record["status"]}
            try:
                observed, evidence = execute("queryDetailByRefundNo", {"refundSerialNo": refund_no}, prefix + "-diagnostic")
                report["calls"].append(evidence)
                report["diagnostic_cancelled"] = verified_readback(observed, refund_no, ticket)
            except Exception as observation_error:
                report["observation_error"] = type(observation_error).__name__
    report["workflow_ms"] = round((time.perf_counter() - started) * 1000, 3)
    report["business_ms"] = sum(call["elapsed_ms"] for call in report["calls"])
    return report


def run_pilot(args: argparse.Namespace) -> None:
    """按轮换顺序给三组各执行三个不同订单并保存结果；已完成槽位不重放，数据映射仅在本地。"""
    preflight()
    prepared = json.loads((args.output / "qa-inputs.json").read_text())
    if not prepared["ready"] or prepared["run_id"] != args.run_id or len(prepared["orders"]) != 9:
        raise ValueError("qa_inputs_not_ready")
    orders = prepared["orders"]
    if len({order["refund_no"] for order in orders}) != 9 or len({order["ticket"] for order in orders}) != 9:
        raise ValueError("qa_inputs_not_distinct")
    for index, order in enumerate(orders):
        round_index, arm_index = divmod(index, 3)
        arm = ARMS[(arm_index + round_index) % 3]
        destination = args.output / f"qa-{index + 1}.json"
        if destination.exists():
            continue
        # 与用户授权范围一致，只执行已准备且真实核对过的九个输入。
        report = run_one(arm, order, f"{args.run_id}-slot-{index + 1}", args.key_file)
        report["slot"] = index + 1
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        LOGGER.info("QA验证 slot=%s arm=%s verified=%s elapsed_ms=%s", index + 1, arm, report["verified"], report["workflow_ms"])


def main() -> None:
    """解析准备/执行阶段和稳定运行ID，绑定项目日志上下文并在退出时自动清理。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "run"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, default=Path("/Users/user/data/api_key/jev_api_key.txt"))
    args = parser.parse_args()
    # 稳定运行ID会进入九个槽位的幂等键，先校验避免部分执行后才被服务拒绝。
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,70}", args.run_id):
        parser.error("run-id must be 8-71 alphanumeric/hyphen/underscore characters")
    from opentest.application.log_context import bind_workflow_log_context, configure_logging
    configure_logging()
    with bind_workflow_log_context(SYSTEM, "jev-refund-qa", args.run_id):
        if args.phase == "prepare":
            prepare(args)
        else:
            run_pilot(args)


if __name__ == "__main__":
    main()
