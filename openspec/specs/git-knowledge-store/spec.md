# git-knowledge-store Specification

## Purpose
TBD - created by archiving change v2-foundation-and-knowledge-store. Update Purpose after archive.
## Requirements
### Requirement: Git文件作为知识真相源
系统 MUST 将系统定义、源码基线和知识正文保存为Git可追踪的YAML与Markdown文件，SQLite不得保存独有业务知识。

#### Scenario: 初始化单系统知识目录
- **WHEN** 注册首个系统
- **THEN** 系统创建根Skill、系统Skill、源码元数据、references、cases和questions目录

### Requirement: 保护人工知识
系统更新知识文档时 MUST 只替换自动生成区域，并完整保留标记外的人工内容。

#### Scenario: 重新生成已人工补充文档
- **WHEN** 文档自动区域之外存在人工说明且系统重新生成该节点
- **THEN** 新文档包含更新后的自动区域和原样保留的人工说明

### Requirement: 单系统范围限制
一期知识仓库 MUST 允许节点保留 `system_id`，但必须拒绝创建目标系统不同的知识关系或Case。

#### Scenario: 拒绝跨系统关系
- **WHEN** 调用方写入目标节点属于另一系统的关系
- **THEN** 系统返回范围错误且不写入关系

