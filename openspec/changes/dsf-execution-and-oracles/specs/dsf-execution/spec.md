## ADDED Requirements

### Requirement: 场景只执行真实生成工具

系统 SHALL 仅在QA环境从绑定扫描manifest解析逻辑工具ID，验证脚本位于tool_root且不是固定shim，并以无shell子进程执行。

#### Scenario: 执行createOrder变体
- **WHEN** 变体引用 `facade.trade.create_order`
- **THEN** DsfExecutor调用该扫描真实生成的create-order脚本并保存命令、退出码、JSON结果和耗时

#### Scenario: 工具路径越界
- **WHEN** manifest脚本越过tool_root或路径属于platform固定shim
- **THEN** 执行在启动子进程前失败

#### Scenario: 单Case请求非QA环境
- **WHEN** 独立变体执行请求声明test、prod或其他非QA环境
- **THEN** 领域模型与执行服务在工具启动前拒绝请求

### Requirement: 变量与断言保持类型

系统 SHALL 类型化解析inputs、steps和qa引用，并将稳定业务断言失败输出为结构化差异。

#### Scenario: 绑定前序订单号
- **WHEN** 后续步骤引用完整占位符 `${steps.create-order.output.response.orderSerialNo}`
- **THEN** 保留原始JSON类型并在字段缺失时明确失败
