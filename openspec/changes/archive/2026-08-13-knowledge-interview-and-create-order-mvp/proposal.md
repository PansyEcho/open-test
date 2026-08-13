# Change: 知识访谈与 createOrder 可用 MVP

## Why

多系统控制台已恢复可靠接入和扫描，但知识页面仍缺少项目背景访谈、可编辑的问题回答与用户反馈修订闭环；自然语言测试在入口知识未确认时也缺少面向业务的修复引导。Booking.Core 的 31 项生命周期 Case 仍等待大量 Fixture，本轮需要先用一份本地安全 Fixture 打通 `TradeFacade#createOrder` 的第一条真实业务闭环。

## What Changes

- 增加项目背景、上下游和业务术语访谈，答案按受影响知识目标传播。
- 增加待确认问题回答、知识反馈、影响分析、草稿重生成与前后差异展示。
- 自然语言缺少已确认入口知识时返回可展示的 `BLOCKED` 预览和修复动作，不抛裸异常。
- 增加 Git 忽略、0600、读取时不回显原始请求与乘客身份的 createOrder MVP Fixture。
- 增加只验证创单的 Booking.Core MVP 编排：真实 DSF、MySQL 主库、临时库、Item 和 Redis；MQ 仅在可归因时为 `EFFECT_ONLY`，TiDB保持阻塞。
- 在知识库和测试执行页面提供引导式表单与本地配置状态。

## Scope

本 Change 只完成知识访谈闭环和 Booking.Core `createOrder` 单接口 MVP。真实 QA 执行必须等用户在回环页面填写最小 Fixture并显式确认；自动化验证阶段不访问 QA。

## Non-Goals

- 不执行出票、取消或31项完整生命周期回归。
- 不使用数据库写入造状态，也不自动清理测试订单。
- 不要求TiDB WRITE权限，不用MySQL结果冒充TiDB。
- 不把Token、完整请求、乘客身份或远程配置写入Git、日志、任务、Snapshot、报告或Agent输入。
- 不归档仍处于 `WAITING_QA_INPUT` 的 `dsf-execution-and-oracles`。
