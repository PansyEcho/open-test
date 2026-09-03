# Design

## 服务端Cleanup Contract

`CleanupContractRuleSet`是consumer Git中的版本化服务端真相。每个Entry contract精确绑定`entry_id`、`action_profile_id`、统一业务身份来源与一组业务取消分类器。分类器只接受精确Candidate所属系统、FQN和完整方法签名；`cancel/remove/release/rollback/close/void`等方法名前缀仅用于提示未归类候选并阻塞，不能把`removeCache`等方法提升为取消能力。

身份来源只能是`SetupFactInputRef`或`ActionFactInputRef`。Contract同时固定身份输入映射和安全常量输入映射。`RefundFacade#createOrder`的系统规则必须声明`required_identity_source=ACTION_FACT`，并将退款单号路径绑定到`RefundFacade#cancel`的逻辑输入；程序不写死业务接口名。

## 直接改库的授权边界

SQL不从API自由提交。`CleanupSqlContract`必须固定latest scan内的MySQL/TiDB `resource_id`、表名、允许SET的列、参数来源和业务键列；独立的`CleanupOracleContract`固定查询资源、投影列和受控标量期望。规则加载时和Plan发布时均解析单条参数化UPDATE/SELECT：

- UPDATE只允许`SET column = ?`与`WHERE column = ? AND ...`；
- SELECT禁止`*`，投影列必须等于contract声明；
- 禁止OR、注释、分号、子查询、函数、DELETE/INSERT/DDL和额外语句；
- UPDATE、Oracle和隔离共用同一`CleanupBusinessIdentityRef`，业务键参数位置按SQL中真实问号顺序验证；
- 恢复值和Oracle期望仅允许`SafeConstantInputRef`能表示的布尔、数值或稳定枚举码。

## 当前证明与冻结历史

发布前预读Recipe步骤、Action和取消能力所属系统，再锁定consumer、Recipe全部provider、Action provider、取消provider以及所有直接`purpose=CLEANUP`候选范围。锁内先只读consumer规则/Recipe重新计算完整provider集合；集合扩张时在读取新provider之前阻塞并要求重试。范围一致后再重读：

- consumer exact latest scan与Entry；
- current Case compilation rules中唯一Action profile、Action capability与ActionFact contract；
- Recipe的历史完整性，以及其每个步骤的current Published和直接`SETUP`依赖；
- 业务取消current Published、精确Candidate分类和直接`CLEANUP`依赖；
- Cleanup Contract历史修订、身份Fact contract/path/Schema与所有输入类型。

任一CLEANUP候选范围缺lateset、漂移、分类匹配不唯一，或已归类Candidate没有对应current Published，都阻塞SQL主策略。只有完整current范围在当前规则下没有业务取消Candidate，且contract提供SQL恢复时，SQL才能成为主策略；不使用自由文本“源码不支持”证明。

`CleanupPlan`冻结`cleanup_rule_revision_id`、`compilation_rule_revision_id`、`action_profile_id`、current `action_capability_ref`、`action_fact_contract_id`、实际身份路径及派生Schema。计划构造和`CleanupPlanStore.write()`与全部验证共享同一多系统事务。同`cleanup_plan_id`不得覆盖；首次发布同时写不可变Plan快照，`list/get`要求current副本与该快照完全一致，防止把业务取消计划手工改成SQL计划。

`list/get`对Git Plan重放冻结规则修订并校验自包含完整性，允许展示后续因依赖撤销而不再current的历史Plan。第8阶段执行前才再验current资产，消费ActionFact运行值，并在Cleanup/Oracle失败时写隔离记录。
