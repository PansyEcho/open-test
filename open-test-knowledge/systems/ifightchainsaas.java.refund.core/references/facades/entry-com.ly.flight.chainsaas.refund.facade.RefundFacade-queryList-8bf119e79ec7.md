---
node_id: entry:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
system_id: ifightchainsaas.java.refund.core
kind: facade
title: RefundFacade#queryList
summary: 包含2个可观察业务阶段。
aliases:
- facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
- com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
- RefundFacade#queryList
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList
  line: 206
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundOrderListQueryInvoker.java
  symbol: com.ly.flight.chainsaas.refund.biz.manager.refund.RefundOrderListQueryInvoker#invoke
  line: 40
  commit: eba0fc72ec39a6883a6ceb1a70c38040ec5ea0bb
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.OrderService#queryOrderList
  line: 50
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#queryOrderList
  line: 131
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: com.ly.flight.chainsaas.refund.dal.proxy.SaasRefundOrderDAOProxy#listPage
  line: 61
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.chainsaas.refund.biz.service.impl.OrderServiceImpl#buildListOrder
  line: 359
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundOrderQueryRequest.java
  symbol: com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest
  line: 19
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
  title: 查询可取消退票单
  condition: 正式平台和状态筛选存在匹配
  expected_outcome: success=true且pageList返回身份和状态完整实体
- kind: validation
  title: 查询未命中
  condition: 无匹配实体
  expected_outcome: success=true且pageList为空，Setup不执行Action
- kind: failure
  title: 查询异常
  condition: 订单服务抛出OrderException
  expected_outcome: success=false且返回固定错误语义
metadata:
  scan_id: scan-20260827223314-a0f437c374-27423ce1
  tool_id: facade.refund.query_list
  analysis_depth: business
  branch_count: 0
  external_call_count: 2
  owned_analysis_symbols:
  - com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList
  - com.ly.flight.chainsaas.refund.biz.manager.refund.RefundOrderListQueryInvoker#invoke
invocation_contract:
  tool_id: facade.refund.query_list
  target_id: facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
  request_type: com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest
  response_type: com.ly.flight.chainsaas.refund.facade.model.response.RefundOrderListResponse
  transport_path: queryList
  request_template:
    serialVersionUID: 0
    traceId: ''
    operator: ''
    page: 0
    pageSize: 0
    lastName: ''
    firstName: ''
    orderSerialNo: ''
    refundSerialNo: ''
    refundSerialNoList:
    - ''
    orderSerialNoList:
    - ''
    thirdOrderSerialNo: ''
    orderState: 0
    refundType: 0
    involuntaryRefundType: 0
    ticketAirline: ''
    depFromDate: ''
    depToDate: ''
    createFromDate: ''
    createToDate: ''
    pnr: ''
    merchantId: ''
    platFormId: ''
    ticketNo: ''
    buyer: ''
    orderType: ''
    memberId: ''
    applyToAirline: 0
    beginUpdateTime: ''
    endUpdateTime: ''
    needRetryEvent: false
    gds: ''
    refundOrderType: ''
    refundChannel: ''
    supplyChannel: 0
  required_fields:
  - page
  - pageSize
  - platFormId
  field_meanings:
    page: 从1开始的页码。
    pageSize: 单页数量，默认20。
    platFormId: 必填平台或租户边界。
    refundSerialNo: 精确退票单号。
    orderSerialNo: 关联原订单号。
    orderState: 退票单状态码。
  date_dimensions:
    depFromDate: 起飞时间开始。
    depToDate: 起飞时间结束。
    createFromDate: 创建时间开始。
    createToDate: 创建时间结束。
    beginUpdateTime: 更新时间开始。
    endUpdateTime: 更新时间结束。
  enum_mappings: {}
  pagination_semantics: page从1开始，pageSize为单页数量；响应list含pageList、totalCount和totalPageCount。
  error_semantics:
  - OrderException转换为success=false、code=-1、message=系统异常。
  - success=true且pageList为空表示未命中，不是业务失败。
  usage_examples:
  - page=1、pageSize=20并绑定正式platFormId及orderState；仅在success=true、pageList非空且状态验证通过时取得Setup
    Fact。
  read_only: true
entry_fact_knowledge:
  entry_id: facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
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
  produces_facts: []
  state_transitions: []
  candidate_operations:
  - assertion_id: entry-fact:refund-query-current-v3-query-operation
    assertion_type: CANDIDATE_OPERATION
    slot_id: refund_order
    fact_contract_id: refund-order/v3
    required_state: ''
    produced_state: ''
    from_state: ''
    to_state: ''
    operation_role: QUERY
    candidate_system_id: ifightchainsaas.java.refund.core
    candidate_operation_id: candidate:ifightchainsaas.java.refund.core:com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
    query_availability:
      type: COLLECTION_NOT_EMPTY
      path: refund_order_page.pageList
      expected_boolean: null
      found_values: []
      not_found_values: []
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
      symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
      line: 200
      commit: ''
      content_digest: ''
    - repository: ''
      path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
      symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
      line: 20
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
      symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
      line: 24
      commit: ''
      content_digest: ''
    confirmed_assertion_id: ''
  binding_paths: []
  evidence_refs:
  - repository: ''
    path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
    symbol: com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
    line: 200
    commit: ''
    content_digest: ''
  - repository: ''
    path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
    symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList(com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest)
    line: 20
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
    symbol: com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
    line: 24
    commit: ''
    content_digest: ''
updated_at: '2026-08-27T23:11:31.885143Z'
---


<!-- kb:auto-start -->
## 业务结论

包含2个可观察业务阶段。

## 业务阶段

- `返回或结束分支：this.execute(request, RefundOrderServiceEnum.QUEYR_ORDER_LIST, OrderSourceEnum.COMMON, request.getTraceId(), request.getRefundSerialNo())`
- `返回或结束分支：createErrorResponse(request, e, RefundOrderListResponse.class)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundFacadeImpl.java com.ly.flight.chainsaas.refund.facade.impl.RefundFacadeImpl#queryList`


## 入口内调用节点：com.ly.flight.chainsaas.refund.biz.manager.refund.RefundOrderListQueryInvoker#invoke

## 业务结论

包含5个可观察业务阶段，调用2个服务/仓储/缓存或消息协作者。

## 业务阶段

- `获取订单详情`
- `订单状态校验`
- `返回或结束分支：new TradeResponse<>(refundOrderListResponse)`
- `refundOrderListResponse.setSuccess(true)`
- `refundOrderListResponse.setSuccess(false)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `orderService.queryOrderList`
- `orderService.queryOrderListCount`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `RefundOrderListQueryInvoker.java com.ly.flight.chainsaas.refund.biz.manager.refund.RefundOrderListQueryInvoker#invoke`

## Agent代码解释（INFERRED）

分页查询退票单；返回身份、原订单关系与状态，空列表表示未找到，异常返回失败响应。

### 完整业务分析

#### 业务目的

按正式筛选条件只读查询退票单，为Setup提供可验证的身份、原订单关系和状态。

#### 适用场景

用于执行前查询可取消退票单，以及按退票单号、原订单号或状态读取受控实体。

#### 输入、默认值与过滤分页语义

page/pageSize控制分页，platFormId限定平台；refundSerialNo、orderSerialNo和orderState用于精确筛选。

#### 返回组装与空结果语义

success=true且list.pageList非空表示命中；元素提供refundSerialNo、orderSerialNo和refundState。

#### 完整业务流程

Facade路由到列表Invoker；Invoker调用OrderService；实现转换分页请求并在DAO边界读取退票单后组装列表。

#### 重要条件分支、计算与外部调用

票号或PNR无匹配时返回空页；DAO成功返回分页列表；OrderException转换为success=false。

#### 异常与失败处理

OrderException返回success=false、code=-1和系统异常；空pageList只是未找到实体。

#### 测试 Oracle

验证success、分页数量、身份非空、状态谓词和原订单关系。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
