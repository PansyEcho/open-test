from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "ai_test_platform" / "web"


def test_knowledge_page_contains_chat_tree_skill_and_editor_controls():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    for marker in [
        'id="knowledgeSkillDir"',
        'id="knowledgeChatMessages"',
        'id="knowledgeTree"',
        'id="newKnowledge"',
        'id="confirmKnowledgeWrite"',
        'id="cancelKnowledgeReturn"',
        'id="regenerateKnowledge"',
        'id="editKnowledge"',
        'id="saveKnowledgeEdit"',
        'id="cancelKnowledgeEdit"',
        "请先扫描项目生成 CLI。",
    ]:
        assert marker in html


def test_knowledge_page_keeps_tree_and_content_in_right_panel():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    aside = html[html.index('<aside class="knowledge-side"') : html.index("</aside>", html.index('<aside class="knowledge-side"'))]

    assert 'id="knowledgeTree"' in aside
    assert 'id="knowledgeViewPanel"' in aside
    assert 'id="knowledgeChatPanel"' not in aside


def test_knowledge_frontend_uses_catalog_chat_and_node_apis():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for marker in [
        "loadKnowledgeCatalog",
        "/knowledge/catalog",
        "/knowledge/chat/start",
        "/knowledge/chat",
        "/knowledge/nodes/",
        "renderKnowledgeTree",
        "renderKnowledgeContent",
        "linkKnowledgeContent",
    ]:
        assert marker in app_js


def test_frontend_uses_optional_event_binding_for_removed_legacy_buttons():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function bindClick(" in app_js
    assert '$("generateKnowledge").addEventListener' not in app_js


def test_knowledge_chat_does_not_navigate_back_to_content_page_after_send():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    send_body = app_js[app_js.index("async function sendKnowledgeMessage") : app_js.index("async function newKnowledge")]
    render_content_body = app_js[app_js.index("function renderKnowledgeContent") : app_js.index("function markdownToHtml")]
    render_chat_body = app_js[app_js.index("function renderKnowledgeChat") : app_js.index("async function sendKnowledgeMessage")]

    assert 'renderKnowledgeContent(payload.result.node)' not in send_body
    assert '$("knowledgeChatPanel").classList.add("hidden")' not in render_content_body
    assert '$("knowledgeViewPanel").classList.add("hidden")' not in render_chat_body


def test_knowledge_chat_uses_draft_then_confirm_write_endpoint():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    send_body = app_js[app_js.index("async function sendKnowledgeMessage") : app_js.index("async function newKnowledge")]
    confirm_body = app_js[app_js.index("async function confirmKnowledgeWrite") : app_js.index("function cancelKnowledgeReturn")]

    assert "renderKnowledgeDraft" in app_js
    assert "payload.result.draft_content" in send_body
    assert "/knowledge/chat/confirm" in confirm_body
    assert "session_id: state.knowledge.session.session_id" in confirm_body
    assert "content: $(\"knowledgeEditor\").value" in confirm_body
    assert "知识内容已确认写入当前知识库" in confirm_body


def test_knowledge_chat_waits_for_agent_reply_and_clears_input_immediately():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    send_body = app_js[app_js.index("async function sendKnowledgeMessage") : app_js.index("async function newKnowledge")]

    assert "等待 Agent 回复..." in send_body
    assert "正在通过本地 Agent 生成知识" not in send_body
    assert 'showNotice(payload.result.reply' not in send_body
    assert send_body.index('knowledgeMessage").value = ""') < send_body.index("/knowledge/chat")


def test_knowledge_tree_can_collapse_and_chat_history_is_visible_per_node():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="knowledgeChatHistory"' in html
    assert "collapsedGroups" in app_js
    assert "toggleKnowledgeGroup" in app_js
    assert "loadKnowledgeChatHistory" in app_js
    assert "/knowledge/chats" in app_js


def test_knowledge_draft_has_original_snapshot_tab():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'data-knowledge-tab="draft"' in html
    assert 'data-knowledge-tab="original"' in html
    assert 'id="knowledgeOriginal"' in html
    assert "setKnowledgeTab" in app_js
    assert "原先快照" in html


def test_knowledge_edit_and_chat_have_cancel_return_handlers():
    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "function cancelKnowledgeEdit()" in app_js
    assert "async function confirmKnowledgeWrite()" in app_js
    assert "function cancelKnowledgeReturn()" in app_js
    assert 'bindClick("cancelKnowledgeEdit"' in app_js
    assert 'bindClick("confirmKnowledgeWrite"' in app_js
    assert 'bindClick("cancelKnowledgeReturn"' in app_js
