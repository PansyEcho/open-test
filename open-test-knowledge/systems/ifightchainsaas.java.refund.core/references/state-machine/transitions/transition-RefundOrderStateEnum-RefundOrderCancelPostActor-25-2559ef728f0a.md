---
node_id: transition:RefundOrderStateEnum:RefundOrderCancelPostActor:25
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: PENDING_APPLY/WAIT_REFUND/RESHOPING/REFUND_FAIL → REFUND_CANCEL
summary: 订单从PENDING_APPLY/WAIT_REFUND/RESHOPING/REFUND_FAIL流转到REFUND_CANCEL；包含1个可观察业务阶段，包含1个条件分支，产生1项状态或数据副作用。
aliases:
- transition:RefundOrderStateEnum:RefundOrderCancelPostActor:25
- RefundOrderCancelPostActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor
  line: 29
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor#addCancelReasonUpdateTask
  line: 52
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor#addTask
  line: 32
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel
  line: 84
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel
  line: 292
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke
  line: 80
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#innerInvoke
  line: 99
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#doInvoke
  line: 135
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/CBDSService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.CBDSService#refundCancel
  line: 26
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/CBDSServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.CBDSServiceImpl#refundCancel
  line: 66
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/resources/ResourcesClient.java
  symbol: com.ly.flight.chainsaas.refund.integration.resources.ResourcesClient#refundCancel
  line: 39
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/resources/ResourcesClientImpl.java
  symbol: com.ly.flight.chainsaas.refund.integration.resources.ResourcesClientImpl#refundCancel
  line: 61
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/proxy/RefundResourcesFacadeProxy.java
  symbol: com.ly.flight.chainsaas.refund.integration.proxy.RefundResourcesFacadeProxy#refundCancel
  line: 100
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/RefundOrderStateEnum.java
  symbol: com.ly.flight.chainsaas.refund.enums.RefundOrderStateEnum
  line: 12
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
test_points:
- kind: transition
  title: 处理中订单取消
  condition: 当前状态属于 PENDING_APPLY、WAIT_REFUND、RESHOPING、REFUND_FAIL
  expected_outcome: 状态变为 REFUND_CANCEL
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  phase: post
  owned_analysis_symbols:
  - RefundOrderCancelPostActor
  - RefundOrderCancelPostActor#addCancelReasonUpdateTask
  - RefundOrderCancelPostActor#addTask
invocation_contract: null
entry_fact_knowledge: null
updated_at: '2026-08-27T22:56:43.817397Z'
---


<!-- kb:auto-start -->
## 业务结论

订单从PENDING_APPLY/WAIT_REFUND/RESHOPING/REFUND_FAIL流转到REFUND_CANCEL；包含1个可观察业务阶段，包含1个条件分支，产生1项状态或数据副作用。

## 业务阶段

- `更新取消原因`

## 条件与分支

- `request == null`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `addCancelReasonUpdateTask`

## 源码证据

- `RefundOrderCancelPostActor.java RefundOrderCancelPostActor`


## 状态流转内部方法：RefundOrderCancelPostActor#addCancelReasonUpdateTask

## 业务结论

当前源码仅能证明该入口或方法存在，未直接提取到条件、外部交互或状态副作用。

## 业务阶段

- `未从当前方法直接证明`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundOrderCancelPostActor.java RefundOrderCancelPostActor#addCancelReasonUpdateTask`


## 状态流转内部方法：RefundOrderCancelPostActor#addTask

## 业务结论

包含1个可观察业务阶段，包含1个条件分支，产生1项状态或数据副作用。

## 业务阶段

- `更新取消原因`

## 条件与分支

- `request == null`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `addCancelReasonUpdateTask`

## 源码证据

- `RefundOrderCancelPostActor.java RefundOrderCancelPostActor#addTask`

## Agent代码解释（INFERRED）

取消后置处理覆盖 PENDING_APPLY、WAIT_REFUND、RESHOPING、REFUND_FAIL 到 REFUND_CANCEL，并登记取消原因更新任务。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
