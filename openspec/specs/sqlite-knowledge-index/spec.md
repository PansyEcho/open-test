# sqlite-knowledge-index Specification

## Purpose
TBD - created by archiving change v2-foundation-and-knowledge-store. Update Purpose after archive.
## Requirements
### Requirement: 可重建SQLite索引
系统 MUST 能够仅根据Git知识文件重建SQLite节点、关系、别名、源码引用和全文索引。

#### Scenario: 删除索引后重建
- **WHEN** 本地索引文件被删除并执行重建
- **THEN** 精确查询、全文查询和关系查询返回与删除前等价的结果

### Requirement: 原子发布索引
索引重建失败时系统 MUST 保留原有可用索引，成功后才能替换正式索引文件。

#### Scenario: 无效知识文件导致重建失败
- **WHEN** 重建过程中遇到无法通过模型校验的知识文件
- **THEN** 系统报告具体文件错误且原索引仍可查询

### Requirement: 无向量依赖
一期索引 MUST 只使用SQLite内置能力，不得要求embedding模型或向量数据库。

#### Scenario: 离线构建索引
- **WHEN** 环境无网络且没有embedding服务
- **THEN** 系统仍可完成知识索引重建和查询

