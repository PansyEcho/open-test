"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/app.js"), "utf8");

/**
 * 提取生产函数，故障场景运行真实按钮和读取逻辑而不启动整个控制台。
 * @param {string} name 页面函数名。
 * @returns {string} 包含函数定义的源码。
 */
function sourceFunction(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1);
  // 文档注释是函数边界；避免把页面初始化和定时器一起加载进测试。
  return source.slice(start, source.indexOf("\n/**", start));
}

/**
 * 建立已有基础任务的按钮环境，记录网络请求与打开的任务。
 * @returns {object} 可注入后继竞争、失败和系统切换的隔离环境。
 */
function continuationHarness() {
  const nodes = {}, opened = [], requests = [];
  const context = vm.createContext({
    currentCaseTask: {task_id: "base-task", generation_id: "base", status: "completed"},
    currentCaseHandoff: null, currentCaseCoverage: null, activeCaseHandoffId: "base-handoff",
    captureSystemScope: () => ({systemId: "refund"}), isCurrentSystemScope: () => true,
    element: id => nodes[id] || (nodes[id] = {}),
    showBusinessTask: async task => {opened.push(task.task_id); return true;},
    getOrCreateCaseRequestId: () => "continuation-request",
  });
  // 只有创建路径会调用业务启动；本组已有后继测试不提供启动替身以防误派发。
  for (const name of ["renderCaseContinuationActions", "openCaseSuccessor", "continueCaseGeneration"]) {
    vm.runInContext(sourceFunction(name), context);
  }
  const parent = {handoff_id: "base-handoff", system_id: "refund", task_id: "base-task",
    generation_id: "base", status: "COMPLETED", revision: 1, successor_handoff_id: ""};
  const child = {handoff_id: "child-handoff", system_id: "refund", task_id: "child-task"};
  return {context, nodes, opened, requests, parent, child};
}

/**
 * 执行真实的可见性恢复函数，隔离网络和 DOM，只记录被接受的覆盖结果。
 * @returns {object} 可控制可见性、版本与网络响应的页面环境。
 */
function visibilityHarness() {
  const rendered = [];
  const context = vm.createContext({
    document: {hidden: true}, currentCaseGeneration: {generation_id: "base"},
    captureSystemScope: () => ({systemId: "refund"}),
    isCurrentSystemScope: scope => scope.systemId === "refund",
    renderCaseCoverage: coverage => rendered.push(coverage),
  });
  // 从生产源码提取函数，使恢复请求、可见性和迟到检查都走同一实现。
  const start = source.indexOf("async function refreshVisibleCaseCoverage(");
  vm.runInContext(source.slice(start, source.indexOf("\n/**", start)), context);
  return {context, rendered};
}

/** 隐藏页不轮询，重新可见后读取完成状态并交给原渲染器恢复展示。 */
test("visible page resumes coverage observation without starting another measurement", async () => {
  const {context, rendered} = visibilityHarness();
  const requests = [];
  context.api = async route => {
    requests.push(route);
    return {coverage_assistance: {status: "COMPLETED"}};
  };
  await vm.runInContext("refreshVisibleCaseCoverage()", context);
  assert.equal(requests.length, 0);
  context.document.hidden = false;
  await vm.runInContext("refreshVisibleCaseCoverage()", context);
  assert.deepEqual(requests, ["/systems/refund/case-generations/base/coverage"]);
  assert.equal(rendered[0].status, "COMPLETED");
});

/** 可见性恢复与用户切版本同时发生时，不把上一版本的增强状态画到新版本。 */
test("late visibility response cannot replace another selected generation", async () => {
  const {context, rendered} = visibilityHarness();
  let complete;
  context.api = () => new Promise(resolve => {complete = resolve;});
  context.document.hidden = false;
  const pending = vm.runInContext("refreshVisibleCaseCoverage()", context);
  context.currentCaseGeneration = {generation_id: "enhanced"};
  complete({coverage_assistance: {status: "RUNNING"}});
  await pending;
  assert.equal(rendered.length, 0);
});

/** 已有后继必须在点击读取时发现，继续或重新生成都只打开原任务，不发POST。 */
test("both continuation intents open the existing successor without a write", async () => {
  for (const intent of ["continue", "regenerate_latest"]) {
    const {context, requests, opened, parent, child, nodes} = continuationHarness();
    parent.successor_handoff_id = child.handoff_id;
    context.api = async (route, options = {}) => {
      requests.push([route, options.method || "GET"]);
      return route.endsWith("/context") ? {context: {handoff: parent}} : {handoff: child};
    };
    assert.equal(await vm.runInContext(`continueCaseGeneration("${intent}")`, context), true);
    assert.deepEqual(opened, ["child-task"]);
    assert.equal(requests.some(([, method]) => method !== "GET"), false);
    assert.equal(nodes["regenerate-case-latest"].disabled, true);
    assert.equal(nodes["continue-case-generation"].textContent, "查看后继任务");
  }
});

/** 读取父revision后被增强抢先建立后继时，只核实并跳转，不重试写请求。 */
test("a successor created during continuation redirects after one rejected write", async () => {
  const {context, requests, opened, parent, child} = continuationHarness();
  context.api = async (route, options = {}) => {
    requests.push([route, options.method || "GET"]);
    if (options.method === "POST") throw new Error("predecessor already has a successor");
    if (route.endsWith("/context")) return {context: {handoff: parent}};
    return {handoff: route.includes("base-handoff")
      ? {...parent, successor_handoff_id: child.handoff_id, revision: 2} : child};
  };
  assert.equal(await vm.runInContext('continueCaseGeneration("continue")', context), true);
  assert.deepEqual(opened, ["child-task"]);
  assert.equal(requests.filter(([, method]) => method === "POST").length, 1);
});

/** 没有确认后继时保留原始写失败，不将读取失败或其他业务拒绝伪装为成功。 */
test("continuation failure stays visible when no successor can be confirmed", async () => {
  const {context, opened, parent} = continuationHarness();
  context.api = async (route, options = {}) => {
    if (options.method === "POST") throw new Error("original failure");
    if (route.endsWith("/context")) return {context: {handoff: parent}};
    throw new Error("status read unavailable");
  };
  await assert.rejects(vm.runInContext('continueCaseGeneration("continue")', context), /original failure/);
  assert.deepEqual(opened, []);
});

/** 后继与覆盖投影必须属于当前任务；切换任务后旧增强不能封锁新版本。 */
test("continuation buttons follow matching handoff or coverage successor only", () => {
  const {context, nodes, parent, child} = continuationHarness();
  context.currentCaseHandoff = {...parent, successor_handoff_id: child.handoff_id};
  vm.runInContext("renderCaseContinuationActions()", context);
  assert.equal(nodes["regenerate-case-latest"].disabled, true);
  context.currentCaseHandoff = null;
  context.currentCaseCoverage = {base_generation_id: "base", supplement_task_id: "child-task"};
  vm.runInContext("renderCaseContinuationActions()", context);
  assert.equal(nodes["continue-case-generation"].textContent, "查看当前增强任务");
  context.currentCaseTask = {task_id: "other-task", generation_id: "other", status: "completed"};
  vm.runInContext("renderCaseContinuationActions()", context);
  assert.equal(nodes["regenerate-case-latest"].disabled, false);
  assert.equal(nodes["continue-case-generation"].textContent, "继续原基线任务");
});

/** Loading结束后仍按已建立后继重新应用门禁，不能把重新生成按钮无条件恢复可用。 */
test("loading completion keeps regeneration disabled after successor discovery", async () => {
  const {context, nodes, parent, child} = continuationHarness();
  const button = {id: "regenerate-case-latest", classList: {add() {}, remove() {}}, setAttribute() {}};
  nodes[button.id] = button;
  context.button = button;
  context.action = async () => {
    context.currentCaseHandoff = {...parent, successor_handoff_id: child.handoff_id};
  };
  vm.runInContext(sourceFunction("withButtonLoading"), context);
  await vm.runInContext("withButtonLoading(button, action)", context);
  assert.equal(button.disabled, true);
});

/** 用户在后继读取途中切换Case任务，迟到响应不能打开旧任务的弹窗。 */
test("late successor response cannot open a task after the user changes selection", async () => {
  const {context, parent, child, opened} = continuationHarness();
  parent.successor_handoff_id = child.handoff_id;
  context.parent = parent;
  let complete;
  context.api = () => new Promise(resolve => {complete = resolve;});
  const pending = vm.runInContext('openCaseSuccessor(parent, {systemId: "refund"})', context);
  context.currentCaseTask = {task_id: "other-task", generation_id: "other"};
  complete({handoff: child});
  assert.equal(await pending, false);
  assert.deepEqual(opened, []);
});

/**
 * 为覆盖卡片提供小型DOM和失败通知，检验公开原因与任务入口。
 * @returns {object} 包含渲染节点、消息和真实卡片函数的测试环境。
 */
function coveragePanelHarness() {
  const nodes = [], notices = [];
  const panel = {replaceChildren: () => {nodes.length = 0;}, append: (...items) => nodes.push(...items)};
  const context = vm.createContext({
    caseCoveragePollTimer: null, currentCaseCoverage: null, window: {clearTimeout: () => {}},
    element: () => panel, renderCaseContinuationActions: () => {}, isCurrentSystemScope: () => true,
    textNode: (tag, text) => ({tag, text, addEventListener(event, callback) {this[event] = callback;}}),
    withButtonLoading: async (_button, action) => action(), showToast: (...notice) => notices.push(notice),
  });
  // 完成态不轮询，失败按钮只验证读取和通知，不实际打开其他应用。
  vm.runInContext(sourceFunction("renderCaseCoverage"), context);
  return {context, nodes, notices, panel};
}

/** 内部裁剪标记不能成为失败原因，打开增强任务的网络失败必须有可见反馈。 */
test("coverage panel hides internal maintenance codes and reports task lookup failure", async () => {
  const {context, nodes, notices} = coveragePanelHarness();
  context.coverage = {status: "PARTIAL", reason_codes: ["INTERNAL_REPORT_RETENTION_PENDING", "COVERAGE_CAPTURE_FAILED"],
    supplement_task_id: "child-task"};
  context.api = async () => {throw new Error("network unavailable");};
  vm.runInContext('renderCaseCoverage(coverage, {systemId: "refund"}, "base")', context);
  assert.equal(nodes.some(node => node.text.includes("INTERNAL_")), false);
  assert.equal(nodes.some(node => node.text.includes("COVERAGE_CAPTURE_FAILED")), true);
  assert.equal(nodes.some(node => node.text.includes("只有一个承接请求的实例")), false);
  await nodes.find(node => node.tag === "button").click();
  assert.equal(notices.length, 1);
  assert.match(notices[0][0], /增强任务打开失败：network unavailable/);
  assert.equal(notices[0][1], "error");
});

/** 已被替代的共享任务只能单Case修订；过期按钮也不得发起整批POST或打开旧后继。 */
test("shared terminal continuation is disabled and cannot send a successor request", async () => {
  for (const intent of ["continue", "regenerate_latest"]) {
    const {context, nodes, parent, requests, opened} = continuationHarness();
    context.currentCaseTask.result = {baseline_id: "baseline-one", environment_id: "uat"};
    context.currentCaseHandoff = {...parent, baseline_id: "baseline-one", successor_handoff_id: "hidden-old-child"};
    context.api = async route => {requests.push(route); throw new Error("unexpected request");};
    vm.runInContext("renderCaseContinuationActions()", context);
    assert.equal(nodes["continue-case-generation"].disabled, true);
    assert.equal(nodes["regenerate-case-latest"].disabled, true);
    assert.match(nodes["continue-case-generation"].textContent, /单个Case/);
    await assert.rejects(vm.runInContext(`continueCaseGeneration("${intent}")`, context), /单个Case/);
    assert.deepEqual(requests, []);
    assert.deepEqual(opened, []);
  }
});
