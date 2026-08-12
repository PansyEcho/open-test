# Change: DSF真实执行、Oracle与Snapshot闭环

## Why

场景变体已经具备逻辑工具ID、完整输入、断言和清理信息，但尚不能安全绑定真实scriptgen工具，也没有类型化变量解析、异步Oracle轮询和版本快照。缺少这些能力时Case只能作为文档，无法形成可审计回归闭环。

## What Changes

- 仅从稳定ScanManifest解析逻辑工具并调用scriptgen真实脚本。
- 实现结构化变量绑定、JSON输出解析、断言差异和失败证据。
- 建立DSF查询、MySQL、TiDB、Redis和MQ Oracle扩展边界及截止时间轮询。
- 增加同仓库Java QA Worker；Worker使用目标应用身份从远程配置加载MySQL、TiDB和Redis连接，Python与Agent不读取这些密码。
- 从源码发现逻辑数据源、Redis Group与MQ Topic，并在控制台展示可核查资源状态。
- 增加固定Oracle操作目录、业务回归套件批量执行和QA全局Job一次性确认门禁。
- Labrador等执行密钥只通过本地环境引用注入，不写入Git、不展示到页面或报告。
- 创建绑定源码、知识、Case、工具和Skill摘要的Snapshot。
- 将执行记录与证据保存在 `.opentest/runs` 并通过任务入口返回。

## Scope

一期只执行当前系统的核心订单生命周期场景。真实QA调用需要本地业务Fixture与必要的Labrador环境引用；MySQL、TiDB和Redis连接由Worker通过远程配置解析。缺少前置条件时系统返回明确阻塞原因，不伪造成功。

## Non-Goals

- 不执行跨系统数据准备。
- 不提供浏览器Executor。
- 不把内部临时参数设为稳定硬断言。
- 不把连接探测计入业务Case通过数。
- 不在缺少MQ轨迹接口时声称消息传输已经直接验证。
