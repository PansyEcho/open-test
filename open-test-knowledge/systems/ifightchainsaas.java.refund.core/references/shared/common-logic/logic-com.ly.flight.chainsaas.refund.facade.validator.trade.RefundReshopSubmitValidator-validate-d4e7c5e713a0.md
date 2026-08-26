---
node_id: logic:com.ly.flight.chainsaas.refund.facade.validator.trade.RefundReshopSubmitValidator#validate
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: RefundReshopSubmitValidator · validate
summary: 包含4个条件分支。
aliases:
- com.ly.flight.chainsaas.refund.facade.validator.trade.RefundReshopSubmitValidator#validate
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/RefundReshopSubmitValidator.java
  symbol: com.ly.flight.chainsaas.refund.facade.validator.trade.RefundReshopSubmitValidator#validate
  line: 26
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
updated_at: '2026-08-26T02:44:11.880416Z'
---

<!-- kb:auto-start -->
## 业务结论

包含4个条件分支。

## 业务阶段

- `未从当前方法直接证明`

## 条件与分支

- `CollectionUtils.isNotEmpty(taxDetailList`
- `CollectionUtils.isEmpty(taxItemList`
- `taxItemList.size(`
- `StringUtils.isNotBlank(waiverCode`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundReshopSubmitValidator.java com.ly.flight.chainsaas.refund.facade.validator.trade.RefundReshopSubmitValidator#validate`

## Agent代码解释（INFERRED）

校验必填字段、税项明细和waiverCode长度。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
