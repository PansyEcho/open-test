---
node_id: transition:RefundOrderStateEnum:RefundOrderSuccessPreActor:38
system_id: ifightchainsaas.java.refund.core
kind: state_transition
title: WAIT_REFUND/REFUNDING/REFUND_FAIL → REFUND_SUCCESS
summary: 订单从WAIT_REFUND/REFUNDING/REFUND_FAIL流转到REFUND_SUCCESS；包含11个可观察业务阶段，包含5个条件分支，调用2个服务/仓储/缓存或消息协作者，产生2项状态或数据副作用。
aliases:
- transition:RefundOrderStateEnum:RefundOrderSuccessPreActor:38
- RefundOrderSuccessPreActor
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/pre/RefundOrderSuccessPreActor.java
  symbol: RefundOrderSuccessPreActor
  line: 42
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  phase: pre
updated_at: '2026-08-22T17:17:29.748351Z'
---

<!-- kb:auto-start -->
## 业务结论

订单从WAIT_REFUND/REFUNDING/REFUND_FAIL流转到REFUND_SUCCESS；包含11个可观察业务阶段，包含5个条件分支，调用2个服务/仓储/缓存或消息协作者，产生2项状态或数据副作用。

## 业务阶段

- `自动根据返回的数据保存,或者自动失败，人工处理`
- `手动根据传入的数据更新`
- `遍历乘客`
- `遍历一个乘客下所有票信息`
- `返回或结束分支：true`
- `返回或结束分支：*/ private List<UpdateTicketNoParameter> convertAuto(RefundConfirmResponse response, SaasRefundOrderVO orderVO) throws OrderException { List<PassengerRefundResInfo> passengers = response.getPassengerInfos()`
- `返回或结束分支：result`
- `返回或结束分支：*/ private List<UpdateTicketNoParameter> convertAuto(VoidingConfirmResponse response, SaasRefundOrderVO orderVO) throws OrderException { List<PassengerRefundResInfo> passengers = response.getPassengerInfos()`
- `返回或结束分支：*/ private List<UpdateTicketNoParameter> convertManual(RefundConfirmRequest request, SaasRefundOrderVO orderVO) throws OrderException { List<SaasRefundOrderPassagerVO> passengers = PsiUtils.getPassengers(orderVO.getPsis())`
- `返回或结束分支：*/ private boolean passengerMatch(SaasRefundOrderPsiVO psivo, String firstName, String secondName) { SaasRefundOrderPassagerVO passengerVO = psivo.getPassenger()`
- `返回或结束分支：StringUtils.equalsIgnoreCase(passengerVO.getFirstName() + passengerVO.getLastName(), firstName + secondName)`

## 条件与分支

- `saasChangeOrderVO.getIsAuto(`
- `response != null`
- `voidingConfirmResponse != null`
- `valid`
- `valid`

## 外部交互

- `orderService.queryByRefundSerialNo`
- `itemService.updateTicketNo`

## 状态与副作用

- `itemService.updateTicketNo`
- `UpdateTicketNoParameter`

## 源码证据

- `RefundOrderSuccessPreActor.java RefundOrderSuccessPreActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
