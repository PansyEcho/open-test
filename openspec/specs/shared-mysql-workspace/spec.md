# shared-mysql-workspace Specification

## Purpose
TBD - created by archiving change remote-mysql-interface-regression. Update Purpose after archive.
## Requirements
### Requirement: 历史重复请求证据完整保留

迁移 SHALL 保留旧文件模式中同一Data请求已发生的多次执行及原始request_id。新库请求索引 SHALL 由原目录语义中最近的一次执行持有，较早记录仅将索引列置NULL，原摘要、载荷和源码文件 SHALL 不被删改。此迁移兼容 SHALL NOT 放宽新请求的唯一性。

#### Scenario: 中断后迁移同一请求的两次历史试跑
- **WHEN** 较早试跑已迁入并占用了请求索引，而来源还存在同请求的较新试跑
- **THEN** 验证原载荷相同后释放较早记录的索引，保留两次真实记录，由较新记录持有索引
- **AND** 重复迁移仍得到相同原始证据，不再次调用业务接口

#### Scenario: 同一固定Generation再次执行
- **WHEN** 两次独立Case执行复用同一Variant及数据函数
- **THEN** 新Data请求去重键包含本次Case执行身份，同次调用稳定而不同次执行互不冲突
- **AND** 固定Case定义、历史请求号和预期不被改写

### Requirement: 任务身份互斥不得扩大到系统目录

任务创建 SHALL 仅按数据库与任务身份串行判定；该锁 SHALL 保持到承载事务提交或回滚后连接关闭。已经持有各自系统行的不同工作台 SHALL 能并发创建不同任务，不再追加全系统目录锁。

#### Scenario: 两工作台同时为不同系统创建任务
- **WHEN** 两个Data工作流分别已持有A和B的系统行后创建各自任务
- **THEN** 两者均能提交，不因按相反顺序等待其他系统行而死锁

### Requirement: Shared metadata uses existing typed aggregates in MySQL
The system SHALL persist shared systems, immutable scans, interfaces, contract revisions, knowledge, generations, data functions, published capabilities, workflows, execution results and published rules in MySQL using their existing validated models. Credentials and machine paths SHALL remain local. Metadata connections SHALL be distinct from business test connections.

#### Scenario: Read shared data on a second workstation
- **WHEN** a second workspace connects to the metadata database
- **THEN** it reads the same persisted identities and exact versions without importing the first workspace's absolute paths

#### Scenario: Preserve user knowledge during migration
- **WHEN** existing knowledge and frozen generations are imported
- **THEN** model values and manual Markdown are preserved and references are verified before storage is switched

### Requirement: Retired archives preserve explicit recovery limits
The system SHALL preserve an inactive legacy archive's system identity with `is_archived=1`, import its compatible knowledge nodes, edges, context and standard questions only after validating those files against the original archive manifest, and retain its original local directories. Retired Cases, scans, additional legacy question formats and workstation execution assets SHALL NOT be promoted to current executable assets. The shared archive SHALL expose `restore_scope=local_only` with an actionable reason when those assets have not been fully imported. Original machine source paths SHALL remain only in the original local archive.

#### Scenario: Import compatible knowledge from a legacy archive
- **WHEN** a legacy archive contains compatible knowledge and retired execution formats
- **THEN** its compatible knowledge is queryable in the existing shared tables and its system remains archived
- **AND** unrelated old-file integrity failures remain visible without suppressing independently verified knowledge or deleting the original files

#### Scenario: Reject incomplete shared restoration
- **WHEN** a user requests shared restoration of a local-only legacy archive
- **THEN** restoration is rejected with the archive's specific reason and the shared system remains inactive
- **AND** the reason explains that integrity inspection, repair and restoration require the preserved file-mode workspace, and migration into the current executable directory requires a new scan and legacy-format conversion before activation

### Requirement: Shared mutation preserves atomicity and idempotency
The system SHALL publish related shared records and revision pointers atomically in short transactions. It SHALL preserve global Operation request identity, system-scoped data request identity and request-content conflict validation. Long-running scans and business calls SHALL run outside database transactions.

#### Scenario: Concurrent duplicate operation
- **WHEN** two workspaces submit the same Operation request identity
- **THEN** only one dispatch occurs and a conflicting request cannot reuse that identity

#### Scenario: Replay a completed data draft request
- **WHEN** a data draft execution request matches an existing execution listed as a summary
- **THEN** the system reads that execution's complete persisted outputs, steps and checks before returning it
- **AND** it does not dispatch the business calls again

#### Scenario: Concurrent scan publication
- **WHEN** related systems publish simultaneously
- **THEN** publication reads the current directory under its transaction and neither direction is missed

### Requirement: Large immutable artifacts are cached by existing versions
The system SHALL query small metadata directly and transfer large scan and tool artifacts only when their fixed scan version is absent locally. List and progress requests SHALL NOT read full artifact or execution payloads.

#### Scenario: Repeated scan access
- **WHEN** the same immutable scan is requested twice
- **THEN** the second request reuses the cached artifact while mutable directory state is read from MySQL

### Requirement: Local execution ownership survives shared persistence
The system SHALL persist the owner workspace of active workflows and executions, and SHALL only use local process liveness to recover records belonging to that workspace.

#### Scenario: Another workspace starts
- **WHEN** a workspace cannot find the PID of a task owned by a different workspace
- **THEN** the remote task remains unchanged and is not dispatched again

### Requirement: Missing required observation is a failed assertion
The system SHALL distinguish business behavior differences from unavailable observation. When a frozen Case itself contains an MQ send, internal RPC or command assertion and no observation source is available to execute it, that assertion SHALL fail with OBSERVATION_FAILED, preserving other results and cleanup. The system SHALL NOT synthesize required observations from static scan analysis.

#### Scenario: MQ observer is not configured
- **WHEN** a frozen Case contains an assertion on MQ sending but no direct observation source exists
- **THEN** the assertion fails with null actual evidence and is not passed by route availability or downstream effects

### Requirement: Scan assets provide reusable contracts
The system SHALL persist per-interface request and response contracts, purposes, four-state field requirements and dependency evidence with the source scan. Unsupported semantics SHALL remain explicit unknowns. Existing generations SHALL retain exact frozen assets.

#### Scenario: Read a known contract without source access
- **WHEN** a task requests an existing scan and contract revision
- **THEN** persisted input and response contracts are returned without reparsing source

### Requirement: MySQL为唯一生产运行存储
系统 SHALL 要求有效MySQL配置与连接，缺少配置或连接失败时明确报错，不切换文件或SQLite运行分支。历史格式读取仅在离线迁移恢复工具保留。

#### Scenario: 本地重复文件清理后重启
- **WHEN** 按身份、版本、内容和引用验证共享库后删除重复历史文件与可恢复缓存
- **THEN** 重启从MySQL恢复；本机配置、源码绑定及local_only历史归档和恢复内容保持不变

