"""在FastAPI依赖不可用时也能验证V2控制台静态安全契约。"""

from __future__ import annotations

from pathlib import Path


def test_console_static_client_uses_only_v2_routes_and_safe_rendering() -> None:
    """静态客户端应集中使用V2前缀，并通过textContent展示业务响应。

    Returns:
        None；通过静态资源断言验证周期路由、右栏门禁和安全渲染。
    """

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "OpenTest V2 Console" in html
    assert 'const API_ROOT = "/api/v2"' in script
    assert '<meta name="opentest-page-version" content="20260826-02">' in html
    assert '/assets/app.js?v=20260826-02' in html
    assert 'id="stale-page-warning"' in html
    assert html.index('id="stale-page-warning"') < html.index('id="workspace-workbench"')
    assert "verifyCurrentPageVersion" in script
    assert 'await verifyCurrentPageVersion()' in script
    assert "/api/projects" not in script
    assert "/resource-probes" in script
    assert "/validation-capabilities" in script
    assert "/oracle-operations" not in script
    assert "/regression-suites/" in script
    assert 'value="suite:train-booking-core:core-order-lifecycle-v2"' in html
    assert "estimated_process_count" in script
    assert "non_test_order_count" in script
    assert ".innerHTML" not in script
    assert ".textContent" in script
    assert "EFFECT_ONLY：仅证明 MQ 消费后的业务效果" in html
    assert "Host、账号、密码、Token" in html
    assert html.count('class="nav-item') == 9
    assert 'role="tooltip"' in html
    assert "查看集群详情" in script
    assert "mqDetailControl" in script
    assert "resourceErrorLabel" in script
    assert "historical_orphans" in script
    assert "function shellQuote(value)" in script
    assert 'replaceAll("\'", `\'"\'"\'`)' in script
    assert "systemRequestGeneration" in script
    assert "isCurrentSystemScope" in script
    assert 'id="detail-drawer"' in html
    assert "场景矩阵 → 人工确认 → Case → 执行步骤" in html
    assert "QA 数据模板" not in html
    assert "/knowledge/generations" in script
    assert "/knowledge/generation-batches/" not in script
    assert "/case-generations" in script
    assert "/natural-language-tests/previews" in script
    assert "preview-natural-language\" disabled" not in html
    assert 'id="generate-all-knowledge"' not in html
    assert 'id="start-knowledge-generation"' not in html
    assert "生成全部接口与公共逻辑知识" not in html
    assert "knowledgeGenerationTargets" not in script
    assert 'id="knowledge-agent-stream-panel"' in html
    assert "new EventSource" in script
    assert "source.onerror = async" in script
    assert "const taskPayload = await api(`/tasks/${encodeURIComponent(task.task_id)}`)" in script
    assert "activeKnowledgeEventSource !== source" in script
    assert "terminalStatuses.includes(latestTask.status)" in script
    assert "if (!taskRunning)" in script
    assert "stopKnowledgeAgentEventStream(true)" in script
    assert "if (taskRunning) {\n    // 只有仍在运行的任务需要累计耗时" in script
    assert "if (taskRunning) {\n    activeKnowledgeStreamStartedAt" in script
    assert 'id="cancel-knowledge-agent"' in html
    assert 'cancelButton.dataset.taskId = task.task_id' in script
    assert 'cancelButton.dataset.attemptId = handoff.attempt_id || ""' in script
    assert 'selectedTask?.client_handoff?.attempt_id !== attemptId' in script
    assert 'cancelButton.dataset.taskId !== taskId' in script
    assert 'id="continue-knowledge-agent"' in html
    assert 'id="view-agent-diagnostics"' in html
    assert 'id="knowledge-agent-prompt"' in html
    assert 'id="knowledge-agent-source-access"' in html
    assert 'id="knowledge-agent-resume-command"' in html
    assert "/agent-diagnostics" in script
    assert "公开推理摘要" in html
    assert "隐藏思维链" in html
    assert "diagnostics.final_output_truncated" in script
    continuation = script[
        script.index("async function continueKnowledgeAgent") : script.index("function refreshKnowledgeGenerationActions")
    ]
    assert "renderCodexTaskPane" in continuation
    assert "/continuations" not in continuation
    assert "backgroundKnowledgeReady" in script
    assert "use_agent" not in script
    assert "agent," in script
    assert "requireKnowledgeAgentSelection" in script
    assert "confirmKnowledgeGeneration" in script
    assert 'interaction_mode: "codex_client"' in script
    assert 'finalProgress.status === "superseded"' in script
    assert 'generation_blocked_reason: "running"' in script
    assert 'blockedReason === "running"' in script
    assert 'blockedReason === "waiting_for_input"' in script
    assert '"completed", "partial", "failed"' in script
    assert "部分完成 · 仅代码事实" in script
    assert "error_summary" in script
    assert 'intent: regenerateTarget ? "regenerate" : "initial"' in script
    assert "await Promise.all([loadKnowledgeWorkflow(), loadScanCatalog()])" in script
    # 目标切换必须立即替换旧正文、主动取消旧GET并仅恢复当前目标/attempt的任务卡。
    assert "let activeKnowledgeTargetController = null" in script
    assert "activeKnowledgeTargetController.abort()" in script
    assert 'textNode("p", `正在读取 ${target.display_name}…`, "loading-skeleton")' in script
    assert "signal: activeKnowledgeTargetController.signal" in script
    assert "knowledgeTargetDetailCache" in script
    invalidation = script[
        script.index("function invalidateKnowledgeReadCaches") : script.index("function knowledgeGenerationAttemptTargetId")
    ]
    assert "knowledgeTargetRequestGeneration += 1" in invalidation
    assert "activeKnowledgeTargetController" in invalidation
    assert "&scan_id=${encodeURIComponent(scanId)}`" in script
    assert "generation_attempts" in script
    assert "attempt.target_id === selectedTargetId" in script
    assert 'let selectedKnowledgeDiagnosticsTaskId = ""' in script
    diagnostics = script[
        script.index("async function viewKnowledgeAgentDiagnostics") : script.index("async function copyKnowledgeAgentResumeCommand")
    ]
    assert "selectedKnowledgeDiagnosticsTaskId" in diagnostics
    assert "selectedKnowledgeDiagnosticsTaskId !== taskId" in diagnostics
    assert 'dataset.targetId !== targetId' in diagnostics
    assert "active_generation_task_id" not in diagnostics
    assert "latest_agent_task" not in diagnostics
    assert 'interaction_mode: agent === "codex" ? "codex_client" : "opentest_stream"' not in script
    codex_confirmation = script[
        script.index("function confirmKnowledgeGeneration") : script.index("function confirmKnowledgeAgentOperation")
    ]
    # 点击Codex生成本身就是单聊天授权，不再追加容易打断多轮客户端交互的费用确认框。
    assert 'if (agent === "codex")' in codex_confirmation
    assert "return true" in codex_confirmation
    assert "window.confirm" not in codex_confirmation
    # 失败/部分/过期attempt以及仍有有效旧知识的目标都必须明确走重新生成语义。
    assert 'const regenerateTarget = retryableTerminal || ["STALE", "FAILED"].includes(selectedKnowledgeStatus)' in script
    assert 'intent: regenerateTarget ? "regenerate" : "initial"' in script
    generation_actions = script[
        script.index("function refreshKnowledgeGenerationActions") : script.index("async function finishKnowledgeGeneration")
    ]
    assert "else if (selectedCategory && regenerateTarget)" in generation_actions
    assert "open-codex-client-thread" in script
    assert "codex://threads/" in script
    assert "使用 Codex 重新生成当前对象知识" in script
    assert 'id="knowledge-generation-profile"' in html
    assert 'value="gpt-5.6-luna|medium"' in html
    assert '<option value="gpt-5.6-luna|low">Luna · Low</option>' in html
    assert 'codex_model: "gpt-5.6-luna"' in script
    assert 'codex_reasoning_effort: "low"' in script
    assert 'value="gpt-5.6-luna|low"' in html
    assert "selectedKnowledgeGenerationProfile" in script
    assert "codex_model: generationProfile.codexModel" in script
    assert "reasoning_effort: generationProfile.reasoningEffort" in script
    assert "最低底线知识当前没有新缺口，可进入测试场景准备" not in script
    assert 'id="generate-case-matrix"' in html
    assert 'id="run-natural-language"' in html
    assert 'id="save-natural-language-case"' in html
    assert 'id="knowledge-task-progress"' in html
    assert "finishKnowledgeGeneration" in script
    assert "helpedAction" in script
    assert "阻塞：${condition.reason}" in script
    assert "renderKnowledgeBackgroundEditor" in script
    assert "saveKnowledgeBackground" in script
    assert "renderBusinessTermEditor" in script
    assert 'id="knowledge-workflow-panel"' in html
    assert 'id="knowledge-agent-select"' in html
    assert 'id="show-all-knowledge-questions"' in html
    assert 'id="knowledge-question-pane"' in html
    assert 'id="codex-task-filter"' in html
    assert 'id="codex-task-list"' in html
    assert "renderCodexTaskPane" in script
    assert "打开 Codex 聊天记录" in script
    assert "在 Codex 中继续" in script
    assert "在 Codex 中回答" in script
    assert 'waiting_for_input: "等待用户回答"' in script
    assert 'failed: "技术失败"' in script
    assert 'payload.state === "manual_required"' in script
    assert "/knowledge/question-cycle" not in script
    assert "/knowledge/question-cycles/" not in script
    target_renderer = script[script.index("function renderKnowledgeTargetDetail") : script.index("async function loadKnowledgeInterview")]
    assert "detail.questions" not in target_renderer
    assert "detail.latest_drafts" not in target_renderer
    assert 'id="knowledge-feedback"' not in html
    assert 'id="knowledge-conversation-history"' in html
    assert 'id="send-knowledge-conversation"' in html
    assert 'id="mvp-create-order-request"' in html
    assert 'id="load-mvp-fixture-summary"' in html
    assert 'id="run-create-order-mvp"' in html
    assert "/knowledge/context" in script
    assert "/knowledge/targets/" in script
    assert "/knowledge/context/narrative" not in script
    assert "/knowledge/context/candidates" in script
    assert "/knowledge/discoveries" not in script
    assert "createBusinessTerm" in script
    assert "createTargetKnowledgeRevision" not in script
    assert "source_refs || []" in script
    assert "/knowledge/revisions" not in script
    assert "/knowledge/conversation-turns" not in script
    assert "/create-order-mvp/fixture" in script
    assert 'bindShortAction("load-mvp-fixture-summary", loadMvpFixtureSummary)' in script
    assert "loadMvpFixtureSummary(scope)" not in script
    assert "[loadMvpFixtureSummary()]" not in script
    assert "/create-order-mvp/plan" in script
    assert "/dsf-operations/canary-fixture" in script
    assert "loadDsfOperationCatalogWithFixture" in script
    assert "includeFixture = false" in script
    assert "/dsf-operations/canary-executions" in script
    assert 'id="dsf-operation-list"' in html
    assert 'id="save-dsf-canary-fixture"' in html
    assert "const operationIds = new Set(" in script
    assert "operationIds.delete(input.dataset.dsfOperationChoice)" in script
    assert "${profile.registry_host}" not in script
    assert "页面不再保留请求正文" in script
    assert "请先在系统配置中新增或切换一个系统" in script
    # 通用知识工作区不得再硬编码Booking.Core术语或默认自然语言示例。
    generic_knowledge = html[html.index('id="workspace-knowledge"') : html.index('id="workspace-regression-cases"')]
    assert all(term not in generic_knowledge for term in ("港币", "EBK", "票机", "收单", "分单系统关系"))
    assert "不要输入 Token、真实订单号、HT/TX" in generic_knowledge
    assert 'id="booking-mvp-section"' in html
    assert 'id="booking-lifecycle-section"' in html
    assert 'id="collapse-sidebar"' in html[html.index('id="sidebar"') : html.index('class="brand"')]
    assert 'id="restore-sidebar"' in html[: html.index('id="sidebar"')]
    assert 'id="global-task-progress"' in html


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
