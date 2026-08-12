## ADDED Requirements

### Requirement: 非工具入口和状态机保持结构化语义

系统 SHALL 扫描目标Java系统的MQ监听入口和 `@State` 转换，并与Facade、Job共同写入扫描manifest，但状态机不得被标记为可执行工具。

#### Scenario: 发现状态转换
- **WHEN** Java类包含可解析的 `@State(from={...}, to={...})`
- **THEN** 结果包含状态枚举、from/to集合、actor阶段、类名、源码相对路径和注解行号

#### Scenario: 发现MQ监听入口
- **WHEN** Java类或方法使用受支持的MQ监听注解
- **THEN** 结果包含Consumer类、方法、topic或队列提示和源码证据

#### Scenario: 无法解析注解
- **WHEN** 注解存在但缺少必要状态或入口信息
- **THEN** 扫描继续完成并在warnings中记录文件和原因，不猜测缺失语义
