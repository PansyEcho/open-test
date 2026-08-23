---
node_id: logic:semantic:d752b47abfc1e94fd5a1
system_id: ifightchainsaas.java.refund.core
kind: common_logic
title: AbstractFacade.createErrorResponse
summary: 该方法被31个知识入口复用，符号解析状态为resolved。
aliases:
- semantic:d752b47abfc1e94fd5a1
- com.ly.flight.chainsaas.refund.facade.impl.AbstractFacade#createErrorResponse(Request,com.ly.flight.chainsaas.refund.facade.exception.APIException,java.lang.Class<Response>)
- com.ly.flight.chainsaas.refund.facade.impl.CallbackFacadeImpl#refundApplyCallback(com.ly.flight.chainsaas.refund.facade.model.request.RefundApplyCallbackRequest)
- com.ly.flight.chainsaas.refund.facade.impl.CallbackFacadeImpl#refundConfirmCallback(com.ly.flight.chainsaas.refund.facade.model.request.RefundConfirmCallbackRequest)
- com.ly.flight.chainsaas.refund.facade.impl.CommonFacadeImpl#executeJob(com.ly.flight.chainsaas.refund.facade.model.request.JobRequest)
- com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterCancelRequest)
- com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#pageBusinessLog(com.ly.flight.chainsaas.refund.facade.model.request.RefundBusinessLogRequest)
- com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#queryDetailByRefundNo(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterOrderDetailRequest)
- com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterOrderQueryRequest)
- com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#refundConfirm(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterConfirmRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundDistributionFacadeImpl#queryDetail(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderDetailRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundDistributionFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#applyToAirline(com.ly.flight.chainsaas.refund.facade.model.request.RefundApplyToAirlineRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#autoRefund(com.ly.flight.chainsaas.refund.facade.model.request.AutoRefundRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#autoRefundReshop(com.ly.flight.chainsaas.refund.facade.model.request.RefundCheckRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createLog(com.ly.flight.chainsaas.refund.facade.model.request.CreateLogRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createPayment(com.ly.flight.chainsaas.refund.facade.model.request.PaymentInfoRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#getPlatFee(com.ly.flight.chainsaas.refund.facade.model.request.PlatFeeRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#lockOrder(com.ly.flight.chainsaas.refund.facade.model.request.LockOrderRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryDetailByOrderNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundSerialNoRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryDetailByRefundNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderDetailRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryListByOrderNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundSerialNoRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundConfirm(com.ly.flight.chainsaas.refund.facade.model.request.RefundConfirmRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshop(com.ly.flight.chainsaas.refund.facade.model.request.RefundReshopRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshopSubmit(com.ly.flight.chainsaas.refund.facade.model.request.OrderReshopSubmitRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#ticketRefunding(com.ly.flight.chainsaas.refund.facade.model.request.TicketRefundingRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#unLockOrder(com.ly.flight.chainsaas.refund.facade.model.request.UnLockOrderRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#voucherRefundSubmit(com.ly.flight.chainsaas.refund.facade.model.request.VoucherRefundSubmitRequest)
- com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#walletRefundRetry(com.ly.flight.chainsaas.refund.facade.model.request.WalletRefundRetryRequest)
- com.ly.flight.chainsaas.refund.facade.impl.ToolFacadeImpl#syncOrder(com.ly.flight.chainsaas.refund.facade.model.request.SyncRefundOrderRequest)
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/AbstractFacade.java
  symbol: com.ly.flight.chainsaas.refund.facade.impl.AbstractFacade#createErrorResponse(Request,com.ly.flight.chainsaas.refund.facade.exception.APIException,java.lang.Class<Response>)
  line: 182
  commit: ''
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  analysis_depth: semantic
  resolution_status: resolved
  reuse_entry_count: 31
  entry_point_ids:
  - com.ly.flight.chainsaas.refund.facade.impl.CallbackFacadeImpl#refundApplyCallback(com.ly.flight.chainsaas.refund.facade.model.request.RefundApplyCallbackRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.CallbackFacadeImpl#refundConfirmCallback(com.ly.flight.chainsaas.refund.facade.model.request.RefundConfirmCallbackRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.CommonFacadeImpl#executeJob(com.ly.flight.chainsaas.refund.facade.model.request.JobRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterCancelRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#pageBusinessLog(com.ly.flight.chainsaas.refund.facade.model.request.RefundBusinessLogRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#queryDetailByRefundNo(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterOrderDetailRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterOrderQueryRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#refundConfirm(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterConfirmRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundDistributionFacadeImpl#queryDetail(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderDetailRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundDistributionFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#applyToAirline(com.ly.flight.chainsaas.refund.facade.model.request.RefundApplyToAirlineRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#autoRefund(com.ly.flight.chainsaas.refund.facade.model.request.AutoRefundRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#autoRefundReshop(com.ly.flight.chainsaas.refund.facade.model.request.RefundCheckRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createLog(com.ly.flight.chainsaas.refund.facade.model.request.CreateLogRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createPayment(com.ly.flight.chainsaas.refund.facade.model.request.PaymentInfoRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#getPlatFee(com.ly.flight.chainsaas.refund.facade.model.request.PlatFeeRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#lockOrder(com.ly.flight.chainsaas.refund.facade.model.request.LockOrderRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryDetailByOrderNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundSerialNoRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryDetailByRefundNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderDetailRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryListByOrderNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundSerialNoRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundConfirm(com.ly.flight.chainsaas.refund.facade.model.request.RefundConfirmRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshop(com.ly.flight.chainsaas.refund.facade.model.request.RefundReshopRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshopSubmit(com.ly.flight.chainsaas.refund.facade.model.request.OrderReshopSubmitRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#ticketRefunding(com.ly.flight.chainsaas.refund.facade.model.request.TicketRefundingRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#unLockOrder(com.ly.flight.chainsaas.refund.facade.model.request.UnLockOrderRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#voucherRefundSubmit(com.ly.flight.chainsaas.refund.facade.model.request.VoucherRefundSubmitRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#walletRefundRetry(com.ly.flight.chainsaas.refund.facade.model.request.WalletRefundRetryRequest)
  - com.ly.flight.chainsaas.refund.facade.impl.ToolFacadeImpl#syncOrder(com.ly.flight.chainsaas.refund.facade.model.request.SyncRefundOrderRequest)
  patterns: []
updated_at: '2026-08-22T17:17:29.350995Z'
---

<!-- kb:auto-start -->
## 业务结论

该方法被31个知识入口复用，符号解析状态为resolved。

## 复用入口

- `com.ly.flight.chainsaas.refund.facade.impl.CallbackFacadeImpl#refundApplyCallback(com.ly.flight.chainsaas.refund.facade.model.request.RefundApplyCallbackRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.CallbackFacadeImpl#refundConfirmCallback(com.ly.flight.chainsaas.refund.facade.model.request.RefundConfirmCallbackRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.CommonFacadeImpl#executeJob(com.ly.flight.chainsaas.refund.facade.model.request.JobRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterCancelRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#pageBusinessLog(com.ly.flight.chainsaas.refund.facade.model.request.RefundBusinessLogRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#queryDetailByRefundNo(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterOrderDetailRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterOrderQueryRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.OuterRefundFacadeImpl#refundConfirm(com.ly.flight.chainsaas.refund.facade.model.outer.request.RefundOuterConfirmRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundDistributionFacadeImpl#queryDetail(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderDetailRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundDistributionFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#applyToAirline(com.ly.flight.chainsaas.refund.facade.model.request.RefundApplyToAirlineRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#autoRefund(com.ly.flight.chainsaas.refund.facade.model.request.AutoRefundRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#autoRefundReshop(com.ly.flight.chainsaas.refund.facade.model.request.RefundCheckRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createLog(com.ly.flight.chainsaas.refund.facade.model.request.CreateLogRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createPayment(com.ly.flight.chainsaas.refund.facade.model.request.PaymentInfoRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#getPlatFee(com.ly.flight.chainsaas.refund.facade.model.request.PlatFeeRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#lockOrder(com.ly.flight.chainsaas.refund.facade.model.request.LockOrderRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryDetailByOrderNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundSerialNoRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryDetailByRefundNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderDetailRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryListByOrderNo(com.ly.flight.chainsaas.refund.facade.model.request.RefundSerialNoRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundConfirm(com.ly.flight.chainsaas.refund.facade.model.request.RefundConfirmRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshop(com.ly.flight.chainsaas.refund.facade.model.request.RefundReshopRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#refundReshopSubmit(com.ly.flight.chainsaas.refund.facade.model.request.OrderReshopSubmitRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#ticketRefunding(com.ly.flight.chainsaas.refund.facade.model.request.TicketRefundingRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#unLockOrder(com.ly.flight.chainsaas.refund.facade.model.request.UnLockOrderRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#voucherRefundSubmit(com.ly.flight.chainsaas.refund.facade.model.request.VoucherRefundSubmitRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#walletRefundRetry(com.ly.flight.chainsaas.refund.facade.model.request.WalletRefundRetryRequest)`
- `com.ly.flight.chainsaas.refund.facade.impl.ToolFacadeImpl#syncOrder(com.ly.flight.chainsaas.refund.facade.model.request.SyncRefundOrderRequest)`

## 模式证据

- 未发现高置信度特定模式；按通用共享逻辑展示

## 源码证据

- `app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/AbstractFacade.java:182 · com.ly.flight.chainsaas.refund.facade.impl.AbstractFacade#createErrorResponse(Request,com.ly.flight.chainsaas.refund.facade.exception.APIException,java.lang.Class<Response>)`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
