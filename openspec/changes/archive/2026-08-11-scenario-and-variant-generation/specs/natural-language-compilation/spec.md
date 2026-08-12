## ADDED Requirements

### Requirement: 自然语言先编译为结构化约束

系统 SHALL 保存原始请求、已识别约束、未识别条件和知识证据，再据此生成独立可重放变体。

#### Scenario: 创建两个港币多乘客订单
- **WHEN** 用户输入“创建2个港币支付的订单，要求多乘客，包含儿童和成人”
- **THEN** 编译结果包含order_count=2、currency=HKD、minimum_passengers=2、adult_count>=1、child_count>=1，并生成两个不同业务订单标识的变体

#### Scenario: 缺少QA必填数据
- **WHEN** 知识没有提供可执行的车次、日期、联系人或乘客身份模板
- **THEN** 返回needs_input和明确missing_conditions，不构造猜测值
