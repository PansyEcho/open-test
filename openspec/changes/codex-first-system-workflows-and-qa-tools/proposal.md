# Change: Codex 优先的系统工作流与 QA 工具

## Why

OpenTest 已能从页面把单接口知识任务交给 Codex，也能执行同系统 Facade 和 Job，但系统接入、批量接口知识、接口级 Case、外部 DSF、MQ 和数据库仍不能在一个显式 Skill 中完成。知识准备的异常恢复还会在 batch 尚未落盘时用 `knowledge draft batch not found` 覆盖真实失败原因。

## What Changes

- 最小修复 Codex 客户端知识准备异常：batch 不存在时直接保留原异常，存在时继续复用既有恢复流程。
- 新增显式 `$open-test` 系统管理 Skill，并把系统 Skill 扩展为源码、顺序多接口知识、接口级 Case 和统一 QA 操作入口。
- Case 允许在接口知识不完整时保存，只有缺数据或 oracle 的具体变体保持 `BLOCKED`。
- 统一操作目录增加调用方扫描固定的外部 DSF、MQ 消费者发送和受限数据库操作。
- QA 业务结果与业务异常完整返回；Token、配置和连接凭据继续隐藏。

## Scope

真实验收只使用当前 Refund.Core scan 和 QA 契约：外部 `TradeFacade#queryList` READ、一个Refund消费者MQ消息、`saas_refund_order_psi` 唯一软删除验收记录和一个READ Case。不得重新生成或修改 `RefundFacade#queryList` 知识。
