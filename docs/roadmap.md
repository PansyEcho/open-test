# OpenTest 产品路线图

## 当前阶段：单系统DSF闭环

- 建立V2基础、Git知识真相源和SQLite派生索引。
- 扫描一个Java DSF系统的Facade、Job、状态机和外部交互入口。
- 以 `TradeFacade#createOrder` 跑通知识、场景、执行和Oracle纵向闭环。
- 完成单系统内部的增量影响分析。

## 后续阶段

1. 生成Codex和Claude Code可复用的系统Skill。
2. 扩展多系统注册、公共系统关系和跨系统场景。
3. 支持普通HTTP服务扫描与执行。
4. 支持Web应用浏览器执行器和稳定语义选择器。
5. 复用API与数据库完成Web测试数据准备和业务Oracle。
6. 增加多人协作和可选的中央只读聚合服务。

## 明确非目标

- 当前阶段不验证火车票、国际机票和结算系统的跨系统知识。
- 当前阶段不引入embedding或向量数据库。
- 当前阶段不迁移legacy MVP生成的数据。
