# fault-injection-capabilities Specification

## Purpose
TBD - created by archiving change fault-injection-capabilities. Update Purpose after archive.
## Requirements
### Requirement: 外部Tool Candidate必须由程序从真实Git文件解析

系统 SHALL 使用独立只读Tool目录保存脚本来源和协议分析，不把脚本冒充源码Candidate或可执行能力。

#### Scenario: Booking真实Mock脚本

- **WHEN** 程序读取已指定真实绝对路径的`create-interface-mock.sh`
- **THEN** Candidate只记录install/update、`mockKey`、缺少verify/rollback及硬编码环境值blocker，不保存URL或脚本正文

#### Scenario: 调用方手写协议metadata

- **WHEN** API或scan manifest尝试提交supports_verify、supports_rollback或工具角色字典
- **THEN** 请求模型拒绝或目录忽略这些字段，协议只能来自内置分析器

#### Scenario: 生命周期角色绑定正式Operation

- **WHEN** 一个真实脚本实现install、verify或rollback并在源码受控声明中指定委托Operation ID
- **THEN** 程序将角色绑定到该正式Operation；发布请求不得另行覆盖角色身份，未声明时的发现身份不得冒充Published绑定

#### Scenario: Tool源码漂移或符号链接

- **WHEN** 发布时Git commit、单文件dirty状态、真实路径或协议与Candidate不一致
- **THEN** 返回Tool Candidate drift blocker且不发布

#### Scenario: 注释、帮助文本或未追踪脚本伪造协议

- **WHEN** 协议关键字只出现在shell注释/帮助heredoc，或路径不属于当前commit的已追踪Git blob
- **THEN** 程序不识别该生命周期角色，且未追踪来源直接阻塞

### Requirement: Fault能力必须覆盖安装到撤销的完整生命周期

系统 SHALL 只发布能证明目标操作、调用位置、故障结果、验证方式和撤销步骤的Mock/Stub Fault能力。

#### Scenario: Mock脚本只能安装并返回mockKey

- **WHEN** Candidate协议表明脚本支持安装/更新但没有已验证撤销
- **THEN** 系统返回`FAULT_ROLLBACK_CAPABILITY_MISSING`且不发布Fault能力

#### Scenario: Mock具备安装验证和撤销能力

- **WHEN** adapter协议与三个Published原子能力均完整
- **THEN** 系统发布可用于指定调用次数的FaultInjectionCapability

#### Scenario: verify或rollback来自未声明工具

- **WHEN** 生命周期Published能力的provider操作不在adapter协议声明的verify/rollback工具身份中
- **THEN** 系统返回adapter mismatch且不发布Fault能力

#### Scenario: 生命周期能力跨系统无FAULT授权

- **WHEN** target、install、verify或rollback属于其他系统但consumer没有直接`purpose=FAULT`依赖
- **THEN** 返回具体dependency blocker且不发布

### Requirement: Fault规划必须优先使用真实业务数据

系统 SHALL 在同一目标和调用位置同时存在Real Data与Mock/Stub能力时选择Real Data，并在均不存在时阻塞。

#### Scenario: 真实Setup Recipe可稳定触发中间调用失败

- **WHEN** REAL_DATA Fault能力支持MIDDLE位置
- **THEN** Planner使用该Recipe并不安装Mock

#### Scenario: Real Data使用人工证明字段

- **WHEN** 草稿只提供constraint_proven、Fixture/literal或自定义failure_target/failure_position
- **THEN** 返回`FAULT_REAL_DATA_TRIGGER_UNPROVEN`，不得发布或规划

#### Scenario: Real Data Fact没有进入被测Action

- **WHEN** Recipe Fact有受控Trigger contract但当前Action Profile未从该Fact contract绑定输入
- **THEN** 返回`FAULT_REAL_DATA_ACTION_BINDING_MISSING`

#### Scenario: 仅有完整Mock能力

- **WHEN** 没有匹配Real Data能力且Mock支持目标位置
- **THEN** Planner生成包含install、verify和rollback引用的FaultInjectionPlan

#### Scenario: 两类能力均不存在

- **WHEN** Fault义务没有匹配正式能力
- **THEN** Planner返回`BLOCKED_MISSING_FAULT_CAPABILITY`且不生成Case字段

### Requirement: Planner只能解析服务器冻结的Fault义务

系统 SHALL 只接受entry和obligation身份，并从exact latest冻结清单恢复目标、位置与逐实体期望。

#### Scenario: 客户端提交完整Fault义务

- **WHEN** 请求包含target、position、fault result或expected entity states
- **THEN** 严格请求模型拒绝额外字段

#### Scenario: 中间或末次调用缺少总数证明

- **WHEN** 能力没有受控Fact或协议提供total invocations和具体ordinal
- **THEN** 返回`BLOCKED_FAULT_INVOCATION_UNPROVEN`，不得默认MIDDLE为2或抽象LAST为倒数一次

#### Scenario: 精确调用序号已证明

- **WHEN** total和ordinal满足FIRST=1、`2 <= MIDDLE < total`或LAST=total
- **THEN** 计划保存确定的total与invocation number

#### Scenario: 全局循环规则冻结三个位置

- **WHEN** 程序分析产生`ordered_iteration`并由全局规则冻结FIRST/MIDDLE/LAST及SUCCESS/FAILED/NOT_EXECUTED
- **THEN** Planner为三个位置保留同一义务中的参数化实体预期，不额外要求`NOT_APPLICABLE`

### Requirement: Fault执行必须观察安装、命中和撤销结果

系统 SHALL 在安装调用成功后立即标记必须回滚，要求verify输出`fault_installed=true`、目标Action实际返回计划错误码和失败类别且非空逐实体状态匹配，并要求rollback输出`fault_removed=true`。

#### Scenario: 安装后输出映射失败

- **WHEN** Mock安装调用已成功但mockKey映射或verify资产解析失败
- **THEN** finally仍尝试rollback并把无法确认的结果计入Attempt失败

#### Scenario: Action没有命中预期错误

- **WHEN** 目标Action返回成功但payload碰巧包含逐实体状态
- **THEN** Fault Oracle返回`FAULT_EXPECTED_ERROR_NOT_OBSERVED`

#### Scenario: 错误码相同但失败类别不同

- **WHEN** Fault计划要求error_response但目标Action被规范化为exception或timeout
- **THEN** Attempt返回`FAULT_RESULT_OUTCOME_MISMATCH`且仍执行rollback

#### Scenario: Fault义务没有逐实体期望

- **WHEN** 规则或草稿提交空expected_entity_states
- **THEN** 模型拒绝该义务或计划，不允许空循环被宣称为Oracle通过

#### Scenario: install后的任意阶段异常

- **WHEN** install provider已成功，而output mapping、verify资产、verify调用、Action或Oracle随后异常
- **THEN** `finally`仍调用rollback，并同时保留主失败和rollback证据

### Requirement: Fault注册表必须不可变且规划时重验

系统 SHALL append版本化Fault能力，并在每次列表/规划时重验Tool、Published、Recipe和dependency current状态。

#### Scenario: 相同发布请求改变语义

- **WHEN** 同一publication request或capability ID改变target、Recipe、selector、结果或生命周期引用
- **THEN** 返回immutable conflict且不覆盖已有能力

#### Scenario: 已发布能力的依赖被撤销

- **WHEN** current直接FAULT/SETUP依赖不再存在
- **THEN** 该能力不参与Planner并返回具体失效原因

### Requirement: Fault资产不得保存敏感环境值

系统 SHALL 只保存所需本地配置键名和硬编码风险布尔值，不保存URL、Token、Authorization、请求或响应正文。

#### Scenario: 脚本包含硬编码环境地址

- **WHEN** 协议分析发现非本地配置提供的HTTP地址
- **THEN** Candidate标记环境不安全且发布阻塞，Git和日志不出现该地址正文

