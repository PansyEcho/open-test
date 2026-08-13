## ADDED Requirements

### Requirement: 资源主表只投影当前源码发现

系统 SHALL 使用当前扫描源码摘要过滤资源，并将旧摘要或旧系统状态移入高级历史；没有专用适配器的系统不得调用 Booking.Core Worker。

#### Scenario: 新系统尚无结果校验适配器
- **WHEN** 用户查看非 Booking.Core 系统资源
- **THEN** 页面展示源码发现和“尚未支持该系统结果校验”，不会发起 Booking.Core Worker 请求

#### Scenario: 源码摘要漂移
- **WHEN** 资源状态绑定的源码、操作目录或 Worker 摘要与当前值不同
- **THEN** 资源标记为已过期而不是沿用历史连接成功状态

### Requirement: MQ 按 NameServer 配置聚合

系统 SHALL 在主表按 NameServer 配置 Key 展示一个 MQ 集群，Producer、Consumer、Topic、Group、Tag 和证据进入详情；路由连接与业务效果分开记录。

#### Scenario: Booking.Core 使用一个 NameServer Key
- **WHEN** 当前 Manifest 包含多个 Producer 和 Consumer 但共享同一配置 Key
- **THEN** 主表只显示一行 MQ 集群，路由成功仅更新连接状态，业务效果仍为 `EFFECT_ONLY` 或 `N/A`
