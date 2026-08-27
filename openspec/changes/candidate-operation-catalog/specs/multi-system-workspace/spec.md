# multi-system-workspace Specification

## MODIFIED Requirements

### Requirement: 同一知识仓库支持多个彼此隔离的系统

系统 SHALL 允许注册、更新和读取多个系统，并按稳定系统ID隔离知识、扫描、Case、资源与报告；系统 SHALL 仅允许通过显式`SystemDependencyBinding`建立consumer到provider的直接只读候选发现关系，其他跨系统关系和引用仍 SHALL 被拒绝。

#### Scenario: 更新一个系统

- **WHEN** 用户编辑已注册系统的名称或源码路径
- **THEN** 注册表只替换对应ID的记录，其他系统定义和资产保持不变；源码路径变化后该系统的候选范围阻塞到新扫描完成

#### Scenario: 新增系统

- **WHEN** 用户处于新增模式并提交另一个有效源码目录
- **THEN** 系统创建基于目录名的独立ID，而不是覆盖当前系统

#### Scenario: 建立直接候选发现关系

- **WHEN** 活动consumer绑定另一个活动provider并声明UPSTREAM/DOWNSTREAM角色和用途
- **THEN** consumer可搜索provider只读Candidate，但不能由此发布、引用或执行provider能力

#### Scenario: 尝试传递或反向发现

- **WHEN** A绑定B且B绑定C，或B未绑定A
- **THEN** A不能搜索C，B也不能仅因A到B的绑定搜索A
