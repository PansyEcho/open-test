## ADDED Requirements

### Requirement: 执行绑定完整版本Snapshot

系统 SHALL 在运行前保存并引用包含源码、知识、Case、工具和Skill版本的不可变Snapshot。

#### Scenario: 相同输入重复创建Snapshot
- **WHEN** 所有版本和文件摘要未变化
- **THEN** 返回相同稳定snapshot_id

#### Scenario: Case或知识发生变化
- **WHEN** 任一受绑定资产摘要变化
- **THEN** 新Snapshot使用不同snapshot_id，旧运行仍可追溯旧摘要

#### Scenario: 生命周期Case属于其他源码扫描
- **WHEN** 非STALE的custom Case或业务Suite声明的source_scan_id与Snapshot工具扫描不同
- **THEN** 系统拒绝创建混合版本Snapshot，即使Case当前因Fixture不足而BLOCKED
