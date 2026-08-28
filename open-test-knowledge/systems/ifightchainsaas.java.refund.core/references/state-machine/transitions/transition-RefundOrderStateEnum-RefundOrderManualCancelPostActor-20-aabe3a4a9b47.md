---
node_id: transition:RefundOrderStateEnum:RefundOrderManualCancelPostActor:20
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: AUDITED → REFUND_CANCEL
summary: 订单从AUDITED流转到REFUND_CANCEL；当前源码仅能证明该入口或方法存在，未直接提取到条件、外部交互或状态副作用。
aliases:
- transition:RefundOrderStateEnum:RefundOrderManualCancelPostActor:20
- RefundOrderManualCancelPostActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderManualCancelPostActor.java
  symbol: RefundOrderManualCancelPostActor
  line: 24
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
  title: 审核后取消
  condition: 当前状态为 AUDITED
  expected_outcome: 状态变为 REFUND_CANCEL
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  phase: post
  owned_analysis_symbols:
  - RefundOrderManualCancelPostActor
invocation_contract: null
entry_fact_knowledge: null
updated_at: '2026-08-27T22:56:43.834448Z'
---


<!-- kb:auto-start -->
## 业务结论

订单从AUDITED流转到REFUND_CANCEL；当前源码仅能证明该入口或方法存在，未直接提取到条件、外部交互或状态副作用。

## 业务阶段

- `未从当前方法直接证明`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundOrderManualCancelPostActor.java RefundOrderManualCancelPostActor`

## Agent代码解释（INFERRED）

人工审核完成的 AUDITED 退票单允许流转到 REFUND_CANCEL。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
