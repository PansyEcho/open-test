"""在FastAPI依赖不可用时也能验证V2控制台静态安全契约。"""

from __future__ import annotations

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
    assert '<meta name="opentest-page-version" content="20260903-06">' in html
    assert '/assets/app.js?v=20260903-06' in html
    assert '/assets/styles.css?v=20260903-01' in html
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
    assert "只生成、不访问QA" in html
    start_generation = script[
        script.index("async function startCaseGeneration") : script.index("async function refreshCaseHandoff")
    ]
    assert "const requestBody = { operation_id: operationId }" in start_generation
    assert "execution_mode" not in start_generation
    assert "/case-generations" in start_generation
    execute_generation = script[
        script.index("async function executeCaseGeneration") : script.index("function delay")
    ]
    assert "/executions" in execute_generation
    assert 'environment_id: element("case-execution-environment").value' in execute_generation
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
    """重扫、目录和Curl请求的迟到失败不得覆盖用户刚切换的新系统页面。"""

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")

    # 三个跨系统异步入口都必须捕获请求代次，并在失败回写前检查当前系统作用域。
    retry_scan = script[script.index("async function retryScan()") : script.index("async function loadScanHistory")]
    load_catalog = script[script.index("async function loadScanCatalog") : script.index("function renderScanTree")]
    curl_preview = script[script.index("async function updateCurlPreview") : script.index("async function copyFacadeCurl")]
    assert "const requestScope = captureSystemScope();" in retry_scan
    assert retry_scan.count("if (!isCurrentSystemScope(requestScope))") >= 3
    assert "requestScope.systemId" in retry_scan
    assert "catch (error) {\n    if (!isCurrentSystemScope(requestScope))" in load_catalog
    assert "catch (error) {\n    if (!isCurrentSystemScope(requestScope))" in curl_preview


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


def test_page_conversation_is_retired_and_task_polling_stays_scoped() -> None:
    """页面聊天不再发请求，现有长任务轮询仍不得跨系统或对象回写。

    Returns:
        None；旧聊天入口无网络写入，且通用任务轮询仍固定作用域即通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    send_turn = script[
        script.index("async function sendKnowledgeConversation") : script.index("async function retryKnowledgeConversationTurn")
    ]
    retry_turn = script[
        script.index("async function retryKnowledgeConversationTurn") : script.index("async function generateCurrentKnowledge")
    ]
    load_questions = script[
        script.index("async function loadQuestions(") : script.index("function renderKnowledgeQuestions")
    ]
    task_progress = script[
        script.index("async function showTaskProgress") : script.index("async function resumeConsoleActivity")
    ]
    # 旧聊天入口只能提示迁移，不得保留conversation-turns读取、写入或重试路径。
    assert "renderCodexTaskPane" in send_turn
    assert "api(" not in send_turn
    assert "api(" not in retry_turn
    assert "return false;" in retry_turn
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
    """快速切换对象时，旧详情响应和finally都不能覆盖最后选择或提前清除Loading。

    Returns:
        None；详情函数使用独立目标代次校验而非仅校验系统时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    detail_loader = script[
        script.index("async function showKnowledgeTarget") : script.index("function renderKnowledgeTargetDetail")
    ]

    assert "knowledgeTargetRequestGeneration += 1" in detail_loader
    assert detail_loader.count("isCurrentKnowledgeTargetRequestScope(requestScope)") >= 3
    assert "isCurrentSystemScope(requestScope)" not in detail_loader
    # 中栏聊天也属于当前详情；发请求前必须先绑定新目标，不能继续显示上一个接口的作用域。
    immediate_scope = detail_loader.index(
        'bindKnowledgeConversationScope({ kind: "TARGET", scope_id: target.target_id }, target.display_name)'
    )
    assert immediate_scope < detail_loader.index("try {")
    scope_check = detail_loader.index("if (!isCurrentKnowledgeTargetRequestScope(requestScope))")
    cache_write = detail_loader.index("knowledgeTargetDetailCache.set(cacheKey, detail)")
    assert scope_check < cache_write
    assert "const scanId = scanCatalog?.scan_id || \"latest\"" in detail_loader
    assert "scan_id=${encodeURIComponent(scanId)}" in detail_loader


def test_codex_handoff_monitor_rejects_stale_same_target_attempt_responses() -> None:
    """同一目标切换到新attempt后，旧轮询响应不得重绘任务卡或Toast。

    Returns:
        None；轮询在GET后及终态刷新后都复核当前monitor task ID时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    monitor = script[
        script.index("async function monitorCodexClientHandoff") : script.index("function openCodexClientThread")
    ]

    assert "activeCodexHandoffMonitorTaskId === initialTask.task_id" in monitor
    assert monitor.count("if (!monitorIsCurrent())") >= 2
    task_get = monitor.index("const payload = await api")
    first_guard = monitor.index("if (!monitorIsCurrent())", task_get)
    attempt_write = monitor.index("currentKnowledgeWorkflow =", first_guard)
    assert task_get < first_guard < attempt_write
    terminal_reload = monitor.index("await Promise.all")
    terminal_guard = monitor.index("if (!monitorIsCurrent())", terminal_reload)
    toast = monitor.index('showToast("Codex 候选已确认并写入当前对象知识")')
    assert terminal_reload < terminal_guard < toast


def test_codex_thread_button_opens_desktop_before_requesting_owner_start() -> None:
    """等待任务按钮必须先打开原深链，再请求桌面owner幂等启动turn。

    Returns:
        None；静态客户端包含范围化turn路由，且跳转语句位于启动请求之前时通过。
    """

    script_path = Path(__file__).parents[2] / "opentest" / "web" / "app.js"
    script = script_path.read_text(encoding="utf-8")
    opener = script[
        script.index("async function openPersistedCodexTask") : script.index("function renderCodexTaskPane")
    ]

    start_request = opener.index("/knowledge/client-handoffs/${encodeURIComponent(handoffId)}/turns")
    deep_link_open = opener.index("window.location.href = deepLink")
    assert deep_link_open < start_request
    assert 'task.status === "waiting_for_client"' in script


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
    finish_generation = script[
        script.index("async function finishKnowledgeGeneration") : script.index("async function searchKnowledge")
    ]

    assert 'element("knowledge-task-progress").textContent = `生成失败：${message}`' in generate_current
    assert 'showToast(`知识生成失败：${message}`, "error")' in generate_current
    assert "activeKnowledgeStreamTaskId === task.task_id" in finish_generation
    assert "stopKnowledgeAgentEventStream(true)" in finish_generation
    assert "流式连接已关闭" in finish_generation
