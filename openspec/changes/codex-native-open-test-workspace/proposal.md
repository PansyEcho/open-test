# Change: Codex 原生 OpenTest 工作区

## Why

知识详情当前为每次请求重新解析完整扫描产物并重建目录；Codex 插件只能读取知识生成源码，无法执行 QA Facade 或 Job；页面问题周期又与原 Codex 聊天形成两个用户入口。这些约束使详情浏览、业务操作和任务恢复割裂。

## What Changes

- 把最新知识目录预热为有界、可失效的内存投影，详情读取不再重复解析完整 Manifest。
- 新增独立于只读知识契约的 Facade/Job 操作能力、索引、幂等执行记录和 QA-only API。
- 扩展本地 Codex 插件，为每个系统生成显式调用的操作 skill，并通过独立 MCP 暴露固定操作工具。
- 保留三栏页面，将问题栏替换为 Codex 任务栏；新问题只在原 Codex 聊天补全，历史问题周期只读保留。

## Scope

本 Change 只实现离线扫描、索引、fake provider 和本地 Codex 集成。不得读取 Fixture 正文、执行真实 QA 写调用、DSF 金丝雀或生命周期 Case。

## Superseded Decisions

`dsf-proxy-execution-and-agent-tools` 中待完成的 Facade 工具切换、操作确认页面和只读金丝雀不再作为写操作开放前置条件。固定操作目录、QA 环境和 DSF Worker 身份仍复用；真实金丝雀保持未执行。
