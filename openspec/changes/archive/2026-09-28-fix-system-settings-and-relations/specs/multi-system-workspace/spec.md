## MODIFIED Requirements

### Requirement: 同一知识仓库支持多个彼此隔离的系统

系统 SHALL 允许注册、更新和读取多个系统，并按稳定系统 ID 隔离知识、扫描、Candidate、Published、Case、资源与报告；系统 SHALL 仅允许通过显式`SystemDependencyBinding`建立consumer到provider的直接只读Candidate发现关系，且不得由此反向、传递、执行或通过consumer路由写入provider注册表。

#### Scenario: 更新一个系统

- **WHEN** 用户编辑已注册系统的名称或资源环境
- **THEN** 只更新对应ID的配置，其他系统定义和资产保持不变，不触发扫描
- **AND** 普通更新拒绝修改源码路径，代码基准只能通过显式基线更新动作切换

#### Scenario: 新增系统

- **WHEN** 用户处于新增模式并提交另一个有效源码目录
- **THEN** 系统创建基于目录名的独立ID，而不是覆盖当前系统

#### Scenario: 建立直接Candidate发现关系

- **WHEN** 活动consumer绑定另一个活动provider并声明UPSTREAM或DOWNSTREAM角色和用途
- **THEN** consumer可搜索provider只读Candidate，但不能由此发布、引用或执行provider能力

#### Scenario: 尝试传递或反向发现

- **WHEN** A绑定B且B绑定C，或B未绑定A
- **THEN** A不能搜索C，B也不能仅因A到B的绑定搜索A

#### Scenario: consumer发现provider Candidate后发布

- **WHEN** consumer通过直接绑定搜索到provider Candidate
- **THEN** consumer路由不得发布该Candidate，调用方必须使用provider系统路由并只写provider的Published注册表
