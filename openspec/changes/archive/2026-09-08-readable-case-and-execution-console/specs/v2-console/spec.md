## MODIFIED Requirements

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

## ADDED Requirements

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
