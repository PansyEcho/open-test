"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("opentest/web/shared-workspace.js", "utf8");

/** 从指定脚本提取实际函数，在隔离上下文检查请求身份；找不到函数时立即失败。 */
function load(context, name, script = source) {
  // 允许同一测试组合 app 请求入口与共享目录函数，不启动页面或真实后台任务。
  const start = script.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1);
  const end = script.indexOf("\n/**", start);
  vm.runInContext(script.slice(start, end < 0 ? undefined : end), context);
}

/** 模拟同一标签页重载时保留的会话存储，不含真实凭据。 */
function harness(storage) {
  const context = vm.createContext({sharedWorkspace: {baseline: {baseline_id:"base"}, environment:"qa", caseView:"mine", requests:new Map()},
    systemId:()=>"system", systemRequestGeneration:1, window:{OpenTestAuth:{state:{employee:{user_id:"owner"}}}},
    sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    crypto:{randomUUID:()=>`request-${storage.size}`}});
  for (const name of ["sharedScope", "sharedRequestId", "completeSharedRequest"]) load(context, name);
  return context;
}

/** 结果未知后的刷新必须复用原身份，其他员工和视图不能继承。 */
test("unknown write request survives refresh and is owner/scope isolated", () => {
  const storage = new Map();
  const first = harness(storage), original = first.sharedRequestId("execute:case:gen:variant");
  const refreshed = harness(storage);
  assert.equal(refreshed.sharedRequestId("execute:case:gen:variant"), original);
  refreshed.sharedWorkspace.caseView = "published";
  assert.notEqual(refreshed.sharedRequestId("execute:case:gen:variant"), original);
  refreshed.window.OpenTestAuth.state.employee.user_id = "other";
  assert.notEqual(refreshed.sharedRequestId("execute:case:gen:variant"), original);
});

/** 确认响应后按发起时范围清理，不能误删另一个环境的待确认请求。 */
test("known receipt clears only its frozen request scope", () => {
  const storage = new Map(), context = harness(storage);
  context.sharedRequestId("execute:case:gen:variant");
  const originalScope = context.sharedScope();
  context.sharedWorkspace.environment = "uat";
  const otherRequest = context.sharedRequestId("execute:case:gen:variant");
  context.completeSharedRequest("execute:case:gen:variant", originalScope);
  assert.equal(storage.size, 1);
  assert.equal(context.sharedRequestId("execute:case:gen:variant"), otherRequest);
});

/** 同名独立批次有可读区别；旧记录不能伪造开始和结束。 */
test("batch labels preserve origin and unknown lifecycle", () => {
  const context = vm.createContext({}); load(context, "sharedCaseBatchLabel");
  const label = context.sharedCaseBatchLabel({generation_id:"generation-12345678",origin_kind:"COVERAGE_REUSED"});
  assert.match(label,/基础复测/); assert.match(label,/12345678/);
  assert.match(label,/开始时间未记录/); assert.match(label,/结束时间未记录/);
});

/**
 * 为顶部生成构造网络结果未知的真实入口测试，不接触模型、业务或浏览器存储。
 * @param {Map} storage 模拟跨刷新保留的本标签页请求身份。
 * @param {Array} requests 收集实际序列化后的请求，供检查完整接口范围。
 * @returns {object} 可执行生产 startCaseGeneration 的隔离上下文。
 */
function generationStartHarness(storage, requests) {
  const scope = {systemId:"system", baselineId:"base", environment:"qa", generation:1};
  const context = harness(storage), nodes = new Map();
  context.window.sessionStorage = context.sessionStorage;
  context.window.crypto = context.crypto;
  Object.assign(context, {captureSystemScope:()=>scope, sharedScope:()=>scope, sharedScopeCurrent:()=>true,
    isCurrentSystemScope:()=>true, document:{querySelector:()=>({})}, currentSystem:{coverage_assistance:{enabled:false}},
    element:id=>{if (!nodes.has(id)) nodes.set(id,{value:"entry"}); return nodes.get(id);},
    stopCaseHandoffPolling(){}, caseRequestGeneration:1, renderSharedCaseTasks(){},
    api:async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});throw new Error("result unknown");}});
  // 列表筛选故意与接口全量范围不一致，证明请求没有把当前可见成员作为替换集合。
  context.sharedWorkspace.generationSelection = {scope, operationId:"entry", view:"mine", executionMode:"generate_only"};
  context.sharedWorkspace.caseBatch = "old-filtered-batch";
  context.sharedWorkspace.cases = [{case_id:"only-visible-case"}];
  const script = fs.readFileSync("opentest/web/app.js", "utf8");
  for (const name of ["getOrCreateCaseRequestId", "startCaseGeneration"]) load(context, name, script);
  return context;
}

/** 顶部替换请求不能继承旧追加请求，但自己的未知结果必须跨刷新复用同一身份。 */
test("regeneration replaces all own drafts and isolates its retry identity from append", async () => {
  const storage = new Map(), requests = [], first = generationStartHarness(storage, requests);
  const legacyIdentity = "base:entry:qa:mine:generate_only";
  const legacyRequest = first.getOrCreateCaseRequestId("start", legacyIdentity);
  await assert.rejects(first.startCaseGeneration(), /result unknown/);
  const refreshed = generationStartHarness(storage, requests);
  await assert.rejects(refreshed.startCaseGeneration(), /result unknown/);
  assert.equal(requests[0].body.replace_existing_drafts, true);
  assert.equal(requests[0].body.request_id, requests[1].body.request_id);
  assert.notEqual(requests[0].body.request_id, legacyRequest);
  assert.equal(requests[0].body.operation_id, "entry");
  assert.equal(requests[0].body.baseline_id, "base");
  assert.equal(requests[0].body.environment_id, "qa");
  assert.equal(requests[0].body.execution_mode, "generate_only");
  assert.equal(requests[0].body.view, "mine");
  assert.ok(!("case_selection" in requests[0].body) && !("generation_id" in requests[0].body) && !("search" in requests[0].body));
  assert.equal(storage.size, 2);
});

/** 只对明确替换本人草稿的 Case 任务说明部分结果保留旧稿，其他任务保持原状态文案。 */
test("partial regeneration reports retained drafts without claiming publication", () => {
  const context = vm.createContext({}), script = fs.readFileSync("opentest/web/app.js", "utf8");
  for (const name of ["isCaseGenerationTask", "codexTaskStatusLabel"]) load(context, name, script);
  const replacement = {operation:"case-generation", status:"partial", result:{case_request:{replace_existing_drafts:true}}};
  assert.equal(context.codexTaskStatusLabel(replacement), "部分完成，原草稿保留");
  // 旧字段、普通生成和其他类型不能被页面猜测成已经保留了整批旧草稿。
  assert.equal(context.codexTaskStatusLabel({...replacement,result:{}}), "部分发布");
  assert.equal(context.codexTaskStatusLabel({...replacement,result:{replace_existing_drafts:true}}), "部分发布");
  assert.equal(context.codexTaskStatusLabel({...replacement,result:{case_request:{replace_existing_drafts:false}}}), "部分发布");
  assert.equal(context.codexTaskStatusLabel({...replacement,operation:"knowledge-target-generation"}), "部分发布");
});
