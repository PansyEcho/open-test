---
node_id: logic:semantic:b6ca347028bfcfd2120d
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: BaseJob.buildLockKey
summary: 该方法被4个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:b6ca347028bfcfd2120d
- com.ly.flight.chainsaas.refund.biz.job.BaseJob#buildLockKey(java.lang.String)
- com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/job/BaseJob.java
  symbol: com.ly.flight.chainsaas.refund.biz.job.BaseJob#buildLockKey(java.lang.String)
  line: 28
  commit: ''
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 4
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)
  patterns: []
updated_at: '2026-08-22T17:17:29.364792Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被4个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.biz.job.MerchantBuyerFeeDataMigrateJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.SupplyChannelCleanJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.WalletRefundQueryJob#process(JobRequest)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/job/BaseJob.java:28 · com.ly.flight.chainsaas.refund.biz.job.BaseJob#buildLockKey(java.lang.String)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
