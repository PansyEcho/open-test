---
node_id: entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#refundReshopSubmit
system_id: ifightchainsaas.java.refund.core
kind: facade
title: RefundFacade#refundReshopSubmit
summary: 包含2个可观察业务阶段。
aliases:
- facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#refundReshopSubmit
- com.ly.flight.chainsaas.refund.facade.RefundFacade#refundReshopSubmit
- RefundFacade#refundReshopSubmit
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshopSubmit
  line: 117
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: RefundFacade#refundReshopSubmit
  line: 153
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: RefundFacadeImpl#refundReshopSubmit
  line: 117
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/RefundReshopSubmitValidator.java
  symbol: RefundReshopSubmitValidator#validate
  line: 26
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundReshopSubmitServiceInvoker.java
  symbol: RefundReshopSubmitServiceInvoker#invoke
  line: 74
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundReshopSubmitServiceInvoker.java
  symbol: RefundReshopSubmitServiceInvoker#innerInvoke
  line: 93
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundReshopSubmitServiceInvoker.java
  symbol: RefundReshopSubmitServiceInvoker#doInvoke
  line: 103
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/AbstractOrderServiceInvoker.java
  symbol: AbstractOrderServiceInvoker#queryOrderByRefundSerialNo
  line: 76
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: OrderService#queryByRefundSerialNo
  line: 60
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#queryByRefundSerialNo
  line: 250
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/AbstractOrderService.java
  symbol: AbstractOrderService
  line: 11
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: SaasRefundOrderDAOProxy#queryByRefundSerialNo
  line: 51
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260825075610-a0f437c374-8132c1a1
  tool_id: facade.refund.refund_reshop_submit
  analysis_depth: business
  branch_count: 0
  external_call_count: 0
invocation_contract: null
updated_at: '2026-08-26T02:44:11.853343Z'
---


<!-- kb:auto-start -->
## 业务结论

包含2个可观察业务阶段。

## 业务阶段

- `返回或结束分支：this.execute(request, RefundOrderServiceEnum.REFUND_RESHOP_SUBMIT, OrderSourceEnum.COMMON, request.getTraceId(), request.getRefundSerialNo())`
- `返回或结束分支：createErrorResponse(request, e, OrderReshopSubmitResponse.class)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundFacadeImpl.java com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshopSubmit`

## Agent代码解释（INFERRED）

退改审核确认入口，生成traceId并路由REFUND_RESHOP_SUBMIT，异常转失败响应并清理上下文。

### 完整业务分析

#### 业务目的

退改核价或退票申请后提交审核确认，将有效退票单审核通过并保存报价信息。

#### 适用场景

适用于PENDING_APPLY或RESHOPING，不适用于其他状态或最终确认退票。

#### 输入、默认值与过滤分页语义

traceId、operator、merchantToBuyerRate、refundSerialNo必填；feeType、taxDetailList、waiverCode、isVoucher表示费用类型、税项、非自愿标识和代金券；refundChargeInfoVO与auditDate虽标注必填但本Validator未校验。

#### 返回组装与空结果语义

成功响应success=true；异常返回失败响应。

#### 完整业务流程

Facade校验、加锁、查单、状态校验后转AUDITED，前后置Actor保存信息并追加任务。

#### 重要条件分支、计算与外部调用

订单不存在、状态错误、非CBDS代金券或航司不支持均失败；CBDS代金券强制人工；出票详情为空跳过价格更新。

#### 异常与失败处理

校验或更新失败不转状态；无分页，auditDate仅作有效期字段，本入口不计算超时。

#### 测试 Oracle

合法请求成功进入AUDITED并保存费用；缺参、税项不合法、waiverCode超长、订单不存在、状态错误、代金券条件不符均失败；同一退票单加锁。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
