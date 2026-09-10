# v2-console Specification

## Purpose
TBD - created by archiving change v2-api-and-console-cutover. Update Purpose after archive.
## Requirements
### Requirement: Case目录必须由latest scan全部真实触发入口生成

系统 SHALL 按 Facade、MQ、Job 层级列出latest scan中的全部真实入口，知识状态只作为附加信息，且目录请求不得逐入口执行Case preview。

#### Scenario: 入口尚无知识或Generation
- **WHEN** latest scan包含一个真实入口但尚无知识或Case
- **THEN** 目录仍显示该入口并以中性“未生成”状态展示

#### Scenario: 同入口正在生成
- **WHEN** current源码代际的Case任务已记录Agent turn成功启动，或服务端正在校验已提交草稿
- **THEN** 目录显示“生成中”和可核查业务步骤，不调用preview且不让历史阻塞Generation覆盖该进度

#### Scenario: Handoff等待但Agent未运行
- **WHEN** current源码代际只存在等待、需人工打开、阻塞或失败的Case handoff
- **THEN** 目录停止轮询并显示“待补充”或对应终态，不得长期显示“生成中”

#### Scenario: 用户查看Case生成进度
- **WHEN** Case生成尚未进入READY终态
- **THEN** 页面按实际状态展示“程序正在编译”“等待Codex补全”“Codex正在设计Recipe”“正在校验草稿”“正在重新生成”“已生成”或“待补充”，且明确生成阶段不访问QA

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
- **THEN** 每个模型turn在同一持久线程上通过忽略用户配置的隔离调用启动，其完整可调用工具集合严格等于Case读取与typed draft提交两个工具；知识handoff、源码、QA、Operation、Case执行和REPL工具在机器目录及调用路由中均不可用
- **AND** Agent先读取冻结范围、current正式资产和服务器Draft Schema，再通过Case专用typed draft工具提交

### Requirement: Case页面必须使用Entry与Scenario业务视图

系统 SHALL 在回归 Case 页提供“用例”和“执行结果”，按现有模板关联子用例形成测试场景，不新增场景实体。场景详情 SHALL 在唯一抽屉内展示准备规则、子用例对比和共同预期，并在同一抽屉切换子用例详情。

#### Scenario: 普通用户查看Scenario

- **WHEN** 用户从场景列表打开详情并选择子用例
- **THEN** 同一抽屉展示变化项、计划字段树、最终有效预期和折叠的清理与技术详情
- **AND** 返回场景恢复内容与查看位置，关闭抽屉保留列表搜索和版本选择

#### Scenario: Entry和Scenario按需读取

- **WHEN** 用户选择入口和不可变用例版本
- **THEN** 场景、子用例及字段来源使用该版本已有产物作只读展示，不调用准备工具、业务接口或取值函数
- **AND** 字段描述和枚举只使用可靠证据，没有说明时保留原字段名

#### Scenario: 同Generation中的另一个Scenario失败

- **WHEN** 同版本不同场景有不同执行结果
- **THEN** 每个场景只统计所选环境最新单个批次中属于自身的子用例
- **AND** 没有执行记录时显示未执行，不从其他批次补取结果

### Requirement: Case页面必须区分四类状态

系统 SHALL 分别展示生成生命周期、可执行性、最近执行和Finalization状态，并将其确定性映射为八种业务状态。

#### Scenario: 尚未生成
- **WHEN** 入口没有Generation
- **THEN** 页面显示中性“未生成”且不生成红色阻塞日志

#### Scenario: 可重试资产上的Setup阻塞
- **WHEN** 最新Attempt因查询无数据或实体占用而BLOCKED，但正式资产仍允许再次执行
- **THEN** 主状态优先显示“待补充”而不是“可执行”或“有失败”

#### Scenario: 无需Finalization的只读执行通过
- **WHEN** 当前Variant的可信最新Attempt为PASSED且Finalization为NOT_APPLICABLE
- **THEN** 主状态显示“已通过”并保留四状态轴的原始值

### Requirement: Console shows scan Git identity with the bound knowledge catalog

The console SHALL show the selected scan's full commit, original revision, compatibility `branch` display hint, dirty state and scan ID beside the scan catalog, and SHALL update the knowledge catalog and Git card as one versioned selection. A tag or commit copied into the compatibility field SHALL NOT be used as proof that the commit belongs to a branch.

#### Scenario: Historical catalog load succeeds

- **WHEN** the user changes the scan-history selection
- **THEN** the console loads that scan's catalog and knowledge tree before declaring the new Git baseline current

#### Scenario: Historical catalog load fails

- **WHEN** the selected historical catalog cannot be loaded
- **THEN** the console restores the previously confirmed scan selection and baseline
- **AND** it does not label the old visible knowledge tree with the failed new commit

### Requirement: Regression Case page exposes the V4 workflow and raw artifacts

The console SHALL allow a user to enter any eligible Facade path, choose generation-only or generation-plus-QA, start and poll the V4 handoff, open the bound Codex task, and inspect the raw generation and execution JSON.

#### Scenario: V4 handoff reaches a terminal state

- **WHEN** the handoff becomes `COMPLETED`, `PARTIAL`, `BLOCKED` or `FAILED`
- **THEN** the page shows the frozen model, turn state, DSL, Variants, Operation request/response traces, structured assertions and source-scan Git mappings that are present
- **AND** missing or failed data remains explicit in the JSON

#### Scenario: User switches from polling to generation history

- **WHEN** the user requests the existing V4 Generation list while a handoff request is in flight
- **THEN** the console invalidates both late successful responses and late errors from the older view
- **AND** the user-selected Generation JSON is not overwritten by stale polling

### Requirement: 控制台只使用当前版本化API

控制台 SHALL 按能力通过 `/api/v2`、`/api/v3` 或 `/api/v4` 展示和操作系统、扫描、知识、资源、Hybrid Case、Case Template与运行，不调用legacy `/api/projects` 等路由。

#### Scenario: 编译自然语言场景

- **WHEN** 用户在控制台输入港币多乘客请求
- **THEN** 页面展示结构化约束、missing_conditions或独立变体，不在浏览器中猜测QA数据

#### Scenario: 查看运行失败

- **WHEN** 真实工具、断言、Oracle或清理失败
- **THEN** 页面展示步骤状态、简洁错误和结构化diff，不显示QA密钥

### Requirement: Case fields distinguish variation, source and actual observation

The console SHALL use reusable read-only field trees, variant comparisons and assertion comparisons. Variation SHALL derive from template parameters, compiled selections and explicit dependencies, never from differences between runtime JSON payloads. Planned and actual values SHALL remain distinct.

#### Scenario: Preparation varies a business state

- **WHEN** a varied parameter selects preparation conditions while the request identity comes from a data output
- **THEN** the preparation condition is a variation and the dynamic identity remains a preparation-sourced field without an automatic variation badge

#### Scenario: Nested values and missing observations

- **WHEN** a field contains an object, array, long string, mixed type, unknown schema field or an empty value
- **THEN** all recorded content remains inspectable through collapsed field trees and complete-value details
- **AND** absent, null, empty object, empty array, empty string, zero, false, unevaluated and unrecorded states are not conflated

#### Scenario: Effective assertions differ by subcase

- **WHEN** variants have overridden or parameter-dependent assertions
- **THEN** only genuinely common effective rules appear as common expectations and each subcase shows its own final rules

### Requirement: Execution console follows one evidenced batch and preserves reading state

The console SHALL show one batch with its bound version, environment, subcase list, conclusion, evidenced stages, assertion outcomes, actual request and actual response. Existing polling SHALL refresh only the active scope without resetting the user's selection, filters, expanded details or viewing position.

#### Scenario: Batch is still running

- **WHEN** a batch has not yet recorded results for all included subcases
- **THEN** the list retains all subcases whose inclusion is proved by the execution contract and exact bound generation
- **AND** missing result records do not imply waiting, running, unexecuted or passed statuses
- **AND** when the complete inclusion set cannot be proved, the summary says only how many results are recorded
- **AND** a RUNNING batch never appears wholly passed merely because all currently recorded results passed

#### Scenario: Scope changes during polling

- **WHEN** the user changes system, entry, version, environment or batch while an older read is in flight
- **THEN** neither the old success nor the old failure changes the new view

#### Scenario: Negative checks, preparation failures and cleanup anomalies

- **WHEN** existing records show expected rejection, preparation blocking, operation failure, assertion failure or cleanup failure
- **THEN** the display follows recorded assertion outcomes and stage evidence without judging success from an HTTP or business error code
- **AND** successful business checks followed by cleanup failure display “业务校验通过 · 清理异常”
- **AND** counts represent subcases rather than assertions and each subcase is counted once

#### Scenario: History and actual browser acceptance

- **WHEN** the user views a historical execution or the changed UI is verified
- **THEN** definitions belong to the exact recorded generation, absent evidence is explicit, and raw details remain collapsed and inspectable
- **AND** acceptance exercises the running HTTP page in a real browser, including the four-screen path, field expansion, batch switching and isolated running-result updates

### Requirement: Case entry selector supports local filtering

The console SHALL provide a searchable single-selection entry combobox matching display names, canonical paths and entry types without case sensitivity. Search text SHALL remain separate from committed selection; only confirmation changes the entry, versions and generation target.

#### Scenario: Search and confirm an entry
- **WHEN** a user types part of an entry name or path
- **THEN** matching current and historical entries are shown, with all entries for empty search and a clear empty-result message
- **AND** mouse or arrow keys and Enter can confirm a result; Escape or blur cancels search and restores the committed label

#### Scenario: Refresh or switch the system
- **WHEN** the current system directory refreshes or another system is selected
- **THEN** refresh preserves a valid committed entry and a system change clears search and selection
- **AND** stale responses cannot restore another system's entries

### Requirement: Environment selection loads before slow workspace catalogs

The console SHALL load configured environments as soon as the system is selected, before waiting for local settings, scan history or other system catalogs. It SHALL distinguish loading, empty configuration and request failure.

#### Scenario: Scan history is slow
- **WHEN** scan history takes several seconds
- **THEN** environments are already selectable and environment rendering does not wait for history

#### Scenario: Environment read fails or system changes
- **WHEN** the environment request fails or belongs to an obsolete system
- **THEN** failure is visible without blocking other catalogs and obsolete responses do not update current selectors

