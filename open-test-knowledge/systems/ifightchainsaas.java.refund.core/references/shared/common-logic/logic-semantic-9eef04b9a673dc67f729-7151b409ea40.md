---
node_id: logic:semantic:9eef04b9a673dc67f729
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: RefundOrderSuccessPreActor.iterateTicketsAuto
summary: 该方法被0个知识入口复用，符号解析状态为partial。 源码证据将其标记为状态机。
aliases:
- semantic:9eef04b9a673dc67f729
- com.ly.flight.chainsaas.refund.biz.actor.pre.RefundOrderSuccessPreActor#iterateTicketsAuto(SaasRefundOrderVO,List<UpdateTicketNoParameter>,PassengerRefundResInfo)
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/pre/RefundOrderSuccessPreActor.java
  symbol: com.ly.flight.chainsaas.refund.biz.actor.pre.RefundOrderSuccessPreActor#iterateTicketsAuto(SaasRefundOrderVO,List<UpdateTicketNoParameter>,PassengerRefundResInfo)
  line: 136
  commit: ''
  content_digest: ''
status: code_verified
confidence: 0.65
tags:
- 状态机
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: partial
  reuse_entry_count: 0
  entry_point_ids: []
  patterns:
  - state_machine
updated_at: '2026-08-22T17:17:29.297051Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被0个知识入口复用，符号解析状态为partial。 源码证据将其标记为状态机。

## 复用入口

- `尚未解析到入口`

## 模式证据

- `state_machine`：类型命名或状态流转注解提供明确状态机证据。

## 源码证据

- `app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/pre/RefundOrderSuccessPreActor.java:136 · com.ly.flight.chainsaas.refund.biz.actor.pre.RefundOrderSuccessPreActor#iterateTicketsAuto(SaasRefundOrderVO,List<UpdateTicketNoParameter>,PassengerRefundResInfo)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
