## ADDED Requirements

### Requirement: 控制台明确区分系统新增、编辑和切换

系统 SHALL 提供系统列表和当前系统选择器；新增与编辑使用不同状态，切换时清理旧系统临时 UI 状态并重新加载全部工作区数据。

#### Scenario: 从系统 A 切换到系统 B
- **WHEN** 用户在右上角选择系统 B
- **THEN** 页面清空 A 的扫描选择、知识草稿、资源抽屉和 Case 缓存，仅展示 B 的数据

### Requirement: 表单和操作提供一致可靠反馈

系统 SHALL 在前端和后端校验必填字段，短操作显示按钮 Spinner 和 Toast，冲突长任务使用全局排他门禁及全屏阶段 Loading，刷新后可恢复状态。

#### Scenario: 缺少必填 Token
- **WHEN** 用户提交 DSF 系统表单但未填写 Labrador QA Token
- **THEN** 页面定位 Token 字段，后端返回字段化错误，且不写系统或创建扫描任务

#### Scenario: 长任务运行中提交另一冲突任务
- **WHEN** 一个扫描或知识批量任务持有全局门禁
- **THEN** 页面锁定导航和按钮，直接 API 请求也被拒绝并返回当前任务摘要

### Requirement: 扫描目录按业务层次展示状态

系统 SHALL 默认折叠类别和类层级，Facade 叶子只显示方法名；父层折叠时展示状态统计，展开时状态归属叶子，并支持状态筛选和知识跳转。

#### Scenario: 查看 OrderFacade
- **WHEN** 用户展开 Facade 和 OrderFacade
- **THEN** 子项显示 `queryOrderCount` 而不是重复的 `OrderFacade#queryOrderCount`，并可跳转到对应知识目标

### Requirement: Curl 示例只在本地浏览器组合

系统 SHALL 从扫描接口后缀和本地网关前缀生成 Curl 结构，Token 只在浏览器组合；复制操作 SHALL 不访问 QA。

#### Scenario: 复制接口 Curl
- **WHEN** 用户选择一个已扫描 Facade 并点击复制
- **THEN** 剪贴板包含网关、接口后缀、Token 请求头和请求模板，但服务端日志、任务和报告不包含 Token
