# java-knowledge-tracing Specification

## Purpose
TBD - created by archiving change knowledge-generation-and-indexing. Update Purpose after archive.
## Requirements
### Requirement: 入口知识可追溯到深层业务规则

系统 SHALL 从扫描入口追踪实现、校验、业务方法、Builder、状态与外部依赖，并为结论保留源码路径、符号、行号和scan baseline。

#### Scenario: createOrder纵向切片
- **WHEN** 用户为 `TradeFacade#createOrder` 生成知识
- **THEN** 入口可沿关系找到CreateOrderValidator、CreateOrderServiceInvoker、订单状态流转和港币逐乘客报价规则

#### Scenario: 无法解析动态调用
- **WHEN** 分析器不能由代码确定实际实现或业务含义
- **THEN** 结论保持inferred或生成待确认问题，不标记为code_verified

