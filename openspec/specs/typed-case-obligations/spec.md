# typed-case-obligations Specification

## Purpose
TBD - created by archiving change typed-case-obligations-and-rules. Update Purpose after archive.
## Requirements
### Requirement: 覆盖要求必须按生成模型分型

系统 SHALL 使用Factor、Boundary、Decision、Sequence、FaultInjection、Effect和Requirement七类覆盖义务，且每项保存入口、来源规则和独立身份。

#### Scenario: 顺序循环中的中间实体失败
- **WHEN** 规则要求循环中间实体失败
- **THEN** 系统冻结FaultInjectionObligation而不是普通Factor字段

#### Scenario: DB或MQ副作用
- **WHEN** 代码证据表明入口会产生数据库或MQ副作用
- **THEN** 系统冻结EffectObligation且不默认增加参数组合

### Requirement: 冻结清单不得静默丢失规则义务

系统 SHALL 在规则预览中列出全部命中规则、产生义务和冲突；互斥规则不得按声明顺序静默胜出。

#### Scenario: 系统规则要求互斥取值
- **WHEN** 两条不同规则对同一目标声明不同的exclusive要求
- **THEN** 清单状态为BLOCKED且blockers包含`BLOCKED_RULE_CONFLICT`和双方规则ID

### Requirement: 覆盖义务必须区分可信来源

系统 SHALL 将每个义务标记为program、semantic或rule来源，规则和Semantic Draft均不得覆盖、删除或伪装program义务。

#### Scenario: 系统规则与程序决策使用相同目标
- **WHEN** 两者均对同一字段产生覆盖要求
- **THEN** 清单保留program义务并累加rule义务，不能用规则版本替换程序证据

