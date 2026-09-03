# resource-cleanup-plans Specification

## Purpose
TBD - created by archiving change resource-cleanup-plans. Update Purpose after archive.
## Requirements
### Requirement: Cleanup必须使用版本化服务端Contract

系统 SHALL 从当前Cleanup Contract决定业务身份、取消Candidate和SQL表列边界，不信任API自由文本或方法名推断。

#### Scenario: 精确归类业务取消Candidate

- **WHEN** current Candidate的所属系统、FQN和完整签名唯一匹配Contract分类器
- **THEN** 该Candidate可作为`BUSINESS_CANCEL`的源码依据，但仍需发布为current Published才能进入Plan

#### Scenario: 通用名称看似取消

- **WHEN** Candidate只因`cancel/remove/release`等名称看似回收，却没有精确Contract分类
- **THEN** 程序不得把它当成取消能力；如名称命中保守词表则阻塞SQL主策略并要求完善Contract

### Requirement: Cleanup必须优先使用业务取消能力

系统 SHALL 在当前Contract归类到取消Candidate时要求对应current Published并将它作为主策略。

#### Scenario: 已归类且已发布取消能力

- **WHEN** Cleanup草稿引用与精确Candidate匹配的current Published能力
- **THEN** Plan首个动作为`BUSINESS_CANCEL`，SQL最多是contract提供的fallback

#### Scenario: 已归类Candidate尚未发布

- **WHEN** current Candidate目录命中Contract，但没有同Candidate的current Published取消能力
- **THEN** 返回`CLEANUP_CANCEL_CAPABILITY_NOT_PUBLISHED`，不允许用SQL绕过

#### Scenario: 完整current范围没有匹配Candidate

- **WHEN** consumer和全部`purpose=CLEANUP`直接provider目录都READY，且无Candidate命中Contract分类或未归类保守词表
- **THEN** 如Contract提供完整SQL恢复，程序允许`SQL_UPDATE`为主策略，无人工审批字段

### Requirement: Cleanup业务键必须来自类型化Fact

系统 SHALL 用一个统一`CleanupBusinessIdentityRef`绑定cancel、UPDATE、Oracle和隔离策略。

#### Scenario: createOrder产生退款单号

- **WHEN** 系统Contract要求`ACTION_FACT`且current Action profile的ActionFact contract将该路径标记为业务身份
- **THEN** CleanupPlan冻结Case compilation revision、Action profile、Action capability、ActionFact contract、身份路径及Schema，cancel在第8阶段只能消费ActionFact运行值

#### Scenario: Fixture或Setup Fact冒充Action资源身份

- **WHEN** Contract要求`ACTION_FACT`，草稿或旧资产尝试改用Fixture、literal或Setup Fact路径
- **THEN** 严格模型或发布服务拒绝

### Requirement: SQL恢复必须受固定资源、表列和业务键约束

系统 SHALL 只使用Cleanup Contract中绑定lateset MySQL/TiDB资源的单条参数化UPDATE和SELECT Oracle。

#### Scenario: 业务键不是WHERE首个条件

- **WHEN** UPDATE在业务键前还有contract允许的参数化AND条件
- **THEN** 程序按业务键列真实位置计数SET和之前WHERE占位符，并确认它引用统一身份

#### Scenario: 越界修改表或列

- **WHEN** 草稿或手工Git Plan使用Contract未固定的表、SET列、业务键列或Oracle投影列
- **THEN** 返回contract/integrity blocker且不发布或展示为有效Plan

#### Scenario: 使用OR、DELETE或多语句

- **WHEN** SQL包含OR、DELETE/INSERT/DDL、注释、分号或额外语句
- **THEN** 返回`CLEANUP_SQL_UNSAFE`

#### Scenario: Oracle使用SELECT star或自由期望

- **WHEN** Oracle使用`SELECT *`、未声明投影列，或期望值不是Contract中的受控标量
- **THEN** 返回`CLEANUP_ORACLE_UNSAFE`

### Requirement: Cleanup发布必须在同一多系统快照内完成

系统 SHALL 锁定consumer、Recipe/Action/取消provider和所有直接CLEANUP候选范围，在同一事务内重验并写Plan。

#### Scenario: 跨系统取消缺少CLEANUP授权

- **WHEN** cancel能力属于provider，但consumer没有直接`purpose=CLEANUP`依赖
- **THEN** 返回`CLEANUP_DEPENDENCY_MISSING`且不写Plan

#### Scenario: Recipe历史完整但步骤已漂移

- **WHEN** Recipe仍可历史读取，但任一步骤Published、provider latest或直接SETUP依赖已失效
- **THEN** Cleanup发布返回current Recipe blocker

### Requirement: Cleanup Plan必须不可变且历史可验证

系统 SHALL 把`cleanup_plan_id`作为Scenario冻结的资源生命周期版本身份，并使用冻结规则修订重放Plan完整性。

#### Scenario: 修改已发布Cleanup步骤

- **WHEN** 调用方使用相同`cleanup_plan_id`重新提交任何内容
- **THEN** 返回`CLEANUP_PLAN_ID_ALREADY_PUBLISHED`且不覆盖原Plan

#### Scenario: 把业务取消Plan手工改为SQL

- **WHEN** current Plan YAML偏离首次发布快照，即使SQL字段与冻结Contract一致
- **THEN** `list/get`返回完整性错误，不把篡改后的Plan展示为有效历史

#### Scenario: 依赖撤销后查看历史Plan

- **WHEN** Plan发布后current Published或dependency失效，但冻结Cleanup/Case compilation规则修订和Plan本身未被篡改
- **THEN** `list/get`仍可展示历史Plan；第8阶段执行前再因current授权失效而阻塞

### Requirement: 阶段7不得伪造回收执行证据

系统 SHALL 在本变更仅发布/读取Plan和隔离策略，不访问QA、不执行取消/SQL/Oracle、不写Attempt或隔离记录。

#### Scenario: 正式Refund知识缺少Published或Recipe

- **WHEN** 从真实注册、latest scan和knowledge副本读取`RefundFacade#createOrder`，但尚无正式Published/Recipe/ActionFact资产
- **THEN** Cleanup发布保持具体`BLOCKED`且Plan目录为空，不使用Fake provider变成PASSED

