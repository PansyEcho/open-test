# Change: 正式原子操作能力发布

## Why

Candidate只解决“AI能看到哪些源码方法”，不能直接进入Recipe或执行器。系统需要一个唯一、可校验的晋升入口，把AI的语义选择转换成程序掌控的最小可执行面。

## What Changes

- 增加`CandidateRef`、`ProviderOperationRef`和带稳定请求ID的`CapabilityDraft`提交契约；Draft只选择已有Candidate和已有`OperationCapability`，不复制provider坐标。
- 扩充现有`OperationCapability`的程序证据，提供精确Entry/源码引用、闭合输入/输出Schema和程序派生的本地绑定路径；不新增平行provider模型、invoker或执行器。
- 程序验证Candidate完整DTO、Candidate与Operation精确关系、映射路径和类型、本地QA绑定及同系统所有权。
- 验证成功后在同系统事务内写入V2 `PublishedCapabilityRegistry`；旧V1/手写资产只能只读兼容展示，不能被正式引用。
- 本变更只发布原子操作引用，不增加Setup、Fault、Oracle或Cleanup编排，不调用`OperationExecutionService.execute`或任一QA provider。
