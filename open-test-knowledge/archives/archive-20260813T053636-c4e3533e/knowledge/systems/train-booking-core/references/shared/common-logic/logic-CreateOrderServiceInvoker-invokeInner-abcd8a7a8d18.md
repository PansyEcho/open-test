---
node_id: logic:CreateOrderServiceInvoker#invokeInner
system_id: train-booking-core
kind: common_logic
title: 创建订单业务编排
summary: 检查乘客与发车时间，防重复，下单构建并持久化，按联程/港铁/临近发车/分单结果驱动状态。
aliases:
- CreateOrderServiceInvoker
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java
  symbol: CreateOrderServiceInvoker#invokeInner
  line: 131
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.534931Z'
---

<!-- kb:auto-start -->
## 业务结论

检查乘客与发车时间，防重复，下单构建并持久化，按联程/港铁/临近发车/分单结果驱动状态。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java:131 CreateOrderServiceInvoker#invokeInner`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
