# scriptgen-source-scan Specification

## Purpose
TBD - created by archiving change single-system-source-analysis. Update Purpose after archive.
## Requirements
### Requirement: 真实scriptgen是可执行工具唯一来源

系统 SHALL 调用配置的真实scriptgen并只根据其tool manifest建立逻辑工具，不得添加固定离线shim。

#### Scenario: 成功扫描Facade和Job
- **WHEN** scriptgen返回有效scan manifest与tool manifest
- **THEN** 每个入口保留请求响应类型、源码位置和source_id，每个工具保留逻辑ID与生成脚本路径

#### Scenario: scriptgen不可用
- **WHEN** 配置路径不存在、命令失败或manifest无效
- **THEN** 扫描任务失败并给出精简诊断，不生成伪造工具

#### Scenario: 入口与工具数量核对
- **WHEN** 扫描完成
- **THEN** 结构化结果的工具集合与scriptgen generated_tools一一对应且不包含 `platform/*`

