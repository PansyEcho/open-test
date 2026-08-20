"""在FastAPI依赖不可用时也能验证V2控制台静态安全契约。"""

from __future__ import annotations

from pathlib import Path


def test_console_static_client_uses_only_v2_routes_and_safe_rendering() -> None:
    """静态客户端应集中使用V2前缀，并通过textContent展示业务响应。"""

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "OpenTest V2 Console" in html
    assert 'const API_ROOT = "/api/v2"' in script
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
    assert "/knowledge/generation-batches" in script
    assert "/case-generations" in script
    assert "/natural-language-tests/previews" in script
    assert "preview-natural-language\" disabled" not in html
    assert 'id="generate-all-knowledge"' in html
    assert 'id="generate-case-matrix"' in html
    assert 'id="run-natural-language"' in html
    assert 'id="save-natural-language-case"' in html
    assert 'id="knowledge-task-progress"' in html
    assert "finishKnowledgeGeneration" in script
    assert "helpedAction" in script
    assert "阻塞：${condition.reason}" in script
    assert 'id="knowledge-background-editor"' in html
    assert 'id="knowledge-question-pane"' in html
    assert 'id="question-scope-filter"' in html
    assert 'id="question-priority-filter"' in html
    assert 'id="question-category-filter"' in html
    assert "renderKnowledgeQuestions" in script
    target_renderer = script[script.index("function renderKnowledgeTargetDetail") : script.index("async function loadKnowledgeInterview")]
    assert "detail.questions" not in target_renderer
    assert 'id="knowledge-feedback"' in html
    assert 'id="mvp-create-order-request"' in html
    assert 'id="run-create-order-mvp"' in html
    assert "/knowledge/context" in script
    assert "/knowledge/targets/" in script
    assert "/knowledge/discoveries" in script
    assert "createKnowledgeCandidate" in script
    assert "createTargetKnowledgeRevision" in script
    assert "source_refs || []" in script
    assert "/knowledge/revisions" in script
    assert "/create-order-mvp/fixture" in script
    assert "/create-order-mvp/plan" in script
    assert "/dsf-operations/canary-fixture" in script
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
    assert all(term not in generic_knowledge for term in ("港币", "EBK", "票机", "收单", "HT", "分单系统关系"))
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
    assert 'if (progress.status !== "completed")' in task_progress
    assert "throw new Error(taskPayload.task.error" in task_progress
    assert "扫描任务执行成功" not in task_progress
