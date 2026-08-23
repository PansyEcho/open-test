---
node_id: logic:semantic:67c42d07b6546898d1ad
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: TracerUtils.clear
summary: 该方法被11个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:67c42d07b6546898d1ad
- com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#clear()
- com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.TimeoutCancelJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.mq.listener.TicketedJourneySenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketedJourneySenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.CustomerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.CustomerPayRefundSenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.LogSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.LoggerSenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.RefundDoneSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.RefundDoneSenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.SuppilerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SuppilerPayRefundSenderEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.TicketNotifyListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketNofityEvent)
- com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/utils/TracerUtils.java
  symbol: com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#clear()
  line: 54
  commit: ''
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 11
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.TimeoutCancelJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.mq.listener.TicketedJourneySenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketedJourneySenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.CustomerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.CustomerPayRefundSenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.LogSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.LoggerSenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.RefundDoneSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.RefundDoneSenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.SuppilerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SuppilerPayRefundSenderEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.TicketNotifyListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketNofityEvent)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)
  patterns: []
updated_at: '2026-08-22T17:17:29.431236Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被11个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.TimeoutCancelJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.mq.listener.TicketedJourneySenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketedJourneySenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.CustomerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.CustomerPayRefundSenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.LogSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.LoggerSenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.RefundDoneSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.RefundDoneSenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.SuppilerPayRefundSenderListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.SuppilerPayRefundSenderEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.TicketNotifyListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.TicketNofityEvent)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/utils/TracerUtils.java:54 · com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#clear()`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
