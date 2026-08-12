---
node_id: facade:TradeFacade#createOrder
system_id: train-booking-core
kind: facade
title: 创建订单入口
summary: 接收CreateOrderRequest，经统一代理执行校验与CREATE_ORDER业务Invoker。
aliases:
- com.ly.travel.train.supplychain.bookingcore.facade.TradeFacade#createOrder
- createOrder
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/travel/train/supplychain/bookingcore/facade/impl/TradeFacadeImpl.java
  symbol: TradeFacadeImpl#createOrder
  line: 52
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.534569Z'
---

<!-- kb:auto-start -->
## 业务结论

接收CreateOrderRequest，经统一代理执行校验与CREATE_ORDER业务Invoker。

## 源码证据

- `app/facade-impl/src/main/java/com/ly/travel/train/supplychain/bookingcore/facade/impl/TradeFacadeImpl.java:52 TradeFacadeImpl#createOrder`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
