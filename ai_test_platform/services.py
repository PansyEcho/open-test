from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .execution import ExecutionService, read_json, write_json


SCRIPTGEN_PYTHONPATH = Path("/Users/user/data/code/other/CLI-Anything/scriptgen/agent-harness")


def utcish_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def short_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def slugify(value: str) -> str:
    allowed = [ch.lower() if ch.isalnum() else "-" for ch in value.strip()]
    slug = "".join(allowed).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or f"project-{uuid.uuid4().hex[:6]}"


def copytree_overlay(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


class Platform:
    def __init__(self, data_root: Path | str | None = None):
        self.data_root = Path(data_root or os.environ.get("AI_TEST_PLATFORM_HOME", "~/.ai-test-platform")).expanduser()
        self.projects_root = self.data_root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        for project_json in sorted(self.projects_root.glob("*/project.json")):
            projects.append(read_json(project_json, {}))
        return projects

    def create_project(self, config: dict[str, Any]) -> dict[str, Any]:
        source_path = Path(config["source_path"]).expanduser()
        if not source_path.exists() or not source_path.is_dir():
            raise ValueError(f"source_path does not exist or is not a directory: {source_path}")

        project_key = slugify(config.get("project_key") or config.get("name") or source_path.name)
        workspace = self.projects_root / project_key
        workspace.mkdir(parents=True, exist_ok=True)
        for rel in (
            "baselines",
            "drafts/knowledge",
            "drafts/cli",
            "drafts/cases",
            "versions/kb",
            "versions/cli",
            "versions/cases",
            "snapshots",
            "agent-runs",
            "runs",
        ):
            (workspace / rel).mkdir(parents=True, exist_ok=True)

        skill_info = self.validate_skill(config.get("skill_dir", ""))
        project = {
            "id": f"p_{project_key}",
            "name": config.get("name") or project_key,
            "project_key": project_key,
            "source_path": str(source_path),
            "workspace_path": str(workspace),
            "language": config.get("language", "java"),
            "agent_profile": config.get("agent_profile", "codex-local"),
            "skill_dir": skill_info.get("skill_dir", config.get("skill_dir", "")),
            "skill_hash": skill_info.get("skill_hash", ""),
            "env_name": config.get("env_name", "qa"),
            "facade_http_prefix": config.get("facade_http_prefix", ""),
            "headers": config.get("headers", {}),
            "job_rules": config.get("job_rules", []),
            "active_versions": {},
            "active_snapshot_id": None,
            "artifact_versions": [],
            "diff_proposals": [],
            "created_at": utcish_now(),
            "updated_at": utcish_now(),
        }
        project["code_baseline"] = self.scan_baseline(project)
        write_json(workspace / "project.json", project)
        write_json(workspace / "baselines" / f"code-baseline-{int(time.time())}.json", project["code_baseline"])
        return project

    def get_project(self, project_id: str) -> dict[str, Any]:
        for project in self.list_projects():
            if project.get("id") == project_id or project.get("project_key") == project_id:
                return project
        raise KeyError(f"project not found: {project_id}")

    def save_project(self, project: dict[str, Any]) -> None:
        project["updated_at"] = utcish_now()
        write_json(Path(project["workspace_path"]) / "project.json", project)

    def detect_agents(self) -> list[dict[str, Any]]:
        return [self._detect_agent("codex-local", "Codex CLI", "codex"), self._detect_agent("claude-code-local", "Claude Code", "claude")]

    def _detect_agent(self, profile_key: str, display_name: str, binary: str) -> dict[str, Any]:
        command_path = shutil.which(binary)
        version = ""
        status = "missing"
        if command_path:
            status = "available"
            try:
                completed = subprocess.run([command_path, "--version"], capture_output=True, text=True, timeout=5)
                version = (completed.stdout or completed.stderr).strip().splitlines()[0] if (completed.stdout or completed.stderr) else ""
            except Exception:
                version = "unknown"
        return {
            "profile_key": profile_key,
            "display_name": display_name,
            "command": binary,
            "command_path": command_path or "",
            "available": bool(command_path),
            "status": status,
            "version": version,
            "run_template": "codex exec --cwd <artifact-dir> <prompt>" if binary == "codex" else "claude -p <prompt> --output-format json --max-turns 8",
        }

    def validate_skill(self, skill_dir: str | Path | None) -> dict[str, Any]:
        if not skill_dir:
            return {"valid": False, "reason": "empty skill_dir", "skill_hash": ""}
        path = Path(skill_dir).expanduser()
        if not path.exists() or not path.is_dir():
            return {"valid": False, "reason": "skill_dir not found", "skill_dir": str(path), "skill_hash": ""}
        return {
            "valid": True,
            "skill_dir": str(path),
            "skill_hash": self.hash_directory(path),
            "summary": [str(item.relative_to(path)) for item in sorted(path.glob("*"))[:20]],
        }

    def hash_directory(self, path: Path) -> str:
        digest = hashlib.sha256()
        excluded = {".git", "node_modules", ".venv", "__pycache__", "target"}
        for item in sorted(path.rglob("*")):
            if any(part in excluded for part in item.parts):
                continue
            if item.is_dir():
                continue
            rel = item.relative_to(path).as_posix()
            digest.update(rel.encode("utf-8"))
            stat = item.stat()
            digest.update(str(stat.st_size).encode("ascii"))
            try:
                digest.update(item.read_bytes())
            except OSError:
                digest.update(str(stat.st_mtime_ns).encode("ascii"))
        return f"sha256:{digest.hexdigest()}"

    def scan_baseline(self, project: dict[str, Any]) -> dict[str, Any]:
        source = Path(project["source_path"])
        baseline = {"type": "filesystem", "source_path": str(source), "created_at": utcish_now()}
        try:
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
            branch = subprocess.run(["git", "-C", str(source), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=5)
            dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain"], capture_output=True, text=True, timeout=5)
            if commit.returncode == 0:
                baseline.update(
                    {
                        "type": "git",
                        "commit": commit.stdout.strip(),
                        "branch": branch.stdout.strip(),
                        "dirty": bool(dirty.stdout.strip()),
                    }
                )
        except Exception:
            pass
        try:
            baseline["file_count"] = sum(1 for path in source.rglob("*") if path.is_file())
        except OSError:
            baseline["file_count"] = 0
        return baseline

    def generate_knowledge(self, project_id: str, user_message: str = "") -> dict[str, Any]:
        project = self.get_project(project_id)
        draft_id = short_id("knowledge")
        draft_root = Path(project["workspace_path"]) / "drafts" / "knowledge" / draft_id
        knowledge_dir = draft_root / "knowledge"
        source_summary = self._scan_source_summary(Path(project["source_path"]))
        agent_run = self._record_agent_run(
            project,
            "knowledge",
            (
                "请基于只读业务代码目录、Skill 和用户补充生成知识库草稿。\n"
                f"source_path={project['source_path']}\n"
                f"skill_dir={project.get('skill_dir')}\n"
                f"user_message={user_message}\n"
            ),
        )
        write_json(
            knowledge_dir / "index.json",
            {
                "project_key": project["project_key"],
                "generated_at": utcish_now(),
                "source_summary": source_summary,
                "agent_profile": project.get("agent_profile"),
                "agent_run_id": agent_run["id"],
            },
        )
        (knowledge_dir / "glossary.md").parent.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "glossary.md").write_text(
            "# 业务词汇\n\n- 主流程 Case: 可重复执行的后端业务回归集合。\n- Labrador: QA 环境 HTTP 化调用入口。\n",
            encoding="utf-8",
        )
        (knowledge_dir / "facades" / "trade").mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "facades" / "trade" / "create-order.md").write_text(
            "# 交易相关接口 - 创建订单\n\n"
            "## 来源\n\n"
            f"- 代码目录: `{project['source_path']}`\n"
            "- 关键断言: `success=true`、`orderSerialId not_null`、`transactionId not_null`。\n",
            encoding="utf-8",
        )
        (knowledge_dir / "jobs").mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "jobs" / "job-overview.md").write_text(
            "# Job 触发规则\n\n"
            + "\n".join(f"- `{rule.get('package_name')}` -> `{rule.get('http_url_prefix')}`" for rule in project.get("job_rules", []))
            + "\n",
            encoding="utf-8",
        )
        (knowledge_dir / "testing").mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "testing" / "assertions.md").write_text(
            "# 测试断言\n\n- stdout 必须输出 JSON。\n- 执行阶段只使用已确认脚本，不调用 LLM。\n",
            encoding="utf-8",
        )
        result = {
            "success": True,
            "artifact_type": "knowledge",
            "summary": "生成知识库草稿，覆盖创建订单、Job 规则和执行断言。",
            "created_files": [str(path.relative_to(draft_root)) for path in knowledge_dir.rglob("*") if path.is_file()],
            "updated_files": [],
            "warnings": [],
            "requires_user_confirmation": True,
        }
        write_json(draft_root / "agent-result.json", result)
        proposal = self._add_proposal(project, "knowledge", draft_id, draft_root, result["summary"])
        return proposal

    def _scan_source_summary(self, source: Path) -> dict[str, Any]:
        facades: list[str] = []
        jobs: list[str] = []
        for path in source.rglob("*.java"):
            name = path.name
            if "Facade" in name and len(facades) < 30:
                facades.append(str(path.relative_to(source)))
            if "Job" in name and len(jobs) < 30:
                jobs.append(str(path.relative_to(source)))
            if len(facades) >= 30 and len(jobs) >= 30:
                break
        return {"facades": facades, "jobs": jobs, "facade_count_sampled": len(facades), "job_count_sampled": len(jobs)}

    def generate_cli(self, project_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        project = self.get_project(project_id)
        draft_id = short_id("cli")
        draft_root = Path(project["workspace_path"]) / "drafts" / "cli" / draft_id
        draft_root.mkdir(parents=True, exist_ok=True)
        scriptgen_result = self._run_scriptgen(project, draft_root, options)
        self._write_offline_tools(draft_root)
        platform_index = self._build_platform_tool_index(draft_root)
        write_json(draft_root / "_meta" / "platform-tool-index.json", {"tools": list(platform_index.values())})
        if not (draft_root / "_meta" / "tool-manifest.json").exists():
            write_json(
                draft_root / "_meta" / "tool-manifest.json",
                {
                    "success": True,
                    "output_dir": str(draft_root),
                    "generated_summary": {
                        "facade_tool_count": 3,
                        "job_tool_count": 1,
                        "invalid_tool_count": 0,
                        "readme_generated": True,
                        "tool_manifest_generated": True,
                    },
                    "generated_tools": [
                        {
                            "tool_id": item["tool_id"],
                            "tool_type": item["kind"],
                            "display_name": item["display_name"],
                            "source_id": item.get("source_id", item["tool_id"]),
                            "default_url": item.get("default_url", ""),
                            "script_rel_path": item["script_path"],
                            "http_method": "POST",
                            "request_mode": "raw_json_body",
                            "supports_template": True,
                            "status": item.get("status", "ready"),
                            "validation_errors": [],
                        }
                        for item in platform_index.values()
                    ],
                    "warnings": [],
                },
            )
        (draft_root / "README.md").write_text(
            "# CLI 工具草稿\n\n"
            "本目录包含 scriptgen 生成的工具和平台离线验收 shim。离线 shim 用于本地 MVP 回归，不调用 LLM。\n",
            encoding="utf-8",
        )
        proposal = self._add_proposal(
            project,
            "cli",
            draft_id,
            draft_root,
            f"生成 CLI 草稿：scriptgen_success={scriptgen_result['success']}，平台索引 {len(platform_index)} 个工具。",
        )
        proposal["scriptgen"] = scriptgen_result
        return proposal

    def _run_scriptgen(self, project: dict[str, Any], output_dir: Path, options: dict[str, Any]) -> dict[str, Any]:
        if not SCRIPTGEN_PYTHONPATH.exists():
            return {"success": False, "reason": "scriptgen path not found"}
        command = [
            sys.executable,
            "-m",
            "cli_anything.scriptgen",
            "build-tools",
            project["source_path"],
            "--env",
            project.get("env_name", "qa"),
            "--facade-http-prefix",
            project.get("facade_http_prefix", ""),
            "--output-dir",
            str(output_dir),
            "--types",
            options.get("types", "facade,job"),
            "--json",
        ]
        for rule in project.get("job_rules", []):
            command.extend(["--job-rule", json.dumps(rule, ensure_ascii=False)])
        env = {**os.environ, "PYTHONPATH": str(SCRIPTGEN_PYTHONPATH)}
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=int(options.get("timeout", 180)), env=env)
            (output_dir / "_meta").mkdir(parents=True, exist_ok=True)
            (output_dir / "_meta" / "scriptgen-command.json").write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / "_meta" / "scriptgen.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (output_dir / "_meta" / "scriptgen.stderr.log").write_text(completed.stderr, encoding="utf-8")
            return {"success": completed.returncode == 0, "return_code": completed.returncode, "stdout_tail": completed.stdout[-1000:], "stderr_tail": completed.stderr[-1000:]}
        except Exception as exc:
            return {"success": False, "reason": str(exc)}

    def _write_offline_tools(self, cli_dir: Path) -> None:
        platform = cli_dir / "platform"
        platform.mkdir(parents=True, exist_ok=True)
        scripts = {
            "create-order.sh": (
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' '{\"success\":true,\"orderSerialId\":\"HTKB20260525001\",\"transactionId\":\"TX20260525001\",\"orderStatus\":\"已创建\"}'\n"
            ),
            "pay-order.sh": (
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' '{\"success\":true,\"paymentSerialId\":\"PAY20260525001\",\"orderStatus\":\"支付中\"}'\n"
            ),
            "query-order-detail.sh": (
                "#!/usr/bin/env bash\n"
                "status='已创建'\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  case \"$1\" in\n"
                "    --scenario) shift; [ \"${1:-}\" = 'payment_pending' ] && status='支付中' ;;\n"
                "  esac\n"
                "  shift || true\n"
                "done\n"
                "printf '{\"success\":true,\"orderCount\":1,\"orderStatus\":\"%s\",\"firstOrderPsiCount\":2}\\n' \"$status\"\n"
            ),
            "trigger-job.sh": (
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' '{\"success\":true,\"jobTriggerId\":\"JOB20260525001\",\"triggerStatus\":\"accepted\"}'\n"
            ),
        }
        for name, content in scripts.items():
            path = platform / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o755)

    def _build_platform_tool_index(self, cli_dir: Path) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        manifest = read_json(cli_dir / "_meta" / "tool-manifest.json", {}) or {}
        for tool in manifest.get("generated_tools", []):
            normalized = self._normalize_tool_id(tool.get("tool_id", ""))
            if not normalized:
                continue
            index[normalized] = {
                "tool_id": normalized,
                "raw_tool_id": tool.get("tool_id"),
                "display_name": tool.get("display_name") or normalized,
                "kind": "job" if "job" in tool.get("tool_type", "") else "facade",
                "script_path": tool.get("script_rel_path"),
                "source_id": tool.get("source_id", ""),
                "default_url": tool.get("default_url", ""),
                "status": tool.get("status", "ready"),
            }
        index.update(
            {
                "facade.trade.create_order": {
                    "tool_id": "facade.trade.create_order",
                    "display_name": "交易相关接口 - 创建订单",
                    "kind": "facade",
                    "script_path": "platform/create-order.sh",
                    "source_id": "TradeFacade#createOrder",
                    "status": "ready",
                },
                "facade.payment.pay_order": {
                    "tool_id": "facade.payment.pay_order",
                    "display_name": "支付相关接口 - 支付订单",
                    "kind": "facade",
                    "script_path": "platform/pay-order.sh",
                    "source_id": "PaymentFacade#payOrder",
                    "status": "ready",
                },
                "facade.order.query_detail": {
                    "tool_id": "facade.order.query_detail",
                    "display_name": "订单查询接口 - 查询详情",
                    "kind": "facade",
                    "script_path": "platform/query-order-detail.sh",
                    "source_id": "OrderFacade#queryDetail",
                    "status": "ready",
                },
                "jobs.booking.trigger_compensation": {
                    "tool_id": "jobs.booking.trigger_compensation",
                    "display_name": "补偿 Job - 触发主流程补偿",
                    "kind": "job",
                    "script_path": "platform/trigger-job.sh",
                    "source_id": "BookingCompensationJob",
                    "status": "ready",
                },
            }
        )
        return index

    def _normalize_tool_id(self, raw: str) -> str:
        if not raw:
            return ""
        value = raw
        if value.startswith("facade_raw."):
            value = "facade." + value.removeprefix("facade_raw.")
        value = value.replace("-", "_")
        parts = value.split(".")
        if parts:
            last = parts[-1]
            snake = ""
            for ch in last:
                if ch.isupper() and snake:
                    snake += "_"
                snake += ch.lower()
            parts[-1] = snake
        return ".".join(parts)

    def generate_cases(self, project_id: str, scope: str = "main-flow") -> dict[str, Any]:
        project = self.get_project(project_id)
        self._require_active(project, "knowledge")
        self._require_active(project, "cli")
        draft_id = short_id("cases")
        draft_root = Path(project["workspace_path"]) / "drafts" / "cases" / draft_id
        cases_root = draft_root / "cases"
        cases = [
            {
                "case_id": "trade.create_order.main_success",
                "name": "创建订单主流程",
                "priority": "P0",
                "path": "trade/create-order/创建订单主流程",
                "steps": [
                    {
                        "step_index": 1,
                        "name": "创建订单",
                        "description": "创建一个普通订单并返回订单号。",
                        "execution_type": "script",
                        "execution_tool": "tool://facade.trade.create_order",
                        "input_params": {"train-no": "G303", "passenger": ["name=张三,type=adult"]},
                        "verification_type": "assertion",
                        "verification_assertion": {"success": True, "orderSerialId": "not_null", "transactionId": "not_null"},
                    },
                    {
                        "step_index": 2,
                        "name": "查询订单详情",
                        "execution_type": "script",
                        "execution_tool": "tool://facade.order.query_detail",
                        "input_params": {"order-serial-no": "${steps[0].output.orderSerialId}", "scenario": "created"},
                        "verification_type": "assertion",
                        "verification_assertion": {"success": True, "orderCount": 1, "orderStatus": "已创建"},
                    },
                ],
            },
            {
                "case_id": "trade.payment.main_success_should_fail_for_demo",
                "name": "支付成功主流程",
                "priority": "P0",
                "path": "trade/payment/支付成功主流程",
                "steps": [
                    {
                        "step_index": 1,
                        "name": "创建订单",
                        "execution_type": "script",
                        "execution_tool": "tool://facade.trade.create_order",
                        "input_params": {"train-no": "G303", "passenger": ["name=李四,type=adult"]},
                        "verification_type": "assertion",
                        "verification_assertion": {"success": True, "orderSerialId": "not_null"},
                    },
                    {
                        "step_index": 2,
                        "name": "支付订单",
                        "execution_type": "script",
                        "execution_tool": "tool://facade.payment.pay_order",
                        "input_params": {"order-serial-no": "${steps[0].output.orderSerialId}"},
                        "verification_type": "assertion",
                        "verification_assertion": {"success": True, "paymentSerialId": "not_null"},
                    },
                    {
                        "step_index": 3,
                        "name": "验证支付结果",
                        "execution_type": "script",
                        "execution_tool": "tool://facade.order.query_detail",
                        "input_params": {"order-serial-no": "${steps[0].output.orderSerialId}", "scenario": "payment_pending"},
                        "verification_type": "assertion",
                        "verification_assertion": {"success": True, "orderStatus": "已支付"},
                    },
                ],
            },
        ]
        suite_cases: list[dict[str, Any]] = []
        for item in cases:
            case_dir = cases_root / item["path"]
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "case.md").write_text(
                f"# {item['name']}\n\n优先级：{item['priority']}\n\n绑定已确认知识库与 CLI 工具，执行阶段不调用 LLM。\n",
                encoding="utf-8",
            )
            write_json(case_dir / "steps.json", item["steps"])
            suite_cases.append(
                {
                    "case_id": item["case_id"],
                    "name": item["name"],
                    "priority": item["priority"],
                    "case_doc": f"cases/{item['path']}/case.md",
                    "steps_file": f"cases/{item['path']}/steps.json",
                    "enabled": True,
                }
            )
        suite = {
            "suite_id": "main-flow-suite",
            "name": "主流程回归 Case 集",
            "scope": scope,
            "source": {
                "knowledge_version": project["active_versions"]["knowledge"]["version_key"],
                "cli_version": project["active_versions"]["cli"]["version_key"],
                "code_baseline": project.get("code_baseline"),
                "skill_hash": project.get("skill_hash"),
                "agent_profile": project.get("agent_profile"),
            },
            "cases": suite_cases,
        }
        write_json(draft_root / "suite.json", suite)
        return self._add_proposal(project, "case", draft_id, draft_root, "生成主流程 Case 草稿：2 个 case，包含一个可展示断言差异的失败样例。")

    def confirm_draft(self, project_id: str, draft_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        proposal = next((item for item in project.get("diff_proposals", []) if item["draft_id"] == draft_id), None)
        if not proposal:
            raise KeyError(f"draft not found: {draft_id}")
        artifact_type = proposal["artifact_type"]
        version_prefix = {"knowledge": "kb", "cli": "cli", "case": "case"}[artifact_type]
        version_no = 1 + max(
            [item.get("version_no", 0) for item in project.get("artifact_versions", []) if item.get("artifact_type") == artifact_type],
            default=0,
        )
        version_key = f"{version_prefix}-v{version_no}"
        version_dir_name = "cases" if artifact_type == "case" else ("kb" if artifact_type == "knowledge" else "cli")
        version_path = Path(project["workspace_path"]) / "versions" / version_dir_name / version_key
        version_path.mkdir(parents=True, exist_ok=True)
        if artifact_type == "cli" and project.get("active_versions", {}).get("cli"):
            old_path = Path(project["active_versions"]["cli"]["path"])
            if old_path.exists():
                copytree_overlay(old_path, version_path)
        copytree_overlay(Path(proposal["draft_path"]), version_path)
        if artifact_type == "cli":
            self._merge_retained_cli_index(project, version_path)
        record = {
            "id": f"{artifact_type}-{version_key}",
            "project_id": project["id"],
            "artifact_type": artifact_type,
            "version_no": version_no,
            "version_key": version_key,
            "path": str(version_path),
            "content_hash": self.hash_directory(version_path),
            "source_draft_id": draft_id,
            "code_baseline": project.get("code_baseline"),
            "metadata": {"confirmed_at": utcish_now()},
            "created_at": utcish_now(),
        }
        project.setdefault("artifact_versions", []).append(record)
        project.setdefault("active_versions", {})[artifact_type] = record
        proposal["status"] = "confirmed"
        proposal["confirmed_version"] = version_key
        self.save_project(project)
        return record

    def _merge_retained_cli_index(self, project: dict[str, Any], version_path: Path) -> None:
        old = project.get("active_versions", {}).get("cli")
        if not old:
            return
        old_index_path = Path(old["path"]) / "_meta" / "platform-tool-index.json"
        new_index_path = version_path / "_meta" / "platform-tool-index.json"
        old_tools = {item["tool_id"]: item for item in (read_json(old_index_path, {}) or {}).get("tools", [])}
        new_tools = {item["tool_id"]: item for item in (read_json(new_index_path, {}) or {}).get("tools", [])}
        for tool_id, item in old_tools.items():
            if tool_id not in new_tools:
                retained = dict(item)
                retained["status"] = "retained"
                new_tools[tool_id] = retained
        write_json(new_index_path, {"tools": list(new_tools.values())})

    def create_snapshot(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        kb = self._require_active(project, "knowledge")
        cli = self._require_active(project, "cli")
        case = self._require_active(project, "case")
        snapshot_no = 1 + len(list((Path(project["workspace_path"]) / "snapshots").glob("S*.json")))
        snapshot_id = f"S{time.strftime('%Y%m%d')}-{snapshot_no:03d}"
        snapshot = {
            "snapshot_id": snapshot_id,
            "project_id": project["id"],
            "knowledge_version_id": kb["id"],
            "cli_version_id": cli["id"],
            "case_version_id": case["id"],
            "knowledge_version": kb["version_key"],
            "cli_version": cli["version_key"],
            "case_version": case["version_key"],
            "knowledge_path": kb["path"],
            "cli_path": cli["path"],
            "case_path": case["path"],
            "code_baseline": project.get("code_baseline"),
            "agent_profile": project.get("agent_profile"),
            "skill_dir": project.get("skill_dir"),
            "skill_hash": project.get("skill_hash"),
            "created_at": utcish_now(),
            "pinned": False,
        }
        write_json(Path(project["workspace_path"]) / "snapshots" / f"{snapshot_id}.json", snapshot)
        project["active_snapshot_id"] = snapshot_id
        self.save_project(project)
        return snapshot

    def run_regression(self, project_id: str, snapshot_id: str | None = None) -> dict[str, Any]:
        project = self.get_project(project_id)
        snapshot_id = snapshot_id or project.get("active_snapshot_id")
        if not snapshot_id:
            raise ValueError("snapshot_id is required")
        snapshot = read_json(Path(project["workspace_path"]) / "snapshots" / f"{snapshot_id}.json", {})
        if not snapshot:
            raise KeyError(f"snapshot not found: {snapshot_id}")
        run_id = short_id("run")
        run_dir = Path(project["workspace_path"]) / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        case_dir = Path(snapshot["case_path"])
        cli_dir = Path(snapshot["cli_path"])
        suite = read_json(case_dir / "suite.json", {})
        tool_index = self._load_tool_index(cli_dir)
        executor = ExecutionService(self.data_root)
        case_results: list[dict[str, Any]] = []
        passed = 0
        failed = 0
        for case in suite.get("cases", []):
            if not case.get("enabled", True):
                continue
            case_run_dir = run_dir / "cases" / case["case_id"]
            result = executor.run_steps(
                steps_file=case_dir / case["steps_file"],
                tool_index=tool_index,
                cli_dir=cli_dir,
                skill_dir=Path(snapshot.get("skill_dir") or project.get("skill_dir") or cli_dir),
                run_dir=case_run_dir,
                binding={
                    "snapshot_id": snapshot_id,
                    "case_version": snapshot["case_version"],
                    "cli_version": snapshot["cli_version"],
                    "knowledge_version": snapshot["knowledge_version"],
                    "code_baseline": snapshot.get("code_baseline"),
                    "skill_hash": snapshot.get("skill_hash"),
                },
            )
            result.update({"case_id": case["case_id"], "case_name": case["name"], "priority": case.get("priority")})
            case_results.append(result)
            if result["status"] == "passed":
                passed += 1
            else:
                failed += 1
        run = {
            "id": run_id,
            "run_id": run_id,
            "project_id": project["id"],
            "snapshot_id": snapshot_id,
            "status": "failed" if failed else "passed",
            "total_count": passed + failed,
            "passed_count": passed,
            "failed_count": failed,
            "llm_invocations": 0,
            "binding": snapshot,
            "cases": case_results,
            "report_path": str(run_dir / "report.md"),
            "created_at": utcish_now(),
        }
        write_json(run_dir / "run.json", run)
        self._write_report(run_dir / "report.md", run)
        return run

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        return [read_json(path, {}) for path in sorted((Path(project["workspace_path"]) / "runs").glob("*/run.json"), reverse=True)]

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        run = read_json(Path(project["workspace_path"]) / "runs" / run_id / "run.json", {})
        if not run:
            raise KeyError(f"run not found: {run_id}")
        return run

    def _write_report(self, path: Path, run: dict[str, Any]) -> None:
        lines = [
            f"# 回归执行报告 {run['run_id']}",
            "",
            f"- 状态: {run['status']}",
            f"- Snapshot: {run['snapshot_id']}",
            f"- KB/CLI/Case: {run['binding']['knowledge_version']} / {run['binding']['cli_version']} / {run['binding']['case_version']}",
            f"- LLM 调用次数: {run['llm_invocations']}",
            f"- 汇总: passed={run['passed_count']} failed={run['failed_count']}",
            "",
        ]
        for case in run["cases"]:
            lines.append(f"## {case['case_name']} ({case['status']})")
            for step in case["steps"]:
                lines.append(f"- Step {step['step_index']} {step['step_name']}: {step['status']}")
                lines.append(f"  - command: `{step['command']}`")
                if not step["assertion_result"]["passed"]:
                    lines.append(f"  - diffs: `{json.dumps(step['assertion_result']['diffs'], ensure_ascii=False)}`")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _load_tool_index(self, cli_dir: Path) -> dict[str, dict[str, Any]]:
        payload = read_json(cli_dir / "_meta" / "platform-tool-index.json", {}) or {}
        return {item["tool_id"]: item for item in payload.get("tools", [])}

    def _require_active(self, project: dict[str, Any], artifact_type: str) -> dict[str, Any]:
        active = project.get("active_versions", {}).get(artifact_type)
        if not active:
            raise ValueError(f"active {artifact_type} version is required")
        return active

    def _add_proposal(self, project: dict[str, Any], artifact_type: str, draft_id: str, draft_root: Path, summary: str) -> dict[str, Any]:
        proposal = {
            "id": f"proposal-{draft_id}",
            "draft_id": draft_id,
            "project_id": project["id"],
            "artifact_type": artifact_type,
            "draft_path": str(draft_root),
            "base_version_id": project.get("active_versions", {}).get(artifact_type, {}).get("id"),
            "status": "draft",
            "summary": summary,
            "diff": self._diff_summary(Path(project["active_versions"].get(artifact_type, {}).get("path", "")), draft_root),
            "created_at": utcish_now(),
            "updated_at": utcish_now(),
        }
        project.setdefault("diff_proposals", []).append(proposal)
        self.save_project(project)
        return proposal

    def _diff_summary(self, base_path: Path, draft_path: Path) -> dict[str, Any]:
        base_files = set()
        if str(base_path) and base_path.exists():
            base_files = {path.relative_to(base_path).as_posix() for path in base_path.rglob("*") if path.is_file()}
        draft_files = {path.relative_to(draft_path).as_posix() for path in draft_path.rglob("*") if path.is_file()}
        return {
            "added": sorted(draft_files - base_files),
            "modified": sorted(draft_files & base_files),
            "retained_or_removed": sorted(base_files - draft_files),
        }

    def _record_agent_run(self, project: dict[str, Any], task_type: str, prompt: str) -> dict[str, Any]:
        run_id = short_id("agent")
        run_dir = Path(project["workspace_path"]) / "agent-runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        (run_dir / "stdout.log").write_text("MVP deterministic draft generated locally; set execute_agent=true to invoke local CLI.\n", encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        result = {
            "id": run_id,
            "project_id": project["id"],
            "profile_key": project.get("agent_profile", "codex-local"),
            "task_type": task_type,
            "status": "completed",
            "prompt_path": str(run_dir / "prompt.md"),
            "stdout_path": str(run_dir / "stdout.log"),
            "stderr_path": str(run_dir / "stderr.log"),
            "started_at": utcish_now(),
            "ended_at": utcish_now(),
            "created_at": utcish_now(),
        }
        write_json(run_dir / "result.json", result)
        return result
