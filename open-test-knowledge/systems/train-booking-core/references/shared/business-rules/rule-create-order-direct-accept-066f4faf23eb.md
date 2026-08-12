---
node_id: rule:create-order:direct-accept
system_id: train-booking-core
kind: business_rule
title: 联程或港铁订单直接收单
summary: 联程、港铁、临近发车或身份拦截命中时不走同步分单，直接设置TICKETING/OCCUPYING后返回成功。
aliases:
- 港铁直接收单
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java
  symbol: CreateOrderServiceInvoker#invokeInner
  line: 155
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.535275Z'
---

<!-- kb:auto-start -->
## 业务结论

联程、港铁、临近发车或身份拦截命中时不走同步分单，直接设置TICKETING/OCCUPYING后返回成功。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java:155 CreateOrderServiceInvoker#invokeInner`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
