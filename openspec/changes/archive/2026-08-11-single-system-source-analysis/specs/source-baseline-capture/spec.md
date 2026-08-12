## ADDED Requirements

### Requirement: 扫描绑定可核查源码基线

系统 SHALL 在扫描前记录源码绝对路径、当前分支、commit、dirty状态、dirty摘要、分析器版本和捕获时间。

#### Scenario: 干净Git工作区
- **WHEN** 用户扫描一个无未提交改动的已注册源码仓库
- **THEN** 基线包含branch和commit，dirty为false且dirty摘要为空

#### Scenario: 含未提交改动
- **WHEN** 已跟踪或未跟踪源码相对当前commit发生变化
- **THEN** dirty为true并生成不泄露源码正文的稳定摘要

#### Scenario: 非Git源码目录
- **WHEN** 注册目录不是Git工作区
- **THEN** 系统保留源码路径并以空commit、空branch和目录内容摘要建立显式基线
