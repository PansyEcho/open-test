## ADDED Requirements

### Requirement: createOrder Fixture仅在本机安全保存

系统 SHALL 将完整创单请求保存为Git忽略的0600本地文件，读取接口 SHALL 只返回非敏感摘要，Snapshot、日志、任务、报告和Agent输入 SHALL 不包含请求正文或乘客身份。

#### Scenario: 保存可成功创单Fixture
- **WHEN** 用户从回环页面提交完整请求、预期EBK供应商和票机预期
- **THEN** 系统原子写入本地文件并返回请求摘要、乘客数量和配置完成状态

### Requirement: createOrder MVP验证业务结果而非连接探测

系统 SHALL 调用真实 `TradeFacade#createOrder` 并用批准的MySQL主库、临时库、Item和Redis校验项验证业务结果；MQ仅在可归因时标为 `EFFECT_ONLY`，TiDB READ池不可用时保持阻塞但不冒充结果。

#### Scenario: EBK实时分单成功
- **WHEN** Fixture指定一个可成功的EBK实时分单请求且用户显式确认执行
- **THEN** 报告验证响应、TICKETING订单、供应商/票机、临时收单库0行、逐Item和Redis稳定Key，并记录保留订单号与清理责任

#### Scenario: Fixture尚未配置
- **WHEN** 用户请求MVP计划或执行但本地Fixture不完整
- **THEN** 系统返回 `BLOCKED` 和具体缺失项，不得调用DSF、Worker或QA资源
