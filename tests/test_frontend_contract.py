from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "ai_test_platform" / "web"


def test_frontend_has_global_notice_for_actions():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="globalNotice"' in html
    assert "function showNotice(" in app_js
    assert "showNotice(message" in app_js


def test_frontend_bootstraps_existing_project_after_reload():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "async function loadExistingProject()" in app_js
    assert 'api("/api/projects")' in app_js
    assert "loadExistingProject();" in app_js


def test_generate_buttons_render_visible_progress_in_current_panel():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "正在生成知识库草稿" in app_js
    assert "正在生成 CLI 草稿" in app_js
    assert "正在为当前知识节点生成 Case" in app_js


def test_frontend_defaults_to_real_local_agent_chat():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    select_block = html[html.index('id="executeAgent"') : html.index("</select>", html.index('id="executeAgent"'))]
    assert '<option value="true" selected>开启（调用 Codex/Claude CLI）</option>' in select_block
    assert "force_agent: true" in app_js


def test_cli_tools_render_as_catalog_tree_not_raw_json_dump():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="cliTree"' in html
    assert 'id="cliSearch"' in html
    assert "renderCliCatalog" in app_js
    assert "loadCliCatalog" in app_js
    assert "$(\"cliTools\").textContent = pretty(payload.version)" not in app_js


def test_case_page_has_knowledge_tree_list_flow_and_json_editor():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for element_id in [
        "caseKnowledgeTree",
        "caseOverview",
        "caseList",
        "caseSummary",
        "caseFlow",
        "caseJsonEditor",
        "addCase",
        "saveCaseJson",
    ]:
        assert f'id="{element_id}"' in html

    for function_name in [
        "loadCaseCatalog",
        "renderCaseCatalog",
        "selectCaseNode",
        "renderCaseList",
        "openCaseDetail",
        "renderCaseFlow",
        "saveCaseJson",
        "addCase",
    ]:
        assert function_name in app_js

    assert "/cases/catalog" in app_js
    assert "/cases/detail/" in app_js
