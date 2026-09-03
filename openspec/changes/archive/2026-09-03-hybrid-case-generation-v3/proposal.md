# Change: Hybrid Case Generation V3可信主流程

## Why

前七个阶段已经建立程序覆盖分析、Candidate、Published、Setup、分型编译、Fault和Cleanup的正式边界，但当前V3入口仍要求客户端提交Action、Recipe、Oracle和Cleanup ID，旧执行器也仍按已废弃字段读取资产。直接解除阻断会允许客户端选取生命周期资产、错用跨系统能力，或在真实QA调用前写出伪Attempt。

## What Changes

- V3生成请求只接受真实latest scan中的`entry_id`，其他生命周期字段一律拒绝。
- 新增独立`CaseGenerationHandoff`，复用本地任务与Codex线程基础设施，但不复用知识候选发布状态机。
- Agent只提交entry/scan绑定的typed草稿；程序调用阶段1至7正式服务完成校验和发布，再从latest断点恢复。
- 程序按确定性规则选择Action、全部合法Recipe、Oracle、Cleanup和Fault，禁止选择“第一个”或排序最小资产。
- V3 Generation冻结完整执行图、规则与依赖证明和覆盖核算，并采用首次写入不可变存储。
- 重建V3执行预检和生命周期执行；能力始终按`PublishedCapabilityRef.system_id`加载，Attempt始终归属被测consumer。
- 旧V2矩阵、Scenario和Variant只读兼容；旧写入口继续退役。

## Out of Scope

- 本阶段不修改Case工作台页面，也不声明退款真实链路已经PASSED；页面和真实Refund验收属于阶段9。
- QA不可用或正式资产缺失时保持具体BLOCKED，不使用Fake provider制造PASSED证据。
