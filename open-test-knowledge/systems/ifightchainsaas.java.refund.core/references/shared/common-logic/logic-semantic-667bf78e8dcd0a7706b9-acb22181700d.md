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
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/CreateRefundOrderValidator.java
  symbol: com.ly.flight.chainsaas.refund.facade.validator.trade.CreateRefundOrderValidator#validate
  line: 28
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker
  line: 82
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
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker
  line: 88
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/AbstractOrderServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.AbstractOrderServiceInvoker
  line: 36
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/AbstractOrderServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.AbstractOrderServiceInvoker
  line: 52
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.OrderService#saveOrder
  line: 107
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl
  line: 56
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#saveOrder
  line: 410
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/AbstractOrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.AbstractOrderService
  line: 11
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
status: inferred
confidence: 1.0
tags: []
test_points:
- kind: common_rule
  title: 乘客和航段键均为空
  condition: passengerKey为空且segmentKeys为null或空集合
  expected_outcome: 不向keys集合添加监控键。
- kind: common_rule
  title: 仅有乘客键
  condition: passengerKey非空且segmentKeys为null或空集合
  expected_outcome: 将passengerKey直接加入keys集合。
- kind: common_rule
  title: 乘客与航段组合
  condition: segmentKeys包含非空值，passengerKey为空或非空，且可能包含空航段键
  expected_outcome: 空航段键跳过；每个非空航段生成segmentKey或passengerKey@segmentKey并加入keys。
metadata:
  scan_id: scan-20260902095328-66619d80f6-47b8cbc3
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
input_contract: null
entry_fact_knowledge: null
updated_at: '2026-09-07T21:09:34.924308Z'
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

MonitorEventListener.addMonitorKeys把乘客键和航段键加入退票监控集合：两者都为空时跳过；没有航段键时直接加入乘客键；有航段键时跳过空值，并按passengerKey@segmentKey或单独segmentKey组合加入集合。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
