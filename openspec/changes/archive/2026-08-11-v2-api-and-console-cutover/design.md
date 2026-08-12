# V2 API与控制台设计

## API组织

所有路由位于 `/api/v2`，系统资源向下包含scans、knowledge、scenarios、snapshots和runs；长任务统一返回TaskRecord并通过 `/api/v2/tasks/{task_id}` 轮询。同步编译和只读查询直接返回领域模型。

领域异常统一映射为not_found、validation_error、scope_violation和execution_failure，Pydantic负责HTTP 422传输校验。响应不返回Python堆栈、QA密钥或完整执行命令请求体。

## 控制台

FastAPI直接托管 `opentest/web` 静态文件。控制台包含：系统与基线、扫描任务、知识搜索与问题、自然语言场景、变体与Snapshot、执行任务与报告。所有请求集中在一个API客户端函数，便于后续替换UI框架。

页面只展示业务ID、状态、摘要和结构化差异；不渲染本地环境密钥。轮询有客户端截止次数，服务端Oracle仍使用独立deadline。

## 兼容策略

legacy入口保持原样，旧43个测试持续通过。V2稳定且用户确认后再创建独立change删除legacy；本change不让新控制台回退调用旧API。
