---
node_id: logic:semantic:6c8a3178efa1f9a0286f
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: TracerUtils.generateTraceId
summary: 该方法被7个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:6c8a3178efa1f9a0286f
- com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#generateTraceId()
- com.ly.flight.chainsaas.refund.biz.job.RefundOrderTaskCleanJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.RefundTaskJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.mq.listener.WalletRefundCallbackMessageListener#process(WalletAsyncCallbackDTO)
- com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#billSupplement(com.ly.flight.chainsaas.refund.facade.model.request.BillSupplementRequest)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/utils/TracerUtils.java
  symbol: com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#generateTraceId()
  line: 62
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
  - com.ly.flight.chainsaas.refund.biz.job.RefundOrderTaskCleanJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.RefundTaskJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.mq.listener.WalletRefundCallbackMessageListener#process(WalletAsyncCallbackDTO)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#billSupplement(com.ly.flight.chainsaas.refund.facade.model.request.BillSupplementRequest)
  patterns: []
updated_at: '2026-08-22T17:17:29.439039Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被7个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.biz.job.RefundOrderTaskCleanJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.RefundTaskJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.mq.listener.WalletRefundCallbackMessageListener#process(WalletAsyncCallbackDTO)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.WeChatNoticeListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.WeChatNoticeEvent)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#billSupplement(com.ly.flight.chainsaas.refund.facade.model.request.BillSupplementRequest)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/utils/TracerUtils.java:62 · com.ly.flight.chainsaas.refund.biz.utils.TracerUtils#generateTraceId()`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
