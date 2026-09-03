# candidate-operation-catalog Specification

## ADDED Requirements

### Requirement: 源码发现目录必须与可执行能力注册表隔离

系统 SHALL 把最新扫描发现的方法保存为只读Candidate，任何Candidate均不得被Recipe或执行器引用。

#### Scenario: 绑定包含多个Facade的源码

- **WHEN** 用户完成系统源码绑定和扫描
- **THEN** 候选目录可搜索这些方法但不会自动发布任一可执行Facade

### Requirement: Candidate必须提供选择和漂移校验所需元数据

系统 SHALL 返回FQN、完整方法签名、参数与返回DTO结构、调用方、注释、入口类型、provider与配置线索、读写线索、源码位置和源码基线。DTO结构 SHALL 包含字段类型、集合属性、校验注解和源码引用。

#### Scenario: AI搜索适合构造出票单的方法

- **WHEN** AI按业务词、方法名、DTO或provider线索搜索候选目录
- **THEN** 系统只返回当前扫描中匹配的Candidate及其只读源码元数据

#### Scenario: 最新扫描缺少完整语义分析

- **WHEN** Manifest只有已确认入口而没有完整方法索引
- **THEN** 系统只投影入口Candidate且不猜测未发现方法

### Requirement: 跨系统候选发现必须依赖显式直接绑定

系统 SHALL 只搜索consumer自身和`SystemDependencyBinding`直接授权的活动provider；绑定 SHALL 声明上下游角色和至少一个用途，且不得反向、传递或授予执行权限。

#### Scenario: 搜索未绑定上游系统

- **WHEN** 退款系统与出票系统都已独立扫描但不存在退款到出票的绑定
- **THEN** 退款系统Candidate搜索不返回出票系统方法

#### Scenario: 搜索显式绑定的上游系统

- **WHEN** 退款consumer显式绑定出票provider且角色为UPSTREAM、用途含SETUP
- **THEN** 搜索结果包含两个系统各自的scan和baseline状态，并可返回出票系统的只读Candidate

#### Scenario: 绑定系统发生扫描漂移

- **WHEN** provider的注册基线与其latest扫描不一致或bundle不完整
- **THEN** 搜索结果标记不完整并返回具体blocker，不静默忽略该系统

#### Scenario: 删除绑定后读取旧Candidate

- **WHEN** consumer删除provider绑定后继续使用曾经返回的provider Candidate ID查询详情
- **THEN** 详情查询拒绝访问该Candidate

### Requirement: 入口与方法关系必须来自精确源码身份

系统 SHALL 使用接口FQN、完整签名、具体实现和扫描Entry证据关联Candidate，不得以同名方法或目标业务名称合并接口、实现和入口。

#### Scenario: 接口与实现都存在同名方法

- **WHEN** 语义目录包含Facade接口声明和唯一具体实现
- **THEN** Candidate保留contract与implementation关系且入口只绑定到唯一具体实现

#### Scenario: 零个或多个具体实现

- **GIVEN** Entry的精确接口FQN和完整签名不存在具体实现或同时存在多个具体实现
- **WHEN** 程序投影Candidate目录
- **THEN** Entry保持PARTIAL并返回稳定实现缺失或歧义blocker，不绑定任一实现

#### Scenario: 重复Candidate身份

- **GIVEN** 同一扫描中多个模块产生相同Candidate ID
- **WHEN** 程序构建或搜索目录
- **THEN** 整个源码快照以稳定漂移blocker拒绝，不按列表顺序返回详情

### Requirement: 本阶段能力发布必须失败关闭

系统 SHALL 在Published能力阶段完成前拒绝能力草稿提交，且不得读取QA配置或写入Published注册表。

#### Scenario: 使用Candidate提交能力草稿

- **WHEN** 调用方把只读Candidate提交给现有能力草稿API
- **THEN** API返回`BLOCKED_CAPABILITY_PUBLICATION_NOT_REBUILT`且无Published资产产生

### Requirement: 后续阶段写入口必须失败关闭

系统 SHALL 在各后续OpenSpec完成前拒绝Setup发布、Fault发布/规划、Cleanup发布和V3执行，仅允许旧资产只读展示。

#### Scenario: 工作区残留旧的后续阶段资产

- **GIVEN** 工作区可能保留旧Published、Recipe、Cleanup或READY Generation
- **WHEN** 调用方在本阶段调用对应发布、规划或执行入口
- **THEN** API返回对应`NOT_REBUILT` blocker，不读取QA、不执行残留资产且不写入任何新文件
