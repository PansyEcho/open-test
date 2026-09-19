## MODIFIED Requirements

### Requirement: Case目录必须由latest scan全部真实触发入口生成

系统 SHALL 按 Facade、MQ、Job 层级列出latest scan中的全部真实入口，知识状态只作为附加信息，且目录请求不得逐入口执行Case preview。

#### Scenario: 入口尚无知识或Generation
- **WHEN** latest scan包含一个真实入口但尚无知识或Case
- **THEN** 目录仍显示该入口并以中性“未生成”状态展示

#### Scenario: 同入口正在生成
- **WHEN** current源码代际的Case任务已记录Agent turn成功启动，或服务端正在校验已提交草稿
- **THEN** 目录显示“生成中”和可核查业务步骤，不调用preview且不让历史阻塞Generation覆盖该进度

#### Scenario: Handoff等待但Agent未运行
- **WHEN** current源码代际只存在等待、需人工打开、阻塞或失败的Case handoff
- **THEN** 目录停止轮询并显示“待补充”或对应终态，不得长期显示“生成中”

#### Scenario: 用户查看Case生成进度
- **WHEN** Case生成尚未进入READY终态
- **THEN** 页面按实际状态展示“程序正在编译”“等待Codex补全”“Codex正在设计Recipe”“正在校验草稿”“正在重新生成”“已生成”或“待补充”，且区分真实数据准备、Case校验、目标试跑与回查；generate_only明确显示不执行业务

#### Scenario: 用户选择Case Codex兜底档位
- **WHEN** 用户打开Case工作台
- **THEN** 页面提供Luna·Low、Luna·Medium、Sol·Low、Sol·Medium，并说明“仅在程序无法完成Case生成时用于Codex补全”

#### Scenario: 活动Codex显示冻结档位
- **WHEN** current Entry存在等待、运行或校验中的Case handoff
- **THEN** 页面显示该handoff首次冻结的模型和推理档位，后续选择不得改写它

#### Scenario: 空线程等待桌面接管
- **WHEN** 持久Codex线程已经创建但桌面owner尚未打开它，后台首次启动返回manual required且线程没有turn
- **THEN** 页面保持“等待Codex补全”并提供“打开并继续 Codex 任务”；用户点击后打开同一线程并幂等请求首次turn，不得显示为业务待补充或创建第二线程

#### Scenario: 主视图隐藏内部错误码
- **WHEN** Generation或handoff进入Blocked、Failed或Needs Input
- **THEN** 主视图使用“待补充”等业务文案，原始错误码仅在默认折叠的技术详情中可查

#### Scenario: Codex turn结束但没有合法产物
- **WHEN** 已启动的Case Agent turn已completed或failed，但Handoff没有进入校验或READY
- **THEN** 页面分别转为“待补充”或“未完成”并停止轮询，不得继续显示“生成中”；completed允许用户在同一线程显式继续，且不得重复启动同一turn

#### Scenario: Codex CLI延迟启动失败可恢复
- **WHEN** Case-only CLI越过同步启动窗口后退出，且原持久线程仍未出现新turn
- **THEN** 系统收割该进程并把同一任务恢复为“等待Codex补全”，保留原handoff、thread和冻结档位；再次点击只重试同一线程，不得永久显示运行中或创建第二任务

#### Scenario: Case Agent使用独立typed工具
- **WHEN** Case Agent开始或继续一个`case-handoff-*`任务
- **THEN** 每个模型turn使用任务绑定的typed工具读取固定源码、检索与解析接口、修订草稿和发布；generate_and_verify可调用任务范围内非生产数据准备和业务验证工具，generate_only在服务端拒绝这些执行工具；工具不能选择其他任务身份或任意源码根
- **AND** Agent先读取冻结范围、current正式资产和服务器Draft Schema，再通过Case专用typed draft工具提交

