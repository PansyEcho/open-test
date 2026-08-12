# 场景与变体设计

## Context

createOrder知识已经包含成人必需、港铁直接收单、港币逐乘客价格校验、报价来源和状态机。场景生成必须能反向追溯这些结论，并将每个订单实例拆成可独立执行、清理和重放的变体。

## Decisions

### 覆盖目标先于Case

生成器先把业务规则、状态转换、依赖结果和边界划分为CoverageTarget，再从最近真实扫描入口的请求模板构造ScenarioDefinition。每个Variant保存覆盖目标ID、真实DTO输入和数据前置条件，报告可由Variant反查知识证据。报价缺失、高于用户价格等下游结果不作为createOrder请求字段。

### 约束驱动的有限组合

每个维度先定义有效等价类和边界值。生成器优先保留基础成功、单维变化、关键失败和贪心pairwise覆盖，不生成裸笛卡尔积。稳定排序与seed共同决定Variant ID。

### 自然语言编译

编译器只识别知识支持的支付币种、乘客构成、数量和入口。否定、数量越界及未消费条件进入missing_conditions；缺少QA必填模板、有效路线报价、身份DTO或公司枚举时状态为needs_input，不虚构值。

### Git存储

CoverageTarget、Scenario和Variant分别写入 `cases/coverage-targets.yaml`、`cases/scenarios/<id>-<hash>.yaml` 和 `cases/variants/<id>-<hash>.yaml`。文件名哈希避免有损slug碰撞；系统级文件锁覆盖读、合并和发布。增量生成合并未受影响目标、场景与变体，仅全量语义失效时标记stale。SQLite后续保存覆盖反向关系；一期Case真相始终可脱离数据库读取。

## Risks / Trade-offs

- 接口模板可能随扫描变化 → Case保存真实scan ID，Snapshot拒绝组合不同scan的场景和工具。
- pairwise不能替代风险分析 → 高风险业务失败组合显式列为必选种子。
- 自然语言歧义 → 返回已解析约束和缺失条件，由用户补充后重编译。
- 业务问题或内部状态Oracle未就绪 → Variant标记blocked，禁止空断言产生绿色通过。
