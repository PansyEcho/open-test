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
- kind: validation
  title: 订单或原订单号为空
  condition: refundOrderVO为null或orderSerialNo为空白
  expected_outcome: 返回空字符串，不生成监控键。
- kind: main_flow
  title: 有效明细组装监控键
  condition: 退票订单存在且orderSerialNo非空，psis包含有效明细和可生成的乘客或航段信息
  expected_outcome: 生成乘客/航段组合键，并按原订单号与排序后的键集合组装监控键。
- kind: boundary
  title: 空明细和无有效键
  condition: psis为null、包含null元素，或所有明细无法生成有效键
  expected_outcome: 跳过无效明细；没有有效键时返回原订单号，不抛出异常。
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
updated_at: '2026-09-07T21:09:34.934202Z'
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

MonitorEventListener.buildRefundMonitorKey按退票订单构造回溯监控键：订单为空或原订单号为空白返回空串；否则遍历psis，跳过null明细，构造乘客和航段键并调用addMonitorKeys，最后按原订单号和键集合组装结果。有效订单但没有有效明细键时返回原订单号；有键时先排序再拼接。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
