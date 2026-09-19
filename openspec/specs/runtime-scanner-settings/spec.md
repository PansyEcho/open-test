# runtime-scanner-settings Specification

## Purpose
TBD - created by archiving change multi-system-console-reliability-and-reset. Update Purpose after archive.
## Requirements
### Requirement: scriptgen 在每次扫描前动态解析并验证

系统 SHALL 按环境变量、本地运行设置、已安装模块的优先级动态选择 scriptgen，并在提交任务前验证目录、模块入口和启动能力。

#### Scenario: 本地设置提供有效路径
- **WHEN** `.opentest/settings.yaml` 指向可启动的 scriptgen agent harness
- **THEN** PyCharm 与终端启动的 OpenTest 均报告扫描器就绪并可提交扫描

#### Scenario: 配置路径无效
- **WHEN** 所有候选均不可用
- **THEN** 页面禁用自动扫描并展示稳定修复建议，后端拒绝请求且不创建必然失败的任务

### Requirement: 本地运行设置不进入共享产物

系统 SHALL 以 `0600` 原子写入 Git 忽略的本地设置，并不得把路径以外的本机敏感配置复制进日志、Agent 输入、Snapshot 或报告。

#### Scenario: 更新扫描器路径
- **WHEN** 回环客户端保存新的 scriptgen 路径
- **THEN** 后续扫描立即使用新设置，无需重启 Uvicorn

### Requirement: 扫描动态读取本地运行与系统网关设置
系统 SHALL 在扫描提交时动态解析scriptgen路径和资源配置环境；系统 SHALL NOT 读取HTTP Job网关或Labrador Token，不生成旧HTTP Job执行入口。

#### Scenario: 普通DSF系统无HTTP网关扫描
- **WHEN** 用户未配置旧HTTP Job Token或网关而提交DSF系统扫描
- **THEN** Facade及MQ发现正常进行
- **AND** `CommonFacade#executeJob` 等DSF方法仍作为Facade保留

#### Scenario: 历史HTTP Job产物被调用
- **WHEN** 客户端尝试执行旧job_http_trigger操作
- **THEN** 系统拒绝已退役路径，且不调用HTTP脚本

### Requirement: Resource configuration environment is explicit and scan-bound

The system SHALL allow each registered system to select `test`, `qa`, `uat` or `auto` as the resource configuration environment and SHALL freeze the actually selected property-file suffix into the resulting scan and DSF profile.

#### Scenario: User selects a concrete environment

- **WHEN** the user selects `test`, `qa` or `uat` and starts a new scan
- **THEN** discovery reads safe filter files matching `*.<environment>` and combines their values with the main `dsf_application.properties` template when present
- **AND** later DSF, database and MQ Operation resolution uses that scan-bound environment instead of a hard-coded QA suffix
- **AND** resource types without a scan-bound executable adapter remain unsupported rather than reading an unrelated environment definition

#### Scenario: Auto compatibility mode is selected

- **WHEN** the setting is `auto`
- **THEN** scanning prefers matching `*.qa` filters and falls back to matching `*.test` filters only when QA filters are unavailable
- **AND** the actual choice is recorded so execution does not guess again

