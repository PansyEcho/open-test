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
系统 SHALL 在首次扫描后自动生成并使用系统定位、核心主流程和责任边界，允许人工修改，不要求核心对象或人工确认门禁。已有背景 SHALL 不被自动覆盖；显式重新生成只替换所选范围。接口契约补充 SHALL 通过类型、字段路径、源码证据和冲突校验后发布到MySQL。

#### Scenario: 回答共享业务术语问题
- **WHEN** 用户回答一个影响多个入口的去重问题
- **THEN** 所有受影响草稿获得相同内容，已发布人工区域保持不变

#### Scenario: 初始与后续扫描
- **WHEN** 首次扫描完成或系统再次扫描
- **THEN** 缺失三项背景自动生成，已有内容保留，接口浏览和连接探测不依赖背景确认

### Requirement: 未知契约缺口的有限Agent补充
系统 SHALL 在程序扫描之后通过已有Agent任务和契约补充通道处理未来未知缺口，只读取相关固定源码和依赖；将触发原因、源码位置、补充结果和采纳结论写入现有MySQL任务记录。

#### Scenario: 补充失败或证据冲突
- **WHEN** 补充内容无法通过类型、字段路径、证据或冲突校验
- **THEN** 保持对应缺口并说明原因，不自动循环重试，也不阻断无关可靠目标

### Requirement: 背景生成必须消费固定源码证据
系统 SHALL 通过已有注册源码安全读取边界提供有界Java证据，依据实际内容归纳背景；Agent退出成功不等于已取得源码。生成期间的人工修改 SHALL 优先保留。本机Agent执行路径 SHALL 可配置，未单独选择Case模型时使用OpenTest已选模型。

#### Scenario: 无源码证据或Agent失败
- **WHEN** 背景生成无法取得固定Java证据或Agent执行失败
- **THEN** 保持已有背景，显示独立失败原因，不撤销已发布的可靠接口

#### Scenario: 生成期间人工修改
- **WHEN** Agent运行期间用户保存了同一背景字段
- **THEN** 保留用户的新内容，仅保存未发生并发修改的生成字段

#### Scenario: 背景源码的有界覆盖
- **WHEN** 背景生成选择入口及其已解析调用的源码证据
- **THEN** 调用范围最多扩展两层且不受调用边排列顺序影响；同一文件中相隔较远的已选方法分别提供片段，重叠片段不重复占用总计100,000字符的证据预算，空白源码不视为有效证据

