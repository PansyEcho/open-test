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
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: RefundFacade#refundReshopSubmit
  line: 153
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: RefundFacadeImpl#refundReshopSubmit
  line: 117
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/RefundReshopSubmitValidator.java
  symbol: RefundReshopSubmitValidator#validate
  line: 26
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundReshopSubmitServiceInvoker.java
  symbol: RefundReshopSubmitServiceInvoker#invoke
  line: 74
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundReshopSubmitServiceInvoker.java
  symbol: RefundReshopSubmitServiceInvoker#innerInvoke
  line: 93
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundReshopSubmitServiceInvoker.java
  symbol: RefundReshopSubmitServiceInvoker#doInvoke
  line: 103
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/AbstractOrderServiceInvoker.java
  symbol: AbstractOrderServiceInvoker#queryOrderByRefundSerialNo
  line: 76
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: OrderService#queryByRefundSerialNo
  line: 60
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#queryByRefundSerialNo
  line: 250
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/AbstractOrderService.java
  symbol: AbstractOrderService
  line: 11
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: SaasRefundOrderDAOProxy#queryByRefundSerialNo
  line: 51
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260825075610-a0f437c374-8132c1a1
  analysis_depth: business
invocation_contract: null
updated_at: '2026-08-26T02:44:11.916606Z'
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

## Agent代码解释（INFERRED）

保存费用、税项、豁免码和代金券；CBDS代金券退票强制人工。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
