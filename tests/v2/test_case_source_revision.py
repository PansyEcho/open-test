"""Case只选择已有扫描，任务来源不改变共享pin/latest，重试保持首次冻结身份。"""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.source_analysis import GitSourceRepository
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
from opentest.application.tasks import LocalTaskManager
from opentest.application.auth import bind_authenticated_identity, current_employee
from opentest.domain.auth import AuthenticatedIdentity, EmployeeIdentity
from opentest.application.case_template_v4 import CaseTemplateV4Service
from opentest.application.case_source_selection import resolve_case_source_pin
from opentest.application.foundation import OpenTestApplication
from opentest.domain.case_template_v4 import CaseTemplateGenerationStartRequest, CaseTemplateSourceScope
from opentest.domain.errors import IdempotencyConflictError, KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import CoverageAssistancePolicy, EntryPoint, KnowledgeNodeKind, ScanManifest, SourceBaseline, SystemDefinition
from test_case_template_v4_revision import OPERATION_ID, SYSTEM_ID, _handoff


@pytest.fixture(autouse=True)
def employee_identity():
    """为编排单测绑定已核验员工；凭据验证另由认证集成测试覆盖，结束恢复线程上下文。"""

    with bind_authenticated_identity(AuthenticatedIdentity(EmployeeIdentity(user_id="employee-a", name="测试员工"), "user_bearer")):
        yield


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
    create_record = application.tasks.create_business_record

    def create_owned_record(record):
        """文件任务fixture模拟MySQL入口已验证归属，实际幂等与记录恢复仍使用真实任务存储。"""

        return create_record(record.model_copy(update={"owner_user_id": current_employee().user_id}))

    application.tasks.create_business_record = create_owned_record
    application.publications = SimpleNamespace(list_interface_summaries=Mock(return_value=[]))
    application.store.metadata = SimpleNamespace(fetch_one=Mock())
    application.source_analysis = SimpleNamespace(git_repository=GitSourceRepository(), artifacts=Mock())
    application.case_template_v4 = SimpleNamespace(handoffs=CaseTemplateHandoffStoreV4(tmp_path / "handoffs"), select_source_scan=Mock(return_value=None))
    application.analyze_source = Mock(side_effect=AssertionError("Case preparation must not scan"))
    application.rebuild_index = Mock(side_effect=AssertionError("Case preparation must not rebuild"))
    application.update_source_version = Mock(side_effect=AssertionError("Case preparation must not update system pin"))
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


def _scan(source: Path, commit: str, scan_id: str = "scan-case-selected", dirty: bool = False) -> ScanManifest:
    """创建具备目标入口的固定扫描样本，不执行Java扫描或写系统latest。"""

    # 无快照样本须记录真实branch/path等基线字段，避免测试绕过旧扫描的一致性约束。
    baseline = GitSourceRepository().capture(source).model_copy(update={"commit": commit, "dirty": dirty})
    return ScanManifest(scan_id=scan_id, system_id=SYSTEM_ID,
        baseline=baseline,
        entries=[EntryPoint(entry_id=OPERATION_ID, system_id=SYSTEM_ID, kind=KnowledgeNodeKind.FACADE,
            display_name="cancel", source_id=OPERATION_ID, source_path="Example.java")])


def _install_start(application, tmp_path, manifests, latest):
    """安装写入真实回执的轻量start，使准备请求重试行为不依赖扫描器或模型。"""

    from opentest.domain.case_template_v4 import CaseTemplateRequestReceipt

    def start(system_id, request, scan_id="", knowledge_ref=None):
        """按所选扫描创建不可变handoff，重放时校验首次请求参数。"""
        existing = application.case_template_v4.handoffs.find_request_receipt(request.request_id)
        parameters = request.model_dump(mode="json", exclude={"request_id"})
        if existing is not None:
            assert existing[1].parameters == parameters
            return existing[0]
        manifest = manifests[scan_id] if scan_id else latest()
        if scan_id:
            assert request.source_revision == manifest.baseline.commit
        handoff = _handoff(tmp_path).model_copy(update={
            "task_id": request.task_id, "root_task_id": request.root_task_id,
            "source_scan_id": manifest.scan_id, "baseline_id": request.baseline_id,
            "owner_user_id": current_employee().user_id, "environment_id": request.environment_id,
            "knowledge_dependencies": [knowledge_ref] if knowledge_ref else [],
            "source_scopes": [CaseTemplateSourceScope(source_system_id=system_id,
                source_scan_id=manifest.scan_id, source_baseline=manifest.baseline)],
            "request_receipts": [CaseTemplateRequestReceipt(request_id=request.request_id,
                action="start", parameters=parameters, response={"handoff_id": _handoff(tmp_path).handoff_id})],
        })
        application.case_template_v4.handoffs.write(handoff)
        return handoff

    manifest = next(iter(manifests.values()))
    application.store.metadata.fetch_one.return_value = {"scan_id": manifest.scan_id, "source_commit": manifest.baseline.commit}
    application.publications.list_interface_summaries.return_value = [{"operation_id": OPERATION_ID, "status": "AVAILABLE",
        "baseline_interface_id": 1, "interface_id": 1, "contract_revision": 1}]
    application.case_template_v4.start = Mock(side_effect=start)


def test_case_retries_keep_selected_commit_and_knowledge_when_shared_pointer_moves(tmp_path):
    """首次固定扫描和知识后，QA分支或共享发布变化都不能改写同一请求输入。"""

    source, first = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        manifest = _scan(source, first)
        _install_start(application, tmp_path, {manifest.scan_id: manifest}, lambda: manifest)
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, request_id="case-source-retry-001",
            baseline_id="baseline-one", environment_id="uat", deployment_confirmed=True)
        first_result = application.start_case_template_generation_v4(SYSTEM_ID, request)
        _commit(source, "new-qa-head")
        application.publications.list_interface_summaries.return_value = []
        application.store.metadata.fetch_one.return_value = None
        restored = application.start_case_template_generation_v4(SYSTEM_ID, request)
        assert restored["handoff"].handoff_id == first_result["handoff"].handoff_id
        assert restored["task"].result["case_source_commit"] == first
        assert restored["task"].result["case_source_scan_id"] == manifest.scan_id
        assert restored["task"].result["case_knowledge_ref"]["contract_revision"] == 1
        assert restored["handoff"].environment_id == "uat"
        application.publications.list_interface_summaries.assert_called_once()
        application.case_template_v4.select_source_scan.assert_not_called()
        assert application.store.get_system(SYSTEM_ID).source_version is None
        application.analyze_source.assert_not_called()
        application.update_source_version.assert_not_called()
    finally:
        application.tasks.close()


def test_case_rejects_separate_source_version_before_creating_task(tmp_path):
    """删除的源码输入不可通过Agent参数恢复；显式revision在任务与扫描之前拒绝。"""

    source, first = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, baseline_id="baseline-one",
            request_id="case-source-missing-001", source_revision=first[:8])
        with pytest.raises(KnowledgeValidationError, match="不再支持单独指定源码"):
            application.start_case_template_generation_v4(SYSTEM_ID, request)
        application.publications.list_interface_summaries.assert_not_called()
        application.analyze_source.assert_not_called()
    finally:
        application.tasks.close()


@pytest.mark.parametrize("qa_unavailable", [False, True])
def test_current_baseline_generation_never_resolves_qa_branch(tmp_path, qa_unavailable):
    """QA分支不存在或漂移都不影响所选基准，不触发旧自动选择与fallback。"""

    source, first = _repository(tmp_path)
    manifest = _scan(source, first, "scan-base")
    if qa_unavailable:
        _git(source, "branch", "-m", "main")
    else:
        _commit(source, "unscanned-qa")
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        _install_start(application, tmp_path, {manifest.scan_id: manifest}, lambda: manifest)
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, request_id="case-current-base-001",
            baseline_id="baseline-one", deployment_confirmed=True)
        prepared = application.start_case_template_generation_v4(SYSTEM_ID, request)
        assert prepared["task"].result["case_source_commit"] == first
        assert "coverage_skip_reason" not in prepared["task"].result
        assert application.case_template_v4.start.call_args.args[1].source_revision == first
        application.case_template_v4.select_source_scan.assert_not_called()
        application.analyze_source.assert_not_called()
    finally:
        application.tasks.close()


@pytest.mark.parametrize("missing", ["knowledge", "source"])
def test_current_baseline_missing_material_fails_without_fallback(tmp_path, missing):
    """当前可见接口契约或固定Git源码缺失时失败，不用latest或其他员工版本替代。"""

    source, commit = _repository(tmp_path)
    manifest = _scan(source, commit)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        _install_start(application, tmp_path, {manifest.scan_id: manifest}, lambda: manifest)
        # 分别缺失可见契约和固定源码，确认取消长文门禁没有放宽真实材料边界。
        if missing == "knowledge":
            application.publications.list_interface_summaries.return_value = []
        else:
            application.store.metadata.fetch_one.return_value = None
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, request_id="case-material-missing-" + missing,
            baseline_id="baseline-one", deployment_confirmed=True)
        with pytest.raises(KnowledgeValidationError, match="接口契约|固定Git源码"):
            application.start_case_template_generation_v4(SYSTEM_ID, request)
        application.case_template_v4.start.assert_not_called()
        application.case_template_v4.select_source_scan.assert_not_called()
        application.analyze_source.assert_not_called()
    finally:
        application.tasks.close()


@pytest.mark.parametrize("enabled,execution_mode", [(False, "generate_and_verify"), (True, "generate_only")])
def test_generation_without_effective_coverage_does_not_require_deployment_confirmation(tmp_path, enabled, execution_mode):
    """未启用增强或只生成时无需部署确认，但仍固定当前基准的知识与扫描。"""

    source, commit = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source, enabled))
        manifest = _scan(source, commit)
        _install_start(application, tmp_path, {manifest.scan_id: manifest}, lambda: manifest)
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, baseline_id="baseline-one",
            request_id="case-no-coverage-001", execution_mode=execution_mode)
        prepared = application.start_case_template_generation_v4(SYSTEM_ID, request)
        assert prepared["task"].result["case_source_commit"] == commit
        application.case_template_v4.select_source_scan.assert_not_called()
    finally:
        application.tasks.close()


def test_active_coverage_requires_confirmation_before_any_task(tmp_path):
    """增强启用且将执行时，未确认部署版本不能创建任务或读取知识。"""

    source, _ = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, baseline_id="baseline-one", request_id="case-confirm-001")
        with pytest.raises(KnowledgeValidationError, match="确认所选测试环境部署版本"):
            application.start_case_template_generation_v4(SYSTEM_ID, request)
        application.publications.list_interface_summaries.assert_not_called()
    finally:
        application.tasks.close()


def test_source_choice_conflict_is_rejected_but_other_long_task_does_not_block(tmp_path):
    """同请求不能切换基准；已有扫描复用不释放或占用其他长任务的门禁。"""

    source, first = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, baseline_id="baseline-one",
            request_id="case-source-conflict-001", deployment_confirmed=True)
        task, effective = application._prepare_case_start_task(SYSTEM_ID, request)
        with pytest.raises(IdempotencyConflictError):
            application._prepare_case_start_task(SYSTEM_ID, request.model_copy(update={"baseline_id": "another-baseline"}))
        manifest = _scan(source, first)
        _install_start(application, tmp_path, {manifest.scan_id: manifest}, lambda: manifest)
        application.tasks._reserve_exclusive(task)
        try:
            handoff = application._start_case_from_selected_source(task, effective)
            assert handoff.source_scan_id == manifest.scan_id
            assert task.task_id in application.tasks._exclusive_handles
        finally:
            application.tasks._release_exclusive(task.task_id)
        application.analyze_source.assert_not_called()
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


def _source_service(tmp_path, system, manifests, latest_id):
    """装配真实Case启动器与固定扫描缓存，契约读取按scan匹配且不调用扫描器。"""

    from test_case_template_v4_revision import _contract

    artifacts = Mock()
    artifacts.read.side_effect = lambda system_id, scan_id="latest": manifests[latest_id if scan_id == "latest" else scan_id]
    artifacts.list_manifest_paths.return_value = [Path(manifest.scan_id + ".json") for manifest in manifests.values()]
    artifacts.list_manifests.side_effect = AssertionError("must not deserialize all history")
    store = Mock()
    store.get_system.return_value = system
    store.source_scan_matches_configured_version.return_value = True
    service = CaseTemplateV4Service(store, artifacts, Mock(), CaseTemplateHandoffStoreV4(tmp_path / "selected-handoffs"))
    service.operation_contracts = SimpleNamespace(get_contract=Mock(side_effect=lambda _system, _entry, scan_id: _contract(scan_id)))
    return service


def test_explicit_scan_uses_history_independent_of_system_pin_and_latest(tmp_path):
    """历史任务读取指定scan，系统pin/latest指向另一commit也不串版本或被改写。"""

    source, first = _repository(tmp_path)
    first_pin = resolve_case_source_pin(GitSourceRepository(), _system(source), first)
    second = _commit(source, "new-system-pin")
    second_pin = resolve_case_source_pin(GitSourceRepository(), _system(source), second)
    system = _system(source).model_copy(update={"source_version": second_pin})
    historical = _scan(source, first, "scan-history")
    historical.baseline.snapshot_path = str(tmp_path / "snapshot-first")
    latest = _scan(source, second, "scan-latest")
    service = _source_service(tmp_path, system, {historical.scan_id: historical, latest.scan_id: latest}, latest.scan_id)
    selected = service.select_source_scan(SYSTEM_ID, OPERATION_ID, first_pin.commit)
    assert selected.scan_id == historical.scan_id
    request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, request_id="selected-history-001",
        source_revision=first_pin.commit)
    handoff = service.start(SYSTEM_ID, request, selected.scan_id)
    assert handoff.source_scan_id == historical.scan_id
    assert handoff.source_scopes[0].source_baseline.commit == first
    assert service.operation_contracts.get_contract.call_args.args[2] == historical.scan_id
    service.store.source_scan_matches_configured_version.assert_not_called()
    service.artifacts.require_source_snapshot.assert_called_with(SYSTEM_ID, historical.baseline, service.source_repository)
    assert system.source_version.commit == second


@pytest.mark.parametrize("change", ["branch", "registered_path"])
def test_legacy_scan_start_and_source_access_reject_the_same_baseline_drift(tmp_path, change):
    """无快照旧扫描即使commit相同且clean，也须在启动和后续源码访问使用同一基线判断。"""

    source, commit = _repository(tmp_path)
    manifest = _scan(source, commit)
    system = _system(source)
    # 两种改变均保持源码commit与clean状态，专门复现旧启动检查曾放过的基线差异。
    if change == "branch":
        _git(source, "switch", "-c", "same-commit-other-branch")
    else:
        relocated = tmp_path / "relocated"
        subprocess.run(["git", "clone", str(source), str(relocated)], check=True, capture_output=True)
        system = system.model_copy(update={"source_path": str(relocated)})
    service = _source_service(tmp_path, system, {manifest.scan_id: manifest}, manifest.scan_id)
    assert service.select_source_scan(SYSTEM_ID, OPERATION_ID, commit) is None
    request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
        request_id=f"legacy-drift-{change}", source_revision=commit)
    with pytest.raises(KnowledgeValidationError, match="source changed after scan"):
        service.start(SYSTEM_ID, request, manifest.scan_id)
    assert service.handoffs.find_request_receipt(request.request_id) is None
    handoff = _handoff(tmp_path).model_copy(update={"source_scopes": [
        CaseTemplateSourceScope(source_system_id=SYSTEM_ID, source_scan_id=manifest.scan_id,
            source_baseline=manifest.baseline),
    ]})
    with pytest.raises(KnowledgeValidationError, match="source changed after scan"):
        service._require_current_source_scopes(handoff)


def test_legacy_scan_same_baseline_allows_start_and_source_access(tmp_path):
    """无快照旧扫描基线未变时仍可生成并读取，重新捕获时间不应造成拒绝。"""

    source, commit = _repository(tmp_path)
    manifest = _scan(source, commit)
    service = _source_service(tmp_path, _system(source), {manifest.scan_id: manifest}, manifest.scan_id)
    # 真实Git capture会产生新的captured_at，两条入口都应排除它而保留全部源码身份字段。
    assert service.select_source_scan(SYSTEM_ID, OPERATION_ID, commit) is manifest
    request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
        request_id="legacy-baseline-unchanged", source_revision=commit)
    handoff = service.start(SYSTEM_ID, request, manifest.scan_id)
    service._require_current_source_scopes(handoff)
    assert handoff.source_scopes[0].source_baseline == manifest.baseline


@pytest.mark.parametrize("unusable", ["dirty", "missing_entry", "blocked_contract"])
def test_selection_skips_unusable_latest_and_accepts_reliable_partial_history(tmp_path, unusable):
    """同commit的dirty、缺入口或契约阻塞latest不永久挡住可靠的部分历史扫描。"""

    from opentest.domain.models import ScanCompleteness, ScanPublicationOutcome
    from test_case_template_v4_revision import _contract

    source, commit = _repository(tmp_path)
    historical = _scan(source, commit, "scan-partial").model_copy(update={
        "completeness": ScanCompleteness.PARTIAL, "publication_outcome": ScanPublicationOutcome.PARTIAL_PROJECTION})
    latest = _scan(source, commit, "scan-unusable")
    if unusable == "dirty":
        latest.baseline.dirty = True
    elif unusable == "missing_entry":
        latest.entries = []
    service = _source_service(tmp_path, _system(source), {historical.scan_id: historical, latest.scan_id: latest}, latest.scan_id)
    if unusable == "blocked_contract":
        service.operation_contracts.get_contract.side_effect = lambda _system, _entry, scan_id: _contract(scan_id).model_copy(
            update={"status": "BLOCKED"} if scan_id == latest.scan_id else {})
    selected = service.select_source_scan(SYSTEM_ID, OPERATION_ID, commit)
    assert selected is historical and selected.completeness == ScanCompleteness.PARTIAL
    handoff = service.start(SYSTEM_ID, CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
        request_id="selected-partial-001", source_revision=commit), selected.scan_id)
    assert handoff.source_scan_id == historical.scan_id


def test_shared_tool_cache_is_materialized_before_reusing_history(tmp_path):
    """历史工具本机尚无缓存时复用共享下载入口，真正缺材料才提示重新扫描。"""

    from opentest.domain.models import ToolDefinition
    from opentest.domain.errors import KnowledgeNotFoundError

    source, commit = _repository(tmp_path)
    manifest = _scan(source, commit)
    tool_root = tmp_path / "materialized-tools"
    manifest.tools = [ToolDefinition(tool_id="tool-target", system_id=SYSTEM_ID, display_name="target",
        script_path=str(tool_root / "target.sh"))]
    service = _source_service(tmp_path, _system(source), {manifest.scan_id: manifest}, manifest.scan_id)

    def materialize(system_id, scan_id):
        """模拟共享包下载成功，只创建本测试缓存，不发布新scan。"""
        assert system_id == SYSTEM_ID and scan_id == manifest.scan_id
        tool_root.mkdir()
        return tool_root

    service.artifacts.ensure_tool_bundle.side_effect = materialize
    assert service.select_source_scan(SYSTEM_ID, OPERATION_ID, commit) is manifest
    service.artifacts.ensure_tool_bundle.assert_called_once_with(SYSTEM_ID, manifest.scan_id)
    service.artifacts.ensure_tool_bundle.side_effect = KnowledgeNotFoundError("no shared bundle")
    assert service.select_source_scan(SYSTEM_ID, OPERATION_ID, commit) is None


@pytest.mark.parametrize("revision,dirty", [("", False), ("a" * 40, False), ("match", True)])
def test_internal_selected_scan_requires_exact_clean_commit(tmp_path, revision, dirty):
    """内部scan参数不是绕过版本校验的通行证，缺commit、错commit或dirty均拒绝。"""

    source, commit = _repository(tmp_path)
    manifest = _scan(source, commit, dirty=dirty)
    service = _source_service(tmp_path, _system(source), {manifest.scan_id: manifest}, manifest.scan_id)
    with pytest.raises(KnowledgeValidationError):
        service.start(SYSTEM_ID, CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
            request_id="invalid-selected-001", source_revision=commit if revision == "match" else revision), manifest.scan_id)
    assert service.handoffs.find_request_receipt("invalid-selected-001") is None


@pytest.mark.parametrize("intent", ["continue", "regenerate_latest"])
def test_continuation_inherits_only_fixed_source_and_auxiliary_skip(tmp_path, intent):
    """continue保留实际源码及增强跳过原因；显式latest重生成不继承旧来源。"""

    from opentest.domain.case_template_v4 import CaseTemplateContinuationRequest

    source, commit = _repository(tmp_path)
    application = _application(tmp_path)
    try:
        application.store.register_system(_system(source))
        request = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, request_id="base-source-continue")
        task, _ = application._prepare_case_start_task(SYSTEM_ID, request)
        task = application.tasks.save_business_record(task.model_copy(update={
            "generation_id": "case-template-generation-" + "b" * 20,
            "result": {**task.result, "case_source_scan_id": "scan-fixed", "case_source_commit": commit,
                "coverage_skip_reason": "SOURCE_SCAN_UNAVAILABLE"}}))
        successor_request_id = "continue-fixed-source-001"
        continuation = CaseTemplateContinuationRequest(request_id=successor_request_id, expected_revision=1,
            intent=intent, task_id=application._stable_case_task_id(SYSTEM_ID, successor_request_id))
        child = application._prepare_case_successor_task(task, continuation)
        if intent == "continue":
            assert child.result["case_source_scan_id"] == "scan-fixed"
            assert child.result["case_source_commit"] == commit
            assert child.result["coverage_skip_reason"] == "SOURCE_SCAN_UNAVAILABLE"
        else:
            assert "case_source_scan_id" not in child.result and "coverage_skip_reason" not in child.result
    finally:
        application.tasks.close()


def test_mysql_concurrent_tasks_keep_distinct_existing_scans_without_moving_system_pin(tmp_path):
    """真实MySQL中两个不同commit的任务并发冻结各自scan，共享pin/latest及长任务门禁不变。"""

    from concurrent.futures import ThreadPoolExecutor
    from test_case_template_v4_revision import _contract

    source, first = _repository(tmp_path)
    second = _commit(source, "second-version")
    app = OpenTestApplication(tmp_path / "knowledge")
    try:
        repository = app.source_analysis.git_repository
        system_pin = resolve_case_source_pin(repository, _system(source), second)
        app.store.register_system(_system(source).model_copy(update={"source_version": system_pin}))
        manifests = []
        for index, commit in enumerate((first, second)):
            # 测试准备真实固定快照和共享扫描；待测Case启动本身没有扫描或发布动作。
            manifest = _scan(source, commit, f"scan-concurrent-{index}")
            snapshot = app.knowledge.artifacts.source_snapshot_path(SYSTEM_ID, commit)
            repository.materialize_revision(manifest.baseline, snapshot, app.knowledge.artifacts.source_snapshot_root)
            manifest.baseline.snapshot_path = str(snapshot)
            app.knowledge.artifacts.write_manifest(manifest)
            manifests.append(manifest)
        app.knowledge.artifacts.publish_latest(SYSTEM_ID, manifests[1].scan_id)
        app.case_template_v4.operation_contracts = SimpleNamespace(
            get_contract=Mock(side_effect=lambda _system, _entry, scan_id: _contract(scan_id)))
        app._case_preparation_result = _prepared_result
        app.analyze_source = Mock(side_effect=AssertionError("must not scan"))
        app.rebuild_index = Mock(side_effect=AssertionError("must not rebuild"))
        app.update_source_version = Mock(side_effect=AssertionError("must not update pin"))
        app.tasks._reserve_exclusive = Mock(side_effect=AssertionError("must not occupy global task gate"))
        before = app.store.get_system(SYSTEM_ID).source_version
        requests = [CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID,
            request_id=f"concurrent-source-{index}", source_revision=commit[:8]) for index, commit in enumerate((first, second))]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(app.start_case_template_generation_v4, SYSTEM_ID, request) for request in requests]
            results = [future.result(timeout=20) for future in futures]
        assert [item["handoff"].source_scan_id for item in results] == [item.scan_id for item in manifests]
        assert [item["task"].result["case_source_commit"] for item in results] == [first, second]
        assert app.store.get_system(SYSTEM_ID).source_version == before
        assert app.knowledge.artifacts.read(SYSTEM_ID, "latest").scan_id == manifests[1].scan_id
        app.tasks._reserve_exclusive.assert_not_called()
        app.analyze_source.assert_not_called()
        app.update_source_version.assert_not_called()
        # 从共享库重放首次请求仍返回相同handoff，不被另一个任务的版本覆盖。
        replay = app.start_case_template_generation_v4(SYSTEM_ID, requests[0])
        assert replay["handoff"].handoff_id == results[0]["handoff"].handoff_id
    finally:
        app.close()


def test_historical_selection_skips_broken_scan_and_stops_before_unrelated_payloads(tmp_path):
    """先读轻量历史ID，跳过单条损坏并在首个可用scan短路，不解压其余旧大包。"""

    source, commit = _repository(tmp_path)
    latest = _scan(source, "c" * 40, "scan-current")
    usable = _scan(source, commit, "scan-selected")
    service = _source_service(tmp_path, _system(source), {latest.scan_id: latest, usable.scan_id: usable}, latest.scan_id)
    service.artifacts.list_manifest_paths.return_value = [Path("scan-unrelated.json"),
        Path(usable.scan_id + ".json"), Path("scan-broken.json"), Path(latest.scan_id + ".json")]

    def read(system_id, scan_id="latest"):
        """模拟损坏新历史与不能被访问的大旧包，验证真实短路读取顺序。"""
        assert system_id == SYSTEM_ID
        if scan_id == "latest":
            return latest
        if scan_id == "scan-broken":
            raise KnowledgeValidationError("malformed history")
        if scan_id == usable.scan_id:
            return usable
        raise AssertionError("unrelated history payload must not be loaded")

    service.artifacts.read.side_effect = read
    assert service.select_source_scan(SYSTEM_ID, OPERATION_ID, commit) is usable
    assert [call.args[1] for call in service.artifacts.read.call_args_list] == ["latest", "scan-broken", usable.scan_id]
    service.artifacts.list_manifests.assert_not_called()


def test_mysql_existing_continue_request_preserves_original_identity_when_projecting_source(tmp_path):
    """升级前已创建的continue child可重放并补来源投影，异参仍由原创建身份严格拒绝。"""

    from opentest.domain.case_template_v4 import CaseTemplateContinuationRequest
    from opentest.domain.models import TaskRecord, TaskStatus, utc_now

    source, commit = _repository(tmp_path)
    app = OpenTestApplication(tmp_path / "knowledge")
    try:
        app.store.register_system(_system(source))
        initial = CaseTemplateGenerationStartRequest(operation_id=OPERATION_ID, request_id="legacy-source-parent")
        predecessor, _ = app._prepare_case_start_task(SYSTEM_ID, initial)
        pin = resolve_case_source_pin(app.source_analysis.git_repository, _system(source), commit)
        predecessor = app.tasks.save_business_record(predecessor.model_copy(update={
            "generation_id": "case-template-generation-" + "b" * 20,
            "result": {**predecessor.result, "case_source_pin": pin.model_dump(mode="json"),
                "case_source_scan_id": "scan-original", "case_source_commit": commit,
                "coverage_skip_reason": "SOURCE_SCAN_UNAVAILABLE"}}))
        request_id = "legacy-continue-before-upgrade"
        request = CaseTemplateContinuationRequest(request_id=request_id, expected_revision=3,
            intent="continue", task_id=app._stable_case_task_id(SYSTEM_ID, request_id))
        # 升级前初始result只有三项请求参数，保存它实际形成的task_request_identity。
        old_child = app.tasks.create_business_record(TaskRecord(task_id=request.task_id, operation="case-generation",
            system_id=predecessor.system_id, target_id=predecessor.target_id,
            root_task_id=predecessor.root_task_id or predecessor.task_id,
            predecessor_task_id=predecessor.task_id, predecessor_generation_id=predecessor.generation_id,
            trace_id="legacy-child", status=TaskStatus.WAITING_FOR_CLIENT, ended_at=utc_now(),
            result={"request_id": request_id, "continuation_intent": "continue", "expected_revision": 3}))
        original_identity = old_child.result["task_request_identity"]
        restored = app._prepare_case_successor_task(predecessor, request)
        assert restored.task_id == old_child.task_id
        assert restored.result["task_request_identity"] == original_identity
        assert restored.result["case_source_commit"] == commit
        assert restored.result["coverage_skip_reason"] == "SOURCE_SCAN_UNAVAILABLE"
        replayed = app._prepare_case_successor_task(predecessor, request)
        assert replayed.result == restored.result
        with pytest.raises(IdempotencyConflictError):
            app._prepare_case_successor_task(predecessor, request.model_copy(update={"expected_revision": 4}))
    finally:
        app.close()
