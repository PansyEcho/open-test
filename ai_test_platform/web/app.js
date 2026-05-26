const state = {
  project: null,
  drafts: {},
  versions: {},
  snapshot: null,
  run: null,
  knowledge: {
    catalog: null,
    selectedNodeId: "project_background",
    session: null,
    mode: "chat",
    regenerating: false,
    draftContent: "",
    originalContent: "",
    collapsedGroups: {},
    chatHistories: {},
  },
  cli: {
    catalog: null,
    collapsedGroups: {},
  },
};

const $ = (id) => document.getElementById(id);

function showNotice(message, kind = "idle") {
  const notice = $("globalNotice");
  notice.textContent = message;
  notice.className = `notice ${kind}`;
}

function bindClick(id, handler) {
  const element = $(id);
  if (element) element.addEventListener("click", handler);
}

function log(message, data) {
  const text = data ? `${message}\n${JSON.stringify(data, null, 2)}` : message;
  $("statusLog").textContent = text;
  showNotice(message, data && data.error ? "error" : "ok");
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function sanitizeKnowledgeText(value) {
  return String(value ?? "").replace(/<!--\s*kb:[\s\S]*?-->\s*/gi, "").trim();
}

async function api(path, options = {}) {
  const init = { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } };
  if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  const response = await fetch(path, init);
  const payload = await response.json();
  if (!response.ok || payload.success === false) throw new Error(payload.error || response.statusText);
  return payload;
}

function projectPayload() {
  return {
    name: $("projectName").value,
    project_key: $("projectKey").value,
    source_path: $("sourcePath").value,
    agent_profile: $("agentProfile").value,
    execute_agent: $("executeAgent").value === "true",
    skill_dir: $("skillDir").value,
    env_name: $("envName").value,
    facade_http_prefix: $("facadePrefix").value,
    headers: { LABRADOR_TRACE_LOG: "true" },
    job_rules: [
      {
        package_name: $("jobPackage").value,
        trigger_mode: "http",
        http_url_prefix: $("jobPrefix").value,
        enabled: true,
      },
    ],
  };
}

function updateMetrics() {
  $("metricProject").textContent = state.project ? "1" : "0";
  const active = state.project?.active_versions || {};
  $("metricKb").textContent = active.knowledge?.version_key || "-";
  $("metricCli").textContent = active.cli?.version_key || "-";
  $("metricCase").textContent = active.case?.version_key || "-";
  $("metricSnapshot").textContent = state.snapshot?.snapshot_id || state.project?.active_snapshot_id || "-";
  if (state.run) {
    $("metricPassed").textContent = state.run.passed_count;
    $("metricFailed").textContent = state.run.failed_count;
    $("metricLlm").textContent = state.run.llm_invocations;
  }
  const stages = {
    project: Boolean(state.project),
    knowledge: Boolean(active.knowledge),
    cli: Boolean(active.cli),
    case: Boolean(active.case),
    snapshot: Boolean(state.snapshot || state.project?.active_snapshot_id),
    run: Boolean(state.run),
  };
  document.querySelectorAll(".stagebar div").forEach((node) => {
    const done = stages[node.dataset.stage];
    node.classList.toggle("done", done);
    node.classList.toggle("failed", node.dataset.stage === "run" && state.run?.failed_count > 0);
  });
  renderDraftQueue();
}

function renderDraftQueue() {
  const queue = $("draftQueue");
  const drafts = Object.values(state.drafts).filter(Boolean);
  if (!drafts.length) {
    queue.className = "queue empty";
    queue.textContent = "暂无待确认草稿";
    return;
  }
  queue.className = "queue";
  queue.innerHTML = drafts
    .map((draft) => `<div class="item"><strong>${draft.artifact_type} · ${draft.draft_id}</strong><span class="tag warn">${draft.status}</span>${draft.summary}</div>`)
    .join("");
}

async function refreshProject() {
  if (!state.project) return;
  const payload = await api(`/api/projects/${state.project.id}`);
  state.project = payload.project;
  applyProjectToForm(state.project);
  $("projectJson").textContent = pretty(state.project);
  updateMetrics();
}

async function loadExistingProject() {
  try {
    const payload = await api("/api/projects");
    const projects = payload.projects || [];
    if (!projects.length) {
      showNotice("未发现已配置项目，请先在“项目配置”中新建项目。");
      return;
    }
    state.project = projects[projects.length - 1];
    applyProjectToForm(state.project);
    $("projectJson").textContent = pretty(state.project);
    $("knowledgeSkillDir").value = state.project.knowledge_skill_dir || state.project.skill_dir || $("knowledgeSkillDir").value;
    showNotice(`已加载项目：${state.project.name}`, "ok");
    updateMetrics();
    await loadKnowledgeCatalog();
  } catch (error) {
    showNotice(`加载已有项目失败：${error.message}`, "error");
  }
}

function applyProjectToForm(project) {
  if (!project) return;
  $("projectName").value = project.name || "";
  $("projectKey").value = project.project_key || "";
  $("sourcePath").value = project.source_path || "";
  $("agentProfile").value = project.agent_profile || "codex-local";
  $("executeAgent").value = project.execute_agent ? "true" : "false";
  $("skillDir").value = project.skill_dir || "";
  $("envName").value = project.env_name || "test";
  $("facadePrefix").value = project.facade_http_prefix || "";
  const firstRule = (project.job_rules || [])[0] || {};
  $("jobPackage").value = firstRule.package_name || "";
  $("jobPrefix").value = firstRule.http_url_prefix || "";
}

async function detectAgents() {
  const payload = await api("/api/agents/detect");
  $("agentList").className = "list";
  $("agentList").innerHTML = payload.agents
    .map((agent) => `<div class="item"><strong>${agent.display_name}</strong><span class="tag ${agent.available ? "ok" : "fail"}">${agent.status}</span>${agent.command_path || agent.command}</div>`)
    .join("");
  log("Agent 检测完成", payload.agents);
}

async function createProject() {
  const payload = await api("/api/projects", { method: "POST", body: projectPayload() });
  state.project = payload.project;
  $("knowledgeSkillDir").value = state.project.knowledge_skill_dir || state.project.skill_dir || $("knowledgeSkillDir").value;
  $("projectJson").textContent = pretty(state.project);
  log("项目已创建", payload.project);
  updateMetrics();
  await loadKnowledgeCatalog();
}

async function generateKnowledge() {
  ensureProject();
  $("knowledgeDraft").textContent = "正在生成知识库草稿...";
  $("knowledgeDiff").textContent = "等待生成完成后展示 diff。";
  const payload = await api(`/api/projects/${state.project.id}/knowledge/generate`, {
    method: "POST",
    body: { message: $("knowledgeMessage").value },
  });
  state.drafts.knowledge = payload.draft;
  $("knowledgeDraft").textContent = pretty(payload.draft);
  $("knowledgeDiff").textContent = pretty(payload.draft.diff);
  log("知识库草稿已生成", payload.draft);
  updateMetrics();
}

async function generateCli() {
  ensureProject();
  $("cliDraft").textContent = "正在生成 CLI 草稿，这一步会调用本机 scriptgen 扫描 Java 项目。";
  $("cliTree").textContent = "生成完成后展示工具目录。";
  const payload = await api(`/api/projects/${state.project.id}/cli/build-all`, { method: "POST", body: { types: "facade,job" } });
  state.drafts.cli = payload.draft;
  renderCliDraft(payload.draft);
  await loadCliCatalog(payload.draft.draft_id);
  log("CLI 草稿已生成", { summary: payload.draft.summary, draft_id: payload.draft.draft_id });
  updateMetrics();
}

function renderCliDraft(draft) {
  const scriptgen = draft.scriptgen || {};
  $("cliDraft").innerHTML = `
    <div class="summary-line"><strong>${escapeHtml(draft.summary || "CLI 草稿已生成")}</strong></div>
    <div class="summary-meta">草稿：${escapeHtml(draft.draft_id || "-")}</div>
    <div class="summary-meta">状态：${escapeHtml(draft.status || "draft")} · scriptgen：${scriptgen.success ? "成功" : "需查看日志"}</div>
  `;
}

async function loadCliCatalog(draftId = "") {
  if (!state.project) return;
  const suffix = draftId ? `?draft_id=${encodeURIComponent(draftId)}` : "";
  const payload = await api(`/api/projects/${state.project.id}/cli/catalog${suffix}`);
  state.cli.catalog = payload.catalog;
  if (!draftId && state.project?.active_versions?.cli) {
    const activeCli = state.project.active_versions.cli;
    $("cliDraft").innerHTML = `<div class="summary-line"><strong>当前已确认：${escapeHtml(activeCli.version_key)}</strong></div><div class="summary-meta">${escapeHtml(activeCli.path || "")}</div>`;
  }
  renderCliCatalog();
}

function renderCliCatalog() {
  const catalog = state.cli.catalog;
  const root = $("cliTree");
  if (!catalog || !catalog.ready) {
    $("cliToolCount").textContent = "0 tools";
    root.textContent = catalog?.empty_message || "等待生成或确认 CLI 后查看。";
    return;
  }
  $("cliToolCount").textContent = `${catalog.tool_count} tools`;
  const search = ($("cliSearch").value || "").trim();
  root.innerHTML = catalog.tree
    .map((group) => {
      const groupId = group.id;
      const collapsed = Boolean(state.cli.collapsedGroups[groupId]) && !search;
      const children = (group.children || [])
        .filter((item) => !search || item.title.includes(search) || (item.script_path || "").includes(search))
        .map((item) => `<div class="tree-node cli-tool-node">
          <span>▧ ${escapeHtml(item.title)}</span>
          <span class="tool-script">${escapeHtml(item.script_path || item.source_id || "")}</span>
        </div>`)
        .join("");
      if (!children) return "";
      return `<div class="tree-group">
        <button class="tree-group-title" data-cli-group-id="${escapeHtml(groupId)}">${collapsed ? "›" : "⌄"} ${escapeHtml(group.title)}</button>
        <div class="${collapsed ? "hidden" : ""}">${children}</div>
      </div>`;
    })
    .join("");
}

function toggleCliGroup(groupId) {
  state.cli.collapsedGroups[groupId] = !state.cli.collapsedGroups[groupId];
  renderCliCatalog();
}

async function saveKnowledgeSkill() {
  ensureProject();
  const payload = await api(`/api/projects/${state.project.id}/skills/knowledge`, {
    method: "POST",
    body: { skill_dir: $("knowledgeSkillDir").value },
  });
  state.project.knowledge_skill_dir = payload.skill.skill_dir;
  state.project.knowledge_skill_hash = payload.skill.skill_hash;
  showNotice(`知识库生成 Skill 已保存：${payload.skill.skill_hash}`, "ok");
  await refreshProject();
  await loadKnowledgeCatalog();
}

async function loadKnowledgeCatalog(options = {}) {
  if (!state.project) return;
  const shouldSelect = options.select !== false;
  const payload = await api(`/api/projects/${state.project.id}/knowledge/catalog`);
  state.knowledge.catalog = payload.catalog;
  $("knowledgeHint").textContent = payload.catalog.ready
    ? "请选择右侧知识节点，通过聊天逐个生成或查看内容。"
    : payload.catalog.empty_message;
  $("knowledgeSkillDir").value = payload.catalog.knowledge_skill_dir || $("knowledgeSkillDir").value;
  renderKnowledgeTree();
  if (shouldSelect) {
    await selectKnowledgeNode(state.knowledge.selectedNodeId || "project_background");
  }
}

function renderKnowledgeTree() {
  const catalog = state.knowledge.catalog;
  const root = $("knowledgeTree");
  if (!catalog || !catalog.ready) {
    root.textContent = catalog?.empty_message || "请先扫描项目生成 CLI。";
    return;
  }
  const search = ($("knowledgeSearch").value || "").trim();
  root.innerHTML = catalog.tree
    .map((group) => {
      if (group.children) {
        const groupId = group.id;
        const collapsed = Boolean(state.knowledge.collapsedGroups[groupId]) && !search;
        const children = group.children
          .filter((node) => !search || node.title.includes(search))
          .map((node) => knowledgeNodeHtml(node))
          .join("");
        if (!children) return "";
        return `<div class="tree-group">
          <button class="tree-group-title" data-knowledge-group-id="${escapeHtml(groupId)}">${collapsed ? "›" : "⌄"} ${escapeHtml(group.title)}</button>
          <div class="${collapsed ? "hidden" : ""}">${children}</div>
        </div>`;
      }
      if (search && !group.title.includes(search)) return "";
      return `<div class="tree-group">${knowledgeNodeHtml(group)}</div>`;
    })
    .join("");
}

function toggleKnowledgeGroup(groupId) {
  state.knowledge.collapsedGroups[groupId] = !state.knowledge.collapsedGroups[groupId];
  renderKnowledgeTree();
}

function knowledgeNodeHtml(node) {
  const active = node.id === state.knowledge.selectedNodeId ? " active" : "";
  const badgeClass = node.status === "generated" ? "ok" : "missing";
  return `<div class="tree-node${active}" data-node-id="${escapeHtml(node.id)}">
    <span>▧ ${escapeHtml(node.title)}</span>
    <span class="badge ${badgeClass}">${node.status_label}</span>
  </div>`;
}

async function selectKnowledgeNode(nodeId, options = {}) {
  if (!state.project) return;
  const previousNodeId = state.knowledge.selectedNodeId;
  state.knowledge.selectedNodeId = nodeId;
  renderKnowledgeTree();
  const payload = await api(`/api/projects/${state.project.id}/knowledge/nodes/${encodeURIComponent(nodeId)}`);
  renderKnowledgeContent(payload.node);
  await loadKnowledgeChatHistory(nodeId);
  if (options.startChat && previousNodeId !== nodeId) {
    await startKnowledgeChat(nodeId, false);
  }
}

function renderKnowledgeContent(node) {
  state.knowledge.mode = "view";
  state.knowledge.draftContent = "";
  state.knowledge.originalContent = node.raw_markdown || node.content || "";
  $("knowledgeViewPanel").classList.remove("hidden");
  $("knowledgeNodeTitle").textContent = node.title || node.id;
  $("knowledgeBreadcrumb").textContent = `知识库 / ${node.category || "项目背景"} / ${node.title || node.id}`;
  $("knowledgeNodeMeta").textContent = `${node.status_label || "未生成"}${node.updated_at ? ` · 最近更新 ${node.updated_at}` : ""}`;
  $("knowledgeDependencies").innerHTML = (node.dependencies || [])
    .map((item) => `<button class="knowledge-link" data-node-id="${escapeHtml(item.id)}">${escapeHtml(item.title)}</button>`)
    .join("");
  const content = node.content || node.empty_message || "当前知识还未生成。点击“重新生成”或返回聊天补充背景后生成。";
  $("knowledgeContent").innerHTML = linkKnowledgeContent(markdownToHtml(content));
  $("knowledgeEditor").value = node.raw_markdown || node.content || "";
  $("knowledgeOriginal").innerHTML = linkKnowledgeContent(markdownToHtml(node.raw_markdown || node.content || "暂无原先快照。"));
  $("knowledgeContent").classList.remove("hidden");
  $("knowledgeEditor").classList.add("hidden");
  $("knowledgeOriginal").classList.add("hidden");
  setKnowledgeTab("draft");
  $("saveKnowledgeEdit").classList.add("hidden");
  $("cancelKnowledgeEdit").classList.add("hidden");
  $("editKnowledge").classList.remove("hidden");
  $("regenerateKnowledge").classList.remove("hidden");
  $("cancelRegenerate").classList.toggle("hidden", !state.knowledge.regenerating);
}

function renderKnowledgeDraft(node, draftContent) {
  if (!draftContent) return;
  state.knowledge.draftContent = draftContent;
  state.knowledge.originalContent = node.raw_markdown || node.content || "";
  $("knowledgeViewPanel").classList.remove("hidden");
  $("knowledgeNodeTitle").textContent = node.title || node.id;
  $("knowledgeBreadcrumb").textContent = `知识库 / ${node.category || "项目背景"} / ${node.title || node.id}`;
  $("knowledgeNodeMeta").textContent = "聊天草稿待确认写入";
  $("knowledgeDependencies").innerHTML = (node.dependencies || [])
    .map((item) => `<button class="knowledge-link" data-node-id="${escapeHtml(item.id)}">${escapeHtml(item.title)}</button>`)
    .join("");
  $("knowledgeContent").innerHTML = linkKnowledgeContent(markdownToHtml(draftContent));
  $("knowledgeEditor").value = draftContent;
  $("knowledgeOriginal").innerHTML = linkKnowledgeContent(markdownToHtml(state.knowledge.originalContent || "暂无原先快照。"));
  $("knowledgeContent").classList.add("hidden");
  $("knowledgeEditor").classList.remove("hidden");
  $("knowledgeOriginal").classList.add("hidden");
  setKnowledgeTab("draft");
  $("saveKnowledgeEdit").classList.add("hidden");
  $("cancelKnowledgeEdit").classList.remove("hidden");
  $("editKnowledge").classList.add("hidden");
  $("regenerateKnowledge").classList.add("hidden");
  $("cancelRegenerate").classList.toggle("hidden", !state.knowledge.regenerating);
}

function setKnowledgeTab(tabName) {
  document.querySelectorAll("[data-knowledge-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.knowledgeTab === tabName);
  });
  const showingEditor = Boolean(state.knowledge.draftContent) || !$("saveKnowledgeEdit").classList.contains("hidden");
  $("knowledgeOriginal").classList.toggle("hidden", tabName !== "original");
  if (tabName === "original") {
    $("knowledgeContent").classList.add("hidden");
    $("knowledgeEditor").classList.add("hidden");
    return;
  }
  $("knowledgeContent").classList.toggle("hidden", showingEditor);
  $("knowledgeEditor").classList.toggle("hidden", !showingEditor);
}

function markdownToHtml(markdown) {
  return escapeHtml(sanitizeKnowledgeText(markdown))
    .replace(/^# (.*)$/gm, "<h1>$1</h1>")
    .replace(/^## (.*)$/gm, "<h2>$1</h2>")
    .replace(/^### (.*)$/gm, "<h3>$1</h3>")
    .replace(/^- (.*)$/gm, "<li>$1</li>")
    .replace(/\n\n/g, "<br><br>");
}

function linkKnowledgeContent(html) {
  return html.replace(/\[\[([^\]]+)]]/g, (_, title) => {
    const node = findNodeByTitle(title);
    return node ? `<button class="knowledge-link" data-node-id="${escapeHtml(node.id)}">${escapeHtml(title)}</button>` : `<strong>${escapeHtml(title)}</strong>`;
  });
}

function findNodeByTitle(title) {
  const groups = state.knowledge.catalog?.tree || [];
  for (const group of groups) {
    if (group.title === title) return group;
    for (const child of group.children || []) {
      if (child.title === title) return child;
    }
  }
  return null;
}

async function startKnowledgeChat(nodeId = state.knowledge.selectedNodeId || "project_background", regenerate = false) {
  ensureProject();
  const payload = await api(`/api/projects/${state.project.id}/knowledge/chat/start`, {
    method: "POST",
    body: { node_id: nodeId, regenerate },
  });
  state.knowledge.session = payload.session;
  state.knowledge.selectedNodeId = nodeId;
  state.knowledge.regenerating = regenerate;
  $("knowledgeMessage").value = nodeId === "__new__" ? "" : "你好";
  renderKnowledgeChat();
  await loadKnowledgeChatHistory(nodeId);
}

function renderKnowledgeChat() {
  state.knowledge.mode = "chat";
  $("knowledgeChatPanel").classList.remove("hidden");
  $("cancelRegenerate").classList.toggle("hidden", !state.knowledge.regenerating);
  const messages = state.knowledge.session?.messages || [
    { role: "assistant", content: "请先扫描项目生成 CLI，然后选择知识节点开始生成。" },
  ];
  $("knowledgeChatMessages").innerHTML = messages
    .map((message) => {
      const user = message.role === "user";
      return `<div class="chat-msg ${user ? "user" : "assistant"}">
        <div class="chat-avatar">${user ? "你" : "AI"}</div>
        <div class="chat-bubble">${escapeHtml(sanitizeKnowledgeText(message.content))}</div>
      </div>`;
    })
    .join("");
  $("knowledgeChatMessages").scrollTop = $("knowledgeChatMessages").scrollHeight;
}

async function loadKnowledgeChatHistory(nodeId = state.knowledge.selectedNodeId || "project_background") {
  if (!state.project) return;
  const payload = await api(`/api/projects/${state.project.id}/knowledge/chats?node_id=${encodeURIComponent(nodeId)}`);
  state.knowledge.chatHistories[nodeId] = payload.chats || [];
  renderKnowledgeChatHistory(nodeId);
}

function renderKnowledgeChatHistory(nodeId = state.knowledge.selectedNodeId || "project_background") {
  const root = $("knowledgeChatHistory");
  const chats = state.knowledge.chatHistories[nodeId] || [];
  if (!chats.length) {
    root.className = "history-list empty";
    root.textContent = "暂无历史聊天";
    return;
  }
  root.className = "history-list";
  root.innerHTML = chats
    .map((chat) => `<button class="history-item" data-session-id="${escapeHtml(chat.session_id)}">
      <strong>${escapeHtml(chat.updated_at || chat.created_at || chat.session_id)}</strong>
      <span>${escapeHtml(sanitizeKnowledgeText(chat.preview || "空会话"))}</span>
      <em>${chat.message_count} 条${chat.has_draft ? " · 有草稿" : ""}</em>
    </button>`)
    .join("");
}

async function loadKnowledgeChatSession(sessionId) {
  ensureProject();
  const payload = await api(`/api/projects/${state.project.id}/knowledge/chats/${encodeURIComponent(sessionId)}`);
  state.knowledge.session = payload.session;
  state.knowledge.selectedNodeId = payload.session.node_id || state.knowledge.selectedNodeId;
  state.knowledge.draftContent = payload.session.draft_content || "";
  renderKnowledgeChat();
  if (payload.session.draft_content) {
    const nodePayload = await api(`/api/projects/${state.project.id}/knowledge/nodes/${encodeURIComponent(payload.session.draft_node_id || payload.session.node_id)}`);
    renderKnowledgeDraft(nodePayload.node, payload.session.draft_content);
  }
}

async function sendKnowledgeMessage() {
  ensureProject();
  if (!state.knowledge.session) {
    await startKnowledgeChat(state.knowledge.selectedNodeId || "project_background", false);
  }
  const message = $("knowledgeMessage").value.trim();
  if (!message) {
    showNotice("请输入需要补充的业务背景或知识点。", "error");
    return;
  }
  const currentNodeId = state.knowledge.session.node_id || state.knowledge.selectedNodeId || "project_background";
  $("knowledgeMessage").value = "";
  const localMessages = [...(state.knowledge.session.messages || []), { role: "user", content: message }];
  state.knowledge.session.messages = localMessages.concat([{ role: "assistant", content: "等待 Agent 回复..." }]);
  showNotice("等待 Agent 回复...", "busy");
  renderKnowledgeChat();
  const payload = await api(`/api/projects/${state.project.id}/knowledge/chat`, {
    method: "POST",
    body: { session_id: state.knowledge.session.session_id, node_id: currentNodeId, message, force_agent: true },
  });
  state.knowledge.session = payload.result.session;
  state.knowledge.selectedNodeId = payload.result.node.id;
  const agentFailed = payload.result.agent_run?.status === "failed";
  const notice = agentFailed
    ? "本地 Agent 调用失败，详情已保留在聊天记录中。"
    : (payload.result.draft_content ? "Agent 已生成右侧草稿，请对照原先快照后确认写入。" : "Agent 已回复，请继续对话。");
  showNotice(notice, agentFailed ? "error" : "ok");
  renderKnowledgeChat();
  await refreshProject();
  await loadKnowledgeCatalog({ select: false });
  await loadKnowledgeChatHistory(state.knowledge.selectedNodeId);
  if (payload.result.draft_content) {
    renderKnowledgeDraft(payload.result.node, payload.result.draft_content);
  }
}

async function newKnowledge() {
  await startKnowledgeChat("__new__", false);
  $("knowledgeMessage").value = "新增一个关于退款前置校验的知识。";
}

async function regenerateKnowledge() {
  await startKnowledgeChat(state.knowledge.selectedNodeId || "project_background", true);
}

function editKnowledge() {
  $("knowledgeContent").classList.add("hidden");
  $("knowledgeEditor").classList.remove("hidden");
  $("knowledgeOriginal").classList.add("hidden");
  setKnowledgeTab("draft");
  $("saveKnowledgeEdit").classList.remove("hidden");
  $("cancelKnowledgeEdit").classList.remove("hidden");
  $("editKnowledge").classList.add("hidden");
  $("regenerateKnowledge").classList.add("hidden");
}

async function saveKnowledgeEdit() {
  ensureProject();
  const nodeId = state.knowledge.selectedNodeId || "project_background";
  const payload = await api(`/api/projects/${state.project.id}/knowledge/nodes/${encodeURIComponent(nodeId)}`, {
    method: "POST",
    body: { content: $("knowledgeEditor").value },
  });
  showNotice("知识库人工编辑已保存", "ok");
  await loadKnowledgeCatalog();
  renderKnowledgeContent(payload.node);
}

function cancelKnowledgeEdit() {
  $("knowledgeEditor").classList.add("hidden");
  $("knowledgeContent").classList.remove("hidden");
  $("knowledgeOriginal").classList.add("hidden");
  setKnowledgeTab("draft");
  $("saveKnowledgeEdit").classList.add("hidden");
  $("cancelKnowledgeEdit").classList.add("hidden");
  $("editKnowledge").classList.remove("hidden");
  $("regenerateKnowledge").classList.remove("hidden");
  showNotice("已取消人工编辑，返回知识预览。", "idle");
}

async function confirmKnowledgeWrite() {
  ensureProject();
  if (state.knowledge.draftContent && state.knowledge.session?.session_id && !$("knowledgeEditor").classList.contains("hidden")) {
    const payload = await api(`/api/projects/${state.project.id}/knowledge/chat/confirm`, {
      method: "POST",
      body: {
        session_id: state.knowledge.session.session_id,
        node_id: state.knowledge.selectedNodeId || state.knowledge.session.node_id,
        content: $("knowledgeEditor").value,
        edited_manually: true,
      },
    });
    state.knowledge.draftContent = "";
    state.knowledge.session = payload.result.session;
    showNotice("知识内容已确认写入当前知识库。", "ok");
    await refreshProject();
    await loadKnowledgeCatalog({ select: false });
    await loadKnowledgeChatHistory(payload.result.node.id);
    renderKnowledgeContent(payload.result.node);
    return;
  }
  if (!$("knowledgeEditor").classList.contains("hidden")) {
    await saveKnowledgeEdit();
    return;
  }
  showNotice("知识内容已确认写入当前知识库。", "ok");
  await loadKnowledgeCatalog({ select: false });
}

function cancelKnowledgeReturn() {
  state.knowledge.regenerating = false;
  $("knowledgeMessage").value = "";
  renderKnowledgeChat();
  if (!$("knowledgeEditor").classList.contains("hidden")) {
    cancelKnowledgeEdit();
  } else {
    showNotice("已取消当前聊天操作，右侧保留当前知识预览。", "idle");
  }
}

async function cancelRegenerate() {
  state.knowledge.regenerating = false;
  cancelKnowledgeReturn();
}

async function generateCases() {
  ensureProject();
  $("caseDraft").textContent = "正在生成 Case 草稿...";
  $("caseBinding").textContent = pretty(state.project.active_versions || {});
  const payload = await api(`/api/projects/${state.project.id}/cases/generate`, { method: "POST", body: { scope: "main-flow" } });
  state.drafts.case = payload.draft;
  $("caseDraft").textContent = pretty(payload.draft);
  $("caseBinding").textContent = pretty(state.project.active_versions);
  log("Case 草稿已生成", payload.draft);
  updateMetrics();
}

async function confirmDraft(kind) {
  ensureProject();
  const draft = state.drafts[kind];
  if (!draft) throw new Error(`没有可确认的 ${kind} 草稿`);
  const payload = await api(`/api/projects/${state.project.id}/drafts/${draft.draft_id}/confirm`, { method: "POST", body: {} });
  state.versions[kind] = payload.version;
  state.drafts[kind] = null;
  await refreshProject();
  if (kind === "cli") {
    $("cliDraft").innerHTML = `<div class="summary-line"><strong>CLI 已确认：${escapeHtml(payload.version.version_key)}</strong></div><div class="summary-meta">${escapeHtml(payload.version.path)}</div>`;
    await loadCliCatalog();
  }
  log(`${kind} 已确认`, { version_key: payload.version.version_key, artifact_type: payload.version.artifact_type });
}

async function confirmAll() {
  for (const kind of ["knowledge", "cli", "case"]) {
    if (state.drafts[kind]) await confirmDraft(kind);
  }
}

async function createSnapshot() {
  ensureProject();
  const payload = await api(`/api/projects/${state.project.id}/snapshots`, { method: "POST", body: {} });
  state.snapshot = payload.snapshot;
  await refreshProject();
  log("Snapshot 已创建", payload.snapshot);
}

async function runRegression() {
  ensureProject();
  const payload = await api(`/api/projects/${state.project.id}/runs`, {
    method: "POST",
    body: { snapshot_id: state.snapshot?.snapshot_id || state.project.active_snapshot_id },
  });
  state.run = payload.run;
  renderRun(payload.run);
  log("回归执行完成", payload.run);
  updateMetrics();
}

function renderRun(run) {
  const cases = $("runCases");
  cases.className = "list";
  cases.innerHTML = run.cases
    .map((item) => `<div class="item"><strong>${item.case_name}</strong><span class="tag ${item.status === "passed" ? "ok" : "fail"}">${item.status}</span>${item.steps.length} steps</div>`)
    .join("");
  const failedCase = run.cases.find((item) => item.status === "failed");
  const failedStep = failedCase?.steps.find((item) => item.status === "failed");
  $("failureDetail").textContent = failedStep
    ? pretty({
        case: failedCase.case_name,
        step: failedStep.step_name,
        command: failedStep.command,
        stdout_json: failedStep.stdout_json,
        assertion_diff: failedStep.assertion_result.diffs,
        binding: run.binding,
      })
    : "无失败";
}

async function runMvp() {
  await withBusy($("runMvp"), async () => {
    await detectAgents();
    await createProject();
    await generateCli();
    await confirmDraft("cli");
    await loadKnowledgeCatalog();
    await startKnowledgeChat("project_background", false);
    $("knowledgeMessage").value = "请先生成订单系统的项目背景与核心交易知识。";
    await sendKnowledgeMessage();
    await startKnowledgeChat("facade.trade.create_order", false);
    $("knowledgeMessage").value = "请生成创建订单知识，并关联项目背景和计算最晚出票时间。";
    await sendKnowledgeMessage();
    await generateCases();
    await confirmDraft("case");
    await createSnapshot();
    await runRegression();
  });
}

function ensureProject() {
  if (!state.project) throw new Error("请先创建项目");
}

async function withBusy(button, fn) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "处理中...";
  showNotice(`${label} 处理中...`, "busy");
  try {
    await fn();
  } catch (error) {
    log(`操作失败：${error.message}`, { error: true });
  } finally {
    button.textContent = label;
    button.disabled = false;
  }
}

document.getElementById("nav").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-panel]");
  if (!button) return;
  document.querySelectorAll("nav button").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".panel").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  $(button.dataset.panel).classList.add("active");
  window.scrollTo(0, 0);
  if (button.dataset.panel === "knowledge") {
    loadKnowledgeCatalog();
  }
  if (button.dataset.panel === "cli") {
    loadCliCatalog();
  }
});

bindClick("detectAgents", () => withBusy($("detectAgents"), detectAgents));
bindClick("createProject", () => withBusy($("createProject"), createProject));
bindClick("generateKnowledge", () => withBusy($("generateKnowledge"), generateKnowledge));
bindClick("generateCli", () => withBusy($("generateCli"), generateCli));
bindClick("generateCases", () => withBusy($("generateCases"), generateCases));
bindClick("confirmAll", () => withBusy($("confirmAll"), confirmAll));
bindClick("createSnapshot", () => withBusy($("createSnapshot"), createSnapshot));
bindClick("runRegression", () => withBusy($("runRegression"), runRegression));
bindClick("runMvp", runMvp);
bindClick("saveKnowledgeSkill", () => withBusy($("saveKnowledgeSkill"), saveKnowledgeSkill));
bindClick("sendKnowledgeMessage", () => withBusy($("sendKnowledgeMessage"), sendKnowledgeMessage));
bindClick("newKnowledge", () => withBusy($("newKnowledge"), newKnowledge));
bindClick("regenerateKnowledge", () => withBusy($("regenerateKnowledge"), regenerateKnowledge));
bindClick("editKnowledge", editKnowledge);
bindClick("saveKnowledgeEdit", () => withBusy($("saveKnowledgeEdit"), saveKnowledgeEdit));
bindClick("cancelKnowledgeEdit", cancelKnowledgeEdit);
bindClick("confirmKnowledgeWrite", () => withBusy($("confirmKnowledgeWrite"), confirmKnowledgeWrite));
bindClick("cancelKnowledgeReturn", cancelKnowledgeReturn);
bindClick("cancelRegenerate", () => withBusy($("cancelRegenerate"), cancelRegenerate));
bindClick("backToKnowledgeChat", () => withBusy($("backToKnowledgeChat"), () => startKnowledgeChat(state.knowledge.selectedNodeId || "project_background", false)));
bindClick("clearKnowledgeChat", () => {
  state.knowledge.session = null;
  startKnowledgeChat(state.knowledge.selectedNodeId || "project_background", false);
});
$("knowledgeSearch")?.addEventListener("input", renderKnowledgeTree);
$("knowledgeTree")?.addEventListener("click", (event) => {
  const group = event.target.closest("[data-knowledge-group-id]");
  if (group) {
    toggleKnowledgeGroup(group.dataset.knowledgeGroupId);
    return;
  }
  const node = event.target.closest("[data-node-id]");
  if (node) selectKnowledgeNode(node.dataset.nodeId, { startChat: true });
});
$("knowledgeDependencies")?.addEventListener("click", (event) => {
  const node = event.target.closest("[data-node-id]");
  if (node) selectKnowledgeNode(node.dataset.nodeId, { startChat: true });
});
$("knowledgeContent")?.addEventListener("click", (event) => {
  const node = event.target.closest("[data-node-id]");
  if (node) selectKnowledgeNode(node.dataset.nodeId, { startChat: true });
});
$("knowledgeTabs")?.addEventListener("click", (event) => {
  const tab = event.target.closest("[data-knowledge-tab]");
  if (tab) setKnowledgeTab(tab.dataset.knowledgeTab);
});
$("knowledgeChatHistory")?.addEventListener("click", (event) => {
  const item = event.target.closest("[data-session-id]");
  if (item) loadKnowledgeChatSession(item.dataset.sessionId);
});
bindClick("refreshKnowledgeHistory", () => withBusy($("refreshKnowledgeHistory"), () => loadKnowledgeChatHistory()));
$("cliSearch")?.addEventListener("input", renderCliCatalog);
$("cliTree")?.addEventListener("click", (event) => {
  const group = event.target.closest("[data-cli-group-id]");
  if (group) toggleCliGroup(group.dataset.cliGroupId);
});
document.querySelectorAll("[data-confirm]").forEach((button) => {
  button.addEventListener("click", () => withBusy(button, () => confirmDraft(button.dataset.confirm)));
});

updateMetrics();
loadExistingProject();
