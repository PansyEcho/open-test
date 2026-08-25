---
node_id: entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder
system_id: ifightchainsaas.java.refund.core
kind: facade
title: RefundFacade#createOrder
summary: 包含2个可观察业务阶段。
aliases:
- facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder
- com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder
- RefundFacade#createOrder
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: RefundFacadeImpl#createOrder
  line: 223
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: CreateRefundOrderInvoker#invoke
  line: 125
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: CreateRefundOrderInvoker#innerInvoke
  line: 145
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/resources/BookOrderClient.java
  symbol: BookOrderClient#getOrderDetail
  line: 18
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: RefundFacade#createOrder
  line: 36
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/CreateRefundOrderValidator.java
  symbol: CreateRefundOrderValidator#validate
  line: 28
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/invoke/ServiceInvokerLockDelegate.java
  symbol: ServiceInvokerLockDelegate#invokeWithLock
  line: 29
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: CreateRefundOrderInvoker#initContext
  line: 248
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: CreateRefundOrderInvoker#checkDuplicateorder
  line: 347
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/resources/BookOrderClientImpl.java
  symbol: BookOrderClientImpl#getOrderDetail
  line: 40
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/proxy/ChangeFacadeProxy.java
  symbol: ChangeFacadeProxy#changeOrderByType
  line: 50
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/validator/RefundValidator.java
  symbol: RefundValidator#createRefundValidator
  line: 70
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/validator/RefundValidator.java
  symbol: RefundValidator#invalidity
  line: 246
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/OrderBuilder.java
  symbol: OrderBuilder#build
  line: 77
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/OrderBuilder.java
  symbol: OrderBuilder#buildOrder
  line: 97
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/PassengerBuilder.java
  symbol: PassengerBuilder#buildPassengers
  line: 56
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/SegmentBuilder.java
  symbol: SegmentBuilder#buildSegments
  line: 72
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/PsiBuilder.java
  symbol: PsiBuilder#buildTicketPsis
  line: 64
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/PsiBuilder.java
  symbol: PsiBuilder#buildTicketItem
  line: 147
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#queryOrderListByPassengerName
  line: 223
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#saveOrder
  line: 410
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: SaasRefundOrderDAOProxy#insert
  line: 81
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/CBDSServiceImpl.java
  symbol: CBDSServiceImpl#refundApply
  line: 48
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/LoggerWriterServiceImpl.java
  symbol: LoggerWriterServiceImpl#sendLogger
  line: 32
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/CreateRefundOrderRequest.java
  symbol: CreateRefundOrderRequest
  line: 21
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/response/CreateRefundOrderResponse.java
  symbol: CreateRefundOrderResponse
  line: 14
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/OrderRefundTypeEnum.java
  symbol: OrderRefundTypeEnum
  line: 18
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/InvoluntaryRefundTypeEnum.java
  symbol: InvoluntaryRefundTypeEnum
  line: 8
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/RefundOrderStateEnum.java
  symbol: RefundOrderStateEnum
  line: 12
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260825064756-a0f437c374-f87d9c32
  tool_id: facade.refund.create_order
  analysis_depth: business
  branch_count: 0
  external_call_count: 0
invocation_contract: null
updated_at: '2026-08-25T09:50:06.917379Z'
---


<!-- kb:auto-start -->
## 业务结论

包含2个可观察业务阶段。

## 业务阶段

- `返回或结束分支：this.execute(request, RefundOrderServiceEnum.CREATE_ORDER, OrderSourceEnum.COMMON, request.getTraceId(), request.getRefundDetailApiDTO().getOrderRefundInfo().getOrderSerialNo())`
- `返回或结束分支：createErrorResponse(request, e, CreateRefundOrderResponse.class)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundFacadeImpl.java RefundFacadeImpl#createOrder`

## Agent代码解释（INFERRED）

createOrder是SaaS国际机票退票申请写入口，首次生成系统退票号并保存SaasRefundOrderVO、乘客、航段、item、itemFee、PSI，普通初态PENDING_APPLY；不代表已核价、退票成功或钱包退款完成。

适用场景：运营人工(isAuto=false，默认BUSINESS_MANAGE、人工轨迹，普通非TOC成功order可空)；白屏自动(isAuto=true，默认WHITE_DISTRIBUTION、自动轨迹并返回order，但AUTO仍受权限/GDS/乘客范围/类型/改签/私有资源限制)；自动失败后转人工的首次建单/留底；当日作废(有VOIDING_SEARCH权限先核验，可INVALID，不发CBDS)；SAPL+CBDS普通全航段退(事务后核价)；普通非CBDS/非SAPL；TOC(非自动也返回order)。原单不存在、历史重复、处理中退/改单、多PNR、CBDS少航段、废票核验失败禁止；不适用于查询。

输入：traceId由Facade补齐；operator为空时普通轨迹回退系统操作人。refundDetailApiDTO、orderRefundInfo、orderSerialNo、refundSubCategory、segmentRefundInfos、refundItemInfos必填。orderSerialNo是booking.core原单号和锁键；请求refundSerialNo仅写thirdRefundSerialNo，系统号另生成；otherSerialNo未用。refundSubCategory真实0非自愿/1自愿/2当日作废；involuntaryRefundType 1航变/2病退/3拒签/4错购；非自愿非航变不能自动；vouchers进扩展。
segmentRefundInfos只校验非空，实际航段来自refundItemInfos.passSegs.segmentInfo，时间yyyy-MM-dd HH:mm:ss；按出发城市+到达城市+sequence去重排序并从原单补业务字段。refundItemInfos逐项不判空；乘客按姓名匹配原单。
passengerIds/segmentIds用于处理中单、改单、CBDS全航段、PNR。非IJ冲突检查把segmentIds置null改按乘客；此前CBDS/PNR仍用原值。两者未直接必填。orderChannelSource原样写，未传int为0；isAuto控制默认渠道/日志/响应order，channelEnum可覆盖；memberId写订单，language写扩展；refundSource未用；contactInfoDTO未复制进上下文。
自动标记非isAuto直传：非Amadeus具备范围资格，Amadeus仅全乘客；还需供应商权限、非“非自愿非航变”、无完成改单；私有资源MANUAL；作废有权限INVALID，否则MANUAL。

流程：Facade经Validator分发CreateRefundOrderInvoker，按ORDER_OPERATE_+原单号加锁。历史防重逐乘客固定pageSize=1000查AUDITED/REFUND_DONE，同姓名且flightNo+gmtTakeOff命中LY0510300025；createOrder无对外分页。
通过BookOrderClient调用booking.core；原单对象空返回code=-1、bizCode10000003。SAPL+CBDS少航段返回405/20000009；多PNR返回406。处理中状态含PENDING_APPLY、RESHOPING、AUDITED、WAIT_REFUND、REFUNDING、REFUND_SUCCESS、REFUND_DONE，指定航段还需sequence交集；再查endorse.core，命中返回404和existOrderDTO(type1退票/0改签)、bizCode20000005/20000004。
查询供应商/改签后构造订单：默认PENDING_APPLY、UNDONE、UN_LOCK、NO代金券、供采金额0、auditPassSync/confirmSync/eventState=0；其他字段继承原单/供应商，Galileo优先hostLevelPnr。PSI为退票乘客×去重航段；item复制原票字段，退款金额/罚金/已用/服务费等为0。
有权限作废落库前resource.core voidingSearch，失败/异常LY0110000004。saveOrder在rollbackFor=Exception事务写订单、乘客、航段、item、itemFee、PSI并补supplyChannel/refundChangeId/monitorKey。事务后发轨迹、企微；SAPL+CBDS非作废refundSearch并尝试RESHOPING；最后发申请通知。CBDS内部吞异常。

输出/失败：响应含success/code/message/traceId、order、existOrderDTO、bizCode。仅TOC或request.isAuto成功返回order；普通非自动非TOC order=null正常。锁失败LY0110000005，未知异常-1。Facade在Validator前解引用嵌套对象，null可NPE。BookOrderClient异常/null/失败转IntegrationException；innerInvoke只置success=false，code/message/traceId可空。DB事务仅saveOrder，事务后异常可能响应失败但订单已提交。

Oracle：并发失败LY0110000005；历史重复LY0510300025且零新增；原单空(-1,10000003)；CBDS少航段(405,20000009)；多PNR406；处理中单404并核对existOrderDTO/bizCode；废票失败LY0110000004且零写入。成功断言1订单、乘客数=refundItemInfos、航段去重排序、PSI/item/itemFee数=乘客数×航段数、共享refundSerialNo/orderSerialNo/traceId/env、订单PENDING_APPLY/未锁/未申请/金额0。覆盖自动枚举、通知、CBDS和order可见性。

### 完整业务分析

#### 业务目的

首次落退票申请及核心PSI，PENDING_APPLY，支撑后续生命周期，不等于最终退款。

#### 适用场景

运营人工、白屏自动、自动失败转人工首次留底、当日作废、SAPL+CBDS全航段、普通非CBDS/非SAPL、TOC；说明渠道、轨迹、资源动作和返回差异。不适用于查询；原单空、历史重复、处理中退/改单、多PNR、CBDS少航段、废票失败禁止。

#### 输入、默认值与过滤分页语义

顶层/嵌套、枚举、默认、未用字段、日期、航段来源差异、空风险。

#### 返回组装与空结果语义

公共响应、order、existOrderDTO、bizCode、成功空order。

#### 完整业务流程

Facade、Invoker锁、防重校验、booking远程边界、构造、多表事务、后置副作用。

#### 重要条件分支、计算与外部调用

防重、Changing、IJ、CBDS、多PNR、Amadeus、权限、私有、非自愿、作废、渠道。

#### 异常与失败处理

锁、原单、集成空字段、业务/未知异常、回滚及事务后已落单风险。

#### 测试 Oracle

错误码、零写入、数量初态、自动枚举、CBDS/通知、order可见性。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
