---
node_id: logic:semantic:acb7510b9a51202eba9c
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: MonitorEventListener.buildRefundMonitorKey
summary: 该方法被2个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:acb7510b9a51202eba9c
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java
  symbol: com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
  line: 263
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
  - com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)
  patterns: []
updated_at: '2026-08-22T17:17:29.400843Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被2个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java:263 · com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
