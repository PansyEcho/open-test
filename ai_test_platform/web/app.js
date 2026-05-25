const state = {
  project: null,
  drafts: {},
  versions: {},
  snapshot: null,
  run: null,
};

const $ = (id) => document.getElementById(id);

function log(message, data) {
  const text = data ? `${message}\n${JSON.stringify(data, null, 2)}` : message;
  $("statusLog").textContent = text;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
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
  $("projectJson").textContent = pretty(state.project);
  updateMetrics();
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
  $("projectJson").textContent = pretty(state.project);
  log("项目已创建", payload.project);
  updateMetrics();
}

async function generateKnowledge() {
  ensureProject();
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
  const payload = await api(`/api/projects/${state.project.id}/cli/build-all`, { method: "POST", body: { types: "facade,job" } });
  state.drafts.cli = payload.draft;
  $("cliDraft").textContent = pretty(payload.draft);
  log("CLI 草稿已生成", payload.draft);
  updateMetrics();
}

async function generateCases() {
  ensureProject();
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
  if (kind === "cli") $("cliTools").textContent = pretty(payload.version);
  log(`${kind} 已确认`, payload.version);
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
    await generateKnowledge();
    await confirmDraft("knowledge");
    await generateCli();
    await confirmDraft("cli");
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
  try {
    await fn();
  } catch (error) {
    log(`操作失败：${error.message}`);
    throw error;
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
});

$("detectAgents").addEventListener("click", () => withBusy($("detectAgents"), detectAgents));
$("createProject").addEventListener("click", () => withBusy($("createProject"), createProject));
$("generateKnowledge").addEventListener("click", () => withBusy($("generateKnowledge"), generateKnowledge));
$("generateCli").addEventListener("click", () => withBusy($("generateCli"), generateCli));
$("generateCases").addEventListener("click", () => withBusy($("generateCases"), generateCases));
$("confirmAll").addEventListener("click", () => withBusy($("confirmAll"), confirmAll));
$("createSnapshot").addEventListener("click", () => withBusy($("createSnapshot"), createSnapshot));
$("runRegression").addEventListener("click", () => withBusy($("runRegression"), runRegression));
$("runMvp").addEventListener("click", runMvp);
document.querySelectorAll("[data-confirm]").forEach((button) => {
  button.addEventListener("click", () => withBusy(button, () => confirmDraft(button.dataset.confirm)));
});

updateMetrics();
