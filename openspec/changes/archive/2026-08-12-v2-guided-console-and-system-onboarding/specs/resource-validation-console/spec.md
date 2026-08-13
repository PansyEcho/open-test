## ADDED Requirements

### Requirement: MQ按连接集群聚合

系统 SHALL 按NameServer配置Key展示MQ连接资源，并把Producer、Consumer、Topic、Group和源码证据放入详情。

#### Scenario: 多个交互共享NameServer
- **WHEN** 源码中的多个Producer和Consumer都引用`mq.nameSrvAddress`
- **THEN** 资源列表只展示一个MQ集群，详情保留全部去重后的交互事实

### Requirement: 连接与业务验证分级

系统 SHALL 分别展示最近连接探测和Snapshot绑定业务验证，不把一次探测描述为持续在线或业务通过。

#### Scenario: 临时Worker探测成功
- **WHEN** Worker只读连接资源后退出
- **THEN** 页面显示最近连接成功时间，并继续把未运行的业务Case标记为未验证

#### Scenario: MQ路由可查询但无消息轨迹
- **WHEN** NameServer只读Topic路由查询成功且没有直接消息轨迹能力
- **THEN** 连接状态为已连接，消息业务证据仍只能是仅效果验证

### Requirement: 结果校验能力可见可操作

系统 SHALL 使用“结果校验能力”面向用户，并允许从全局按钮或资源行数量打开同一详情视图。

#### Scenario: 点击资源行校验数量
- **WHEN** 用户点击某资源的校验能力数量
- **THEN** 详情抽屉展示校验项标题、参数、结果字段和证据等级，不展示SQL、Key模板或连接信息
