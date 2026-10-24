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

/** 验证不可用提示优先，正常契约仍保留未分析及三个分析结论。 */
test("接口分类保留未分析和已分析UNKNOWN四态", () => {
  const context = scopeHarness();
  loadFunction(context, "interfaceMutabilityLabel");
  // 扫描提示只读不能假装完成语义分析；分析后UNKNOWN必须展示原因。
  assert.equal(context.interfaceMutabilityLabel({mutability: "READ_ONLY"}), "未分析");
  for (const [mutability, label] of [["READ_ONLY", "只读"], ["WRITE", "写入"], ["UNKNOWN", "无法确定"]]) {
    assert.equal(context.interfaceMutabilityLabel({mutability, mutability_analyzed: true}), `已分析·${label}`);
  }
  assert.match(context.interfaceMutabilityLabel({mutability: "UNKNOWN", mutability_analyzed: true, mutability_reason: "调用不可见"}), /调用不可见/);
  // 缺失契约不能显示为未分析或沿用残留只读值；原因供用户恢复原可见版本。
  assert.equal(context.interfaceMutabilityLabel({mutability: null, contract_available: false}), "契约不可用");
  assert.equal(context.interfaceMutabilityLabel({mutability: "READ_ONLY", mutability_analyzed: true,
    contract_available: false, contract_unavailable_reason: "固定修订缺失"}), "契约不可用：固定修订缺失");
});

test("分析按钮固定Case契约且网络结果未知时复用请求身份", async () => {
  const context = scopeHarness(), requests = [];
  loadFunction(context, "prepareInterfaceClassification");
  context.api = async (path, options) => { requests.push({path, ...JSON.parse(options.body)}); throw new Error("network result unknown"); };
  const item = {operation_id: "facade:Query#run", case_id: "case-old", input_contract: {source_scan_id: "scan-old", contract_revision: 3}};
  // 只创建原生分析任务，不提交目标执行；同一次未知结果的重试不重复创建任务。
  await assert.rejects(context.prepareInterfaceClassification(context.sharedScope(), item, "published"));
  await assert.rejects(context.prepareInterfaceClassification(context.sharedScope(), item, "published"));
  assert.equal(requests[0].path, "/systems/system-a/data-capabilities/prepare");
  assert.equal(requests[0].scan_id, "scan-old");
  assert.equal(requests[0].contract_revision, 3);
  assert.equal(requests[0].baseline_id, "base-a");
  assert.equal(requests[0].case_id, "case-old");
  assert.equal(requests[0].request_id, requests[1].request_id);
  assert.equal(requests[0].execution_mode, "generate_only");
  assert.equal(requests[0].interaction_mode, "native");
});

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
  const {context}=caseDetailHarness();let resolve;
  context.api=()=>new Promise(done=>{resolve=done;});
  loadFunction(context,"loadSharedCaseDetails");
  const pending=context.loadSharedCaseDetails("case-a");
  context.sharedWorkspace.baseline.baseline_id="base-b";
  resolve({case_id:"case-a"});await pending;
  assert.equal(context.sharedWorkspace.selectedCase,null);
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
  for (const name of ["sharedStatus", "sharedCoverageReason", "sharedCaseSelectionCurrent", "loadSharedCoverage"]) loadFunction(context, name);
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
  loadFunction(context, "isCaseGenerationTask", appSource);
  loadFunction(context, "appendTaskIssueSummary", appSource);
  loadFunction(context, "showBusinessTask", appSource);
  await context.showBusinessTask({task_id: "legacy"});
  assert.deepEqual(requests, ["/tasks/legacy/context"]);
  assert.equal(children[0].children.some(item => item.tag === "button" && item.text === "查看正式知识"), false);
  assert.ok(children[0].children.some(item => /顶部选择对应代码基准/.test(item.text)));
});

/**
 * 构造只记录文本和子节点的 DOM，供实际生产渲染函数验证状态边界。
 * @param {string} tag 节点标签。
 * @param {string} text 初始文本。
 * @returns {object} 可追加和替换内容的节点，不提供浏览器或网络副作用。
 */
function caseNode(tag = "div", text = "") {
  return {tag, text, value: "", children: [], dataset: {}, classList: {
    /** 此夹具不检查样式，仅满足生产代码的类切换调用。 */
    toggle() {},
  },
    /** 记录同一业务阶段追加的多个子节点。 */
    append(...items) { this.children.push(...items); },
    /** 记录一个渲染节点，不访问浏览器。 */
    appendChild(item) { this.children.push(item); },
    /** 清除旧投影并记录新节点，供竞态断言使用。 */
    replaceChildren(...items) { this.children = items; },
    /** 属性不影响本夹具关注的请求范围。 */
    setAttribute() {},
    /** 事件回调通过 sharedButton 单独捕获，不自动执行。 */
    addEventListener() {},
    /** 不模拟与本测试无关的 DOM 查询。 */
    querySelector() { return null; }};
}

/**
 * 运行真实单 Case 读取逻辑所需的页面上下文，允许测试控制响应先后顺序。
 * @returns {{context: object, panels: object}} VM 与可断言的渲染节点。
 */
function caseDetailHarness() {
  const context = scopeHarness();
  const panels = Object.fromEntries(["shared-case-operation", "shared-case-detail", "shared-case-executions", "shared-case-coverage", "shared-history-case", "shared-coverage-case"].map(id => [id, caseNode()]));
  panels["shared-case-operation"].value = "facade:Query#run";
  Object.assign(context.sharedWorkspace, {caseSelectionEpoch: 0, caseTab: "cases", selectedCase: null});
  // API 由各测试控制；这里仅提供渲染必需的节点，避免假执行掩盖请求身份问题。
  Object.assign(context, {element: id => panels[id], document: {getElementById: id => panels[id], createElement: caseNode},
    window: {clearTimeout() {}}, textNode: caseNode, sharedButton: (label, action) => ({label, action, dataset: {}})});
  for (const name of ["clearSharedCaseSelection", "sharedCaseSelectionCurrent", "sharedStatus", "interfaceMutabilityLabel", "loadSharedCaseDetails"]) loadFunction(context, name);
  return {context, panels};
}

/**
 * 返回属于同一入口的最小真实 Case 投影结构。
 * @param {string} id Case 身份，用于检查是否把后点击的选择覆盖。
 * @returns {object} 生产详情函数能读取的 Case 与 Variant 字段。
 */
function caseProjection(id) {
  return {case_id: id, operation_id: "facade:Query#run", title: id, generation_id: `generation-${id}`, impact_status: "CURRENT",
    variant: {variant_id: `variant-${id}`, status: "READY", data_calls: [], oracles: [], request_values: {pageSize: 10}}};
}

test("同基准先点 A 后点 B，A 的迟到详情不能覆盖 B", async () => {
  const {context, panels} = caseDetailHarness();
  const waiting = [];
  context.api = () => new Promise(resolve => waiting.push(resolve));
  const first = context.loadSharedCaseDetails("case-a");
  const second = context.loadSharedCaseDetails("case-b");
  waiting[1](caseProjection("case-b")); await second;
  waiting[0](caseProjection("case-a")); await first;
  assert.equal(context.sharedWorkspace.selectedCase.case_id, "case-b");
  assert.equal(panels["shared-case-detail"].children[0].text, "case-b");
});

test("同基准旧详情的迟到失败不能破坏新选择", async () => {
  const {context, panels} = caseDetailHarness();
  let rejectOld;
  context.api = () => new Promise((resolve, reject) => { rejectOld = reject; });
  const pending = context.loadSharedCaseDetails("case-a");
  context.api = async () => caseProjection("case-b");
  await context.loadSharedCaseDetails("case-b");
  rejectOld(new Error("old read failed"));
  await pending;
  assert.equal(panels["shared-case-detail"].children[0].text, "case-b");
});

test("旧 Case 执行闭包在选择变化后不发送业务请求", async () => {
  const {context, panels} = caseDetailHarness();
  context.api = async () => caseProjection("case-a");
  await context.loadSharedCaseDetails("case-a");
  const execute = panels["shared-case-detail"].children.find(item => item.label === "执行当前 Case");
  context.clearSharedCaseSelection();
  let writes = 0;
  context.api = async () => { writes += 1; };
  await assert.rejects(execute.action(), /已切换/);
  assert.equal(writes, 0);
});

test("本人生成目录包含新私有入口且过滤下游依赖", async () => {
  const context = scopeHarness(), paths = [];
  context.api = async path => {
    paths.push(path);
    return path.endsWith("view=mine") ? {items: [{operation_id: "facade:Mine#newEntry"}]} : {items: [
      {operation_id: "facade:Query#run"}, {operation_id: "dsf:other:query:list"},
      {operation_id: "mq:resource:queue:producer:send"}, {operation_id: "mq:Consumer"},
    ]};
  };
  for (const name of ["entryPlacement", "readSharedEntryCatalog"]) loadFunction(context, name);
  const entries = await context.readSharedEntryCatalog(context.sharedScope(), "mine");
  assert.deepEqual(Array.from(entries, item => [item.operation_id, item.knowledgeView]), [
    ["facade:Mine#newEntry", "mine"], ["facade:Query#run", "published"], ["mq:Consumer", "published"],
  ]);
  assert.equal(paths.length, 2);
  assert.ok(paths.every(path => path.includes("/baselines/base-a/")));
});

test("更换基准后生成目录重新读取，不复用非空旧目录", async () => {
  const context = scopeHarness(), paths = [];
  context.sharedWorkspace.operationViews = new Map([["facade:Old#run", "mine"]]);
  context.api = async path => { paths.push(path); return {items: [{operation_id: "facade:New#run"}]}; };
  for (const name of ["entryPlacement", "readSharedEntryCatalog"]) loadFunction(context, name);
  context.sharedWorkspace.baseline.baseline_id = "base-b";
  const entries = await context.readSharedEntryCatalog(context.sharedScope(), "published");
  assert.equal(entries[0].operation_id, "facade:New#run");
  assert.match(paths[0], /baselines\/base-b\/interfaces\?view=published/);
});

test("生成下拉按接口和类分层，不包含全部入口、下游或空分组", () => {
  const context = scopeHarness(), select = caseNode("select");
  context.document = {createElement: caseNode};
  context.Option = class {
    /** 保留生产下拉选项的可读标题与业务身份，供分层目录断言。 */
    constructor(text, value) { this.text = text; this.value = value; }
  };
  for (const name of ["entryPlacement", "appendOperationOptions"]) loadFunction(context, name);
  context.appendOperationOptions(select, ["facade:Query#run", "facade:Refund#cancel", "database:orders", "dsf:app:query:list"], new Map());
  assert.deepEqual(select.children.map(group => group.label), ["接口 / Query", "接口 / Refund"]);
  assert.ok(select.children.every(group => group.children.length === 1 && group.children[0].value));
});

/**
 * 构造生成弹框需要的选项默认值和事件记录，使测试执行实际提交门禁而非复制判断公式。
 * @param {string} tag 节点标签。
 * @param {string} text 节点文本。
 * @param {string} className 可选样式名称，用于定位部署提示。
 * @returns {object} 支持分组选项和手动事件触发的最小 DOM 节点。
 */
function generationDialogNode(tag, text = "", className = "") {
  const node = caseNode(tag, text);
  node.className = className;
  node.listeners = {};
  if (tag === "input") node.checked = false;
  /** 记录生产回调，测试可模拟用户真正切换生成方式。 */
  node.addEventListener = function (name, action) { this.listeners[name] = action; };
  if (tag === "select") {
    // 原生 select 默认选中首个选项，且 options 会平铺 optgroup 下的选项。
    let selected;
    Object.defineProperty(node, "options", {
      /** 返回按可见顺序平铺的实际分组选项。 */
      get() { return this.children.flatMap(child => child.tag === "optgroup" ? child.children : [child]); },
    });
    Object.defineProperty(node, "value", {
      /** 未手动选择时按浏览器默认行为返回首项。 */
      get() { return selected ?? this.options[0]?.value ?? ""; },
      /** 保存测试模拟的用户选择，供生产回调读取。 */
      set(value) { selected = value; },
    });
  }
  return node;
}

/**
 * 运行真实生成弹框，截获确认按钮规则和模式切换回调，不发起任务或业务请求。
 * @returns {{context: object, state: object}} 页面状态与可操控的弹框节点。
 */
function generationDialogHarness() {
  const context = scopeHarness(), state = {nodes: [], refreshCount: 0, dialog: null};
  const filter = generationDialogNode("select"); filter.value = "facade:Query#run";
  Object.assign(context, {currentSystem: {coverage_assistance: {enabled: true}},
    document: {querySelector: () => ({id: "workspace-regression-cases"}),
      /** 记录表单控件，测试只通过生产注册的事件模拟交互。 */
      createElement(tag) { const node = generationDialogNode(tag); state.nodes.push(node); return node; }},
    textNode: generationDialogNode, element: () => filter,
    readSharedEntryCatalog: async () => [{operation_id: "facade:Query#run", knowledgeView: "published"}],
    entrySummary: () => "查询入口", baselineDisplayName: () => "测试基准", baselineShortCommit: () => "test",
    sharedDeploymentNotice: () => "确认部署", selectSharedOperation: () => {},
    /** 只保存实际弹框配置；关闭结果防止本测试启动生成工作流。 */
    openDialog(config) { state.dialog = config; return {result: Promise.resolve(false), refresh: () => { state.refreshCount += 1; }}; },
    Option: class {
      /** 保存原生选项的标签和身份，供真实生成方式选择读取。 */
      constructor(text, value) { this.text = text; this.value = value; }
    },
  });
  // 入口分层也运行生产实现，避免缺少可选入口让门禁测试误通过。
  for (const name of ["entryPlacement", "sharedCaseBrowseEntries", "appendOperationOptions", "openCaseGenerationDialog"]) loadFunction(context, name);
  return {context, state};
}

test("有效知识目录移除入口后，授权历史 Case 仍可选择且不能生成或执行", async () => {
  const {context, panels} = caseDetailHarness();
  const oldCase = {...caseProjection("old-case"), operation_id: "facade:Retired#run", impact_status: "INTERFACE_REMOVED", view: "published"};
  const generateButton = generationDialogNode("button", "生成 Case");
  for (const id of ["shared-case-operation", "case-operation", "case-entry-select", "shared-case-actions", "shared-case-tree", "shared-case-entry-search", "shared-case-search", "shared-case-list", "shared-publish-cases", "shared-refresh-history", "shared-refresh-coverage", "shared-history-case", "shared-coverage-case"]) {
    panels[id] = generationDialogNode(id.includes("operation") || id.endsWith("-select") || id.endsWith("-case") ? "select" : "div");
  }
  panels["shared-case-actions"].querySelector = () => generateButton;
  Object.assign(context, {textNode: generationDialogNode,
    document: {getElementById: id => panels[id], createElement: generationDialogNode},
    sharedButton: (label, action, style) => Object.assign(generationDialogNode("button", label, style), {label, action}),
    Option: class {
      /** 保留真实业务选择身份与标签，不补充被知识目录删除的选项。 */
      constructor(text, value) { this.text = text; this.value = value; }
    },
    /** 模拟授权 API 的实际投影：目录不含删除入口，但历史 Case 仍携带移除影响状态。 */
    api: async path => {
      if (path.endsWith("/cases?view=published")) return {items: [oldCase]};
      if (path.endsWith("/interfaces?view=published")) return {items: [{operation_id: "facade:Query#run"}]};
      if (path.includes("/cases/old-case?")) return oldCase;
      throw new Error(`unexpected read: ${path}`);
    },
  });
  // 运行实际目录合并、下拉渲染、具体入口选择和详情逻辑，而非单独断言补项算法。
  for (const name of ["sharedCaseValueLabel", "sharedCaseVariationNames", "sharedCaseGroups", "entryPlacement", "entrySummary", "entryGroup", "readSharedEntryCatalog", "sharedCaseBrowseEntries", "appendOperationOptions", "renderSharedCaseTree", "renderSharedCases", "selectSharedOperation", "loadSharedCaseWorkspace"]) loadFunction(context, name);
  await context.loadSharedCaseWorkspace("old-case");
  assert.equal(panels["shared-case-operation"].value, "facade:Retired#run");
  assert.match(panels["shared-case-operation"].options.find(option => option.value === "facade:Retired#run").text, /入口已移除/);
  assert.equal(panels["shared-history-case"].value, "old-case");
  assert.equal(context.sharedWorkspace.selectedCase.case_id, "old-case");
  assert.equal(generateButton.disabled, true);
  assert.equal(panels["shared-case-detail"].children.find(node => node.label === "执行当前 Case").disabled, true);
  assert.equal(panels["shared-case-detail"].children.find(node => node.label === "基于此 Case 重新生成草稿").disabled, true);
  const generationEntries = await context.readSharedEntryCatalog(context.sharedScope(), "published");
  assert.deepEqual(Array.from(generationEntries, entry => entry.operation_id), ["facade:Query#run"]);
  assert.equal(context.sharedWorkspace.operationViews.has("facade:Retired#run"), false);
  // 覆盖栏目仍可读取历史，但不能通过增强按钮重新执行业务目标。
  context.api = async () => ({coverage_assistance: null});
  for (const name of ["sharedCoverageReason", "loadSharedCoverage"]) loadFunction(context, name);
  await context.loadSharedCoverage(oldCase, context.sharedScope());
  assert.equal(panels["shared-case-coverage"].children.find(node => node.label === "执行我的覆盖增强").disabled, true);
});

test("生成弹框仅验证模式要求部署确认，模式切换刷新真实提交门禁", async () => {
  const {context, state} = generationDialogHarness();
  await context.openCaseGenerationDialog();
  const mode = state.nodes.filter(node => node.tag === "select")[1];
  const check = state.nodes.find(node => node.type === "checkbox");
  const notice = state.dialog.body.children.find(node => node.className === "dialog-check");
  assert.equal(mode.value, "generate_and_verify");
  assert.equal(state.dialog.canConfirm(), false);
  assert.equal(notice.hidden, false);
  const before = state.refreshCount;
  mode.value = "generate_only"; mode.listeners.change();
  assert.equal(state.refreshCount, before + 1);
  assert.equal(notice.hidden, true);
  assert.equal(state.dialog.canConfirm(), true);
  // 即使隐藏控件仍保留旧勾选，纯生成也不能保存部署预确认供后续执行复用。
  check.checked = true;
  await state.dialog.onConfirm();
  assert.equal(context.sharedWorkspace.deploymentPreconfirmed, null);
  assert.equal(context.sharedWorkspace.generationSelection.executionMode, "generate_only");
  mode.value = "generate_and_verify"; check.checked = false; mode.listeners.change();
  assert.equal(notice.hidden, false);
  assert.equal(state.dialog.canConfirm(), false);
  check.checked = true; check.listeners.change();
  assert.equal(state.dialog.canConfirm(), true);
  await state.dialog.onConfirm();
  assert.equal(context.sharedWorkspace.deploymentPreconfirmed.baselineId, "base-a");
  assert.equal(context.sharedWorkspace.generationSelection.executionMode, "generate_and_verify");
});

test("执行记录只展示实际请求响应与断言，不转储内部证据", () => {
  const context = scopeHarness(), container = caseNode();
  Object.assign(context, {textNode: caseNode, document: {createElement: caseNode}});
  loadFunction(context, "renderSharedExecutionResults");
  context.renderSharedExecutionResults(container, [{status: "COMPLETED", environment_id: "qa", execution_id: "internal-id",
    variant_result: {status: "COMPLETED", secret_evidence: "DO-NOT-RENDER", assertions: [{passed: true, actual_path: "$.success"}],
      operations: [{phase: "TARGET", stage_id: "target", status: "COMPLETED", actual_request: {pageSize: 10}, actual_response: {success: true}}]}}]);
  const output = JSON.stringify(container);
  assert.match(output, /实际请求/); assert.match(output, /实际响应/);
  assert.match(output, /pageSize/); assert.match(output, /success/);
  assert.doesNotMatch(output, /DO-NOT-RENDER|执行证据|internal-id/);
  const step = container.children[0].children.find(item => item.tag === "details");
  assert.notEqual(step.open, true);
  assert.ok(step.children.filter(item => item.tag === "details").every(item => item.open !== true));
});

test("无效覆盖测量即使携带计数也不能显示为有效零覆盖", async () => {
  const {context, children} = coverageHarness("COMPLETED", "VALID");
  context.api = async () => ({coverage_assistance: {status: "COMPLETED", baseline: {status: "INVALID", analysis: {scope_counts: {
    method: {covered: 0, missed: 2}, line: {covered: 0, missed: 8}, branch: {covered: 0, missed: 3},
  }}}}});
  await context.loadSharedCoverage({case_id: "case-a", generation_id: "generation-a", view: "published"}, context.sharedScope());
  assert.ok(children.some(item => /第一次测量：尚无有效计数/.test(item.text)));
  assert.ok(children.every(item => !/方法 0 已覆盖/.test(item.text)));
});

test("同一场景的状态子用例按模板归组并标出变化参数", () => {
  const context = scopeHarness();
  for (const name of ["sharedCaseValueLabel", "sharedCaseVariationNames", "sharedCaseGroups"]) loadFunction(context, name);
  const cases = [
    {generation_id: "generation-a", template_id: "cancel_allowed_states", title: "取消成功",
      variant: {ordinal: 2, parameter_values: {state: {code: 2, name: "WAIT_REFUND"}}}},
    {generation_id: "generation-a", template_id: "cancel_allowed_states", title: "取消成功",
      variant: {ordinal: 5, parameter_values: {state: {code: 0, name: "PENDING_APPLY"}}}},
    {generation_id: "generation-a", template_id: "cancel_rejected_states", title: "拒绝取消",
      variant: {ordinal: 7, parameter_values: {state: {code: 7, name: "REFUND_DONE"}}}},
  ];
  const groups = context.sharedCaseGroups(cases);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].items.length, 2);
  assert.deepEqual([...context.sharedCaseVariationNames(groups[0].items)], ["state"]);
  assert.equal(context.sharedCaseValueLabel({code: 2, name: "WAIT_REFUND"}), "WAIT_REFUND（2）");
  assert.equal(groups[0].items[1].variant.ordinal, 5);
});

test("同场景多子用例先显示场景行，展开后才显示状态变体", () => {
  const ids = ["shared-case-operation", "shared-case-search", "shared-case-list",
    "shared-history-case", "shared-coverage-case", "shared-refresh-history", "shared-refresh-coverage"];
  const panels = Object.fromEntries(ids.map(id => [id, caseNode()]));
  panels["shared-case-operation"].value = "facade:Query#run";
  panels["shared-case-search"].value = "";
  const context = scopeHarness();
  const cases = [
    {case_id: "case-a", operation_id: "facade:Query#run", title: "取消成功", generation_id: "generation-a", template_id: "cancel_allowed_states",
      variant: {ordinal: 2, parameter_values: {state: {code: 2, name: "WAIT_REFUND"}}}},
    {case_id: "case-b", operation_id: "facade:Query#run", title: "取消成功", generation_id: "generation-a", template_id: "cancel_allowed_states",
      variant: {ordinal: 5, parameter_values: {state: {code: 0, name: "PENDING_APPLY"}}}},
  ];
  Object.assign(context.sharedWorkspace, {caseView: "mine", caseTab: "cases", selectedCase: null, cases});
  Object.assign(context, {
    element: id => panels[id],
    document: {getElementById: id => panels[id], createElement: caseNode},
    textNode: caseNode,
    sharedButton: (label, action) => ({tag: "button", text: label, action, children: [], appendChild(item) { this.children.push(item); }}),
    addSharedDraftActions(container) { container.children.push({tag: "button", text: "发布"}); },
    loadSharedCaseDetails: async () => {},
    clearSharedCaseSelection: () => {},
    Option: function (text) { return caseNode("option", text); },
    sharedStatus: status => status,
  });
  for (const name of ["sharedCaseGroups", "sharedCaseVariationNames", "sharedCaseValueLabel", "renderSharedCases"]) loadFunction(context, name);
  context.renderSharedCases();
  const body = panels["shared-case-list"].children[0].children[1];
  assert.equal(body.children.length, 3);
  assert.equal(body.children[0].className, "shared-case-group-row");
  assert.equal(body.children[0].children[0].children[0].text, "▸ 取消成功");
  assert.equal(body.children[1].hidden, true);
  assert.equal(body.children[2].hidden, true);
  assert.match(body.children[1].children[0].children[0].text, /state：WAIT_REFUND（2）/);
});
