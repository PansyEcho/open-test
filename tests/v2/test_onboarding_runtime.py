"""验证接入流程的MySQL启动边界、三项背景保存与受控Agent命令。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.agent_runner import AgentRunner, AgentRunnerConfig
from opentest.adapters.knowledge_interview import KnowledgeInterviewStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.application.foundation import OpenTestApplication
from opentest.application.knowledge_discovery import KnowledgeDiscoveryService
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import AgentRunRequest, KnowledgeBackgroundUpdate, RuntimeToolSettings, ScanManifest, SourceBaseline, SystemDefinition


def test_runtime_requires_mysql_without_creating_local_database(tmp_path):
    """缺失MySQL配置立即报告，不产生可被误当成生产库的本地文件。"""

    with pytest.raises(KnowledgeValidationError, match="MySQL配置"):
        OpenTestApplication(tmp_path / "knowledge")
    assert not (tmp_path / "knowledge").exists()


def test_runtime_mysql_failure_never_uses_file_fallback(tmp_path, monkeypatch):
    """元数据连接故障保留明确错误并关闭连接，不读取旧文件库。"""

    metadata = Mock()
    metadata.fetch_one.side_effect = OSError("private endpoint detail")
    monkeypatch.setattr("opentest.application.foundation.load_metadata_store", lambda root: metadata)
    with pytest.raises(KnowledgeValidationError, match="MySQL连接失败") as captured:
        OpenTestApplication(tmp_path / "knowledge")
    assert "private" not in str(captured.value)
    metadata.close.assert_called_once()
    assert not (tmp_path / "knowledge").exists()


def test_background_generation_preserves_existing_and_concurrent_manual_edits(tmp_path):
    """只补缺失三项背景；生成期间人工修改优先，不再需要核心对象与确认。"""

    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="sample-system", name="样例", source_path=str(tmp_path)))
    discovery = KnowledgeDiscoveryService(store, KnowledgeInterviewStore(store.root / ".opentest"))
    discovery.save_background("sample-system", KnowledgeBackgroundUpdate(answers={"interview:system-positioning": "人工定位"}))
    # 单元测试只组装本次业务函数需要的真实领域Store，避免重新开放文件生产启动入口。
    app = OpenTestApplication.__new__(OpenTestApplication)
    app.store = store
    app.knowledge_root = store.root
    app.knowledge_discovery = discovery
    app.runtime_settings = Mock()
    app.runtime_settings.read.return_value = RuntimeToolSettings()
    app.agent_runner = Mock()
    app._background_source_evidence = Mock(return_value=[{"path": "Facade.java", "start_line": 1, "content": "interface Facade {}"}])
    manifest = ScanManifest(system_id="sample-system", scan_id="scan-background", baseline=SourceBaseline(source_path=str(tmp_path), commit="a" * 40))

    def generate_with_concurrent_edit(request, source_root, evidence_root):
        """模拟生成窗口中的人工保存，输出仍带旧输入时只采纳未被修改的部分。"""

        assert set(request.output_schema["required"]) == {"interview:primary-flow", "interview:responsibility-boundaries"}
        discovery.save_background("sample-system", KnowledgeBackgroundUpdate(answers={"interview:primary-flow": "人工修改主流程"}))
        output = tmp_path / "background.json"
        output.write_text(json.dumps({"interview:primary-flow": "机器主流程", "interview:responsibility-boundaries": "机器边界"}))
        return SimpleNamespace(output_path=str(output), run_id=request.run_id)

    app.agent_runner.run.side_effect = generate_with_concurrent_edit
    published = app.generate_knowledge_background(manifest)
    context = discovery.get_context("sample-system")
    assert published["section_ids"] == ["interview:responsibility-boundaries"]
    assert context.interview_answers["interview:system-positioning"] == "人工定位"
    assert context.interview_answers["interview:primary-flow"] == "人工修改主流程"
    assert context.background_completed_at is not None
    assert "interview:core-objects" not in context.interview_answers
    assert app.generate_knowledge_background(manifest)["status"] == "preserved"
    assert app.agent_runner.run.call_count == 1


def test_background_agent_uses_selected_model_and_approved_readonly_source_tools(tmp_path):
    """无Task桥的背景任务也能读取授权源码，保持只读沙箱并遵守模型选择。"""

    request = AgentRunRequest(system_id="sample-system", agent="codex", prompt="读取固定源码生成背景", model="gpt-5.6-luna")
    command = AgentRunner(AgentRunnerConfig())._build_command(request, Path("/usr/bin/codex"), None,
        tmp_path / "output", tmp_path, tmp_path / "access")
    assert 'mcp_servers.opentest_source.default_tools_approval_mode="approve"' in command
    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert 'sandbox_mode="read-only"' in command
    assert "--ignore-user-config" in command
    assert any("registered_source_mcp.py" in argument for argument in command)
