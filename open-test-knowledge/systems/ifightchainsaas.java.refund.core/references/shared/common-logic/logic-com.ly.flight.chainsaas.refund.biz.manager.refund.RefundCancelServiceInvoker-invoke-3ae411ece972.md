---
node_id: logic:com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: RefundCancelServiceInvoker · invoke
summary: 包含3个可观察业务阶段，调用1个服务/仓储/缓存或消息协作者，产生2项状态或数据副作用。
aliases:
- com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke
  line: 80
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: RefundFacade#cancel
  line: 84
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: RefundFacadeImpl#cancel
  line: 292
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/RefundCancelValidator.java
  symbol: RefundCancelValidator#validate
  line: 19
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
  symbol: RefundCancelRequest
  line: 13
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/BaseRequest.java
  symbol: BaseRequest
  line: 14
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/response/RefundCancelResponse.java
  symbol: RefundCancelResponse
  line: 3
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: RefundCancelServiceInvoker#invoke
  line: 80
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: RefundCancelServiceInvoker#innerInvoke
  line: 99
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: RefundCancelServiceInvoker#doInvoke
  line: 114
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
  path: app/dal/src/main/resources/sqlmap/refundcore/SaasRefundOrderMapperExt.xml
  symbol: queryByRefundSerialNo
  line: 169
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor
  line: 25
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor#addTask
  line: 32
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor#addCancelReasonUpdateTask
  line: 52
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderManualCancelPostActor.java
  symbol: RefundOrderManualCancelPostActor
  line: 20
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260825075610-a0f437c374-8132c1a1
  analysis_depth: business
invocation_contract: null
updated_at: '2026-08-26T01:52:09.384022Z'
---

<!-- kb:auto-start -->
## 业务结论

包含3个可观察业务阶段，调用1个服务/仓储/缓存或消息协作者，产生2项状态或数据副作用。

## 业务阶段

- `返回或结束分支：OrderConstants.ORDER_OPERATE_ + request.getRefundSerialNo()`
- `返回或结束分支：request.getRefundSerialNo()`
- `返回或结束分支：innerInvoke(request)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `serviceInvokerLockDelegate.invokeWithLock`

## 状态与副作用

- `serviceInvokerLockDelegate.invokeWithLock`
- `lockKey`

## 源码证据

- `RefundCancelServiceInvoker.java com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke`

## Agent代码解释（INFERRED）

按退票单号加业务锁，查询订单、校验状态并驱动取消；CBDS/SAPL 非代金券订单调用 CBDS 取消。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
