# knowledge-target-workspace Specification

## Purpose
TBD - created by archiving change system-specific-knowledge-discovery-and-task-progress. Update Purpose after archive.
## Requirements
### Requirement: 知识目录与目标工作区一致

控制台 SHALL 使用与扫描结果相同的分类、类/业务域和叶子层级组织知识目标。用户选择叶子后 SHALL 加载该目标的知识工作区，不得自动启动Agent。

#### Scenario: 选择退款Facade方法

- **WHEN** 用户在`Facade → RefundDistributionFacade → queryList`点击方法
- **THEN** 主编辑区展示面包屑、知识状态、源码证据、最新草稿、已发布正文、关联问题和目标反馈输入
- **AND** 叶子名称不重复显示Facade类名
- **AND** 未生成目标只显示详情和可执行操作

### Requirement: 系统背景采用叙述与候选确认

控制台 SHALL 让用户自由描述系统用途和上游系统与入口关系；下游应用和业务术语 SHALL 来自代码发现候选并支持确认、忽略、合并和手工补充。

#### Scenario: 普通系统编辑背景

- **WHEN** 用户打开非Booking.Core系统的知识页面
- **THEN** 页面不显示主要下游、分单系统关系或固定EBK/票机/收单/HT字段
- **AND** 展示当前系统自己的术语和外部应用候选及源码证据

