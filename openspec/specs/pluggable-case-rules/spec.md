# pluggable-case-rules Specification

## Purpose
TBD - created by archiving change typed-case-obligations-and-rules. Update Purpose after archive.
## Requirements
### Requirement: Case规则必须使用全局与系统两层结构化资产

系统 SHALL 从随程序发布的全局规则和系统知识目录中的Git规则解析覆盖义务，不使用向量匹配或自由文本提示词承担规则执行。

#### Scenario: 系统补充单航段和多航段
- **WHEN** 系统Git规则对创单入口增加航段基数边界
- **THEN** 预览返回该系统规则及其产生的BoundaryObligation

### Requirement: 字段规则必须绑定字段自身的类型与影响证据

系统 SHALL 只对分析器证明会影响分支、计算、下游或集合处理的具体字段命中规则，不得把入口级影响类型套用到性别、联系方式等全部字段；集合基数义务必须生成真实空、单元素和多元素值，顺序故障规则必须引用操作身份而不是字段名。

#### Scenario: 只有乘客集合参与循环
- **WHEN** passengers携带collection_iteration证据而gender和contacts没有该证据
- **THEN** 全局集合规则只对passengers产生BoundaryObligation并生成真实集合值

#### Scenario: 顺序循环指向退款操作
- **WHEN** 分析器把ordered_iteration绑定到ticket.refundPassenger
- **THEN** FaultInjectionObligation的target_operation为该操作身份

### Requirement: 规则覆盖与替换必须显式

系统 SHALL 让不同ID规则累加、同ID系统规则覆盖全局版本，并只接受指向现存规则的supersedes声明。

#### Scenario: 系统同ID规则覆盖全局默认
- **WHEN** 系统层定义与全局层相同rule_id
- **THEN** 只使用系统版本且来源显示为system

#### Scenario: 替换不存在的规则
- **WHEN** 系统规则supersedes一个不存在的ID
- **THEN** 预览进入BLOCKED_RULE_CONFLICT并展示无效替换

