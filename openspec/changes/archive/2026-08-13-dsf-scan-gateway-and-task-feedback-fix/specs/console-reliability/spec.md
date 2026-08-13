## ADDED Requirements

### Requirement: 长任务终态与成功反馈一致

控制台 SHALL 只在后台任务完成且其后置业务数据成功加载时展示操作成功。后台任务失败或中断时 SHALL 立即停止依赖该任务产物的请求，并展示一次明确失败反馈。

#### Scenario: 扫描任务失败

- **WHEN** scriptgen扫描任务以failed或interrupted结束
- **THEN** 控制台不读取latest扫描Manifest
- **AND** 不显示系统扫描成功或目录刷新成功
- **AND** 展示任务的稳定失败原因

#### Scenario: 扫描任务成功但目录读取失败

- **WHEN** 后台扫描完成但扫描目录无法读取
- **THEN** 控制台不显示最终成功提示
- **AND** 保留目录读取失败信息供用户修复
