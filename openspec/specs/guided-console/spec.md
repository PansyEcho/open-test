# guided-console Specification

## Purpose
TBD - created by archiving change v2-guided-console-and-system-onboarding. Update Purpose after archive.
## Requirements
### Requirement: 控制台按工作流分区

控制台 SHALL 使用九个左侧一级导航承载系统接入、扫描、资源、知识、Case、执行、自然语言和报告，不把全部功能堆在同一页面。

#### Scenario: 切换导航
- **WHEN** 用户选择任一一级目录
- **THEN** 页面只显示对应工作区并保留当前系统上下文

### Requirement: 操作按钮提供可访问帮助

每个操作按钮 SHALL 配套可聚焦问号入口和`role=tooltip`说明用途、前置条件、QA访问、产物与常见阻塞。

#### Scenario: 键盘查看按钮帮助
- **WHEN** 用户聚焦问号入口
- **THEN** 对应tooltip可见且屏幕阅读器能关联其文本

