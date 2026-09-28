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

/** 编辑B期间切换到C，B的迟到请求不得填写任何字段或读取C的环境。 */
test("late edit cannot overwrite another system form", async () => {
  let finishSwitch;
  const fields = {};
  const context = vm.createContext({
    registeredSystems: [{system_id:"b", name:"B"}], currentSystem:{system_id:"a"}, systemFormMode:"view", generation:0,
    element: id => fields[id] || (fields[id] = {}),
    renderSystemFormMode: () => {}, switchWorkspace: () => {},
    loadEnvironmentProfiles: () => { throw new Error("迟到编辑不能读取环境"); },
  });
  context.switchSystem = async () => {
    // 模拟正式切换先更新选择和代次，目录请求仍在途。
    context.currentSystem = {system_id:"b"};
    context.generation += 1;
    await new Promise(resolve => { finishSwitch = resolve; });
  };
  context.captureSystemScope = () => ({systemId:context.currentSystem.system_id, generation:context.generation});
  context.isCurrentSystemScope = scope => scope.systemId === context.currentSystem.system_id && scope.generation === context.generation;
  vm.runInContext(sourceFunction("beginEditSystem"), context);
  const pending = vm.runInContext("beginEditSystem('b')", context);
  context.currentSystem = {system_id:"c"};
  context.generation += 1;
  finishSwitch();
  await pending;
  assert.deepEqual(fields, {});
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
