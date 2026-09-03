# java-structure-scan Specification

## Purpose
TBD - created by archiving change single-system-source-analysis. Update Purpose after archive.
## Requirements
### Requirement: 非工具入口和状态机保持结构化语义

系统 SHALL 只扫描目标Java系统`src/main/java`中的MQ监听入口和`@State`转换，并与Facade、Job共同写入扫描manifest，但状态机不得被标记为可执行工具；MQ入口 SHALL 只由当前系统Git固定规则路径中的结构化规则，对精确FQN注解或直接父类/接口、文件顶层具体类直接声明handler完整签名和有效payload位置的唯一匹配产生。

#### Scenario: 发现状态转换

- **WHEN** Java类包含可解析的`@State(from={...}, to={...})`
- **THEN** 结果包含状态枚举、from/to集合、actor阶段、类名、源码相对路径和注解行号

#### Scenario: 规则识别注解MQ入口

- **WHEN** 具体Java类或方法的监听注解和handler满足唯一框架规则
- **THEN** 结果包含Consumer类、真实handler、topic或队列提示、rule ID、匹配owner和源码证据

#### Scenario: 规则识别继承MQ入口

- **WHEN** 具体类继承或实现规则声明的owner类型并声明符合签名的handler方法
- **THEN** Entry指向该具体handler而不是继承的框架回调或根据类名猜测的方法

#### Scenario: 无规则或规则歧义

- **WHEN** 监听迹象不存在唯一规则，或多个规则匹配同一handler
- **THEN** 扫描继续完成并在warnings中记录文件和原因，不创建MQ Entry

#### Scenario: 删除系统规则

- **WHEN** 系统Git规则是某类MQ入口的唯一识别依据且该规则被删除
- **THEN** 下一次真实扫描不再包含对应Entry

#### Scenario: 测试源码或文本伪handler

- **GIVEN** `src/test/java`、生成目录、嵌套类、注释或方法体调用中出现符合名称的Listener或handler文本
- **WHEN** 程序扫描入口
- **THEN** 不创建MQ Entry，且不得以同简单名但不同FQN的框架类型替代精确规则身份

#### Scenario: 顶层非具体类包含嵌套Listener

- **GIVEN** Java文件顶层是interface或enum，其中嵌套具体类声明了匹配handler
- **WHEN** 程序扫描入口
- **THEN** 不得把嵌套类误认为文件顶层具体类，也不得生成错误FQN的MQ Entry

#### Scenario: 系统规则路径通过符号链接逃逸

- **GIVEN** 固定系统规则文件自身或`source-rules`祖先是指向系统Git根外的符号链接
- **WHEN** 程序加载系统规则
- **THEN** 扫描以校验错误终止，不读取外部未版本化规则

#### Scenario: payload位置不存在

- **GIVEN** 框架规则声明的payload参数位置超出真实handler参数数量
- **WHEN** 程序尝试匹配该方法
- **THEN** 记录无法唯一识别的warning且不创建缺少请求类型的MQ Entry

