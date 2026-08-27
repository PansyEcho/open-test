# Change: 分型Case覆盖义务与可插拔规则

## Why

当前Case生成使用四类粗粒度CoverageTarget，并依赖知识测试点或专用代码补场景。循环故障、顺序门控和副作用观察因此容易被误当作普通字段组合，也需要反复修改提示词补覆盖。

## What Changes

- 将覆盖要求拆为Factor、Boundary、Decision、Sequence、FaultInjection、Effect和Requirement七类义务。
- Java语义分析器只输出可复核的控制流、数据来源、调用和副作用源码证据；程序将其编译为独立、scan绑定的`ProgramCaseAnalysisCatalog`，不再信任`Entry.metadata.case_analysis`。
- 定义版本化`CaseSemanticDraft`和完整性校验，但本阶段不调用AI；所有未决语义缺口保持BLOCKED。
- 增加全局内置与系统Git两层结构化Case规则，不做领域向量匹配。
- 不同规则默认累加，同ID系统规则覆盖全局版本，互斥要求失败关闭。
- 扫描以manifest和分析目录组成的单一bundle原子发布；旧scan缺少分析目录时显式阻塞。
- 提供只读规则预览和冻结覆盖清单；客户端不能提交完整冻结清单，旧编译/生成入口在服务端清单加载重做前失败关闭。本变更不调用AI、不生成Case、不访问QA。
