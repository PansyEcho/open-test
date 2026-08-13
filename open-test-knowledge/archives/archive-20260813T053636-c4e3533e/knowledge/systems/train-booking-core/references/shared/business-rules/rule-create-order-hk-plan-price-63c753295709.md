---
node_id: rule:create-order:hk-plan-price
system_id: train-booking-core
kind: business_rule
title: 港铁计划港币价格来源
summary: 每名乘客优先查车次日期OD坐席报价；儿童查基础票价，非儿童再按卧铺与基础票价fallback，HK_PAYMENT可回退用户foreignTicketPrice。
aliases:
- 港币报价
- fillPlanForeignPrice
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java
  symbol: OrderBuilder#fillPlanForeignPrice
  line: 594
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.535678Z'
---

<!-- kb:auto-start -->
## 业务结论

每名乘客优先查车次日期OD坐席报价；儿童查基础票价，非儿童再按卧铺与基础票价fallback，HK_PAYMENT可回退用户foreignTicketPrice。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java:594 OrderBuilder#fillPlanForeignPrice`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
