---
node_id: entry:com.ly.flight.chainsaas.refund.facade.ToolFacade#syncOrder
system_id: ifightchainsaas.java.refund.core
kind: facade
title: ToolFacade#syncOrder
summary: 包含2个可观察业务阶段。
aliases:
- facade:com.ly.flight.chainsaas.refund.facade.ToolFacade#syncOrder
- com.ly.flight.chainsaas.refund.facade.ToolFacade#syncOrder
- ToolFacade#syncOrder
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/ToolFacadeImpl.java
  symbol: ToolFacadeImpl#syncOrder
  line: 35
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  tool_id: facade.tool.sync_order
  analysis_depth: business
  branch_count: 0
  external_call_count: 0
updated_at: '2026-08-22T17:17:29.662663Z'
---

<!-- kb:auto-start -->
## 业务结论

包含2个可观察业务阶段。

## 业务阶段

- `返回或结束分支：this.execute(request, RefundOrderServiceEnum.SYNC_ORDER, OrderSourceEnum.COMMON, request.getTraceId(), request.getTraceId())`
- `返回或结束分支：createErrorResponse(request, e, BaseResponse.class)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `ToolFacadeImpl.java ToolFacadeImpl#syncOrder`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
