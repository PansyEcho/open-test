## 1. 轻量故障修复

- [x] 1.1 batch写入前失败保留原始异常，batch写入后继续既有恢复
- [x] 1.2 回归失败不创建Codex线程或重复任务
- [x] 1.3 当前scan的`RefundFacade#createOrder`页面入口得到有效batch、task和深链

## 2. Codex工作流

- [x] 2.1 增加显式`$open-test`和可同步的系统Skill
- [x] 2.2 增加系统源码、顺序知识准备、接口Case和Case执行MCP工具
- [x] 2.3 `ScenarioStep.operation_id`与旧`tool_id`二选一兼容

## 3. QA操作

- [x] 3.1 扫描并执行固定外部DSF引用
- [x] 3.2 扫描消费者MQ并以ACK/message ID返回成功
- [x] 3.3 扫描数据库并执行受限参数化读写事务
- [x] 3.4 业务结果与业务错误完整持久化，连接与凭据继续隐藏

## 4. 验收与门禁

- [x] 4.1 完成外部Trade查询、Refund MQ、PSI INSERT/UPDATE/SELECT和READ Case真实QA验收
- [x] 4.2 完成Python、Java、Skill和OpenSpec strict门禁
- [x] 4.3 完成OCR delegation审查并修复合理High/Medium
- [x] 4.4 更新`docs/status.md`且不修改`queryList`知识
