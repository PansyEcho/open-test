---
node_id: logic:RefundOrderSuccessPostActor#addWalletRefundTask
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: RefundOrderSuccessPostActor · addWalletRefundTask
summary: 包含1个可观察业务阶段，包含1个条件分支。
aliases:
- RefundOrderSuccessPostActor#addWalletRefundTask
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderSuccessPostActor.java
  symbol: RefundOrderSuccessPostActor#addWalletRefundTask
  line: 89
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: business
updated_at: '2026-08-22T17:17:29.737857Z'
---

<!-- kb:auto-start -->
## 业务结论

包含1个可观察业务阶段，包含1个条件分支。

## 业务阶段

- `普通成功、补单和同步入口都统一追加钱包结算任务，人工重试由专用接口直接落task。`

## 条件与分支

- `useVoucher`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundOrderSuccessPostActor.java RefundOrderSuccessPostActor#addWalletRefundTask`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
