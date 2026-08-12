## ADDED Requirements

### Requirement: Oracle可扩展且配置留在本地

系统 SHALL 支持DSF、MySQL、TiDB、Redis和MQ观察适配器。Booking.Core的MySQL、TiDB和Redis必须通过受限Java Worker按固定operation_id访问，Python、本地配置和LLM不得读取连接密码。

#### Scenario: 异步状态最终满足
- **WHEN** Oracle在deadline前观察到预期订单状态
- **THEN** 步骤通过并保留每次观察的时间、结果摘要和最终证据

#### Scenario: 轮询超时
- **WHEN** deadline到达仍未满足断言
- **THEN** 步骤失败并保留最后观察值，不进行无限重试

#### Scenario: 空Oracle断言
- **WHEN** Oracle请求没有任何稳定业务断言
- **THEN** Poller在读取资源前拒绝请求，不把首次读取成功当作业务Case通过
