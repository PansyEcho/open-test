"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const app = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/app.js"), "utf8");
const start = app.indexOf("async function continueTaskInCodex(");
const handoffSource = app.slice(start, app.indexOf("\n/**", start));
const deepLink = "codex://threads/01a0ae74-0512-79c3-959a-aea3f2b88505";

/** 为真实接续函数提供隔离HTTP与导航；返回上下文和完整请求缓存以验证重放。 */
function sandbox(api, loadTaskCatalog = async () => {}) {
  const stored = new Map();
  const location = {href:""};
  const context = vm.createContext({api,loadTaskCatalog,
    captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,
    window:{location,crypto:{randomUUID:()=>"request-1"},sessionStorage:{getItem:(key)=>stored.get(key),setItem:(key,value)=>stored.set(key,value),removeItem:(key)=>stored.delete(key)}},
  });
  vm.runInContext(handoffSource, context);
  return {context,location,stored};
}

/** 接续请求完成之前不能打开Codex；导航只能使用成功回执中的同一会话。 */
test("native handoff succeeds before navigation", async () => {
  let release;
  const requests = [];
  const state = sandbox(async (url, options) => {
    requests.push({url, options});
    if (url.endsWith("/context")) return {context:{revision:2}};
    return new Promise((resolve)=>{release=resolve;});
  });
  const pending = vm.runInContext("continueTaskInCodex({task_id:'task-1'})", state.context);
  await new Promise(setImmediate);
  assert.equal(state.location.href, "");
  assert.equal(requests[1].options.method, "POST");
  assert.deepEqual(JSON.parse(requests[1].options.body), {request_id:"native-request-1",expected_revision:2});
  release({deep_link:deepLink});
  await pending;
  assert.equal(state.location.href, deepLink);
  assert.equal(state.stored.size, 0);
});

/** 网络丢响应保留原revision和请求身份；明确的409拒绝不得跳转。 */
test("unknown response replays exact handoff and explicit refusal does not navigate", async () => {
  const bodies = [];
  let contextReads = 0;
  const state = sandbox(async (url, options) => {
    if (url.endsWith("/context")) {contextReads++;return {context:{revision:2}};}
    bodies.push(options.body);
    if (bodies.length === 1) throw new Error("lost response");
    return {deep_link:deepLink};
  });
  await assert.rejects(vm.runInContext("continueTaskInCodex({task_id:'task-1'})", state.context), /lost response/);
  assert.equal(state.location.href, "");
  await vm.runInContext("continueTaskInCodex({task_id:'task-1'})", state.context);
  assert.equal(contextReads, 1);
  assert.equal(bodies[0], bodies[1]);
  const rejected = sandbox(async (url) => {
    if (url.endsWith("/context")) return {context:{revision:2}};
    throw Object.assign(new Error("worker active"), {httpStatus:409});
  });
  await assert.rejects(vm.runInContext("continueTaskInCodex({task_id:'task-1'})", rejected.context), /worker active/);
  assert.equal(rejected.location.href, "");
  assert.equal(rejected.stored.size, 0);
});

/** 刷新目录期间切换系统必须撤销迟到跳转，避免把用户带回旧系统任务。 */
test("system change during catalog refresh prevents late navigation", async () => {
  let current = true;
  const state = sandbox(async (url)=>url.endsWith("/context") ? {context:{revision:2}} : {deep_link:deepLink}, async()=>{current=false;});
  state.context.isCurrentSystemScope = ()=>current;
  await vm.runInContext("continueTaskInCodex({task_id:'task-1'})", state.context);
  assert.equal(state.location.href, "");
});
