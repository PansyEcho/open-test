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
from opentest.domain.models import (
    AgentRunRequest, EntryPoint, KnowledgeBackgroundUpdate, KnowledgeNodeKind, RuntimeToolSettings, ScanManifest,
    SemanticAnalysisResult, SemanticCallEdge, SemanticMethodDefinition, SourceBaseline,
    SourceReference, SystemDefinition,
)


@pytest.mark.production_metadata_loader
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


def _background_method(name, path, line=1, entry=False):
    """为背景取证构造一个具有独立类身份的方法，避免把同类入口当作下游调用。

    Args:
        name: 方法所属测试类名，同时用于生成稳定符号。
        path: 注册源码根内的Java文件相对路径。
        line: 方法证据的一基起始行。
        entry: 是否作为测试入口直接选中。
    Returns:
        可用于真实取证逻辑的方法元数据，不访问文件或运行Agent。
    """

    return SemanticMethodDefinition(
        symbol_id=f"demo.{name}#run()", qualified_class_name=f"demo.{name}", method_name="run",
        source_ref=SourceReference(path=path, line=line), entry_point_ids=["background-entry"] if entry else [],
    )


@pytest.mark.parametrize("reverse_edges", [False, True])
def test_background_evidence_stops_at_two_call_layers(tmp_path, reverse_edges):
    """用正反调用边顺序证明只读取两层下游，排除第三层、未解析调用和循环扩张。

    Args:
        tmp_path: 隔离源码根，只有允许进入证据的三个Java文件。
        reverse_edges: 反向排列相同调用图，结果必须保持一致。
    Returns:
        None；只返回入口和两层已解析调用的片段时通过。
    """

    methods = [_background_method(name, f"{name}.java", entry=name == "Entry")
               for name in ("Entry", "First", "Second", "Third", "Unknown")]
    for method in methods[:3]:
        (tmp_path / method.source_ref.path).write_text(f"class {method.qualified_class_name.rsplit('.', 1)[-1]} {{}}")
    # 未选文件故意不存在：越过两层或误用未解析调用会触发真实读取失败。
    edges = [SemanticCallEdge(
        caller_symbol_id=methods[caller].symbol_id, callee_symbol_id=methods[callee].symbol_id,
        callee_expression="run()", source_ref=methods[caller].source_ref, resolution_status=status,
    ) for caller, callee, status in ((0, 1, "resolved"), (1, 2, "resolved"), (2, 3, "resolved"),
                                   (1, 0, "resolved"), (0, 4, "unresolved"))]
    manifest = ScanManifest(system_id="background-system", scan_id="scan-background",
        baseline=SourceBaseline(source_path=str(tmp_path)),
        semantic_analysis=SemanticAnalysisResult(system_id="background-system", methods=methods,
                                                 call_edges=list(reversed(edges)) if reverse_edges else edges))
    # 直接选定真实入口ID，其他方法只能通过调用图进入取证范围。
    manifest.entries = [EntryPoint(entry_id="background-entry", system_id=manifest.system_id,
        kind=KnowledgeNodeKind.FACADE, display_name="背景入口", source_id=methods[0].symbol_id,
        source_path="Entry.java")]
    application = OpenTestApplication.__new__(OpenTestApplication)
    evidence = application._background_source_evidence(manifest)
    assert {excerpt["path"] for excerpt in evidence} == {"Entry.java", "First.java", "Second.java"}


def test_background_evidence_covers_distant_methods_without_duplicate_lines(tmp_path):
    """同文件中的远端入口仍有证据，重叠区域不重复，脱敏和真实行号保持有效。

    Args:
        tmp_path: 包含多个入口片段的隔离Java源码根。
    Returns:
        None；远端方法、去重、脱敏和真实行号均保留时通过。
    """

    lines = [f"// business line {number}" for number in range(1, 601)]
    lines[14] = 'String password = "must-not-leak";'
    (tmp_path / "Flow.java").write_text("\n".join(lines))
    methods = [_background_method("Flow", "Flow.java", line=line) for line in (20, 25, 400)]
    manifest = ScanManifest(system_id="background-system", scan_id="scan-background",
        baseline=SourceBaseline(source_path=str(tmp_path)),
        semantic_analysis=SemanticAnalysisResult(system_id="background-system", methods=methods))
    manifest.entries = [EntryPoint(entry_id="background-entry", system_id=manifest.system_id,
        kind=KnowledgeNodeKind.FACADE, display_name="背景入口", source_id="demo.Flow#run()", source_path="Flow.java")]
    # 给每个方法独立符号，保持同一真实文件和所属类。
    for method in methods:
        method.symbol_id = f"demo.Flow#run{method.source_ref.line}()"
    application = OpenTestApplication.__new__(OpenTestApplication)
    evidence = application._background_source_evidence(manifest)
    combined = "\n".join(excerpt["content"] for excerpt in evidence)
    assert "business line 400" in combined
    assert combined.count("business line 25") == 1
    assert "must-not-leak" not in combined
    for excerpt in evidence:
        assert excerpt["content"].splitlines()[0] == lines[excerpt["start_line"] - 1]


def test_background_evidence_rejects_empty_source(tmp_path):
    """空白Java不能证明业务背景，应在启动Agent之前报告证据缺失。

    Args:
        tmp_path: 仅有空白Java文件的隔离源码根。
    Returns:
        None；空白源码触发明确的领域错误时通过。
    """

    (tmp_path / "Empty.java").write_text("\n\n  \n")
    method = _background_method("Empty", "Empty.java")
    manifest = ScanManifest(system_id="background-system", scan_id="scan-background",
        baseline=SourceBaseline(source_path=str(tmp_path)),
        semantic_analysis=SemanticAnalysisResult(system_id="background-system", methods=[method]))
    manifest.entries = [EntryPoint(entry_id="background-entry", system_id=manifest.system_id,
        kind=KnowledgeNodeKind.FACADE, display_name="空入口", source_id=method.symbol_id, source_path="Empty.java")]
    application = OpenTestApplication.__new__(OpenTestApplication)
    with pytest.raises(KnowledgeValidationError, match="固定Java源码"):
        application._background_source_evidence(manifest)


def test_background_evidence_keeps_global_character_budget(tmp_path):
    """多个大方法仍共享固定总预算，达到上限后不再读取后续文件。

    Args:
        tmp_path: 包含十个大Java片段的隔离源码根。
    Returns:
        None；每段及总字符预算均受限，未读取超预算文件时通过。
    """

    methods = [_background_method(f"Flow{index}", f"Flow{index:02}.java") for index in range(11)]
    for method in methods[:10]:
        (tmp_path / method.source_ref.path).write_text("// business meaning " + "x" * 12_000)
    # 第十一个文件故意缺失，预算耗尽后不应对它发起读取。
    manifest = ScanManifest(system_id="background-system", scan_id="scan-background",
        baseline=SourceBaseline(source_path=str(tmp_path)),
        entries=[EntryPoint(entry_id=f"entry-{index}", system_id="background-system",
            kind=KnowledgeNodeKind.FACADE, display_name="业务入口", source_id=method.symbol_id,
            source_path=method.source_ref.path) for index, method in enumerate(methods)],
        semantic_analysis=SemanticAnalysisResult(system_id="background-system", methods=methods))
    application = OpenTestApplication.__new__(OpenTestApplication)
    evidence = application._background_source_evidence(manifest)
    assert len(evidence) == 10
    assert sum(len(excerpt["content"]) for excerpt in evidence) == 100_000
    assert all(len(excerpt["content"]) <= 10_000 for excerpt in evidence)
