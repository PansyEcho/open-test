"""验证Case所选源码先固定，再扫描，且网络重试不会跟随qa或tag移动。"""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.source_analysis import GitSourceRepository
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
from opentest.application.tasks import LocalTaskManager
from opentest.application.case_template_v4 import CaseTemplateV4Service
from opentest.application.case_source_selection import resolve_case_source_pin
from opentest.application.foundation import OpenTestApplication
from opentest.domain.case_template_v4 import CaseTemplateGenerationStartRequest, CaseTemplateSourceScope
from opentest.domain.errors import IdempotencyConflictError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import CoverageAssistancePolicy, ScanManifest, SourceBaseline, SystemDefinition
from test_case_template_v4_revision import OPERATION_ID, SYSTEM_ID, _handoff


def _git(source: Path, *arguments: str) -> str:
    """在临时仓库运行测试Git操作并返回输出，失败时立即结束测试。"""

    return subprocess.run(["git", "-C", str(source), *arguments], check=True, text=True,
                          capture_output=True).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    """创建可提交的qa仓库并返回源码路径和首个完整commit，无网络访问。"""

    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "qa")
    _git(source, "config", "user.email", "case-test@example.invalid")
    _git(source, "config", "user.name", "Case test")
    return source, _commit(source, "first")


def _commit(source: Path, content: str) -> str:
    """写一个新源码版本并返回真实commit，使分支漂移测试不依赖虚构身份。"""

    (source / "Example.java").write_text(content, encoding="utf-8")
    _git(source, "add", "Example.java")
    _git(source, "commit", "-m", content)
    return _git(source, "rev-parse", "HEAD")


def _system(source: Path, enabled: bool = True) -> SystemDefinition:
    """返回绑定测试仓库的系统，显式控制是否启用覆盖辅助。"""

    return SystemDefinition(system_id=SYSTEM_ID, name="源码选择测试", source_path=str(source),
                            coverage_assistance=CoverageAssistancePolicy(enabled=enabled))


def _application(tmp_path: Path) -> OpenTestApplication:
    """隔离组合准备入口用到的既有组件，不启动应用或连接工作台MySQL。

    Args:
        tmp_path: 测试专属目录，仅任务、Git和handoff组件使用文件适配器。
    Returns:
        供选择/重试单元测试调用的应用对象；调用方须关闭其tasks。
    """

    # 绕开完整应用构造，只对本slice的编排与持久重试做组件测试，不改变生产MySQL路径。
    application = OpenTestApplication.__new__(OpenTestApplication)
    application.store = GitKnowledgeStore(tmp_path / "knowledge")
    application.tasks = LocalTaskManager(tmp_path / "tasks")
    application.source_analysis = SimpleNamespace(git_repository=GitSourceRepository(), artifacts=Mock())
    application.case_template_v4 = SimpleNamespace(handoffs=CaseTemplateHandoffStoreV4(tmp_path / "handoffs"))
    application.native_task_instruction = Mock(return_value="测试继续指令")
    application._case_preparation_result = _prepared_result
    return application


def _prepared_result(task, handoff):
    """保留准备入口输出，避免单元测试额外构造Agent启动依赖。"""

    return {"task": task, "handoff": handoff}


def test_explicit_short_commit_and_tag_resolve_without_head_fallback(tmp_path):
    """短SHA和tag解析同一真实commit；无效版本不能悄悄选择HEAD。"""

    source, first = _repository(tmp_path)
    _git(source, "tag", "release-case", first)
    _commit(source, "second")
    repository = GitSourceRepository()
    # 两种显式输入都指向旧版本，验证不会被工作树HEAD覆盖。
    assert resolve_case_source_pin(repository, _system(source), first[:8]).commit == first
    assert resolve_case_source_pin(repository, _system(source), "release-case").commit == first
    with pytest.raises(KnowledgeValidationError):
        resolve_case_source_pin(repository, _system(source), "missing-tag")


def test_default_qa_refreshes_origin_and_refresh_failure_does_not_use_cached_ref(tmp_path):
    """有origin时刷新qa后固定最新提交；远端不可读时拒绝缓存旧提交。"""

    remote, first = _repository(tmp_path)
    local = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(local)], check=True, capture_output=True)
    latest = _commit(remote, "second")
    repository = GitSourceRepository()
    assert _git(local, "rev-parse", "qa") == first
    selected = resolve_case_source_pin(repository, _system(local), "")
    assert selected.commit == latest and selected.selected_revision == "qa"
    # 失败时仍有可用的缓存origin/qa，必须报错而不是伪称获取了最新版本。
    _git(local, "remote", "set-url", "origin", str(tmp_path / "missing-remote"))
    with pytest.raises(KnowledgeValidationError, match="刷新qa"):
        resolve_case_source_pin(repository, _system(local), "")


@pytest.mark.parametrize("fail_first_scan", [False, True])
def test_case_retries_keep_persisted_commit_and_scan_scopes(tmp_path, fail_first_scan):
    """qa移动或首次扫描失败后，同一请求仍扫描首次固定commit并冻结同版来源。"""

    source, first = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, request_id="case-source-retry-001")
        current_manifest = None

        def read_manifest(system_id, scan_id="latest"):
            """模拟扫描存储尚无结果或已经发布的固定manifest。"""
            from opentest.domain.errors import KnowledgeNotFoundError

            if current_manifest is None:
                raise KnowledgeNotFoundError("no scan")
            return current_manifest

        def scan(selected_request):
            """保留扫描输入commit并模拟一次失败或发布，不运行Java工具。"""
            nonlocal current_manifest
            if fail_first_scan and application.analyze_source.call_count == 1:
                raise KnowledgeValidationError("scan interrupted")
            current_manifest = ScanManifest(scan_id="scan-case-selected", system_id=SYSTEM_ID,
                baseline=SourceBaseline(source_path=str(source), commit=selected_request.source_revision),
                entries=[], tools=[], state_machines=[])
            return current_manifest

        def start(system_id, selected_request):
            """用准备入口传入的版本创建真实handoff，以便核对最终source_scopes。"""
            assert selected_request.source_revision == current_manifest.baseline.commit
            return _handoff(tmp_path).model_copy(update={
                "task_id": selected_request.task_id, "root_task_id": selected_request.root_task_id,
                "source_scan_id": current_manifest.scan_id,
                "source_scopes": [CaseTemplateSourceScope(source_system_id=system_id,
                    source_scan_id=current_manifest.scan_id, source_baseline=current_manifest.baseline)],
            })

        application.source_analysis.artifacts.read = Mock(side_effect=read_manifest)
        application.analyze_source = Mock(side_effect=scan)
        application.rebuild_index = Mock()
        application.case_template_v4.start = Mock(side_effect=start)
        if fail_first_scan:
            with pytest.raises(KnowledgeValidationError, match="scan interrupted"):
                application.start_case_template_generation_v4(SYSTEM_ID, request)
        else:
            application.start_case_template_generation_v4(SYSTEM_ID, request)
        _commit(source, "new-qa-head")
        # 重试不能重新解析移动后的qa，也不能丢掉失败前写入的pin。
        prepared = application.start_case_template_generation_v4(SYSTEM_ID, request)
        assert prepared["task"].result["case_source_pin"]["commit"] == first
        assert prepared["handoff"].source_scopes[0].source_baseline.commit == first
        assert all(call.args[0].source_revision == first for call in application.analyze_source.call_args_list)
        assert application.tasks._exclusive_handles == {}
    finally:
        application.tasks.close()


@pytest.mark.parametrize("enabled,execution_mode", [(False, "generate_and_verify"), (True, "generate_only")])
def test_existing_generation_without_effective_coverage_keeps_current_source(tmp_path, enabled, execution_mode):
    """未启用覆盖或只生成且未选版本时，不新增qa解析或扫描行为。"""

    source, _ = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source, enabled))
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
            request_id="case-source-legacy-001", execution_mode=execution_mode)
        task, request = application._prepare_case_start_task(SYSTEM_ID, request)
        application.case_template_v4.start = Mock(return_value=_handoff(tmp_path))
        application.analyze_source = Mock(side_effect=AssertionError("legacy path must not scan"))
        application._start_case_from_selected_source(task, request)
        assert application.case_template_v4.start.call_args.args[1].source_revision == ""
    finally:
        application.tasks.close()


def test_source_choice_conflict_and_existing_scan_gate_are_reused(tmp_path):
    """同请求不能改版本，已占用扫描门禁时不写pin或开始第二次扫描。"""

    source, first = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
            request_id="case-source-conflict-001", source_revision=first[:8])
        task, effective = application._prepare_case_start_task(SYSTEM_ID, request)
        with pytest.raises(IdempotencyConflictError):
            application._prepare_case_start_task(SYSTEM_ID, request.model_copy(update={"source_revision": "another-tag"}))
        application.tasks._reserve_exclusive(task)
        try:
            with pytest.raises(ScopeViolationError):
                application._start_case_from_selected_source(task, effective)
            assert "case_source_pin" not in application.tasks.get(task.task_id).result
        finally:
            application.tasks._release_exclusive(task.task_id)
    finally:
        application.tasks.close()


def test_case_start_rejects_latest_changed_by_another_workspace(tmp_path):
    """另一工作台改变latest时，handoff入口拒绝把错误版本交给生成模型。"""

    source, first = _repository(tmp_path)
    artifacts = Mock()
    artifacts.read.return_value = ScanManifest(scan_id="scan-other-workspace", system_id=SYSTEM_ID,
        baseline=SourceBaseline(source_path=str(source), commit="a" * 40), entries=[], tools=[], state_machines=[])
    store = Mock()
    store.get_system.return_value = _system(source)
    handoffs = CaseTemplateHandoffStoreV4(tmp_path / "handoffs")
    service = CaseTemplateV4Service(store, artifacts, Mock(), handoffs)
    # 此检查在读取契约和构建scope之前触发，不能先创建错误代际再靠后续制品校验修补。
    with pytest.raises(KnowledgeValidationError, match="selected commit"):
        service.start(SYSTEM_ID, CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
            request_id="case-cross-workspace-001", source_revision=first))
    assert handoffs.find_request_receipt("case-cross-workspace-001") is None
