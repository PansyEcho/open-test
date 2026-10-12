## MODIFIED Requirements

### Requirement: 表单和操作提供一致可靠反馈

系统 SHALL 在前端和后端校验必填字段，短操作显示按钮 Spinner 和 Toast，冲突长任务使用全局排他门禁及全屏阶段 Loading，刷新后可恢复状态。启动长任务在占用门禁后、运行记录提交前失败时 SHALL 释放门禁并返回原失败。

#### Scenario: 缺少必填 Token
- **WHEN** 用户提交 DSF 系统表单但未填写 Labrador QA Token
- **THEN** 页面定位 Token 字段，后端返回字段化错误，且不写系统或创建扫描任务

#### Scenario: 长任务运行中提交另一冲突任务
- **WHEN** 一个扫描或知识批量任务持有全局门禁
- **THEN** 页面锁定导航和按钮，直接 API 请求也被拒绝并返回当前任务摘要

#### Scenario: 网页运行记录保存失败
- **WHEN** 网页Agent运行已占用全局门禁，但RUNNING记录保存或事务提交失败
- **THEN** 请求返回原失败，任务不保留运行标记，门禁被释放，后续长任务不会被误报为另一个任务正在运行
