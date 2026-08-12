# coverage-driven-generation Specification

## Purpose
TBD - created by archiving change scenario-and-variant-generation. Update Purpose after archive.
## Requirements
### Requirement: Case必须反向追溯知识覆盖目标

系统 SHALL 从业务决策、状态流转、依赖结果和边界生成CoverageTarget，并使每个Scenario和Variant保存覆盖目标ID。

#### Scenario: 生成createOrder主流程Case
- **WHEN** 用户为createOrder生成全量主流程Case
- **THEN** 成人必需、港铁直接收单、港币价格校验、报价来源和关键状态均存在覆盖目标与至少一个变体

### Requirement: 变体组合受业务约束控制

系统 SHALL 使用等价类、边界值和pairwise选择有限组合，不生成违反成人必需等已知规则的成功Case，也不生成裸笛卡尔积。

#### Scenario: 港币成人儿童组合
- **WHEN** 场景要求港币、多乘客且包含成人儿童
- **THEN** 每个成功变体至少包含一名成人和一名儿童，并拥有逐乘客foreignTicketPrice与稳定预期

