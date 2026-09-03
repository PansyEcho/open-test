# Design: Case工作台可信恢复

## Truth source

目录只从latest scan中存在且知识状态为GENERATED或CONFIRMED的Facade、Job和MQ入口构建。canonical Entry ID作为主键，旧Case身份只通过既有只读alias关联，不修改历史资产。

## Pipeline status

工作台按真实资产顺序计算入口状态：程序覆盖分析、Published Action、Setup、Cleanup、V3 Generation和Attempt。最早缺失阶段成为当前阻塞原因；不存在真实入口的名称不会出现在响应中。

## Compatibility

旧Case保持只读并继续返回统计和生成记录。V3 Scenario、Variant和Attempt继续使用现有存储读取。本变更不恢复旧写入口，也不调用QA。
