# structured-entry-fact-knowledge Specification

## Purpose
TBD - created by archiving change deterministic-agent-hybrid-case-lifecycle. Update Purpose after archive.
## Requirements
### Requirement: 正式入口知识必须保存稳定typed事实

系统 SHALL 在exact latest-scan入口保存 `requires_facts`、`produces_facts`、`state_transitions`、`candidate_operations`、`binding_paths` 和 `evidence_refs`，每条断言具有稳定ID、来源和证据。

跨系统 `candidate_operations` SHALL 独立冻结provider系统、latest scan、baseline和规范化证据commit；consumer与provider存在同名相对路径时不得复用consumer证据，provider代际变化后旧断言不得继续作为current Producer证明。

#### Scenario: 发布cancel前置事实
- **WHEN** 用户确认源码证据和Action请求绑定均有效的cancel候选
- **THEN** 正式知识保存 `RefundOrder(CANCELLABLE)` 及 `refundSerialNo` 到实体身份字段的typed绑定

### Requirement: 正式入口事实必须执行断言级信任校验

系统 SHALL 只接受 `CODE_PROVEN`、`KNOWLEDGE_CONFIRMED` 或 `USER_CONFIRMED` 正式断言，并校验latest源码、Fact契约、Action Schema、关系类型、候选操作和冲突。

#### Scenario: AI候选尝试直接发布
- **WHEN** 正式KnowledgeNode包含来源为AI_CANDIDATE的断言
- **THEN** 持久化校验拒绝该节点

#### Scenario: Fact契约版本迁移替换旧正式断言
- **WHEN** 用户精确选择同一业务slot或同一request binding目标的新候选，列出被取代的正式断言ID，并要求current代码证明
- **THEN** 系统只移除这些旧断言，在全部新候选通过同一程序证明器后发布 `CODE_PROVEN` 新断言，并保留无关正式事实和未选择候选

#### Scenario: 替换目标或代码证明不成立
- **WHEN** 候选试图替换不同slot、不同request path或不受支持类型，或任一选择候选缺少完整current程序证据
- **THEN** 系统原子拒绝整个替换，不删除正式断言，也不移除任何候选

### Requirement: Case编译必须读取exact正式入口事实

系统 SHALL 把formal `requires_facts` 转为冻结Case条件，并只把产出、转换和候选操作用于验证Producer Recipe或约束typed草稿。

#### Scenario: 入口没有正式前置事实
- **WHEN** latest入口仅有未确认AI候选
- **THEN** 系统不猜测前置Fact或发布Recipe，只显示待确认或友好阻塞

