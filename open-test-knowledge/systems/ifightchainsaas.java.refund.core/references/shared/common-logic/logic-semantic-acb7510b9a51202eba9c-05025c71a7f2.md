---
node_id: logic:semantic:acb7510b9a51202eba9c
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: MonitorEventListener.buildRefundMonitorKey
summary: 该方法被2个知识所有者复用，符号解析状态为resolved。
aliases:
- semantic:acb7510b9a51202eba9c
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java
  symbol: com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
  line: 263
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder
  line: 223
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#invoke
  line: 125
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#innerInvoke
  line: 145
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/OrderBuilder.java
  symbol: com.ly.flight.chainsaas.refund.biz.builder.impl.OrderBuilder#buildOrder
  line: 97
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#saveOrder
  line: 410
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/converter/OrderConverter.java
  symbol: com.ly.flight.chainsaas.refund.biz.converter.OrderConverter#vo2do
  line: 28
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: com.ly.flight.chainsaas.refund.dal.proxy.SaasRefundOrderDAOProxy#insert
  line: 81
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java
  symbol: com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey
  line: 263
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java
  symbol: com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#addMonitorKeys
  line: 308
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.OrderService#saveOrder
  line: 107
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#innerInvoke
  line: 208
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/AbstractOrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.AbstractOrderService
  line: 8
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
test_points:
- kind: common_rule
  title: 聚合乘机人航段键
  condition: 乘机人或航段键存在
  expected_outcome: 添加非空组合且不形成业务覆盖因子
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 2
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)
  knowledge_owner_ids:
  - com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
  - com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)
  patterns: []
invocation_contract: null
entry_fact_knowledge: null
updated_at: '2026-08-27T23:21:07.967930Z'
---


<!-- kb:auto-start -->
## 业务结论

该方法被2个知识所有者复用，符号解析状态为resolved。

## 复用知识所有者

- `com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)`
- `com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java:263 · com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)`

## Agent代码解释（INFERRED）

addMonitorKeys聚合乘机人与航段键，只属于内部持久化辅助逻辑。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
