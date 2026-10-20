"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.resolve(__dirname, "../../opentest/web/app.js"), "utf8");

/**
 * 提取真实页面函数用于隔离请求竞态测试。
 * @param {string} name 生产函数名。
 * @returns {string} 对应函数源码，不执行页面初始化。
 */
function sourceFunction(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1);
  return source.slice(start, source.indexOf("\n/**", start));
}

/**
 * 建立仅保存公开天网状态的隔离页面环境。
 * @returns {object} VM 与表单字段，用于检查真实生产函数。
 */
function skyeyeHarness() {
  const fields = {};
  const context = vm.createContext({
    currentSystem: {system_id: "refund"}, systemRequestGeneration: 1, systemFormMode: "edit",
    savedSkyeyeSettings: {skyeye_app_id: "101", token_configured: true}, skyeyeSettingsSystemId: "refund",
    element: id => fields[id] || (fields[id] = {value: "", checked: false}),
  });
  context.isCurrentSystemScope = scope => scope.systemId === context.currentSystem.system_id && scope.generation === context.systemRequestGeneration;
  // 生产函数之间共享同一个状态对象，避免测试用复制实现掩盖字段遗漏。
  vm.runInContext(["resetSkyeyeSettingsForm", "readSkyeyeSettingsPatch", "loadSkyeyeSettings"].map(sourceFunction).join("\n"), context);
  vm.runInContext("resetSkyeyeSettingsForm()", context);
  return {context, fields};
}

/** 留空密码框保留 Token，修改 appId 不携带凭据，明确清除才发送空串。 */
test("token omission, replacement and explicit clear use different requests", () => {
  const {context, fields} = skyeyeHarness();
  assert.equal(fields["skyeye-api-token"].value, "");
  assert.equal(vm.runInContext("readSkyeyeSettingsPatch()", context), null);
  fields["skyeye-app-id"].value = "102";
  let patch = vm.runInContext("readSkyeyeSettingsPatch()", context);
  assert.equal(patch.skyeye_app_id, "102");
  assert.equal(Object.hasOwn(patch, "skyeye_api_token"), false);
  fields["skyeye-clear-token"].checked = true;
  assert.equal(vm.runInContext("readSkyeyeSettingsPatch()", context).skyeye_api_token, "");
  // 冲突输入必须在任何写入前拦截；错误提示不包含用户输入的秘密。
  fields["skyeye-api-token"].value = "fake-private-token";
  assert.throws(() => vm.runInContext("readSkyeyeSettingsPatch()", context), /取消清除/);
  fields["skyeye-clear-token"].checked = false;
  assert.equal(vm.runInContext("readSkyeyeSettingsPatch()", context).skyeye_api_token, "fake-private-token");
});

/** 系统切换后迟到的响应不能回写 appId、配置状态或其他额外返回字段。 */
test("late settings response does not replace the active system", async () => {
  const {context, fields} = skyeyeHarness();
  let finish;
  context.api = () => new Promise(resolve => {finish = resolve;});
  const pending = vm.runInContext("loadSkyeyeSettings({systemId:'refund',generation:1})", context);
  context.currentSystem = {system_id: "other"};
  context.systemRequestGeneration += 1;
  context.savedSkyeyeSettings = {skyeye_app_id: "202", token_configured: false};
  context.skyeyeSettingsSystemId = "other";
  fields["skyeye-app-id"].value = "202";
  finish({skyeye_settings: {skyeye_app_id: "101", token_configured: true}});
  assert.equal(await pending, false);
  assert.equal(fields["skyeye-app-id"].value, "202");
  assert.equal(context.skyeyeSettingsSystemId, "other");
});

/** 读取失败不能把未知设置当成空配置提交；服务端错误原文也不应显示在凭据表单。 */
test("failed read disables private setting updates while metadata remains editable", async () => {
  const {context, fields} = skyeyeHarness();
  context.api = async () => {throw new Error("fake-private-token");};
  assert.equal(await vm.runInContext("loadSkyeyeSettings({systemId:'refund',generation:1})", context), false);
  assert.equal(context.skyeyeSettingsSystemId, "");
  assert.equal(vm.runInContext("readSkyeyeSettingsPatch()", context), null);
  assert.equal(fields["skyeye-settings-status"].textContent.includes("fake-private-token"), false);
});

/** 成功读取只保留公开字段，取消编辑会清除密码草稿和清除标记。 */
test("read projection and form reset never retain raw credentials", async () => {
  const {context, fields} = skyeyeHarness();
  context.api = async () => ({skyeye_settings: {skyeye_app_id: "303", token_configured: true, unexpected: "fake-private-token"}});
  fields["skyeye-api-token"].value = "draft-token";
  fields["skyeye-clear-token"].checked = true;
  assert.equal(await vm.runInContext("loadSkyeyeSettings({systemId:'refund',generation:1})", context), true);
  assert.equal(fields["skyeye-api-token"].value, "");
  assert.equal(fields["skyeye-clear-token"].checked, false);
  assert.equal(JSON.stringify(context.savedSkyeyeSettings).includes("fake-private-token"), false);
});

/** 覆盖开关默认关闭，报告粒度独立可选，不依赖天网密码框。 */
test("coverage policy reads only explicit public controls", () => {
  const {context, fields} = skyeyeHarness();
  fields["coverage-assistance-enabled"] = {checked: false};
  fields["coverage-report-retention-scope"] = {value: "SYSTEM_ENVIRONMENT"};
  vm.runInContext(sourceFunction("readCoverageAssistancePolicy"), context);
  assert.equal(vm.runInContext("readCoverageAssistancePolicy()", context).enabled, false);
  fields["coverage-assistance-enabled"].checked = true;
  fields["coverage-report-retention-scope"].value = "OPERATION";
  const policy = vm.runInContext("readCoverageAssistancePolicy()", context);
  assert.equal(policy.enabled, true);
  assert.equal(policy.report_retention_scope, "OPERATION");
  assert.equal(Object.hasOwn(policy, "skyeye_api_token"), false);
});

/** 运行工具表单必须提交新字段，不能显示后保存却丢掉 JaCoCo 与审查模型。 */
test("runtime form submits coverage tool fields through existing local settings", async () => {
  const {context, fields} = skyeyeHarness();
  for (const [id, value] of Object.entries({"scriptgen-pythonpath": "/fixture/scanner", "knowledge-agent-prompt-template": "fixture",
    "jacoco-cli-path": "/fixture/jacoco.jar", "jacoco-java-command": "", "coverage-review-model": "fixture-review"})) fields[id] = {value};
  let submitted;
  context.api = async (_path, options) => {submitted = JSON.parse(options.body); return {};};
  context.renderRuntimeSettings = () => {};
  context.showToast = () => {};
  vm.runInContext(sourceFunction("saveRuntimeSettings"), context);
  assert.equal(await vm.runInContext("saveRuntimeSettings()", context), true);
  assert.equal(submitted.jacoco_cli_path, "/fixture/jacoco.jar");
  assert.equal(submitted.jacoco_java_command, "java");
  assert.equal(submitted.coverage_review_model, "fixture-review");
});
