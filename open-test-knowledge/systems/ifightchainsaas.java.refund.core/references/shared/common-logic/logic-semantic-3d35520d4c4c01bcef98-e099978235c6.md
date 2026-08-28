---
node_id: logic:semantic:3d35520d4c4c01bcef98
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: StateContextFactory.createState
summary: 该方法被2个知识所有者复用，符号解析状态为resolved。
aliases:
- semantic:3d35520d4c4c01bcef98
- com.ly.flight.chainsaas.refund.biz.fsm.core.StateContextFactory#createState(StateValue,com.ly.flight.chainsaas.refund.biz.fsm.core.StatePersister<T,
  OrderTask, StateValue>,com.ly.flight.chainsaas.refund.biz.fsm.event.StateEventQueue<T,
  OrderTask, StateValue>)
- com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.TimeoutCancelJob#process(JobRequest)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/fsm/core/StateContextFactory.java
  symbol: com.ly.flight.chainsaas.refund.biz.fsm.core.StateContextFactory#createState(StateValue,com.ly.flight.chainsaas.refund.biz.fsm.core.StatePersister<T,
    OrderTask, StateValue>,com.ly.flight.chainsaas.refund.biz.fsm.event.StateEventQueue<T,
    OrderTask, StateValue>)
  line: 38
  commit: ''
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
- kind: common_rule
  title: 状态上下文构造
  condition: 状态委托创建上下文
  expected_outcome: 使用调用方持久化器和事件队列构造上下文
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 2
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.TimeoutCancelJob#process(JobRequest)
  knowledge_owner_ids:
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.TimeoutCancelJob#process(JobRequest)
  patterns: []
invocation_contract: null
entry_fact_knowledge: null
updated_at: '2026-08-27T22:56:43.849660Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被2个知识所有者复用，符号解析状态为resolved。

## 复用知识所有者

- `com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.TimeoutCancelJob#process(JobRequest)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/fsm/core/StateContextFactory.java:38 · com.ly.flight.chainsaas.refund.biz.fsm.core.StateContextFactory#createState(StateValue,com.ly.flight.chainsaas.refund.biz.fsm.core.StatePersister<T, OrderTask, StateValue>,com.ly.flight.chainsaas.refund.biz.fsm.event.StateEventQueue<T, OrderTask, StateValue>)`

## Agent代码解释（INFERRED）

StateContextFactory#createState 是共享技术构造逻辑，不形成 cancel 的独立业务覆盖维度。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
