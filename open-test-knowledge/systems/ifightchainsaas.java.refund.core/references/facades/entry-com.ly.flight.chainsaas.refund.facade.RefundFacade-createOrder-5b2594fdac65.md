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
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#invoke
  line: 125
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/CreateRefundOrderValidator.java
  symbol: com.ly.flight.chainsaas.refund.facade.validator.trade.CreateRefundOrderValidator#validate
  line: 28
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#innerInvoke
  line: 145
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/OrderBuilder.java
  symbol: com.ly.flight.chainsaas.refund.biz.builder.impl.OrderBuilder#buildOrder
  line: 97
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#saveOrder
  line: 410
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/converter/OrderConverter.java
  symbol: com.ly.flight.chainsaas.refund.biz.converter.OrderConverter#vo2do
  line: 28
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
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.OrderService#saveOrder
  line: 107
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#innerInvoke
  line: 208
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
- kind: main_flow
  title: 创建待申请退票单
  condition: 正式原订单Fact与请求明细满足校验
  expected_outcome: 创建成功后可由查询能力取得RefundOrder(PENDING_APPLY)
- kind: validation
  title: 原订单不存在
  condition: Booking查询不到原订单
  expected_outcome: 返回失败且不产生退票单
- kind: failure
  title: 保存失败
  condition: 持久化抛出异常
  expected_outcome: 事务回滚且不能宣称produced fact
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  tool_id: facade.refund.create_order
  analysis_depth: business
  branch_count: 0
  external_call_count: 1
  owned_analysis_symbols:
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder
  - com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#invoke
  - com.ly.flight.chainsaas.refund.facade.validator.trade.CreateRefundOrderValidator#validate
invocation_contract: null
entry_fact_knowledge:
  entry_id: facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder
  source_scan_id: scan-20260827223314-a0f437c374-27423ce1
  source_baseline:
    source_path: /Users/user/data/code/tc/ifightchainsaas.java.refund.core
    commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
    branch: feature_673598_20260806
    dirty: false
    dirty_digest: ''
    analyzer_version: 0.2.0
    captured_at: '2026-08-27T22:33:14.750680Z'
  requires_facts: []
  produces_facts:
  - assertion_id: entry-fact:refund-create-current-v3-produces-pending-order
    assertion_type: PRODUCES_FACT
    slot_id: refund_order
    fact_contract_id: refund-order/v3
    required_state: ''
    produced_state: PENDING_APPLY
    from_state: ''
    to_state: ''
    operation_role: ''
    candidate_system_id: ''
    candidate_operation_id: ''
    query_availability: null
    request_path: ''
    fact_path: ''
    cardinality: 1
    acquisition_policy: ''
    constraints: []
    relations: []
    source: CODE_PROVEN
    evidence_refs:
    - repository: ''
      path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
      symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#innerInvoke(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest):entity_lifecycle
      line: 208
      commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
      content_digest: ''
    - repository: ''
      path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/OrderBuilder.java
      symbol: com.ly.flight.chainsaas.refund.biz.builder.impl.OrderBuilder#buildOrder(com.ly.flight.chainsaas.refund.biz.service.context.OrderContext):state-assignment
      line: 122
      commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
      content_digest: ''
    - repository: ''
      path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
      symbol: com.ly.flight.chainsaas.refund.dal.proxy.SaasRefundOrderDAOProxy#insert(com.ly.flight.chainsaas.refund.dal.model.SaasRefundOrderDO)
      line: 419
      commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
      content_digest: ''
    confirmed_assertion_id: ''
  state_transitions: []
  candidate_operations:
  - assertion_id: entry-fact:refund-create-current-v3-create-operation
    assertion_type: CANDIDATE_OPERATION
    slot_id: refund_order
    fact_contract_id: refund-order/v3
    required_state: ''
    produced_state: ''
    from_state: ''
    to_state: ''
    operation_role: CREATE
    candidate_system_id: ifightchainsaas.java.refund.core
    candidate_operation_id: candidate:ifightchainsaas.java.refund.core:com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)
    query_availability: null
    request_path: ''
    fact_path: ''
    cardinality: 1
    acquisition_policy: ''
    constraints: []
    relations: []
    source: CODE_PROVEN
    evidence_refs:
    - repository: ''
      path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
      symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)
      line: 217
      commit: ''
      content_digest: ''
    - repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
      symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)
      line: 32
      commit: ''
      content_digest: ''
    - repository: ''
      path: app/facade-impl/src/main/resources/META-INF/spring/refundcore-facade-impl-trade-rpc.xml
      symbol: dsf.ifightchainsaas.refund.core
      line: 13
      commit: ''
      content_digest: ''
    - repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
      symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder
      line: 36
      commit: ''
      content_digest: ''
    confirmed_assertion_id: ''
  binding_paths: []
  evidence_refs:
  - repository: ''
    path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/CreateRefundOrderInvoker.java
    symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.CreateRefundOrderInvoker#innerInvoke(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest):entity_lifecycle
    line: 208
    commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
    content_digest: ''
  - repository: ''
    path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/builder/impl/OrderBuilder.java
    symbol: com.ly.flight.chainsaas.refund.biz.builder.impl.OrderBuilder#buildOrder(com.ly.flight.chainsaas.refund.biz.service.context.OrderContext):state-assignment
    line: 122
    commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
    content_digest: ''
  - repository: ''
    path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
    symbol: com.ly.flight.chainsaas.refund.dal.proxy.SaasRefundOrderDAOProxy#insert(com.ly.flight.chainsaas.refund.dal.model.SaasRefundOrderDO)
    line: 419
    commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
    content_digest: ''
  - repository: ''
    path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
    symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)
    line: 217
    commit: ''
    content_digest: ''
  - repository: ''
    path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
    symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder(com.ly.flight.chainsaas.refund.facade.model.request.CreateRefundOrderRequest)
    line: 32
    commit: ''
    content_digest: ''
  - repository: ''
    path: app/facade-impl/src/main/resources/META-INF/spring/refundcore-facade-impl-trade-rpc.xml
    symbol: dsf.ifightchainsaas.refund.core
    line: 13
    commit: ''
    content_digest: ''
  - repository: ''
    path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
    symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#createOrder
    line: 36
    commit: ''
    content_digest: ''
updated_at: '2026-08-27T23:21:07.939469Z'
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

创建退票单入口；通过校验后持久化状态为PENDING_APPLY的退票单，但响应不保证返回可直接绑定的身份。

### 完整业务分析

#### 业务目的

基于真实原出票订单创建退票单，并把新退票单持久化为待申请状态；产物身份必须由正式查询能力重新取得。

#### 适用场景

作为需要RefundOrder(PENDING_APPLY/CANCELLABLE)的Setup生产者，但仅在其requires fact与Recipe均正式发布后可执行。

#### 输入、默认值与过滤分页语义

orderSerialNo用于查询并锁定原订单；退票类别、乘机人和航段决定创建内容，但原订单可用状态仍需正式Booking知识确认。

#### 返回组装与空结果语义

成功只证明创建流程完成；响应不保证携带可直接绑定的退票单身份，必须通过Published查询能力取得并验证。

#### 完整业务流程

Facade接收创建请求，经创建Invoker校验原订单与重复单后构建OrderContext；OrderBuilder把退票单状态初始化为PENDING_APPLY，OrderService转换并持久化退票单。

#### 重要条件分支、计算与外部调用

原单不存在、CBDS限制、多PNR或存在处理中退改单时不创建；校验全部通过后才保存。

#### 异常与失败处理

业务校验失败返回明确失败响应；保存异常由现有事务回滚，不能形成produced fact。

#### 测试 Oracle

验证创建响应成功，并通过正式查询能力取得refundSerialNo且实际refundState=PENDING_APPLY。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
