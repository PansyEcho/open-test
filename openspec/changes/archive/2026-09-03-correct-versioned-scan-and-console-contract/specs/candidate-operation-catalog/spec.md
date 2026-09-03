## REMOVED Requirements

### Requirement: 本阶段能力发布必须失败关闭

**Reason:** Published能力阶段已经完成并具有独立正式规格；Candidate阶段的临时失败关闭会与当前已交付发布流程直接冲突。

**Migration:** Candidate仍保持只读且不能被Recipe或执行器直接引用；能力发布改由`published-operation-capabilities`的正式约束控制。

### Requirement: 后续阶段写入口必须失败关闭

**Reason:** Setup、Fault、Cleanup和V3阶段已经完成并分别具有正式规格；继续返回`NOT_REBUILT`不再代表当前产品行为。

**Migration:** 各写入口由对应正式资产、源码代际、权限和执行门禁验证，旧资产继续按其独立兼容规则只读或执行。
