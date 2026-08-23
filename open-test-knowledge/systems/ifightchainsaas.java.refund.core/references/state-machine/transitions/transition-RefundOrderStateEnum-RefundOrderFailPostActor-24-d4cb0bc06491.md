---
node_id: transition:RefundOrderStateEnum:RefundOrderFailPostActor:24
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: WAIT_REFUND/REFUNDING → REFUND_FAIL
summary: 订单从WAIT_REFUND/REFUNDING流转到REFUND_FAIL；包含2个可观察业务阶段。
aliases:
- transition:RefundOrderStateEnum:RefundOrderFailPostActor:24
- RefundOrderFailPostActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderFailPostActor.java
  symbol: RefundOrderFailPostActor
  line: 28
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  phase: post
updated_at: '2026-08-22T17:17:29.706103Z'
---

<!-- kb:auto-start -->
## 业务结论

订单从WAIT_REFUND/REFUNDING流转到REFUND_FAIL；包含2个可观察业务阶段。

## 业务阶段

- `发送退票通知`
- `发送邮件`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundOrderFailPostActor.java RefundOrderFailPostActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
