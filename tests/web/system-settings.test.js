"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const app = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/app.js"), "utf8");

/** 提取生产页面函数以复现异步响应竞争，返回不含初始化的函数源码。 */
function sourceFunction(name) {
  const start = app.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1);
  return app.slice(start, app.indexOf("\n/**", start));
}

/** 编辑B立即显示表单；环境请求未完成时切到C，迟到B不得改变C的编辑状态。 */
test("late edit cannot overwrite another system form", async () => {
  let finishProfiles;
  const fields = {};
  const context = vm.createContext({
    registeredSystems: [{system_id:"b", name:"B"}], currentSystem:{system_id:"a"}, systemFormMode:"view", systemRequestGeneration:0,
    environmentProfileSystemId:"", savedEnvironmentProfiles:{qa:"",uat:""},
    element: id => fields[id] || (fields[id] = {}),
    cancelSystemReads: () => {}, clearSystemWorkspaceState: () => {}, renderSystemSelector: () => {},
    window:{localStorage:{setItem:()=>{}}}, renderSystemFormMode: () => {},
    switchWorkspace: () => {throw new Error("迟到编辑不得导航");},
    loadEnvironmentProfiles: () => new Promise(resolve => {finishProfiles = resolve;}),
  });
  context.updateSystemContext = system => {context.currentSystem = system;};
  context.captureSystemScope = () => ({systemId:context.currentSystem.system_id, generation:context.systemRequestGeneration});
  context.isCurrentSystemScope = scope => scope.systemId === context.currentSystem.system_id && scope.generation === context.systemRequestGeneration;
  vm.runInContext(sourceFunction("beginEditSystem"), context);
  const pending = vm.runInContext("beginEditSystem('b')", context);
  assert.equal(fields["system-name"].value, "B");
  // 用户的后续系统选择拥有写页面资格，前一个环境响应只能结束自身等待。
  context.currentSystem = {system_id:"c"}; context.systemFormMode = "view";
  context.systemRequestGeneration += 1;
  fields["system-name"].value = "C";
  finishProfiles(); await pending;
  assert.equal(fields["system-name"].value, "C");
  assert.equal(context.systemFormMode, "view");
});

/** 旧auto配置允许只改名称而不覆盖环境；新建系统仍必须明确QA配置。 */
test("editing preserves unselected environment while creation requires QA", () => {
  const context = vm.createContext({systemFormMode:"edit", element:()=>({value:""})});
  vm.runInContext(sourceFunction("readEnvironmentProfile"), context);
  assert.equal(vm.runInContext("readEnvironmentProfile('qa')", context), null);
  context.systemFormMode = "create";
  assert.throws(()=>vm.runInContext("readEnvironmentProfile('qa')", context), /选择实际项目配置/);
});

/** 建立保存流程的最小页面，所有额外目录查询都会使测试失败。 */
function saveHarness(uat = "uat") {
  const fields = Object.fromEntries(Object.entries({"source-path":"/source/a", "source-revision":"", "system-id":"a", "system-name":"新名称", "qa-config-environment":"qa"}).map(([key,value]) => [key,{value}]));
  const requests = [], notices = [];
  const context = vm.createContext({
    systemFormMode:"edit", systemRequestGeneration:1, currentSystem:{system_id:"a",description:"原说明"},
    registeredSystems:[], savedEnvironmentProfiles:{qa:"qa",uat:"uat"}, environmentProfileSystemId:"a",
    element:id => fields[id] || (fields[id]={}), validateSystemForm:()=>true,
    readEnvironmentProfile:()=>({environment:"uat",resource_config_environment:uat}),
    renderSystemSelector:()=>{}, renderSystemList:()=>{}, renderSystemFormMode:()=>{}, render:()=>{},
    window:{localStorage:{setItem:()=>{}}}, showToast:message=>notices.push(message),
    renderError:(_id,error)=>notices.push(error.message),
    loadEnvironmentProfiles:()=>{throw new Error("保存不得重读环境");},
    loadScanCatalog:()=>{throw new Error("保存不得等待目录");},
    loadDependencies:()=>{throw new Error("保存不得等待关系");},
    api:async (path,options)=>{requests.push({path,body:JSON.parse(options.body)}); return {system:{system_id:"a",name:"新名称",description:"原说明"}};},
  });
  context.captureSystemScope=()=>({systemId:context.currentSystem.system_id,generation:context.systemRequestGeneration});
  context.isCurrentSystemScope=scope=>scope.generation===context.systemRequestGeneration && scope.systemId===context.currentSystem.system_id;
  context.updateSystemContext=system=>{context.currentSystem=system;};
  vm.runInContext(sourceFunction("saveSystem"),context);
  return {context,requests,notices,fields};
}

/** 名称编辑只等实际写入；未改的QA/UAT不提交，也不把目录读取绑定到保存按钮。 */
test("save exits edit immediately after its one actual write", async()=>{
  const {context,requests,fields}=saveHarness();
  await vm.runInContext("saveSystem()",context);
  assert.equal(requests.length,1);
  assert.equal(requests[0].path,"/systems/a");
  assert.equal(requests[0].body.resource_config_environment,undefined);
  assert.equal(context.systemFormMode,"view");
  assert.equal(fields["system-name"].value,"新名称");
});

/** 第二次写入失败须保留未保存环境，并清楚区分已成功保存的名称。 */
test("partial environment save remains editable and reports saved portion",async()=>{
  const {context,notices}=saveHarness("test");
  const original=context.api;
  context.api=async(path,options)=>{
    if(path.endsWith("local-settings")) throw new Error("UAT写入失败");
    return original(path,options);
  };
  await vm.runInContext("saveSystem()",context);
  assert.equal(context.systemFormMode,"edit");
  assert.equal(context.currentSystem.name,"新名称");
  assert.equal(context.savedEnvironmentProfiles.uat,"uat");
  assert.ok(notices.some(message=>message.includes("系统信息已保存；UAT")));
});

/** 同一GET只发一次；切换系统取消读请求，写请求不进入取消集合。 */
test("identical reads coalesce and system switch cancels only reads",async()=>{
  const calls=[];
  const context=vm.createContext({pendingReads:new Map(),systemRequestGeneration:1,AbortController,
    verifyCurrentPageVersion:async()=>true,
    performApiRequest:(_root,path,options)=>new Promise((resolve,reject)=>{
      calls.push({path,options,resolve});
      options.signal?.addEventListener("abort",()=>reject(new Error("cancelled")));
    }),
  });
  vm.runInContext(sourceFunction("apiFromRoot")+"\n"+sourceFunction("cancelSystemReads"),context);
  const first=vm.runInContext("apiFromRoot('/api','/tasks')",context);
  const second=vm.runInContext("apiFromRoot('/api','/tasks')",context);
  const write=vm.runInContext("apiFromRoot('/api','/systems/a',{method:'PUT'})",context);
  const settled=Promise.allSettled([first,second]);
  // VM中的async返回跨realm Promise，给版本检查完成一次事件循环，不使用固定延时。
  await new Promise(setImmediate);
  assert.equal(calls.length,2);
  vm.runInContext("cancelSystemReads()",context);
  assert.ok((await settled).every(result=>result.status==="rejected"));
  assert.equal(calls[1].options.signal,undefined);
  calls[1].resolve({saved:true}); await write;
});

/** 轮询必须等待请求结束；隐藏页面不再安排下一轮。 */
test("poll schedules only after completion and pauses when hidden",async()=>{
  let callback,finish; let scheduled=0;
  const document={hidden:false,querySelector:()=>({id:"workspace-tasks"})};
  const context=vm.createContext({document,taskPollTimer:null,systemId:()=>"a",
    window:{clearTimeout:()=>{},setTimeout:handler=>{callback=handler;scheduled+=1;return scheduled;}},
    loadTaskCatalog:()=>new Promise(resolve=>{finish=resolve;}),
    element:()=>({}),
  });
  vm.runInContext(sourceFunction("scheduleTaskPoll"),context);
  vm.runInContext("scheduleTaskPoll()",context);
  const pending=callback();
  assert.equal(scheduled,1);
  document.hidden=true; finish(); await pending;
  assert.equal(scheduled,1);
});

/** A环境写入期间切到B，成功响应只完成A的保存，不污染B差异比较使用的基线。 */
test("late environment save preserves the new system baseline", async()=>{
  let finish;
  const context=vm.createContext({currentSystem:{system_id:"a"},systemRequestGeneration:1,systemFormMode:"edit",
    savedEnvironmentProfiles:{qa:"qa",uat:""},environmentProfileSystemId:"a",
    captureSystemScope:()=>({systemId:"a",generation:1}),
    readEnvironmentProfile:environment=>environment==="qa"?{environment,resource_config_environment:"test"}:null,
    api:()=>new Promise(resolve=>{finish=resolve;}),element:()=>({}),
  });
  context.isCurrentSystemScope=scope=>scope.systemId===context.currentSystem.system_id;
  vm.runInContext(sourceFunction("saveEnvironmentProfiles"),context);
  const pending=vm.runInContext("saveEnvironmentProfiles()",context);
  context.currentSystem={system_id:"b"}; context.savedEnvironmentProfiles={qa:"dev",uat:""};
  finish({}); await pending;
  assert.equal(context.savedEnvironmentProfiles.qa,"dev");
});

/** 列表第2页没有正在跟踪的任务时，按ID刷新原任务而非绑定第2页的其他Case。 */
test("task pagination keeps the selected Case identity", async()=>{
  const calls=[];
  const selected={task_id:"selected",operation:"case-generation",active_handoff_id:"handoff-selected"};
  const context=vm.createContext({currentCaseTask:selected,currentTasks:[],activeCaseHandoffId:"handoff-selected",
    currentCaseInstruction:"",currentKnowledgeWorkflow:null,consolePages:{tasks:2},
    isCurrentSystemScope:()=>true,renderConsolePager:()=>{},renderWorkbenchTasks:()=>{},
    renderCodexTaskPane:()=>{},renderSelectedKnowledgeGenerationAttempt:()=>{},
    taskContinuationInstruction:()=>"",element:()=>({}),
    api:async path=>{calls.push(path);return path.startsWith("/tasks?")?{tasks:[{task_id:"other",operation:"case-generation",active_handoff_id:"handoff-other"}]}:{task:selected};},
  });
  vm.runInContext(sourceFunction("readTaskCatalog"),context);
  await vm.runInContext("readTaskCatalog({systemId:'a',generation:1})",context);
  assert.equal(context.currentCaseTask.task_id,"selected");
  assert.equal(context.activeCaseHandoffId,"handoff-selected");
  assert.equal(calls[1],"/tasks/selected?view=summary");
});

/** 隐藏报告页只列批次，不把摘要当完整证据；用户进入结果页后才读取全文。 */
test("Case list loads full report only for the visible result tab",async()=>{
  const fields={"case-generation-select":{value:"g1"},"case-execution-environment":{value:"qa"},
    "case-execution-select":{value:"",replaceChildren:()=>{},appendChild:()=>{}}};
  const detailReads=[];
  const context=vm.createContext({consolePages:{caseExecutions:1},caseReading:{tab:"cases",executionEpoch:1},
    currentCaseGeneration:{generation_id:"g1"},currentCaseExecutions:[],caseExecutionViewRequestGeneration:1,
    captureSystemScope:()=>({systemId:"a"}),isCurrentSystemScope:()=>true,element:id=>fields[id],
    Option:function(text,value){this.text=text;this.value=value;},caseTimeLabel:()=>"now",
    api:async url=>{assert.match(url,/environment_id=qa/);return{executions:[{execution_id:"e1",generation_id:"g1",environment_id:"qa"}]};},
    renderConsolePager:()=>{},renderCaseScenes:()=>{},renderCaseExecution:()=>{},
    loadCaseExecution:async id=>{detailReads.push(id);},
  });
  vm.runInContext(sourceFunction("loadCaseExecutions"),context);
  await vm.runInContext("loadCaseExecutions('', 'g1')",context);
  assert.equal(fields["case-execution-select"].value,"e1");
  assert.equal(detailReads.length,0);
  context.caseReading.tab="results";
  await vm.runInContext("loadCaseExecutions('', 'g1')",context);
  assert.deepEqual(detailReads,["e1"]);
});

/** 候选接管尚在加载的接口视图，失败也必须清理遮罩，不能永久禁用中栏交互。 */
test("candidate supersedes target loading and cleans its overlay on failure",async()=>{
  const classes=new Set(["loading-surface"]); let aborted=0;
  const content={dataset:{},classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)},
    setAttribute:(key,value)=>{content[key]=value;},replaceChildren:()=>{}};
  const context=vm.createContext({knowledgeTargetRequestGeneration:1,currentKnowledgeDetail:{},
    captureSystemScope:()=>({systemId:"a"}),isCurrentSystemScope:()=>true,
    activeKnowledgeTargetController:{abort:()=>{aborted++;}},
    element:id=>id==="knowledge-content"?content:{setAttribute:()=>{}},
    textNode:()=>({}),showToast:()=>{},api:async()=>{throw new Error("read failed");},
    pushKnowledgeReturnContext:()=>{assert.ok(context.currentKnowledgeDetail);},
  });
  vm.runInContext(sourceFunction("showKnowledgeCandidate"),context);
  await vm.runInContext("showKnowledgeCandidate({candidate_id:'candidate:a',detail_view:'summary',name:'A'},true)",context);
  assert.equal(aborted,1);
  assert.equal(content["aria-busy"],"false");
  assert.equal(classes.has("loading-surface"),false);
});

/** 必要子面板自行显示错误并返回false时，页面计时仍必须记录失败。 */
test("workspace completion rejects failed required subreads",async()=>{
  const context=vm.createContext({loadEnvironmentCatalog:async()=>false,loadDataCapabilities:async()=>true,
    isCurrentSystemScope:()=>true});
  vm.runInContext(sourceFunction("readWorkspaceData"),context);
  await assert.rejects(vm.runInContext("readWorkspaceData('data-capabilities',{systemId:'a'})",context),/部分数据读取失败/);
});
