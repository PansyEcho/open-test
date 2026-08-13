## ADDED Requirements

### Requirement: 自然语言先生成业务测试方案预览

系统 SHALL 把业务描述编译为订单数量、乘客组合、调用流程、测试数据、结果校验、清理策略和缺失字段组成的可读预览。

#### Scenario: 预览港币成人儿童多乘客订单
- **WHEN** 用户输入“创建2个港币支付的多乘客订单，包含成人和儿童”
- **THEN** 预览显示2个订单、成人儿童组合、匹配入口、逐Item价格校验和明确补充字段，不展示QA JSON

### Requirement: 用户确认前不得创建业务数据

系统 SHALL 把预览和执行分成不同操作，只有显式确认的运行请求才能调用DSF或Job。

#### Scenario: 创建或更新预览
- **WHEN** 用户提交自然语言或补充业务字段
- **THEN** 系统可以读取知识并规划资源，但不调用创单工具、不执行Job且不生成业务run_id

#### Scenario: 确认后执行
- **WHEN** 预览无缺失条件、Snapshot有效且用户显式确认
- **THEN** 系统执行受控Scenario并生成报告，仍受QA Token、Fixture、资源和全局Job门禁约束

### Requirement: 预览可保存为回归Case

系统 SHALL 允许用户把确认过的自然语言测试方案保存为新的长期回归Case，且不覆盖同名人工Case。

#### Scenario: 保存测试方案
- **WHEN** 用户选择保存已确认预览
- **THEN** 系统创建稳定ID的用户维护Case并记录来源预览与知识版本
