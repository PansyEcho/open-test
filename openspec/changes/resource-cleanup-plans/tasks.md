# Tasks

## 1. Contract

- [x] 1.1 增加版本化Cleanup Contract、精确取消Candidate分类和SQL/字段白名单
- [x] 1.2 增加统一业务身份引用、Action/Setup Fact来源和类型化取消输入
- [x] 1.3 增加冻结Case compilation/ActionFact证明、二元Published/Recipe引用和不可变CleanupPlan V2

## 2. Validation and storage

- [x] 2.1 实现Cleanup Contract current/历史Git Store与严格SQL contract校验
- [x] 2.2 在多系统事务内重验Action profile、ActionFact、Recipe步骤current Published和SETUP/CLEANUP直接依赖
- [x] 2.3 校验业务取消精确Candidate分类、Published输入Schema与业务取消优先顺序
- [x] 2.4 校验同一身份的参数化UPDATE、SELECT Oracle、受控期望和隔离策略
- [x] 2.5 在同一事务写入不可变Plan，开放规则及Plan发布/列表/详情API

## 3. Verification

- [x] 3.1 增加业务取消优先、ActionFact主键、跨系统依赖与未发布Candidate反例
- [x] 3.2 增加表列越界、非首个WHERE业务键、OR/多语句和Oracle反例
- [x] 3.3 在正式Refund知识副本中验证缺Published/Recipe时BLOCKED且零Plan
- [x] 3.4 运行本变更模型/契约测试、OpenSpec strict和完整差异复核
- [x] 3.5 使用OCR delegation和同一只读Agent复核实现及测试证据
