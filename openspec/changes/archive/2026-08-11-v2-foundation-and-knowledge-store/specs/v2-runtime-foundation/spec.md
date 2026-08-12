## ADDED Requirements

### Requirement: 类型化V2运行时
系统 MUST 通过Pydantic模型校验V2领域输入和输出，并且V2应用服务不得依赖legacy `Platform`。

#### Scenario: 拒绝无效系统定义
- **WHEN** 调用方提交缺少系统ID或源码目录的系统定义
- **THEN** 系统返回结构化校验错误且不写入知识仓库

### Requirement: 工作流日志上下文
系统 MUST 在工作流入口绑定 `trace_id`、`filter1` 和 `filter2`，并在正常或异常退出时清理上下文。

#### Scenario: 异常后清理上下文
- **WHEN** 工作流在执行期间抛出异常
- **THEN** 调用结束后当前线程或异步上下文不再保留该工作流的日志字段

### Requirement: 可查询的本地任务
系统 MUST 为长时间扫描、Agent和执行工作创建任务ID，并持久化状态、结果摘要和错误摘要。

#### Scenario: 查询已完成任务
- **WHEN** 后台任务成功结束后调用方按任务ID查询
- **THEN** 系统返回完成状态、开始结束时间和结果引用
