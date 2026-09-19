## MODIFIED Requirements

### Requirement: 单系统范围限制
一期知识仓库 MUST 允许节点保留 `system_id`，但必须拒绝越过当前系统范围写入另一个系统的知识节点或注册表；Case的数据步骤可通过显式直接关联与独立执行授权调用provider Operation。

#### Scenario: 拒绝跨系统关系
- **WHEN** 调用方未通过系统绑定和所属资产路由而直接写入另一系统的知识关系
- **THEN** 系统返回范围错误且不写入关系
