from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class JsonParseError(ValueError):
    """Raised when a step stdout cannot be parsed as JSON."""


class _Missing:
    pass


MISSING = _Missing()
_REF_RE = re.compile(r"\$\{steps\[(\d+)]\.output\.([^}]+)}")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_by_path(data: Any, dotted_path: str) -> Any:
    current = data
    for segment in dotted_path.split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)])?", segment)
        if not match:
            return MISSING
        key, index = match.group(1), match.group(2)
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return MISSING
        if index is not None:
            if not isinstance(current, list):
                return MISSING
            idx = int(index)
            if idx >= len(current):
                return MISSING
            current = current[idx]
    return current


def resolve_value(value: Any, step_outputs: list[dict[str, Any]]) -> Any:
    if isinstance(value, dict):
        return {key: resolve_value(item, step_outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, step_outputs) for item in value]
    if not isinstance(value, str):
        return value

    def lookup(match: re.Match[str]) -> Any:
        step_index = int(match.group(1))
        path = match.group(2)
        if step_index >= len(step_outputs):
            return ""
        found = get_by_path(step_outputs[step_index], path)
        if found is MISSING:
            return ""
        return found

    full_match = _REF_RE.fullmatch(value)
    if full_match:
        return lookup(full_match)

    return _REF_RE.sub(lambda match: str(lookup(match)), value)


def parse_stdout_json(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        raise JsonParseError("stdout is empty; expected JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    last_value: Any = MISSING
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        last_value = value
    if last_value is MISSING:
        raise JsonParseError("stdout does not contain a JSON object or array")
    return last_value


def _normalize_expected(expected: Any) -> tuple[str, Any]:
    if isinstance(expected, dict):
        return str(expected.get("op", "eq")), expected.get("value")
    if isinstance(expected, str):
        for prefix, op in (
            ("gt:", "gt"),
            ("gte:", "gte"),
            ("lt:", "lt"),
            ("lte:", "lte"),
            ("contains:", "contains"),
            ("pattern:", "regex"),
        ):
            if expected.startswith(prefix):
                return op, expected[len(prefix) :]
        if expected in {"not_null", "null"}:
            return expected, None
    return "eq", expected


def _coerce_number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


class AssertionEngine:
    def assert_json(self, actual_json: Any, expected_assertions: dict[str, Any]) -> dict[str, Any]:
        diffs: list[dict[str, Any]] = []
        for path, expected in expected_assertions.items():
            actual = get_by_path(actual_json, path)
            op, expected_value = _normalize_expected(expected)
            passed = self._matches(actual, op, expected_value)
            if not passed:
                diffs.append(
                    {
                        "path": path,
                        "expected": expected if op in {"eq", "not_null", "null"} else expected_value,
                        "actual": None if actual is MISSING else actual,
                        "operator": op,
                    }
                )
        return {"passed": not diffs, "diffs": diffs}

    def _matches(self, actual: Any, op: str, expected: Any) -> bool:
        if op == "not_null":
            return actual is not MISSING and actual is not None and actual != ""
        if op == "null":
            return actual is MISSING or actual is None
        if actual is MISSING:
            return False
        if op == "contains":
            if isinstance(actual, (list, tuple, set)):
                return expected in actual
            return str(expected) in str(actual)
        if op == "regex":
            return re.search(str(expected), str(actual)) is not None
        if op in {"gt", "gte", "lt", "lte"}:
            actual_number = _coerce_number(actual)
            expected_number = _coerce_number(expected)
            if op == "gt":
                return actual_number > expected_number
            if op == "gte":
                return actual_number >= expected_number
            if op == "lt":
                return actual_number < expected_number
            return actual_number <= expected_number
        return actual == expected


def command_for_script(script: Path, params: dict[str, Any]) -> list[str]:
    if script.suffix == ".py":
        command = [sys.executable, str(script)]
    elif script.suffix == ".sh":
        command = ["bash", str(script)]
    else:
        command = [str(script)]

    for key, value in params.items():
        flag = f"--{key}"
        values = value if isinstance(value, list) else [value]
        for item in values:
            command.append(flag)
            if isinstance(item, (dict, list)):
                command.append(json.dumps(item, ensure_ascii=False))
            elif isinstance(item, bool):
                command.append("true" if item else "false")
            else:
                command.append(str(item))
    return command


@dataclass
class ToolResolution:
    script_path: Path
    display_name: str
    tool_id: str


class ExecutionService:
    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root)
        self.assertions = AssertionEngine()

    def run_steps(
        self,
        *,
        steps_file: Path,
        tool_index: dict[str, dict[str, Any]],
        cli_dir: Path,
        skill_dir: Path,
        run_dir: Path,
        binding: dict[str, Any],
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        steps = read_json(steps_file, [])
        run_dir.mkdir(parents=True, exist_ok=True)
        step_outputs: list[dict[str, Any]] = []
        step_results: list[dict[str, Any]] = []
        status = "passed"
        started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        for step in steps:
            result = self._run_step(
                step=step,
                step_outputs=step_outputs,
                tool_index=tool_index,
                cli_dir=Path(cli_dir),
                skill_dir=Path(skill_dir),
                run_dir=run_dir,
                timeout_seconds=timeout_seconds,
            )
            step_results.append(result)
            if isinstance(result.get("stdout_json"), dict):
                step_outputs.append(result["stdout_json"])
            else:
                step_outputs.append({})
            if result["status"] != "passed":
                status = "failed"
                break

        ended_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        payload = {
            "status": status,
            "binding": binding,
            "steps_file": str(steps_file),
            "started_at": started_at,
            "ended_at": ended_at,
            "llm_invocations": 0,
            "steps": step_results,
        }
        write_json(run_dir / "steps-result.json", payload)
        return payload

    def _run_step(
        self,
        *,
        step: dict[str, Any],
        step_outputs: list[dict[str, Any]],
        tool_index: dict[str, dict[str, Any]],
        cli_dir: Path,
        skill_dir: Path,
        run_dir: Path,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        step_index = int(step.get("step_index", len(step_outputs) + 1))
        stdout_path = run_dir / "steps" / f"step-{step_index:03d}.stdout.json"
        stderr_path = run_dir / "steps" / f"step-{step_index:03d}.stderr.log"
        resolved = self.resolve_tool(step.get("execution_tool", ""), tool_index, cli_dir, skill_dir)
        params = resolve_value(step.get("input_params", {}), step_outputs)
        command = command_for_script(resolved.script_path, params)
        command_text = shlex.join(command)
        started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        try:
            completed = subprocess.run(
                command,
                cwd=str(cli_dir),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env={**os.environ, "AI_TEST_PLATFORM_EXECUTION": "1"},
            )
            stdout_raw = completed.stdout
            stderr_raw = completed.stderr
            return_code = completed.returncode
        except Exception as exc:  # pragma: no cover - defensive subprocess boundary
            stdout_raw = ""
            stderr_raw = str(exc)
            return_code = 127

        stdout_json: Any
        assertion_result: dict[str, Any]
        status: str
        try:
            stdout_json = parse_stdout_json(stdout_raw)
            assertion_result = self.assertions.assert_json(
                stdout_json,
                step.get("verification_assertion") or {},
            )
            status = "passed" if return_code == 0 and assertion_result["passed"] else "failed"
        except JsonParseError as exc:
            stdout_json = {"raw": stdout_raw}
            assertion_result = {
                "passed": False,
                "diffs": [
                    {
                        "path": "$stdout",
                        "expected": "JSON",
                        "actual": stdout_raw,
                        "operator": "parse_json",
                    }
                ],
                "error": str(exc),
            }
            status = "failed"

        write_json(stdout_path, stdout_json)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.write_text(stderr_raw, encoding="utf-8")
        return {
            "step_index": step_index,
            "step_name": step.get("name", f"Step {step_index}"),
            "tool": step.get("execution_tool", ""),
            "tool_display_name": resolved.display_name,
            "status": status,
            "command": command_text,
            "return_code": return_code,
            "stdout_json": stdout_json,
            "stderr": stderr_raw,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "assertion_result": assertion_result,
            "started_at": started_at,
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    def resolve_tool(
        self,
        execution_tool: str,
        tool_index: dict[str, dict[str, Any]],
        cli_dir: Path,
        skill_dir: Path,
    ) -> ToolResolution:
        if execution_tool.startswith("tool://"):
            tool_id = execution_tool.removeprefix("tool://")
            entry = tool_index.get(tool_id)
            if not entry:
                raise FileNotFoundError(f"Tool not found: {execution_tool}")
            script = Path(entry["script_path"])
            if not script.is_absolute():
                script = cli_dir / script
            return ToolResolution(script, entry.get("display_name", tool_id), tool_id)

        if execution_tool.startswith("skill://"):
            rel_path = execution_tool.removeprefix("skill://").lstrip("/")
            return ToolResolution(skill_dir / rel_path, execution_tool, execution_tool)

        return ToolResolution(cli_dir / execution_tool, execution_tool, execution_tool)
