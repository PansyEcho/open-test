---
node_id: logic:RefundOrderSuccessPostActor#addTask
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: RefundOrderSuccessPostActor · addTask
summary: 包含5个可观察业务阶段，包含2个条件分支，产生2项状态或数据副作用。
aliases:
- RefundOrderSuccessPostActor#addTask
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderSuccessPostActor.java
  symbol: RefundOrderSuccessPostActor#addTask
  line: 35
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: business
updated_at: '2026-08-22T17:17:29.743018Z'
---

<!-- kb:auto-start -->
## 业务结论

包含5个可观察业务阶段，包含2个条件分支，产生2项状态或数据副作用。

## 业务阶段

- `发送对账`
- `发送行程单`
- `支付通知`
- `发送邮件`
- `追加钱包结算任务，后续由钱包成功回调或查询补偿推进退款完成。`

## 条件与分支

- `isSupplementOrSyncSuccess(stateContext`
- `!VoucherFlagEnum.isYes(stateContext.getData(`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `accountCheckSenderTask`
- `addTicketedJourneySenderTask`

## 源码证据

- `RefundOrderSuccessPostActor.java RefundOrderSuccessPostActor#addTask`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
