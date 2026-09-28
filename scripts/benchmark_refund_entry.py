"""比较Codex原子工具、Codex单次Jev工具和直接HTTP入口的真实QA完成时间。"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
import select
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

from scripts import benchmark_refund_models as models
from scripts import benchmark_refund_qa as qa

LOGGER = logging.getLogger(__name__)
ARMS = ("codex-atomic", "codex-jev", "http-jev")
ENTRY_URL = "http://127.0.0.1:8789/cancel"
TEMPLATES = (
    "取消票号是{ticket}的退票单，取消原因你帮我自动填写。",
    "请撤销票号{ticket}对应的退票申请，原因由系统自动填写。",
    "帮我取消票号{ticket}的退票单，原因自动选一个合适的。",
    "票号{ticket}的退票申请不要继续了，请取消这张退票单，取消原因自动填写。",
    "现在取消票号{ticket}对应的退票单即可，原因请自动填。",
)


def save_json(path: Path, payload: Any) -> None:
    """保存本地实验结果；调用方负责私有目录，文件不写入密钥或供应商异常正文。"""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


class RefundWorkflow:
    """为一个自然语言请求绑定票号候选和稳定执行键；复用真实业务服务而非准备结果。"""

    def __init__(self, job: dict[str, Any], key_file: Path):
        """从原始请求建立本地身份映射；key_file仅传给Jev调用，未查询前没有真实退票目标。"""
        self.job = job
        self.key_file = key_file
        self.state, self.tickets = models.make_state(job["user_request"])
        self.refund_no = ""
        self.ticket = ""
        self.ready = False
        self.report: dict[str, Any] = {"verified": False, "calls": [], "tools": [], "preflight_ms": 0}

    def preflight(self) -> None:
        """首次动作前检查历史写入；当前QA环境和操作契约由每次既有execute服务校验。"""
        if self.ready:
            return
        started = time.perf_counter()
        # 已发起过取消的样本不能再被计成一条全新的速度测量。
        if qa.known_execution(self.job["request_id"] + "-cancel") is not None:
            raise ValueError("prior_write_requires_readonly_inspection")
        # execute/execute_resolved已逐次校验当前目录、绑定和环境，重复四次只读HTTP不会增强这些约束。
        self.report["preflight_ms"] = (time.perf_counter() - started) * 1000
        self.ready = True

    def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """用本请求稳定的动作键调用既有执行服务，返回真实业务输出并积累逐阶段耗时。"""
        output, evidence = qa.execute(action, arguments, self.job["request_id"] + "-" + action)
        self.report["calls"].append(evidence)
        return output

    def query(self, candidate: str) -> dict[str, Any]:
        """查询原文候选的真实票号并绑定唯一可取消退票单；对外只返回候选名和状态。"""
        if candidate not in self.tickets:
            raise ValueError("unknown_ticket_candidate")
        self.ticket = self.tickets[candidate]
        self.preflight()
        queried = self.execute("queryList", {"ticketNo": self.ticket, "page": 1, "pageSize": 1000})
        page = queried.get("list") or {}
        orders = page.get("pageList") or []
        cancellable = [order for order in orders if order.get("refundState") in qa.CANCELLABLE]
        if len(cancellable) != 1:
            raise ValueError("refund_target_not_unique")
        # 单号只能取自当前查询；准备阶段的预期单号不会参与实际目标选择。
        target = qa.eligible_refund(queried, cancellable[0]["refundSerialNo"])
        self.refund_no = target["refundSerialNo"]
        self.report["before_state"] = target["refundState"]
        return {"refund_candidate": "r1", "ticket_candidate": candidate,
                "state": target["refundState"], "unique_cancellable": True}

    def cancel(self, candidate: str) -> dict[str, Any]:
        """只取消本请求查询并校验过的r1，按已授权自动原因策略提交，服务端保持请求去重。"""
        if candidate != "r1" or not self.refund_no:
            raise ValueError("cancel_requires_verified_query")
        # 取消原因是已验证的固定策略，模型不能添加其他API、订单或任意字段。
        self.execute("cancel", {"refundSerialNo": self.refund_no, "cancelReasonId": "OTHER",
                                "cancelReason": "用户要求取消", "cancelRemark": "OpenTest QA：Jev入口耗时对照"})
        return {"accepted": True, "readback_required": True, "refund_candidate": "r1"}

    def verify(self, candidate: str) -> dict[str, Any]:
        """独立读取目标详情，核实票号、退票身份及REFUND_CANCEL；不以取消响应代替结果。"""
        if candidate != "r1" or not self.refund_no:
            raise ValueError("verify_requires_verified_query")
        observed = self.execute("queryDetailByRefundNo", {"refundSerialNo": self.refund_no})
        self.report["verified"] = qa.verified_readback(observed, self.refund_no, self.ticket)
        if not self.report["verified"]:
            raise ValueError("readback_failed")
        return {"verified": True, "refund_candidate": "r1", "state": "REFUND_CANCEL"}

    def run_fast(self) -> dict[str, Any]:
        """一次Jev调用后连续执行三个业务阶段；失败保留并只读观察未知写入，不自动重试。"""
        started = time.perf_counter()
        try:
            measured = models.measure("jev", self.job["user_request"], self.key_file)
            self.report["model"] = measured
            decision = measured.get("decision") or {}
            self.report["cancellation_route"] = bool(measured["ok"] and models.cancellation_route(decision))
            if not measured["ok"]:
                raise ValueError("model_request_failed")
            if not self.report["cancellation_route"] or decision.get("reason") != "automatic":
                self.report["outcome"] = "not_executed"
            else:
                self.query(decision["target"])
                self.cancel("r1")
                self.verify("r1")
                self.report["outcome"] = "verified"
        except Exception as exc:
            self.record_failure(exc)
        self.report["workflow_ms"] = (time.perf_counter() - started) * 1000
        self.report["business_ms"] = sum(call["elapsed_ms"] for call in self.report["calls"])
        return self.report

    def record_failure(self, exc: Exception) -> None:
        """保留安全错误分类；取消结果未知时只读查记录及详情，诊断成功也不掩盖原始失败。"""
        self.report["error_type"] = type(exc).__name__
        self.report["outcome"] = "failed"
        if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc)):
            self.report["error_code"] = str(exc)
        record = qa.known_execution(self.job["request_id"] + "-cancel")
        if record is not None and not self.refund_no:
            # 取消记录不保存请求参数；从同一次真实查询记录恢复身份，不能使用准备阶段预期值。
            queried = qa.known_execution(self.job["request_id"] + "-queryList")
            output = ((queried or {}).get("result") or {}).get("output") or {}
            candidates = [order for order in (output.get("list") or {}).get("pageList", [])
                          if order.get("refundState") in qa.CANCELLABLE]
            if len(candidates) == 1 and self.ticket:
                try:
                    target = qa.eligible_refund(output, candidates[0]["refundSerialNo"])
                    self.refund_no = target["refundSerialNo"]
                except ValueError:
                    self.report["diagnostic_error"] = "previous_query_not_usable"
            else:
                self.report["diagnostic_error"] = "previous_query_not_usable"
        if record is not None and self.refund_no:
            # 读请求也去重，每次诊断都用新观察键；写键保持稳定，旧错误仍不变成速度成功样本。
            try:
                observed, evidence = qa.execute("queryDetailByRefundNo", {"refundSerialNo": self.refund_no},
                                                self.job["request_id"] + "-diagnostic-" + str(time.time_ns()))
                self.report["calls"].append(evidence)
                self.report["diagnostic_cancelled"] = qa.verified_readback(observed, self.refund_no, self.ticket)
            except Exception as diagnostic_error:
                self.report["diagnostic_error"] = type(diagnostic_error).__name__
        LOGGER.warning("入口实验失败 sample=%s error=%s", self.job["request_id"], type(exc).__name__)


def call_entry(job: dict[str, Any]) -> dict[str, Any]:
    """提交完整中文到固定本机实验HTTP入口并返回最终回查证据；不使用代理或跟随重定向。"""
    request = Request(ENTRY_URL, method="POST", headers={"Content-Type": "application/json"},
                      data=json.dumps({"sample_id": job["sample_id"], "user_request": job["user_request"]}, ensure_ascii=False).encode())
    # Codex单次工具和直接HTTP组使用同一路由与相同请求结构。
    with build_opener(ProxyHandler({}), models.NoRedirect()).open(request, timeout=180) as response:
        return json.load(response)


def serve_http(root: Path, key_file: Path) -> None:
    """在8789启动实验HTTP入口，仅接收预先准备样本的原文，密钥与业务标识只留在本机。"""
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from opentest.application.log_context import bind_workflow_log_context
    app = FastAPI()

    @app.post("/cancel")
    def cancel_request(payload: dict[str, str]) -> dict[str, Any]:
        """执行一个已准备样本并返回回查与耗时；拒绝改写原文、未知样本或重复计量。"""
        sample_id = payload.get("sample_id", "")
        if not re.fullmatch(r"sample-\d{2}-(?:codex-atomic|codex-jev|http-jev|negative)", sample_id):
            raise HTTPException(400, "invalid_sample")
        directory = root / sample_id
        job_path = directory / "job.json"
        if not job_path.is_file():
            raise HTTPException(404, "sample_not_prepared")
        job = json.loads(job_path.read_text())
        if payload.get("user_request") != job["user_request"]:
            raise HTTPException(400, "request_mismatch")
        if (directory / "workflow.json").exists():
            raise HTTPException(409, "sample_already_measured")
        # 日志上下文按请求绑定并在异常退出时由现有context manager清理。
        with bind_workflow_log_context(qa.SYSTEM, "jev-entry-http", job["request_id"]):
            workflow = RefundWorkflow(job, key_file)
            report = workflow.run_fast()
            save_json(directory / "workflow.json", report)
            return report

    uvicorn.run(app, host="127.0.0.1", port=8789, access_log=False)


def tool_definitions(arm: str) -> list[dict[str, Any]]:
    """返回两条Agent路径的最小工具契约；原子组和聚合组共享查询、校验、取消、回查语义。"""
    # 仅改变业务编排归属；两组工具均限制在本样本的同一组真实操作及候选内。
    choices = [("execute_refund_request", "将用户原文交给Jev及固定QA流程，一次调用返回真实取消回查。", "user_request")]
    if arm == "codex-atomic":
        choices = [("query_refund", "按原文票号候选查询并校验唯一可取消退票单，返回真实退票候选。", "ticket_candidate"),
                   ("cancel_refund", "取消已经查询核实的退票候选，按用户授权自动填原因；随后必须回查。", "refund_candidate"),
                   ("verify_refund", "独立回查退票候选的身份、票号关联及REFUND_CANCEL。", "refund_candidate")]
    return [{"name": name, "description": description,
             "annotations": {"readOnlyHint": name in {"query_refund", "verify_refund"},
                             "destructiveHint": name in {"cancel_refund", "execute_refund_request"},
                             "idempotentHint": True, "openWorldHint": False},
             "inputSchema": {"type": "object", "properties": {field: ({"type": "string"} if field == "user_request" else
                                                                          {"type": "string", "enum": ["t1" if field == "ticket_candidate" else "r1"]})},
                             "required": [field], "additionalProperties": False}}
            for name, description, field in choices]


def serve_mcp(job_path: Path, key_file: Path) -> None:
    """以项目既有逐行JSON-RPC形式提供实验工具；每个进程绑定一个样本，不改全局MCP配置。"""
    from opentest.application.log_context import bind_workflow_log_context
    job = json.loads(job_path.read_text())
    workflow = RefundWorkflow(job, key_file)
    directory = job_path.parent
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request.get("method")
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request["id"]}
        if method == "initialize":
            response["result"] = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "refund-entry-experiment", "version": "1"},
                                  "instructions": "执行用户授权的QA请求，不需另行确认；必须收到真实回查成功才能报告完成。"}
        elif method == "tools/list":
            response["result"] = {"tools": tool_definitions(job["arm"])}
        elif method == "tools/call":
            params = request["params"]
            started = time.perf_counter()
            try:
                with bind_workflow_log_context(qa.SYSTEM, "jev-entry-mcp", job["request_id"]):
                    output = dispatch_tool(workflow, params["name"], params.get("arguments", {}))
                response["result"] = {"content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}]}
            except Exception as exc:
                workflow.record_failure(exc)
                response["result"] = {"isError": True, "content": [{"type": "text", "text": type(exc).__name__}]}
            workflow.report["tools"].append({"name": params["name"], "elapsed_ms": (time.perf_counter() - started) * 1000})
            save_json(directory / "mcp.json", workflow.report)
        elif method == "ping":
            response["result"] = {}
        else:
            response["error"] = {"code": -32601, "message": "method_not_supported"}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def dispatch_tool(workflow: RefundWorkflow, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """校验当前实验路径允许的工具和原文，返回仅含候选及业务结果的模型可见内容。"""
    allowed = {tool["name"] for tool in tool_definitions(workflow.job["arm"])}
    if name not in allowed:
        raise ValueError("tool_not_in_arm")
    if name == "execute_refund_request":
        if arguments.get("user_request") != workflow.state["user_request"]:
            raise ValueError("original_request_changed")
        report = call_entry(workflow.job)
        workflow.report["verified"] = report["verified"]
        workflow.report["workflow_ms"] = report["workflow_ms"]
        return {"verified": report["verified"], "outcome": report["outcome"],
                "state": "REFUND_CANCEL" if report["verified"] else None}
    if name == "query_refund":
        return workflow.query(arguments.get("ticket_candidate", ""))
    if name == "cancel_refund":
        return workflow.cancel(arguments.get("refund_candidate", ""))
    return workflow.verify(arguments.get("refund_candidate", ""))


def stop_agent_group(process: subprocess.Popen) -> None:
    """终止本次CLI的独立进程组并回收父进程；正常或超时退出都不能留下MCP后代继续执行。"""
    # 进程组由start_new_session创建，仅属于本样本；不按进程名清理用户其他Codex任务。
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # 父进程先退出并不证明后代结束，仍向本组清理可能忽略TERM的MCP进程。
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_agent(job_path: Path, key_file: Path) -> dict[str, Any]:
    """计时完整临时xhigh会话，记录启动、工具事件及最终答复；180秒超时保留为失败。"""
    job = json.loads(job_path.read_text())
    state, _ = models.make_state(job["user_request"])
    prompt = ("执行下面用户授权的QA请求。票号已替换为本地可逆候选，不能猜测真实标识。"
              "两种工具路径均使用已验证的查询、唯一可取消目标校验、取消及独立回查契约。"
              "原因自动填写采用OTHER/用户要求取消。得到verified=true才可报告成功。"
              "直接使用提供的工具，不执行其他操作。传递用户原文时不得改写。\n"
              + json.dumps(state, ensure_ascii=False))
    with tempfile.TemporaryDirectory(prefix="refund-entry-") as temporary:
        workspace = Path(temporary)
        schema = workspace / "result.json"
        save_json(schema, {"type": "object", "properties": {"verified": {"type": "boolean"}, "summary": {"type": "string"}},
                           "required": ["verified", "summary"], "additionalProperties": False})
        command = models.codex_command(workspace, schema, "xhigh")[:-1]
        # 覆盖仅影响本次CLI，系统已安装的插件和模型设置不变。
        settings = {"command": str(models.ROOT / ".venv/bin/python"),
                    "args": ["-m", "scripts.benchmark_refund_entry", "mcp", "--job", str(job_path), "--key-file", str(key_file)],
                    "env.PYTHONPATH": str(models.ROOT), "enabled": True,
                    "startup_timeout_sec": 30, "tool_timeout_sec": 120}
        for key, setting in settings.items():
            command.extend(["-c", f"mcp_servers.refund_entry_experiment.{key}={json.dumps(setting)}"])
        # 用户已授权本次QA实验；预授权仅限这个进程内、绑定单个准备样本的三个或一个工具。
        for tool in tool_definitions(job["arm"]):
            command.extend(["-c", f'mcp_servers.refund_entry_experiment.tools.{tool["name"]}.approval_mode="approve"'])
        command.append("-")
        started = time.perf_counter()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        events = []
        report: dict[str, Any] = {"ok": False, "usage": {}}
        try:
            process.stdin.write(prompt.encode())
            process.stdin.close()
            buffer = b""
            while True:
                remaining = 180 - (time.perf_counter() - started)
                if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                    raise TimeoutError("agent_timeout")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    event = json.loads(line)
                    elapsed = (time.perf_counter() - started) * 1000
                    item = event.get("item") or {}
                    events.append({"type": event.get("type"), "item_type": item.get("type"),
                                   "tool": item.get("tool"), "elapsed_ms": elapsed})
                    if event.get("type") == "turn.started":
                        report["startup_ms"] = elapsed
                    if event.get("type") == "turn.completed":
                        report["usage"] = event.get("usage", {})
                    if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                        # 工具前的进度文字不是最终结构化答案，不能因此中止仍在进行的业务流程。
                        try:
                            answer = json.loads(item.get("text", "{}"))
                        except json.JSONDecodeError:
                            continue
                        if isinstance(answer, dict) and isinstance(answer.get("verified"), bool):
                            report["answer"] = answer
            report["ok"] = process.wait(timeout=5) == 0 and bool(report.get("answer"))
        except Exception as exc:
            report["error_type"] = type(exc).__name__
        finally:
            stop_agent_group(process)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()
        report["entry_ms"] = (time.perf_counter() - started) * 1000
        report["events"] = events
        return report


def prepare_experiment(args: argparse.Namespace) -> None:
    """冻结十五个比较槽位和共享中文模板；真实退票单在各次计时开始前通过固定版本函数准备。"""
    qa.preflight()
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (args.output / "qa").mkdir(mode=0o700)
    save_json(args.output / "qa/qa-inputs.json", {"run_id": args.run_id, "orders": [], "preparation_ms": 0, "ready": False})
    for index in range(15):
        round_index, arm_index = divmod(index, 3)
        arm = ARMS[(round_index + arm_index) % 3]
        sample_id = f"sample-{index + 1:02}-{arm}"
        directory = args.output / sample_id
        directory.mkdir(mode=0o700)
        save_json(directory / "job.json", {"sample_id": sample_id, "arm": arm,
                  "request_id": f"{args.run_id}-{index + 1}", "round": round_index + 1,
                  "request_template": TEMPLATES[round_index]})


def prepare_job(job_path: Path) -> dict[str, Any]:
    """为冻结槽位准备新退票并保存原文；中断后复用本槽位准备记录，不重复创建或重复统计。"""
    from scripts.prepare_refund_entry_data import prepare_refund_entry_v1
    job = json.loads(job_path.read_text())
    if "user_request" in job:
        return job
    inputs_path = job_path.parent.parent / "qa/qa-inputs.json"
    inputs = json.loads(inputs_path.read_text())
    # 准备记录先落盘、job后落盘；若两者之间中断，按槽位恢复已有真实身份。
    prepared = next((order for order in inputs["orders"] if order.get("sample_id") == job["sample_id"]), None)
    if prepared is None:
        prepared = prepare_refund_entry_v1(job["request_id"] + "-prepare")
        if prepared["refund_no"] in {order["refund_no"] for order in inputs["orders"]}:
            raise ValueError("prepared_refund_was_already_used")
        prepared["sample_id"] = job["sample_id"]
        inputs["orders"].append(prepared)
        inputs["preparation_ms"] += prepared["preparation_ms"]
        inputs["ready"] = len(inputs["orders"]) == 15
        save_json(inputs_path, inputs)
    job.update(user_request=job["request_template"].format(ticket=prepared["ticket"]),
               expected_refund=prepared["refund_no"], expected_ticket=prepared["ticket"])
    save_json(job_path, job)
    return job


def run_experiment(args: argparse.Namespace) -> None:
    """按冻结顺序运行两个xhigh路径及直接HTTP路径；失败也落盘，已存在结果不重复取消。"""
    for directory in sorted(args.output.glob("sample-*")):
        if (directory / "result.json").exists():
            continue
        job_path = directory / "job.json"
        job = json.loads(job_path.read_text())
        if args.limit and int(job["sample_id"].split("-")[1]) > args.limit:
            break
        # 新建并回查完成后才启动入口计时；底层出票订单可共享，退票身份必须不同。
        job = prepare_job(job_path)
        started = time.perf_counter()
        if job["arm"] == "http-jev":
            try:
                workflow = call_entry(job)
                report = {"ok": True, "entry_ms": (time.perf_counter() - started) * 1000,
                          "answer": {"verified": workflow["verified"]}}
            except Exception as exc:
                report = {"ok": False, "entry_ms": (time.perf_counter() - started) * 1000, "error_type": type(exc).__name__}
        else:
            report = run_agent(job_path, args.key_file)
        evidence_path = directory / ("mcp.json" if job["arm"] == "codex-atomic" else "workflow.json")
        evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
        # 真实执行证据和Agent最终答复必须同时成功，不能只统计工具内成功。
        report["verified"] = bool(report["ok"] and report.get("answer", {}).get("verified") and evidence.get("verified")
                                  )
        report["had_tool_error"] = bool(evidence.get("error_type"))
        report.update(arm=job["arm"], sample_id=job["sample_id"])
        save_json(directory / "result.json", report)
        LOGGER.info("入口对照 sample=%s arm=%s verified=%s elapsed_ms=%.1f", job["sample_id"], job["arm"], report["verified"], report["entry_ms"])


def write_report(root: Path) -> None:
    """按原始测量生成三路径对照及十秒达标比例；小样本只报告中位数和范围，不报告可靠P95。"""
    rows = []
    for path in sorted(root.glob("sample-*/result.json")):
        row = json.loads(path.read_text())
        inner = path.parent / ("mcp.json" if row["arm"] == "codex-atomic" else "workflow.json")
        row["inner"] = json.loads(inner.read_text()) if inner.exists() else {}
        rows.append(row)
    summary = {}
    lines = ["# Jev 十秒入口可行性实验", "", "原162.4秒仅为历史参考。本次两组Codex均为gpt-5.6-sol/xhigh，原子组已获得相同业务契约，省去了原任务的接口搜索和源码阅读；不运行low。Codex使用CLI，计时含启动、工具调用和最终答复，不包含桌面渲染。", "",
             "| 路径 | 成功/尝试 | 十秒内完成 | 总耗时中位数 | 范围 |", "|---|---:|---:|---:|---:|"]
    for arm in ARMS:
        group = [row for row in rows if row["arm"] == arm]
        if not group:
            continue
        durations = [row["entry_ms"] / 1000 for row in group]
        within = sum(row["verified"] and row["entry_ms"] <= 10000 for row in group)
        summary[arm] = {"count": len(group), "verified": sum(row["verified"] for row in group),
                        "within_10s": within, "median_seconds": statistics.median(durations),
                        "min_seconds": min(durations), "max_seconds": max(durations)}
        item = summary[arm]
        lines.append(f"| {arm} | {item['verified']}/{len(group)} | {within}/{len(group)} | {item['median_seconds']:.3f}s | {min(durations):.3f}–{max(durations):.3f}s |")
    lines += ["", "每条路径五个独立订单，是可行性试点，不足以保证P95或所有业务请求均低于十秒。失败保留在尝试分母和总等待时间统计中。", "", "## 单次流程工具与外层Codex", ""]
    for row in rows:
        if row["arm"] != "codex-jev" or not row["inner"]:
            continue
        inner_ms = row["inner"].get("workflow_ms", 0)
        lines.append(f"- {row['sample_id']}：完整入口 {row['entry_ms']/1000:.3f}s；服务端流程 {inner_ms/1000:.3f}s；外层及传输差额 {(row['entry_ms']-inner_ms)/1000:.3f}s。")
    lines += ["", "Jev只接收脱敏原文、候选标签、业务契约及闭集问题；真实票号和退款单号由本地映射与实时查询取得。取消状态、唯一目标、幂等和回查由代码执行。直接HTTP组与Codex单次工具组调用同一个本机HTTP接口。", "", "## 失败", ""]
    for row in rows:
        if not row["verified"]:
            lines.append(f"- {row['sample_id']}：{row.get('error_type') or row['inner'].get('error_code') or '未取得完整成功证据'}。")
    prepared = json.loads((root / "qa/qa-inputs.json").read_text())
    lines += ["", f"QA数据准备 {prepared['preparation_ms']/1000:.3f}s，单独计量；服务启动不计入请求耗时。运行前已有服务可用，所有请求仍执行环境及当前操作契约校验。"]
    lines += ["", "数据不足时，通过prepare_refund_entry_v1在每次计时前动态创建新的真实退票单并回查；允许共享原出票订单，退票单身份不得复用。QA准备会使服务处于已运行状态，因此这些是运行中服务的请求耗时，不是冷启动保证。"]
    save_json(root / "comparison.json", summary)
    (root / "report.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    """选择准备、HTTP服务、MCP适配、实验或报告阶段；所有业务入口使用现有日志上下文。"""
    from opentest.application.log_context import configure_logging, bind_workflow_log_context
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "serve", "mcp", "run", "report"))
    parser.add_argument("--output", type=Path, default=models.ROOT / ".opentest/jev-refund-entry")
    parser.add_argument("--job", type=Path)
    parser.add_argument("--run-id", default="jev-entry-20260923-v1")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--key-file", type=Path, default=Path("/Users/user/data/api_key/jev_api_key.txt"))
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,70}", args.run_id):
        parser.error("invalid run-id")
    configure_logging()
    # 由统一上下文管理器覆盖各实验阶段，退出时恢复日志上下文，避免请求之间串号。
    with bind_workflow_log_context(qa.SYSTEM, "jev-entry-experiment", args.run_id):
        if args.phase == "prepare":
            prepare_experiment(args)
        elif args.phase == "serve":
            serve_http(args.output, args.key_file)
        elif args.phase == "mcp":
            if args.job is None:
                parser.error("mcp requires --job")
            serve_mcp(args.job, args.key_file)
        elif args.phase == "run":
            run_experiment(args)
        else:
            write_report(args.output)


if __name__ == "__main__":
    main()
