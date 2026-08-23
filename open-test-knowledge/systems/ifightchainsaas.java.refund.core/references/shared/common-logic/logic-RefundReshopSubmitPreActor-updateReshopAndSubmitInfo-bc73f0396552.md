---
node_id: logic:RefundReshopSubmitPreActor#updateReshopAndSubmitInfo
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: RefundReshopSubmitPreActor · updateReshopAndSubmitInfo
summary: 包含5个可观察业务阶段，包含3个条件分支，调用1个服务/仓储/缓存或消息协作者，产生1项状态或数据副作用。
aliases:
- RefundReshopSubmitPreActor#updateReshopAndSubmitInfo
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/pre/RefundReshopSubmitPreActor.java
  symbol: RefundReshopSubmitPreActor#updateReshopAndSubmitInfo
  line: 78
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: business
updated_at: '2026-08-22T17:17:29.801135Z'
---

<!-- kb:auto-start -->
## 业务结论

包含5个可观察业务阶段，包含3个条件分支，调用1个服务/仓储/缓存或消息协作者，产生1项状态或数据副作用。

## 业务阶段

- `是否人工调价`
- `税项明细`
- `非自愿标识码`
- `代金券标记`
- `代金券退票且为CBDS时，改为人工退票；否则不更新is_auto`

## 条件与分支

- `orderExt == null`
- `VoucherFlagEnum.isYes(order.getIsVoucher(`
- `rowAffect <= 0`

## 外部交互

- `orderService.updateReshopSubmitInfo`

## 状态与副作用

- `orderService.updateReshopSubmitInfo`

## 源码证据

- `RefundReshopSubmitPreActor.java RefundReshopSubmitPreActor#updateReshopAndSubmitInfo`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
