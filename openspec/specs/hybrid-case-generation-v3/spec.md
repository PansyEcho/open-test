# hybrid-case-generation-v3 Specification

## Purpose
TBD - created by archiving change hybrid-case-generation-v3. Update Purpose after archive.
## Requirements
### Requirement: V3公开请求必须只标识真实Entry

系统 SHALL 只接受exact latest scan中的`entry_id`，并由程序恢复全部生命周期资产。

#### Scenario: 客户端提交Action或Fixture

- **WHEN** V3生成请求包含action、recipe、oracle、cleanup、base input或Fixture字段
- **THEN** 严格请求校验拒绝调用且不写Generation、Handoff或Attempt

### Requirement: Case Handoff必须独立且可恢复

系统 SHALL 使用独立`CaseGenerationHandoff`冻结scan和流水线断点，复用任务与Codex线程基础设施但不复用知识候选发布语义。

#### Scenario: Agent提交typed草稿

- **WHEN** handoff中的Agent提交Semantic、Capability、Setup、Oracle或Cleanup草稿
- **THEN** 程序仅通过对应正式服务校验和发布，再从当前latest恢复流水线

#### Scenario: 源码在handoff期间变化

- **WHEN** consumer或引用provider的latest scan不再等于handoff冻结代际
- **THEN** handoff变为`STALE_SOURCE`且旧线程不得继续生成Case

#### Scenario: 依赖范围在handoff期间扩大

- **WHEN** 新增provider绑定或现有绑定的revision、角色、用途发生变化
- **THEN** 旧handoff不得读取新增Candidate并转为`STALE_SOURCE`

#### Scenario: 进程中断时处于VALIDATING

- **WHEN** 提交进程退出后同一handoff仍处于`VALIDATING`
- **THEN** 后续调用取得独占处理锁后可恢复同一冻结范围，终态和并发提交不得恢复

### Requirement: 程序必须确定性选择并冻结完整执行图

系统 SHALL 唯一解析Action/Profile/Oracle，并为每个合法Recipe精确匹配Cleanup和Fault；不得选择第一个候选或静默丢失义务。

#### Scenario: 多个等价Action或Cleanup

- **WHEN** 当前资产存在多个同等合法Action或同一Scenario匹配多个CleanupPlan
- **THEN** 返回具体歧义blocker且对应Scenario不能READY

#### Scenario: 写Action具备完整生命周期

- **WHEN** Action、Recipe、Oracle、Cleanup和全部覆盖义务均由current正式资产证明
- **THEN** Generation冻结Scenario、Variant、二元Published引用、规则修订、依赖证明和完整覆盖核算

#### Scenario: 生命周期过滤丢失Factor合法组合

- **WHEN** Cleanup或其他正式资产过滤使最终Variant不再覆盖全部合法二元Factor目标
- **THEN** 相关Factor义务以`BLOCKED_FACTOR_PAIRWISE_COVERAGE_LOST`阻塞，Generation不得READY

#### Scenario: Fault缺少真实数据或完整Mock生命周期

- **WHEN** Fault Planner不能覆盖某个调用位置
- **THEN** 保留`BLOCKED_MISSING_FAULT_CAPABILITY`且不把位置编码成普通输入字段

### Requirement: Generation必须首次写入不可变

系统 SHALL 拒绝使用同一generation ID覆盖不同语义，并在读取和执行前验证自包含引用。

#### Scenario: Git内容被修改

- **WHEN** Generation当前文件与首次写入快照不一致
- **THEN** 列表、详情和执行均阻塞完整性错误

### Requirement: 执行必须按owning system重验真实资产

系统 SHALL 在QA访问前完成多系统current预检，并让Attempt始终归属被测consumer。

#### Scenario: 跨系统Setup和Observer

- **WHEN** Scenario引用上游Setup或只读Observer
- **THEN** 程序按各自`PublishedCapabilityRef.system_id`加载能力并验证SETUP或ORACLE直接依赖

#### Scenario: 运行前资产漂移

- **WHEN** Candidate、Provider、Recipe、Cleanup、Fault或直接依赖任一不再current
- **THEN** 不访问QA并写入consumer归属的终态BLOCKED Attempt

#### Scenario: Fixture提供业务主键

- **WHEN** Fixture包含Recipe未声明字段或订单号、退款单号等业务身份字段
- **THEN** provider调用前拒绝，业务身份只能来自SetupFact或ActionFact

### Requirement: Cleanup和Fault撤销必须在失败路径执行

系统 SHALL 在资源事实产生后始终尝试Cleanup，在Fault安装成功后始终尝试rollback，并独立记录各失败边界。

#### Scenario: Action失败且Cleanup也失败

- **WHEN** Action返回业务失败且Cleanup或恢复Oracle失败
- **THEN** Attempt最终FAILED、保留primary和cleanup失败摘要并隔离残留资源

### Requirement: Attempt不得持久化业务原值

系统 SHALL 只保存阶段、主体、状态、错误码、断言路径和无值差异，不保存Fixture、Fact、业务键或provider正文。

#### Scenario: Oracle比较订单或退款身份

- **WHEN** actual与expected包含SetupFact或ActionFact派生的业务标识
- **THEN** Attempt只记录字段路径和匹配结论，原始值仅停留在瞬时执行上下文

### Requirement: 旧Case资产只能读取兼容

系统 SHALL 保留旧矩阵、Scenario和Variant读取API，但拒绝旧矩阵生成、确认和批量执行写入口并指向V3。

#### Scenario: 调用旧矩阵生成接口

- **WHEN** 客户端向V2 case-generations提交写请求
- **THEN** 系统拒绝请求并提示使用V3生成入口

