## ADDED Requirements

### Requirement: 远程配置连接由受限Java Worker持有

系统 SHALL 通过当前系统应用身份和最小环境变量白名单启动Java Worker，并仅允许Snapshot绑定的固定Oracle操作；Python、Agent、Case与API均不得接收数据库或Redis密码、云凭据或API Key。

#### Scenario: 执行批准的只读订单查询
- **WHEN** QA Worker收到正确系统、QA环境、已知资源、已知操作和有效目录摘要
- **THEN** Worker使用READ资源执行固定查询并只返回白名单业务字段

#### Scenario: 拒绝越权资源访问
- **WHEN** 请求包含非QA环境、未知操作、SQL文本、任意Redis命令、错误应用身份或不存在的READ池
- **THEN** Worker在访问业务数据前拒绝并返回不含连接信息的稳定错误码

### Requirement: 页面准确展示资源状态

系统 SHALL 从源码发现MySQL、TiDB、Redis和MQ资源，并以 `DISCOVERED / CONNECTED / READY / BLOCKED / EFFECT_ONLY / STALE` 展示状态及源码证据。

#### Scenario: 连接成功但未完成业务验证
- **WHEN** 资源探测成功但没有业务Case证据
- **THEN** 页面显示CONNECTED而不是READY

#### Scenario: MQ只有下游效果证据
- **WHEN** MQ没有轨迹查询端点但业务Case验证了消费后的订单或任务结果
- **THEN** 页面显示EFFECT_ONLY且报告明确未直接证明消息传输

#### Scenario: 页面输出脱敏
- **WHEN** 资源探测或Worker调用失败
- **THEN** API只返回稳定错误码、时间和安全摘要，不返回Host、账号、密码、Token、远程配置或原始SDK异常

#### Scenario: 业务证据升级资源状态
- **WHEN** 一个Snapshot绑定Case的非空Oracle断言通过且RunRecord含匹配步骤观察证据
- **THEN** 系统以步骤ID和断言摘要发布READY或EFFECT_ONLY；缺失、空断言或失败步骤只记为BLOCKED
