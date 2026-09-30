## MODIFIED Requirements
### Requirement: 资源主表只投影当前源码发现
系统 SHALL 使用当前已发布扫描中的可靠资源，并将旧源码或旧系统状态移入高级历史。连接探测 SHALL 独立于业务校验Profile，使用项目选定QA/UAT实际配置和通用Java Worker，不包含Booking固定映射。

#### Scenario: 新系统尚无结果校验适配器
- **WHEN** 用户检测没有业务校验Profile的系统
- **THEN** 执行数据库轻量只读查询、Redis PING或MQ路由查询，分别记录每项结果和原因；连接成功不代表业务校验通过

#### Scenario: 源码摘要漂移
- **WHEN** 资源状态绑定的源码、操作目录或Worker版本与当前值不同
- **THEN** 资源标记为已过期而不是沿用历史连接成功状态

#### Scenario: 重测与部分失败
- **WHEN** 用户重新探测且部分资源失败
- **THEN** 创建新任务并显示成功数量及各失败原因，原失败任务保持不变

#### Scenario: 不同环境先后检测
- **WHEN** 用户先检测QA再检测UAT
- **THEN** 各任务保留实际环境与结果，资源页面明确标明最近连接检测所属环境，不把它推定为其他环境也已连接
