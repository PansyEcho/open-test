---
node_id: logic:semantic:8c151c8d5c3904009e4e
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: OrderStateMachineStarter.setStateEventRegistration
summary: 该方法被0个知识入口复用，符号解析状态为resolved。 源码证据将其标记为状态机。
aliases:
- semantic:8c151c8d5c3904009e4e
- com.ly.flight.chainsaas.refund.biz.fsm.core.OrderStateMachineStarter#setStateEventRegistration(com.ly.flight.chainsaas.refund.biz.fsm.event.StateEventRegistration<com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO,
  java.lang.String, com.ly.flight.chainsaas.refund.enums.RefundOrderStateEnum>)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/fsm/core/OrderStateMachineStarter.java
  symbol: com.ly.flight.chainsaas.refund.biz.fsm.core.OrderStateMachineStarter#setStateEventRegistration(com.ly.flight.chainsaas.refund.biz.fsm.event.StateEventRegistration<com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO,
    java.lang.String, com.ly.flight.chainsaas.refund.enums.RefundOrderStateEnum>)
  line: 97
  commit: ''
  content_digest: ''
status: code_verified
confidence: 1.0
tags:
- 状态机
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 0
  entry_point_ids: []
  patterns:
  - state_machine
updated_at: '2026-08-22T17:17:29.178435Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被0个知识入口复用，符号解析状态为resolved。 源码证据将其标记为状态机。

## 复用入口

- `尚未解析到入口`

## 模式证据

- `state_machine`：类型命名或状态流转注解提供明确状态机证据。

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/fsm/core/OrderStateMachineStarter.java:97 · com.ly.flight.chainsaas.refund.biz.fsm.core.OrderStateMachineStarter#setStateEventRegistration(com.ly.flight.chainsaas.refund.biz.fsm.event.StateEventRegistration<com.ly.flight.chainsaas.refund.model.SaasRefundOrderVO, java.lang.String, com.ly.flight.chainsaas.refund.enums.RefundOrderStateEnum>)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
