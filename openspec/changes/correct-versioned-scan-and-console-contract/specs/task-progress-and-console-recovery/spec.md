## MODIFIED Requirements

### Requirement: 长任务报告可核查的真实进度

所有控制台长任务 SHALL 先保存统一业务任务，再报告阶段编码和名称、阶段序号、完成项、总项、当前处理对象、警告及更新时间。任务 SHALL 能按系统、操作、目标和状态查询，且问题、草稿和恢复 SHALL 不依赖Agent thread_id。

#### Scenario: 网页任务等待原生Agent

- **WHEN** 用户从网页发起知识或Case生成但尚未由原生Agent接手
- **THEN** 任务显示等待接手和包含task_id的继续指令
- **AND** 不显示正在生成，不创建第二个交互Agent

#### Scenario: 刷新或新会话恢复

- **WHEN** 页面刷新、服务重启、原会话丢失或任务没有thread_id
- **THEN** 待接手、待回答、待修复和失败任务仍可查询
- **AND** 新会话可读取同一任务的问题、答案、草稿和验证结果继续

#### Scenario: Agent输出但保存失败

- **WHEN** Agent已经提交内容但正式产物校验或保存失败
- **THEN** 页面显示待修复或失败并保留草稿
- **AND** 不把输出流结束或Agent声明完成当作业务成功
