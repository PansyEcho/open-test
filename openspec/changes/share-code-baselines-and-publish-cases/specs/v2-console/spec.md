## MODIFIED Requirements

### Requirement: Case目录必须由latest scan全部真实触发入口生成

系统 SHALL 按接口（Facade 按类分组）、MQ 消费、定时任务层级列出当前基准与 published/mine 视图中可见真实入口，仅展示包含真实入口的分类，知识状态只作为附加信息，且目录请求不得逐入口执行Case preview。

#### Scenario: 员工浏览入口列表
- **WHEN** 员工打开“入口列表”
- **THEN** 页面按“业务入口”（接口按类分组、MQ 消费、定时任务）与“下游依赖”（外部 DSF 按提供方分组、MQ 发送、数据库、缓存）分层展示当前基准与视图的全部接口，并可按用途、类名或方法搜索，空分类不显示
- **AND** 目录只使用接口摘要；点开某个入口后才读取它的字段与知识正文，业务背景与术语在单独入口维护

#### Scenario: 入口尚无知识或Generation
- **WHEN** 当前基准可见目录包含一个真实入口但尚无知识或Case
- **THEN** 目录仍显示该入口并以中性“未生成”状态展示

#### Scenario: 同入口正在生成
- **WHEN** current源码代际的Case任务已记录Agent turn成功启动，或服务端正在校验已提交草稿
- **THEN** 目录显示“生成中”和可核查业务步骤，不调用preview且不让历史阻塞Generation覆盖该进度

#### Scenario: Handoff等待但Agent未运行
- **WHEN** current源码代际只存在等待、需人工打开、阻塞或失败的Case handoff
- **THEN** 目录停止轮询并显示“待补充”或对应终态，不得长期显示“生成中”

#### Scenario: 用户查看Case生成进度
- **WHEN** Case生成尚未进入READY终态
- **THEN** 页面按实际状态展示“程序正在编译”“等待Codex补全”“Codex正在设计Recipe”“正在校验草稿”“正在重新生成”“已生成”或“待补充”，且区分真实数据准备、Case校验、目标试跑与回查；generate_only明确显示不执行业务

#### Scenario: 用户选择Case Codex兜底档位
- **WHEN** 用户打开Case工作台
- **THEN** 页面提供Luna·Low、Luna·Medium、Sol·Low、Sol·Medium，并说明“仅在程序无法完成Case生成时用于Codex补全”

#### Scenario: 活动Codex显示冻结档位
- **WHEN** current Entry存在等待、运行或校验中的Case handoff
- **THEN** 页面显示该handoff首次冻结的模型和推理档位，后续选择不得改写它

#### Scenario: 空线程等待桌面接管
- **WHEN** 持久Codex线程已经创建但桌面owner尚未打开它，后台首次启动返回manual required且线程没有turn
- **THEN** 页面保持“等待Codex补全”并提供“打开并继续 Codex 任务”；用户点击后打开同一线程并幂等请求首次turn，不得显示为业务待补充或创建第二线程

#### Scenario: 主视图隐藏内部错误码
- **WHEN** Generation或handoff进入Blocked、Failed或Needs Input
- **THEN** 主视图使用“待补充”等业务文案，原始错误码仅在默认折叠的技术详情中可查

#### Scenario: Codex turn结束但没有合法产物
- **WHEN** 已启动的Case Agent turn已completed或failed，但Handoff没有进入校验或READY
- **THEN** 页面分别转为“待补充”或“未完成”并停止轮询，不得继续显示“生成中”；completed允许用户在同一线程显式继续，且不得重复启动同一turn

#### Scenario: Codex CLI延迟启动失败可恢复
- **WHEN** Case-only CLI越过同步启动窗口后退出，且原持久线程仍未出现新turn
- **THEN** 系统收割该进程并把同一任务恢复为“等待Codex补全”，保留原handoff、thread和冻结档位；再次点击只重试同一线程，不得永久显示运行中或创建第二任务

#### Scenario: Case Agent使用独立typed工具
- **WHEN** Case Agent开始或继续一个`case-handoff-*`任务
- **THEN** 每个模型turn使用任务绑定的typed工具读取固定源码、检索与解析接口、修订草稿和发布；generate_and_verify可调用任务范围内非生产数据准备和业务验证工具，generate_only在服务端拒绝这些执行工具；工具不能选择其他任务身份或任意源码根
- **AND** Agent先读取冻结范围、current正式资产和服务器Draft Schema，再通过Case专用typed draft工具提交

### Requirement: Console shows scan Git identity with the bound knowledge catalog
The console SHALL show the selected shared baseline's user-entered revision name and an 8-character short commit, together with a personal system and QA/UAT environment selection. System-generated `opentest/baseline/<commit>` tags and bare commits SHALL NOT be shown as revision names, and the full commit SHALL remain available by copying the short commit. The baseline picker SHALL be a dropdown panel that contains the create-baseline entry accepting branch, tag or commit. The header SHALL NOT show explanatory developer notes; it shows only the employee's unfinished creation status. Internal scan revisions SHALL NOT become separate public workspaces.

#### Scenario: User copies the baseline commit
- **WHEN** an employee hovers the short commit of the current baseline and clicks it
- **THEN** the copy affordance appears on hover, the full commit is copied to the clipboard and a confirmation is shown; a clipboard failure is reported instead of being ignored

#### Scenario: User opens the baseline picker
- **WHEN** an employee opens the baseline dropdown
- **THEN** each baseline shows its readable name or short commit, local creation time to the minute and missing-material or legacy badge; a legacy baseline without a commit also shows its short baseline identity so same-day legacy baselines remain distinguishable, the current baseline is marked, and the panel offers "新建代码基准" and, when applicable, continuing the employee's unfinished creation

#### Scenario: User changes baseline
- **WHEN** an employee selects a shared baseline
- **THEN** interface and Case catalogs switch together to that baseline and the selected published/mine view, without changing another employee's selection or a running task

#### Scenario: Selected catalog fails to load
- **WHEN** the requested baseline catalog is unavailable
- **THEN** preserve the previously confirmed selection and do not mislabel its contents with the failed baseline
- **AND** show an actionable error and persist the preference only after successful loading; a late failure cannot roll back a later successful selection

#### Scenario: Completed legacy knowledge task is opened
- **WHEN** an employee opens an old completed knowledge task without a reliable baseline association
- **THEN** direct the employee to choose the matching baseline and view current interface knowledge, without offering the retired system-level knowledge endpoint

### Requirement: Regression Case page exposes the V4 workflow and raw artifacts
The console SHALL allow generation for an eligible interface of the current baseline, generation-only or generation-plus-verification in the selected QA/UAT environment, task polling and bound Agent access. The console SHALL show only current shared Cases and the employee's unpublished drafts through per-Case projections; replaced versions remain in storage without a history selector.

#### Scenario: Employee browses Cases by entry
- **WHEN** the employee opens the regression Case page
- **THEN** show a hierarchical entry directory with interface classes and methods, MQ consumers and scheduled jobs only where actual entries exist; select a concrete entry and show only that entry's Cases without an "全部入口" aggregate item
- **AND** retain published/mine ownership semantics and separate Case library, generation tasks, execution records and coverage assistance into tabs; an empty directory clears the selection and its details

#### Scenario: One scenario has multiple state sub-cases
- **WHEN** visible Cases of the selected entry come from the same Generation and scenario template with multiple state variants
- **THEN** the Case library first shows one scenario row with its sub-case count and varying parameters, collapsed by default
- **AND** expanding it shows each state Case with its own publish, comparison and execution actions; identical titles are not flattened into repeated Case rows

#### Scenario: An entry has been removed but retains authorized Cases
- **WHEN** current authorized Cases belong to an entry that is absent from the visible interface knowledge directory
- **THEN** preserve that concrete entry in the browsing directory, mark its knowledge unavailable, and allow its Cases and historical executions to be inspected
- **AND** do not add it to the generation directory or enable execution of a removed or outdated Case

#### Scenario: Employee reads generation tasks
- **WHEN** the employee opens the generation-task tab
- **THEN** filter tasks by the current employee, system, concrete entry, baseline and environment, independently of the task-center page
- **AND** order the complete authorized scope by its most recent persisted activity (progress, handoff, end, start or creation time) before limiting the response to one task; earlier generation tasks remain available in the task center
- **AND** display progress and recovery only through that task's detail, without a second legacy progress panel or history pager

#### Scenario: An older generation resumes after many newer tasks were created
- **WHEN** a task outside the first creation-time page has the latest persisted progress for the selected scope
- **THEN** it is the single generation task shown, even if its original start time is unchanged and newer tasks exist outside the current employee, entry, baseline or environment

#### Scenario: A running Case task is correcting a recoverable tool error
- **WHEN** the persisted Case task is running and retains a safe tool or validation error
- **THEN** show its running state and keep the error in a collapsed processing record rather than a top-level failure alert
- **AND** show an explicit failure summary when the task is no longer running and remains blocked or failed

#### Scenario: Employee reads execution results
- **WHEN** the employee opens the execution-record tab for the selected Case
- **THEN** load the exact Case's authorized executions for the selected environment, show outcome and assertion summaries, and put actual requests, responses and available result checks in collapsed sections without dumping internal execution evidence

#### Scenario: Employee regenerates a Case draft
- **WHEN** the employee chooses to regenerate from a selected Case
- **THEN** explain that a personal draft is created and state whether data preparation and business verification will run in the selected environment before dispatch; the action does not directly replace shared content

#### Scenario: V4 handoff reaches a terminal state
- **WHEN** a handoff completes, partially completes or fails
- **THEN** display its actual progress and permitted Case content, frozen model and source identity without exposing other private Variants or replaced content

#### Scenario: Selection changes during polling
- **WHEN** the employee changes baseline, view, entry or selected Case while a previous request is in flight
- **THEN** invalidate late responses and errors from the older selection, clear details and actions that no longer belong to the selection, and prevent old execution or coverage results from replacing the current contents

#### Scenario: Employee starts Case generation
- **WHEN** an employee chooses "生成 Case" on the Case page or on an entry in the entry list
- **THEN** a centered in-page dialog lets the employee pick a concrete business entry from a searchable hierarchy and shows the baseline, environment and that the result is saved as the employee's draft; the directory uses the current system, baseline and source view, including the employee's private entry when starting from mine
- **AND** let the employee choose generation-only or generation-plus-verification; require explicit deployment confirmation only when verification and coverage assistance are both enabled, without asking twice for that request or retaining confirmation from a generation-only request

#### Scenario: Case generation cannot resolve missing knowledge or data
- **WHEN** generation or coverage Case supplementation cannot resolve missing materials, data or validation problems within its authorized scope
- **THEN** retain the draft and actionable blocking reasons and finish failed, or partially complete only when valid partial results exist, without waiting for a user answer or telling the employee to answer in another chat
- **AND** other requested entries can continue independently; standalone knowledge interviews retain their existing question workflow

#### Scenario: One Case template is blocked while others compile
- **WHEN** an unresolved item or diagnostic question names a case template or data function of the current draft by its bare name
- **THEN** treat it as scoped to that template or data function, so Variants of other templates that do not use the affected data function remain eligible for `available` publication
- **AND** targets that are neither generation-wide nor a name declared in the draft continue to block every Variant

#### Scenario: All draft Cases are published
- **WHEN** the employee chooses publish all
- **THEN** select all of this employee's eligible drafts in the current baseline across pagination, show per-item success or conflict, and retain failed drafts for resolution


## ADDED Requirements

### Requirement: Console selects and confirmations use in-page controls
The console SHALL present single-choice selects as styled in-page dropdowns that keep the native select as the source of value and change events, and SHALL offer a search box when a list has more than eight options. Confirmations and text prompts SHALL use centered in-page dialogs instead of browser-native confirm or prompt windows.

#### Scenario: Employee filters a long list
- **WHEN** an employee opens a select with more than eight options, such as the system, interface or business-entry select
- **THEN** the dropdown shows a search box that filters options by visible text and value, groups remain labelled, and keyboard navigation and Escape work without changing the value until an option is chosen

#### Scenario: Employee confirms a sensitive action
- **WHEN** an action needs confirmation or a short text input, such as archiving a system, deleting a business term or running a read-only DSF canary
- **THEN** a centered dialog asks for it; cancelling sends no request, and a failed confirmation keeps the dialog open with the error

#### Scenario: Login expires while a modal is open
- **WHEN** the employee's identity expires or is cleared while a business or confirmation modal is open
- **THEN** close the modal, settle pending confirmation as cancelled and allow the employee to reach the login screen without triggering a new business action

#### Scenario: Employee moves the pointer over a drawer backdrop
- **WHEN** a detail drawer is open and the pointer moves over its backdrop
- **THEN** keep the backdrop translucent and neutral; primary-button hover styling does not apply to it
