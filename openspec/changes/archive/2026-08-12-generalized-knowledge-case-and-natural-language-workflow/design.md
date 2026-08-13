# 通用知识、Case与自然语言测试闭环设计

## Change切换

已归档`v2-guided-console-and-system-onboarding`。`dsf-execution-and-oracles`继续以`WAITING_QA_INPUT`保留任务5.4，不作为正在编码的Change。本change是唯一实施中的核心Change。

## 通用Java知识分析

`GeneralizedJavaKnowledgeTracer`从选中的`KnowledgeTarget`和稳定Manifest开始，先用确定性解析构建符号与调用关系，再按业务深度规则递归：条件分支、业务计算、状态变化、数据库/Redis/MQ/RPC调用、降级和异常处理必须追踪；纯映射、getter/setter与框架代理跳过。Facade通过`ApiService`关联Validator和ServiceInvoker；Job追踪实际执行方法；状态流转追踪Pre/Post Actor；事件继续追到Listener及其业务副作用。

同一全限定方法被多个入口引用且包含可测试逻辑时，生成独立`COMMON_LOGIC`节点并让调用入口通过关系引用。每个生成节点必须包含可验证源码路径、符号、行号、业务分支摘要和结构化分析维度；缺少这些字段的草稿不能标记为已生成。

保留createOrder的既有专用规则作为深层回归基线，通用追踪在该目标上必须合并而非退化现有节点与关系。

## Agent安全边界

默认Agent选择顺序为Codex、Claude Code。两者均不可用时，确定性扫描和代码证明知识仍成功，只有需要语义提炼的深层草稿标记为阻塞。Agent提示仅由系统信息的非敏感投影、目标扫描证据、允许的源码文件和已发布知识构成；拒绝`.opentest/environments`、Fixture、Token、Worker请求/响应和报告路径。

Agent输出使用严格JSON envelope，OpenTest逐项验证系统ID、节点ID、源码路径范围、符号、行号、关系端点与目标闭包。原始Agent输出只存本地忽略目录，只有通过校验的草稿可进入确认工作流。

## 知识草稿、问答与发布

知识目录合并扫描目标、草稿批次、发布节点和开放问题。批量生成在一个系统内串行，先生成代码可证明内容，再按规范化问题文本与受影响节点去重高影响问题。回答一个问题会更新所有受影响草稿，但不会自动发布；用户确认节点后才写入Git真相并重建SQLite索引。`kb:auto`区域可更新，标记外人工内容保留。

## Case生成状态机

Case生成记录分为`MATRIX_DRAFT`、`MATRIX_CONFIRMED`、`CASES_GENERATED`和`BLOCKED`。首次请求只根据已确认知识生成接口级场景矩阵、覆盖点、脚本/校验能力缺口，不生成可执行步骤。只有显式确认矩阵后才生成业务Case与步骤。未确认知识、Fixture、关键枚举、脚本或结果校验能力缺失时，Case保留缺失条件并处于阻塞。

生成资产写入独立generated目录，不覆盖`cases/custom`的31个人工Booking.Core Case。复杂多实体规则保留实体顺序、逐实体结果、聚合结果与门控行为。

## 自然语言测试

自然语言请求先匹配已确认知识、入口和既有Case，生成`NaturalLanguageTestPreview`：订单数量、乘客组合、执行流程、测试数据、结果校验、清理策略、所需资源和缺失业务字段。缺失条件使用字段定义和候选值，不向用户暴露QA JSON。

预览创建和更新均不得调用DSF/Job或创建订单。用户显式确认后，运行接口才把预览编译为临时ScenarioVariant并调用现有执行内核；所有Token、Fixture、Snapshot和资源门禁仍在执行边界校验。成功或阻塞的预览都可选择保存为长期回归Case，但人工资产不被覆盖。

## API与控制台

新增知识目录/节点/批次/问题回答、Case生成/目录和自然语言预览/更新/运行API。控制台知识页采用中间编辑确认区和右侧目录树；回归Case页明确显示四阶段；自然语言页只显示业务输入、可读预览、补充表单和确认执行。

## 兼容与错误语义

现有`knowledge/generations`、Scenario生成和自然语言编译API保持兼容读取。新业务API使用稳定错误码和`missing_conditions`，不以空草稿、空步骤或模拟成功填充功能。真实QA输入不足时保持BLOCKED。
