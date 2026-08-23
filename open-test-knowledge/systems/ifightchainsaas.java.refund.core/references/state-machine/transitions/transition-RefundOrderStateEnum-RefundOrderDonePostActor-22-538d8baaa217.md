---
node_id: transition:RefundOrderStateEnum:RefundOrderDonePostActor:22
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: REFUND_SUCCESS → REFUND_DONE
summary: 订单从REFUND_SUCCESS流转到REFUND_DONE；包含3个可观察业务阶段，产生1项状态或数据副作用。
aliases:
- transition:RefundOrderStateEnum:RefundOrderDonePostActor:22
- RefundOrderDonePostActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderDonePostActor.java
  symbol: RefundOrderDonePostActor
  line: 26
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  phase: post
updated_at: '2026-08-22T17:17:29.690581Z'
---

<!-- kb:auto-start -->
## 业务结论

订单从REFUND_SUCCESS流转到REFUND_DONE；包含3个可观察业务阶段，产生1项状态或数据副作用。

## 业务阶段

- `更新退款时间`
- `通知支付`
- `发送邮件`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `addUpdateRefundTimeTask`

## 源码证据

- `RefundOrderDonePostActor.java RefundOrderDonePostActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
