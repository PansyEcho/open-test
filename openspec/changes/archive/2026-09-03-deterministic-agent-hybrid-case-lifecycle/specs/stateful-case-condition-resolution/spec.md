## ADDED Requirements

### Requirement: 有状态实体条件必须复用现有Fact和Recipe资产

系统 SHALL 通过现有Setup Fact contract、Published Capability和DataSetupRecipe表达实体身份、状态谓词、约束、关系及确定性获取策略。

#### Scenario: 表达可取消退票单
- **WHEN** cancel正式知识要求 `RefundOrder(CANCELLABLE)`
- **THEN** 该条件进入Setup解析且不进入Pairwise组合

### Requirement: Recipe解析必须生成固定递归DAG

系统 SHALL 按Fact、状态、策略、约束和关系递归选择唯一最低优先级Producer，在活动解析栈发现环并阻塞同优先级歧义。

#### Scenario: QTC优先完整QTC
- **WHEN** 同一状态需求同时存在完整QUERY_THEN_CREATE与QUERY_ONLY Recipe
- **THEN** 系统先选择完整QUERY_THEN_CREATE，再在该策略内按优先级选择唯一Recipe

#### Scenario: QTC降级完整Query-only
- **WHEN** QUERY_THEN_CREATE需求没有完整同策略Recipe但存在完整QUERY_ONLY Recipe
- **THEN** Coverage保留QUERY_THEN_CREATE需求，冻结Setup Plan选择QUERY_ONLY且不要求CREATE链闭合

#### Scenario: QTC不得降级Create-only
- **WHEN** QUERY_THEN_CREATE需求只有CREATE_ONLY Recipe
- **THEN** 系统保持缺少兼容Producer的Blocked，不得把CREATE_ONLY作为隐式降级

#### Scenario: 单策略必须精确匹配
- **WHEN** 需求策略为QUERY_ONLY或CREATE_ONLY
- **THEN** 系统只选择同名策略Recipe

#### Scenario: 编译退款取消链
- **WHEN** 正式资产证明 `TicketOrder -> createOrder -> RefundOrder(CANCELLABLE)`
- **THEN** Generation冻结每个Producer、依赖、状态、关系、Action绑定和Finalization引用且不访问QA

#### Scenario: Producer依赖环
- **WHEN** 两个Recipe的前置Fact相互依赖
- **THEN** 生成阶段确定性返回依赖环阻塞且不创建Attempt

### Requirement: QUERY_THEN_CREATE必须仅在明确miss后创建

系统 SHALL 先执行目标Query，命中时跳过create依赖，明确miss时才执行依赖与CREATE，Provider失败、超时或未知结果码不得触发创建。

#### Scenario: 已有可取消退票单
- **WHEN** 初始Query返回已验证的RefundOrder
- **THEN** 系统直接绑定cancel且不查询或创建TicketOrder

#### Scenario: 未找到可取消退票单
- **WHEN** 初始Query按正式判定明确miss
- **THEN** 系统准备TicketOrder、调用createOrder、重新查询并验证同一关系的RefundOrder后才执行cancel

#### Scenario: 创建响应不是最终可用实体
- **WHEN** CREATE只返回创建身份而最终Action需要后续Query验证的实体
- **THEN** Generation分别冻结CREATE Fact与最终Fact，Action只绑定最终Fact，Producer Finalization只使用CREATE Fact

#### Scenario: 创建响应只返回成功结果
- **WHEN** CREATE不返回实体身份，但末次Query使用前置Fact的业务身份定位结果且最终Fact证明同一实体关系
- **THEN** Generation不伪造CREATE Fact，Action绑定状态验证后的最终Fact，Producer Finalization只在末次Query成功验证后使用该最终实体身份

#### Scenario: 无身份创建后的末次查询失败
- **WHEN** CREATE可能已经写入资源但末次Query未找到实体、返回失败或关系验证不通过
- **THEN** Setup失败且Action不执行；系统不得声称Cleanup通过，并按冻结隔离或可用Finalization证据处理未知资源

### Requirement: 查询协议不得强制统一available字段

系统 SHALL 使用受限的集合非空、值非空、布尔相等或结果码映射判断存在性，并使用VALUE或确定性FIRST_ITEM提取实体。

#### Scenario: 查询返回列表
- **WHEN** Published查询返回 `List<RefundOrder>`
- **THEN** Recipe使用集合非空和有唯一性或稳定排序证明的实体提取，而不要求provider新增available字段

#### Scenario: 当前退款Query Recipe
- **WHEN** `RefundFacade#cancel` 需要 `refund-order/v3(CANCELLABLE)` 且current queryList Recipe可用
- **THEN** 系统以READ_ONLY queryList、`page=1`、`page_size=1`、`order_state=0`、`COLLECTION_NOT_EMPTY`和`FIRST_ITEM(max_cardinality=1)`取得并验证`PENDING_APPLY`退票单

#### Scenario: 查询输入安全边界
- **WHEN** Query不是READ_ONLY、身份来自Fixture、`page_size`不是服务器白名单1或FIRST_ITEM没有确定性证明
- **THEN** DataSetupRecipeService拒绝发布且不访问QA

#### Scenario: 结果码尝试触发创建
- **WHEN** QUERY调用成功并返回一个被Recipe列为not-found但未由exact正式操作知识证明的业务结果码
- **THEN** Setup以查询协议失败结束且不得执行依赖或CREATE

#### Scenario: 查询命中分支缺少关系Fact
- **WHEN** QUERY_THEN_CREATE目标关系引用只会在miss后执行的依赖slot
- **THEN** Generation明确阻塞该Recipe而不生成命中后必然验证失败的Ready Variant

### Requirement: Setup结果必须与业务测试结果分离

系统 SHALL 将QUERY_ONLY miss记录为Setup Blocked并保持Action与Oracle未执行；Provider失败或实体状态/关系验证失败记录为Setup Failed。

#### Scenario: QUERY_ONLY无数据
- **WHEN** 查询明确未找到受控实体
- **THEN** Attempt为BLOCKED、stage为SETUP且Action/Oracle证据为零

#### Scenario: Query Provider失败
- **WHEN** queryList返回Provider失败、超时或协议失败
- **THEN** Attempt为SETUP FAILED且不进入CREATE、Action或Oracle

### Requirement: 同主机查询实体必须在Attempt期间串行保护

系统 SHALL 使用现有本地锁模式按环境、查询provider和Fact contract排序取得跨进程锁，并持有至Action与Finalization结束；该保证不扩展到跨主机。

#### Scenario: 两个Variant竞争同类实体
- **WHEN** 同一主机另一个Attempt持有相同Query实体门禁
- **THEN** 后续Attempt在固定等待预算后以Setup busy阻塞且不访问QA

### Requirement: Action与Setup Finalization必须按真实生命周期逆序执行

系统 SHALL 先终结Action对根实体的影响，再按DAG逆序执行实际CREATE节点的Producer Cleanup；不同Plan即使共享业务身份也不得被推断为等价。Action若有exact正式状态转换与current Action Oracle共同证明根实体已退出可复用谓词，可使用受限 `CONSUMED_BY_ACTION` 终结，不得再调用一次目标Action。

#### Scenario: cancel使用Setup创建的退票单
- **WHEN** Action和Refund producer均冻结各自Cleanup Plan
- **THEN** 系统依次执行Action Plan及其Oracle、Refund producer Plan及其Oracle，再回收更早依赖

#### Scenario: Action本身消费根实体
- **WHEN** exact正式转换证明Action把根Setup Fact从required state移出可复用谓词，且冻结Action Oracle在本Attempt中通过
- **THEN** `CONSUMED_BY_ACTION` 复用已有Action和Oracle证据完成Finalization，不得发起第二次业务调用

#### Scenario: Action消费未得到运行证明
- **WHEN** Action未执行、Action失败或冻结Oracle未通过
- **THEN** 系统记录 `BLOCKED_CONSUMED_BY_ACTION_UNPROVEN`，不调用第二次Action，并保留现有隔离或Producer Cleanup责任

#### Scenario: Action与Producer使用不同资源身份
- **WHEN** 查询或创建链的最终可用Fact与CREATE返回Fact不同
- **THEN** ACTION_EFFECT计划读取最终验证slot，STATEFUL_PRODUCER计划读取精确CREATE身份，二者不得互相替代

#### Scenario: CREATE没有直接实体身份
- **WHEN** QTC创建接口只返回成功结果且最终Query已按依赖关系验证实体
- **THEN** STATEFUL_PRODUCER计划读取该验证后的最终Fact；在最终Query完成前不得用成功码、依赖ID或猜测值替代目标实体身份
