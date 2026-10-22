"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");

/** 从实际页面脚本提取指定函数，保留真实状态分支，隔离页面启动和网络。 */
function load(context, name, file = "app.js") {
  const source = fs.readFileSync(`opentest/web/${file}`, "utf8");
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1);
  const end = source.indexOf("\n/**", start);
  vm.runInContext(source.slice(start, end < 0 ? undefined : end), context);
}

/** 构造事件与元素最小替身；关闭事件可延迟，重现登录失效早于浏览器close派发的竞争。 */
function dialogHarness() {
  const nodes = [];
  /** 创建可记录事件的节点，供真实openDialog管理按钮和生命周期。 */
  function node(tag) {
    const listeners = new Map();
    const item = {tag, children: [], disabled: false, open: false,
      append(...items) { this.children.push(...items); },
      appendChild(child) { this.children.push(child); },
      addEventListener(name, handler) { listeners.set(name, handler); },
      removeEventListener(name) { listeners.delete(name); },
      dispatch(name) { return listeners.get(name)?.({preventDefault() {}}); },
      contains() { return false; }, querySelector() { return null; }, focus() {},
      showModal() { this.open = true; }, close() { this.open = false; }, remove() { this.removed = true; }};
    nodes.push(item);
    return item;
  }
  const window = node("window");
  const context = vm.createContext({document: {createElement: node, body: node("body")}, window,
    selectPanel: {element: null}, closeSelectPanel() {}});
  load(context, "openDialog", "ui-controls.js");
  return {context, nodes, window};
}

test("登录失效同步取消确认，迟到确认结果不能重新提交或恢复弹框", async () => {
  const {context, nodes, window} = dialogHarness();
  let finish, calls = 0;
  const pending = new Promise(resolve => {finish = resolve;});
  const dialog = context.openDialog({title: "发布", onConfirm: () => {calls++; return pending;}});
  const confirm = nodes.find(item => item.tag === "button" && item.textContent === "确定");
  const click = confirm.dispatch("click");
  window.dispatch("opentest-auth-cleared");
  assert.equal(await dialog.result, null);
  finish(true);
  await click;
  await confirm.dispatch("click");
  assert.equal(calls, 1);
  assert.equal(nodes.find(item => item.tag === "dialog").removed, true);
});

test("外部原生close也解除等待中的确认", async () => {
  const {context, nodes} = dialogHarness();
  const dialog = context.openDialog({title: "生成"});
  nodes.find(item => item.tag === "dialog").dispatch("close");
  assert.equal(await dialog.result, null);
});

test("历史Case等待问题显示受阻，知识访谈仍能等待回答", () => {
  const context = vm.createContext({});
  load(context, "isCaseGenerationTask");
  load(context, "codexTaskStatusLabel");
  assert.equal(context.codexTaskStatusLabel({operation: "case-generation", status: "waiting_for_input"}), "生成受阻");
  assert.equal(context.codexTaskStatusLabel({operation: "knowledge-target-generation", status: "waiting_for_input"}), "等待用户回答");
});

test("生成使用弹框冻结的私有入口和只生成模式，不受目录刷新覆盖", async () => {
  const scope = {systemId: "system-a", baselineId: "base-a", environment: "qa", generation: 1};
  const requests = [];
  const nodes = new Map();
  const context = vm.createContext({
    sharedWorkspace: {caseView: "published", operationViews: new Map([["entry-new", "published"]]),
      generationSelection: {scope, operationId: "entry-private", view: "mine", executionMode: "generate_only"}},
    document: {querySelector: () => ({})}, captureSystemScope: () => scope, sharedScope: () => scope,
    sharedScopeCurrent: () => true, isCurrentSystemScope: () => true,
    element: id => {if (!nodes.has(id)) nodes.set(id, {value: "entry-new"}); return nodes.get(id);},
    currentSystem: {coverage_assistance: {enabled: true}},
    confirmSharedDeployment: () => {throw new Error("只生成不能要求部署确认");},
    stopCaseHandoffPolling() {}, caseRequestGeneration: 1, getOrCreateCaseRequestId: () => "frozen-request",
    renderSharedCaseTasks() {},
    api: async (path, options) => {requests.push(JSON.parse(options.body)); throw new Error("admission rejected");},
  });
  load(context, "startCaseGeneration");
  await assert.rejects(context.startCaseGeneration(), /admission rejected/);
  assert.equal(requests[0].operation_id, "entry-private");
  assert.equal(requests[0].view, "mine");
  assert.equal(requests[0].execution_mode, "generate_only");
  assert.equal(requests[0].deployment_confirmed, false);
});

/**
 * 构造真实任务卡与详情函数需要的DOM替身，记录请求而不启动页面或后台工作。
 * @param {object} task 后端返回的当前任务。
 * @param {object} taskContext 详情接口的补充上下文。
 * @returns {object} 可检查列表、旧面板、对话框及请求的运行环境。
 */
function taskRenderingHarness(task, taskContext = {}) {
  /** 创建保留文本、展开状态与子节点的元素，供实际渲染函数消费。 */
  function textNode(tag, text = "", className = "") {
    return {tag, textContent: text, className, children: [], dataset: {}, open: false,
      /** 保存批量渲染的子节点，使断言能检查提示与折叠区。 */
      append(...items) { this.children.push(...items); },
      /** 保存单个任务卡或详情节点，供后续展示断言读取。 */
      appendChild(child) { this.children.push(child); },
      /** 模拟列表替换，确保迟到响应测试不会把历史卡片混入新列表。 */
      replaceChildren(...items) { this.children = items; },
      /** 渲染测试不点击恢复动作；只接收真实函数的事件注册。 */
      addEventListener() {},
      /** 此夹具没有已展开诊断，防止轮询测试复用不存在的节点。 */
      querySelector() {return null;},
      /** 标记真实详情函数已打开对话框，便于检查它的默认展开状态。 */
      showModal() { this.open = true; }};
  }
  const scope = {systemId: "system-a", baselineId: "base-a", environment: "qa", generation: 1};
  const container = textNode("section"), body = textNode("body"), progress = {hidden: false};
  const requests = [];
  const operation = {value: "entry-a"};
  const context = vm.createContext({
    document: {getElementById: id => id === "shared-case-task-list" ? container : null, body,
      querySelector: selector => selector === ".workspace.active" ? {id: "workspace-regression-cases"} : progress},
    sharedScope: () => scope, sharedScopeCurrent: () => true, captureSystemScope: () => scope,
    isCurrentSystemScope: () => true,
    currentCaseTask: {task_id: "old-selected-task", target_id: "entry-a", result: {baseline_id: "base-a", environment_id: "qa"}},
    sharedWorkspace: {caseTab: "generation", taskListScope: "", taskListLoading: ""},
    element: () => operation, textNode, URLSearchParams,
    sharedButton: label => textNode("button", label),
    appendResourceProbeResult() {}, appendTaskAgentDiagnostics() {},
    window: {setTimeout() {}}, CASE_HANDOFF_POLL_INTERVAL_MS: 5000,
    api: async path => {
      requests.push(path);
      return path.endsWith("/context") ? {task, context: taskContext}
        : {tasks: [task], pagination: {has_more: true}};
    },
  });
  // 加载生产实现，避免替身把错误分类或查询契约写死为预期答案。
  for (const name of ["parseApiTime", "isCaseGenerationTask", "caseTaskActivityTime", "codexTaskUpdatedAt",
    "codexTaskStatusLabel", "appendTaskIssueSummary", "renderSharedCaseTasks", "showBusinessTask"])
    load(context, name);
  return {context, container, body, progress, requests, operation};
}

test("生成任务页签向服务端请求范围内最近活动一项，不重复旧进度或历史分页", async () => {
  const {context, container, progress, requests} = taskRenderingHarness({
    task_id: "task-rerun", operation: "case-generation", status: "completed",
    created_at: "2026-10-20T09:00:00Z", ended_at: "2026-10-23T11:31:08Z"});
  await context.renderSharedCaseTasks();
  assert.equal(container.children.length, 1);
  assert.equal(container.children[0].children[0].textContent, "已完成");
  assert.equal(progress.hidden, true);
  const query = new URL(requests[0], "http://localhost").searchParams;
  assert.deepEqual(Object.fromEntries(query), {system_id: "system-a", target_id: "entry-a", operation: "case-generation",
    baseline_id: "base-a", environment_id: "qa", view: "summary", page: "1", page_size: "1", order_by: "activity"});
});

test("恢复中的旧任务显示新进度时间，工具错误在卡片和详情中默认折叠", async () => {
  const task = {task_id: "task-running", operation: "case-generation", status: "running", web_run_active: true,
    error: "缺少可修正字段", created_at: "2026-10-20T09:00:00Z", started_at: "2026-10-20T09:00:00Z",
    progress: {updated_at: "2026-10-23T11:31:08Z"}};
  const {context, container, body} = taskRenderingHarness(task, {validation_issues: [{message: "缺少可修正字段"}]});
  assert.equal(context.caseTaskActivityTime(task), Date.parse(task.progress.updated_at));
  await context.renderSharedCaseTasks();
  await context.showBusinessTask(task);
  for (const surface of [container.children[0], body.children[0]]) {
    const processing = surface.children.find(node => node.className === "task-processing-issue");
    assert.equal(processing.tag, "details");
    assert.equal(processing.open, false);
    assert.equal(surface.children.some(node => node.className === "status-blocked"), false);
  }
  const validation = body.children[0].children.find(node => node.className === "task-validation-issues");
  assert.equal(validation.open, false);
});

test("任务退出运行且失败时仍明确展示阻塞原因", async () => {
  const task = {task_id: "task-failed", operation: "case-generation", status: "failed", web_run_active: false,
    error: "依赖不可用，目标未执行"};
  const {context, container, body} = taskRenderingHarness(task);
  await context.renderSharedCaseTasks();
  await context.showBusinessTask(task);
  for (const surface of [container.children[0], body.children[0]])
    assert.equal(surface.children.find(node => node.className === "status-blocked").textContent,
      "失败摘要：依赖不可用，目标未执行");
});

test("切换入口后的迟到任务响应不能覆盖新入口唯一任务", async () => {
  const {context, container, operation} = taskRenderingHarness({});
  let finishOld;
  context.api = path => path.includes("target_id=entry-a")
    ? new Promise(resolve => {finishOld = resolve;})
    : Promise.resolve({tasks: [{task_id: "new-entry-task", status: "completed"}]});
  const pending = context.renderSharedCaseTasks();
  operation.value = "entry-b";
  await context.renderSharedCaseTasks();
  finishOld({tasks: [{task_id: "old-entry-task", status: "failed", error: "旧错误"}]});
  await pending;
  assert.equal(container.children.length, 1);
  assert.equal(container.children[0].children[0].textContent, "已完成");
  assert.equal(container.children[0].children.some(node => node.className === "status-blocked"), false);
});
