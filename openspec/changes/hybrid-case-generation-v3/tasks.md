# Tasks

## 1. Entry-only workflow

- [x] 1.1 将V3请求收缩为entry_id并增加CaseGenerationHandoff/typed draft契约
- [x] 1.2 增加独立handoff私有存储、任务/线程身份和同scan断点恢复API
- [x] 1.3 将Semantic、Capability、Setup、Oracle/Fault/Cleanup草稿交给阶段1至7正式校验器

## 2. Deterministic generation

- [x] 2.1 重建Action/Profile/Recipe/Oracle/Cleanup/Fault确定性选择与歧义阻塞
- [x] 2.2 串联分型编译并生成普通与Fault独立Scenario/Variant
- [x] 2.3 冻结资产版本、跨系统依赖证明和逐义务完整核算
- [x] 2.4 实现Generation首次写入不可变存储和列表/详情API

## 3. Trusted execution

- [x] 3.1 实现多系统current预检、owning-system能力路由和Fixture身份门禁
- [x] 3.2 实现Setup/Action/Oracle与Fault/Cleanup双finalizer
- [x] 3.3 分离主失败、rollback、cleanup、cleanup oracle和quarantine证据并保持值脱敏
- [x] 3.4 保持旧V2写入口退役和旧资产只读

## 4. Verification

- [x] 4.1 增加entry-only、handoff恢复、歧义选择、Generation不可变和跨系统反例
- [x] 4.2 使用正式服务链测试生成；Fake invoker不得产生或宣称PASSED
- [x] 4.3 在真实Refund注册/scan/知识上证明缺正式资产时具体BLOCKED、零READY和零QA访问
- [x] 4.4 运行本阶段测试、OpenSpec strict和完整差异复核
- [x] 4.5 使用OCR delegation和同一只读Agent复核实现及测试证据
