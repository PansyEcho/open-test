# data-setup-recipes Specification

## ADDED Requirements

### Requirement: Setup Recipe只能组合当前Published原子操作

系统 SHALL 让每个步骤使用`PublishedCapabilityRef(system_id, capability_id)`引用当前provider源码代际的V2 `PublishedOperationCapability`，不得接受Candidate、V1能力或已漂移能力。

#### Scenario: 跨系统引用已发布上游能力

- **WHEN** consumer步骤引用provider系统当前Published能力，且存在直接`SETUP`依赖
- **THEN** Recipe保存二元能力引用并仍只归属consumer入口

#### Scenario: Recipe直接引用Candidate

- **WHEN** Recipe步骤把Candidate ID放入Published引用
- **THEN** 系统返回`BLOCKED_UNPUBLISHED_CAPABILITY`且不保存Recipe

#### Scenario: provider latest已经变化

- **WHEN** Published引用的scan不再是provider latest
- **THEN** 系统返回`BLOCKED_STALE_CAPABILITY`且不保存Recipe

### Requirement: 跨系统Recipe发布必须原子验证全部系统

系统 SHALL 按系统ID排序一次性锁定consumer和全部provider，并在锁内重新读取consumer latest、依赖、provider latest、Published、规则和既有Recipe后写consumer资产。

#### Scenario: 验证期间provider切换latest

- **WHEN** provider新扫描与Recipe发布并发
- **THEN** 两者按同一系统锁串行，Recipe不得保存发布时已过期的能力引用

#### Scenario: 跨系统依赖用途不正确

- **WHEN** 依赖不存在、方向错误或purposes不含`SETUP`
- **THEN** 系统返回`BLOCKED_SETUP_DEPENDENCY_MISSING`且不借用反向或传递关系

### Requirement: TestFact语义和来源由服务器规则确定

系统 SHALL 从consumer Git读取`SetupFactContractDefinition`，并按稳定`fact_contract_id`验证来源、字段Schema、业务身份与必需约束；`fact_name`不得决定业务语义。

既有`fact_contract_id` SHALL 不可删除或原地改写；语义变化必须发布新版本ID。`fact_name` SHALL 不包含`.`，使Fact实例名与子路径不存在解析歧义。

#### Scenario: ticketed-order事实来自真实上游

- **WHEN** Recipe声明`ticketed-order/v1`
- **THEN** 产出步骤必须属于直接UPSTREAM provider的Published输出，并包含业务订单身份、出票状态和segments数组

#### Scenario: 退款能力冒充出票事实

- **WHEN** 同系统或非UPSTREAM能力输出被绑定为要求`UPSTREAM_PUBLISHED_OUTPUT`的事实契约
- **THEN** 系统返回`SETUP_FACT_ORIGIN_INVALID`

#### Scenario: 调用方改名或降低来源策略

- **WHEN** 调用方改变fact实例名或只提交普通输出来源
- **THEN** 程序仍按服务器fact contract要求校验，Recipe提交无权降低策略

#### Scenario: 原地改写Fact contract

- **WHEN** 规则更新删除既有contract ID或改变其来源、字段、身份或约束定义
- **THEN** 系统拒绝写入并要求使用新的版本ID

### Requirement: Fact Schema和约束必须确定性验证

系统 SHALL 从Published输出路径派生Fact Schema，不接受调用方重复Schema，并验证所有约束路径、值类型、基数和冲突。

#### Scenario: 单航段出票订单

- **WHEN** `ticketed-order/v1`的segments数组声明`cardinality=SINGLE`
- **THEN** 约束通过并保存为独立Recipe版本

#### Scenario: 多航段出票订单

- **WHEN** 同一事实契约的segments数组声明`cardinality=MULTIPLE`
- **THEN** 约束独立保存且不会覆盖单航段Recipe

#### Scenario: 标量字段声明集合基数

- **WHEN** string或number字段使用cardinality
- **THEN** 系统返回`SETUP_FACT_CONSTRAINT_INVALID`

#### Scenario: 约束类型错误或互相矛盾

- **WHEN** `eq/in`值不符合字段Schema，或同一路径约束没有共同可满足值
- **THEN** 系统返回`SETUP_FACT_CONSTRAINT_INVALID`或`SETUP_FACT_CONSTRAINT_CONFLICT`

#### Scenario: 约束写入业务资源身份

- **WHEN** Recipe尝试在fact contract的业务身份路径上持久化`eq/in`具体值
- **THEN** 系统返回`SETUP_FACT_IDENTITY_VALUE_FORBIDDEN`

### Requirement: Setup输入来源必须由服务器策略授权

系统 SHALL 要求每个步骤逻辑输入根匹配`SetupInputPolicy`；未经分类的Fixture/literal失败关闭，业务身份输入只能来自更早Fact。

literal与约束安全值 SHALL 同时比较标量类型和值，不得使用语言运行时的宽松相等规则混淆布尔与数字。

#### Scenario: literal安全值

- **WHEN** literal值属于策略维护的安全枚举、布尔或边界白名单且符合Published Schema
- **THEN** Recipe可保存该值

#### Scenario: literal或Fixture提供订单号

- **WHEN** 业务身份输入来自literal或Fixture
- **THEN** 系统返回`SETUP_INPUT_SOURCE_FORBIDDEN`且值不进入Git

#### Scenario: Fixture路径和类型

- **WHEN** 策略允许Fixture且Recipe提供不含值的闭合`fixture_schema`
- **THEN** 程序验证路径存在、类型兼容，并保留运行时实际值复核义务

#### Scenario: 后续步骤消费前序Fact子字段

- **WHEN** 步骤输入引用更早Fact的真实子字段
- **THEN** 程序验证完整路径和Schema可赋值；未知Fact、未知子字段或前向引用均阻塞

#### Scenario: 布尔值命中数字白名单

- **WHEN** 规则只允许数字`1`但Recipe提交布尔`true`
- **THEN** 系统返回`SETUP_LITERAL_VALUE_FORBIDDEN`

### Requirement: 已发布Setup Recipe必须不可变且冻结依赖证明

系统 SHALL 将Recipe ID作为Scenario冻结身份，保存二元Published引用、规则版本和程序派生的直接依赖版本证明；同ID内容不得覆盖。每次依赖或规则更新 SHALL 先追加不可变历史快照，再切换current。

#### Scenario: 修改已发布Recipe内容

- **WHEN** 相同recipe_id重新提交不同名称、步骤或事实绑定
- **THEN** 系统返回`SETUP_RECIPE_ID_ALREADY_PUBLISHED`

#### Scenario: 发布后删除依赖

- **WHEN** 旧Recipe引用的跨系统绑定被删除或角色/用途变化
- **THEN** Recipe历史仍可读，但阶段8执行前重新验证失败且不得调用provider

#### Scenario: 发布后撤销输入策略

- **WHEN** current input policy删除或改变已发布Recipe使用的来源
- **THEN** Recipe继续通过发布时规则版本展示历史，阶段8使用current policy阻止不再授权的执行

#### Scenario: Git Recipe派生证据被篡改

- **WHEN** 已保存YAML中的Fact Schema、origin、步骤关系或dependency proof被手工改写
- **THEN** 读取服务从冻结Published和不可变Fact contract重新验证失败，不得通过目录或单条API返回为已验证Recipe

#### Scenario: 手写完全自洽的依赖证明

- **WHEN** Git Recipe声明格式正确的UPSTREAM/SETUP proof但引用的binding revision历史不存在
- **THEN** 读取服务返回完整性错误，不把内部字段自洽当成发布来源证明

#### Scenario: Git Recipe注入不存在入口

- **WHEN** Recipe的`entry_id`不属于`entry_source_scan_id`指定的精确历史scan
- **THEN** 读取服务返回完整性错误

### Requirement: 阶段4不得访问QA执行面

系统 SHALL 只发布静态Recipe契约，不调用OperationExecutionService或任何provider，也不产生TestFact实例。

#### Scenario: Recipe发布成功

- **WHEN** 全部静态引用、策略、Schema和约束校验通过
- **THEN** 只写consumer Git Recipe，QA调用与ExecutionRecord数量保持不变

#### Scenario: 真实退款和Booking当前没有Published

- **WHEN** 从正式资产隔离副本提交跨系统出票Recipe
- **THEN** 返回`BLOCKED_UNPUBLISHED_CAPABILITY`且正式仓库与副本都不产生Recipe
