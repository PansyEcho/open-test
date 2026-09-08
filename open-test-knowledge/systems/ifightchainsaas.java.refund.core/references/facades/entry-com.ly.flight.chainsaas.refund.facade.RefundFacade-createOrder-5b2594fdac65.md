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
  symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder
  line: 223
  commit: 99b494d7824eab12ffc237ae7e945aac79d61411
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#invoke
  line: 125
  commit: 99b494d7824eab12ffc237ae7e945aac79d61411
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/CreateRefundOrderValidator.java
  symbol: com.ly.flight.chainsaas.refund.facade.validator.trade.CreateRefundOrderValidator#validate
  line: 28
  commit: 99b494d7824eab12ffc237ae7e945aac79d61411
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker
  line: 82
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
- kind: main_flow
  title: 创建请求路由
  condition: 请求通过CreateRefundOrderValidator结构校验
  expected_outcome: 调用execute(request, RefundOrderServiceEnum.CREATE_ORDER, OrderSourceEnum.COMMON,
    traceId, orderSerialNo)进入退票创建编排。
- kind: validation
  title: 创建请求必填校验
  condition: traceId、refundDetailApiDTO、原订单号、refundSubCategory、航段集合或乘客集合为空
  expected_outcome: CreateRefundOrderValidator抛出ValidationException，不进入加锁、原单查询和落单流程。
- kind: failure
  title: 入口异常转换与上下文清理
  condition: execute或下游抛出APIException，或请求正常完成
  expected_outcome: APIException转换为CreateRefundOrderResponse失败结果，并执行LogContextUtils.removeAll。
metadata:
  scan_id: scan-20260902095328-66619d80f6-47b8cbc3
  tool_id: facade.refund.create_order
  analysis_depth: business
  branch_count: 0
  external_call_count: 1
  owned_analysis_symbols:
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder
  - com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#invoke
  - com.ly.flight.chainsaas.refund.facade.validator.trade.CreateRefundOrderValidator#validate
invocation_contract: null
input_contract:
  contract_version: operation-input-knowledge/v1
  target_id: facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder
  request_type: com.ly.flight.chainsaas.refund.enums.RefundSourceEnum
  source_scan_id: scan-20260902095328-66619d80f6-47b8cbc3
  status: BLOCKED
  request_schema:
    type: object
    properties: {}
    additionalProperties: false
  fields: []
  blocked_reason: 请求字段Schema路径冲突：channelEnum.code
entry_fact_knowledge: null
updated_at: '2026-09-07T21:09:34.909196Z'
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

- `RefundFacadeImpl.java com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder`


## 入口内调用节点：com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#invoke

## 业务结论

包含3个可观察业务阶段，调用1个服务/仓储/缓存或消息协作者，产生2项状态或数据副作用。

## 业务阶段

- `返回或结束分支：serviceInvokerLockDelegate.invokeWithLock(new InvokeLockCommand<TradeResponse<CreateRefundOrderResponse>>() { @Override public String lockKey() { return OrderConstants.ORDER_OPERATE_ + orderSerialNo`
- `返回或结束分支：orderSerialNo`
- `返回或结束分支：innerInvoke(request)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `serviceInvokerLockDelegate.invokeWithLock`

## 状态与副作用

- `serviceInvokerLockDelegate.invokeWithLock`
- `lockKey`

## 源码证据

- `CreateRefundOrderInvoker.java com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#invoke`


## 入口内调用节点：com.ly.flight.chainsaas.refund.facade.validator.trade.CreateRefundOrderValidator#validate

## 业务结论

当前源码仅能证明该入口或方法存在，未直接提取到条件、外部交互或状态副作用。

## 业务阶段

- `未从当前方法直接证明`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `CreateRefundOrderValidator.java com.ly.flight.chainsaas.refund.facade.validator.trade.CreateRefundOrderValidator#validate`

## Agent代码解释（INFERRED）

RefundFacadeImpl#createOrder统一接收创建退票请求，生成或沿用traceId后以RefundOrderServiceEnum.CREATE_ORDER和OrderSourceEnum.COMMON路由到创建编排；APIException转换为统一失败响应，并在finally清理日志上下文。路由前由CreateRefundOrderValidator校验traceId、退票详情、原订单号、退票子类型、航段集合和乘客集合。

### 完整业务分析

#### 业务目的

为运营后台人工退票、白屏分销创建及自动化失败转人工建立退票订单留痕。入口负责统一路由和异常边界，创建编排负责原单校验、重复操作控制、退票上下文构造、订单及关联数据落库，并按条件触发CBDS退票申请和通知；最终退款金额结算由后续流程负责。

#### 适用场景

适用于运营人员创建普通退票单、白屏或自动路径创建退票单，以及自动核价或自动确认失败后在同一退票单转人工处理的场景。OrderRefundTypeEnum.INVALID废票也经过此入口，但废票不会调用CBDS refundApply。

#### 输入、默认值与过滤分页语义

请求必须包含traceId、refundDetailApiDTO；其内部必须有原订单号orderSerialNo、退票子类型refundSubCategory、航段集合segmentRefundInfos和乘客集合refundItemInfos。auto为true时默认RefundChannelEnum.WHITE_DISTRIBUTION，否则默认RefundChannelEnum.BUSINESS_MANAGE；非空channelEnum覆盖默认值。operator用于业务日志操作者，空值时使用系统操作者。原订单号同时作为加锁和原单查询关键字。

#### 返回组装与空结果语义

成功时CreateRefundOrderResponse设置success=true和traceId；请求为TOC或auto时回填新建退票订单。原单查询返回null或无SaasOrderVO时返回失败并设置ErrorMessageEnum.ORDER_NOT_EXIST；SAPL全航段限制、多PNR、处理中退票或改签单分别返回失败码405、406、404及对应业务信息；APIException由Facade转换为统一失败响应。

#### 完整业务流程

RefundFacadeImpl#createOrder先生成traceId，再以RefundOrderServiceEnum.CREATE_ORDER和OrderSourceEnum.COMMON调用execute；CreateRefundOrderValidator校验请求结构。CreateRefundOrderInvoker按原订单号构造OrderConstants.ORDER_OPERATE_锁键，在锁内先检查重复退票，再通过bookOrderClient查询原单，依次校验原单存在、SAPL全退限制、单退票单单PNR和处理中退票/改签单。通过后按auto或显式channelEnum初始化OrderContext并执行废票校验，调用OrderServiceImpl#saveOrder事务落库；随后写AUTO_REFUND_CREATE或REFUND_CREATE业务日志，发送企微和邮件通知。原单GDS为GdsEnum.SAPL、OfficeNoUtils.isCbds为true且refundSubCategory不是OrderRefundTypeEnum.INVALID时调用cbdsService.refundApply。

#### 重要条件分支、计算与外部调用

CreateRefundOrderValidator校验traceId、退票详情、原订单号、退票子类型、航段集合和乘客集合，失败抛ValidationException。原单为空返回ErrorMessageEnum.ORDER_NOT_EXIST；saplLimitCheck失败返回405和ErrorMessageEnum.CBDS_NEED_ALL_REFUND；checkMultiPnrLimit命中返回406；createRefundValidator发现处理中退票单或改签单返回404，并按type设置ErrorMessageEnum.HAS_REFUND_ORDER或ErrorMessageEnum.HAS_CHANGE_ORDER。auto默认RefundChannelEnum.WHITE_DISTRIBUTION，非auto默认RefundChannelEnum.BUSINESS_MANAGE，但非空channelEnum优先；OrderRefundTypeEnum.INVALID、非GdsEnum.SAPL或非CBDS OfficeNo均跳过cbdsService.refundApply；TOC或auto响应回填order。

#### 异常与失败处理

入口通过ValidationException拒绝结构不完整请求，APIException转换为统一失败响应并在finally清理日志上下文。加锁避免同一原订单号并发重复创建；业务层对重复单、原单不存在、SAPL限制、多个PNR和处理中退改单返回明确失败结果。innerInvoke捕获OrderException并按错误码和消息构造失败响应，捕获IntegrationException设置失败；事务saveOrder异常时回滚订单及关联数据。CBDS或后续异步流程没有回调时保持对应处理中状态，自动化失败沿用同一退票单转人工，不新建退票单。

#### 测试 Oracle

验证必填字段缺失抛ValidationException且不调用原单查询或落单；模拟bookOrderClient返回空响应，断言success=false、bizCode为ErrorMessageEnum.ORDER_NOT_EXIST。覆盖SAPL限制、多PNR、处理中退票单和改签单，断言405/406/404及对应业务码；验证auto默认渠道、显式channelEnum覆盖和人工/自动日志类型；验证saveOrder事务写入主单及乘客、航段、item、itemFee、psi；分别验证OrderRefundTypeEnum.INVALID、非SAPL、非CBDS OfficeNo不调用cbdsService.refundApply，满足三条件时调用；验证APIException统一转换、OrderException/IntegrationException失败结果和finally上下文清理。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
