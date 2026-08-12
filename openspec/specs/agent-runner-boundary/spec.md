# agent-runner-boundary Specification

## Purpose
TBD - created by archiving change knowledge-generation-and-indexing. Update Purpose after archive.
## Requirements
### Requirement: 本地Agent运行遵循最小权限

系统 SHALL 只允许配置的Codex或Claude命令，在注册源码根内以只读意图运行，使用环境白名单、截止时间和独立输出文件。

#### Scenario: Agent成功输出候选知识
- **WHEN** 用户显式启用本地Agent增强
- **THEN** 原始提示、输出、退出码和耗时保存在本地任务证据中，候选知识默认inferred

#### Scenario: 命令不在允许列表
- **WHEN** 配置其他可执行程序或输出越过本地任务目录
- **THEN** Runner在启动进程前拒绝请求

