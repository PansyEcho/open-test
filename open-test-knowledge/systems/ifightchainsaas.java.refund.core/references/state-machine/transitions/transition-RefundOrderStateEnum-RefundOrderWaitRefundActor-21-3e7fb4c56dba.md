---
node_id: transition:RefundOrderStateEnum:RefundOrderWaitRefundActor:21
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: AUDITED → WAIT_REFUND
summary: 订单从AUDITED流转到WAIT_REFUND；包含2个可观察业务阶段，产生1项状态或数据副作用。
aliases:
- transition:RefundOrderStateEnum:RefundOrderWaitRefundActor:21
- RefundOrderWaitRefundActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderWaitRefundActor.java
  symbol: RefundOrderWaitRefundActor
  line: 26
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  phase: post
updated_at: '2026-08-22T17:17:29.769331Z'
---

<!-- kb:auto-start -->
## 业务结论

订单从AUDITED流转到WAIT_REFUND；包含2个可观察业务阶段，产生1项状态或数据副作用。

## 业务阶段

- `发送退票通知`
- `更新自动废票类型`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `addUpdateAutoTypeTask`

## 源码证据

- `RefundOrderWaitRefundActor.java RefundOrderWaitRefundActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
