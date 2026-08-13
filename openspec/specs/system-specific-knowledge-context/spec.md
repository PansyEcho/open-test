# system-specific-knowledge-context Specification

## Purpose
TBD - created by archiving change system-specific-knowledge-discovery-and-task-progress. Update Purpose after archive.
## Requirements
### Requirement: 系统专属上下文自动发现

系统 SHALL 在单系统源码扫描成功后自动发现业务术语、外部应用及需要用户补充的背景问题，并以当前`system_id`为隔离边界保存候选、问题、答案和源码证据。普通系统 SHALL 不出现Booking.Core专属术语或流程。

#### Scenario: 退款系统完成扫描

- **WHEN** 退款系统的Manifest发布成功
- **THEN** 系统基于退款源码生成至少一个真实术语、外部应用或背景问题
- **AND** 不生成港币、EBK、票机、收单、HT或createOrder专属候选
- **AND** 发现失败不会撤销已经发布的Manifest

#### Scenario: 增量重扫保留人工答案

- **WHEN** 已确认候选在重扫后仍存在但源码证据发生变化
- **THEN** 系统保留人工含义和答案并把候选标记为`NEEDS_REVIEW`
- **AND** 新候选生成新问题，已消失候选标记为`STALE`

#### Scenario: Agent返回越界引用

- **WHEN** Agent候选引用其他系统、未知目标或当前源码根之外的文件
- **THEN** 系统确定性拒绝该输出
- **AND** 不污染当前或其他系统的上下文与问题

### Requirement: 统一待确认问题

系统 SHALL 统一投影缺失背景叙述、开放候选、知识草稿和修订问题，并确保按钮红色数字与未回答问题列表一致。

#### Scenario: 旧草稿包含开放问题

- **WHEN** 当前系统已有包含开放问题的旧知识草稿
- **THEN** 该问题立即进入统一列表和红色数量
- **AND** 旧草稿标记为需要重新生成而不被删除

