## ADDED Requirements

### Requirement: 所有知识目标使用同一深层业务追踪契约

系统 SHALL 对Facade、Job、状态流转、事件Listener和共享公共逻辑追踪业务分支、计算、外部调用、降级与副作用，并为每项结论保留可验证源码证据。

#### Scenario: 生成非createOrder Facade知识
- **WHEN** 用户选择扫描目录中的另一Facade方法
- **THEN** 草稿包含关联Validator、ServiceInvoker和至少一项实际业务逻辑证据，而不是入口签名占位

#### Scenario: 追踪事件副作用
- **WHEN** Actor或业务方法触发事件
- **THEN** 草稿继续关联事件载荷和业务Listener结果，只有纯框架派发可以省略

#### Scenario: 抽取共享公共逻辑
- **WHEN** 一个含业务分支的方法被多个目标引用
- **THEN** 系统建立独立共享逻辑节点，并从每个入口说明当前场景关注的分支

### Requirement: 本地Agent遵守只读最小输入边界

系统 SHALL 自动选择可用的Codex或Claude Code辅助语义提炼，但不得把Token、Fixture、本地QA配置或QA观察结果交给Agent。

#### Scenario: 本地Agent均不可用
- **WHEN** Codex和Claude Code都无法启动
- **THEN** 确定性扫描仍完成，需要Agent的知识目标显示明确阻塞且不生成伪造草稿

### Requirement: 知识经问题回答和人工确认后发布

系统 SHALL 让一个问题答案传播到全部受影响草稿，并仅在用户确认节点后写入Git知识真相和重建索引。

#### Scenario: 回答共享业务术语问题
- **WHEN** 用户回答一个影响多个入口的去重问题
- **THEN** 所有受影响草稿获得相同确认内容，已发布人工区域保持不变
