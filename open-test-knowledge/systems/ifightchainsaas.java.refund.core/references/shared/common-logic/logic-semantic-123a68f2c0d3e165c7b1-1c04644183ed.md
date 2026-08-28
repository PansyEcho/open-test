---
node_id: logic:semantic:123a68f2c0d3e165c7b1
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: OrderServiceImpl.buildListOrder
summary: 该方法被2个知识所有者复用，符号解析状态为resolved。
aliases:
- semantic:123a68f2c0d3e165c7b1
- com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#buildListOrder(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
- com.ly.flight.chainsaas.refund.biz.job.ItemPnrJob#process(JobRequest)
- com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#buildListOrder(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)
  line: 358
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList
  line: 206
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundOrderListQueryInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundOrderListQueryInvoker#invoke
  line: 40
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.OrderService#queryOrderList
  line: 50
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#queryOrderList
  line: 131
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: com.ly.flight.chainsaas.refund.dal.proxy.SaasRefundOrderDAOProxy#listPage
  line: 61
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#buildListOrder
  line: 359
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundOrderQueryRequest.java
  symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest
  line: 19
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
  title: 补齐明细关系
  condition: 分页包含退票单
  expected_outcome: 按refundSerialNo与orderSerialNo加载items和psis
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 2
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.biz.job.ItemPnrJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  knowledge_owner_ids:
  - com.ly.flight.chainsaas.refund.biz.job.ItemPnrJob#process(JobRequest)
  - com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)
  patterns: []
invocation_contract: null
entry_fact_knowledge: null
updated_at: '2026-08-27T23:11:31.910365Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被2个知识所有者复用，符号解析状态为resolved。

## 复用知识所有者

- `com.ly.flight.chainsaas.refund.biz.job.ItemPnrJob#process(JobRequest)`
- `com.ly.flight.chainsaas.refund.biz.job.RetryEventJob#process(JobRequest)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java:358 · com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#buildListOrder(com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO)`

## Agent代码解释（INFERRED）

buildListOrder为分页退票单补齐订单项和乘机人关系，不形成输入组合。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
