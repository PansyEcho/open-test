# v2-console Specification

## Purpose
TBD - created by archiving change v2-api-and-console-cutover. Update Purpose after archive.
## Requirements
### Requirement: V2控制台只使用V2 API

控制台 SHALL 通过 `/api/v2` 展示和操作单系统扫描、知识、场景、Snapshot与运行，不调用legacy `/api/projects` 等路由。

#### Scenario: 编译自然语言场景
- **WHEN** 用户在控制台输入港币多乘客请求
- **THEN** 页面展示结构化约束、missing_conditions或独立变体，不在浏览器中猜测QA数据

#### Scenario: 查看运行失败
- **WHEN** 真实工具、断言、Oracle或清理失败
- **THEN** 页面展示步骤状态、简洁错误和结构化diff，不显示QA密钥

