# Change: 场景覆盖目标与可重放数据变体

## Why

知识节点已经能解释createOrder深层规则，但测试仍需要把业务决策、状态、依赖结果和边界转换为可执行Case。裸笛卡尔积会产生大量低价值组合，自然语言若直接补全未知字段又会生成不可执行或错误场景。

## What Changes

- 从已发布知识生成稳定CoverageTarget、ScenarioDefinition和ScenarioVariant。
- 使用业务约束、等价类、边界值与确定性pairwise选择组合。
- 将自然语言港币、多乘客、成人儿童与订单数量编译为结构化约束。
- 知识或执行模板不足时返回缺失条件，不猜测QA业务数据。
- 将Case YAML写入系统知识包并保持可重放稳定ID。

## Scope

一期只生成 `train-booking-core` 的 `TradeFacade#createOrder` 主流程Case，不创建跨系统前置动作。

## Non-Goals

- 不执行真实DSF或数据库校验。
- 不自动生成跨系统数据准备。
- 不承诺解析任意自然语言业务请求。
