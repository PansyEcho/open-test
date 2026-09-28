# candidate-operation-catalog Specification

## Purpose
TBD - created by archiving change candidate-operation-catalog. Update Purpose after archive.
## Requirements
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
系统 SHALL 从当前系统候选目录开始，人工SystemDependencyBinding和两层系统可达范围不得自动导入相关系统的全部候选。当前场景存在无法自行取得或构造的入参时，流程 SHALL 根据扫描证明的接口关系检索并选择精确Operation，保存缺失入参说明及固定来源。候选发现不授予执行权限；查询调用关系不等于数据创建职责。

#### Scenario: 搜索未绑定上游系统
- **WHEN** 退款与出票系统均已扫描但当前场景尚未选择出票接口
- **THEN** 退款普通Candidate搜索仅返回本系统方法，不自动合并出票目录

#### Scenario: 搜索显式绑定的上游系统
- **WHEN** 系统存在历史人工绑定但场景没有未满足入参或精确接口选择
- **THEN** 该绑定不会扩大当前候选或执行范围

#### Scenario: 绑定系统发生扫描漂移
- **WHEN** 按需选择的provider注册基线与当前完整扫描不一致或接口存在歧义
- **THEN** 选择返回具体阻塞原因，不能静默换用其他版本或同名方法

#### Scenario: 删除绑定后读取旧Candidate
- **WHEN** 历史人工绑定删除后仍以consumer身份请求其他系统旧Candidate
- **THEN** 普通Candidate详情不因旧绑定开放其他系统目录

#### Scenario: 查询已取得所需输入
- **WHEN** 已选查询接口实际取得并回查满足当前场景所需数据
- **THEN** 数据准备停止扩展依赖，不继续纳入该查询系统的其他上下游

#### Scenario: 已选provider仍无法满足输入
- **WHEN** A已选B接口而B仍缺少当前场景输入，任务给出非空缺失路径和用途并选择C的精确接口
- **THEN** 系统以已冻结B扫描为来源继续解析C的规范接口，不受总计两层限制
- **AND** C已经固定时保持原扫描；新增C后也只开放该次选择的接口

#### Scenario: Case选用固定共享数据函数
- **WHEN** Case显式选择已发布共享函数的精确版本
- **THEN** 编译前仅合入该函数实际runtime_call使用的接口、契约修订和固定扫描
- **AND** 同系统已有扫描或契约修订冲突时拒绝合入，不扩大为提供方整个接口目录

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

### Requirement: 扫描发布保存接口级关系与基础契约
系统 SHALL 在固定源码扫描阶段保存接口输入输出结构、源码可证明的用途和字段说明、明确的未知约束、零版契约及程序覆盖。接口关系 SHALL 区分实际入口可达调用、仅配置声明和MQ消息流，无法确定调用入口时保留未知。DSF匹配须同时满足完整路由与接口符号；MQ相同路由的多个有效消费者为一对多关系。

#### Scenario: 基础契约不依赖AI补充
- **WHEN** 扫描完成而接口尚未生成任何人工或AI说明
- **THEN** 后续流程可直接读取已持久化零版契约
- **AND** 没有证明执行校验的字段保留unknown，不将注解或注释直接升级为required或optional

#### Scenario: 新系统补全双方关系
- **WHEN** A发布完整扫描并匹配此前其他系统保存的引用
- **THEN** 自动补全A出边与指向A的入边，同一边支持上下游反向查询

#### Scenario: 重扫删除接口或解除歧义
- **WHEN** A的新扫描移除旧发布坐标或改变某坐标提供方集合
- **THEN** 系统按A旧、新坐标并集重算受影响引用，移除旧关系并正确保留未解析或歧义状态
- **AND** 历史Generation的固定接口定义不随当前关系变化

#### Scenario: 契约按需补充
- **WHEN** 固定扫描的外部接口结构或业务说明得到新的可验证证据
- **THEN** 系统追加契约版本，旧版本可精确读取且不被覆盖

#### Scenario: MQ发送入口不明或历史配置漂移
- **WHEN** 发送调用位置无法定位到可达入口，或旧扫描对应的源码配置已不可验证
- **THEN** 系统分别保留声明级入口未知或MQ源码不可用，不以类名猜测入口且不读取新checkout配置补写旧扫描事实

#### Scenario: 迁移中断后重放同一扫描
- **WHEN** 同一扫描已存在接口事实、补充契约和后续解析定义
- **THEN** 相同原始事实可重放且保留补充版本；不同原始事实报冲突，不能覆盖历史

