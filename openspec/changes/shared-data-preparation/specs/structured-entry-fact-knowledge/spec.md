## MODIFIED Requirements

### Requirement: 正式入口知识必须保存稳定typed事实

系统 SHALL 对已有正式入口知识保留 `requires_facts`、`produces_facts`、`state_transitions`、`candidate_operations`、`binding_paths` 和 `evidence_refs`，每条历史断言保留稳定ID、来源和证据；新Case、数据和自然语言操作不得要求预先生成这些知识节点。

跨系统 `candidate_operations` SHALL 独立冻结provider系统、latest scan、baseline和规范化证据commit；consumer与provider存在同名相对路径时不得复用consumer证据，provider代际变化后旧断言不得继续作为current Producer证明。

#### Scenario: 发布cancel前置事实
- **WHEN** 用户读取已保存且源码证据和Action请求绑定有效的历史cancel事实
- **THEN** 正式知识仍可读取 `RefundOrder(CANCELLABLE)` 及 `refundSerialNo` 到实体身份字段的typed绑定

## REMOVED Requirements

### Requirement: Case编译必须读取exact正式入口事实
**Reason**: 正式知识节点不再是Case编译的必需输入。
**Migration**: Case直接消费固定源码的接口契约和内嵌数据定义，已有事实只作为明确来源的历史参考，不猜测不存在的结论。
