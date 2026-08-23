---
node_id: transition:RefundOrderStateEnum:RefundOrderSuccessPostActor:28
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: WAIT_REFUND/REFUNDING/REFUND_FAIL → REFUND_SUCCESS
summary: 订单从WAIT_REFUND/REFUNDING/REFUND_FAIL流转到REFUND_SUCCESS；包含9个可观察业务阶段，包含4个条件分支，产生2项状态或数据副作用。
aliases:
- transition:RefundOrderStateEnum:RefundOrderSuccessPostActor:28
- RefundOrderSuccessPostActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderSuccessPostActor.java
  symbol: RefundOrderSuccessPostActor
  line: 32
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  phase: post
updated_at: '2026-08-22T17:17:29.716532Z'
---

<!-- kb:auto-start -->
## 业务结论

订单从WAIT_REFUND/REFUNDING/REFUND_FAIL流转到REFUND_SUCCESS；包含9个可观察业务阶段，包含4个条件分支，产生2项状态或数据副作用。

## 业务阶段

- `发送对账`
- `发送行程单`
- `支付通知`
- `发送邮件`
- `追加钱包结算任务，后续由钱包成功回调或查询补偿推进退款完成。`
- `addLogTask(stateContext, LogTypeEnum.REFUND_DONE, LogTypeEnum.REFUND_DONE.getDesc(), FsmConstants.SYSTEM_OPERATOR);`
- `普通成功、补单和同步入口都统一追加钱包结算任务，人工重试由专用接口直接落task。`
- `返回或结束分支：false`
- `返回或结束分支：RefundOrderTypeEnum.SUPPLEMENT.getCode().equals(refundOrderType)`

## 条件与分支

- `isSupplementOrSyncSuccess(stateContext`
- `!VoucherFlagEnum.isYes(stateContext.getData(`
- `stateContext == null || stateContext.getData(`
- `useVoucher`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `accountCheckSenderTask`
- `addTicketedJourneySenderTask`

## 源码证据

- `RefundOrderSuccessPostActor.java RefundOrderSuccessPostActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
