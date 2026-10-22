"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const sharedSource = fs.readFileSync("opentest/web/shared-workspace.js","utf8");
const appSource = fs.readFileSync("opentest/web/app.js","utf8");

/** 提取实际生产函数，测试跨范围响应与写请求边界，不运行整个浏览器初始化。 */
function loadFunction(context, name, source = sharedSource) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start,-1);
  const end = source.indexOf("\n/**",start);
  vm.runInContext(source.slice(start,end < 0 ? undefined : end),context);
}

/** 构造个人基准与环境的最小浏览器上下文；不读本机偏好或发真实业务请求。 */
function scopeHarness() {
  const context=vm.createContext({sharedWorkspace:{baseline:{baseline_id:"base-a"},environment:"qa",caseView:"published",requests:new Map()},systemId:()=>"system-a",systemRequestGeneration:1,crypto:{randomUUID:()=>"isolated-request"}});
  for (const name of ["sharedScope","sharedScopeCurrent","sharedPath","sharedRequestId"]) loadFunction(context,name);
  return context;
}

test("迟到响应必须匹配原基准、环境和页面代次",()=>{
  // 同一系统切换环境或基准也必须让旧响应失效。
  const context=scopeHarness();const scope=context.sharedScope();
  assert.equal(context.sharedScopeCurrent(scope),true);
  context.sharedWorkspace.environment="uat";assert.equal(context.sharedScopeCurrent(scope),false);
  context.sharedWorkspace.environment="qa";context.sharedWorkspace.baseline.baseline_id="base-b";assert.equal(context.sharedScopeCurrent(scope),false);
});

test("取消部署确认不创建生成请求",async()=>{
  const context=scopeHarness();const requests=[];
  Object.assign(context,{document:{querySelector:()=>({})},captureSystemScope:()=>({systemId:"system-a"}),element:()=>({value:"facade:Query#run"}),currentSystem:{coverage_assistance:{enabled:true}},confirmSharedDeployment:()=>false,api:async(...args)=>requests.push(args)});
  loadFunction(context,"startCaseGeneration",appSource);
  await context.startCaseGeneration();assert.equal(requests.length,0);
});

test("全部发布网络结果未知时复用原请求范围",async()=>{
  const context=scopeHarness();const requests=[];
  context.api=async(path,options)=>{requests.push(JSON.parse(options.body));throw new Error("network result unknown");};
  loadFunction(context,"publishShared");
  await assert.rejects(context.publishShared("cases"));
  await assert.rejects(context.publishShared("cases"));
  assert.equal(requests[0].request_id,requests[1].request_id);
  assert.equal(requests[0].scope,"all");assert.deepEqual(requests[0].items,[]);
});

test("Case详情响应到达时已切换基准不能覆盖新页面",async()=>{
  const context=scopeHarness();let resolve;
  context.api=()=>new Promise(done=>{resolve=done;});
  loadFunction(context,"loadSharedCaseDetails");
  const pending=context.loadSharedCaseDetails("case-a");
  context.sharedWorkspace.baseline.baseline_id="base-b";
  resolve({case_id:"case-a"});await pending;
  assert.equal(context.sharedWorkspace.selectedCase,undefined);
});

test("共享基准列表迟到响应不能恢复切换前的选择", async () => {
  const context = scopeHarness();
  let finish;
  context.api = () => new Promise(resolve => {finish = resolve;});
  loadFunction(context, "loadSharedBaselines");
  const pending = context.loadSharedBaselines("base-a");
  context.systemRequestGeneration += 1;
  context.sharedWorkspace.baseline = {baseline_id: "base-b"};
  finish({baselines: [{baseline_id: "base-a"}]});
  await pending;
  assert.equal(context.sharedWorkspace.baseline.baseline_id, "base-b");
});

test("覆盖缺材料提供中文原因且未知原因不伪造成功",()=>{
  const context=scopeHarness();loadFunction(context,"sharedCoverageReason");
  assert.match(context.sharedCoverageReason("COVERAGE_MATERIAL_MISSING"),/原始覆盖材料缺失/);
  assert.match(context.sharedCoverageReason("NEW_UNKNOWN_CODE"),/未完成/);
});

test("覆盖查询必须绑定选中的单个Case", async () => {
  const {context} = coverageHarness("COMPLETED", "VALID");
  const requests = [];
  context.api = async path => {requests.push(path); return {coverage_assistance: null};};
  const item = {case_id: "case-a", generation_id: "generation-a", view: "published"};
  await context.loadSharedCoverage(item, context.sharedScope());
  assert.match(requests[0], /[?&]case_id=case-a(?:&|$)/);
});

/** 为覆盖详情构造最小可见面板；模拟材料只用于验证按钮和请求边界。 */
function coverageHarness(status, verificationStatus) {
  const context = scopeHarness();
  const children = [];
  const panel = {replaceChildren: () => {children.length = 0;}, appendChild: item => children.push(item)};
  const coverage = {status, enhancement_id: "enhancement-a", verification: {status: verificationStatus}};
  context.sharedWorkspace.selectedCase = {case_id: "case-a"};
  // 注入测量状态而不模拟真实采集，直接运行生产详情渲染和重试回调。
  Object.assign(context, {window: {clearTimeout: () => {}}, element: () => panel,
    textNode: (tag, text) => ({tag, text}), sharedButton: (label, action) => ({label, action}),
    api: async () => ({coverage_assistance: coverage})});
  for (const name of ["sharedStatus", "sharedCoverageReason", "loadSharedCoverage"]) loadFunction(context, name);
  return {context, children};
}

test("部分完成但复测无效或跳过可以重试，取消部署确认不写请求", async () => {
  // 有效复测的部分完成可能是未解决缺口，不允许误当采集失败重复执行。
  for (const [status, verificationStatus, retryable] of [
    ["PARTIAL", "INVALID", true], ["PARTIAL", "SKIPPED", true],
    ["PARTIAL", "VALID", false], ["COMPLETED", "VALID", false],
    ["FAILED", "INVALID", true], ["SKIPPED", "SKIPPED", true],
  ]) {
    const {context, children} = coverageHarness(status, verificationStatus);
    const item = {case_id: "case-a", generation_id: "generation-a", view: "published", variant: {variant_id: "variant-a"}};
    await context.loadSharedCoverage(item, context.sharedScope());
    const retry = children.find(child => child.label === "重新执行覆盖增强");
    assert.equal(Boolean(retry), retryable, `${status}/${verificationStatus}`);
    if (retry) {
      context.confirmSharedDeployment = () => false;
      let writes = 0;
      context.api = async () => {writes += 1;};
      await retry.action();
      assert.equal(writes, 0);
    }
  }
});

test("工作台统计必须带基准环境和视图，无基准不读系统最新扫描", async () => {
  const context = scopeHarness();
  const metrics = {"metric-entry": {}, "metric-resource": {}};
  const requests = [];
  context.sharedWorkspace.interfaceView = "mine";
  Object.assign(context, {isCurrentSystemScope: () => true, element: id => metrics[id],
    api: async path => {requests.push(path); return {entry_count: 3, resource_count: 2};}});
  loadFunction(context, "loadWorkbenchSummary", appSource);
  await context.loadWorkbenchSummary({systemId: "system-a"});
  assert.match(requests[0], /baseline_id=base-a&environment_id=qa&view=mine/);
  assert.equal(metrics["metric-entry"].textContent, "3");
  // 顶部暂无共享基准时，只清空计数，不调用退役系统级扫描接口。
  context.sharedWorkspace.baseline = null;
  await context.loadWorkbenchSummary({systemId: "system-a"});
  assert.equal(requests.length, 1);
  assert.equal(metrics["metric-entry"].textContent, "0");
  assert.equal(metrics["metric-resource"].textContent, "0");
});

/** 构造可切换三个基准的界面，记录真正落入个人偏好的选择和失败提示。 */
function baselineSelectionHarness() {
  const context = scopeHarness();
  const choices = ["base-a", "base-b", "base-c"].map(baseline_id => ({baseline_id}));
  const select = {value: "base-b"}, saved = [], messages = [];
  Object.assign(context.sharedWorkspace, {baselines: choices, baseline: choices[0]});
  Object.assign(context, {element: () => select,
    document: {querySelector: () => ({id: "workspace-knowledge"})},
    cancelSystemReads: () => {}, clearSystemWorkspaceState: () => {}, syncSharedEnvironment: () => {},
    renderSharedBaselineHeader: () => {select.value = context.sharedWorkspace.baseline.baseline_id;},
    sharedPreference: name => name, localStorage: {setItem: (key, value) => saved.push(value)},
    showToast: message => messages.push(message)});
  loadFunction(context, "handleSharedBaselineSelection");
  return {context, select, saved, messages};
}

test("基准目录读取失败保留原选择，成功后才保存偏好", async () => {
  const {context, select, saved, messages} = baselineSelectionHarness();
  const reads = [];
  context.loadWorkspaceData = async () => {
    const baseline = context.sharedWorkspace.baseline.baseline_id;
    reads.push(baseline);
    if (baseline === "base-b") throw new Error("catalog unavailable");
  };
  await context.handleSharedBaselineSelection();
  assert.equal(context.sharedWorkspace.baseline.baseline_id, "base-a");
  assert.equal(select.value, "base-a");
  assert.deepEqual(saved, []);
  assert.deepEqual(reads, ["base-b", "base-a"]);
  assert.match(messages[0], /切换失败.*恢复原选择/);
  select.value = "base-c";
  await context.handleSharedBaselineSelection();
  assert.deepEqual(saved, ["base-c"]);
});

test("迟到的切换失败不能撤销后来已成功的基准", async () => {
  const {context, select, saved, messages} = baselineSelectionHarness();
  let fail;
  context.loadWorkspaceData = () => context.sharedWorkspace.baseline.baseline_id === "base-b"
    ? new Promise((resolve, reject) => {fail = reject;}) : Promise.resolve();
  const pending = context.handleSharedBaselineSelection();
  select.value = "base-c";
  await context.handleSharedBaselineSelection();
  fail(new Error("old request failed"));
  await pending;
  assert.equal(context.sharedWorkspace.baseline.baseline_id, "base-c");
  assert.deepEqual(saved, ["base-c"]);
  assert.deepEqual(messages, []);
});

test("旧知识任务详情不再提供已退役的知识读取按钮", async () => {
  const children = [], requests = [];
  /** 提供任务详情所需最小DOM，保存实际按钮标签而不执行页面初始化。 */
  function node(tag, text) {
    const item = {tag, text, children: [], dataset: {}, append(...values) {this.children.push(...values);},
      appendChild(value) {this.children.push(value);}, addEventListener() {}, showModal() {}};
    return item;
  }
  const context = vm.createContext({
    captureSystemScope: () => ({systemId: "system-a"}), isCurrentSystemScope: () => true,
    api: async path => {requests.push(path); return {task: {task_id: "legacy", status: "completed"}, context: {kind: "knowledge"}};},
    document: {getElementById: () => null, body: {appendChild: item => children.push(item)}},
    textNode: node, codexTaskStatusLabel: () => "已完成", appendResourceProbeResult: () => {}, appendTaskAgentDiagnostics: () => {},
  });
  loadFunction(context, "showBusinessTask", appSource);
  await context.showBusinessTask({task_id: "legacy"});
  assert.deepEqual(requests, ["/tasks/legacy/context"]);
  assert.equal(children[0].children.some(item => item.tag === "button" && item.text === "查看正式知识"), false);
  assert.ok(children[0].children.some(item => /顶部选择对应代码基准/.test(item.text)));
});
