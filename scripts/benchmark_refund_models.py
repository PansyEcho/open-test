"""使用相同闭集契约比较Jev和Codex；只输出决策，不直接访问订单业务。"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
import re
import select
import statistics
import subprocess
import tempfile
import time
import tomllib
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("jev", "codex-xhigh", "codex-low")
FIELDS = ("intent", "action", "target", "reason")
MODEL = "jev-1.13.0"
# QA中也存在短数字票号；只有用户明确写出票号字段时才接纳，避免把日期或数量当目标。
TICKET_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Z]{2,6})?\d{10,20}(?![A-Za-z0-9_])"
    r"|(?:(?<=票号)|(?<=票号是)|(?<=票号为))\d{3,9}(?![A-Za-z0-9_])"
)
LOGGER = logging.getLogger(__name__)
CONTRACT = {
    "scope": "取消退票申请和取消原机票订单不同。此实验只提供单个退票单取消能力。",
    "flow": "按原文票号查询；必须唯一对应真实可取消退票单；取消后独立回查相同退票单REFUND_CANCEL。",
    "identifiers": "候选仅来自原文。不能生成或猜测票号、退票单号。多个目标不自动选择第一张。",
}
RUBRIC = {
    "intent": {
        "instructions": "判断用户本轮主要讨论或要求的业务动作。即使否定或只咨询，也选择对应动作；是否执行由action另行判断。以最后明确的主要要求为准。",
        "criteria": {"cancel_refund": "取消已有退票单、撤销退票申请", "query_refund": "查询退票或退款状态", "create_refund": "新建、发起退票申请", "cancel_booking": "取消原机票订单", "other": "其他或无法识别业务动作"},
    },
    "action": {
        "instructions": "独立阅读user_request，判断说话者要不要现在办理其要求的动作。要求取消/撤销退票申请本身也是肯定的执行请求：取消和撤销是业务动词，不代表禁止执行。查状态/帮我查查也属于execute。仅咨询能否取消、操作方法或一般知识问题属于inquire，即使附带先别操作。只有明确说不要取消、不撤销、别执行才属于refrain。明确说尚未决定、等我通知属于unclear。",
        "criteria": {"execute": "明确要求现在办理动作，包括取消、撤销、查询或创建", "inquire": "只提出问题，请求解释、可行性、方法或一般知识回答", "refrain": "明确禁止所讨论的业务动作，或取消了先前的执行要求", "unclear": "未决定、等通知或意图不明，不包括普通提问"},
    },
    "reason": {
        "instructions": "用户如何要求填写取消原因？必须有原文依据；没有提到原因即unspecified。",
        "criteria": {"automatic": "明确允许系统选择或自动填写原因", "explicit": "明确给出要填写的原因内容", "unspecified": "没有指定或授权自动选择原因"},
    },
}


class NoRedirect(HTTPRedirectHandler):
    """密钥只能发送到配置的官方端点，拒绝HTTP重定向。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """拒绝urllib规定签名的重定向回调，返回None以保留原HTTP错误。"""
        return None


def make_state(text: str) -> tuple[dict[str, Any], dict[str, str]]:
    """把输入中的票号替换为候选占位符，返回模型上下文及仅本地使用的逆向映射。"""
    # 相同票号只建一个候选，按出现顺序保持多目标指令的语义。
    tickets = list(dict.fromkeys(TICKET_PATTERN.findall(text)))
    mapping = {f"t{i + 1}": ticket for i, ticket in enumerate(tickets)}
    placeholders = {ticket: f"TICKET_{candidate[1:]}" for candidate, ticket in mapping.items()}

    def mask_ticket(match: re.Match[str]) -> str:
        """把原文完整匹配的票号映射为占位符，返回替换文本，避免短号污染长号。"""
        return placeholders[match.group(0)]

    masked = TICKET_PATTERN.sub(mask_ticket, text)
    candidates = {candidate: f"TICKET_{candidate[1:]}" for candidate in mapping}
    return {"user_request": masked, "candidates": candidates, "contract": CONTRACT}, mapping


def questions_for(state: dict[str, Any]) -> dict[str, Any]:
    """基于同一候选集合生成四个独立闭集问题，返回两种模型共同使用的题面。"""
    questions = {name: {"type": "choice", **question} for name, question in RUBRIC.items()}
    # none/ambiguous必须显式存在，避免闭集强迫模型选择某一真实订单。
    criteria = {key: f"唯一目标是原文中的{token}" for key, token in state["candidates"].items()}
    criteria.update({"none": "原文没有可用票号目标", "ambiguous": "要求多个目标，或有多个候选但未唯一指定一个"})
    questions["target"] = {
        "type": "choice", "criteria": criteria,
        "instructions": "选择主要动作对应的唯一票号候选；不受是否执行影响。重复出现同一票号仍是一个目标；明确只操作其中一个时选该候选；多个目标或未明确选哪一个必须ambiguous；未给票号必须none。",
    }
    return questions


def validate_decision(decision: Any, questions: dict[str, Any]) -> dict[str, str]:
    """校验模型闭集输出并返回规范决策；字段缺失、多余或越界时抛出ValueError。"""
    if not isinstance(decision, dict) or set(decision) != set(FIELDS):
        raise ValueError("decision_fields_invalid")
    # 禁止把模型任意字符串解释成API、标识或可执行参数。
    for name in FIELDS:
        if not isinstance(decision[name], str) or decision[name] not in questions[name]["criteria"]:
            raise ValueError("decision_choice_invalid")
    return decision


def cancellation_route(decision: dict[str, str]) -> bool:
    """判断决策是否企图路由到单目标取消；不等同于状态校验或业务执行授权。"""
    return (decision["intent"] == "cancel_refund" and decision["action"] == "execute"
            and decision["target"] not in {"none", "ambiguous"})


def call_jev(state: dict[str, Any], key_file: Path) -> dict[str, Any]:
    """调用固定版本Jev并返回闭集决策、置信度和用量；密钥仅在内存中读取且不自动重试。"""
    key = key_file.read_text().strip()
    if not key or "\n" in key:
        raise ValueError("invalid_key_file")
    questions = questions_for(state)
    request = Request("https://api.typesafe.ai/v1/systemone", method="POST",
                      data=json.dumps({"model": MODEL, "state": state, "questions": questions}, ensure_ascii=False).encode(),
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    # 不记录请求头或异常正文，避免第三方错误回显密钥或请求内容。
    with build_opener(NoRedirect()).open(request, timeout=45) as response:
        payload = json.load(response)
    if payload.get("model") != MODEL:
        raise ValueError("unexpected_model_version")
    answers = payload["answers"]
    decision = validate_decision({name: answers[name]["choice"] for name in FIELDS}, questions)
    return {"decision": decision, "model": payload["model"], "usage": payload.get("usage", {}),
            "confidence": {name: answers[name].get("confidence") for name in FIELDS},
            "cli_startup_ms": None}


def codex_command(workspace: Path, schema_path: Path, effort: str) -> list[str]:
    """构造保留现有认证/provider的临时只读CLI命令；禁用工具和用户MCP以固定实验上下文。"""
    executable = os.environ.get("OPENTEST_BENCHMARK_CODEX", "codex")
    command = [executable, "-a", "never", "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules",
               "--json", "--color", "never", "--sandbox", "read-only", "-C", str(workspace),
               "--model", "gpt-5.6-sol", "-c", f'model_reasoning_effort="{effort}"',
               "-c", 'service_tier="default"', "--output-schema", str(schema_path)]
    # 仅覆盖本子进程的扩展能力；不能用ignore-user-config丢掉用户现有provider配置。
    for feature in ("shell_tool", "unified_exec", "apps", "browser_use", "computer_use", "image_generation",
                    "multi_agent", "plugins", "hooks", "tool_call_mcp_elicitation"):
        command.extend(["--disable", feature])
    config_path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    for name in config.get("mcp_servers", {}):
        # Codex的-c按点分割键，不支持把引号当作TOML路径转义；沿用项目已有名称限制。
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("unsupported_mcp_name")
        command.extend(["-c", f"mcp_servers.{name}.enabled=false"])
    command.append("-")
    return command


def call_codex(state: dict[str, Any], effort: str) -> dict[str, Any]:
    """调用独立Codex CLI决策并返回用量及可观测启动窗口；不会启动工具或持久会话。"""
    questions = questions_for(state)
    schema = {"type": "object", "properties": {name: {"type": "string", "enum": list(questions[name]["criteria"])} for name in FIELDS},
              "required": list(FIELDS), "additionalProperties": False}
    prompt = "Evaluate each independent closed-choice question against state. Return only the four selected option keys as JSON. Do not execute any business action.\n"
    prompt += json.dumps({"state": state, "questions": questions}, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix="jev-refund-codex-") as directory:
        workspace = Path(directory)
        schema_path = workspace / "decision-schema.json"
        schema_path.write_text(json.dumps(schema))
        started = time.perf_counter()
        # 事件按流读取，启动指标定义为进程创建至turn.started，不冒充模型内部耗时。
        process = subprocess.Popen(codex_command(workspace, schema_path, effort), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        startup_ms = None
        final_text = ""
        usage = {}
        try:
            process.stdin.write(prompt)
            process.stdin.close()
            buffer = b""
            while True:
                # 固定单次截止时间保留超时样本；不让CLI的网络恢复拖住整组实验。
                remaining = 180 - (time.perf_counter() - started)
                if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                    raise TimeoutError("codex_decision_timeout")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    event = json.loads(line)
                    if event.get("type") == "turn.started" and startup_ms is None:
                        startup_ms = round((time.perf_counter() - started) * 1000, 3)
                    if event.get("type") == "item.completed":
                        item = event.get("item", {})
                        if item.get("type") in {"command_execution", "mcp_tool_call"}:
                            raise ValueError("unexpected_tool_call")
                        if item.get("type") == "agent_message":
                            final_text = item.get("text", "")
                    if event.get("type") == "turn.completed":
                        usage = event.get("usage", {})
            if process.wait() != 0:
                raise ValueError("codex_failed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # 超时退出必须回收本次CLI，不能留下继续计费的子进程。
                    process.kill()
                    process.wait()
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()
        decision = validate_decision(json.loads(final_text), questions)
        return {"decision": decision, "model": "gpt-5.6-sol", "reasoning_effort": effort,
                "usage": usage, "cli_startup_ms": startup_ms}


def measure(arm: str, text: str, key_file: Path) -> dict[str, Any]:
    """测量一次完整客户端决策调用；模型/网络错误保留为失败，不替换模型或自动重试。"""
    state, _ = make_state(text)
    started = time.perf_counter()
    try:
        if arm == "jev":
            result = call_jev(state, key_file)
        elif arm in ARMS:
            result = call_codex(state, arm.removeprefix("codex-"))
        else:
            raise ValueError("unknown_arm")
        result["ok"] = True
    except Exception as exc:
        # 失败也参与分母；只输出安全异常分类，永不把供应商正文或密钥写入报告。
        result = {"ok": False, "error_type": type(exc).__name__}
        if isinstance(exc, HTTPError):
            result["http_status"] = exc.code
        elif isinstance(exc, ValueError) and str(exc) in {"unexpected_model_version", "codex_failed", "decision_choice_invalid", "unexpected_tool_call"}:
            result["error_code"] = str(exc)
    result.update(arm=arm, client_ms=round((time.perf_counter() - started) * 1000, 3))
    return result


def score_sample(sample: dict[str, Any], measurement: dict[str, Any]) -> dict[str, Any]:
    """把预先标注的答案与模型决策比较；标注仅用于本地计分，绝不传给模型。"""
    expected = dict(zip(FIELDS, sample["expected"], strict=True))
    decision = measurement.get("decision")
    # unsafe包括错误目标，不能只检查模型有没有选取消标签。
    unsafe = bool(decision and cancellation_route(decision) and
                  (not cancellation_route(expected) or decision["target"] != expected["target"]))
    return {**measurement, "sample_id": sample["id"], "expected": expected,
            "correct": bool(measurement["ok"] and decision == expected), "unsafe_route": unsafe,
            "unresolved": bool(not decision or decision["target"] in {"none", "ambiguous"}
                               or decision["action"] == "unclear")}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """按组汇总观测耗时和含失败分母的准确率；返回可序列化统计，不推断端到端提速。"""
    summary = {}
    for arm in ARMS:
        group = [row for row in rows if row["arm"] == arm]
        if not group:
            continue
        # 成功延迟与错误耗时分开，防止快速HTTP失败使模型看起来更快。
        durations = sorted(row["client_ms"] for row in group if row["ok"])
        startup = [row["cli_startup_ms"] for row in group if row.get("cli_startup_ms") is not None]
        summary[arm] = {"count": len(group), "successes": sum(row["ok"] for row in group),
                        "accuracy": sum(row["correct"] for row in group) / len(group),
                        "unsafe_routes": sum(row["unsafe_route"] for row in group),
                        "unresolved_rate": sum(row["unresolved"] for row in group) / len(group),
                        "median_client_ms": statistics.median(durations) if durations else None,
                        "p95_client_ms": durations[math.ceil(len(durations) * .95) - 1] if durations else None,
                        "median_cli_startup_ms": statistics.median(startup) if startup else None,
                        "failed_elapsed_ms": [row["client_ms"] for row in group if not row["ok"]],
                        "input_tokens": sum(row.get("usage", {}).get("input_tokens", 0) for row in group),
                        "output_tokens": sum(row.get("usage", {}).get("output_tokens", 0) for row in group)}
    return summary


def run_samples(args: argparse.Namespace) -> None:
    """执行指定样本分区并逐条保存结果；输出目录必须新建以防把重复调用混入旧结果。"""
    fixtures = json.loads(args.cases.read_text())
    samples = fixtures[args.split]
    if args.limit:
        samples = samples[:args.limit]
    args.output.mkdir(parents=True, exist_ok=False)
    os.chmod(args.output, 0o700)
    arms = list(ARMS) if args.arm == "all" else [args.arm]
    rows = []
    # 保存实际发送的公共契约和题面，之后可核实各组确实使用同一版本。
    metadata = {"split": args.split, "repeats": args.repeats, "arms": arms, "rubric": RUBRIC,
                "contract": CONTRACT, "fixture_cases": samples, "timing": "client wall clock; CLI startup is launch to turn.started"}
    (args.output / "inputs.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    with (args.output / "samples.jsonl").open("x") as output:
        for repeat in range(args.repeats):
            for index, sample in enumerate(samples):
                # 顺序轮换抵消时间段和热启动偏差，正式测量不并发争抢同一provider资源。
                offset = (index + repeat) % len(arms)
                for arm in arms[offset:] + arms[:offset]:
                    measurement = measure(arm, sample["text"], args.key_file)
                    scored = score_sample(sample, measurement)
                    scored["repeat"] = repeat + 1
                    rows.append(scored)
                    output.write(json.dumps(scored, ensure_ascii=False) + "\n")
                    output.flush()
                    LOGGER.info("decision sample=%s arm=%s repeat=%s ok=%s correct=%s elapsed_ms=%s", sample["id"], arm, repeat + 1, scored["ok"], scored["correct"], scored["client_ms"])
    (args.output / "summary.json").write_text(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


def write_report(root: Path) -> dict[str, Any]:
    """从原始验收和QA测量生成可分享报告；缺失、恢复或失败样本不能通过接入建议条件。"""
    rows = [json.loads(line) for line in (root / "heldout/samples.jsonl").read_text().splitlines()]
    metadata = json.loads((root / "heldout/inputs.json").read_text())
    summary = summarize(rows)
    qa_rows = [json.loads(path.read_text()) for path in sorted((root / "qa").glob("qa-[0-9]*.json"))]
    expected_pairs = {(sample["id"], repeat) for sample in metadata["fixture_cases"] for repeat in (1, 2, 3)}
    complete = len(metadata["fixture_cases"]) == 20 and metadata["repeats"] == 3
    for arm in ARMS:
        group = [row for row in rows if row["arm"] == arm]
        complete = complete and len(group) == 60 and {(row["sample_id"], row["repeat"]) for row in group} == expected_pairs
    # 正式比较只接受冻结后的共同题面；恢复流程不作为新的正常耗时样本。
    complete = complete and metadata["rubric"] == RUBRIC and metadata["contract"] == CONTRACT
    qa_complete = len(qa_rows) == 9 and len({row["slot"] for row in qa_rows}) == 9
    qa_complete = qa_complete and all(sum(row["arm"] == arm for row in qa_rows) == 3 for arm in ARMS)
    qa_complete = qa_complete and all(row["verified"] and not row.get("recovered") for row in qa_rows)
    jev = summary.get("jev", {})
    low = summary.get("codex-low", {})
    faster = bool(jev.get("median_client_ms") and low.get("median_client_ms")
                  and jev["median_client_ms"] <= low["median_client_ms"] / 2)
    recommend = bool(complete and qa_complete and jev.get("accuracy", 0) >= .95
                     and jev.get("unsafe_routes") == 0 and faster)
    verdict = {"heldout_complete": bool(complete), "qa_complete": bool(qa_complete),
               "jev_at_least_twice_as_fast_as_low": faster, "recommend_jev_integration": recommend}
    lines = ["# Jev 取消退票单对照实验", "", "## 决策结果", "",
             "以下是客户端观测耗时，包含网络和各自客户端成本，不是纯模型推理时间。Codex保留原provider，使用临时无工具CLI会话；模型名是请求配置，后端实际路由未由CLI响应独立证明。",
             "", "| 组别 | 成功/总数 | 完整答案正确率 | 不安全取消路由 | 未决比例 | 中位数 | P95 | CLI启动中位数 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        item = summary.get(arm)
        if not item:
            continue
        median = f"{item['median_client_ms'] / 1000:.3f}s" if item["median_client_ms"] is not None else "不可用"
        p95 = f"{item['p95_client_ms'] / 1000:.3f}s" if item["p95_client_ms"] is not None else "不可用"
        startup = f"{item['median_cli_startup_ms'] / 1000:.3f}s" if item["median_cli_startup_ms"] is not None else "不适用"
        lines.append(f"| {arm} | {item['successes']}/{item['count']} | {item['accuracy']:.1%} | {item['unsafe_routes']} | {item['unresolved_rate']:.1%} | {median} | {p95} | {startup} |")
    lines += ["", "完整答案要求意图、执行意向、目标及原因方式全部正确；失败保留在准确率分母，延迟分位数仅含成功调用。未决包含正确识别的缺失目标/多目标，不能单独视为错误率。CLI启动窗口为进程启动至turn.started；其余耗时仍不能等同服务端推理。",
              "", "验收只有20条独立中文措辞，三次重复不是60种独立场景；此结果是试点依据，不能证明所有中文业务请求的准确率。",
              "", "各协议上下文成本不同：Jev接收结构化业务题面，Codex CLI另带Agent系统上下文，因此这是一项接入路径对照，不能分离模型权重本身的性能。供应商返回的token总量如下：", ""]
    lines += ["脚本不重试失败请求；Codex内部网络行为沿用已配置provider及CLI默认，观测耗时包含这些成本。", ""]
    for arm, item in summary.items():
        lines.append(f"- {arm}：输入 {item['input_tokens']}，输出 {item['output_tokens']} tokens。")
    lines += ["", "## QA结果", "",
              "| 组别 | 回查通过 | 业务调用中位数 | 总流程中位数 | 总流程范围 |", "|---|---:|---:|---:|---:|"]
    for arm in ARMS:
        group = [row for row in qa_rows if row["arm"] == arm]
        valid = [row for row in group if row["verified"] and not row.get("recovered")]
        if valid:
            workflow = [row["workflow_ms"] / 1000 for row in valid]
            business = [row["business_ms"] / 1000 for row in valid]
            lines.append(f"| {arm} | {sum(row['verified'] for row in group)}/{len(group)} | {statistics.median(business):.3f}s | {statistics.median(workflow):.3f}s | {min(workflow):.3f}–{max(workflow):.3f}s |")
        else:
            lines.append(f"| {arm} | 0/{len(group)} | 不可用 | 不可用 | 不可用 |")
    inputs_path = root / "qa/qa-inputs.json"
    if inputs_path.exists():
        prepared = json.loads(inputs_path.read_text())
        lines += ["", f"动态数据准备耗时：{prepared['preparation_ms'] / 1000:.3f}s，独立于上述流程。服务启动不计入上述流程。每组仅三单，范围只是试点观测，不报告QA P95。"]
    lines += ["", "## 判断", "", "建议继续开展Jev固定流程接入。" if recommend else "当前结果不满足全部接入条件，保留现有业务入口。",
              "", f"验收集完整：{bool(complete)}；九次QA完整通过：{bool(qa_complete)}；Jev决策中位数至少比low快一倍：{faster}。",
              "", "原聊天162.4秒包含接口发现、源码确认及多轮Agent调度，与本实验固定契约流程不同；不能把两者差值全部归因于Jev，也不能据此声称Codex聊天入口已提速。",
              "", "## 错误样例", ""]
    # 只写合成样例ID及闭集答案；真实业务ID仍在本机既有执行记录/QA输入中。
    for row in rows:
        if not row["correct"]:
            lines.append(f"- {row['arm']} / {row['sample_id']} / 第{row['repeat']}次：预期 `{json.dumps(row['expected'], ensure_ascii=False)}`；实际 `{json.dumps(row.get('decision', row.get('error_type')), ensure_ascii=False)}`。")
    for row in qa_rows:
        if not row["verified"]:
            lines.append(f"- QA槽位{row['slot']} / {row['arm']}：`{row.get('error_code', row.get('error_type', 'readback_failed'))}`。")
    (root / "report.md").write_text("\n".join(lines) + "\n")
    (root / "comparison.json").write_text(json.dumps({"decisions": summary, "criteria": verdict}, ensure_ascii=False, indent=2))
    return verdict


def main() -> None:
    """解析只运行模型决策的CLI参数并绑定日志上下文；不会启动QA服务或修改订单。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("all", *ARMS), default="all")
    parser.add_argument("--report", action="store_true", help="从output下的heldout/qa测量生成报告，不调用模型或业务")
    parser.add_argument("--split", choices=("development", "heldout"), default="development")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/fixtures/jev-refund-cases.json")
    parser.add_argument("--key-file", type=Path, default=Path("/Users/user/data/api_key/jev_api_key.txt"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # 使用项目既有日志绑定/清理，模型输入及API密钥不出现在日志中。
    from opentest.application.log_context import bind_workflow_log_context, configure_logging
    configure_logging()
    with bind_workflow_log_context("ifightchainsaas.java.refund.core", "jev-refund-benchmark"):
        if args.report:
            write_report(args.output)
        else:
            run_samples(args)


if __name__ == "__main__":
    main()
