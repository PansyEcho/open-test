"""使用本地假 CLI 验证异步 reviewer 的独立截止；不访问真实供应商或业务。"""

from datetime import timedelta
import json
import os
from pathlib import Path
import time

import pytest

from opentest.adapters.agent_runner import AgentRunner, AgentRunnerConfig
from opentest.domain.errors import ExecutionFailure, KnowledgeValidationError
from opentest.domain.models import AgentRunRequest, utc_now


def test_nonblocking_reviewer_deadline_survives_observer_detach(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """start立即返回，服务观察分离后原worker仍自行到期退出，不生成第二个run。"""

    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nsleep 30\nprintf 'finished'\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "source"
    source.mkdir()
    evidence_root = tmp_path / "evidence"
    runner = AgentRunner(AgentRunnerConfig(codex_executable="codex"))
    deadline_at = utc_now() + timedelta(seconds=0.5)
    started = time.monotonic()
    run_id = runner.start(AgentRunRequest(system_id="demo-system", agent="codex", prompt="只读复核", run_id="agent-" + "a" * 16),
                          source, evidence_root, deadline_at=deadline_at)
    assert time.monotonic() - started < 2
    runner.detach_observers()
    # 模拟重启后的另一个观察者只读原运行；绝不调用 run/start 续开请求。
    observer = AgentRunner()
    state = {}
    while time.monotonic() - started < 8:
        state = observer.read_state(run_id, evidence_root)
        if state.get("status") == "failed":
            break
        time.sleep(0.02)
    assert state.get("status") == "failed" and state.get("timed_out") is True
    evidence = json.loads((evidence_root / run_id / "evidence.json").read_text())
    assert evidence["timed_out"] is True
    request = json.loads((evidence_root / run_id / "worker-request.json").read_text())
    assert request["deadline_at"] == deadline_at.isoformat()
    assert len(list(evidence_root.iterdir())) == 1
    # 创建者回收直接子进程句柄，避免测试遗留 zombie。
    runner.read_state(run_id, evidence_root)


def test_expired_review_budget_never_starts_provider(tmp_path: Path) -> None:
    """等待上限从登记开始；启动前已过期时不创建运行目录或付费进程。"""

    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ExecutionFailure, match="expired"):
        AgentRunner().start(AgentRunRequest(system_id="demo-system", agent="codex", prompt="只读复核"),
                            source, tmp_path / "evidence", deadline_at=utc_now() - timedelta(seconds=1))
    assert not (tmp_path / "evidence").exists()


def test_review_deadline_cannot_cancel_a_business_task(tmp_path: Path) -> None:
    """此等待预算只允许独立只读辅助运行，带业务工具任务必须拒绝使用。"""

    request = AgentRunRequest(system_id="demo-system", agent="codex", prompt="业务任务", task_id="task-" + "a" * 16)
    with pytest.raises(KnowledgeValidationError, match="independent read-only"):
        AgentRunner().start(request, tmp_path, tmp_path / "evidence", deadline_at=utc_now() + timedelta(seconds=180))
