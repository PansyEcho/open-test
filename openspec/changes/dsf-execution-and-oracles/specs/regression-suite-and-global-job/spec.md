## ADDED Requirements

### Requirement: 业务回归套件保留逐Case证据

系统 SHALL 使用生产 `RegressionSuiteReader` 严格加载Suite，并将 `cases/custom` 生命周期文档编译为统一ScenarioVariant。系统批量执行Snapshot绑定的业务变体，并为每个变体保存独立RunRecord、真实Oracle步骤ID、断言摘要、资源证据级别和阻塞原因；连接探测不得计入业务Case通过数。

#### Scenario: 批量执行核心业务Suite
- **WHEN** 用户提交有效Snapshot、Suite和QA环境
- **THEN** 系统顺序执行可运行变体、保留BLOCKED变体，并返回通过、失败、阻塞及资源覆盖汇总

#### Scenario: 自定义Case仍缺少Fixture
- **WHEN** Suite引用的生命周期Case仍声明 `blocked + missing_conditions`
- **THEN** CaseStore返回同ID的BLOCKED ScenarioVariant，而不是未编译占位或绿色通过

#### Scenario: Oracle没有稳定业务断言
- **WHEN** generated、user_edited或即将执行的Oracle步骤没有非空断言
- **THEN** 系统在访问QA前拒绝该变体，且不得发布READY或EFFECT_ONLY资源证据

### Requirement: QA全局Job需要短期显式确认

系统 SHALL 在执行不能按测试订单限定范围的Job前，从Snapshot manifest重读实际工具ID、脚本字节摘要和目标URL，生成只读影响预估和五分钟一次性确认Token。

#### Scenario: 确认后执行QA全局Job
- **WHEN** 请求处于QA环境、工具URL环境一致、Token有效且 `allow_global_job=true`
- **THEN** 系统执行Snapshot绑定Job并记录预估、确认和结果证据

#### Scenario: 拒绝未确认或跨环境Job
- **WHEN** Token缺失、过期、已使用，或工具目标不是QA
- **THEN** 系统在调用Job前拒绝执行

#### Scenario: Suite声明与Snapshot工具漂移
- **WHEN** Job脚本字节、URL、工具ID或Snapshot任一项与预估时绑定不一致
- **THEN** 系统在签发或消费Token前拒绝，且不调用Job Runner
