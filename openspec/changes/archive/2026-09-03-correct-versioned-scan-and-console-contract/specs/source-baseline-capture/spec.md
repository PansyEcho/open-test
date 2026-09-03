## MODIFIED Requirements

### Requirement: 扫描绑定可核查源码基线

系统 SHALL 在Git扫描前把用户选择的branch、tag、commit或默认HEAD解析为完整commit，物化并只读取该commit的托管快照，并记录源码绝对路径、完整commit、请求revision、兼容`branch`展示提示、`dirty=false`、分析器版本和捕获时间。显式revision复制到`branch`字段时该字段 SHALL NOT 被视为真实branch归属证明。非Git目录 SHALL 记录源码路径和目录内容摘要，且只在内容仍与基线一致时允许后续读取。

#### Scenario: 选择Git revision扫描

- **WHEN** 用户选择一个可解析为commit的branch、tag、commit或使用默认HEAD发起扫描
- **THEN** 系统从该完整commit的托管快照生成扫描结果
- **AND** 基线保存原始revision和兼容branch展示提示，dirty为false且dirty摘要为空
- **AND** tag或commit形式的展示提示不证明该commit属于某个branch

#### Scenario: Git working tree含未提交改动

- **WHEN** 注册仓库相对所选commit存在已跟踪或未跟踪的working tree变化
- **THEN** 本次扫描仍只读取所选commit快照，不把working tree内容或dirty摘要纳入该代际

#### Scenario: 扫描后Git源码继续变化

- **WHEN** 扫描启动后注册仓库切换分支、产生新commit或修改working tree
- **THEN** 已冻结扫描及其后续源码读取继续使用原完整commit快照

#### Scenario: revision无效

- **WHEN** 用户选择不存在、不是commit对象或包含不支持字符的revision
- **THEN** 系统在扫描工具启动前拒绝请求且不发布新的latest scan

#### Scenario: 非Git源码目录

- **WHEN** 注册目录不是Git工作区且用户未显式选择revision
- **THEN** 系统保留源码路径，以空commit、空branch和目录内容摘要建立显式基线
- **AND** 后续需要读取该代际时先确认活动目录与摘要一致

### Requirement: Scan history exposes the revision used by knowledge and Cases

The system SHALL return `scan_id`, commit, requested revision, the non-authoritative compatibility `branch` display hint, dirty state, dirty digest and capture time for each successful scan, and each V4 generation and handoff SHALL retain the source scan identity it used. A Git-backed scan SHALL populate the full commit and original revision; a non-Git scan SHALL leave those Git fields empty and expose its directory digest as defined above. A display hint copied from an explicit tag or commit SHALL NOT be treated as proof of branch membership.

#### Scenario: User inspects a historical knowledge version

- **WHEN** the user selects a historical scan created from a branch, tag or commit
- **THEN** the scan catalog and knowledge tree are loaded from that exact scan
- **AND** the displayed Git baseline identifies the same immutable commit and original revision

#### Scenario: Case uses more than one source system

- **WHEN** a V4 handoff reads the target system and an authorized provider system
- **THEN** its result exposes each safe `source_system_id` and `source_scan_id`
- **AND** the console can map every source scan back to its Git baseline without exposing source-root paths
