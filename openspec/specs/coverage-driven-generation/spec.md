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

### Requirement: 覆盖分母必须由typed条件分类决定

系统 SHALL 仅把入口字段已证明影响分支、计算、路由或核心结果的 `INPUT_COVERAGE` 条件加入覆盖分母；有状态实体、Oracle、故障、环境和内部诊断不得被错误展开为Pairwise因素。

#### Scenario: 内部错误响应方法可达
- **WHEN** 可达内部方法的计算或下游调用没有入口字段绑定且只组装错误响应
- **THEN** 系统将其记录为 `INTERNAL_DIAGNOSTIC`，不产生语义硬阻塞或覆盖组合

#### Scenario: 入口字段真实控制路由
- **WHEN** 程序证据把入口字段绑定到分支或路由选择
- **THEN** 系统生成不可删除的输入覆盖义务

#### Scenario: 首版未实现的条件处理器
- **WHEN** 冻结条件既不是内部诊断或有状态实体，也没有同证据来源的现有义务处理器
- **THEN** 编译返回明确unsupported blocker而不生成假Ready Variant

#### Scenario: AI尝试删除程序覆盖分母
- **WHEN** Semantic Draft使用旧的无需新增动作、引用其他条件或提交与原条件不兼容的义务类型
- **THEN** 系统保留Program Requirement并返回校验或不支持阻塞，只有精确AI条件的兼容typed replacement才能替换占位义务

### Requirement: 副作用和故障覆盖必须保持真实语义

系统 SHALL 将无条件DB/MQ副作用投影为Oracle义务，并在缺少真实故障能力时阻塞故障路径。

#### Scenario: 无条件MQ写入
- **WHEN** 程序证明入口执行会发送MQ但该字段不改变业务路径
- **THEN** 系统添加MQ观察义务且不增加输入Factor

