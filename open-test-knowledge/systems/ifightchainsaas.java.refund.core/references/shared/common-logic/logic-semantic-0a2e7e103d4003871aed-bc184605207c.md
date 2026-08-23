---
node_id: logic:semantic:0a2e7e103d4003871aed
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: TracerUtils.initTracerParams
summary: 该方法被7个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:0a2e7e103d4003871aed
- com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#initTracerParams(com.ly.flight.chainsaas.refund.biz.constants.LogEnum,java.lang.String,java.lang.String)
- com.ly.flight.chainsaas.refund.biz.mq.listener.TicketedJourneySenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketedJourneySenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.CustomerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.CustomerPayRefundSenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.LogSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.LoggerSenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.SendEmailSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SendEmailEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.SuppilerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SuppilerPayRefundSenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.TicketNotifyListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketNofityEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/utils/TracerUtils.java
  symbol: com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#initTracerParams(com.ly.flight.chainsaas.refund.biz.constants.LogEnum,java.lang.String,java.lang.String)
  line: 32
  commit: ''
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 7
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.mq.listener.TicketedJourneySenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketedJourneySenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.CustomerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.CustomerPayRefundSenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.LogSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.LoggerSenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.SendEmailSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SendEmailEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.SuppilerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SuppilerPayRefundSenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.TicketNotifyListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketNofityEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)
  patterns: []
updated_at: '2026-08-22T17:17:29.445958Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被7个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.biz.mq.listener.TicketedJourneySenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketedJourneySenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.CustomerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.CustomerPayRefundSenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.LogSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.LoggerSenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.SendEmailSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SendEmailEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.SuppilerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SuppilerPayRefundSenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.TicketNotifyListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketNofityEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/utils/TracerUtils.java:32 · com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#initTracerParams(com.ly.flight.chainsaas.refund.biz.constants.LogEnum,java.lang.String,java.lang.String)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
