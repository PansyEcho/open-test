# multi-system-workspace Specification

## Purpose
TBD - created by archiving change multi-system-console-reliability-and-reset. Update Purpose after archive.
## Requirements
### Requirement: 同一知识仓库支持多个彼此隔离的系统

系统 SHALL 允许注册、更新和读取多个系统，并按稳定系统 ID 隔离知识、扫描、Candidate、Published、Case、资源与报告；系统 SHALL 仅允许通过显式`SystemDependencyBinding`建立consumer到provider的直接只读Candidate发现关系，且不得由此反向、传递、执行或通过consumer路由写入provider注册表。

#### Scenario: 更新一个系统

- **WHEN** 用户编辑已注册系统的名称或源码路径
- **THEN** 注册表只替换对应ID的记录，其他系统定义和资产保持不变
- **AND** 源码路径变化后该系统的Candidate范围阻塞到新扫描完成

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

### Requirement: 混合系统数据可验证归档并恢复

系统 SHALL 在活动系统移除前生成包含文件大小和 SHA-256 的归档清单并验证全部资产；归档失败 SHALL 回滚，成功归档 SHALL 可恢复且重建派生索引。

#### Scenario: 归档当前混合数据
- **WHEN** 管理员以“源码路径错误且资产归属混合”为原因归档 `train-booking-core`
- **THEN** 可提交资产与本地资产分别进入对应归档根目录，活动注册表为空且任何文件都未被永久删除

#### Scenario: 恢复归档系统
- **WHEN** 归档摘要有效且活动区不存在目标冲突
- **THEN** 系统恢复原资产、注册定义和本地权限，并重建 SQLite 索引

