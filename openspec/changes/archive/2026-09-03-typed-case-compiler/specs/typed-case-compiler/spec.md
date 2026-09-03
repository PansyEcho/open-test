# typed-case-compiler Specification

## ADDED Requirements

### Requirement: 编译输入必须由服务端重建

系统 SHALL 只接受`entry_id`，并从latest scan、Program分析、Semantic Draft和规则服务重新冻结清单；Action、Setup、Oracle和Cleanup只能由正式服务端资产解析。

#### Scenario: 客户端提交完整Manifest或资产ID

- **WHEN** 请求额外包含Manifest、执行图、Published/Recipe/Oracle/Cleanup ID或base inputs
- **THEN** 严格请求模型拒绝该载荷，不进入编译器

#### Scenario: 真实入口没有Published Action

- **WHEN** latest入口没有唯一当前V2 Published能力
- **THEN** 返回`BLOCKED_UNPUBLISHED_ACTION_CAPABILITY`且不创建Scenario/Variant

#### Scenario: 写Action但Cleanup阶段尚未实现

- **WHEN** 唯一Action为WRITE且没有内部`ValidatedCleanupPlanRef`
- **THEN** 返回`BLOCKED_MISSING_CLEANUP_PLAN`，不得接受客户端Cleanup字符串

### Requirement: Action数据流必须使用类型化事实来源

系统 SHALL 冻结`SetupFact → ActionInput → ActionResult → ActionFact → Oracle/Cleanup`事实链，并用服务器规则标记业务身份路径。

#### Scenario: Action订单号来自Setup Fact

- **WHEN** Action业务身份输入绑定`SetupFactInputRef`
- **THEN** 编译器验证Recipe、fact contract、子路径和Schema，并冻结Recipe来源证明

#### Scenario: Action Profile自行声明输入安全

- **WHEN** Profile来源、业务身份或安全常量没有独立`CapabilityInputSourcePolicy`支持
- **THEN** 返回输入策略阻塞，不得依据Profile自声明放行

#### Scenario: 页面输入提供业务主键

- **WHEN** Generated输入、Fixture或安全常量尝试绑定业务身份字段
- **THEN** 返回`BLOCKED_BUSINESS_IDENTITY_SOURCE_INVALID`

#### Scenario: Action产出退款单号

- **WHEN** Action逻辑输出满足服务器ActionFact contract
- **THEN** 编译器冻结来源于Published output mapping的`ActionFactRef`，不保存任何运行时退款单号

### Requirement: 每类覆盖义务必须使用对应生成器

系统 SHALL 仅让ConstrainedPairwise处理Factor，并分别处理Boundary、Decision、Sequence、Effect和Requirement。

#### Scenario: Pairwise覆盖Factor

- **WHEN** Factor约束和Action Schema存在合法组合
- **THEN** Variant coverage proof只列出该向量实际覆盖的factor value和合法pair

#### Scenario: Pairwise遗漏声明值或合法pair

- **WHEN** 选择结果没有覆盖完整声明值域或约束允许的任一二元组合
- **THEN** Factor生成失败并阻塞，不得用“至少出现一个值”标记义务完成

#### Scenario: 多因素Pairwise规模边界

- **WHEN** Factor数量使全笛卡尔积不可接受
- **THEN** 程序按声明值和二元pair逐目标求满足witness并在有限候选上选择，不得枚举全组合

#### Scenario: 集合基数缺少元素来源

- **WHEN** Boundary要求SINGLE/MULTIPLE但没有可信Setup Fact、服务器元素模板或构造器
- **THEN** 返回`BLOCKED_BOUNDARY_ELEMENT_SOURCE_MISSING`且不生成`[{}]`

#### Scenario: Decision只有自然语言条件

- **WHEN** 义务缺少受控谓词AST、exact evidence或程序验证向量
- **THEN** 返回`BLOCKED_DECISION_REACHABILITY_UNPROVEN`

#### Scenario: Decision借用其他证据或改写Analyzer谓词

- **WHEN** Decision evidence类型、条件、结果、AST、期望或字段路径与Analyzer输出不一致
- **THEN** 返回`BLOCKED_DECISION_REACHABILITY_UNPROVEN`

#### Scenario: 内部Sequence字符串

- **WHEN** Sequence描述Java内部调用或门控顺序
- **THEN** 只生成源码trace覆盖证明，不把字符串当作Published执行节点

#### Scenario: Sequence激活向量与程序谓词不一致

- **WHEN** Sequence trace匹配但Semantic草稿向量不满足Analyzer产出的exact激活谓词
- **THEN** 返回`BLOCKED_SEQUENCE_REACHABILITY_UNPROVEN`且不附加顺序覆盖证明

#### Scenario: 循环故障缺少能力

- **WHEN** 清单包含Fault义务且阶段6尚未提供真实数据或Published故障能力
- **THEN** 返回`BLOCKED_MISSING_FAULT_CAPABILITY`，不生成含该义务ID的Variant或failurePosition字段

### Requirement: Requirement必须使用结构化编译目标

系统 SHALL 使用判别联合目标并保留原Requirement覆盖分母；目标路径和证据必须由程序验证。

#### Scenario: 自然语言Requirement

- **WHEN** 条款没有结构化target或引用证据不足
- **THEN** 返回`BLOCKED_REQUIREMENT_UNCOMPILABLE`且不猜测向量

#### Scenario: compile payload覆盖服务器身份

- **WHEN** 调用方尝试提交任意字典改变obligation/system/entry/source身份
- **THEN** 请求模型拒绝该字段，编译结果身份只能由服务器生成

### Requirement: Effect只附加经过验证的Oracle观察

系统 SHALL 默认把Effect观察附加到已有可达Variant，不新增组合；Observer必须是current READ_ONLY Published并具备跨系统ORACLE授权。

#### Scenario: Effect已有可达Variant

- **WHEN** exact effect evidence有Analyzer激活谓词、服务器Oracle模板且部分已有Variant使谓词为真
- **THEN** 只向这些Variant附加观察证明而不增加因素组合

#### Scenario: Observer路径引用provider原始字段

- **WHEN** actual path不属于Published逻辑output schema
- **THEN** 返回`BLOCKED_EFFECT_OBSERVER_OUTPUT_UNKNOWN`

#### Scenario: Observer跨系统无ORACLE绑定

- **WHEN** observer属于其他系统但没有直接`purpose=ORACLE`依赖
- **THEN** 返回`BLOCKED_EFFECT_OBSERVER_DEPENDENCY_MISSING`

#### Scenario: Effect无可达向量

- **WHEN** 现有Variant均不可到达且没有Decision reachability proof
- **THEN** 返回`BLOCKED_EFFECT_REACHABILITY_UNPROVEN`，不得伪造参数组合

#### Scenario: Effect缺少Analyzer激活谓词

- **WHEN** 规则或AI只提供Effect ID，但源码证据没有同类型、同目标的激活AST
- **THEN** 返回`BLOCKED_EFFECT_REACHABILITY_UNPROVEN`

#### Scenario: Effect位于未知控制流门控

- **WHEN** 外部调用受循环、switch、三元、短路求值或不可解析条件门控
- **THEN** Analyzer不得输出恒真激活谓词，编译器保持`BLOCKED_EFFECT_REACHABILITY_UNPROVEN`

### Requirement: Scenario和Variant必须具有稳定身份及覆盖证明

系统 SHALL 按正式执行图、Setup、Action绑定模板、Oracle、Cleanup和生命周期生成稳定Scenario身份；Variant保存因素值、参数化期望和实际覆盖证明。

#### Scenario: A/M金额共享模板

- **WHEN** A/M使用相同执行图、Setup、Oracle表达式、Cleanup和生命周期
- **THEN** 生成一个Scenario和多个Variant，预期金额字面值不影响Scenario身份

#### Scenario: 输入顺序变化

- **WHEN** 相同类型化向量和模板仅遍历顺序不同
- **THEN** Scenario/Variant稳定身份保持不变

#### Scenario: 冻结义务没有结果

- **WHEN** 任一义务既没有Variant覆盖、blocker也没有不可行证明
- **THEN** 整体返回`BLOCKED_COVERAGE_ACCOUNTING_INCOMPLETE`

### Requirement: Oracle表达式必须静态类型安全

系统 SHALL 只执行受控表达式，并在编译时验证factor、SetupFact、ActionResult和ActionFact路径及数值运算类型。

#### Scenario: 金额Oracle引用因素和前置事实

- **WHEN** 表达式组合数值Factor与SetupFact金额
- **THEN** 编译通过并保存参数化表达式模板，不执行自由文本代码

#### Scenario: 算术引用字符串或未知路径

- **WHEN** 数值运算包含string或不存在的Fact路径
- **THEN** 返回`BLOCKED_ORACLE_EXPRESSION_TYPE_INVALID`

#### Scenario: Factor表达式引用非Factor生成字段

- **WHEN** Oracle以factor来源读取仅由Boundary或Decision生成的路径
- **THEN** 返回`BLOCKED_ORACLE_EXPRESSION_TYPE_INVALID`，不得混用生成输入与因素命名空间

### Requirement: 编译资产必须来自同一可信快照

系统 SHALL 在同一多系统锁范围内重读consumer规则、Recipe和所有Published provider，并重新验证规则历史及Published当前性。

#### Scenario: Current规则被手工改写

- **WHEN** Current规则内容与其不可变history revision不同或revision缺失
- **THEN** 返回`BLOCKED_CASE_COMPILATION_RULES_INVALID`

#### Scenario: Published YAML绕过发布服务写入

- **WHEN** Registry能力无法重新通过Candidate、Provider Operation、Schema mapping或本地绑定验证
- **THEN** 该能力不参与Action或Observer选择

#### Scenario: 加锁前跨系统引用发生变化

- **WHEN** 加锁后规则或Recipe出现未包含在锁范围的新provider系统
- **THEN** 返回`BLOCKED_CROSS_SYSTEM_SNAPSHOT_INVALID`并要求重新编译

### Requirement: 阶段5不得执行Case

系统 SHALL 只生成静态Scenario、Variant、覆盖证明和blocker，不调用QA、不执行Published能力、不创建Attempt。

#### Scenario: 正式退款入口当前没有Action

- **WHEN** 从正式registered/latest/knowledge隔离副本编译退款入口且Published仍为0
- **THEN** 返回真实`BLOCKED_UNPUBLISHED_ACTION_CAPABILITY`，零Scenario、零Variant、零Attempt
