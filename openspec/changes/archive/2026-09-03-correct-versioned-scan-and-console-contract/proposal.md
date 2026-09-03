# Change: 修正版本化扫描与控制台主契约

## Why

历史Change集中归档后，部分较早的过渡期要求覆盖或保留在主规格中，已经与当前实现冲突：Git扫描仍被描述为读取dirty working tree，控制台仍被限制为只调用V2 API，Candidate阶段的临时失败关闭仍否定已经交付的后续能力，跨系统隔离要求也丢失了早期直接绑定场景。继续保留这些描述会让后续开发在错误基线上实现和验收。

## What Changes

- 将Git扫描契约修正为先解析branch、tag、commit或HEAD，再只读取物化的不可变commit快照。
- 将V4源码身份保留范围收窄到V4 Generation/Handoff，并准确区分original revision、完整commit与非权威`branch`展示提示。
- 将控制台契约修正为按能力调用当前V2、V3与V4版本化API，同时继续禁止legacy路由。
- 移除Candidate重建阶段已经失效的临时失败关闭要求，恢复跨系统直接绑定的完整隔离场景。
- 允许DSF执行使用所选扫描配置中的test、qa或uat非生产路由，而不是固定`env=qa,targetenv=test`。
- 将环境资源发现描述为读取匹配`*.<environment>`的安全filter并与主`dsf_application.properties`模板合并，兼容项目真实文件命名。
- 精确描述V4 App Server线程与turn的顺序创建语义，以及当前MySQL、Redis、MQ Observer的实际可执行边界。

## Scope

本Change只修正已经实现能力的OpenSpec主契约，不修改运行时代码、持久化数据或页面行为，也不把尚未完成的真实QA金丝雀标为完成。

## Non-Goals

- 不归档仍有未完成任务的活动Change。
- 不新增Redis或MQ只读Observer。
- 不修改legacy Case记录以补写历史source scan。
