---
node_id: logic:semantic:667bf78e8dcd0a7706b9
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: MonitorEventListener.addMonitorKeys
summary: 该方法被2个知识所有者复用，符号解析状态为resolved。
aliases:
- semantic:667bf78e8dcd0a7706b9
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#addMonitorKeys(java.util.Set<java.lang.String>,java.lang.String,java.util.Set<java.lang.String>)
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#buildRefundMonitorKey(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
- com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#onEvent(com.ly.flight.chainsaas.refund.biz.event.AutoRefundMonitorEvent)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java
  symbol: com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#addMonitorKeys(java.util.Set<java.lang.String>,java.lang.String,java.util.Set<java.lang.String>)
  line: 308
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
  title: 生成监控键
  condition: 退票单包含原订单及PSI关系
  expected_outcome: 按固定格式派生监控键
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
updated_at: '2026-08-27T23:21:07.959037Z'
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

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/mq/sender/MonitorEventListener.java:308 · com.ly.flight.chainsaas.refund.biz.mq.sender.MonitorEventListener#addMonitorKeys(java.util.Set<java.lang.String>,java.lang.String,java.util.Set<java.lang.String>)`

## Agent代码解释（INFERRED）

buildRefundMonitorKey只为持久化实体派生稳定监控键，不新增Case输入组合。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
