# scriptgen-source-scan Specification

## Purpose
TBD - created by archiving change single-system-source-analysis. Update Purpose after archive.
## Requirements
### Requirement: 真实scriptgen是可执行工具唯一来源
系统 SHALL 将配置的真实scriptgen作为源码发现输入，结合已有Java语义与精确Maven/JAR解析生成接口契约。Facade执行 SHALL 使用已发布DSF声明，不依赖HTTP脚本、业务文件命名或AI解析兜底。

#### Scenario: 成功扫描Facade和Job
- **WHEN** scriptgen返回有效扫描结果
- **THEN** 每个可靠Facade保留请求响应类型、源码位置和source_id；未启用的旧Job规则不影响Facade完整性

#### Scenario: scriptgen不可用
- **WHEN** 配置路径不存在、命令失败或manifest无效
- **THEN** 扫描任务失败并给出精简诊断，不生成伪造工具

#### Scenario: 入口与工具数量核对
- **WHEN** 扫描完成
- **THEN** Facade目录由有效发布声明与框架入口生成，退役HTTP工具不进入执行目录

### Requirement: 程序解析与可靠结果发布
系统 SHALL 复用源码与实际classpath中的精确依赖类型解析请求、响应、继承与泛型，记录缺失类型位置及已解决或不适用诊断。可靠接口、资源、契约与关系 SHALL 在部分完成时发布到现有表；latest指向当前固定版本最近一次成功发布的扫描，失败扫描不得替换可用结果。任务 SHALL 冻结扫描和契约版本。

#### Scenario: 依赖DTO不在本项目源码
- **WHEN** Facade使用精确依赖JAR中的JobRequest
- **THEN** 程序解析traceId、operator、jobName、startDate、ext及依赖版本，不调用AI

#### Scenario: 局部缺失和恢复
- **WHEN** 单个DTO确实不可解析
- **THEN** 对应目标显示明确缺口，其他可靠接口仍可用；补齐实际依赖后程序重新扫描恢复且历史Case不变

#### Scenario: 通用入口和MQ关联
- **WHEN** 项目更换名称或包名并通过XML、注解或继承发布接口和Listener
- **THEN** 使用相同扫描路径识别入口并把MQ资源关联真实处理方法

#### Scenario: 同一filter文件内重复键
- **WHEN** 同一环境filter文件内重复定义同名属性且值不同
- **THEN** 按Java Properties加载语义取后出现值并记录INFO提示；跨文件同名不同值仍显式判冲突、丢弃该键并告警实际读取的环境后缀

#### Scenario: SOF事件派发解析容错
- **WHEN** fireEvent调用的实参链含注解处理器生成的方法导致完整符号求解失败
- **THEN** 显式与隐式接收者共用同一派发判定：接收者须为SOFContext或其子类型，且所有名称和实参数量可能匹配的候选方法均声明于SOFContext；候选检查包含继承和可变参数，存在业务重载、覆盖或无法证明归属时保留解析缺口，不生成监听器派发边。通过派发判定后，按唯一同名同参数方法（含继承方法）回推事件类型候选；候选返回类型仍含未代入的类型变量或无法唯一确定时告警附单行根因
- **AND** 无接收者的fireEvent按所在类型及其祖先查找候选声明；不属于SOFContext的普通包装类型不得误报派发缺口，所在类型或祖先链不可求解时记录派发缺口

#### Scenario: SOF子类型中的同名业务重载
- **WHEN** 完整符号求解失败，SOF子类型声明或继承了与fireEvent调用实参数量可能匹配的业务重载或覆盖，包括可变参数方法
- **THEN** 显式或隐式接收者均保留派发解析缺口，不把业务重载推断为SOF监听器调用

#### Scenario: 无歧义SOF派发继续可用
- **WHEN** 完整符号求解失败，但继承的SOF声明是唯一可能来源，其他业务重载的固定参数数量不匹配
- **THEN** 继续解析事件类型并保留真实SOF监听器候选边；精确符号求解成功时仍以精确声明为准

