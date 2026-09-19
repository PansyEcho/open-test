# knowledge-target-workspace Specification

## Purpose
TBD - created by archiving change system-specific-knowledge-discovery-and-task-progress. Update Purpose after archive.
## Requirements
### Requirement: 知识目录与目标工作区一致
控制台 SHALL 按业务背景、Facade/MQ接口契约、业务术语、代码枚举及外部系统组织知识目录。用户选择接口 SHALL 读取同一扫描的独立契约，不依赖旧长文节点；选择本身不得启动Agent。

#### Scenario: 选择退款Facade方法
- **WHEN** 用户在 `Facade → RefundFacade → cancel` 点击方法
- **THEN** 展示用途、请求字段、业务响应字段、证据和契约状态，并提供生成、更新或查看当前任务入口
- **AND** 叶子名称不重复显示Facade类名，旧长文过期不覆盖当前契约状态

### Requirement: 系统背景采用叙述与候选确认
控制台 SHALL 支持人工系统背景及普通业务术语；语义扫描证明的枚举 SHALL 直接只读展示，不要求人工完善。外部系统 SHALL 按当前调用方引用形成层级目录，支持维护系统和接口说明。

#### Scenario: 普通系统编辑背景
- **WHEN** 用户打开任一系统知识页
- **THEN** 展示当前系统背景、可维护人工术语和只读代码枚举
- **AND** 下游无需接入即可按系统展开当前引用接口，人工说明在重扫后保留

### Requirement: 知识工作区必须区分正式入口事实与候选
系统 SHALL 保留历史正式入口事实与typed候选的来源区分，主知识视图 SHALL 使用独立接口契约，不要求维护内部状态机和公共逻辑长文。

#### Scenario: 查看入口知识候选
- **WHEN** 历史入口包含尚未发布的typed候选
- **THEN** 候选不得升级为正式契约或自动标记为已确认
- **AND** 主页面仍可展示扫描证明的用途与字段契约

