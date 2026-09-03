## ADDED Requirements

### Requirement: Java知识生成必须输出typed入口事实候选

系统 SHALL 要求知识Agent从注册源码输出入口前置Fact、产出Fact、状态转换、候选操作、绑定路径和确切证据的typed候选，且不访问QA或输出真实业务ID。

#### Scenario: 分析RefundFacade cancel
- **WHEN** Agent从取消状态校验源码识别退票单前置状态
- **THEN** 草稿包含 `RefundOrder(CANCELLABLE)` 候选、请求绑定候选和源码证据，但不直接进入正式知识

#### Scenario: 退款仓无法证明出票状态
- **WHEN** 退款源码只能证明原订单存在而不能证明其必须ISSUED
- **THEN** `TicketOrder(ISSUED)`保持AI候选，不能标为CODE_PROVEN
