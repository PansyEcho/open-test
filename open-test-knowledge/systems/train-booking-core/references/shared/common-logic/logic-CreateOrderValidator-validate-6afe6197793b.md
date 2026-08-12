---
node_id: logic:CreateOrderValidator#validate
system_id: train-booking-core
kind: common_logic
title: 创建订单入参校验
summary: 校验联系人、订单、乘客非空与乘客ID唯一，并约束查询单、占座联程、指定车厢和connectType。
aliases:
- CreateOrderValidator
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/travel/train/supplychain/bookingcore/facade/validator/trade/CreateOrderValidator.java
  symbol: CreateOrderValidator#validate
  line: 32
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.534746Z'
---

<!-- kb:auto-start -->
## 业务结论

校验联系人、订单、乘客非空与乘客ID唯一，并约束查询单、占座联程、指定车厢和connectType。

## 源码证据

- `app/facade-impl/src/main/java/com/ly/travel/train/supplychain/bookingcore/facade/validator/trade/CreateOrderValidator.java:32 CreateOrderValidator#validate`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
