---
node_id: logic:semantic:ab9dce36ef6dd20cad55
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: DistributedLockService.tryAcquire
summary: 该方法被5个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:ab9dce36ef6dd20cad55
- com.ly.flight.chainsaas.refund.biz.lock.DistributedLockService#tryAcquire(java.lang.String)
- com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.mq.listener.WalletRefundCallbackMessageListener#process(WalletAsyncCallbackDTO)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/lock/DistributedLockService.java
  symbol: com.ly.flight.chainsaas.refund.biz.lock.DistributedLockService#tryAcquire(java.lang.String)
  line: 35
  commit: ''
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 5
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.mq.listener.WalletRefundCallbackMessageListener#process(WalletAsyncCallbackDTO)
  patterns: []
updated_at: '2026-08-22T17:17:29.370894Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被5个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.mq.listener.WalletRefundCallbackMessageListener#process(WalletAsyncCallbackDTO)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/lock/DistributedLockService.java:35 · com.ly.flight.chainsaas.refund.biz.lock.DistributedLockService#tryAcquire(java.lang.String)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
