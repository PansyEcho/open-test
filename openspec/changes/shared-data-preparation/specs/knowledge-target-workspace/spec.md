## MODIFIED Requirements

### Requirement: 知识目录与目标工作区一致

控制台 SHALL 使用与扫描结果相同的分类、类/业务域和叶子层级组织知识目标。用户选择叶子后 SHALL 加载该目标的知识工作区，不得自动启动Agent。

#### Scenario: 选择退款Facade方法

- **WHEN** 用户在`Facade → RefundDistributionFacade → queryList`点击方法
- **THEN** 主编辑区展示面包屑、源码证据、接口用途和契约以及已存在的历史正文；相关任务通过当前对象入口打开
- **AND** 叶子名称不重复显示Facade类名
- **AND** 没有内部知识长文的真实入口仍可补充契约、生成Case和准备数据，普通公共函数不再提供长文生成动作
