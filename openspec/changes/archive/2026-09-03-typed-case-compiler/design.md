# Design

## 信任边界

公共`TypedCaseCompileRequest`只含`entry_id`。编译器先预读规则和Recipe中的系统引用，再在一次consumer与全部provider的多系统事务中执行；加锁后若引用集合发生变化则返回`BLOCKED_CROSS_SYSTEM_SNAPSHOT_INVALID`，不得混用不同代际的Candidate、Published和Recipe：

1. 读取exact latest scan及对应`ProgramCaseAnalysisArtifact`；
2. 调用阶段1规则服务重新生成服务端`FrozenCoverageManifest`；
3. 通过阶段3 `PublishedOperationCapabilityService`选择与入口、latest scan精确绑定的唯一Action；
4. 通过阶段4 `DataSetupRecipeService`读取已重验的Recipe；
5. 读取consumer Git的不可变`CaseCompilationRuleSet`版本，解析Action输入模板、ActionFact契约和Oracle模板；
6. 构造仅存在于进程内的`VerifiedCompileContext`，再进入各分型生成器。

客户端提交Manifest、Action图、Published ID、Recipe ID、Oracle、Cleanup ID或业务输入值均作为额外字段拒绝。零个Action返回`BLOCKED_UNPUBLISHED_ACTION_CAPABILITY`，多个当前Action返回`BLOCKED_AMBIGUOUS_ACTION_CAPABILITY`。本阶段没有阶段7 Cleanup；WRITE Action返回`BLOCKED_MISSING_CLEANUP_PLAN`，不得把任意字符串当成已验证Cleanup。

## 类型化事实链

服务器编译规则为Action每个逻辑输入根定义判别来源：

- `SetupFactInputRef`：引用`fact_contract_id + fact_path`，编译器从当前入口的已验证Recipe中选择能够提供该Schema和约束的模板；
- `GeneratedInputRef`：只接收Factor、literal Boundary或已证明Decision生成的非身份字段；
- `SafeConstantInputRef`：只允许服务器规则保存的类型化安全常量。

独立`CapabilityInputSourcePolicy`为每个Published逻辑输入根声明允许来源、身份属性和安全常量白名单；Action Profile不能自行扩大该策略。Action业务身份只能使用`SetupFactInputRef`，Observer业务身份可使用`SetupFactInputRef`或`ActionFactInputRef`。页面Fixture、Generated输入和安全常量都不能提供订单号、退款单号或乘客身份；安全常量只接受数值、布尔值和稳定大写枚举码。

Action执行结果先按Published `output_mapping`投影成逻辑`ActionResult`。`ActionFactContractDefinition`从该逻辑`output_fact_schema`声明稳定fact contract、必备字段、业务身份路径及允许消费者；编译器只产生受控`ActionFactRef`。Oracle/未来Cleanup输入只能引用`SetupFactRef`、`ActionFactRef`或服务器安全常量。阶段5仅冻结这些Schema与来源证明，不调用Action、不产生真实业务主键。

## 分型生成与覆盖证明

- Factor：约束支持factor-to-literal和factor-to-factor关系。程序分别为每个声明值和二元pair寻找一条满足约束的完整witness，再对有限witness集合贪心选择；生成和完整性校验都不得枚举全笛卡尔积。不可达声明值阻塞，约束禁止的pair不进入分母；每个Variant只记录自己实际覆盖的目标。
- Boundary：literal边界经Action输入Schema和同一Factor约束求解器验证；集合基数只保存`EMPTY/SINGLE/MULTIPLE`要求，不生成`[{}]`。若没有匹配Setup Fact、服务器元素模板或确定性构造器，返回`BLOCKED_BOUNDARY_ELEMENT_SOURCE_MISSING`。
- Decision：`DecisionObligation`必须与Analyzer evidence的类型、条件、结果标签、受控谓词AST、布尔期望和字段路径逐项一致。程序谓词求值器验证向量命中指定结果并生成`DecisionReachabilityProof`；自然语言条件、AI自造AST或借用其他Gap证据均返回`BLOCKED_DECISION_REACHABILITY_UNPROVEN`。
- Sequence：源码内部trace/门控必须与Analyzer evidence的操作序列或控制流路径、字段路径及激活谓词完全一致，且只附加到使该程序谓词为真的向量，成为`SequenceCoverageProof`。Semantic草稿提供的`activation_vector`不能自证可达性；没有受支持谓词或合法可达向量时返回`BLOCKED_SEQUENCE_REACHABILITY_UNPROVEN`。内部Sequence不能替换外部执行图，外部图固定由Setup Recipe、当前Entry Action、Effect Observer和未来Cleanup的正式引用组成。
- Effect：Analyzer为Effect提供字段绑定和激活谓词；嵌套`if`门控合并全部祖先谓词，循环、switch、三元、短路求值或无法解析的门控不降级为恒真。唯一DSF绑定由程序把`unknown`调用规范化为exact RPC operation ID。Oracle观察只附加到谓词为真的已有Variant，不新增因素组合；没有激活谓词或现有向量均不可达时返回`BLOCKED_EFFECT_REACHABILITY_UNPROVEN`。
- Requirement：使用判别联合`RequirementCompileTarget`，目标路径必须存在，Decision/Sequence/Effect必须引用exact证据。编译结果使用服务器身份并保存`parent_requirement_id`；原Requirement继续留在覆盖分母。
- Fault：每个义务固定产生`BLOCKED_MISSING_FAULT_CAPABILITY`，不生成含该义务ID的Variant，也不写`failurePosition`。

完整向量必须同时通过Factor约束与Action逻辑Schema；按JSON类型和值去重。`VariantCoverageProof`保存实际覆盖的factor value、pair、boundary、decision和sequence证据。每个冻结义务最终必须是`GENERATED`、`BLOCKED`或带程序证明的`PROVEN_INFEASIBLE`，不得把全部Factor ID挂到每个Variant。

## Oracle与Scenario身份

Oracle模板是consumer Git不可变服务器资产，不接受内联提交。Current规则文件必须与其revision历史内容完全一致，历史缺失或手工改写均阻塞。Observer使用`PublishedCapabilityRef(system_id, capability_id)`；跨系统必须有直接`ORACLE`依赖，能力必须重新验证当前Candidate、Provider Operation、DTO、Schema mapping和本地QA绑定且为`READ_ONLY`。Effect target绑定到exact Program evidence；observer输入只能来自SetupFact、ActionFact或安全常量；断言路径只针对Published逻辑输出Schema，执行阶段继续复用现有OperationExecutionService应用`output_mapping`。

`OracleExpression`来源拆为`literal/factor/setup_fact/action_result/action_fact`，其中factor只能引用真实Factor义务路径，SetupFact与ActionFact使用独立运行时命名空间；编译时验证路径与静态类型，算术只允许integer/number。

`ScenarioTemplateKey`由有角色的正式执行图、Setup Recipe版本、Action输入绑定模板、Oracle模板版本、可空的已验证Cleanup引用和生命周期策略组成。预期字面值、运行时业务主键、Fixture值和遍历序号不进入Scenario身份。Variant保存因素值、生成输入、参数化Oracle上下文及覆盖证明。

本阶段不执行Case、不调用QA、不创建`ExecutionAttempt`。Attempt只保留为阶段8运行模型。
