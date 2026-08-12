# v2-api Specification

## Purpose
TBD - created by archiving change v2-api-and-console-cutover. Update Purpose after archive.
## Requirements
### Requirement: API覆盖单系统闭环

FastAPI SHALL 提供系统注册、扫描、知识生成与确认、Case生成与编辑、自然语言编译、Snapshot、执行任务和报告查询接口。

#### Scenario: 从扫描到执行
- **WHEN** 调用方依次提交扫描、生成知识、生成Case、创建Snapshot和执行变体
- **THEN** 所有长操作返回task_id，查询结果保持system_id、scan_id、snapshot_id和run_id追溯链

### Requirement: API错误不泄露内部状态

系统 SHALL 将领域错误映射为结构化HTTP响应，且不返回堆栈、密钥或未脱敏命令参数。

#### Scenario: 查询不存在的运行
- **WHEN** 调用方读取未知run_id
- **THEN** 返回404与not_found错误，不包含Python traceback

