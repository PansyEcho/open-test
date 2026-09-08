"""在FastAPI依赖不可用时也能验证V2控制台静态安全契约。"""

from __future__ import annotations

import re
from pathlib import Path


def test_console_static_client_uses_single_case_workflow_and_safe_rendering() -> None:
    """静态控制台应只展示四个主入口，并分离Case生成与显式执行。

    Returns:
        None；页面、API版本、按钮门禁和安全渲染契约正确时通过。
    """

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "<title>OpenTest Console</title>" in html
    assert '<meta name="opentest-page-version" content="20260908-08">' in html
    assert '/assets/app.js?v=20260908-08' in html
    assert '/assets/styles.css?v=20260908-08' in html
    assert 'const API_ROOT = "/api/v2"' in script
    assert "API_V3_ROOT" not in script
    assert "API_V4_ROOT" not in script
    assert "/api/v3" not in script
    assert "/api/v4" not in script
    assert ".innerHTML" not in script
    assert ".textContent" in script
    assert 'id="stale-page-warning"' in html
    assert "verifyCurrentPageVersion" in script
    assert "async function pollTask" in script
    assert "async function showTaskProgress" in script

    # 导航只保留SOP主线，不再暴露历史Case、自然语言、Suite或独立报告页面。
    assert html.count('class="nav-item') == 4
    for workspace in ("workbench", "system-config", "knowledge", "regression-cases"):
        assert f'data-workspace="{workspace}"' in html
    for retired_workspace in (
        "case-workspace",
        "natural-language",
        "test-execution",
        "booking-mvp",
        "regression-suites",
        "reports",
    ):
        assert f'data-workspace="{retired_workspace}"' not in html

    # Case生成请求不含执行模式；QA只能由第二个显式动作触发。
    assert 'id="start-case-generation"' in html
    assert 'id="execute-case-generation"' in html
    assert "执行本次 Generation 的全部 Variant" in html
    assert "此阶段不会访问 QA" in html
    start_generation = script[
        script.index("async function startCaseGeneration") : script.index("async function refreshCaseHandoff")
    ]
    assert "operation_id: operationId" in start_generation
    assert 'request_id: getOrCreateCaseRequestId("start", operationId)' in start_generation
    assert "execution_mode" not in start_generation
    assert "/case-generations" in start_generation
    assert 'interaction_mode: "web"' in start_generation
    assert "task_id" in start_generation
    execute_generation = script[
        script.index("async function executeCaseGeneration") : script.index("function delay")
    ]
    assert "/executions" in execute_generation
    assert 'const environmentId = element("case-execution-environment").value' in execute_generation
    assert "body: JSON.stringify({ environment_id: environmentId })" in execute_generation
    assert 'currentCaseGeneration?.generation_id !== generationId' in execute_generation
    assert '!["READY", "PARTIAL"].includes(currentCaseGeneration?.status)' in execute_generation
    assert "caseGenerationViewRequestGeneration" in script
    assert "caseExecutionViewRequestGeneration" in script
    assert "FAILED Generation没有不可变文件" in script
    assert "切换瞬间先撤销旧Generation的执行资格和报告" in script
    assert "/natural-language-tests/" not in script
    assert "/regression-suites/" not in script
    assert "/snapshots" not in script
    assert "execution-tasks" not in script
    assert "case-generation-tasks" not in script
def test_all_long_task_callers_use_the_progress_endpoint() -> None:
    """资源与执行等兼容轮询也必须读取统一阶段进度，而不是退回粗粒度任务状态。"""

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    poll_task = script[script.index("async function pollTask") : script.index("async function showTaskProgress")]

    assert "showTaskProgress" in poll_task
    assert "payload.task.operation" not in poll_task


def test_business_enums_have_independent_directory_and_source_aware_return_navigation() -> None:
    """业务枚举不得混入普通术语，且详情应能恢复来源对象的完整页面作用域。

    Returns:
        None；通过目录筛选、业务标题、相关枚举和返回栈静态契约断言验证页面改造。
    """

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "styles.css").read_text(encoding="utf-8")
    tree_renderer = script[script.index("function renderKnowledgeTree") : script.index("function knowledgeTargetButton")]
    directory_navigation = script[
        script.index("function openKnowledgeCandidateFromDirectory") : script.index("function pushKnowledgeReturnContext")
    ]
    candidate_renderer = script[script.index("function showKnowledgeCandidate") : script.index("async function showKnowledgeTarget")]
    target_renderer = script[script.index("function renderKnowledgeTargetDetail") : script.index("function knowledgeInterviewQuestionLabel")]
    summary_renderer = script[script.index("function renderConfirmedCandidateSummary") : script.index("async function loadKnowledgeInterview")]

    assert 'candidate.knowledge_form === "BUSINESS_TERM"' in tree_renderer
    assert 'candidate.knowledge_form === "BUSINESS_ENUM"' in tree_renderer
    assert "业务枚举 · ${businessEnums.length}" in tree_renderer
    assert "businessEnum.business_name" in tree_renderer
    assert "businessEnum.name" in tree_renderer
    assert 'CODE_DEFAULT: "代码默认（可修订）"' in script
    assert "currentKnowledgeDetail && currentSystem" in directory_navigation
    assert "showKnowledgeCandidate(candidate, hasKnowledgeSource)" in directory_navigation
    assert 'candidate.knowledge_form !== "BUSINESS_ENUM"' in summary_renderer
    assert "detail.related_enums" in target_renderer
    assert "pushKnowledgeReturnContext" in candidate_renderer
    assert "returnToKnowledgeSource" in candidate_renderer
    assert "knowledgeReturnStack = []" in script
    assert "questionScope" in script
    assert "questionsOpen" in script
    assert ".business-enum-value-row" in styles
    assert "grid-template-columns: 1fr; gap: 4px" in styles


def test_knowledge_directory_nests_facade_methods_under_their_facade_class() -> None:
    """Facade目录必须展示类名层级，并让方法叶子只显示方法名。

    Returns:
        None；通过目录渲染契约断言Facade分组不会退化为接口方法平铺。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    tree_renderer = script[script.index("function renderKnowledgeTree") : script.index("function knowledgeTargetButton")]

    assert 'for (const [group, items] of Object.entries(groups))' in tree_renderer
    assert 'category === "facade" ? document.createElement("details") : categorySection' in tree_renderer
    assert 'targetContainer.appendChild(textNode("summary", `${group} · ${items.length}`))' in tree_renderer
    assert "targetContainer.appendChild(knowledgeTargetButton(target, leafDisplayName(target)))" in tree_renderer


def test_knowledge_workspace_css_prevents_hidden_overflow_and_mobile_nested_scrolling() -> None:
    """三栏隐藏控件不得扩张页面，窄屏知识内容应只保留页面或抽屉主滚动。"""

    styles_path = Path(__file__).parents[2] / "opentest" / "web" / "styles.css"
    styles = styles_path.read_text(encoding="utf-8")

    # 关闭状态的气泡与抽屉不能继续扩大桌面文档宽度。
    assert '[role="tooltip"] { display: none;' in styles
    assert ".drawer { position: fixed; inset: 0; z-index: 100; overflow: hidden;" in styles

    # 390像素布局由页面或侧栏统一滚动，正文、候选和目录树不得形成第二层滚动区。
    assert ".candidate-grid { grid-template-columns: 1fr; max-height: none; overflow: visible; }" in styles
    assert ".knowledge-main-pane .draft-content { max-height: none; overflow: visible; }" in styles
    assert ".knowledge-directory-pane .tree-panel { max-height: none; overflow: visible; }" in styles
    assert "overflow-x: hidden; overflow-y: auto; overflow-wrap: anywhere" in styles


def test_console_ignores_late_failures_from_previous_system_scope() -> None:
    """重扫、扫描目录和任务目录的迟到结果不得覆盖刚切换的新系统页面。"""

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")

    # 跨系统异步入口必须捕获请求代次，并在任何页面回写前检查当前系统作用域。
    retry_scan = script[script.index("async function retryScan()") : script.index("async function loadScanHistory")]
    load_catalog = script[script.index("async function loadScanCatalog") : script.index("function renderScanTree")]
    load_tasks = script[script.index("async function loadTaskCatalog") : script.index("function renderSelectedKnowledgeGenerationAttempt")]
    assert "const requestScope = captureSystemScope();" in retry_scan
    assert retry_scan.count("if (!isCurrentSystemScope(requestScope))") >= 3
    assert "requestScope.systemId" in retry_scan
    assert "catch (error) {\n    if (!isCurrentSystemScope(requestScope))" in load_catalog
    assert "if (!isCurrentSystemScope(requestScope))" in load_tasks
    assert "/tasks?system_id=" in load_tasks
    assert "updateCurlPreview" not in script
    assert "copyFacadeCurl" not in script


def test_scan_completion_message_uses_persisted_manifest_outcome() -> None:
    """扫描任务completed时，页面仍应按Manifest结果准确提示partial projection。

    Returns:
        None；任务轮询返回持久结果，三个扫描入口均复用业务结果判断时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    classifier = script[
        script.index("function isPartialScanResult") : script.index("async function saveSystem")
    ]
    progress = script[
        script.index("async function showTaskProgress") : script.index("async function resumeConsoleActivity")
    ]
    scan_workflows = script[
        script.index("async function saveSystem") : script.index("async function loadScanHistory")
    ]

    assert 'scanProgress?.result?.publication_outcome === "partial_projection"' in classifier
    assert 'scanProgress?.result?.completeness === "partial"' in classifier
    assert "result: taskPayload.task.result || {}" in progress
    assert scan_workflows.count("isPartialScanResult(scanProgress)") == 3
    assert 'scanProgress.status === "partial"' not in scan_workflows


def test_question_cycle_writes_are_retired_from_the_page() -> None:
    """历史逐题暂存和整轮完成函数不得再调用后端写接口。"""

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    stage_answer = script[
        script.index("async function stageQuestionCycleAnswer") : script.index("async function completeQuestionCycle")
    ]
    complete_cycle = script[
        script.index("async function completeQuestionCycle") : script.index("async function handleCompleteQuestionCycleClick")
    ]

    # 兼容函数只提示回到原Codex任务，不读取周期、不提交答案也不启动重新分析。
    assert "void question;" in stage_answer
    assert "void answer;" in stage_answer
    assert "历史问题周期只读保留" in stage_answer
    assert "api(" not in stage_answer
    assert "return false;" in complete_cycle
    assert "api(" not in complete_cycle
    assert "showTaskProgress" not in complete_cycle


def test_archive_restore_uses_full_system_switch_and_clears_previous_knowledge_state() -> None:
    """归档恢复不得只刷新系统列表并继续展示恢复前系统的知识缓存。

    Returns:
        None；选择变化会先清理，且恢复完成后复用正式系统切换路径即通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    load_system = script[script.index("async function loadSystem") : script.index("function renderArchives")]
    restore_system = script[script.index("async function restoreSystem") : script.index("function validateSystemForm")]

    assert "if (previousSystemId !== selectedSystemId)" in load_system
    assert "clearSystemWorkspaceState();" in load_system
    assert "const loaded = await loadSystem();" in restore_system
    assert "await switchSystem(restoredSystemId);" in restore_system


def test_same_system_list_refresh_rebases_knowledge_return_navigation() -> None:
    """同系统列表刷新应保留候选详情已有的返回入口并更新其异步请求代次。

    Returns:
        None；刷新前固定系统身份，且同系统分支重基返回栈代次即通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    load_system = script[script.index("async function loadSystem") : script.index("function renderArchives")]

    assert 'const previousSystemId = currentSystem?.system_id || "";' in load_system
    assert "if (previousSystemId !== selectedSystemId)" in load_system
    assert "for (const source of knowledgeReturnStack)" in load_system
    assert "source.generation = requestGeneration;" in load_system


def test_legacy_agent_ui_is_removed_and_task_polling_stays_scoped() -> None:
    """旧后台Agent面板、页面会话和写控制调用必须从静态客户端彻底移除。

    Returns:
        None；旧DOM、样式、实时或写入口消失，通用任务轮询仍固定作用域时通过。
    """

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "styles.css").read_text(encoding="utf-8")
    load_questions = script[
        script.index("async function loadQuestions(") : script.index("function renderKnowledgeQuestions")
    ]
    task_progress = script[
        script.index("async function showTaskProgress") : script.index("async function resumeConsoleActivity")
    ]
    # 删除旧区域本身，避免隐藏DOM继续保留已下线的按钮和敏感诊断材料。
    for retired_id in (
        "knowledge-agent-stream-panel",
        "open-codex-client-thread",
        "view-agent-diagnostics",
        "cancel-knowledge-agent",
        "continue-knowledge-agent",
        "copy-agent-resume-command",
        "knowledge-agent-prompt",
        "knowledge-agent-source-access",
        "knowledge-agent-final-output",
        "knowledge-conversation-history",
        "knowledge-conversation-message",
        "send-knowledge-conversation",
    ):
        assert f'id="{retired_id}"' not in html

    # 浏览器不再连接后台Agent事件、取消、页面会话或turn接口。
    for retired_fragment in (
        "EventSource",
        "startKnowledgeAgentEventStream",
        "viewKnowledgeAgentDiagnostics",
        "cancelKnowledgeAgent",
        "continueKnowledgeAgent",
        "sendKnowledgeConversation",
        "retryKnowledgeConversationTurn",
        "/events?after=",
        "/cancel-agent",
        "/conversation-turns",
        "/turns",
    ):
        assert retired_fragment not in script
    for retired_selector in (
        ".knowledge-agent-stream-panel",
        ".knowledge-agent-events",
        ".knowledge-agent-diagnostics",
        ".knowledge-conversation",
        ".conversation-history",
        ".conversation-turn",
    ):
        assert retired_selector not in styles

    # 原生Agent任务卡和统一任务轮询仍是页面恢复入口。
    assert 'id="knowledge-current-task-panel"' in html
    assert 'id="copy-current-knowledge-task-instruction"' in html
    assert "/tasks/${encodeURIComponent(taskId)}/agent-diagnostics" in script
    assert "function taskHasHistoricalAgentEvidence" in script
    assert "function appendTaskAgentDiagnostics" in script
    evidence_guard = script[
        script.index("function taskHasHistoricalAgentEvidence") : script.index("async function loadTaskAgentDiagnostics")
    ]
    assert "progress.agent_event_cursor" in evidence_guard
    assert "progress.agent_session_id" in evidence_guard
    assert "task.client_handoff?.thread_id" in evidence_guard
    assert "diagnostics.prompt ||" not in script
    assert "diagnostics.final_output ||" not in script
    assert ".task-agent-diagnostics" in styles
    assert "requestScope" in task_progress
    assert "isCurrentTaskRequestScope(requestScope)" in task_progress
    assert "if (activeLongTaskId === taskId)" in task_progress
    assert "while (true)" in task_progress
    assert "scopedKnowledgeTask" in task_progress
    assert "375" not in task_progress

    # 兼容loadQuestions不再发question-cycle请求，只刷新现有工作流里的Codex任务。
    assert "renderCodexTaskPane(currentKnowledgeWorkflow)" in load_questions
    assert "api(" not in load_questions


def test_knowledge_target_loading_ignores_out_of_order_detail_responses() -> None:
    """快速切换对象时，旧详情响应和finally不能覆盖最后选择或提前清除Loading。

    Returns:
        None；详情函数先绑定目标任务范围，再使用独立目标代次校验时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    detail_loader = script[
        script.index("async function showKnowledgeTarget") : script.index("function renderKnowledgeTargetDetail")
    ]

    assert "knowledgeTargetRequestGeneration += 1" in detail_loader
    assert detail_loader.count("isCurrentKnowledgeTargetRequestScope(requestScope)") >= 3
    assert "isCurrentSystemScope(requestScope)" not in detail_loader
    # 当前任务卡和问题投影必须在请求前绑定新目标，不能继续显示上一个接口的作用域。
    immediate_scope = detail_loader.index(
        'setKnowledgeViewScope({ kind: "TARGET", scope_id: target.target_id }, target.display_name)'
    )
    assert immediate_scope < detail_loader.index("try {")
    scope_check = detail_loader.index("if (!isCurrentKnowledgeTargetRequestScope(requestScope))")
    cache_write = detail_loader.index("knowledgeTargetDetailCache.set(cacheKey, detail)")
    assert scope_check < cache_write
    assert "const scanId = scanCatalog?.scan_id || \"latest\"" in detail_loader
    assert "scan_id=${encodeURIComponent(scanId)}" in detail_loader


def test_console_element_lookups_match_static_dom_contract() -> None:
    """脚本中的静态元素读取和短动作绑定必须全部命中当前HTML。

    Returns:
        None；删除旧Agent区域后不存在会在初始化阶段抛错的悬空DOM ID时通过。
    """

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    element_ids = set(re.findall(r'\belement\("([^"]+)"\)', script))
    bound_action_ids = set(re.findall(r'\bbindShortAction\("([^"]+)"', script))

    assert element_ids <= html_ids, sorted(element_ids - html_ids)
    assert bound_action_ids <= html_ids, sorted(bound_action_ids - html_ids)


def test_native_agent_task_uses_copyable_instruction_without_starting_background_turn() -> None:
    """原生继续指令不启动后台turn，网页运行诊断可以只读链接到已有聊天。

    Returns:
        None；原生任务用task_id恢复，查看聊天不产生SSE或turn写请求时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    copier = script[
        script.index("async function copyTaskContinuationInstruction") : script.index("function taskHasHistoricalAgentEvidence")
    ]

    assert "/tasks/${encodeURIComponent(task.task_id)}/context" in copier
    assert "navigator.clipboard.writeText(instruction)" in copier
    assert "instruction.includes(task.task_id)" in copier
    assert "/turns" not in script
    assert "EventSource" not in script
    # 原生继续指令不做深链跳转；网页诊断仅对读取成功的session构造查看链接。
    assert "codex://threads/" not in copier
    assert 'link.href = `codex://threads/${sessionId}`' in script
    assert "waiting_for_client" in script


def test_knowledge_attention_pane_only_shows_each_targets_latest_actionable_task() -> None:
    """知识右栏必须先按目标选最新任务，再隐藏已完成和已取消目标。

    Returns:
        None；任务聚合、过滤顺序、文案和过期知识动作均符合关注事项语义时通过。
    """

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")
    latest_selector = script[
        script.index("function latestKnowledgeTasksByTarget") : script.index("function isKnowledgeTaskAttentionRequired")
    ]
    attention_filter = script[
        script.index("function isKnowledgeTaskAttentionRequired") : script.index("function isCurrentTaskRequestScope")
    ]
    renderer = script[
        script.index("function renderCodexTaskPane") : script.index("function renderWorkbenchTasks")
    ]
    action_renderer = script[
        script.index("function refreshKnowledgeGenerationActions") : script.index("async function searchKnowledge")
    ]
    retired_question_renderer = script[
        script.index("function renderKnowledgeQuestions") : script.index("function selectKnowledgeQuestionTab")
    ]

    # 用户无需再从“全部/已完成”筛选器中分辨任务；右栏本身就是待关注队列。
    assert 'id="codex-task-filter"' not in html
    assert "待关注知识任务" in html
    assert "latestByTarget = new Map()" in latest_selector
    assert "knowledgeTaskCreatedAtMs(task) > knowledgeTaskCreatedAtMs(currentLatest)" in latest_selector
    assert '"pending"' in attention_filter
    assert '"waiting_for_input"' in attention_filter
    assert '"failed"' in attention_filter
    assert '"completed"' not in attention_filter
    assert '"cancelled"' not in attention_filter
    latest_index = renderer.index("latestKnowledgeTasksByTarget(workflow)")
    attention_index = renderer.index(".filter(isKnowledgeTaskAttentionRequired)")
    assert latest_index < attention_index
    assert "当前没有需要关注的知识任务" in renderer
    assert 'element("question-badge")' not in retired_question_renderer
    assert 'element("question-count-inline")' not in retired_question_renderer
    assert 'element("show-all-knowledge-questions")' not in retired_question_renderer

    # STALE是用户能理解的业务状态，主动作必须明确表示会重新生成知识。
    assert 'selectedKnowledgeStatus === "STALE"' in action_renderer
    assert 'generateButtonLabel = "重新生成知识"' in action_renderer


def test_console_exposes_pinned_source_version_and_explicit_baseline_update() -> None:
    """顶部应全局显示固定Git版本，且只有专用动作可以切换现有系统基准。

    Returns:
        None；Tag、完整Commit、分支提示、扫描状态和显式更新端点均存在时通过。
    """

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")
    styles = (web_root / "styles.css").read_text(encoding="utf-8")
    source_renderer = script[
        script.index("function renderConfiguredSourceVersion") : script.index("function clearSystemWorkspaceState")
    ]
    updater = script[
        script.index("async function updateSourceVersionAndScan") : script.index("async function retryScan")
    ]
    retry_scan = script[
        script.index("async function retryScan") : script.index("async function loadScanHistory")
    ]

    for element_id in (
        "source-version-chip",
        "source-version-tag",
        "source-version-commit",
        "source-version-state",
        "source-revision",
        "update-source-version",
    ):
        assert f'id="{element_id}"' in html
    assert "system.source_version || null" in source_renderer
    assert "sourceVersion?.managed_tag" in source_renderer
    assert "sourceVersion?.commit" in source_renderer
    assert "sourceVersion?.branch_hint" in source_renderer
    assert "完整扫描已发布" in source_renderer
    assert ".source-version-chip" in styles

    assert "/source-version`" in updater
    assert 'method: "POST"' in updater
    assert "body: JSON.stringify({ revision })" in updater
    assert "response.scan_task.task_id" in updater
    assert "loadScanHistory(requestScope, true)" in updater
    assert "source_revision" not in retry_scan


def test_scan_catalog_rejects_invalidated_and_out_of_order_scan_responses() -> None:
    """目录失效或历史扫描快速切换时，迟到响应不得写缓存或重绘页面。

    Returns:
        None；目录拥有独立代次、AbortController且缓存写入位于scope校验之后时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    invalidation = script[
        script.index("function invalidateKnowledgeReadCaches") : script.index("function knowledgeGenerationAttemptTargetId")
    ]
    loader = script[script.index("async function loadScanCatalog") : script.index("async function loadDsfOperationCatalog")]

    assert "knowledgeScanCatalogRequestGeneration += 1" in invalidation
    assert "activeKnowledgeScanCatalogController.abort()" in invalidation
    assert "const scanId = element(\"scan-history\").value || \"latest\"" in loader
    assert "catalogGeneration === knowledgeScanCatalogRequestGeneration" in loader
    assert '(element("scan-history").value || "latest") === scanId' in loader
    request = loader.index("payload = await api")
    scope_guard = loader.index("if (!catalogRequestIsCurrent())", request)
    cache_write = loader.index("knowledgeScanCatalogCache.set(catalogCacheKey, payload)")
    assert request < scope_guard < cache_write
    assert "signal: requestController.signal" in loader


def test_generation_list_invalidates_active_handoff_polling() -> None:
    """查看已有Generation前必须废弃在途handoff响应和轮询定时器。

    Returns:
        None；目录、handoff和启动请求共享同一代次门禁时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    list_loader = script[
        script.index("async function loadCaseGenerations") : script.index("async function loadCaseHandoff")
    ]
    handoff_loader = script[
        script.index("async function loadCaseHandoff") : script.index("async function startCaseGeneration")
    ]
    starter = script[
        script.index("async function startCaseGeneration") : script.index("async function refreshCaseHandoff")
    ]

    # Generation目录和handoff共享展示区，用户主动切换目录前必须先废弃旧轮询。
    stop_polling = list_loader.index("stopCaseHandoffPolling(false)")
    generation_request = list_loader.index("payload = await api")
    assert stop_polling < generation_request
    assert handoff_loader.count("requestGeneration !== caseRequestGeneration") >= 2
    assert "activeCaseHandoffId !== handoffId" in handoff_loader
    assert "const startRequestGeneration = caseRequestGeneration" in starter
    assert starter.count("startRequestGeneration !== caseRequestGeneration") >= 2


def test_scan_history_change_restores_confirmed_baseline_after_catalog_failure() -> None:
    """历史scan目录失败时必须恢复原选择，避免Git卡与仍显示的知识目录错配。

    Returns:
        None；切换使用可抛错目录加载，并在失败分支恢复previousScanId即通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    change_handler = script[
        script.index("async function handleScanHistoryChange") : script.index("async function loadScanCatalog")
    ]

    # 只有目录加载成功才能提交新Git基线；失败分支要回到仍在页面中的旧目录版本。
    assert "const previousScanId = scanCatalog?.scan_id || \"\"" in change_handler
    assert "await loadScanCatalog(requestScope, true)" in change_handler
    failure_branch = change_handler.index("} catch (error)")
    assert change_handler.index("select.value = previousScanId", failure_branch) > failure_branch
    assert change_handler.index("renderSelectedScanBaseline()", failure_branch) > failure_branch


def test_console_scan_failure_stops_manifest_loading_and_success_feedback() -> None:
    """扫描失败终态必须抛给主流程，目录读取失败也不得被内部吞掉。"""

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    save_system = script[script.index("async function saveSystem()") : script.index("async function retryScan()")]
    retry_scan = script[script.index("async function retryScan()") : script.index("async function loadScanHistory")]
    task_progress = script[script.index("async function showTaskProgress") : script.index("async function resumeConsoleActivity")]

    assert "await loadScanHistory(scope, true);" in save_system
    assert "await loadScanCatalog(scope, true);" in save_system
    assert "await loadScanHistory(requestScope, true);" in retry_scan
    assert "await loadScanCatalog(requestScope, true);" in retry_scan
    assert 'if (["failed", "interrupted"].includes(progress.status))' in task_progress
    assert "throw new Error(taskPayload.task.error" in task_progress
    assert "扫描任务执行成功" not in task_progress


def test_single_target_knowledge_failure_remains_visible_after_loading_closes() -> None:
    """单目标知识失败必须同时留下常驻摘要和显眼错误提示。

    Returns:
        None；当前对象入口的失败分支更新进度卡并显示错误Toast即通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    generate_current = script[
        script.index("async function generateCurrentKnowledge") : script.index("function backgroundKnowledgeReady")
    ]
    assert 'element("knowledge-task-progress").textContent = `生成失败：${message}`' in generate_current
    assert 'showToast(`知识生成失败：${message}`, "error")' in generate_current
    assert "finishKnowledgeGeneration" not in script
    assert "stopKnowledgeAgentEventStream" not in script


def test_knowledge_generation_uses_complete_latest_instead_of_browsed_partial_scan() -> None:
    """浏览partial扫描时，知识生成仍必须请求后端当前完整latest基线。

    Returns:
        None；生成请求与幂等范围均不再绑定当前浏览目录时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    baseline_key = script[
        script.index("function knowledgeGenerationBaselineKey")
        : script.index("function getOrCreateCodexKnowledgeAttemptId")
    ]
    generate_current = script[
        script.index("async function generateCurrentKnowledge")
        : script.index("function backgroundKnowledgeReady")
    ]

    # latest完整基线驱动幂等身份；用户选择的partial只控制当前目录展示。
    assert "scan.latest" in baseline_key
    assert 'scan.completeness === "complete"' in baseline_key
    assert 'scan.publication_outcome === "complete_baseline"' in baseline_key
    assert 'scan_id: "latest"' in generate_current
    assert "scan_id: scanCatalog?.scan_id" not in generate_current


def test_legacy_knowledge_progress_rejects_scan_id_as_target_fallback() -> None:
    """旧任务current_item中的scan ID不得伪装成右栏知识目标。

    Returns:
        None；回退只接受目录目标、稳定知识前缀或旧Java方法身份时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    classifier = script[
        script.index("function isLegacyKnowledgeTargetId")
        : script.index("function knowledgeGenerationAttemptTargetId")
    ]
    extractor = script[
        script.index("function knowledgeGenerationAttemptTargetId")
        : script.index("function selectKnowledgeGenerationAttempt")
    ]

    # 类型化target字段仍优先；只有历史progress回退需要防止scan任务串入知识关注栏。
    assert "scanCatalog?.targets" in classifier
    assert "state-machine|transition|semantic|entry|logic" in classifier
    assert "#[A-Za-z_$]" in classifier
    assert "isLegacyKnowledgeTargetId(progressTarget)" in extractor
    assert "return task.progress.current_item" not in extractor
