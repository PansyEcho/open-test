# resource-projection Specification

## Purpose
TBD - created by archiving change multi-system-console-reliability-and-reset. Update Purpose after archive.
## Requirements
### Requirement: 资源主表只投影当前源码发现
系统 SHALL 使用当前已发布扫描中的可靠资源，并将旧源码或旧系统状态移入高级历史。连接探测 SHALL 独立于业务校验Profile，使用项目选定QA/UAT实际配置和通用Java Worker，不包含Booking固定映射。

#### Scenario: 新系统尚无结果校验适配器
- **WHEN** 用户检测没有业务校验Profile的系统
- **THEN** 执行数据库轻量只读查询、Redis PING或MQ路由查询，分别记录每项结果和原因；连接成功不代表业务校验通过

#### Scenario: 源码摘要漂移
- **WHEN** 资源状态绑定的源码、操作目录或Worker版本与当前值不同
- **THEN** 资源标记为已过期而不是沿用历史连接成功状态

#### Scenario: 同一源码重新扫描
- **WHEN** 用户在相同commit、相同未提交差异和相同资源声明下重新扫描，仅扫描ID、扫描时间或托管快照目录变化
- **THEN** 资源保持原连接状态，不标记为源码摘要漂移

#### Scenario: 重测与部分失败
- **WHEN** 用户重新探测且部分资源失败
- **THEN** 创建新任务并显示成功数量及各失败原因，原失败任务保持不变

#### Scenario: 不同环境先后检测
- **WHEN** 用户先检测QA再检测UAT
- **THEN** 各任务保留实际环境与结果，资源页面明确标明最近连接检测所属环境，不把它推定为其他环境也已连接

### Requirement: MQ 按 NameServer 配置聚合

系统 SHALL 在主表按 NameServer 配置 Key 展示一个 MQ 集群，Producer、Consumer、Topic、Group、Tag 和证据进入详情；路由连接与业务效果分开记录。

#### Scenario: Booking.Core 使用一个 NameServer Key
- **WHEN** 当前 Manifest 包含多个 Producer 和 Consumer 但共享同一配置 Key
- **THEN** 主表只显示一行 MQ 集群，路由成功仅更新连接状态，业务效果仍为 `EFFECT_ONLY` 或 `N/A`

