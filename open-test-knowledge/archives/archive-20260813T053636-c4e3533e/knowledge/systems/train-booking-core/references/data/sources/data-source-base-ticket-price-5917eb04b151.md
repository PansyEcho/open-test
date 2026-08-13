---
node_id: data-source:base-ticket-price
system_id: train-booking-core
kind: data_source
title: 港铁基础票价库
summary: 按OD、坐席和乘客类型查询基础港币票价，作为儿童和非卧铺fallback。
aliases:
- 基础港币票价
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java
  symbol: BaseDataRepository#findTargetTicketPrice
  line: 624
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.536045Z'
---

<!-- kb:auto-start -->
## 业务结论

按OD、坐席和乘客类型查询基础港币票价，作为儿童和非卧铺fallback。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java:624 BaseDataRepository#findTargetTicketPrice`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
