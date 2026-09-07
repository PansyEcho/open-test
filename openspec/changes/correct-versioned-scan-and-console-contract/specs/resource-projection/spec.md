## MODIFIED Requirements

### Requirement: 资源主表只投影可信源码发现

系统 SHALL 为扫描组件记录`complete`、`partial`或`failed`完整性。普通信息warning不得阻止完整扫描发布；部分扫描 SHALL 展示可靠新资源，只从失败或未读源码范围保留上一完整扫描资源并标明来源。只有完整扫描中的缺失才能确认资源已删除。

#### Scenario: 单个XML无法解析

- **WHEN** 本次扫描可靠发现部分MySQL、Redis或MQ资源但一个生产XML无法读取或解析
- **THEN** 页面展示可靠新资源并只保留该失败范围内的必要旧资源
- **AND** 保留项标记原scan来源，部分结果不得成为知识或Case的新完整基线

#### Scenario: 首次扫描部分成功

- **WHEN** 系统没有上一完整扫描且本次资源组件为partial
- **THEN** 页面展示本次已发现资源和不完整提示
- **AND** 不把结果显示成系统没有资源

#### Scenario: 后续完整扫描确认删除

- **WHEN** 下一次完整扫描不再发现以前保留的资源
- **THEN** 新完整投影移除该资源
- **AND** 不永久携带历史资源

#### Scenario: 普通warning与不完整输入分别处理

- **WHEN** 扫描组件返回不影响输入覆盖范围的普通warning
- **THEN** 系统保存稳定warning code和安全消息，并允许完整扫描正常发布
- **WHEN** 必需源码范围无法枚举、读取或解析
- **THEN** attempt保存稳定issue code及失败相对范围，且不得推进知识与Case使用的latest完整基线
- **AND** 页面仍可展示该attempt中可靠发现的provisional资源

### Requirement: 资源发现、连接检测与结果校验时间分离

系统 SHALL 分别展示源码发现时间、最近连接探测时间和最近业务校验时间；缺少连接配置或结果校验能力不得过滤已发现资源。

#### Scenario: 发现但未检测的资源

- **WHEN** 源码扫描发现资源但从未执行连接探测
- **THEN** 页面显示待配置或未检测，最近检测时间为空
- **AND** 源码扫描时间不得冒充连接检测时间

#### Scenario: 同一逻辑Redis由多个初始化bean使用

- **WHEN** 生产Spring XML中的`RedisClient`、`RedissonProxy`、历史`RedissionProxy`或带`cacheName`的`CacheClientHA`引用同一`${...}`配置键
- **THEN** 资源主表按该配置键展示一个逻辑Redis，并保留每个初始化bean的源码引用
- **AND** 旧bean资源ID只能作为兼容别名，直写运行值不得成为公开资源身份或被持久化
