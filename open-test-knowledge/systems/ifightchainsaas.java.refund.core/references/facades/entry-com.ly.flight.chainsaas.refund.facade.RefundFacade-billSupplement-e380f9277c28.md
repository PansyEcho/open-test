---
node_id: entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#billSupplement
system_id: ifightchainsaas.java.refund.core
kind: facade
title: RefundFacade#billSupplement
summary: 包含3个可观察业务阶段，包含2个条件分支。
aliases:
- facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#billSupplement
- com.ly.flight.chainsaas.refund.facade.RefundFacade#billSupplement
- RefundFacade#billSupplement
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: RefundFacadeImpl#billSupplement
  line: 381
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  tool_id: facade.refund.bill_supplement
  analysis_depth: business
  branch_count: 2
  external_call_count: 0
updated_at: '2026-08-22T17:17:29.563202Z'
---

<!-- kb:auto-start -->
## 业务结论

包含3个可观察业务阶段，包含2个条件分支。

## 业务阶段

- `票号`
- `返回或结束分支：this.execute(request, RefundOrderServiceEnum.BILL_SUPPLEMENT, OrderSourceEnum.COMMON, TracerUtils.generateTraceId(), ticketNo)`
- `返回或结束分支：createErrorResponse(e, BillSupplementResponse.class)`

## 条件与分支

- `request.getArcBillVO(`
- `request.getBspBillVO(`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundFacadeImpl.java RefundFacadeImpl#billSupplement`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
