"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const app = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/app.js"), "utf8");

/** 按文档边界提取生产函数；只跳过浏览器启动，不替换权限逻辑。 */
function sourceFunction(name) {
  const start = app.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1, name);
  return app.slice(start, app.indexOf("\n/**", start));
}

/** 创建可触发真实事件的最小DOM节点，保留开关属性和渲染结构。 */
function fakeNode(tag = "", text = "") {
  return {
    tag, text, children: [], dataset: {}, attrs: {}, events: {}, hidden: false,
    /** 追加顺序对应页面展示顺序。 */
    append(...items) { this.children.push(...items); },
    /** 生产代码兼容的单节点追加。 */
    appendChild(item) { this.children.push(item); },
    /** 替换旧子节点，避免测试保留已移除控件。 */
    replaceChildren(...items) { this.children = items; },
    /** 保留回调供测试模拟交互。 */
    addEventListener(name, fn) { this.events[name] = fn; },
    /** 按DOM字符串语义记录无障碍状态。 */
    setAttribute(key, value) { this.attrs[key] = String(value); },
    /** 读取当前开关状态。 */
    getAttribute(key) { return this.attrs[key]; },
    /** 使用实际事件处理器，不伪造业务状态。 */
    click() { if (!this.disabled) return this.events.click?.(); },
  };
}

/** 构建读写混合目录；隐藏写接口用于检验一键全开的范围。 */
function detailFixture() {
  return {policy: {read_enabled: false, source_scan_allowed: true, db_read: false,
    db_create: false, db_update: false, db_delete: false, db_tables: []}, interfaces: [
    {operation_id: "read", method_name: "queryOrder", interface_name: "BookingFacade", mutability: "READ_ONLY", referenced: true},
    {operation_id: "write", method_name: "createOrder", interface_name: "BookingFacade", mutability: "WRITE", referenced: false},
  ]};
}

/** 创建隔离页面状态和真实函数；返回可替换API的VM，不发网络请求。 */
function harness() {
  const nodes = new Map();
  const summary = {system_key: "booking", display_name: "SaaS出票核心", registered_system_id: "booking",
    roles: ["upstream", "downstream"], channels: ["dsf.booking"], interface_count: null, referenced_count: 1};
  const catalog = {system_id: "refund", environment_id: "qa", revision: 0, systems: [summary]};
  const requests = [], notices = [];
  const context = vm.createContext({
    structuredClone, Map, Set, JSON, dynamicHelpSequence: 0,
    dependencyAccessCatalog: null, dependencyAccessRelations: {}, dependencyAccessEpoch: 0, dependencyAccessSaving: false,
    dependencyAccessDetails: new Map(), dependencyAccessDrafts: new Map(), dependencyAccessShowAll: new Set(), dependencyAccessExpanded: new Set(),
    currentExternalSystems: [],
    /** 为每个页面ID保留稳定节点。 */
    element(id) { if (!nodes.has(id)) nodes.set(id, fakeNode()); return nodes.get(id); },
    captureSystemScope: () => ({systemId: "refund", generation: 1}), isCurrentSystemScope: () => true,
    textNode: fakeNode, document: {createElement: fakeNode}, showToast: (...args) => notices.push(args),
    appendDependencyEvidence: () => {},
    /** 记录每个读取/保存，模拟真实接口分支。 */
    api: async (url, options) => { requests.push({url, options});
      if (url.includes("/relations")) return {};
      if (url.includes("/interfaces?")) return detailFixture();
      return structuredClone(catalog); },
  });
  context.element("dependency-access-environment").value = "qa";
  for (const name of ["loadDependencies", "isCurrentDependencyScope", "renderDependencyAccess", "loadDependencyAccessDetail",
    "dependencySwitch", "dependencyPolicy", "appendDependencyDataPermissions", "renderDependencyAccessDetail",
    "updateDependencyActions", "saveDependencyAccess", "cancelDependencyAccess"]) vm.runInContext(sourceFunction(name), context);
  return {context, catalog, summary, requests, notices};
}

/** 展平结构用于查找真实按钮，不依赖脆弱的CSS或节点下标。 */
function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }

/** 目录加载必须只读摘要，同一上下游系统只出现一张卡片。 */
test("canonical card is collapsed and interfaces are lazy", async () => {
  const {context, requests} = harness();
  await context.loadDependencies();
  assert.equal(requests.length, 2);
  const cards = context.element("dependency-list").children;
  assert.equal(cards.length, 1);
  assert.equal(cards[0].children[1].hidden, true);
  assert.match(JSON.stringify(cards), /上游 \/ 下游/);
  await context.loadDependencyAccessDetail("booking", cards[0].children[1], {system_key: "booking"},
    {systemId: "refund", generation: 1, environment: "qa", dependencyEpoch: 1});
  assert.equal(requests.length, 3);
});

/** 全开包含隐藏写接口，不修改数据库；筛选和折叠不丢草稿，取消恢复原值。 */
test("all on includes writes, keeps database settings and supports cancellation", async () => {
  const {context, summary, catalog} = harness();
  context.dependencyAccessCatalog = catalog;
  const detail = detailFixture(), body = fakeNode();
  context.dependencyAccessDetails.set("booking", structuredClone(detail));
  context.dependencyAccessDrafts.set("booking", detail);
  context.renderDependencyAccessDetail(body, summary, detail, {});
  assert.ok(!JSON.stringify(body).includes('"text":"createOrder"'));
  descendants(body).find(node => node.text.startsWith("全部开启")).click();
  const policy = context.dependencyPolicy(detail);
  assert.deepEqual(Array.from(policy.allowed_read_operation_ids), ["read"]);
  assert.deepEqual(Array.from(policy.allowed_write_operation_ids), ["write"]);
  assert.equal(policy.db_create, false);
  assert.equal(context.updateDependencyActions().length, 1);
  descendants(body).find(node => node.text.startsWith("展示全部接口")).click();
  assert.equal(context.dependencyAccessDrafts.get("booking").interfaces[1].write_allowed, true);
  context.cancelDependencyAccess();
  assert.equal(context.updateDependencyActions().length, 0);
});

/** 环境切换/刷新不会销毁草稿；未保存时提示保存或取消。 */
test("dirty draft prevents refresh and cross-environment save", async () => {
  const {context, catalog, requests, notices} = harness();
  context.dependencyAccessCatalog = catalog;
  const saved = detailFixture(), draft = structuredClone(saved);
  draft.interfaces[1].write_allowed = true;
  context.dependencyAccessDetails.set("booking", saved);
  context.dependencyAccessDrafts.set("booking", draft);
  context.element("dependency-access-environment").value = "uat";
  assert.equal(await context.loadDependencies(), false);
  assert.equal(requests.length, 0);
  assert.equal(context.element("dependency-access-environment").value, "qa");
  assert.equal(context.updateDependencyActions().length, 1);
  assert.match(notices[0][0], /先保存或取消/);
});

/** 并发请求返回顺序不决定当前环境，QA迟到响应不能覆盖UAT。 */
test("late environment response cannot replace current catalog", async () => {
  const {context, catalog} = harness();
  let resolveQa;
  context.api = async (url) => {
    if (url.includes("relations")) return {};
    if (url.includes("environment=qa")) return new Promise(resolve => { resolveQa = resolve; });
    return {...catalog, environment_id: "uat"};
  };
  const qa = context.loadDependencies();
  context.element("dependency-access-environment").value = "uat";
  await context.loadDependencies();
  resolveQa(catalog);
  assert.equal(await qa, false);
  assert.equal(context.dependencyAccessCatalog.environment_id, "uat");
});

/** 保存失败不清掉草稿或伪装成功；重新提交使用原revision。 */
test("save failure retains draft and successful retry clears dirty state", async () => {
  const {context, catalog, notices} = harness();
  context.dependencyAccessCatalog = catalog;
  const saved = detailFixture(), draft = structuredClone(saved);
  draft.interfaces[1].write_allowed = true;
  context.dependencyAccessDetails.set("booking", saved);
  context.dependencyAccessDrafts.set("booking", draft);
  context.api = async () => { throw new Error("save unavailable"); };
  await context.saveDependencyAccess();
  assert.equal(context.updateDependencyActions().length, 1);
  assert.match(notices[0][0], /保存失败/);
  context.api = async (url, options) => {
    assert.match(url, /environment=qa/);
    const body = JSON.parse(options.body);
    assert.equal(body.expected_revision, 0);
    return {policy: {...body.policy, revision: 1}};
  };
  await context.saveDependencyAccess();
  assert.equal(context.updateDependencyActions().length, 0);
  assert.equal(context.dependencyAccessCatalog.revision, 1);
});
