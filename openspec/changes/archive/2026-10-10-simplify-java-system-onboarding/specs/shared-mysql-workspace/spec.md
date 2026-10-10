## MODIFIED Requirements
### Requirement: Missing required observation is a failed assertion
The system SHALL distinguish business behavior differences from unavailable observation. When a frozen Case itself contains an MQ send, internal RPC or command assertion and no observation source is available to execute it, that assertion SHALL fail with OBSERVATION_FAILED, preserving other results and cleanup. The system SHALL NOT synthesize required observations from static scan analysis.

#### Scenario: MQ observer is not configured
- **WHEN** a frozen Case contains an assertion on MQ sending but no direct observation source exists
- **THEN** the assertion fails with null actual evidence and is not passed by route availability or downstream effects

## REMOVED Requirements
### Requirement: Scan assets provide reusable contracts and coverage
**Reason**: 程序覆盖分析整体删除，扫描资产不再持久化覆盖义务；该要求名中的coverage失去所指。
**Migration**: 由同名去coverage的“Scan assets provide reusable contracts”要求替代；ot_interface.coverage_json停止写入，历史值被忽略，不做数据迁移。

## ADDED Requirements
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
