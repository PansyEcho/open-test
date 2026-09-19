"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const app = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/app.js"), "utf8");

/** 提取真实页面函数，在隔离浏览器依赖下检查请求与竞争，不执行DOM初始化。 */
function sourceFunction(name) {
  const start = app.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1);
  return app.slice(start, app.indexOf("\n/**", start));
}

/** 创建页面输入和存储替身；所有请求由测试显式处理，绝不访问QA。 */
function executionSandbox(api) {
  const fields = {"data-execution-environment":{value:"qa"}, "data-capability-inputs":{value:'{"ticket_no":"requested","owner_id":"subject"}'}, "data-allow-writes":{checked:false}, "data-execution-status":{}};
  const stored = new Map();
  const context = vm.createContext({api, fields,
    element: (id) => fields[id], captureSystemScope: () => ({systemId:"refund"}), isCurrentSystemScope: () => true,
    selectedDataCapability:{capability_id:"refund_report",version:1},
    window:{crypto:{randomUUID:()=>"request"},sessionStorage:{getItem:(key)=>stored.get(key),setItem:(key,value)=>stored.set(key,value),removeItem:(key)=>stored.delete(key)}},
    loadDataCapabilities:async()=>{},loadTaskCatalog:async()=>{},openDataExecution:async()=>{},showBusinessTask:async()=>{},
  });
  vm.runInContext(sourceFunction("readJsonObject") + sourceFunction("executeDataCapability"), context);
  return {context, fields, stored};
}

/** 丢响应时重复点击必须重放相同请求；不得静默改变票号或产生第二个请求身份。 */
test("unknown execution response preserves exact inputs, version, write choice and request identity", async () => {
  const requests = [];
  const {context, fields, stored} = executionSandbox(async (url, options) => {
    requests.push({url, body:JSON.parse(options.body)});
    if (requests.length === 1) throw new Error("network lost after dispatch");
    return {execution:{execution_id:"execution-1"}};
  });
  await assert.rejects(vm.runInContext("executeDataCapability()", context), /network lost/);
  fields["data-capability-inputs"].value = '{"ticket_no":"another","owner_id":"subject"}';
  await assert.rejects(vm.runInContext("executeDataCapability()", context), /保持原输入/);
  assert.equal(requests.length, 1);
  fields["data-capability-inputs"].value = '{"ticket_no":"requested","owner_id":"subject"}';
  await vm.runInContext("executeDataCapability()", context);
  assert.deepEqual(requests[0], requests[1]);
  assert.equal(requests[1].body.version, 1);
  assert.equal(requests[1].body.allow_writes, false);
  assert.deepEqual(requests[1].body.inputs, {ticket_no:"requested",owner_id:"subject"});
  assert.equal(stored.size, 0);
});

/** JSON数组不能被误用为参数对象；错误在发出任何业务请求之前返回。 */
test("invalid input object never dispatches data preparation", async () => {
  let calls = 0;
  const {context, fields} = executionSandbox(async () => {calls++;});
  fields["data-capability-inputs"].value = "[]";
  await assert.rejects(vm.runInContext("executeDataCapability()", context), /JSON 对象/);
  assert.equal(calls, 0);
});

/** 后返回的旧能力详情不能覆盖用户已经选择的较新版本或系统。 */
test("late capability detail cannot replace a newer selection", async () => {
  const pending = [];
  const fields = {"data-capability-execute":{}};
  const context = vm.createContext({api:()=>new Promise((resolve)=>pending.push(resolve)),element:(id)=>fields[id],captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,selectedDataCapability:null,dataCapabilityDetailEpoch:0});
  vm.runInContext(sourceFunction("openDataCapability"), context);
  const older = vm.runInContext("openDataCapability('lookup',1)", context);
  vm.runInContext("dataCapabilityDetailEpoch++", context);
  pending[0]({capability:{capability_id:"lookup",version:1}});
  assert.equal(await older, false);
  assert.equal(vm.runInContext("selectedDataCapability", context), null);
  assert.equal(fields["data-capability-execute"].hidden, true);
});

/** 没有背景或内部知识节点时，入口仍可直接创建契约补充任务。 */
test("contract task does not create internal knowledge or depend on completed background", async () => {
  let request;
  const context = vm.createContext({api:async(url,options)=>{request={url,body:JSON.parse(options.body)};return{task:{task_id:"contract-1"}};},
    element:()=>({dataset:{targetId:"facade:RefundFacade#billSupplement"}}),captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,
    currentKnowledgeDetail:{target:{category:"facade"}},selectKnowledgeGenerationAttempt:()=>null,loadTaskCatalog:async()=>{},showBusinessTask:async()=>{},getOrCreateCaseRequestId:()=>"contract-request-001",clearCaseRequestId:()=>{},
  });
  vm.runInContext(sourceFunction("generateCurrentKnowledge"), context);
  await vm.runInContext("generateCurrentKnowledge()", context);
  assert.match(request.url, /data-capabilities\/prepare$/);
  assert.equal(request.body.kind, "contract");
  assert.equal(request.body.operation_id, "facade:RefundFacade#billSupplement");
});

/** 契约准备失败保留可见原因；系统切换后不显示旧请求的错误。 */
test("contract prepare failure remains visible only for its current system", async () => {
  const progress = {textContent:"等待操作"};
  const toasts = [];
  let current = true;
  const context = vm.createContext({
    api:async()=>{throw new Error("scan unavailable");},
    element:(id)=>id === "knowledge-task-progress" ? progress : {dataset:{targetId:"facade:RefundFacade#billSupplement"}},
    captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>current,
    currentKnowledgeDetail:{target:{category:"facade"}},selectKnowledgeGenerationAttempt:()=>null,
    getOrCreateCaseRequestId:()=>"contract-failure-request",showToast:(message,kind)=>toasts.push({message,kind}),
  });
  // 已捕获的服务错误不应再成为未处理Promise，且页面摘要在loading结束后仍可读取。
  vm.runInContext(sourceFunction("generateCurrentKnowledge"), context);
  await vm.runInContext("generateCurrentKnowledge()", context);
  assert.match(progress.textContent, /契约补充失败：.*scan unavailable/);
  assert.equal(toasts[0].kind, "error");
  current = false;
  progress.textContent = "新系统任务";
  await vm.runInContext("generateCurrentKnowledge()", context);
  assert.equal(progress.textContent, "新系统任务");
  assert.equal(toasts.length, 1);
});

/** 跨系统执行详情展示步骤实际路由，不能把调用方qa误显示为provider环境。 */
test("execution detail derives actual environments from recorded operations", async () => {
  const nodes = [];
  const execution = {capability_id:"lookup",capability_version:1,status:"COMPLETED",environment_id:"qa",step_results:[
    {stage_id:"data:query:report",system_id:"supplement",environment_id:"qa",environment_details:{config_environment:"test",routing_environment:"qa",target_environment:"test"},source_scan_id:"scan-a"},
    {stage_id:"data:verify:blocked",system_id:"supplement",environment_id:"",source_scan_id:""},
  ]};
  const context = vm.createContext({
    api:async()=>({execution}),captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,dataExecutionDetailEpoch:0,
    element:()=>({replaceChildren:()=>{nodes.length=0;},appendChild:(node)=>nodes.push(node),append:(...items)=>nodes.push(...items)}),
    textNode:(tag,text)=>({tag,text,addEventListener:()=>{}}),dataFailureLabel:()=>"",openDrawer:()=>{},
  });
  // 没有真实environment_id的阻断步骤不应虚构实际路由，完整证据仍保留在来源区。
  vm.runInContext(sourceFunction("executionEnvironmentLabel") + sourceFunction("openDataExecution"), context);
  assert.equal(await vm.runInContext("openDataExecution('execution-1')", context), true);
  const heading = nodes.findIndex((node)=>node.text === "实际执行环境");
  const recorded = JSON.parse(nodes[heading+1].text);
  assert.equal(recorded.length, 1);
  assert.equal(recorded[0].system_id, "supplement");
  assert.equal(recorded[0].logical_environment, "qa");
  assert.match(recorded[0].environment, /实际配置 test/);
  assert.match(recorded[0].environment, /DSF target test/);
  assert.equal(recorded[0].source_scan_id, "scan-a");
});

/** 历史test保持原值，实际资源环境不从逻辑qa或filter猜测。 */
test("environment details preserve logical, actual and historical identities", () => {
  const context = vm.createContext({});
  vm.runInContext(sourceFunction("executionEnvironmentLabel"), context);
  assert.match(vm.runInContext("executionEnvironmentLabel({environment_id:'test'})", context), /记录环境 test.*未记录/);
  const rendered = vm.runInContext("executionEnvironmentLabel({environment_id:'qa',environment_details:{config_environment:'dev',resource_environment:'isolated-qa'}})", context);
  assert.match(rendered, /逻辑环境 qa.*实际配置 dev.*资源环境 isolated-qa/);
  assert.doesNotMatch(rendered, /DSF target/);
});

/** 浏览器拒绝旧test执行选择，不猜测其对应哪份逻辑Profile。 */
test("legacy test environment cannot dispatch a new data execution", async () => {
  let calls = 0;
  const {context, fields} = executionSandbox(async () => {calls++;});
  fields["data-execution-environment"].value = "test";
  await assert.rejects(vm.runInContext("executeDataCapability()", context), /qa 或 uat/);
  assert.equal(calls, 0);
});

/** 构造独立QA/UAT输入，便于验证凭据不会在两个逻辑环境间复制。 */
function profileFields() {
  const fields = {"environment-profile-status":{textContent:""}};
  for (const environment of ["qa", "uat"]) {
    for (const field of ["config-environment", "labrador-token", "gateway-prefix"]) fields[`${environment}-${field}`] = {value:"",disabled:false};
    fields[`${environment}-profile-status`] = {textContent:""};
  }
  return fields;
}

/** 同一次保存使用两份明确环境，空UAT不创建Profile且不会触发扫描。 */
test("profile saves preserve independent environments without HTTP Job fields", async () => {
  const fields = profileFields();
  const requests = [];
  fields["qa-config-environment"].value = "test";
  fields["qa-labrador-token"].value = "qa-local-token";
  const context = vm.createContext({fields,element:(id)=>fields[id],api:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return{};},
    captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,systemFormMode:"edit",loadEnvironmentCatalog:async()=>true,
  });
  vm.runInContext(sourceFunction("readEnvironmentProfile") + sourceFunction("saveEnvironmentProfiles"), context);
  await vm.runInContext("saveEnvironmentProfiles()", context);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].body.environment, "qa");
  fields["uat-config-environment"].value = "dev";
  fields["uat-labrador-token"].value = "uat-local-token";
  await vm.runInContext("saveEnvironmentProfiles()", context);
  assert.equal(requests[2].body.environment, "uat");
  assert.equal(requests[2].body.resource_config_environment, "dev");
  assert.equal(requests[2].body.qa_labrador_token, undefined);
  assert.equal(requests[1].body.qa_gateway_prefix, undefined);
  assert.ok(requests.every((request)=>request.url === "/systems/refund/local-settings"));
});

/** UAT读取空缺或旧auto时保持空白，绝不展示QA凭据为UAT默认值。 */
test("profile reads use each logical environment and preserve unconfigured uat", async () => {
  const fields = profileFields();
  const urls = [];
  const context = vm.createContext({fields,element:(id)=>fields[id],captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,
    api:async(url)=>{urls.push(url);return{local_settings:url.endsWith("=qa")?{resource_config_environment:"test",qa_labrador_token:"qa-only"}:{resource_config_environment:"auto",available:false}};},
  });
  vm.runInContext(sourceFunction("loadEnvironmentProfiles"), context);
  await vm.runInContext("loadEnvironmentProfiles()", context);
  assert.deepEqual(urls, ["/systems/refund/local-settings?environment=qa", "/systems/refund/local-settings?environment=uat"]);
  assert.equal(fields["qa-config-environment"].value, "test");
  assert.equal(fields["uat-config-environment"].value, "");
  assert.equal(fields["uat-labrador-token"].value, "");
});

/** 新目录只呈现可用逻辑环境；历史test文件不能进入新执行选择器。 */
test("environment selectors ignore actual filter names and unavailable profiles", async () => {
  const selectors = Object.fromEntries(["resource-probe-environment", "case-execution-environment", "data-execution-environment"].map((id)=>[id,{value:"test",options:[],replaceChildren(...options){this.options=options;},appendChild(option){this.options.push(option);}}]));
  const context = vm.createContext({element:(id)=>selectors[id],captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,
    Option:function(text,value){this.text=text;this.value=value;},currentEnvironmentCatalog:[],currentCaseGeneration:null,renderCaseGeneration:()=>{},
    api:async()=>({environments:[{environment:"test"},{environment:"qa"},{environment:"uat",available:false}]})});
  vm.runInContext(sourceFunction("loadEnvironmentCatalog"), context);
  await vm.runInContext("loadEnvironmentCatalog()", context);
  for (const selector of Object.values(selectors)) {
    assert.deepEqual(Array.from(selector.options, (option)=>option.value), ["", "qa"]);
    assert.equal(selector.value, "qa");
  }
});

/** 系统目录保留上游深度，并展示未注册的直接下游而不扩大执行目录。 */
test("relations page renders bounded directions, source evidence and gaps", async () => {
  const nodes = [];
  const list = {replaceChildren(){nodes.length=0;},appendChild(node){nodes.push(node);}};
  const status = {textContent:""};
  const requests = [];
  const catalog = {upstream:[{system_id:"booking",depth:1}],downstream:[{system_id:"report",depth:2}],
    external_systems:[{gs_name:"dsf.resource.core",interfaces:[{operation_id:"external:resource#query"}]}],
    relations:[{source_system_id:"booking",target_system_id:"refund",relation_type:"DSF",evidence:[{system_id:"booking",source_scan_id:"scan-booking",source_ref:{path:"src/Client.java",line:12,symbol:"submit"},detail:"已确认DSF引用"}]},
      {source_system_id:"refund",target_system_id:"report",relation_type:"MQ",evidence:[]}],
    gaps:[{system_id:"report",code:"MISSING_TOPIC",message:"缺少Topic配置"}],};
  const context = vm.createContext({captureSystemScope:()=>({systemId:"refund"}),isCurrentSystemScope:()=>true,
    currentExternalSystems:[{gs_name:"historical-system"}],scanCatalog:null,renderKnowledgeTree:()=>{},
    element:(id)=>id === "dependency-list" ? list : status,
    textNode:(tag,text)=>({tag,text,children:[],append(...items){this.children.push(...items);},appendChild(item){this.children.push(item);}}),
    api:async(url,options)=>{requests.push({url,options});return catalog;},
  });
  vm.runInContext(sourceFunction("appendRelationEvidence") + sourceFunction("renderSystemRelations") + sourceFunction("loadDependencies"), context);
  await vm.runInContext("loadDependencies()", context);
  assert.deepEqual(requests, [{url:"/systems/refund/relations",options:undefined}]);
  const output = JSON.stringify(nodes);
  for (const content of ["上游", "下游", "第 1 层", "dsf.resource.core", "1 个引用接口", "DSF", "MQ", "src/Client.java:12", "scan-booking", "缺少Topic配置"]) assert.ok(output.includes(content));
  assert.ok(!output.includes("第 2 层"));
  // 系统关系始终读取latest；它不能覆盖知识库已选历史扫描的外部引用树。
  assert.equal(vm.runInContext("currentExternalSystems[0].gs_name", context), "historical-system");
});
