---
node_id: transition:RefundOrderStateEnum:RefundReshopSubmitPreActor:35
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: PENDING_APPLY/RESHOPING → AUDITED
summary: 订单从PENDING_APPLY/RESHOPING流转到AUDITED；包含8个可观察业务阶段，包含4个条件分支，调用3个服务/仓储/缓存或消息协作者，产生3项状态或数据副作用。
aliases:
- transition:RefundOrderStateEnum:RefundReshopSubmitPreActor:35
- RefundReshopSubmitPreActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/pre/RefundReshopSubmitPreActor.java
  symbol: RefundReshopSubmitPreActor
  line: 39
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  phase: pre
updated_at: '2026-08-22T17:17:29.795751Z'
---

<!-- kb:auto-start -->
## 业务结论

订单从PENDING_APPLY/RESHOPING流转到AUDITED；包含8个可观察业务阶段，包含4个条件分支，调用3个服务/仓储/缓存或消息协作者，产生3项状态或数据副作用。

## 业务阶段

- `跟新PNR`
- `保存核价以及提交信息`
- `是否人工调价`
- `税项明细`
- `非自愿标识码`
- `代金券标记`
- `代金券退票且为CBDS时，改为人工退票；否则不更新is_auto`
- `返回或结束分支：true`

## 条件与分支

- `orderDetailResponse != null && orderDetailResponse.getSaasOrderVO(`
- `orderExt == null`
- `VoucherFlagEnum.isYes(order.getIsVoucher(`
- `rowAffect <= 0`

## 外部交互

- `orderService.queryByRefundSerialNo`
- `itemService.updatePrice`
- `orderService.updateReshopSubmitInfo`

## 状态与副作用

- `updateReshopAndSubmitInfo`
- `itemService.updatePrice`
- `orderService.updateReshopSubmitInfo`

## 源码证据

- `RefundReshopSubmitPreActor.java RefundReshopSubmitPreActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
