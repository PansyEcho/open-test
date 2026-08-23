---
node_id: logic:semantic:eeaf69dad0fddf88bb4e
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: OrderService.querySyncOrder
summary: 该方法被2个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:eeaf69dad0fddf88bb4e
- com.ly.flight.chainsaas.refund.biz.service.OrderService#querySyncOrder(com.ly.flight.chainsaas.refund.dal.operation.SyncRefundOrderParam)
- com.ly.flight.chainsaas.refund.biz.job.ItemPnrJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.SyncToPreRefundJob#process(JobRequest)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.OrderService#querySyncOrder(com.ly.flight.chainsaas.refund.dal.operation.SyncRefundOrderParam)
  line: 163
  commit: ''
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 2
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.job.ItemPnrJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.SyncToPreRefundJob#process(JobRequest)
  patterns: []
updated_at: '2026-08-22T17:17:29.406988Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被2个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.biz.job.ItemPnrJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.SyncToPreRefundJob#process(JobRequest)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java:163 · com.ly.flight.chainsaas.refund.biz.service.OrderService#querySyncOrder(com.ly.flight.chainsaas.refund.dal.operation.SyncRefundOrderParam)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
