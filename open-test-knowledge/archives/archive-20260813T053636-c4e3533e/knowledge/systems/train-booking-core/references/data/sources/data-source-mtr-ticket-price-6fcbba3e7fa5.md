---
node_id: data-source:mtr-ticket-price
system_id: train-booking-core
kind: data_source
title: 港铁路线报价服务
summary: 按车次、日期、出发站、到达站和坐席查询计划港币报价。
aliases:
- 路线港币报价
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java
  symbol: MtrTicketPriceService#getPrice
  line: 383
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.535855Z'
---

<!-- kb:auto-start -->
## 业务结论

按车次、日期、出发站、到达站和坐席查询计划港币报价。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java:383 MtrTicketPriceService#getPrice`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
