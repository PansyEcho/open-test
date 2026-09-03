# Change: 候选操作目录

## Why

现有操作目录在源码发现阶段直接推导可执行能力，无法表达“AI先搜索全部源码方法，再选择少量方法提交发布草稿”的边界。发现面与执行面必须拆开，避免绑定源码即扩大QA可执行面。

## What Changes

- 从最新源码扫描建立只读`CandidateOperationCatalog`。
- 候选记录方法签名、DTO、调用方、注释、provider与配置线索、读写线索和源码基线。
- 增加显式`SystemDependencyBinding`，仅允许consumer搜索自身及直接绑定provider的Candidate；每个系统仍独立注册、扫描和校验基线。
- 仅扫描`src/main/java`生产源码，使用全局与系统Git中的结构化MQ框架规则和精确FQN识别直接继承/实现关系及具体类直接声明的真实处理方法；测试、生成源码、同简单名类型、嵌套类和文本伪方法均不得成为Entry。
- 提供候选搜索和详情API；Candidate契约固定不可执行。
- 本变更不提交能力草稿、不发布能力、不访问QA；对应阶段完成前能力、Setup、Fault、Cleanup和V3执行写入口全部失败关闭，只保留旧资产只读展示。
