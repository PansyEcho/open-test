"""启动独立工作台验收共享MySQL页面时延；只同值保存配置，不扫描源码或调用业务接口。"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from time import perf_counter
from urllib.parse import quote
import uuid

import httpx
import yaml

from opentest.adapters.mysql_metadata import load_metadata_store


@dataclass
class Endpoint:
    """一次可核验的HTTP读取/同值保存，包含期望身份而不记录业务载荷。"""

    name: str
    path: str
    key: str = ""
    expected: object = None
    body: dict | None = None


def fixture_endpoints(metadata, system: dict) -> list[Endpoint]:
    """从共享库身份构造当前系统端点与完整性预期；不读取源码或更改版本。"""

    sid = system["system_id"]
    base = f"/systems/{quote(sid)}"
    rows = metadata.fetch_all("SELECT operation_id FROM ot_interface WHERE system_id=%s AND scan_id=%s "
                              "AND definition_json->>'$.operation.kind' IN ('FACADE','MQ') ORDER BY operation_id",
                              (sid, system["latest_scan_id"]))
    targets = [row["operation_id"] for row in rows]
    tasks = metadata.fetch_all("SELECT record_id FROM ot_workflow_record WHERE record_kind='task' AND system_id=%s ORDER BY created_at DESC", (sid,))
    generations = metadata.fetch_all("SELECT generation_id FROM ot_case_generation WHERE system_id=%s ORDER BY created_at DESC", (sid,))
    handoffs = metadata.fetch_all("SELECT record_id FROM ot_workflow_record WHERE record_kind='case_handoff' AND system_id=%s ORDER BY created_at DESC LIMIT 1", (sid,))
    capabilities = metadata.fetch_all("SELECT capability_id,version FROM ot_data_capability_version WHERE system_id=%s ORDER BY created_at DESC LIMIT 1", (sid,))
    executions = metadata.fetch_all("SELECT execution_id,execution_kind FROM ot_execution WHERE system_id=%s ORDER BY created_at DESC", (sid,))
    summary = metadata.fetch_one("SELECT summary_json FROM ot_scan WHERE scan_id=%s", (system["latest_scan_id"],))
    counts = json.loads(summary["summary_json"])["counts"]
    entry_count = sum(counts.get(kind, 0) for kind in ("facade", "mq_consumer"))
    endpoints = [Endpoint("systems", "/systems", "systems"),
        Endpoint("workbench", base + "/console-summary", "entry_count", entry_count),
        Endpoint("environments", base + "/environments", "environments"),
        Endpoint("settings", base + "/local-settings?environment=qa"),
        Endpoint("scans", base + "/scans", "scans"),
        Endpoint("catalog", base + "/scans/latest/catalog", "catalog", set(targets) | {"background:system"}),
        Endpoint("relations", base + "/relations"),
        Endpoint("context", base + "/knowledge/context", "context"),
        Endpoint("workflow", base + "/knowledge/workflow?view=summary", "workflow"),
        Endpoint("background", base + "/knowledge/targets/background%3Asystem?include_questions=false&include_context=false"),
        Endpoint("resources", base + "/resources", "resources"),
        Endpoint("validation", base + "/validation-capabilities", "capabilities"),
        Endpoint("tasks", f"/tasks?system_id={sid}&view=summary", "tasks", min(20, len(tasks))),
        Endpoint("tasks_page2", f"/tasks?system_id={sid}&view=summary&page=2", "tasks", min(20, max(0, len(tasks) - 20))),
        Endpoint("generations", base + "/case-generations?view=summary", "generations", min(20, len(generations))),
        Endpoint("data", base + "/data-capabilities?view=summary", "capabilities"),
        Endpoint("data_reports", base + "/data-executions?view=summary", "executions"),
        Endpoint("case_reports", base + "/case-executions?view=summary", "executions")]
    # 精确详情也参加验收；ID来自库内现有对象，不能把空列表当成详情成功。
    if targets:
        endpoints.extend([Endpoint("contract", base + "/operation-contracts/" + quote(targets[0], safe=""), "operation_contract"),
            Endpoint("target", base + "/knowledge/targets/" + quote(targets[0], safe="") + "?include_questions=false&include_context=false")])
    if tasks:
        endpoints.append(Endpoint("task_status", "/tasks/" + tasks[0]["record_id"] + "?view=summary", "task"))
    if handoffs:
        endpoints.append(Endpoint("handoff", "/case-handoffs/" + handoffs[0]["record_id"] + "/status", "handoff"))
    if generations:
        endpoints.append(Endpoint("generation_detail", base + "/case-generations/" + generations[0]["generation_id"], "generation"))
    if capabilities:
        item = capabilities[0]
        endpoints.append(Endpoint("data_detail", base + f"/data-capabilities/{quote(item['capability_id'])}/versions/{item['version']}?owner_system_id={sid}"))
    for kind in ("case", "data"):
        execution = next((item for item in executions if item["execution_kind"] == kind), None)
        if execution:
            endpoints.append(Endpoint(kind + "_report_detail", base + f"/{kind}-executions/" + execution["execution_id"]))
    return endpoints


class Workload:
    """保存测量值和进程句柄；每个工作台独立缓存、workspace身份及最多四条读连接。"""

    def __init__(self, arguments):
        """绑定命令参数并创建临时目录；启动失败也通过close释放进程。"""

        self.arguments = arguments
        self.root = Path(tempfile.mkdtemp(prefix="opentest-console-load-"))
        self.processes = []
        self.logs = []
        self.samples = []
        self.endpoints = []
        self.saves = []
        self.warm_seconds = 0.0
        self.metadata = load_metadata_store(arguments.knowledge_root)
        if self.metadata is None:
            raise ValueError("MySQL metadata configuration required")

    def prepare(self) -> None:
        """复制必要本机配置但不复制缓存，启动独立进程；不覆盖已有服务端口。"""

        source = self.arguments.knowledge_root.resolve()
        bindings = json.loads((source / ".opentest/source-bindings.json").read_text())
        systems = self.metadata.fetch_all("SELECT system_id,latest_scan_id FROM ot_system WHERE is_archived=0 ORDER BY system_id")
        # 仅验收本机已绑定且有扫描的真实系统；并行测试创建的临时系统不属于本轮负载。
        systems = [system for system in systems if system["system_id"] in bindings and system["latest_scan_id"]]
        if not systems:
            raise ValueError("no locally bound scanned systems to benchmark")
        self.endpoints = [fixture_endpoints(self.metadata, system) for system in systems]
        for index in range(self.arguments.workspaces):
            port = self.arguments.port + index
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
            workspace = self.root / str(index)
            knowledge = workspace / "knowledge"
            (workspace / ".opentest").mkdir(parents=True)
            (knowledge / ".opentest").mkdir(parents=True)
            configuration = dict(self.metadata.configuration, workspace_id="latency-" + uuid.uuid4().hex)
            configuration_path = workspace / ".opentest" / "metadata-mysql.yaml"
            configuration_path.write_text(yaml.safe_dump(configuration))
            configuration_path.chmod(0o600)
            for relative in (".opentest/settings.yaml",):
                if (source.parent / relative).exists():
                    shutil.copy2(source.parent / relative, workspace / relative)
            for relative in (".opentest/source-bindings.json", ".opentest/environments"):
                original, destination = source / relative, knowledge / relative
                if original.is_dir():
                    shutil.copytree(original, destination)
                elif original.exists():
                    shutil.copy2(original, destination)
            log = (self.root / f"service-{index}.log").open("w")
            self.logs.append(log)
            environment = dict(os.environ, OPENTEST_KNOWLEDGE_ROOT=str(knowledge))
            self.processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "opentest.api:app",
                "--host", "127.0.0.1", "--port", str(port)], env=environment, stdout=log, stderr=subprocess.STDOUT))

    async def request(self, client, endpoint: Endpoint, phase: str, workspace: int) -> dict:
        """计量完整HTTP响应并验证字段/身份，失败同样记录并导致最终验收失败。"""

        started = perf_counter()
        sample = {"workspace": workspace, "phase": phase, "endpoint": endpoint.name, "ok": False}
        try:
            response = await client.request("PUT" if endpoint.body is not None else "GET", "/api/v2" + endpoint.path, json=endpoint.body)
            sample.update(seconds=perf_counter() - started, status=response.status_code, bytes=len(response.content),
                          server_timing=response.headers.get("server-timing", ""))
            response.raise_for_status()
            payload = response.json()
            if endpoint.key:
                assert endpoint.key in payload, "required field missing: " + endpoint.key
                if isinstance(endpoint.expected, set):
                    assert {item["target_id"] for item in payload[endpoint.key]["targets"]} == endpoint.expected, "incomplete catalog"
                elif endpoint.expected is not None:
                    actual = payload[endpoint.key]
                    assert (len(actual) if isinstance(actual, list) else actual) == endpoint.expected, "incomplete result"
            sample["ok"] = True
            return payload
        except Exception as exc:
            sample.update(seconds=perf_counter() - started, error=type(exc).__name__ + ": " + str(exc)[:160])
            return {}
        finally:
            self.samples.append(sample)

    async def ready(self, client) -> None:
        """等待十进程导入与启动，启动等待不混入页面时延；超过两分钟明确失败。"""

        deadline = perf_counter() + 120
        while perf_counter() < deadline:
            try:
                response = await client.get("/api/v2/health", timeout=1)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
        raise RuntimeError("service did not become ready")

    async def cold(self, client, index: int) -> None:
        """每工作台完整走两系统的全部端点，首次读取前没有预热业务缓存。"""

        for endpoints in self.endpoints:
            for endpoint in endpoints:
                await self.request(client, endpoint, "cold", index)
        # 采用服务器给出的同值配置，每次保存仍经过真实事务和revision失效。
        payload = await client.get("/api/v2/systems")
        for system in payload.json()["systems"]:
            endpoints = next((group for group in self.endpoints if system["system_id"] in group[1].path), None)
            if endpoints is None:
                continue
            body = {name: system[name] for name in ("name", "source_path", "language", "description")}
            endpoint = Endpoint("save", "/systems/" + system["system_id"], "system", body=body)
            await self.request(client, endpoint, "cold", index)
            if index == 0:
                self.saves.append(endpoint)
            # 保存后第一次目录读也单独纳入冷读；不能仅用热命中掩盖重建耗时。
            await self.request(client, endpoints[5], "after_save", index)

    async def journey(self, client, index: int) -> None:
        """按真实页面请求依赖图测量首访和切换系统总时长；HTTP最多六连接模拟浏览器排队。"""

        for group in self.endpoints:
            endpoints = {endpoint.name: endpoint for endpoint in group}
            base = endpoints["catalog"].path.split("/scans/")[0]
            started = perf_counter()
            sample_start = len(self.samples)
            case_selections = []
            await self.request(client, endpoints["systems"], "journey_request", index)

            if self.arguments.journey == "knowledge":
                endpoints["context"] = Endpoint("context_summary", base + "/knowledge/context?view=summary", "context")

            async def read(name):
                """调用同一页面需要的端点，完整保留HTTP失败和必需字段校验。"""

                return await self.request(client, endpoints[name], "journey_request", index)

            async def knowledge():
                """历史确定所选扫描后读取目录与背景，保持浏览器实际串行依赖。"""

                history = await read("scans")
                scan_id = history["scans"][0]["scan_id"] if history.get("scans") else "latest"
                await self.request(client, Endpoint("selected_catalog", base + f"/scans/{scan_id}/catalog", "catalog"), "journey_request", index)
                # 背景页只消费context中的完整事实，重复读会经过浏览器合并/服务端版本缓存。
                await read("context")

            async def cases():
                """环境、入口/版本目录、精确DSL与对应环境报告按UI依赖依次读取。"""

                environments = await read("environments")
                generations, catalog = await asyncio.gather(read("generations"), read("catalog"))
                # 首次进入先展示入口与版本目录，不替用户选择业务接口。
                versions = generations.get("generations", [])
                if versions:
                    case_selections.append((base, versions[0], environments.get("environments", [])))

            name = self.arguments.journey
            if name == "knowledge":
                await asyncio.gather(knowledge(), read("context"), read("workflow"), read("tasks"))
            elif name == "cases":
                await asyncio.gather(cases(), read("tasks"))
            elif name == "system":
                await asyncio.gather(*(read(key) for key in ("settings", "environments", "relations", "resources", "validation", "scans")),
                    self.request(client, Endpoint("uat_settings", base + "/local-settings?environment=uat"), "journey_request", index),
                    self.request(client, Endpoint("archives", "/system-archives?view=summary"), "journey_request", index),
                    self.request(client, Endpoint("runtime", "/local-settings/runtime"), "journey_request", index))
            else:
                names = {"workbench": ("workbench", "tasks"), "data": ("environments", "data", "data_reports"), "tasks": ("tasks",)}[name]
                await asyncio.gather(*(read(key) for key in names))
            own_samples = [item for item in self.samples[sample_start:] if item["workspace"] == index]
            self.samples.append({"workspace": index, "phase": "journey", "endpoint": name,
                                 "seconds": perf_counter() - started, "ok": all(item["ok"] for item in own_samples)})
            for selection in case_selections:
                await self.case_selection(client, index, selection)

    async def case_selection(self, client, index: int, selection: tuple) -> None:
        """测量用户选择入口直到完整Case出现，再独立测量打开报告；不预热对应大对象。"""

        base, chosen, environments = selection
        started = perf_counter()
        sample_start = len(self.samples)
        query = base + "/case-generations?view=summary&operation_id=" + quote(chosen["operation_id"], safe="")
        versions, _ = await asyncio.gather(
            self.request(client, Endpoint("selected_versions", query, "generations"), "journey_request", index),
            self.request(client, Endpoint("selected_catalog", base + "/scans/latest/catalog", "catalog"), "journey_request", index))
        selected = versions.get("generations", [None])[0]
        if selected is None:
            raise AssertionError("selected operation lost its generation")
        generation_id = selected["generation_id"]
        environment_id = next((item["environment"] for item in environments if item["environment"] == "qa" and item.get("available") is not False), "")
        generation, reports = await asyncio.gather(
            self.request(client, Endpoint("selected_generation", base + "/case-generations/" + generation_id, "generation"), "journey_request", index),
            self.request(client, Endpoint("filtered_reports", base + "/case-executions?view=summary&generation_id=" + generation_id + "&environment_id=" + environment_id, "executions"), "journey_request", index))
        own_samples = [item for item in self.samples[sample_start:] if item["workspace"] == index]
        self.samples.append({"workspace": index, "phase": "journey_action", "endpoint": "select_case_entry",
                             "seconds": perf_counter() - started, "ok": bool(generation) and all(item["ok"] for item in own_samples)})
        if reports.get("executions"):
            await self.request(client, Endpoint("open_report", base + "/case-executions/" + reports["executions"][0]["execution_id"], "execution"), "journey_action", index)

    async def warm(self, client, index: int, deadline: float) -> None:
        """持续混合读取并定期同值保存，固定间隔模拟独立用户，不重试错误请求。"""

        endpoints = [endpoint for group in self.endpoints for endpoint in group]
        iteration = index
        while perf_counter() < deadline:
            endpoint = self.saves[index % len(self.saves)] if iteration % 53 == 0 else endpoints[iteration % len(endpoints)]
            await self.request(client, endpoint, "warm", index)
            iteration += 1
            await asyncio.sleep(0.4)

    async def health(self, clients, deadline: float) -> None:
        """在负载期间持续检查所有进程健康响应，按500毫秒独立验收。"""

        while perf_counter() < deadline:
            await asyncio.gather(*(self.request(client, Endpoint("health", "/health", "status"), "warm", index)
                                   for index, client in enumerate(clients)))
            await asyncio.sleep(1)

    async def run(self) -> None:
        """协调十工作台冷读与十分钟热读，独立HTTP连接模拟浏览器，结束时关闭客户端。"""

        clients = [httpx.AsyncClient(base_url=f"http://127.0.0.1:{self.arguments.port + index}", timeout=15,
                                    limits=httpx.Limits(max_connections=6, max_keepalive_connections=6))
                   for index in range(self.arguments.workspaces)]
        try:
            await asyncio.gather(*(self.ready(client) for client in clients))
            if self.arguments.journey:
                await asyncio.gather(*(self.journey(client, index) for index, client in enumerate(clients)))
                return
            await asyncio.gather(*(self.cold(client, index) for index, client in enumerate(clients)))
            # 冷读失败就保留证据结束，不能用随后大量热命中稀释未达标样本。
            if not self.report():
                return
            warm_started = perf_counter()
            deadline = warm_started + self.arguments.duration
            await asyncio.gather(*(self.warm(client, index, deadline) for index, client in enumerate(clients)), self.health(clients, deadline))
            self.warm_seconds = perf_counter() - warm_started
        finally:
            await asyncio.gather(*(client.aclose() for client in clients))

    def report(self) -> bool:
        """输出逐端点分阶段P95/最大值及全部原始样本；错误永不计为成功。"""

        groups = defaultdict(list)
        for sample in self.samples:
            groups[(sample["phase"], sample["endpoint"])].append(sample)
        summary = []
        for (phase, endpoint), samples in sorted(groups.items()):
            seconds = sorted(sample["seconds"] for sample in samples)
            p95 = seconds[max(0, int(len(seconds) * 0.95 + 0.9999) - 1)]
            errors = sum(not sample["ok"] for sample in samples)
            passed = not errors and p95 <= (0.5 if endpoint == "health" else 3) and max(seconds) <= (0.5 if endpoint == "health" else 5)
            summary.append(dict(phase=phase, endpoint=endpoint, count=len(samples), errors=errors,
                                p95=round(p95, 3), maximum=round(max(seconds), 3), passed=passed))
        passed = bool(summary) and all(item["passed"] for item in summary)
        self.arguments.output.write_text(json.dumps({"passed": passed, "duration": self.arguments.duration,
            "warm_seconds": round(self.warm_seconds, 3), "workspaces": self.arguments.workspaces,
            "workspace_root": str(self.root), "summary": summary, "samples": self.samples}, indent=2))
        print(json.dumps({"passed": passed, "samples": len(self.samples), "failed_groups": [item for item in summary if not item["passed"]], "output": str(self.arguments.output)}, ensure_ascii=False), flush=True)
        return passed

    def close(self) -> None:
        """只停止本脚本创建的服务进程，超时才强制终止，保留临时日志供定位。"""

        for process in self.processes:
            process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in self.logs:
            log.close()
        self.metadata.close()


def main() -> None:
    """执行可重现验收；非零退出代表时延或正确性未达标，finally释放所有服务。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=Path("open-test-knowledge"))
    parser.add_argument("--workspaces", type=int, default=10)
    parser.add_argument("--journey", choices=("knowledge", "cases", "system", "workbench", "data", "tasks"))
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--output", type=Path, default=Path(tempfile.gettempdir()) / "opentest-console-load.json")
    arguments = parser.parse_args()
    workload = Workload(arguments)
    try:
        workload.prepare()
        asyncio.run(workload.run())
        passed = workload.report()
    finally:
        workload.close()
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
