# knowledge-draft-and-confirmation Specification

## Purpose
TBD - created by archiving change knowledge-generation-and-indexing. Update Purpose after archive.
## Requirements
### Requirement: 自动知识与人工确认安全迭代

系统 SHALL 将自动内容与人工内容分区，批量保存高影响问题，并在确认时保留问题、答案和受影响节点。

#### Scenario: 重复生成知识
- **WHEN** 同一入口在新扫描上重新生成
- **THEN** 自动区域更新且人工补充与历史回答保持不变

#### Scenario: 回答问题
- **WHEN** 用户提交问题答案
- **THEN** 问题状态变为answered，答案写入Git知识文件，相关结论可标记为user_confirmed

### Requirement: 发布后可关系检索

系统 SHALL 在知识文件发布后重建SQLite，使入口ID、代码符号、中文术语和一跳关系均可查询。

#### Scenario: 查询港币规则
- **WHEN** 用户搜索 `港币支付` 或从createOrder入口展开关系
- **THEN** 返回带源码证据的港币报价业务规则节点

### Requirement: 入口Fact候选必须逐条确认并与正式知识隔离

系统 SHALL 把AI入口Fact保存在独立候选集合，仅在用户选择确切断言ID且程序校验全部证据和契约后提升为 `USER_CONFIRMED`。

#### Scenario: 确认单条候选
- **WHEN** 同一知识草稿包含多条入口Fact候选且用户只确认一条
- **THEN** 系统只发布被选断言，其余候选继续保持隔离

#### Scenario: 节点整体确认
- **WHEN** 用户确认知识节点正文
- **THEN** 系统不得连带发布该节点中的AI入口Fact候选

#### Scenario: 自动发布可浏览知识草稿
- **WHEN** 系统自动发布CODE_VERIFIED或INFERRED知识正文且草稿仍包含typed AI候选
- **THEN** 正式节点不获得这些候选，候选继续保留在待确认集合

#### Scenario: 候选源码代际已过期
- **WHEN** 用户确认的候选不再属于latest scan及其精确baseline，或源码证据无法重新读取验证
- **THEN** 系统拒绝发布该断言且不影响同草稿其他候选

#### Scenario: 程序证明的逐断言版本替换
- **WHEN** 用户选择精确候选、精确旧断言ID并要求代码证明后迁移Fact契约版本
- **THEN** 系统复用自动发布的程序证明门禁，只有全部选择候选闭合时才原子替换同语义旧断言，且不把来源降为用户猜测

