# Design

## 外部Tool Candidate不是源码Candidate

外部Mock脚本使用独立的`FaultToolCandidateCatalog`，不能写入Java `CandidateOperationCatalog`，也不能因被发现而获得执行权限。用户只提交稳定`tool_id`和真实绝对路径；程序要求路径是Git工作树内已追踪的普通文件且不是符号链接，冻结当前commit与单文件dirty状态，并只分析该commit中的Git blob。内置分析器排除shell注释和帮助heredoc，仅保留真正参与执行的shell与嵌入子程序协议。Candidate保存：绝对路径、仓库根、Git commit、分析器版本、安全参数/结果键、install/update/verify/rollback角色、本地配置键名以及是否发现硬编码环境值。Candidate和Git资产不得保存脚本正文、URL、Token、Authorization或请求/响应样例。

`FaultAdapterProtocolArtifact`只能由程序生成，API和manifest metadata不能提交协议字段。生命周期角色委托的正式Operation ID也必须写在真实脚本源码的受控声明中并由内置分析器读取，不能随发布草稿提交；未声明或声明非法时角色Operation ID为空，不生成任何可与Published匹配的回退身份。发布时程序重新定位同一路径、重跑分析并比较Git基线和完整协议；源码漂移、符号链接、未追踪/非Git来源或协议变化均阻塞。Tool Candidate始终`executable=false`。Booking `create-interface-mock.sh`真实文件只能证明install/update和`mockKey`，没有受控install Operation声明、verify/rollback，且含硬编码QA URL fallback，因此保留为Candidate并拒绝发布Fault能力。

## 二元引用与多系统一致性

Fault target、install、verify和rollback全部使用`PublishedCapabilityRef(system_id, capability_id)`；adapter使用带Candidate版本的`FaultToolCandidateRef`，Real Data使用`DataSetupRecipeRef(system_id, recipe_id)`。Fault服务只通过`PublishedCapabilityService.get_current()`和`DataSetupRecipeService.get()`读取正式资产，不直接信任Store。

发布前先收集consumer、target、Recipe步骤和生命周期能力所属系统，在排序的`multi_system_transaction`内重读latest scan、Tool Candidate、Published、Recipe、编译Action绑定和直接dependency。跨系统引用必须有consumer到provider的直接授权：Recipe步骤沿用current `SETUP`，target及Mock生命周期要求`FAULT`。install逻辑输入必须包含目标操作、精确调用序号和故障结果，输出`mock_key`；verify/rollback必须消费该事实并分别输出严格布尔`fault_installed`/`fault_removed`。三者provider operation ID必须与协议artifact对应角色完全一致。

Fault注册表只append不可变版本。相同`publication_request_id`与完全相同草稿幂等返回；同请求ID或capability ID改变任一语义时阻塞。列表与规划会重新验证current引用，失效能力不会参与优先级。

## Real Data触发证明

Real Data不能用`constraint_proven`布尔值、Fixture、literal或任意`failure_target/failure_position`字段自证。服务器Git维护版本化`FaultTriggerFactContract`，固定：目标Published引用、Setup Fact contract、总调用数字段、故障ordinal字段、错误码/类别字段、实体集合字段以及允许的Action输入Fact路径。

发布时程序确认Recipe Fact直接来自某个current Published步骤输出，Schema包含上述字段，Recipe约束能确定`total_invocations`、`failure_invocation`、预期错误码和失败类别；该Fact contract还必须被当前Entry的Action Profile作为Setup Fact输入使用。无法证明Fact会进入被测Action、无法确定调用总数或ordinal时阻塞。

## Planner与精确选择器

公开Planner只接受`entry_id + obligation_id`。程序从exact latest冻结覆盖清单解析`FaultInjectionObligation`，拒绝客户端提交目标、位置、错误或逐实体期望。target必须等于程序证据绑定的Published provider operation ID，不使用substring匹配。

每个计划包含`total_invocations`和确定的`invocation_number`：FIRST固定为1；MIDDLE必须满足`2 <= n < total`；LAST必须等于total。只有协议artifact明确支持reverse selector时才允许倒数形式。Planner按REAL_DATA、MOCK、STUB排序；无可验证能力返回`BLOCKED_MISSING_FAULT_CAPABILITY`，不生成Case字段。故障结果必须有受控outcome和非空error code；逐实体预期固定包含previous/current/remaining三项及闭合状态值，其语义以服务端冻结义务为准，Planner不因FIRST/LAST位置改写为`NOT_APPLICABLE`。

## 可复用生命周期执行

阶段6提供独立`FaultLifecycleExecutor`，阶段8只负责把它接入Case执行。Mock/Stub install provider一旦成功立即设置rollback-required；随后output mapping、verify资产读取、verify调用、Action、Fault Oracle或其他异常都在`finally`执行rollback。verify必须确认`fault_installed=true`，Action必须同时命中错误码和失败类别，逐实体状态必须完整匹配，rollback必须确认`fault_removed=true`。

执行结果同时保存主失败和rollback失败；rollback资产漂移、调用失败或确认值不为true都使执行失败。Real Data使用`NO_FAULT_INSTALLED`，不调用环境级撤销。纯执行器异常分支可以用通用内存invoker做单元测试，但它不能作为真实Published、Planner或canary通过证据。
