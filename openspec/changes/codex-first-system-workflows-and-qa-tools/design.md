# Design: Codex 优先的系统工作流与 QA 工具

## 轻量知识恢复

`_submit_codex_client_handoff` 保留 `prepare_client_handoff` 抛出的原异常。只有 draft batch 已存在时才进入当前半成品恢复；否则记录 system、target、batch 和异常类型后直接重抛。既有准备顺序、任务状态和持久化模型不变。

## Skill 工作流

手写 `$open-test` 只负责注册、更新、扫描和系统 Skill 同步。生成的 `$open-test-<system-id>` 固定绑定一个系统，显式调用，顺序处理多个知识目标；有效知识默认跳过。它复用现有 handoff MCP 完成候选提交，不创建第二个Codex任务。

接口 Case 从 latest scan 形成最低接口覆盖目标。缺知识会记录 gap，但不阻塞矩阵和 Case 保存；缺少业务输入或 oracle 的变体标记 `BLOCKED`。`ScenarioStep` 以 `tool_id` 或 `operation_id` 二选一执行，operation步骤复用统一幂等执行记录。

## 统一 QA operation

外部 DSF 只从调用方 `sof:reference` 及显式 `sof:method` 生成，执行时使用同一扫描的 `env=qa`、`targetenv=test` Profile。MQ 只从扫描消费者的 NameServer、Topic、Tag 配置键生成发送操作。数据库只从扫描数据源生成，Worker 双重校验单条参数化 `SELECT/SHOW/EXPLAIN/INSERT/UPDATE`，拒绝多语句、DELETE、DDL和未声明使用原因；写语句显式提交或回滚。

MQ和数据库复用已有 qa-oracle-worker 的公司SDK依赖，但使用独立一次性入口。属主专用的临时请求文件只包含扫描资源定义、业务参数和本次操作实际需要的配置值，使用后随0700临时目录删除；这些配置不进入响应或日志。响应保留业务行、Broker ACK和业务异常，仅清除连接及凭据形态。
