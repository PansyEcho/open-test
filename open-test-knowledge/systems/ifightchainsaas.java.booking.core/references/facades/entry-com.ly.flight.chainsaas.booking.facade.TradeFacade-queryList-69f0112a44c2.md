---
node_id: entry:com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList
system_id: ifightchainsaas.java.booking.core
kind: facade
title: TradeFacade#queryList
summary: 包含2个可观察业务阶段。
aliases:
- facade:com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList
- com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList
- TradeFacade#queryList
source_refs:
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/booking/facade/impl/TradeFacadeImpl.java
  symbol: com.ly.flight.chainsaas.booking.facade.impl.TradeFacadeImpl#queryList
  line: 372
  commit: 004c50d90d152f1ef4892679f8b1b322cc7a7405
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/booking/biz/gateway/invoker/manager/trade/OrderListQueryInvoker.java
  symbol: com.ly.flight.chainsaas.booking.biz.gateway.invoker.manager.trade.OrderListQueryInvoker#invoke
  line: 38
  commit: 004c50d90d152f1ef4892679f8b1b322cc7a7405
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/booking/biz/gateway/validator/trade/OrderListQueryValidator.java
  symbol: com.ly.flight.chainsaas.booking.biz.gateway.validator.trade.OrderListQueryValidator#validate
  line: 22
  commit: 004c50d90d152f1ef4892679f8b1b322cc7a7405
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/booking/facade/TradeFacade.java
  symbol: com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList
  line: 26
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/booking/facade/impl/AbstractFacade.java
  symbol: com.ly.flight.chainsaas.booking.facade.impl.AbstractFacade#execute
  line: 89
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/booking/facade/DefaultTradeServiceProxy.java
  symbol: com.ly.flight.chainsaas.booking.facade.DefaultTradeServiceProxy#execute
  line: 105
  commit: ''
  content_digest: ''
- repository: ''
  path: app/order/src/main/java/com/ly/flight/intl/chainsaas/booking/order/service/OrderService.java
  symbol: com.ly.flight.intl.chainsaas.booking.order.service.OrderService#queryOrderList
  line: 44
  commit: ''
  content_digest: ''
- repository: ''
  path: app/order/src/main/java/com/ly/flight/intl/chainsaas/booking/order/service/impl/OrderServiceImpl.java
  symbol: com.ly.flight.intl.chainsaas.booking.order.service.impl.OrderServiceImpl#queryOrderList
  line: 132
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/booking/dal/single/proxy/SaasOrderDAOProxy.java
  symbol: com.ly.flight.chainsaas.booking.dal.single.proxy.SaasOrderDAOProxy#listPage
  line: 160
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/booking/facade/model/request/OrderQueryRequest.java
  symbol: com.ly.flight.chainsaas.booking.facade.model.request.OrderQueryRequest
  line: 44
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/booking/facade/model/response/OrderListResponse.java
  symbol: com.ly.flight.chainsaas.booking.facade.model.response.OrderListResponse
  line: 18
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/booking/model/PageVO.java
  symbol: com.ly.flight.chainsaas.booking.model.PageVO
  line: 13
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/booking/model/CoreVO.java
  symbol: com.ly.flight.chainsaas.booking.model.CoreVO
  line: 35
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/booking/model/SaasOrderVO.java
  symbol: com.ly.flight.chainsaas.booking.model.SaasOrderVO
  line: 47
  commit: ''
  content_digest: ''
- repository: ''
  path: app/order/src/main/java/com/ly/flight/intl/chainsaas/booking/order/converter/OrderConverter.java
  symbol: com.ly.flight.intl.chainsaas.booking.order.converter.OrderConverter#do2vo
  line: 34
  commit: ''
  content_digest: ''
- repository: ''
  path: app/order/src/main/java/com/ly/flight/intl/chainsaas/booking/order/converter/converter/OrderStateEnumConverter.java
  symbol: com.ly.flight.intl.chainsaas.booking.order.converter.converter.OrderStateEnumConverter#asString
  line: 14
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/booking/enums/OrderStateTransferEnum.java
  symbol: com.ly.flight.chainsaas.booking.enums.OrderStateTransferEnum
  line: 15
  commit: ''
  content_digest: ''
- repository: ''
  path: app/order/src/main/java/com/ly/flight/intl/chainsaas/booking/order/converter/OrderListQueryPageConverter.java
  symbol: com.ly.flight.intl.chainsaas.booking.order.converter.OrderListQueryPageConverter#requestToDbQuery
  line: 14
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/booking/dal/single/operation/ListPageQuery.java
  symbol: com.ly.flight.chainsaas.booking.dal.single.operation.ListPageQuery
  line: 48
  commit: ''
  content_digest: ''
- repository: ''
  path: app/order/src/main/java/com/ly/flight/intl/chainsaas/booking/order/service/AbstractOrderService.java
  symbol: com.ly.flight.intl.chainsaas.booking.order.service.AbstractOrderService
  line: 11
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
test_points:
- kind: main_flow
  title: 分页查询订单
  condition: 分页和筛选来自正式Recipe
  expected_outcome: success=true且订单位于list.pageList
- kind: boundary
  title: 无匹配订单
  condition: 筛选无结果
  expected_outcome: 空PageVO记为Setup未找到而非断言失败
- kind: validation
  title: 状态筛选
  condition: 使用正式确认的状态码
  expected_outcome: 整数状态进入ListPageQuery，不按冲突注释猜测
- kind: failure
  title: 查询异常
  condition: 服务或组装异常
  expected_outcome: success=false，不解释为query miss
metadata:
  scan_id: scan-20260827202526-207e53b9cd-acc69a73
  tool_id: facade.trade.query_list
  analysis_depth: business
  branch_count: 0
  external_call_count: 2
  owned_analysis_symbols:
  - com.ly.flight.chainsaas.booking.facade.impl.TradeFacadeImpl#queryList
  - com.ly.flight.chainsaas.booking.biz.gateway.invoker.manager.trade.OrderListQueryInvoker#invoke
  - com.ly.flight.chainsaas.booking.biz.gateway.validator.trade.OrderListQueryValidator#validate
invocation_contract:
  tool_id: facade.trade.query_list
  target_id: facade:com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList
  request_type: com.ly.flight.chainsaas.booking.facade.model.request.OrderQueryRequest
  response_type: com.ly.flight.chainsaas.booking.facade.model.response.OrderListResponse
  transport_path: queryList
  request_template:
    page: 0
    pageSize: 0
    fromPage: false
    orderSerialNo: ''
    thirdOrderSerialNo: ''
    orderState: 0
    orderStates:
    - 0
    orderChannelSource: 0
    supplyChannel: 0
    traceId: ''
    depFromDate: ''
    depToDate: ''
    createFromDate: ''
    createToDate: ''
    pnr: ''
    hostLevelPnr: ''
    contactName: ''
    lastName: ''
    firstName: ''
    ticketAirline: ''
    resourceType: ''
    merchantId: ''
    gmtIssueEndFrom: ''
    gmtIssueEndTo: ''
    buyer: ''
    ownerId: 0
    ticketNo: ''
    orderType: ''
    bookFrom: ''
    bookTo: ''
    memberId: ''
    engineSerialNo: ''
    departureCityCode: ''
    arrivalCityCode: ''
    flightNo: ''
    airlinePnr: ''
    tripType: 0
  required_fields:
  - page
  - pageSize
  field_meanings:
    page: 查询页，源码默认1
    pageSize: 单页数量，源码默认20
    fromPage: 是否仅查询页面所需内容
    orderSerialNo: 交易系统订单号
    thirdOrderSerialNo: 三方订单号
    orderState: 单个订单状态整数筛选，实际业务码须正式确认
    orderStates: 多个订单状态整数筛选，存在时优先
    orderChannelSource: 订单渠道来源
    supplyChannel: 供应渠道
    traceId: 全链路标识
    depFromDate: 起飞时间开始
    depToDate: 起飞时间结束
    createFromDate: 创建时间开始
    createToDate: 创建时间结束
    pnr: PNR编号
    hostLevelPnr: 关联原单的1G特殊PNR
    contactName: 联系人姓名
    lastName: 乘客姓字段
    firstName: 乘客名字段
    ticketAirline: 开票航司
    resourceType: 采购方字段
    merchantId: 供应商字段
    gmtIssueEndFrom: 最晚出票时间开始
    gmtIssueEndTo: 最晚出票时间结束
    buyer: 采购方标识
    ownerId: 平台ID
    ticketNo: 电子客票号
    orderType: 订单类型
    bookFrom: 预订时间开始
    bookTo: 预订时间结束
    memberId: 会员ID
    engineSerialNo: 子引擎订单号
    departureCityCode: 出发城市三字码
    arrivalCityCode: 到达城市三字码
    flightNo: 航班号字段
    airlinePnr: 航司大编码
    tripType: 行程类型
  date_dimensions:
    depFromDate: 起飞开始
    depToDate: 起飞结束
    createFromDate: 创建开始
    createToDate: 创建结束
    gmtIssueEndFrom: 出票完成开始
    gmtIssueEndTo: 出票完成结束
    bookFrom: 预订开始
    bookTo: 预订结束
  enum_mappings: {}
  pagination_semantics: page/pageSize控制分页，list.pageList为当前页。
  error_semantics:
  - success=false是查询失败，不是未找到。
  usage_examples:
  - 固定分页并使用正式确认状态筛选，不从Fixture提供真实订单号。
  read_only: true
entry_fact_knowledge: null
updated_at: '2026-08-27T20:45:31.233272Z'
---

<!-- kb:auto-start -->
## 业务结论

包含2个可观察业务阶段。

## 业务阶段

- `返回或结束分支：this.execute(request, TradeServiceEnum.QUERY_ORDER_LIST, OrderSourceEnum.COMMON, request.getTraceId(), request.getOrderSerialNo())`
- `返回或结束分支：createErrorResponse(request, e, OrderListResponse.class)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `TradeFacadeImpl.java com.ly.flight.chainsaas.booking.facade.impl.TradeFacadeImpl#queryList`


## 入口内调用节点：com.ly.flight.chainsaas.booking.biz.gateway.invoker.manager.trade.OrderListQueryInvoker#invoke

## 业务结论

包含5个可观察业务阶段，调用2个服务/仓储/缓存或消息协作者。

## 业务阶段

- `获取订单详情`
- `订单状态校验`
- `返回或结束分支：new TradeResponse<>(orderListResponse)`
- `orderListResponse.setSuccess(true)`
- `orderListResponse.setSuccess(false)`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `orderService.queryOrderList`
- `orderService.queryOrderListCount`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `OrderListQueryInvoker.java com.ly.flight.chainsaas.booking.biz.gateway.invoker.manager.trade.OrderListQueryInvoker#invoke`


## 入口内调用节点：com.ly.flight.chainsaas.booking.biz.gateway.validator.trade.OrderListQueryValidator#validate

## 业务结论

包含1个可观察业务阶段。

## 业务阶段

- `stringIsNotBlank(request.getTraceId(), "traceId");`

## 条件与分支

- `未从当前方法直接证明`

## 外部交互

- `未从当前方法直接证明`

## 状态与副作用

- `未从当前方法直接证明`

## 源码证据

- `OrderListQueryValidator.java com.ly.flight.chainsaas.booking.biz.gateway.validator.trade.OrderListQueryValidator#validate`

## Agent代码解释（INFERRED）

只读出票订单分页查询。入口经 QUERY_ORDER_LIST 路由至 OrderListQueryInvoker 和 OrderServiceImpl，查询 SaasOrderDAOProxy 后把订单转换为 SaasOrderVO 并放入 OrderListResponse.list.pageList。身份来自 CoreVO.orderSerialNo，状态经 OrderStateEnumConverter 输出整数。OrderStateTransferEnum 将 TICKETED 分组标为4，但请求旧注释写3，冲突未正式解决前不得升级为正式 ISSUED 结论。

### 完整业务分析

#### 业务目的

只读分页检索受控出票订单，提供真实身份、状态和分页信息。

#### 适用场景

按订单号、状态、日期、PNR、票号等条件检索；取消退票链中仅作为Published QUERY Producer。

#### 输入、默认值与过滤分页语义

page/pageSize必填；orderState为单状态整数，orderStates为多状态整数且优先；冲突状态码未正式确认前不得猜测。

#### 返回组装与空结果语义

list是PageVO<SaasOrderVO>；pageList保存订单，orderSerialNo是身份，orderState经转换器输出整数。

#### 完整业务流程

Facade经Proxy分派至Invoker，调用OrderServiceImpl，映射ListPageQuery，经DAO读取并转换为PageVO。

#### 重要条件分支、计算与外部调用

高级条件可提前返回空PageVO；DAO可读ES或数据库；TICKETED旧注释3与当前分组4冲突。

#### 异常与失败处理

异常转失败响应；Provider失败/阻塞/超时不能视为query miss。

#### 测试 Oracle

success=true、pageList可解析、orderSerialNo非空且orderState满足正式谓词；空集合仅为Setup未找到。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
