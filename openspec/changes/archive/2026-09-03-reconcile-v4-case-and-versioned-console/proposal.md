# Change: 补录 V4 Case 与版本化控制台契约

## Why

项目已经实现 V4 结构化 Case、用户 Codex 模型选择、资源配置环境和 Git 基线页面，但这些行为没有进入 OpenSpec；同时十三个已完成 change 仍停留在活动目录，导致 `openspec/specs` 与真实系统长期分叉。

## What Changes

- 归档任务已完成的历史 change，把其 delta 合并到当前规格；未完成 change 继续保留活动状态。
- 补录任意 latest READY Facade 的 V4 handoff、源码工具、按需第三方接口、强类型 DSL、Variant 编译、QA 执行和结构化 Oracle 契约。
- 补录 Codex 用户 Provider 模型目录、V4 模型优先级和原子 thread/turn 启动契约。
- 补录 `test/qa/uat/auto` 资源配置选择及扫描版本冻结契约。
- 补录扫描 Git 基线和 V4 JSON 页面，并把持续维护 OpenSpec 加入仓库完成门禁。

## Scope

本 change 只把已实现且已有测试或真实页面证据的行为同步为规格，不新增运行时代码、数据模型或存储机制，不把真实 QA 阻塞记录改写为通过。

