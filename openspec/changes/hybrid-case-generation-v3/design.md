# Design

## Trust boundary

公开生成请求只有`entry_id`。程序从exact latest scan读取独立`ProgramCaseAnalysisArtifact`和Frozen Coverage Manifest；不读取`Entry.metadata.case_analysis`，也不接受客户端Action、Recipe、Oracle、Cleanup、base input或业务身份。

`CaseGenerationHandoff`是独立于`KnowledgeClientHandoff`的私有工作流。它冻结consumer system、entry、scan、baseline、analysis artifact，以及全部直接provider的binding ID/revision、角色、用途、scan和baseline。提交与恢复由独立跨进程锁串行化；普通异常把`VALIDATING`退回`BLOCKED`，进程退出遗留的`VALIDATING`可在下次取得锁后恢复。Agent不能提交Generation、Scenario、Variant、Attempt、自由SQL、provider地址、Token、Fixture业务键或执行结果。

Agent草稿只能引用当前Candidate/Published/Recipe和服务器规则身份。程序依次调用正式Semantic、Capability、Setup、Case compilation、Fault和Cleanup校验器；任一草稿失败都保留具体blocker并在同一handoff恢复，源码scan变化则终止为`STALE_SOURCE`。

## Deterministic asset selection

- Action由同scan、同Entry的唯一Action Profile绑定唯一current Published能力；零个进入handoff，多个返回歧义阻塞。
- 所有满足Action SetupFact约束的current Recipe分别参与生成；相同执行图和事实约束的等价重复Recipe阻塞，程序不任选一个。
- Oracle只能来自Action Profile在同一Case compilation revision中绑定的模板；observer必须按所属系统current读取、保持READ_ONLY并具备直接ORACLE依赖。
- 每个写Action Scenario必须唯一匹配`Action + Recipe + Action Profile`的current CleanupPlan；Setup已经生产可回收资源时同样必须具备Cleanup。业务取消能力作为CLEANUP节点加入图，SQL策略保留固定资源定义。
- 每个Fault obligation独立调用Planner。真实数据优先；同一优先级出现多个可用能力时阻塞歧义；缺失保持`BLOCKED_MISSING_FAULT_CAPABILITY`。

## Frozen Generation

Generation只在程序完成一次服务器恢复后写入，并冻结：

- consumer scan、baseline、analysis artifact及Frozen obligation清单；
- semantic、规则、Case compilation、Setup、Cleanup和Fault规则修订；
- Action Profile、所有二元Published refs及Candidate/Provider operation证明；
- Recipe refs、Fact contract、SETUP dependency proof；
- Oracle evaluator和observer refs；
- 每个Scenario的CleanupPlan、FaultPlan及ACTION/ORACLE/CLEANUP依赖证明；
- 每项义务到Variant、显式Blocker或不可行证明的完整核算，并冻结Factor可达值和全部合法二元组合分母。

Generation不得保存Fixture值、业务主键或provider输出。同一generation ID首次写入后不可改变；同内容重放幂等，不同内容拒绝。

## Execution

执行前先解析完整owning-system集合并按排序事务冻结。程序在写Attempt和访问QA之前重验consumer latest Entry、Generation完整性、每个Published current Candidate/Provider/Schema/0600绑定、Recipe历史及current步骤、跨系统ACTION/SETUP/ORACLE/FAULT/CLEANUP直接依赖、Cleanup历史与current授权以及Fault工具生命周期。

预检失败不访问QA；可直接写consumer归属的终态BLOCKED Attempt。运行时Fixture只允许Recipe声明的非业务字段，额外字段和业务身份字段在provider调用前拒绝。SetupFact产生资源身份后立即进入必须Cleanup状态；Fault安装成功后任何出口都必须verify/rollback。

Attempt分别保存primary、fault rollback、cleanup、cleanup oracle和quarantine失败摘要。Cleanup或rollback失败决定最终FAILED并隔离资源，不能被Action原始失败隐藏。Git和Attempt只保存无值路径、状态和错误码；隔离业务键只存在0700目录、0600文件且跨进程串行读改写的本地隔离资产。

## Compatibility

旧V2读取API保留，旧生成、确认和批量执行写入口继续拒绝。旧V3请求中的额外字段由严格模型直接拒绝，不提供兼容适配。
