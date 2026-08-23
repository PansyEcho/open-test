---
node_id: transition:RefundOrderStateEnum:RefundOrderCancelPostActor:25
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: PENDING_APPLY/WAIT_REFUND/RESHOPING/REFUND_FAIL → REFUND_CANCEL
summary: 订单从PENDING_APPLY/WAIT_REFUND/RESHOPING/REFUND_FAIL流转到REFUND_CANCEL；包含1个可观察业务阶段，包含1个条件分支，产生1项状态或数据副作用。
aliases:
- transition:RefundOrderStateEnum:RefundOrderCancelPostActor:25
- RefundOrderCancelPostActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor
  line: 29
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  phase: post
updated_at: '2026-08-22T17:17:29.668441Z'
---

<!-- kb:auto-start -->
## 业务结论

订单从PENDING_APPLY/WAIT_REFUND/RESHOPING/REFUND_FAIL流转到REFUND_CANCEL；包含1个可观察业务阶段，包含1个条件分支，产生1项状态或数据副作用。

## 业务阶段

- `更新取消原因`

## 条件与分支

- `request == null`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `addCancelReasonUpdateTask`

## 源码证据

- `RefundOrderCancelPostActor.java RefundOrderCancelPostActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
