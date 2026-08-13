# task-progress-and-console-recovery Specification

## Purpose
TBD - created by archiving change system-specific-knowledge-discovery-and-task-progress. Update Purpose after archive.
## Requirements
### Requirement: 长任务报告可核查的真实进度

所有控制台长任务 SHALL 使用统一进度契约报告阶段编码和名称、阶段序号、完成项、总项、当前处理对象、警告及更新时间。未知总量不得伪造百分比。

#### Scenario: 批量知识生成

- **WHEN** 系统依次生成多个知识目标
- **THEN** 页面展示当前目标、当前阶段和真实`n/total`
- **AND** 刷新页面后从活动任务恢复相同进度并继续轮询

#### Scenario: 扫描后的问题发现失败

- **WHEN** Manifest已发布但Agent问题发现失败
- **THEN** 扫描任务完成并携带安全警告和重试提示
- **AND** 页面不把整个系统注册显示为失败

#### Scenario: 未知任务总量

- **WHEN** 当前阶段无法预先确定总项数
- **THEN** 页面显示阶段Spinner和当前处理对象
- **AND** 不显示推测百分比

### Requirement: 侧边栏控制位于左侧

控制台 SHALL 在展开时把收起按钮放在左侧栏顶部，在收起时把恢复按钮固定在页面左上角，并保留键盘焦点、无障碍标签、本地状态和移动端适配。

#### Scenario: 收起并恢复导航

- **WHEN** 用户在桌面端或移动端收起左侧导航后刷新页面并再次恢复
- **THEN** 收起状态在本地恢复且两个控制按钮始终位于页面左侧
- **AND** 按钮可以通过键盘聚焦并具有明确的`aria-label`

