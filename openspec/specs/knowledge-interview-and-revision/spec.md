# knowledge-interview-and-revision Specification

## Purpose
TBD - created by archiving change knowledge-interview-and-create-order-mvp. Update Purpose after archive.
## Requirements
### Requirement: 知识生成前提供可传播的业务访谈

系统 SHALL 允许用户集中维护系统背景、上下游和业务术语，并 SHALL 将一个答案传播到所有明确受影响的同系统知识草稿，而不是逐接口重复提问。

#### Scenario: 回答共享业务术语
- **WHEN** 用户回答“EBK”的业务含义且该问题影响多个入口和共享逻辑
- **THEN** 系统更新该问题及全部影响草稿并返回影响清单，但不自动发布为已确认知识

#### Scenario: 访谈内容安全进入Agent
- **WHEN** 本地Agent增强知识草稿
- **THEN** 输入可包含用户业务说明，但不包含Token、Fixture、乘客身份或QA结果

### Requirement: 用户反馈形成可审查修订

系统 SHALL 把用户指出的知识错误或缺失转换为澄清问题和影响计划，并在答案齐备后重新生成相关草稿、展示前后差异，最后由用户确认发布。

#### Scenario: 指出知识内容错误
- **WHEN** 用户在知识页面说明某条分单规则不正确
- **THEN** 系统返回受影响节点、待确认问题和草稿差异，而不是直接覆盖Git知识

