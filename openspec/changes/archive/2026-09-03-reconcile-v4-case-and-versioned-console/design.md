# Design: 以当前实现为证据恢复 OpenSpec 真相

## Reconciliation Strategy

1. 使用 OpenSpec 自带 archive 合并十三个任务已完成 change，保留带日期的不可变历史目录。
2. 四个仍含未完成任务的 change 不归档，其勾选状态继续表达真实进度。
3. 对没有历史 change 的 V4、模型、环境和页面能力建立本补录 change；要求只描述当前代码与测试已经证明的行为。
4. 本 change 通过严格校验后归档，使 `openspec/specs` 再次成为当前事实来源。

## Runtime Boundaries Recorded

- V4 只解析 latest scan 中知识 READY 的唯一 Facade Entry。
- Codex 通过当前用户 App Server Provider 创建同会话 thread/turn；OpenTest 不读取 Provider Token。
- AI 只提交有限 DSL，动态业务身份必须追溯到真实 Runtime Operation 输出，Oracle 必须结构化且通过只读资源校验。
- QA 执行结果保留每步请求、响应、execution ID、断言及错误；缺数据时使用 BLOCKED，Provider 或执行错误使用 FAILED。
- 源码读取固定到 handoff 的 commit 快照，后续 working tree 变化不改变本次生成语义。

## Console Boundaries Recorded

- 扫描结果页把知识目录与 scan、commit、revision、branch、dirty 状态放在同一版本卡中。
- 回归 Case 页只调用 V4 API；用户可启动生成、轮询、打开 Codex 深链或只读查看完整 JSON。
- 页面切换使用请求代次隔离迟到成功与异常响应，避免不同系统、scan 或 V4 视图串写。

