# sqlite-knowledge-index Specification

## Purpose
TBD - created by archiving change v2-foundation-and-knowledge-store. Update Purpose after archive.
## Requirements
### Requirement: 可重建SQLite索引
文件模式下系统 MUST 能够根据Git知识文件重建SQLite节点、关系、别名、源码引用和全文索引。共享MySQL模式 SHALL 直接查询共享知识与接口索引，SQLite不得成为跨工作台业务真相或每次启动必须同步的第二目录。

#### Scenario: 删除索引后重建
- **WHEN** 文件模式本地索引被删除并执行重建
- **THEN** 精确查询、全文查询和关系查询返回与删除前等价的结果

#### Scenario: 另一工作台发布知识
- **WHEN** MySQL模式另一工作台发布节点或接口契约
- **THEN** 当前工作台通过共享目录版本读取新结果，无需同步Git知识文件或重建SQLite

### Requirement: 原子发布索引
文件索引重建失败时系统 MUST 保留原有可用索引。MySQL扫描发布 SHALL 先准备不可变产物、接口契约与覆盖，再在短事务内更新当前接口关系、完整扫描指针及目录版本；失败不得暴露部分当前代际。

#### Scenario: 无效知识文件导致重建失败
- **WHEN** 文件模式重建遇到无法通过模型校验的知识文件
- **THEN** 系统报告具体错误且原索引仍可查询

#### Scenario: 同时发布有关联系统
- **WHEN** 两个工作台同时发布系统A与B的扫描
- **THEN** 发布按稳定系统锁顺序读取提交后的当前接口目录并匹配双方关系
- **AND** 耗时扫描、AI分析和大对象上传不持有发布锁

### Requirement: 无向量依赖
系统 MUST 使用已选择存储的常规索引与查询能力，不得要求embedding模型或向量数据库。

#### Scenario: 离线构建索引
- **WHEN** 文件模式无网络且没有embedding服务
- **THEN** 系统仍可完成知识索引重建和查询

#### Scenario: 共享模式读取失败
- **WHEN** MySQL模式无法读取共享元数据
- **THEN** 系统明确报告不可用，不回退到陈旧本地知识作为当前真相

