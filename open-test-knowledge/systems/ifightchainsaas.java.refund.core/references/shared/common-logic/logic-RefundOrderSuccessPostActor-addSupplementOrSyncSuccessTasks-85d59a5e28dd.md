---
node_id: logic:RefundOrderSuccessPostActor#addSupplementOrSyncSuccessTasks
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: RefundOrderSuccessPostActor · addSupplementOrSyncSuccessTasks
summary: 包含1个可观察业务阶段，产生1项状态或数据副作用。
aliases:
- RefundOrderSuccessPostActor#addSupplementOrSyncSuccessTasks
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderSuccessPostActor.java
  symbol: RefundOrderSuccessPostActor#addSupplementOrSyncSuccessTasks
  line: 78
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: business
updated_at: '2026-08-22T17:17:29.721733Z'
---

<!-- kb:auto-start -->
## 业务结论

包含1个可观察业务阶段，产生1项状态或数据副作用。

## 业务阶段

- `addLogTask(stateContext, LogTypeEnum.REFUND_DONE, LogTypeEnum.REFUND_DONE.getDesc(), FsmConstants.SYSTEM_OPERATOR);`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `accountCheckSenderTask`

## 源码证据

- `RefundOrderSuccessPostActor.java RefundOrderSuccessPostActor#addSupplementOrSyncSuccessTasks`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
