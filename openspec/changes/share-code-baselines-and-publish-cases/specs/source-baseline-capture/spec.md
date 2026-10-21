## MODIFIED Requirements

### Requirement: 扫描绑定可核查源码基线
系统 SHALL 在新建基准前将 branch、tag、commit 或默认 HEAD 解析为完整 commit，将对应 Git 快照的实际源码保存到对象存储，再只读取该固定材料扫描。请求 revision 仅作来源提示，不证明实际分支归属；working tree 未提交内容不进入基准。非 Git 内容仅允许历史迁移，不作为新共享基准。

#### Scenario: 选择 Git revision 扫描
- **WHEN** 用户选择可解析为 commit 的 revision
- **THEN** 保存完整 commit 和首次创建来源，并从相同源码对象扫描和读取后续知识

#### Scenario: 本机代码发生变化
- **WHEN** 注册仓库修改 working tree、切换分支或移动 tag
- **THEN** 已冻结基准继续读取原 commit 的材料，不随本机目录变化

#### Scenario: revision 或源码不可用
- **WHEN** revision 不合法、不是 commit、源码包缺失或仅有非 Git 新目录
- **THEN** 明确拒绝依赖该材料的操作，不使用另一版本回退

### Requirement: Scan history exposes the revision used by knowledge and Cases
The system SHALL retain each scan's full commit, original revision, analyzer version and capture time, and SHALL bind every knowledge bundle and Case to its exact scan internally. The public selector SHALL select code baselines rather than exposing scan revisions as separate Case workspaces.

#### Scenario: 同 commit 重新扫描
- **WHEN** 员工重新扫描已有 commit
- **THEN** 保存新的内部扫描及个人草稿，不改写已有 Case，只有发布才更新该基准的共享接口指针

#### Scenario: Case uses more than one source system
- **WHEN** a handoff reads target and authorized provider systems
- **THEN** it retains each fixed source scan and baseline without exposing local roots or changing frozen source after another user publishes
