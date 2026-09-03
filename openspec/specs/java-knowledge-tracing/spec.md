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

### Requirement: Java知识生成必须输出typed入口事实候选

系统 SHALL 要求知识Agent从注册源码输出入口前置Fact、产出Fact、状态转换、候选操作、绑定路径和确切证据的typed候选，且不访问QA或输出真实业务ID。

#### Scenario: 分析RefundFacade cancel
- **WHEN** Agent从取消状态校验源码识别退票单前置状态
- **THEN** 草稿包含 `RefundOrder(CANCELLABLE)` 候选、请求绑定候选和源码证据，但不直接进入正式知识

#### Scenario: 退款仓无法证明出票状态
- **WHEN** 退款源码只能证明原订单存在而不能证明其必须ISSUED
- **THEN** `TicketOrder(ISSUED)`保持AI候选，不能标为CODE_PROVEN

