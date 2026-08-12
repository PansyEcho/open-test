## ADDED Requirements

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
