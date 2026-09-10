"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/case-view.js"), "utf8");
const context = vm.createContext({});
vm.runInContext(source, context);

/** 在隔离作用域测试纯展示函数，JSON仅作为测试跨realm数据传输而非业务重新求值。 */
function run(expression) {
  return JSON.parse(vm.runInContext(`JSON.stringify(${expression})`, context));
}

// 场景固定计划包含一个准备维度和一个不参与组合的动态请求身份。
vm.runInContext(`
const template = {template_id:'state', title:'状态检查', parameters:[{name:'initial',function_id:'enum.values',arguments:{}}], request_bindings:[{field:'id',source:{kind:'data_output',call_id:'lookup',output_name:'id'}}]};
const variants = [0,1].map((code,index)=>({variant_id:'v'+index,template_id:'state',ordinal:index+1,parameter_values:{initial:{code,name:'状态'+code}},request_values:{id:{kind:'data_output',call_id:'lookup',output_name:'id'}},data_calls:[{call_id:'lookup',function_name:'lookup',arguments:{state:{kind:'parameter',name:'initial',path:'code'}}}],oracles:[{oracle_id:'response',channel:'response',assertions:[{actual_path:'ok',operator:'eq',expected:{kind:'literal',value:false}}]}]}));
const generation = {system_id:'system',generation_id:'generation',variants,input_contract:{fields:[{path:'id',description:'业务编号',schema:{type:'string'}}]},submission:{case_templates:[template],data_functions:[{name:'lookup',description:'执行时查询满足状态的业务记录'}]}};
`, context);

test("record presence preserves every JSON empty value and false/zero", () => {
  for (const value of [null, {}, [], "", 0, false]) {
    assert.equal(run(`caseHas({value:${JSON.stringify(value)}},'value')`), true);
    assert.deepEqual(run(`caseActualPayload({operations:[{phase:'TARGET',actual_response:${JSON.stringify(value)}}]},'response')`), {state:"value",value});
  }
  assert.equal(run("caseHas({},'value')"), false);
  assert.equal(run("caseActualPayload({operations:[{phase:'TARGET'}]},'response').state"), "unknown");
});

test("nested fields, all array elements, literal kind objects, and exact missing paths survive", () => {
  assert.equal(run("caseNodeChildren(caseValueNode('items',{state:'value',value:[null,0,false,{},[],{kind:'data_output'}]})).length"), 6);
  assert.deepEqual(run("caseReadPath({items:[null,false]},'items.1')"), {present:true,value:false});
  assert.deepEqual(run("caseReadPath({items:[null,false]},'items.2')"), {present:false});
  assert.equal(run("caseReadPath({items:null},'items.x').present"), false);
});

test("preparation variation never labels its dynamic identity as a request variation", () => {
  assert.deepEqual(run("caseVariationParameters(generation,template).map(item=>item.name)"), ["initial"]);
  assert.equal(run("casePlannedNodes(generation,variants[0])[0].varies"), false);
  assert.equal(run("casePlannedNodes(generation,variants[0])[0].view.state"), "unevaluated");
  assert.match(run("caseVariationSummary(generation,template,variants[1])"), /状态1/);
});

test("negative rejection is passed by its recorded assertion, without code heuristics", () => {
  assert.equal(run("caseResultState({status:'COMPLETED',assertions:[{passed:true,actual_value:false}],operations:[{phase:'TARGET',status:'COMPLETED',actual_response:{code:'REJECT',ok:false}}]}).kind"), "passed");
});

test("error, blocking, assertion failure and cleanup are distinct", () => {
  assert.equal(run("caseResultState({status:'FAILED',operations:[{phase:'DATA',status:'FAILED',error:'超时'}]}).kind"), "error");
  assert.equal(run("caseResultState({status:'BLOCKED',error:'无匹配数据'}).kind"), "blocked");
  assert.equal(run("caseResultState({status:'PARTIAL',assertions:[{passed:false,actual_path:'rows.0.state'}]}).kind"), "assertion");
  assert.equal(run("caseResultState({status:'FAILED',assertions:[{passed:true}],operations:[{phase:'CLEANUP',status:'FAILED'}]}).kind"), "cleanup");
  assert.equal(run("caseResultState({status:'FAILED',assertions:[{passed:false}],operations:[{phase:'CLEANUP',status:'FAILED'}]}).label"), "校验失败 · 清理异常");
});

test("known whole-generation batch retains unrecorded subcases; uncertain history uses only records", () => {
  assert.equal(run("caseExecutionRows({contract_version:'case-generation-execution/v1',system_id:'system',generation_id:'generation',status:'RUNNING',variant_results:[]},generation).rows.length"), 2);
  assert.equal(run("caseExecutionRows({system_id:'system',generation_id:'generation',variant_results:[{variant_id:'old'}]},generation).knownScope"), false);
  assert.equal(run("caseResultState(null).label"), "尚无结果记录");
  assert.equal(run("caseStageStates(null,variants[0])[1].label"), "未记录");
});

test("completed data call alone cannot prove preparation filters succeeded", () => {
  const states = run("caseStageStates({status:'BLOCKED',operations:[{phase:'DATA',status:'COMPLETED'}]},variants[0])");
  assert.equal(states[0].label, "准备阻塞");
  assert.equal(states[1].label, "未执行");
});

test("assertions preserve missing observation versus recorded null", () => {
  assert.equal(run("caseObservation({operations:[]},null,{actual_path:'x'}).state"), "unknown");
  assert.deepEqual(run("caseObservation({operations:[]},null,{actual_path:'x',actual_value:null})"), {state:"value",value:null});
  assert.equal(run("caseObservation({operations:[{phase:'TARGET',actual_response:{}}]},{oracle:{channel:'response'}},{actual_path:'x',actual_value:null}).state"), "absent");
  assert.equal(run("caseObservation({operations:[]},null,{actual_path:'x',actual_value:null,actual_summary:{type:'string'}}).state"), "unknown");
});

test("common expectations exclude final per-variant overrides", () => {
  assert.equal(run("caseCommonChecks(generation,variants).length"), 1);
  assert.equal(run("caseCommonChecks(generation,[variants[0],{...variants[1],oracles:[{...variants[1].oracles[0],assertions:[{actual_path:'ok',operator:'eq',expected:{kind:'literal',value:true}}]}]}]).length"), 0);
});

/** 从实际入口文件提取一个完整声明，测试请求竞态时不加载无关页面初始化。 */
function appFunction(name) {
  const app = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/app.js"), "utf8");
  const start = app.indexOf(`async function ${name}(`);
  return app.slice(start, app.indexOf("\n/**", start));
}

/** 用可控网络完成顺序验证旧批次成功和失败都不会污染新查看上下文。 */
test("late execution reads cannot replace a changed system/version/environment/batch", async () => {
  // 依次复现五种用户切换，成功及失败均在切换之后才返回。
  for (const mutation of ["caseReading.executionEpoch++", "selectedEnvironment='isolated'", "selectedGeneration='other'", "selectedExecution='other'", "scopeCurrent=false"]) {
    for (const failed of [false, true]) {
      let resolveRead, rejectRead;
      const sandbox = vm.createContext({api: () => new Promise((resolve, reject) => {resolveRead = resolve; rejectRead = reject;})});
      vm.runInContext(source + `
        let selectedEnvironment='qa', selectedGeneration='gen', selectedExecution='batch', scopeCurrent=true;
        let currentCaseGeneration={generation_id:'gen'}, caseExecutionViewRequestGeneration=0;
        let rendered=0;
        const window={clearTimeout(){},setTimeout(){return 1;}};
        const captureSystemScope=()=>({systemId:'system'}), isCurrentSystemScope=()=>scopeCurrent;
        const element=(id)=>({value: id==='case-execution-environment'?selectedEnvironment:id==='case-generation-select'?selectedGeneration:selectedExecution});
        const renderCaseExecution=()=>{rendered++};
      ` + appFunction("loadCaseExecution"), sandbox);
      const pending = vm.runInContext("loadCaseExecution('batch','gen')", sandbox);
      vm.runInContext(mutation, sandbox);
      if (failed) rejectRead(new Error("obsolete read"));
      else resolveRead({execution:{execution_id:"batch",generation_id:"gen",environment_id:"qa",status:"RUNNING"}});
      // 当前代码必须在错误分支也校验全部阅读身份。
      assert.equal(await pending, null);
      assert.equal(vm.runInContext("rendered", sandbox), 0);
    }
  }
});

/** 父对象绑定与扁平契约并存时，保留真实子字段、额外字段和运行时来源。 */
test("parent object bindings are inherited by schema children without losing extra fields", () => {
  vm.runInContext(`
    const objectTemplate = {...template,request_bindings:[{field:'operator',source:{kind:'literal',value:{name:'Alice',id:0,extra:false}}}]};
    const objectVariant = {...variants[0],request_values:{operator:{name:'Alice',id:0,extra:false}}};
    const objectGeneration = {...generation,input_contract:{fields:[{path:'operator.name',description:'姓名'},{path:'operator.id'}]},submission:{case_templates:[objectTemplate]}};
  `, context);
  const children = run("caseNodeChildren(casePlannedNodes(objectGeneration,objectVariant)[0])");
  assert.deepEqual(children.map(item => [item.path,item.view.value]), [["operator.name","Alice"],["operator.id",0],["operator.extra",false]]);
  assert.equal(children[0].label, "姓名");
  assert.equal(run("caseNodeChildren(casePlannedNodes({...objectGeneration,submission:{case_templates:[{...objectTemplate,request_bindings:[{field:'operator',source:{kind:'environment',name:'actor'}}]}]}},objectVariant)[0])[0].view.state"), "unevaluated");
});

/** 派生字段沿真实concat参数引用传递变化标记，不运行转换函数。 */
test("direct and transitive concat dependencies propagate variation", () => {
  const definition = {parameters:[{name:"amount",function_id:"enum.values"},{name:"caption",function_id:"transform.concat",arguments:{parts:["USD ",{parameter:"amount"}]}},{name:"message",function_id:"transform.concat",arguments:{parts:[{parameter:"caption"},"!"]}}]};
  for (const name of ["caption","message"]) assert.equal(run(`caseSourceVaries({kind:'parameter',name:'${name}'},${JSON.stringify(definition)},new Set(['amount']))`),true);
  assert.deepEqual(run("caseReadPath({ok:false},'$')"),{present:true,value:{ok:false}});
});
