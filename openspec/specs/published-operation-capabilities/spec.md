# published-operation-capabilities Specification

## Purpose
TBD - created by archiving change published-operation-capabilities. Update Purpose after archive.
## Requirements
### Requirement: 只有通过程序验证的草稿才能晋升为原子操作能力

系统 SHALL 在发布前重新校验Candidate源码代际、完整签名和DTO结构，并通过`ProviderOperationRef`取得现有唯一`OperationCapability`，校验精确源码关系、QA环境、读写属性、闭合参数/输出Schema、映射和程序派生的本地绑定。

#### Scenario: Candidate与草稿属于同一源码代际

- **WHEN** AI提交完整且与latest Candidate及现有Operation一致的能力草稿
- **THEN** 系统发布一个`PublishedOperationCapability`并返回稳定Published ID

#### Scenario: 草稿引用旧扫描签名

- **WHEN** latest源码扫描或方法签名已不同于草稿
- **THEN** 系统拒绝发布并返回`CANDIDATE_SOURCE_DRIFT`

#### Scenario: 本地QA绑定不完整

- **WHEN** 草稿声明的provider所需本地绑定不存在
- **THEN** 系统拒绝发布且Git注册表不包含该能力

#### Scenario: 同名方法没有精确provider来源证据

- **WHEN** Candidate和Operation只有同名方法但没有相同Entry和精确source symbol证据
- **THEN** 系统返回`CAPABILITY_OPERATION_UNPROVEN`而不借用Operation

#### Scenario: Candidate或Schema元数据不完整

- **WHEN** Candidate为PARTIAL、DTO结构不完整，或Operation缺少闭合输入/输出Schema
- **THEN** 系统在发布阶段阻塞而不把错误推迟到QA

#### Scenario: 嵌套对象重新开放额外字段

- **WHEN** 输入或输出Schema的任一嵌套object没有声明properties、required和`additionalProperties=false`
- **THEN** 系统返回`CAPABILITY_SCHEMA_INVALID`，且每个逻辑输入根都必须有显式provider映射

#### Scenario: 映射目标不存在或类型不兼容

- **WHEN** 输入/输出映射目标不在Operation Schema中、类型不兼容、重复、父子冲突或未覆盖provider必填字段
- **THEN** 系统返回结构化映射blocker且不写注册表

#### Scenario: Schema携带样本或QA值

- **WHEN** Draft Schema包含`default`、`const`、`examples`、`enum`或其他非形状关键字
- **THEN** 系统返回`CAPABILITY_SCHEMA_INVALID`且这些值不进入Git

### Requirement: Published必须是现有OperationCapability的审核适配层

系统 SHALL 只保存`CandidateRef`、`ProviderOperationRef`、逻辑Schema/映射和程序验证结果，不复制provider坐标，不新增执行器或provider adapter。

#### Scenario: 发布已有Facade原子操作

- **WHEN** ProviderOperationRef指向同系统同scan的现有Facade OperationCapability
- **THEN** Published保存operation引用，后续执行只能按该operation ID进入现有OperationExecutionService

#### Scenario: 发布Schema与运行时契约隔离

- **WHEN** 程序从完整Java DTO生成发布证明Schema
- **THEN** 现有Operation运行时`input_schema`保持不变，Facade输出映射以真实执行结果的`output`路径为根；无结果契约的Job继续阻塞

#### Scenario: 原始泛型或集合元素无法解析

- **WHEN** DTO继承的泛型实参、集合元素或递归字段不能解析到精确FQN
- **THEN** Candidate与发布Schema保持不完整，不得把未知类型猜成字符串或空对象

#### Scenario: Map或任意业务泛型包装

- **WHEN** 字段使用`Map<K,V>`、`Page<T>`、`Result<T>`、嵌套泛型或白名单之外的容器
- **THEN** Candidate与发布Schema保持不完整，不得把Map或包装对象误投影成数组元素

#### Scenario: 发布通用数据库能力

- **WHEN** ProviderOperationRef指向允许任意SQL的`DATABASE_RESOURCE`
- **THEN** 本阶段明确阻塞并留待Cleanup或Oracle阶段使用受限操作

### Requirement: 跨系统发现不得授予发布权限

系统 SHALL 要求发布路由、CandidateRef和ProviderOperationRef属于同一活动系统；直接依赖绑定不授予跨系统注册表写权限。

#### Scenario: refund路由提交Booking Candidate

- **WHEN** refund consumer搜索到Booking Candidate后在refund发布API提交该引用
- **THEN** 系统返回`CAPABILITY_SYSTEM_SCOPE_MISMATCH`且两个系统注册表均不变化

#### Scenario: 以Candidate所属系统发布

- **WHEN** 调用方改用Booking系统路由提交Booking Candidate和Operation引用
- **THEN** 程序只写Booking的Published注册表，后续跨系统Recipe通过二元引用使用

### Requirement: 本地QA绑定必须由程序派生

系统 SHALL 从现有Operation执行契约取得安全绑定路径并读取所属系统0600 QA配置验证；Draft不得声明、遗漏或替换绑定路径。

#### Scenario: 本地QA绑定不完整

- **WHEN** Operation要求的任一路径在本地配置不存在或为空
- **THEN** 系统拒绝发布且Git注册表不包含该能力或本地值

### Requirement: 正式注册表只能保存原子操作

系统 SHALL 让Published能力绑定一个Candidate和一个唯一provider，不在本阶段包含Setup、Fault、Oracle或Cleanup步骤。

#### Scenario: 读取正式能力注册表

- **WHEN** 调用方读取一个系统的Published注册表
- **THEN** 系统只返回验证通过的原子操作及安全绑定路径，不返回本地密钥值

#### Scenario: 手写V2注册表跨系统或重复ID

- **WHEN** Git YAML中的能力系统/scan引用不一致或capability ID重复
- **THEN** 正式注册表读取失败，不选择其中任一项

#### Scenario: 读取旧V1注册表

- **WHEN** 系统目录残留旧`published-operation-capability/v1`资产
- **THEN** 仅在兼容展示中标记LEGACY_READ_ONLY，不得作为V2 Published返回或被执行引用

### Requirement: Published能力身份必须不可变

系统 SHALL 为每次通过验证的草稿生成版本化Published ID，重新发布同一Candidate不得原位替换既有Recipe或Scenario所引用的语义。

#### Scenario: 同一Candidate重新发布映射

- **WHEN** 新草稿调整业务用途或输入输出映射后再次通过验证
- **THEN** 注册表同时保留新旧Published ID，旧ID仍返回原语义

#### Scenario: 相同发布请求重试

- **WHEN** 相同publication_request_id和完全相同草稿重复提交
- **THEN** 返回第一次发布的同一Published ID且不新增版本

#### Scenario: 相同发布请求修改载荷

- **WHEN** 相同publication_request_id提交不同引用、Schema或映射
- **THEN** 系统返回`CAPABILITY_PUBLICATION_REQUEST_CONFLICT`且不覆盖旧能力

### Requirement: 发布验证与写入必须绑定同一latest代际

系统 SHALL 在Candidate所属系统事务中重新读取latest Candidate和Operation并完成append；latest在事务前已变化时必须阻塞旧草稿。

#### Scenario: 发布前latest发生切换

- **WHEN** 草稿准备后系统完成新扫描并切换latest
- **THEN** 发布返回源码漂移且不会把旧scan引用追加到当前注册表

### Requirement: 发布阶段不得访问QA执行面

系统 SHALL 只读取0600配置验证路径存在，不得调用OperationExecutionService.execute或任一provider。

#### Scenario: 发布成功

- **WHEN** 草稿全部验证通过并写入注册表
- **THEN** QA provider调用次数仍为零且没有ExecutionRecord或Attempt产生

