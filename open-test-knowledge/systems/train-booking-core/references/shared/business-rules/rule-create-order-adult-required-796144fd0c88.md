---
node_id: rule:create-order:adult-required
system_id: train-booking-core
kind: business_rule
title: 订单至少包含一名成人
summary: 当乘客总数等于儿童数时返回NoAdult；成人与儿童组合是可构造场景的关键约束。
aliases:
- 多乘客
- 儿童成人
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java
  symbol: CreateOrderServiceInvoker#check
  line: 295
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.535115Z'
---

<!-- kb:auto-start -->
## 业务结论

当乘客总数等于儿童数时返回NoAdult；成人与儿童组合是可构造场景的关键约束。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java:295 CreateOrderServiceInvoker#check`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
