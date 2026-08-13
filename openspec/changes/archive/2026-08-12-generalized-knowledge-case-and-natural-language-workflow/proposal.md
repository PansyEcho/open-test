# Change: 通用知识、Case与自然语言测试闭环

## Why

现有深层知识追踪只针对`TradeFacade#createOrder`硬编码，其他Facade、Job、状态流转和事件监听器只能得到扫描目录或浅层说明。回归Case也缺少可核查的“场景矩阵确认”阶段，自然语言入口仍未形成执行前预览与确认门禁。

## What Changes

- 将Java知识追踪升级为适用于Facade、Job、状态Actor、事件Listener和共享公共逻辑的确定性深层分析。
- 增加Codex优先、Claude Code兜底的本地只读Agent自动检测；Agent输入不包含Token、Fixture或QA配置。
- 提供知识目录、节点草稿、批量生成、问题回答和人工确认API与控制台工作区。
- 按“场景矩阵→人工确认→Case→执行步骤”建立全量回归生成流程，保留已有31个人工Booking.Core Case。
- 将业务自然语言解析为可读测试方案预览和缺失业务字段，用户确认前不访问业务执行入口；确认后才执行并可保存为回归Case。

## Scope

本change完成单系统、DSF代码与现有知识真相源上的通用闭环。它可以读取源码、知识和公开结果校验能力，但不会补造QA Fixture、运行真实创单或放宽TiDB/全局Job门禁。

## Non-Goals

- 不验证跨系统关系、WEB页面执行或浏览器业务Case。
- 不声称31个真实QA生命周期Case通过。
- 不覆盖已有人工知识区域和31个人工Case。
- 不允许本地Agent读取Token、Fixture、连接配置、QA响应或执行QA操作。
