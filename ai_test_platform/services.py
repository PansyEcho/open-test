from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .execution import ExecutionService, read_json, write_json


SCRIPTGEN_PYTHONPATH = Path("/Users/user/data/code/other/CLI-Anything/scriptgen/agent-harness")
DEFAULT_INTERACTIVE_KNOWLEDGE_SKILL_DIR = Path(__file__).parent / "default_skills" / "interactive-knowledge-builder"
KNOWLEDGE_DOCUMENT_START = "<<<KNOWLEDGE_DOCUMENT>>>"
KNOWLEDGE_DOCUMENT_END = "<<<END_KNOWLEDGE_DOCUMENT>>>"


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
        knowledge_skill_info = self.validate_skill(config.get("knowledge_skill_dir") or config.get("skill_dir", ""))
        project = {
            "id": f"p_{project_key}",
            "name": config.get("name") or project_key,
            "project_key": project_key,
            "source_path": str(source_path),
            "workspace_path": str(workspace),
            "language": config.get("language", "java"),
            "agent_profile": config.get("agent_profile", "codex-local"),
            "execute_agent": bool(config.get("execute_agent", True)),
            "agent_timeout_seconds": int(config.get("agent_timeout_seconds", 180)),
            "skill_dir": skill_info.get("skill_dir", config.get("skill_dir", "")),
            "skill_hash": skill_info.get("skill_hash", ""),
            "knowledge_skill_dir": knowledge_skill_info.get("skill_dir", config.get("knowledge_skill_dir") or config.get("skill_dir", "")),
            "knowledge_skill_hash": knowledge_skill_info.get("skill_hash", ""),
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

    def update_knowledge_skill(self, project_id: str, skill_dir: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        skill_info = self.validate_skill(skill_dir)
        if not skill_info.get("valid"):
            raise ValueError(skill_info.get("reason", "invalid skill directory"))
        project["knowledge_skill_dir"] = skill_info["skill_dir"]
        project["knowledge_skill_hash"] = skill_info["skill_hash"]
        self.save_project(project)
        return skill_info

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

    def get_knowledge_catalog(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        cli = project.get("active_versions", {}).get("cli")
        workspace = Path(project["workspace_path"])
        ready = bool(cli)
        tree: list[dict[str, Any]] = [
            self._knowledge_node_summary(
                project,
                {
                    "id": "project_background",
                    "title": "项目背景",
                    "category": "项目背景",
                    "type": "background",
                    "source": {"source_id": "project", "display_name": project["name"]},
                },
            )
        ]
        if ready:
            tool_index = self._load_tool_index(Path(cli["path"]))
            grouped: dict[str, list[dict[str, Any]]] = {}
            group_order: list[str] = []
            for tool in tool_index.values():
                node = self._tool_to_knowledge_node(tool)
                if node["category"] not in grouped:
                    group_order.append(node["category"])
                grouped.setdefault(node["category"], []).append(self._knowledge_node_summary(project, node))
            if "公共接口" not in grouped:
                group_order.append("公共接口")
            grouped.setdefault("公共接口", []).append(
                self._knowledge_node_summary(
                    project,
                    {
                        "id": "public.calculate_latest_ticket_time",
                        "title": "计算最晚出票时间",
                        "category": "公共接口",
                        "type": "derived",
                        "source": {"source_id": "common-logic#latestTicketTime", "display_name": "公共逻辑"},
                    },
                )
            )
            grouped.setdefault("公共接口", []).append(
                self._knowledge_node_summary(
                    project,
                    {
                        "id": "public.query_exchange_rate",
                        "title": "查询币种汇率",
                        "category": "公共接口",
                        "type": "derived",
                        "source": {"source_id": "common-logic#exchangeRate", "display_name": "公共逻辑"},
                    },
                )
            )
            for category in group_order:
                children = self._dedupe_nodes(grouped.get(category, []))
                if children:
                    tree.append({"id": f"group.{slugify(category)}", "title": category, "type": "group", "children": children})
            custom_nodes = read_json(workspace / "knowledge" / "custom-nodes.json", []) or []
            if custom_nodes:
                tree.append(
                    {
                        "id": "group.custom",
                        "title": "自定义知识",
                        "type": "group",
                        "children": [self._knowledge_node_summary(project, node) for node in custom_nodes],
                    }
                )
        return {
            "ready": ready,
            "empty_message": "" if ready else "请先扫描项目生成 CLI。",
            "knowledge_skill_dir": project.get("knowledge_skill_dir", ""),
            "knowledge_skill_hash": project.get("knowledge_skill_hash", ""),
            "tree": tree,
            "legend": {"generated": "已生成", "missing": "未生成"},
        }

    def get_knowledge_node(self, project_id: str, node_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        node = self._find_knowledge_node(project, node_id) or {
            "id": node_id,
            "title": node_id,
            "category": "自定义知识",
            "type": "custom",
            "source": {},
        }
        summary = self._knowledge_node_summary(project, node)
        content_path = self._knowledge_node_content_path(project, node_id)
        summary["content"] = content_path.read_text(encoding="utf-8") if content_path.exists() else ""
        summary["raw_markdown"] = summary["content"]
        summary["dependencies"] = self._knowledge_dependencies_for_node(node_id)
        if not self.get_project(project_id).get("active_versions", {}).get("cli") and node_id == "project_background":
            summary["empty_message"] = "请先扫描项目生成 CLI。"
        return summary

    def update_knowledge_node(self, project_id: str, node_id: str, content: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        return self._write_knowledge_node_content(project, node_id, content, edited_manually=True)

    def _write_knowledge_node_content(
        self,
        project: dict[str, Any],
        node_id: str,
        content: str,
        *,
        agent_run_id: str = "",
        edited_manually: bool = False,
    ) -> dict[str, Any]:
        node = self._find_knowledge_node(project, node_id) or self._upsert_custom_node(project, node_id, node_id)
        path = self._knowledge_node_content_path(project, node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self._sanitize_knowledge_markdown(content)
        path.write_text(content, encoding="utf-8")
        meta = self._knowledge_node_meta(project, node_id)
        meta.update(
            {
                "id": node_id,
                "title": node.get("title", node_id),
                "category": node.get("category", "自定义知识"),
                "source": node.get("source", {}),
                "dependencies": self._knowledge_dependencies_for_node(node_id),
                "agent_run_id": agent_run_id or meta.get("agent_run_id", ""),
                "edited_manually": edited_manually,
                "updated_at": utcish_now(),
            }
        )
        write_json(self._knowledge_node_meta_path(project, node_id), meta)
        self._ensure_active_knowledge_version(project)
        return self.get_knowledge_node(project["id"], node_id)

    def start_knowledge_chat(self, project_id: str, node_id: str = "project_background", regenerate: bool = False) -> dict[str, Any]:
        project = self.get_project(project_id)
        session_id = short_id("kchat")
        session = {
            "session_id": session_id,
            "project_id": project["id"],
            "node_id": node_id,
            "regenerate": regenerate,
            "status": "open",
            "messages": [
                {
                    "role": "assistant",
                    "content": self._knowledge_chat_opening(project, node_id, regenerate),
                    "created_at": utcish_now(),
                }
            ],
            "created_at": utcish_now(),
            "updated_at": utcish_now(),
        }
        write_json(self._knowledge_chat_path(project, session_id), session)
        return session

    def send_knowledge_chat(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self.get_project(project_id)
        session_id = payload.get("session_id") or short_id("kchat")
        session_path = self._knowledge_chat_path(project, session_id)
        session = read_json(session_path, None) or self.start_knowledge_chat(project_id, payload.get("node_id", "project_background"))
        node_id = payload.get("node_id") or session.get("node_id") or "project_background"
        message = payload.get("message", "")
        session.setdefault("messages", []).append({"role": "user", "content": message, "created_at": utcish_now()})
        if node_id == "__new__":
            title = self._custom_knowledge_title_from_message(message)
            node = self._upsert_custom_node(project, f"custom.{uuid.uuid4().hex[:8]}", title)
            node_id = node["id"]
            session["node_id"] = node_id
        else:
            node = self._find_knowledge_node(project, node_id) or {
                "id": node_id,
                "title": node_id,
                "category": "自定义知识",
                "type": "custom",
                "source": {},
            }
        agent_run = self._record_agent_run(
            project,
            "knowledge-node",
            self._build_knowledge_agent_prompt(project, node, message, session.get("messages", [])),
            force_agent=bool(payload.get("force_agent", False)),
        )
        if payload.get("force_agent") and agent_run.get("status") != "completed":
            reply = self._agent_failure_reply(agent_run)
            session["messages"].append({"role": "assistant", "content": reply, "created_at": utcish_now()})
            session["updated_at"] = utcish_now()
            write_json(session_path, session)
            return {"session": session, "node": self.get_knowledge_node(project_id, node_id), "reply": reply, "agent_run": agent_run}
        if payload.get("force_agent") and not agent_run.get("generated_content"):
            reply = "本地 Agent 已执行，但没有返回可写入的知识内容。请查看 agent-runs 下的 stdout/stderr 日志。"
            session["messages"].append({"role": "assistant", "content": reply, "created_at": utcish_now()})
            session["updated_at"] = utcish_now()
            write_json(session_path, session)
            return {"session": session, "node": self.get_knowledge_node(project_id, node_id), "reply": reply, "agent_run": agent_run}
        agent_text = agent_run.get("generated_content") or self._generate_interview_reply(project, node, message, session)
        reply, draft_content = self._extract_knowledge_document(agent_text)
        if draft_content:
            session["draft_node_id"] = node_id
            session["draft_content"] = draft_content
            session["draft_updated_at"] = utcish_now()
            session["last_agent_run_id"] = agent_run["id"]
        session["messages"].append({"role": "assistant", "content": reply, "created_at": utcish_now()})
        session["updated_at"] = utcish_now()
        write_json(session_path, session)
        return {
            "session": session,
            "node": self.get_knowledge_node(project_id, node_id),
            "reply": reply,
            "draft_content": session.get("draft_content", ""),
            "agent_run": agent_run,
        }

    def confirm_knowledge_chat(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self.get_project(project_id)
        session_id = payload.get("session_id", "")
        session_path = self._knowledge_chat_path(project, session_id)
        session = read_json(session_path, None)
        if not session:
            raise KeyError(f"knowledge chat session not found: {session_id}")
        node_id = payload.get("node_id") or session.get("draft_node_id") or session.get("node_id") or "project_background"
        content = payload.get("content") or session.get("draft_content", "")
        if not str(content).strip():
            raise ValueError("没有可确认写入的知识草稿")
        node = self._write_knowledge_node_content(
            project,
            node_id,
            str(content),
            agent_run_id=session.get("last_agent_run_id", ""),
            edited_manually=bool(payload.get("edited_manually", False)),
        )
        session["status"] = "confirmed"
        session["draft_node_id"] = node_id
        session["draft_content"] = node.get("content", self._sanitize_knowledge_markdown(str(content)))
        session["confirmed_at"] = utcish_now()
        session["updated_at"] = utcish_now()
        write_json(session_path, session)
        return {"session": session, "node": node}

    def list_knowledge_chats(self, project_id: str, node_id: str | None = None) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        chat_root = Path(project["workspace_path"]) / "knowledge" / "chats"
        sessions: list[dict[str, Any]] = []
        for chat_path in sorted(chat_root.glob("*.json")):
            session = read_json(chat_path, {}) or {}
            if node_id and session.get("node_id") != node_id and session.get("draft_node_id") != node_id:
                continue
            sessions.append(self._knowledge_chat_summary(session))
        return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)

    def get_knowledge_chat(self, project_id: str, session_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        session = read_json(self._knowledge_chat_path(project, session_id), None)
        if not session:
            raise KeyError(f"knowledge chat session not found: {session_id}")
        return session

    def _knowledge_chat_summary(self, session: dict[str, Any]) -> dict[str, Any]:
        messages = session.get("messages", []) or []
        last_message = messages[-1] if messages else {}
        return {
            "session_id": session.get("session_id", ""),
            "node_id": session.get("node_id", ""),
            "status": session.get("status", "open"),
            "message_count": len(messages),
            "preview": str(last_message.get("content", ""))[:160],
            "updated_at": session.get("updated_at", session.get("created_at", "")),
            "created_at": session.get("created_at", ""),
            "has_draft": bool(session.get("draft_content")),
        }

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

    def get_cli_catalog(self, project_id: str, draft_id: str | None = None) -> dict[str, Any]:
        project = self.get_project(project_id)
        cli_dir = self._resolve_cli_catalog_path(project, draft_id or "")
        if not cli_dir or not cli_dir.exists():
            return {"ready": False, "empty_message": "请先生成或确认 CLI。", "tree": [], "tool_count": 0}
        tool_index = self._load_tool_index(cli_dir)
        grouped: dict[str, list[dict[str, Any]]] = {}
        group_order: list[str] = []
        for tool in tool_index.values():
            node = self._tool_to_knowledge_node(tool)
            category = node.get("category") or "公共接口"
            if category not in grouped:
                group_order.append(category)
            grouped.setdefault(category, []).append(
                {
                    "id": node["id"],
                    "title": node["title"],
                    "type": node["type"],
                    "status": tool.get("status", "ready"),
                    "script_path": node.get("source", {}).get("script_path", ""),
                    "source_id": node.get("source", {}).get("source_id", ""),
                    "default_url": node.get("source", {}).get("default_url", ""),
                }
            )
        tree: list[dict[str, Any]] = []
        for category in group_order:
            children = self._dedupe_nodes(grouped.get(category, []))
            if children:
                tree.append({"id": f"cli-group.{slugify(category)}", "title": category, "type": "group", "children": children})
        return {
            "ready": True,
            "path": str(cli_dir),
            "tree": tree,
            "tool_count": len(tool_index),
            "source": "draft" if draft_id else "active",
        }

    def _resolve_cli_catalog_path(self, project: dict[str, Any], draft_id: str) -> Path | None:
        if draft_id:
            for proposal in project.get("diff_proposals", []):
                if proposal.get("artifact_type") == "cli" and proposal.get("draft_id") == draft_id:
                    return Path(proposal["draft_path"])
            return None
        active_cli = project.get("active_versions", {}).get("cli", {})
        path = active_cli.get("path")
        return Path(path) if path else None

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
        facade_metadata = self._load_facade_metadata(cli_dir)
        for tool in manifest.get("generated_tools", []):
            normalized = self._normalize_tool_id(tool.get("tool_id", ""))
            if not normalized:
                continue
            entry = {
                "tool_id": normalized,
                "raw_tool_id": tool.get("tool_id"),
                "display_name": tool.get("display_name") or normalized,
                "kind": "job" if "job" in tool.get("tool_type", "") else "facade",
                "script_path": tool.get("script_rel_path"),
                "source_id": tool.get("source_id", ""),
                "default_url": tool.get("default_url", ""),
                "status": tool.get("status", "ready"),
            }
            self._apply_facade_metadata(entry, facade_metadata)
            index[normalized] = entry
        fallback_tools = {
            "facade.trade.create_order": {
                "tool_id": "facade.trade.create_order",
                "display_name": "trade / createOrder",
                "kind": "facade",
                "script_path": "platform/create-order.sh",
                "source_id": "TradeFacade#createOrder",
                "status": "ready",
            },
            "facade.payment.pay_order": {
                "tool_id": "facade.payment.pay_order",
                "display_name": "payment / payOrder",
                "kind": "facade",
                "script_path": "platform/pay-order.sh",
                "source_id": "PaymentFacade#payOrder",
                "status": "ready",
            },
            "facade.order.query_detail": {
                "tool_id": "facade.order.query_detail",
                "display_name": "order / queryDetail",
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
        for tool_id, entry in fallback_tools.items():
            self._apply_facade_metadata(entry, facade_metadata)
            if tool_id in index:
                preserved = {key: value for key, value in index[tool_id].items() if key not in {"script_path", "display_name"}}
                merged = {**entry, **preserved, "script_path": entry["script_path"]}
                if entry.get("display_name"):
                    merged["display_name"] = entry["display_name"]
                self._apply_facade_metadata(merged, facade_metadata)
                index[tool_id] = merged
            else:
                index[tool_id] = entry
        return index

    def _load_facade_metadata(self, cli_dir: Path) -> dict[str, dict[str, Any]]:
        manifest = read_json(cli_dir / "_meta" / "scan-manifest.json", {}) or {}
        metadata: dict[str, dict[str, Any]] = {}
        for facade in manifest.get("facades", []):
            source_id = facade.get("facade_id", "")
            interface_name = facade.get("interface_name", "")
            method_name = facade.get("method_name", "")
            source_path = facade.get("source_path", "")
            comments = self._read_facade_comments(Path(source_path), interface_name, method_name) if source_path else {}
            method_title = comments.get("method_comment") or self._fallback_method_title(method_name)
            facade_title = self._facade_title(interface_name, facade.get("base_path", ""), comments.get("class_comment", ""))
            item = {
                "facade_id": source_id,
                "facade_name": interface_name,
                "facade_title": facade_title,
                "method_name": method_name,
                "method_title": method_title,
                "base_path": facade.get("base_path", ""),
                "method_path": facade.get("method_path", ""),
                "source_path": source_path,
                "request_type": facade.get("request_type", ""),
                "response_type": facade.get("response_type", ""),
            }
            for key in {source_id, f"{interface_name}#{method_name}", f"{source_id.rsplit('.', 1)[-1] if source_id else ''}"}:
                if key and "#" in key:
                    metadata[key] = item
        return metadata

    def _apply_facade_metadata(self, entry: dict[str, Any], metadata: dict[str, dict[str, Any]]) -> None:
        if entry.get("kind") == "job":
            return
        source_id = entry.get("source_id", "")
        item = metadata.get(source_id)
        if not item and "#" in source_id:
            item = metadata.get(source_id.rsplit(".", 1)[-1])
        if not item and "#" in source_id:
            facade_name, method_name = source_id.split("#", 1)
            item = {
                "facade_name": facade_name.rsplit(".", 1)[-1],
                "method_name": method_name,
                "method_title": self._fallback_method_title(method_name),
                "base_path": "",
                "method_path": method_name,
            }
            item["facade_title"] = self._facade_title(item["facade_name"], "", "")
        if not item:
            method_name = entry.get("display_name", "").split("/")[-1].strip() or entry.get("tool_id", "").split(".")[-1]
            item = {
                "facade_name": "",
                "facade_title": "公共接口",
                "method_name": method_name,
                "method_title": self._fallback_method_title(method_name),
            }
        title = item.get("method_name") or entry.get("display_name") or entry["tool_id"]
        method_title = item.get("method_title") or ""
        entry.update(item)
        entry["knowledge_title"] = f"{title}【{method_title}】" if method_title else title

    def _read_facade_comments(self, source_path: Path, interface_name: str, method_name: str) -> dict[str, str]:
        if not source_path.exists():
            return {}
        text = source_path.read_text(encoding="utf-8", errors="ignore")
        class_comment = ""
        if interface_name:
            class_match = re.search(rf"\b(?:interface|class)\s+{re.escape(interface_name)}\b", text)
            if class_match:
                class_comment = self._clean_javadoc(self._last_javadoc_before(text[: class_match.start()]))
        method_comment = ""
        if method_name:
            method_match = re.search(rf"\b{re.escape(method_name)}\s*\(", text)
            if method_match:
                method_comment = self._clean_javadoc(self._last_javadoc_before(text[: method_match.start()]))
        return {"class_comment": class_comment, "method_comment": method_comment}

    def _last_javadoc_before(self, text: str) -> str:
        matches = list(re.finditer(r"/\*\*(.*?)\*/", text, flags=re.S))
        return matches[-1].group(1) if matches else ""

    def _clean_javadoc(self, raw: str) -> str:
        lines: list[str] = []
        for line in raw.splitlines():
            cleaned = line.strip().lstrip("*").strip()
            if not cleaned or cleaned.startswith("@"):
                continue
            lines.append(cleaned)
        return " ".join(lines).strip()

    def _facade_title(self, interface_name: str, base_path: str, class_comment: str) -> str:
        if interface_name:
            return interface_name
        if base_path:
            return base_path
        normalized = (class_comment or "").strip()
        return normalized or "Facade"

    def _fallback_method_title(self, method_name: str) -> str:
        mapping = {
            "createOrder": "下单",
            "cancel": "取消订单",
            "cancelOrder": "取消订单",
            "inquireTicketInfo": "出票核验",
            "issueTicket": "出票",
            "occupyResult": "占座",
            "payOrder": "支付订单",
            "queryDetail": "查询详情",
            "queryOrder": "查询订单",
        }
        return mapping.get(method_name, "")

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
        facade_metadata = self._load_facade_metadata(cli_dir)
        index: dict[str, dict[str, Any]] = {}
        for item in payload.get("tools", []):
            tool_id = item.get("tool_id")
            if not tool_id:
                continue
            entry = dict(item)
            self._apply_facade_metadata(entry, facade_metadata)
            index[tool_id] = entry
        return index

    def _tool_to_knowledge_node(self, tool: dict[str, Any]) -> dict[str, Any]:
        tool_id = tool.get("tool_id", "")
        title_map = {
            "facade.trade.create_order": "createOrder【下单】",
            "facade.payment.pay_order": "payOrder【支付订单】",
            "facade.order.query_detail": "queryDetail【查询详情】",
            "jobs.booking.trigger_compensation": "自动补单任务",
        }
        if tool.get("kind") == "job" or tool_id.startswith("jobs."):
            category = "Job 补偿"
        else:
            category = tool.get("facade_title") or "公共接口"
        title = tool.get("knowledge_title") or title_map.get(tool_id) or self._humanize_tool_title(tool)
        return {
            "id": tool_id,
            "title": title,
            "category": category,
            "type": tool.get("kind", "facade"),
            "source": {
                "source_id": tool.get("source_id", ""),
                "display_name": tool.get("display_name", title),
                "default_url": tool.get("default_url", ""),
                "script_path": tool.get("script_path", ""),
                "facade_name": tool.get("facade_name", ""),
                "facade_title": tool.get("facade_title", ""),
                "method_name": tool.get("method_name", ""),
                "method_title": tool.get("method_title", ""),
                "source_path": tool.get("source_path", ""),
                "request_type": tool.get("request_type", ""),
                "response_type": tool.get("response_type", ""),
            },
        }

    def _humanize_tool_title(self, tool: dict[str, Any]) -> str:
        display = tool.get("display_name", "") or tool.get("tool_id", "")
        if "/" in display:
            display = display.split("/")[-1].strip()
        if "#" in display:
            display = display.split("#")[-1].strip()
        replacements = {
            "createOrder": "创建订单",
            "payOrder": "支付成功",
            "cancelOrder": "取消订单",
            "queryOrder": "查询订单",
            "queryDetail": "查询详情",
        }
        for raw, zh in replacements.items():
            if raw.lower() == display.replace("_", "").replace("-", "").lower():
                return zh
        spaced = ""
        for ch in display.replace("_", " ").replace("-", " "):
            if ch.isupper() and spaced and not spaced.endswith(" "):
                spaced += " "
            spaced += ch
        return spaced.strip() or tool.get("tool_id", "未命名知识")

    def _knowledge_node_summary(self, project: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        node_id = node["id"]
        meta = self._knowledge_node_meta(project, node_id)
        status = "generated" if self._knowledge_node_content_path(project, node_id).exists() else "missing"
        return {
            "id": node_id,
            "title": meta.get("title") or node.get("title", node_id),
            "category": node.get("category", meta.get("category", "")),
            "type": node.get("type", meta.get("type", "knowledge")),
            "status": status,
            "status_label": "已生成" if status == "generated" else "未生成",
            "source": node.get("source", meta.get("source", {})),
            "dependencies": meta.get("dependencies", self._knowledge_dependencies_for_node(node_id)),
            "updated_at": meta.get("updated_at", ""),
            "edited_manually": bool(meta.get("edited_manually", False)),
        }

    def _dedupe_nodes(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for node in sorted(nodes, key=lambda item: item.get("title", "")):
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            result.append(node)
        return result[:80]

    def _find_knowledge_node(self, project: dict[str, Any], node_id: str) -> dict[str, Any] | None:
        if node_id == "project_background":
            return {
                "id": "project_background",
                "title": "项目背景",
                "category": "项目背景",
                "type": "background",
                "source": {"source_id": "project", "display_name": project["name"]},
            }
        cli = project.get("active_versions", {}).get("cli")
        if cli:
            if node_id in {"public.calculate_latest_ticket_time", "public.query_exchange_rate"}:
                return {
                    "id": node_id,
                    "title": "计算最晚出票时间" if node_id.endswith("latest_ticket_time") else "查询币种汇率",
                    "category": "公共接口",
                    "type": "derived",
                    "source": {"source_id": "common-logic", "display_name": "公共逻辑"},
                }
            tool_index = self._load_tool_index(Path(cli["path"]))
            if node_id in tool_index:
                return self._tool_to_knowledge_node(tool_index[node_id])
        for node in read_json(Path(project["workspace_path"]) / "knowledge" / "custom-nodes.json", []) or []:
            if node.get("id") == node_id:
                return node
        return None

    def _upsert_custom_node(self, project: dict[str, Any], node_id: str, title: str) -> dict[str, Any]:
        path = Path(project["workspace_path"]) / "knowledge" / "custom-nodes.json"
        nodes = read_json(path, []) or []
        for node in nodes:
            if node["id"] == node_id:
                node["title"] = title
                write_json(path, nodes)
                return node
        node = {"id": node_id, "title": title, "category": "自定义知识", "type": "custom", "source": {"source_id": "user-chat"}}
        nodes.append(node)
        write_json(path, nodes)
        return node

    def _knowledge_node_content_path(self, project: dict[str, Any], node_id: str) -> Path:
        return Path(project["workspace_path"]) / "knowledge" / "nodes" / f"{node_id.replace('/', '_')}.md"

    def _knowledge_node_meta_path(self, project: dict[str, Any], node_id: str) -> Path:
        return Path(project["workspace_path"]) / "knowledge" / "nodes" / f"{node_id.replace('/', '_')}.json"

    def _knowledge_node_meta(self, project: dict[str, Any], node_id: str) -> dict[str, Any]:
        return read_json(self._knowledge_node_meta_path(project, node_id), {}) or {}

    def _knowledge_chat_path(self, project: dict[str, Any], session_id: str) -> Path:
        return Path(project["workspace_path"]) / "knowledge" / "chats" / f"{session_id}.json"

    def _knowledge_dependencies_for_node(self, node_id: str) -> list[dict[str, str]]:
        if node_id == "facade.trade.create_order":
            return [
                {"id": "project_background", "title": "项目背景"},
                {"id": "public.calculate_latest_ticket_time", "title": "计算最晚出票时间"},
            ]
        if node_id == "project_background":
            return []
        return [{"id": "project_background", "title": "项目背景"}]

    def _knowledge_chat_opening(self, project: dict[str, Any], node_id: str, regenerate: bool) -> str:
        if node_id == "__new__":
            return "请描述你想新增的知识点、相关包路径或接口名，我会根据项目目录和已生成 CLI 创建新的子知识库。"
        node = self._find_knowledge_node(project, node_id)
        title = node.get("title", node_id) if node else node_id
        action = "重新生成" if regenerate else "生成"
        return f"准备{action}《{title}》。请补充业务背景、关键规则、上下游依赖和测试关注点。"

    def _build_knowledge_agent_prompt(
        self,
        project: dict[str, Any],
        node: dict[str, Any],
        message: str,
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        history = history or []
        background = ""
        if node.get("id") != "project_background":
            background_path = self._knowledge_node_content_path(project, "project_background")
            if background_path.exists():
                background = background_path.read_text(encoding="utf-8")[:6000]
        current_path = self._knowledge_node_content_path(project, node.get("id", ""))
        current_content = current_path.read_text(encoding="utf-8")[:6000] if current_path.exists() else ""
        dependencies = self._knowledge_dependencies_for_node(node.get("id", ""))
        history_lines = "\n".join(f"- {item.get('role')}: {item.get('content')}" for item in history[-12:])
        turn_guard = self._knowledge_turn_guard(message)
        configured_skill = self._read_configured_skill(project, max_chars=3500 if self._is_sparse_knowledge_request(message) else 12000)
        return (
            "你是本地 Agent，正在通过多轮聊天帮助用户构建后端自动化测试知识库。\n"
            "不要把本轮对话当成一次性生成任务；除非信息足够或用户明确要求最终文档，否则请继续追问。\n"
            "本系统是聊天窗口，不是后台批处理任务；单轮回复应优先保持可交互、可继续追问。\n"
            "当最终文档可以写入知识库时，必须使用 Active Skill 中定义的 KNOWLEDGE_DOCUMENT 标记协议。\n\n"
            f"## This Turn Guard\n{turn_guard}\n\n"
            f"## Active Skill\n{self._read_interactive_knowledge_skill()}\n\n"
            f"## Configured Skill\npath={project.get('knowledge_skill_dir') or project.get('skill_dir')}\n{configured_skill}\n\n"
            f"## Node Mode\n{self._knowledge_node_mode_label(node)}\n\n"
            "## Project Context\n"
            f"- source_path: {project['source_path']}\n"
            f"- workspace_path: {project['workspace_path']}\n"
            f"- active_cli: {json.dumps(project.get('active_versions', {}).get('cli', {}), ensure_ascii=False)}\n\n"
            f"## Current Node\n{json.dumps(node, ensure_ascii=False, indent=2)}\n\n"
            f"## Existing Project Background\n{background or '暂无项目背景，请优先通过提问补齐。'}\n\n"
            f"## Current Node Existing Content\n{current_content or '暂无已写入内容。'}\n\n"
            f"## Dependency Nodes\n{json.dumps(dependencies, ensure_ascii=False, indent=2)}\n\n"
            f"## Conversation So Far\n{history_lines or '暂无历史对话。'}\n\n"
            f"## Current User Message\n{message}\n"
        )

    def _read_interactive_knowledge_skill(self) -> str:
        path = DEFAULT_INTERACTIVE_KNOWLEDGE_SKILL_DIR / "SKILL.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _knowledge_turn_guard(self, message: str) -> str:
        if self._is_sparse_knowledge_request(message):
            return (
                "- 当前用户输入只是打招呼、开场或泛泛要求生成，业务信息不足。\n"
                "- 本轮不要运行命令、不要扫描代码、不要展开长文档，也不要直接输出 KNOWLEDGE_DOCUMENT。\n"
                "- 请用 3 到 7 个贴合当前节点的问题继续采访用户；回复控制在 900 个中文字符以内。\n"
                "- 可以引用 Current Node、CLI 元数据和已有知识，但只能作为追问依据。"
            )
        return (
            "- 当前用户已经提供了一些业务信息，可以结合已有项目背景、CLI 元数据和必要代码线索继续追问或整理草稿。\n"
            "- 除非用户明确要求最终文档或信息已足够，否则不要输出 KNOWLEDGE_DOCUMENT。\n"
            "- 若需要扫描代码，请先说明你要核对的点，并保持回复适合继续多轮对话。"
        )

    def _is_sparse_knowledge_request(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return True
        if normalized in {"你好", "您好", "hi", "hello", "开始", "继续"}:
            return True
        final_markers = {"最终文档", "输出文档", "生成文档", "确认写入"}
        if any(marker in message for marker in final_markers):
            return False
        business_markers = {"本项目", "本系统", "业务", "规则", "流程", "状态", "上下游", "调用方", "负责", "接口"}
        if any(marker in message for marker in business_markers) and len(message.strip()) >= 24:
            return False
        generic_generation = {"生成", "补全", "整理"}
        return len(message.strip()) < 60 or any(marker in message for marker in generic_generation)

    def _read_configured_skill(self, project: dict[str, Any], max_chars: int = 12000) -> str:
        configured = Path(project.get("knowledge_skill_dir") or project.get("skill_dir") or "").expanduser()
        skill_file = configured / "SKILL.md"
        if not skill_file.exists():
            return "未配置额外 Skill；使用平台内置交互式知识库构建 Skill。"
        try:
            return skill_file.read_text(encoding="utf-8")[:max_chars]
        except OSError as exc:
            return f"读取配置 Skill 失败：{exc}"

    def _knowledge_node_mode_label(self, node: dict[str, Any]) -> str:
        node_id = node.get("id", "")
        if node_id == "project_background":
            return "项目背景知识"
        if node.get("type") == "job" or node_id.startswith("jobs."):
            return "Job 知识"
        if node.get("type") == "custom" or node_id.startswith("custom.") or node_id == "__new__":
            return "自定义知识"
        if node.get("type") == "derived" or node_id.startswith("public."):
            return "公共知识"
        return "Facade 接口知识"

    def _generate_interview_reply(self, project: dict[str, Any], node: dict[str, Any], message: str, session: dict[str, Any]) -> str:
        title = node.get("title", node.get("id", "知识节点"))
        node_id = node.get("id", "")
        if "最终文档" in message or "输出文档" in message or "生成文档" in message:
            if node_id == "project_background":
                doc = (
                    "# 项目背景\n\n"
                    f"{message.replace('输出最终文档：', '').strip()}\n\n"
                    "## 核心流程\n\n- 下单\n- 支付\n- 占座/出票\n- 取消与补偿\n\n"
                    "## 待用户补充\n\n- 联程订单、港币支付订单、供应商补偿等概念仍需继续确认。\n"
                )
            else:
                doc = self._generate_knowledge_content(project, node, message)
            return f"我先整理一版可确认的知识库文档：\n{KNOWLEDGE_DOCUMENT_START}\n{doc}\n{KNOWLEDGE_DOCUMENT_END}"
        if message.strip() in {"你好", "您好", "hi", "hello"}:
            if node_id == "project_background":
                return "你好，请先给定项目的基本项目背景：这个系统服务哪些调用方、核心业务流程是什么、哪些概念最重要？"
            return f"你好，我正在补全《{title}》。请先补充这个知识点的业务背景、关键规则、上下游依赖和你最关心的回归场景。"
        if node_id == "project_background":
            return (
                "我理解了。为了生成项目背景文档，我还需要继续确认几个概念：\n"
                "1. 联程订单在本系统里如何定义？\n"
                "2. 港币支付订单和普通订单的差异是什么？\n"
                "3. 下单、占座、出票、取消分别由哪些核心接口或 Job 承接？\n"
                "4. 哪些失败场景必须进入主流程回归？"
            )
        return (
            f"我会基于《{title}》继续采访。请补充：\n"
            "1. 这个入口的成功标准是什么？\n"
            "2. 主要入参校验有哪些？\n"
            "3. 下游依赖、状态流转和失败补偿分别是什么？\n"
            "4. 哪些字段可以作为 CLI 回归断言？"
        )

    def _extract_knowledge_document(self, text: str) -> tuple[str, str]:
        text = self._sanitize_knowledge_markdown(text)
        if KNOWLEDGE_DOCUMENT_START not in text:
            return text.strip(), ""
        before, rest = text.split(KNOWLEDGE_DOCUMENT_START, 1)
        if KNOWLEDGE_DOCUMENT_END in rest:
            document, after = rest.split(KNOWLEDGE_DOCUMENT_END, 1)
            document = self._sanitize_knowledge_markdown(document).strip()
            before_text = before.strip() or "已生成知识库草稿。"
            after_text = after.strip()
            reply_lines = [before_text, "已生成右侧草稿，请对照原先快照后确认写入。"]
            if after_text:
                reply_lines.append(after_text)
            return "\n".join(reply_lines), document
        document = self._sanitize_knowledge_markdown(rest).strip()
        return "已生成右侧草稿，请对照原先快照后确认写入。", document

    def _sanitize_knowledge_markdown(self, text: str) -> str:
        cleaned = re.sub(r"<!--\s*kb:[\s\S]*?-->\s*", "", str(text or ""), flags=re.I)
        cleaned = re.sub(r"([^#\n])(\#{1,6}\s)", r"\1\n\n\2", cleaned)
        return cleaned.strip()

    def _generate_knowledge_content(self, project: dict[str, Any], node: dict[str, Any], message: str) -> str:
        title = node.get("title", node["id"])
        source = node.get("source", {})
        dependencies = self._knowledge_dependencies_for_node(node["id"])
        dep_text = "、".join(f"[[{item['title']}]]" for item in dependencies) or "无"
        if node["id"] == "project_background":
            body = (
                f"# {title}\n\n"
                f"订单系统的核心目标是围绕下单、支付、取消和 Job 补偿形成可回归的后端主流程。\n\n"
                "## 业务边界\n\n"
                "- 业务代码目录作为只读输入。\n"
                "- 外部入口以已确认 CLI 工具清单为准。\n"
                "- 回归执行只调用脚本和 stdout JSON 断言，不调用 LLM。\n"
            )
        else:
            body = (
                f"# {title}\n\n"
                "## 1. 接口目标\n\n"
                f"{title} 知识由已确认 CLI 入口生成，来源 `{source.get('source_id', 'unknown')}`。\n\n"
                "## 2. 依赖知识\n\n"
                f"依赖：{dep_text}。\n\n"
                "## 3. 核心流程\n\n"
                "1. 根据入参完成业务校验。\n"
                "2. 调用下游服务或公共逻辑生成结果。\n"
                "3. 输出稳定 JSON 字段供 Case 断言。\n\n"
                "## 4. 测试关注点\n\n"
                "- 参数完整性、边界值和业务状态流转。\n"
                "- 下游异常时的回滚、补偿和错误码映射。\n"
            )
        return body + f"\n## 用户补充\n\n{message or '暂无'}\n"

    def _custom_knowledge_title_from_message(self, message: str) -> str:
        import re

        match = re.search(r"关于(.+?)的知识", message)
        if match:
            return match.group(1).strip(" 。.")
        for token in ("新增", "创建", "生成"):
            message = message.replace(token, "")
        return message.strip(" 。.")[:24] or "新的知识"

    def _ensure_active_knowledge_version(self, project: dict[str, Any]) -> None:
        workspace = Path(project["workspace_path"])
        knowledge_root = workspace / "knowledge"
        version_path = workspace / "versions" / "kb" / "kb-v1"
        version_path.mkdir(parents=True, exist_ok=True)
        if knowledge_root.exists():
            copytree_overlay(knowledge_root, version_path)
        record = project.setdefault("active_versions", {}).get("knowledge")
        if not record:
            record = {
                "id": "knowledge-kb-v1",
                "project_id": project["id"],
                "artifact_type": "knowledge",
                "version_no": 1,
                "version_key": "kb-v1",
                "path": str(version_path),
                "content_hash": self.hash_directory(version_path),
                "source_draft_id": "knowledge-chat",
                "code_baseline": project.get("code_baseline"),
                "metadata": {"confirmed_at": utcish_now(), "mode": "chat"},
                "created_at": utcish_now(),
            }
            project.setdefault("artifact_versions", []).append(record)
            project["active_versions"]["knowledge"] = record
        else:
            record["path"] = str(version_path)
            record["content_hash"] = self.hash_directory(version_path)
            record.setdefault("metadata", {})["updated_at"] = utcish_now()
        self.save_project(project)

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

    def _record_agent_run(self, project: dict[str, Any], task_type: str, prompt: str, force_agent: bool = False) -> dict[str, Any]:
        run_id = short_id("agent")
        run_dir = Path(project["workspace_path"]) / "agent-runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        stdout = "MVP deterministic draft generated locally; set execute_agent=true to invoke local CLI.\n"
        stderr = ""
        status = "completed"
        generated_content = ""
        command: list[str] = []
        if force_agent or project.get("execute_agent"):
            profile = project.get("agent_profile", "codex-local")
            binary = "claude" if profile == "claude-code-local" else "codex"
            command_path = shutil.which(binary)
            if command_path:
                command, stdin_text = self._agent_invocation(project, binary, command_path, run_dir, prompt)
                try:
                    completed = subprocess.run(
                        command,
                        cwd=str(run_dir),
                        input=stdin_text,
                        capture_output=True,
                        text=True,
                        timeout=int(project.get("agent_timeout_seconds", 180)),
                        env=self._agent_env(binary),
                    )
                    stdout = completed.stdout
                    stderr = completed.stderr
                    status = "completed" if completed.returncode == 0 else "failed"
                    if completed.returncode == 0 and completed.stdout.strip():
                        generated_content = self._extract_agent_text(binary, completed.stdout)
                except Exception as exc:
                    stderr = str(exc)
                    status = "failed"
            else:
                stderr = f"Agent command not found: {binary}"
                status = "failed"
        (run_dir / "stdout.log").write_text(stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        result = {
            "id": run_id,
            "project_id": project["id"],
            "profile_key": project.get("agent_profile", "codex-local"),
            "task_type": task_type,
            "status": status,
            "command": command,
            "generated_content": generated_content,
            "prompt_path": str(run_dir / "prompt.md"),
            "stdout_path": str(run_dir / "stdout.log"),
            "stderr_path": str(run_dir / "stderr.log"),
            "started_at": utcish_now(),
            "ended_at": utcish_now(),
            "created_at": utcish_now(),
        }
        write_json(run_dir / "result.json", result)
        return result

    def _agent_invocation(
        self,
        project: dict[str, Any],
        binary: str,
        command_path: str,
        run_dir: Path,
        prompt: str,
    ) -> tuple[list[str], str]:
        add_dirs = self._agent_allowed_dirs(project)
        if binary == "claude":
            command = [command_path, "-p", "--input-format", "text", "--output-format", "text", "--permission-mode", "bypassPermissions"]
            for directory in add_dirs:
                command.extend(["--add-dir", directory])
            return command, prompt
        command = [
            command_path,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-C",
            str(run_dir),
        ]
        for directory in add_dirs:
            command.extend(["--add-dir", directory])
        return command, prompt

    def _agent_allowed_dirs(self, project: dict[str, Any]) -> list[str]:
        candidates = [
            project.get("source_path", ""),
            project.get("workspace_path", ""),
            project.get("knowledge_skill_dir", ""),
            project.get("skill_dir", ""),
        ]
        result: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate:
                continue
            path = str(Path(candidate).expanduser())
            if path in seen or not Path(path).exists():
                continue
            seen.add(path)
            result.append(path)
        return result

    def _agent_env(self, binary: str) -> dict[str, str]:
        env = dict(os.environ)
        if binary == "codex" and not env.get("OPENAI_BASE_URL"):
            for key in list(env):
                if key.upper() in {"OPENAI_API_KEY", "CODEX_API_KEY"}:
                    env.pop(key, None)
        if binary == "claude" and not env.get("ANTHROPIC_BASE_URL"):
            for key in list(env):
                if key.upper() == "ANTHROPIC_API_KEY":
                    env.pop(key, None)
        return env

    def _extract_agent_text(self, binary: str, stdout: str) -> str:
        if binary == "codex":
            chunks: list[str] = []
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "item.completed" and isinstance(event.get("item"), dict):
                    item = event["item"]
                    if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                        chunks.append(item["text"])
                elif event.get("type") in {"agent_message", "text_delta"} and isinstance(event.get("text") or event.get("delta"), str):
                    chunks.append(event.get("text") or event.get("delta"))
            return "\n".join(chunk for chunk in chunks if chunk).strip() or stdout.strip()
        return stdout.strip()

    def _agent_failure_reply(self, agent_run: dict[str, Any]) -> str:
        stderr = ""
        stdout = ""
        stderr_path = Path(agent_run["stderr_path"]) if agent_run.get("stderr_path") else None
        stdout_path = Path(agent_run["stdout_path"]) if agent_run.get("stdout_path") else None
        if stderr_path and stderr_path.is_file():
            stderr = stderr_path.read_text(encoding="utf-8", errors="ignore").strip()
        if stdout_path and stdout_path.is_file():
            stdout = stdout_path.read_text(encoding="utf-8", errors="ignore").strip()
        detail = (stderr or stdout or "未知错误")[-800:]
        return f"本地 Agent 调用失败，未写入知识库。请检查 Codex/Claude CLI 登录状态和权限。错误摘要：{detail}"
