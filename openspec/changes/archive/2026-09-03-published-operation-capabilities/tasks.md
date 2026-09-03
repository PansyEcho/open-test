# Tasks

## 1. Contract

- [x] 1.1 增加CandidateRef、ProviderOperationRef、幂等草稿、校验问题和V2 Published模型
- [x] 1.2 扩充现有OperationCapability的源码证据、闭合输入/输出Schema和程序派生绑定路径
- [x] 1.3 增加严格V2 Git注册表及V1只读兼容隔离

## 2. Validation

- [x] 2.1 在同系统事务内校验Candidate基线、签名和完整DTO未漂移
- [x] 2.2 通过现有OperationCapability校验同系统、scan、Entry、源码、读写属性及禁止数据库能力
- [x] 2.3 校验shape-only逻辑Schema、双向映射路径/类型/覆盖和程序派生本地绑定
- [x] 2.4 实现publication_request_id幂等与冲突检测
- [x] 2.5 提供提交、结果、阻塞原因和只读V2注册表API且保持QA执行零调用

## 3. Verification

- [x] 3.1 增加成功、漂移、跨系统、精确Operation、Schema/映射、本地绑定、幂等和旧资产测试
- [x] 3.2 使用正式退款与Booking registered system/latest的原样隔离副本完成fail-closed反造假验收；真实正向晋升仍被DTO证据阻塞，缺绑定时返回真实BLOCKED
- [x] 3.3 断言发布期间不调用OperationExecutionService.execute或QA provider，Git不含本地值/provider坐标
- [x] 3.4 运行本变更相关测试和OpenSpec严格检查
- [x] 3.5 使用OCR delegation和同一只读Agent复核实现与测试来源；最终High已修复，Medium通过明确真实正向阻塞边界解决
