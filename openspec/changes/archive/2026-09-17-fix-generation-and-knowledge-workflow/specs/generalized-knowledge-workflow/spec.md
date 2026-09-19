## MODIFIED Requirements

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
