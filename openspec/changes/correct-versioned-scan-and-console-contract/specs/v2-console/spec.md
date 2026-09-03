## MODIFIED Requirements

### Requirement: Regression Case page exposes the V4 workflow and raw artifacts

The console SHALL expose one version-neutral Regression Case workflow with separate generation and execution actions, immutable Generation history, explicit environment selection and per-Execution reports.

#### Scenario: Generation reaches a terminal state

- **WHEN** the handoff becomes `COMPLETED`, `PARTIAL`, `BLOCKED` or `FAILED`
- **THEN** the page shows the frozen model, turn state, DSL, ordered Variants and source-scan mapping
- **AND** it does not claim that QA was executed

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
