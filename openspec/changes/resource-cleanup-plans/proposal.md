# Change: 独立且可证明的资源回收计划

## Why

Case执行后的业务资源生命周期不能继续混在步骤文本里。退票单号等回收主键必须来自真实ActionFact，业务取消必须引用current Published能力；直接改库仅能使用服务端Git中已固定资源、表、列和业务键的恢复契约。

## What Changes

- 增加版本化`CleanupContractRuleSet`，精确归类业务取消Candidate，并固定Action/Setup身份来源、SQL表列白名单与Oracle期望。
- 新`CleanupPlan` 冻结Case compilation revision、Action profile、Action capability、ActionFact contract、Recipe和二元Published引用。
- 程序固定“业务取消优先”；只有current CLEANUP候选目录在当前规则下不存在匹配时才允许SQL主策略。
- 发布在consumer与全部provider的同一排序事务内重验current资产并写入不可变Git Plan。
- 提供规则、计划的提交/列表/详情API。本阶段不执行QA、SQL或隔离；第8阶段才消费ActionFact运行值并执行回收。
