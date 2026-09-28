# git-knowledge-store Specification

## Purpose
TBD - created by archiving change v2-foundation-and-knowledge-store. Update Purpose after archive.
## Requirements
### Requirement: Git文件作为知识真相源
配置共享MySQL时，系统 MUST 将系统定义、固定源码基线元数据、知识正文、人工说明、Case和工作流作为MySQL共享真相保存；源码本体仍由Git仓库保存，完整commit与受管tag表达源码基线。机器源码根、凭据、工具路径及静态规则 MUST 保留为本地配置。未配置共享MySQL的文件模式 SHALL 保留现有Git文件行为；迁移成功后不得同时以旧文件作为第二写入真相。

#### Scenario: 初始化单系统知识目录
- **WHEN** 注册首个系统
- **THEN** 系统创建本机Skill与配置容器，在已选择的存储模式保存系统共享身份
- **AND** MySQL模式仅在本地保存源码目录绑定，其他工作台不得沿用该绝对路径

#### Scenario: 读取另一工作台扫描
- **WHEN** 工作台读取共享库中已保存的固定扫描
- **THEN** 以system、scan、commit定位产物，源码引用保持相对路径
- **AND** 元数据读取不要求本机已有源码，实际读源码必须具备本机绑定并验证固定commit

### Requirement: 保护人工知识
系统更新知识文档时 MUST 只替换自动生成区域，并完整保留标记外的人工内容。MySQL模式 SHALL 在共享事务内读取并更新完整文档聚合，避免不同工作台覆盖已发布人工内容。

#### Scenario: 重新生成已人工补充文档
- **WHEN** 文档自动区域之外存在人工说明且系统重新生成该节点
- **THEN** 新文档包含更新后的自动区域和原样保留的人工说明

### Requirement: 单系统范围限制
知识节点和正文关系 MUST 保留所属system_id并拒绝跨系统错写。接口上下游 SHALL 使用独立的扫描接口关系表达；Case可按未满足输入选择并固定相关接口和扫描，不能借知识边绕过所属系统校验。

#### Scenario: 拒绝跨系统关系
- **WHEN** 调用方写入目标知识节点属于另一系统的正文关系
- **THEN** 系统返回范围错误且不写入该知识关系

#### Scenario: 冻结必要的跨系统操作
- **WHEN** 当前场景无法自行取得或构造入参并选择已证明相关的精确接口
- **THEN** Case保存该接口的所属系统、固定扫描和定义
- **AND** 后续重扫或目录补全不改变已发布Case

#### Scenario: 执行未保存精确选择列表的历史Case
- **WHEN** 历史Generation的固定来源范围没有selected_operation_ids
- **THEN** 执行视图仅从该Generation固定数据调用、观察函数及清理步骤恢复实际引用接口
- **AND** 不开放来源系统其他接口，也不改写Generation、来源扫描或原有预期

#### Scenario: 独立执行历史共享数据版本
- **WHEN** 已发布共享数据版本的来源范围尚未保存selected_operation_ids
- **THEN** 执行视图从该版本固定runtime_call恢复精确接口并使用原扫描
- **AND** 不读取后续契约修订、不开放来源系统其他接口且不改写已发布版本

