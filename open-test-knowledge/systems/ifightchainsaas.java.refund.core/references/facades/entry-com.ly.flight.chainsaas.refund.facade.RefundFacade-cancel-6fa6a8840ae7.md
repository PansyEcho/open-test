---
node_id: entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel
system_id: ifightchainsaas.java.refund.core
kind: facade
title: RefundFacade#cancel
summary: 包含2个可观察业务阶段。
aliases:
- facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel
- com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel
- RefundFacade#cancel
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel
  line: 292
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke
  line: 80
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/RefundCancelValidator.java
  symbol: com.ly.flight.chainsaas.refund.facade.validator.trade.RefundCancelValidator#validate
  line: 19
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel
  line: 84
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#innerInvoke
  line: 99
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#doInvoke
  line: 135
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/CBDSService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.CBDSService#refundCancel
  line: 26
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/CBDSServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.CBDSServiceImpl#refundCancel
  line: 66
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/resources/ResourcesClient.java
  symbol: com.ly.flight.chainsaas.refund.integration.resources.ResourcesClient#refundCancel
  line: 39
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/resources/ResourcesClientImpl.java
  symbol: com.ly.flight.chainsaas.refund.integration.resources.ResourcesClientImpl#refundCancel
  line: 61
  commit: ''
  content_digest: ''
- repository: ''
  path: app/integration/src/main/java/com/ly/flight/chainsaas/refund/integration/proxy/RefundResourcesFacadeProxy.java
  symbol: com.ly.flight.chainsaas.refund.integration.proxy.RefundResourcesFacadeProxy#refundCancel
  line: 100
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/RefundOrderStateEnum.java
  symbol: com.ly.flight.chainsaas.refund.enums.RefundOrderStateEnum
  line: 12
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
test_points:
- kind: main_flow
  title: 取消可取消退票单
  condition: 退票单为 PENDING_APPLY、WAIT_REFUND、AUDITED、REFUND_FAIL 或 RESHOPING
  expected_outcome: 响应成功且状态变为 REFUND_CANCEL
- kind: validation
  title: 退票单不存在
  condition: refundSerialNo 查询不到退票单
  expected_outcome: 返回订单不存在且不迁移状态
- kind: failure
  title: 不可取消状态
  condition: 订单不在可取消集合且不是 REFUND_CANCEL
  expected_outcome: 返回订单状态错误
- kind: boundary
  title: CBDS取消同步
  condition: 非代金券、GDS为SAPL且officeNo属于CBDS
  expected_outcome: 向资源层发起退票取消
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  tool_id: facade.refund.cancel
  analysis_depth: business
  branch_count: 0
  external_call_count: 1
  owned_analysis_symbols:
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel
  - com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke
  - com.ly.flight.chainsaas.refund.facade.validator.trade.RefundCancelValidator#validate
invocation_contract: null
input_contract:
  contract_version: operation-input-knowledge/v1
  target_id: facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel
  request_type: com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest
  source_scan_id: scan-20260827223314-a0f437c374-27423ce1
  status: READY
  request_schema:
    type: object
    properties:
      traceId:
        type: string
      operator:
        type: string
      refundSerialNo:
        type: string
      cancelReasonId:
        type: string
      cancelReason:
        type: string
      cancelRemark:
        type: string
    additionalProperties: false
    required:
    - cancelReason
    - cancelReasonId
    - cancelRemark
    - refundSerialNo
  fields:
  - path: refundSerialNo
    field_name: refundSerialNo
    schema:
      type: string
    description: 退票订单号
    required: true
    business_identity: true
    requirement_marker: '@required'
    source_ref:
      repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
      symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest#refundSerialNo
      line: 17
      commit: ''
      content_digest: ''
  - path: cancelReasonId
    field_name: cancelReasonId
    schema:
      type: string
    description: 取消原因Id
    required: true
    business_identity: false
    requirement_marker: '@required'
    source_ref:
      repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
      symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest#cancelReasonId
      line: 22
      commit: ''
      content_digest: ''
  - path: cancelReason
    field_name: cancelReason
    schema:
      type: string
    description: 取消原因
    required: true
    business_identity: false
    requirement_marker: '@required'
    source_ref:
      repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
      symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest#cancelReason
      line: 27
      commit: ''
      content_digest: ''
  - path: cancelRemark
    field_name: cancelRemark
    schema:
      type: string
    description: 取消原因备注
    required: true
    business_identity: false
    requirement_marker: '@required'
    source_ref:
      repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
      symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest#cancelRemark
      line: 33
      commit: ''
      content_digest: ''
  - path: traceId
    field_name: traceId
    schema:
      type: string
    description: ''
    required: false
    business_identity: false
    requirement_marker: ''
    source_ref: null
  - path: operator
    field_name: operator
    schema:
      type: string
    description: ''
    required: false
    business_identity: false
    requirement_marker: ''
    source_ref: null
  blocked_reason: ''
entry_fact_knowledge:
  entry_id: facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel
  source_scan_id: scan-20260827223314-a0f437c374-27423ce1
  source_baseline:
    source_path: /Users/user/data/code/tc/ifightchainsaas.java.refund.core
    commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
    branch: feature_673598_20260806
    dirty: false
    dirty_digest: ''
    analyzer_version: 0.2.0
    captured_at: '2026-08-27T22:33:14.750680Z'
  requires_facts:
  - assertion_id: entry-fact:refund-cancel-current-v3-requires-cancellable-order
    assertion_type: REQUIRES_FACT
    slot_id: refund_order
    fact_contract_id: refund-order/v3
    required_state: CANCELLABLE
    produced_state: ''
    from_state: ''
    to_state: ''
    operation_role: ''
    candidate_system_id: ''
    candidate_operation_id: ''
    query_availability: null
    request_path: ''
    fact_path: ''
    cardinality: 1
    acquisition_policy: QUERY_THEN_CREATE
    constraints: []
    relations: []
    source: CODE_PROVEN
    evidence_refs:
    - repository: ''
      path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
      symbol: RefundOrderCancelPostActor
      line: 25
      commit: ''
      content_digest: ''
    - repository: ''
      path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderManualCancelPostActor.java
      symbol: RefundOrderManualCancelPostActor
      line: 20
      commit: ''
      content_digest: ''
    confirmed_assertion_id: ''
  produces_facts: []
  state_transitions:
  - assertion_id: entry-fact:refund-cancel-current-v3-transition-cancelled
    assertion_type: STATE_TRANSITION
    slot_id: ''
    fact_contract_id: refund-order/v3
    required_state: ''
    produced_state: ''
    from_state: CANCELLABLE
    to_state: CANCELLED
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
      path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
      symbol: RefundOrderCancelPostActor
      line: 25
      commit: ''
      content_digest: ''
    - repository: ''
      path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderManualCancelPostActor.java
      symbol: RefundOrderManualCancelPostActor
      line: 20
      commit: ''
      content_digest: ''
    confirmed_assertion_id: ''
  candidate_operations: []
  binding_paths:
  - assertion_id: entry-fact:refund-cancel-current-v3-bind-refund-serial-no
    assertion_type: BINDING_PATH
    slot_id: refund_order
    fact_contract_id: refund-order/v3
    required_state: ''
    produced_state: ''
    from_state: ''
    to_state: ''
    operation_role: ''
    candidate_system_id: ''
    candidate_operation_id: ''
    query_availability: null
    request_path: refund_serial_no
    fact_path: refundSerialNo
    cardinality: 1
    acquisition_policy: ''
    constraints: []
    relations: []
    source: CODE_PROVEN
    evidence_refs:
    - repository: ''
      path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
      symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest)
      line: 286
      commit: ''
      content_digest: ''
    - repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
      symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest#refundSerialNo
      line: 17
      commit: ''
      content_digest: ''
    confirmed_assertion_id: ''
  evidence_refs:
  - repository: ''
    path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
    symbol: RefundOrderCancelPostActor
    line: 25
    commit: ''
    content_digest: ''
  - repository: ''
    path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderManualCancelPostActor.java
    symbol: RefundOrderManualCancelPostActor
    line: 20
    commit: ''
    content_digest: ''
  - repository: ''
    path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
    symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel(com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest)
    line: 286
    commit: ''
    content_digest: ''
  - repository: ''
    path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
    symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundCancelRequest#refundSerialNo
    line: 17
    commit: ''
    content_digest: ''
updated_at: '2026-08-27T23:23:17.814449Z'
---

<!-- kb:auto-start -->
## 业务结论

包含2个可观察业务阶段。

## 业务阶段

- `返回或结束分支：this.execute(request, RefundOrderServiceEnum.CANCEL, OrderSourceEnum.COMMON, request.getTraceId(), request.getRefundSerialNo())`
- `返回或结束分支：createErrorResponse(request, e, RefundCancelResponse.class)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundFacadeImpl.java com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#cancel`


## 入口内调用节点：com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke

## 业务结论

包含3个可观察业务阶段，调用1个服务/仓储/缓存或消息协作者，产生2项状态或数据副作用。

## 业务阶段

- `返回或结束分支：OrderConstants.ORDER_OPERATE_ + request.getRefundSerialNo()`
- `返回或结束分支：request.getRefundSerialNo()`
- `返回或结束分支：innerInvoke(request)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `serviceInvokerLockDelegate.invokeWithLock`

## 状态与副作用

- `serviceInvokerLockDelegate.invokeWithLock`
- `lockKey`

## 源码证据

- `RefundCancelServiceInvoker.java com.ly.flight.chainsaas.refund.biz.manager.refund.RefundCancelServiceInvoker#invoke`


## 入口内调用节点：com.ly.flight.chainsaas.refund.facade.validator.trade.RefundCancelValidator#validate

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

- `RefundCancelValidator.java com.ly.flight.chainsaas.refund.facade.validator.trade.RefundCancelValidator#validate`

## Agent代码解释（INFERRED）

取消入口按 refundSerialNo 定位退票单；已取消时幂等成功，可取消状态流转到 REFUND_CANCEL，其他状态拒绝；特定 CBDS 订单同步下游取消。

### 完整业务分析

#### 业务目的

按退款流水号取消当前允许取消的退票单，并推进到取消终态。

#### 适用场景

适用于 PENDING_APPLY、WAIT_REFUND、AUDITED、REFUND_FAIL、RESHOPING；已取消时幂等成功。

#### 输入、默认值与过滤分页语义

refundSerialNo 是退票单身份、查询条件和锁键；traceId 用于调用链。

#### 返回组装与空结果语义

成功响应表示取消动作完成；code/message 表达业务错误，最终状态需独立验证。

#### 完整业务流程

Facade 调用 Invoker；Invoker 加锁并查询退票单，处理分支、校验状态并迁移；特定 CBDS 订单经 CBDSService、ResourcesClient 和代理同步资源层取消。

#### 重要条件分支、计算与外部调用

不存在拒绝；已取消幂等成功；仅五种状态继续；非代金券、SAPL且CBDS office时触发资源层取消。

#### 异常与失败处理

订单不存在、状态非法或状态迁移异常均返回错误；CBDS远程异常由服务捕获并记录，不改变已完成的本地取消状态。

#### 测试 Oracle

验证响应、REFUND_CANCEL 状态和失败分支无错误迁移；CBDS 条件成立时验证资源层取消及对应业务日志。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
