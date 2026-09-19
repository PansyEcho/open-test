# generalized-knowledge-workflow Specification

## Purpose
TBD - created by archiving change generalized-knowledge-case-and-natural-language-workflow. Update Purpose after archive.
## Requirements
### Requirement: 所有知识目标使用同一深层业务追踪契约
系统 SHALL 将接口知识收敛为用途和请求响应字段契约；内部实现仅在Case或契约补充需要时按固定源码追踪，不要求生成公共逻辑或状态机自然语言文档。

#### Scenario: 生成非createOrder Facade知识
- **WHEN** 用户补充任一Facade接口契约
- **THEN** 保存有证据的接口用途与字段说明、约束，不强制生成完整内部流程长文

#### Scenario: 追踪事件副作用
- **WHEN** Case预期需要判断事件处理结果
- **THEN** Agent可以按需读取固定源码的事件与Listener逻辑，生成有证据的预期

#### Scenario: 抽取共享公共逻辑
- **WHEN** 多个入口使用同一内部业务方法
- **THEN** Case按需复用源码分析，不为知识主目录强制建立共享逻辑文档

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

