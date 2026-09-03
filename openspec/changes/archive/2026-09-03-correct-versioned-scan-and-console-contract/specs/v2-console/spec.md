## REMOVED Requirements

### Requirement: V2控制台只使用V2 API

**Reason:** 当前控制台已经按能力使用V2、V3和V4版本化API；继续限定为V2会否定已交付的Hybrid Case与Case Template V4页面流程。

**Migration:** 系统、扫描、知识和资源继续使用V2，Hybrid Case使用V3，Case Template使用V4；控制台仍不得调用legacy `/api/projects`。

## ADDED Requirements

### Requirement: 控制台只使用当前版本化API

控制台 SHALL 按能力通过 `/api/v2`、`/api/v3` 或 `/api/v4` 展示和操作系统、扫描、知识、资源、Hybrid Case、Case Template与运行，不调用legacy `/api/projects` 等路由。

#### Scenario: 编译自然语言场景

- **WHEN** 用户在控制台输入港币多乘客请求
- **THEN** 页面展示结构化约束、missing_conditions或独立变体，不在浏览器中猜测QA数据

#### Scenario: 查看运行失败

- **WHEN** 真实工具、断言、Oracle或清理失败
- **THEN** 页面展示步骤状态、简洁错误和结构化diff，不显示QA密钥

## MODIFIED Requirements

### Requirement: Console shows scan Git identity with the bound knowledge catalog

The console SHALL show the selected scan's full commit, original revision, compatibility `branch` display hint, dirty state and scan ID beside the scan catalog, and SHALL update the knowledge catalog and Git card as one versioned selection. A tag or commit copied into the compatibility field SHALL NOT be used as proof that the commit belongs to a branch.

#### Scenario: Historical catalog load succeeds

- **WHEN** the user changes the scan-history selection
- **THEN** the console loads that scan's catalog and knowledge tree before declaring the new Git baseline current

#### Scenario: Historical catalog load fails

- **WHEN** the selected historical catalog cannot be loaded
- **THEN** the console restores the previously confirmed scan selection and baseline
- **AND** it does not label the old visible knowledge tree with the failed new commit
