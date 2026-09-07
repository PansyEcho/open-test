## MODIFIED Requirements

### Requirement: Case目录必须由latest scan全部真实触发入口生成

系统 SHALL 按 Facade、MQ、Job 层级列出latest完整扫描中的全部真实入口，知识状态只作为附加信息，且目录请求不得逐入口执行Case preview。Case工作状态 SHALL 来自持久task、handoff和不可变Generation，不得由Agent thread、turn或模型配置推断。

#### Scenario: 入口尚无知识或Generation

- **WHEN** latest完整扫描包含一个真实入口但尚无知识或Case
- **THEN** 目录仍显示该入口并以中性“未生成”状态展示

#### Scenario: 网页任务等待Agent接手

- **WHEN** current源码代际已有持久Case task和handoff，但原生Agent尚未使用该task_id
- **THEN** 目录显示“等待Agent接手”和可复制系统Skill指令，不显示“生成中”
- **AND** 页面不提供Case Provider、模型、推理档位或预建thread入口

#### Scenario: 草稿等待回答或修订

- **WHEN** current handoff包含开放问题、可修复校验问题或待显式发布草稿
- **THEN** 目录与详情显示“待回答”“待修复”或“待发布”及对应安全摘要
- **AND** 不因Agent输出结束、Schema合法的unresolved或缺少thread_id显示业务成功或正式BLOCKED

#### Scenario: Case Agent使用受控typed工具

- **WHEN** 当前原生Agent准备或继续一个Case任务
- **THEN** task context只提供冻结范围、正式资产、服务器Draft Schema和Case读取、问答、草稿、发布及继续工具
- **AND** 生成意图不开放QA执行，用户必须另行显式创建Generation Execution

#### Scenario: 主视图隐藏内部错误码

- **WHEN** Generation或handoff进入待回答、待修复、Blocked或Failed
- **THEN** 主视图使用业务状态、简洁原因和继续入口，原始错误码与源码轨迹仅在默认折叠的技术详情中可查

### Requirement: Regression Case page exposes the V4 workflow and raw artifacts

The console SHALL expose one version-neutral Regression Case workflow with separate generation and execution actions, immutable Generation history, explicit environment selection and per-Execution reports.

#### Scenario: Generation reaches a terminal state

- **WHEN** the handoff becomes `COMPLETED`, `PARTIAL`, `BLOCKED` or `FAILED`
- **THEN** the page shows the task and handoff identity, revision, source baseline, validation result, immutable Generation when present and ordered Variants
- **AND** it does not claim that QA was executed

#### Scenario: Draft needs an answer or revision

- **WHEN** the handoff is waiting for input, contains repairable validation issues or is ready for explicit publication
- **THEN** the page shows a compact task summary, questions, issue locations and the native-Agent continuation instruction
- **AND** full Prompt, source trace and historical Agent output remain in an optional diagnostic detail instead of the main workspace

#### Scenario: User explicitly executes a Generation

- **WHEN** a READY or PARTIAL Generation is selected
- **THEN** the page enables an action that states it will execute every runnable Variant in this Generation
- **AND** the resulting report shows DATA, TARGET, ORACLE and CLEANUP evidence

#### Scenario: User switches between asynchronous views

- **WHEN** the user switches Generation or Execution history while an older request is in flight
- **THEN** the console invalidates both late successes and late errors from the older view
- **AND** the selected artifact is not overwritten

### Requirement: 控制台只使用当前版本化API

控制台 SHALL 只通过 `/api/v2` 展示和操作系统、扫描、知识、资源、Case Generation与Execution，不调用legacy项目、V3或V4路由，并且用户可见内容不展示产品内部Case版本号。

#### Scenario: 用户完成主流程

- **WHEN** 用户依次配置系统、扫描、生成知识、生成Case、显式执行并查看报告
- **THEN** 工作台、系统、知识库和回归Case四个入口能够完成全部操作
- **AND** 不需要进入独立自然语言、测试执行、运行报告、MVP或Suite页面

#### Scenario: 查看运行失败

- **WHEN** 真实工具、断言、Oracle或Cleanup失败
- **THEN** 页面展示阶段状态、简洁错误和结构化结果
- **AND** 不显示QA密钥

### Requirement: Console uses the native Agent as the generation entry

The console SHALL create a durable business task before knowledge or Case generation, SHALL show waiting, answering, repair and terminal states from backend records, and SHALL provide a copyable system-skill instruction instead of starting a background Agent thread.

#### Scenario: No reliable one-click Agent entry exists

- **WHEN** the console cannot prove a supported deep link that opens an unowned native Agent task
- **THEN** it displays and copies the exact system skill plus task_id
- **AND** the task remains visible without thread_id and is not labelled as generating before pickup

### Requirement: Console displays and explicitly updates the pinned source baseline

The console SHALL show the configured managed tag, full commit, branch hint and pin/scan relationship in the global system context, and SHALL separate ordinary configuration saves from an explicit “update source baseline and scan” action.

#### Scenario: User changes local Git state without updating the pin

- **WHEN** the registered repository switches branch, advances HEAD or has local edits while its configured pin is unchanged
- **THEN** the console continues to show and scan the configured commit, and explains that working-tree changes are outside the baseline
- **AND** it does not mark knowledge stale solely because a branch label, scan ID or tag spelling differs for the same commit

#### Scenario: User chooses a new baseline

- **WHEN** the user enters a revision and explicitly selects “update source baseline and scan”
- **THEN** the console calls the dedicated source-version endpoint, shows the pending scan and refreshes the persisted pin after completion
- **AND** a normal metadata save cannot silently change the source version

#### Scenario: Scan task completes with a partial projection

- **WHEN** the generic task lifecycle is `completed` but its persisted result reports `partial_projection`
- **THEN** every registration, baseline-update and retry flow states that the scan was partially successful and the complete generation baseline was not replaced
- **AND** the console does not infer scan completeness from the generic task status

#### Scenario: Generate knowledge while browsing a partial projection

- **WHEN** the user browses a newer partial scan while an earlier complete scan remains the published latest generation baseline
- **THEN** clicking knowledge generation prepares the target against the backend-resolved complete latest baseline
- **AND** the browsed partial scan remains available for discovery and diagnosis but is never submitted as the knowledge generation input
