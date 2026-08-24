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
  symbol: RefundFacadeImpl#queryList
  line: 206
  commit: 4da983bfd4d9de362fc5323412e35c1bdbd08236
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: RefundFacade#queryList
  line: 24
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundOrderQueryRequest.java
  symbol: RefundOrderQueryRequest
  line: 19
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/response/RefundOrderListResponse.java
  symbol: RefundOrderListResponse
  line: 15
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/AbstractFacade.java
  symbol: AbstractFacade#execute
  line: 136
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/DefaultTradeServiceProxy.java
  symbol: DefaultTradeServiceProxy#execute
  line: 104
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundOrderListQueryInvoker.java
  symbol: RefundOrderListQueryInvoker#invoke
  line: 40
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#queryOrderList
  line: 131
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#handleTicketNoSearchCondition
  line: 167
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#handlePnrSearchCondition
  line: 192
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#handleRefundSerialNoSearchCondition
  line: 204
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#buildListOrder
  line: 359
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#queryOrderListCount
  line: 118
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: SaasRefundOrderDAOProxy#listPage
  line: 61
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/resources/sqlmap/refundcore/SaasRefundOrderMapperExt.xml
  symbol: selectListByQuery_where_if
  line: 188
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/resources/sqlmap/refundcore/SaasRefundOrderMapperExt.xml
  symbol: listPage
  line: 308
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/resources/sqlmap/refundcore/SaasRefundOrderMapperExt.xml
  symbol: queryOrderListCount
  line: 380
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/PageQueryUtils.java
  symbol: PageQueryUtils#pageQuery
  line: 32
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderItemDAOProxy.java
  symbol: SaasRefundOrderItemDAOProxy#queryListByTicketNo
  line: 45
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderItemDAOProxy.java
  symbol: SaasRefundOrderItemDAOProxy#queryListByPnr
  line: 52
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderItemDAOProxy.java
  symbol: SaasRefundOrderItemDAOProxy#listItem
  line: 59
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderPsiDAOProxy.java
  symbol: SaasRefundOrderPsiDAOProxy#list
  line: 26
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/converter/PsiConverter.java
  symbol: PsiConverter#do2vo
  line: 31
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/model/SaasRefundOrderVO.java
  symbol: SaasRefundOrderVO
  line: 20
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/model/SaasRefundOrderItemVO.java
  symbol: SaasRefundOrderItemVO
  line: 14
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/RefundOrderStateEnum.java
  symbol: RefundOrderStateEnum
  line: 12
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
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/ApplyToAirlineEnum.java
  symbol: ApplyToAirlineEnum
  line: 7
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/RefundOrderTypeEnum.java
  symbol: RefundOrderTypeEnum
  line: 13
  commit: ''
  content_digest: ''
- repository: ''
  path: app/model/src/main/java/com/ly/flight/chainsaas/refund/enums/RefundChannelEnum.java
  symbol: RefundChannelEnum
  line: 13
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: RefundFacadeImpl#queryList
  line: 209
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/AbstractFacade.java
  symbol: AbstractFacade#execute
  line: 120
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/DefaultTradeServiceProxy.java
  symbol: DefaultTradeServiceProxy#invoke
  line: 55
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/DefaultTradeServiceProxy.java
  symbol: DefaultTradeServiceProxy#execute
  line: 107
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/DefaultTradeServiceProvider.java
  symbol: DefaultTradeServiceProvider#retrieveTradeService
  line: 87
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundOrderListQueryInvoker.java
  symbol: RefundOrderListQueryInvoker#invoke
  line: 44
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/impl/OrderServiceImpl.java
  symbol: OrderServiceImpl#queryOrderList
  line: 148
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/proxy/SaasRefundOrderDAOProxy.java
  symbol: SaasRefundOrderDAOProxy#listPage
  line: 62
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/AbstractFacade.java
  symbol: AbstractFacade#execute
  line: 138
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/OrderService.java
  symbol: OrderService#queryOrderList
  line: 50
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/AbstractOrderService.java
  symbol: AbstractOrderService
  line: 11
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/service/AbstractOrderService.java
  symbol: AbstractOrderService
  line: 8
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/PageQueryUtils.java
  symbol: PageQueryUtils#pageQuery
  line: 20
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/PageQueryUtils.java
  symbol: PageQueryUtils#pageQuery
  line: 21
  commit: ''
  content_digest: ''
- repository: ''
  path: app/dal/src/main/java/com/ly/flight/chainsaas/refund/dal/PageQueryUtils.java
  symbol: PageQueryUtils#pageQuery
  line: 39
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260822121007-6b0d5d1222-8ade0ea6
  tool_id: facade.refund.query_list
  analysis_depth: business
  branch_count: 0
  external_call_count: 0
invocation_contract:
  tool_id: facade.refund.query_list
  target_id: facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList
  request_type: com.ly.flight.chainsaas.refund.facade.model.request.RefundOrderQueryRequest
  response_type: com.ly.flight.chainsaas.refund.facade.model.response.RefundOrderListResponse
  transport_path: queryList
  request_template:
    applyToAirline: 0
    beginUpdateTime: ''
    buyer: ''
    createFromDate: ''
    createToDate: ''
    depFromDate: ''
    depToDate: ''
    endUpdateTime: ''
    firstName: ''
    gds: ''
    involuntaryRefundType: 0
    lastName: ''
    memberId: ''
    merchantId: ''
    needRetryEvent: false
    operator: ''
    orderSerialNo: ''
    orderSerialNoList:
    - ''
    orderState: 0
    orderType: ''
    page: 0
    pageSize: 0
    platFormId: ''
    pnr: ''
    refundChannel: ''
    refundOrderType: ''
    refundSerialNo: ''
    refundSerialNoList:
    - ''
    refundType: 0
    serialVersionUID: 0
    supplyChannel: 0
    thirdOrderSerialNo: ''
    ticketAirline: ''
    ticketNo: ''
    traceId: ''
  required_fields:
  - page
  - pageSize
  - platFormId
  field_meanings:
    serialVersionUID: Java序列化兼容字段，业务调用不应设置。
    traceId: 链路ID；空值由Facade生成，不过滤数据。
    operator: 操作人；本路径不参与过滤。
    page: 页码；对象默认1，显式0保留。
    pageSize: 每页条数；对象默认20，显式0形成limit 0。
    lastName: 乘客姓；当前实现不生效。
    firstName: 乘客名；当前实现不生效。
    orderSerialNo: 原交易订单号，精确匹配；票号预处理可补写/校验。
    refundSerialNo: 单个退票单号；与票号/PNR结果冲突则成功空结果。
    refundSerialNoList: 退票单号IN集合；与票号/PNR结果取交集。
    orderSerialNoList: 名义为交易订单号集合，但当前SQL实际匹配refund_serial_no IN。
    thirdOrderSerialNo: 三方订单号，精确匹配。
    orderState: 状态码：-1无效、0申请、1审核通过、2待退票、3退票中、4成功、5失败、6取消、7退款完成、8核价中。
    refundType: 0非自愿、1自愿、2当日作废。
    involuntaryRefundType: 1航变、2病退、3拒签、4错购。
    ticketAirline: 开票航司，精确匹配。
    depFromDate: 起飞时间包含下界。
    depToDate: 起飞时间不含上界。
    createFromDate: 退票创建时间包含下界。
    createToDate: 退票创建时间不含上界。
    pnr: 按退票item.real_pnr+env精确查并派生退票单号集合。
    merchantId: 出票供应商ID，精确匹配。
    platFormId: 租户/供应商归属平台ID，列表与状态概览维度。
    ticketNo: 按退票item.ticket_no+env精确查并派生原单号与退票单号。
    buyer: 采购商ID，精确匹配，也是状态概览维度。
    orderType: 订单类型，精确匹配。
    memberId: 会员ID，精确匹配。
    applyToAirline: 1未申请、2已申请。
    beginUpdateTime: update_time严格大于下界。
    endUpdateTime: update_time小于等于上界。
    needRetryEvent: true时event_state!=0；false不加条件。
    gds: GDS类型，精确匹配。
    refundOrderType: C_END_SYNC/NORMAL/SUPPLEMENT。
    refundChannel: C_END_SYNC/TCPL/WHITE_DISTRIBUTION/AI/BUSINESS_MANAGE/ARC/BSP。
    supplyChannel: 1=CBDS；2=其他且兼容NULL；其他非空值精确匹配。
  date_dimensions:
    depFromDate: gmt_take_off包含下界，String且代码不校验格式。
    depToDate: gmt_take_off不含上界，String且代码不校验格式。
    createFromDate: gmt_refund_create包含下界，String且代码不校验格式。
    createToDate: gmt_refund_create不含上界，String且代码不校验格式。
    beginUpdateTime: update_time严格大于Date下界。
    endUpdateTime: update_time小于等于Date上界。
  enum_mappings:
    orderState:
      '0': 退票申请
      '1': 审核通过
      '2': 待退票
      '3': 退票中
      '4': 退票成功
      '5': 退票失败
      '6': 已取消
      '7': 退款完成
      '8': 核价中
      '-1': 无效
    refundType:
      '0': 非自愿
      '1': 自愿退票
      '2': 当日作废
    involuntaryRefundType:
      '1': 航变退
      '2': 病退
      '3': 拒签退
      '4': 错购退
    applyToAirline:
      '1': 未申请
      '2': 已申请
    supplyChannel:
      '1': CBDS
      '2': 其他（包含NULL历史值）
    refundOrderType:
      C_END_SYNC: C端同步
      NORMAL: 正常单
      SUPPLEMENT: 补单
    refundChannel:
      C_END_SYNC: C端同步
      TCPL: TCPL
      WHITE_DISTRIBUTION: 白屏分销
      AI: AI创建
      BUSINESS_MANAGE: 运营后台
      ARC: ARC补单
      BSP: BSP补单
  pagination_semantics: 缺省page=1/pageSize=20；同条件先count，offset=(page-1)*pageSize（仅两者>0，否则0），limit=pageSize，create_time
    DESC；显式0不回退默认。
  error_semantics:
  - null请求可能在Facade前置解引用处直接NPE。
  - OrderException返回success=false/code=-1/message=系统异常并保留traceId。
  - 其他异常由代理优先透传LY错误码/消息，否则code=-1并采用异常消息，再由Facade组装失败响应。
  - 票号/PNR无匹配或条件冲突是success=true的零计数空分页，并仍返回状态概览。
  usage_examples:
  - '{"page":1,"pageSize":20,"platFormId":"10001"}'
  - '{"page":1,"pageSize":20,"platFormId":"10001","buyer":"20001","orderState":3}'
  - '{"page":1,"pageSize":20,"platFormId":"10001","ticketNo":"7812345678901","createFromDate":"2026-08-01
    00:00:00","createToDate":"2026-09-01 00:00:00"}'
  - '{"page":1,"pageSize":50,"platFormId":"10001","needRetryEvent":true,"supplyChannel":2}'
  read_only: true
updated_at: '2026-08-24T06:47:06.243057Z'
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

- `RefundFacadeImpl.java RefundFacadeImpl#queryList`

## Agent代码解释（INFERRED）

【目的与场景】SaaS退票管理端的只读分页入口，用于按租户平台、采购商、原单/退票单/三方单号、状态、退票类型、航司、供应商、日期、票号、PNR、GDS、渠道和待重试事件定位退票单，返回主单、PSI中的商品摘要及全状态概览。适合refund.mng列表、人工处理队列和异常定位；不执行创建、核价、确认、取消、退款，不调用booking.core/resource.core/wallet.core，不写库、不发MQ。
【入口与路由】POST JSON路径refund/queryList。Facade生成或沿用traceId，以QUEYR_ORDER_LIST和COMMON来源调用，finally清理日志上下文；网关按服务ID取得RefundOrderListQueryInvoker，无转换器时请求/响应原样透传。
【输入】对象缺省page=1、pageSize=20；显式0覆盖默认。platFormId为租户/供应商归属平台。orderSerialNo、refundSerialNo、thirdOrderSerialNo分别精确匹配原单、退票单、三方单；refundSerialNoList为退票单IN集合。orderSerialNoList虽名义为交易订单号集合，SQL实际对refund_serial_no执行IN，是必须保留的现状。buyer、merchantId、ticketAirline、gds、orderType、memberId、refundOrderType、refundChannel均精确匹配。firstName/lastName在本路径没有进入服务或数据库查询，当前不生效；operator/traceId仅用于上下文。
【票号/PNR分支】ticketNo先按item.ticket_no+当前env精确查：无记录即返回空分页；有记录时取第一条item的orderSerialNo，若请求未给原单号则补写，若已给且忽略大小写后不一致则空；命中的refundSerialNo集合再与显式refundSerialNo/refundSerialNoList校验或取交集。pnr按item.real_pnr+env查询并执行相同退票单号交集规则。预处理会修改请求中的orderSerialNo/refundSerialNoList。
【状态与枚举】orderState=-1无效、0申请、8核价中、1审核通过、2待退票、3退票中、4退票成功、5失败、6取消、7退款完成；refundType=0非自愿、1自愿、2当日作废；involuntaryRefundType=1航变、2病退、3拒签、4错购；applyToAirline=1未申请、2已申请。supplyChannel=1精确CBDS，=2匹配2或NULL以兼容历史其他数据，其他非空值精确匹配。needRetryEvent仅true时增加event_state!=0。
【日期】depFromDate/depToDate过滤gmt_take_off为[from,to)；createFromDate/createToDate过滤gmt_refund_create为[from,to)；它们是String且代码不校验格式。beginUpdateTime/endUpdateTime是Date，过滤update_time为(begin,end]。服务总附加当前env，所有有效条件AND组合；主查询未显式排除逻辑删除。
【分页】先以相同条件count；有数据时offset=(page-1)*pageSize（只有二者>0才计算，否则0）、limit=pageSize，按create_time DESC。返回totalCount、totalPageCount、pageList。显式pageSize=0形成limit 0，不回退20。
【返回组装】主表转SaasRefundOrderVO；每个分页订单再按refundSerialNo+orderSerialNo+env分别查item和PSI。PSI转换先生成仅含passengerId/segmentId/itemId的占位对象，列表组装只按itemId替换完整SaasRefundOrderItemVO，不补装完整passenger、segment或itemFee。主单包含各类单号、状态/退票类型、锁单/自动化/渠道、采购与供应金额币种、航司/PNR/GDS/航程、业务时间、处理人、取消、事件、钱包、代金券和psis；item含票号/PNR及买卖双方售价、税费、应退额、罚金、服务费、平台费、币种汇率等。
【状态概览】Invoker另遍历RefundOrderStateEnum每个值，以platFormId+buyer+env+状态计数。该计数不继承列表的日期、票号、PNR、供应商等其他过滤，是租户/采购商全局概览，不是当前列表分组统计。
【空结果】票号/PNR无匹配或与显式条件冲突时，整体success=true，分页数值为0且新PageVO的pageList通常为null，同时仍返回全状态计数。普通SQL count=0时分页库返回空PageList形态。
【失败】OrderException在Invoker内转success=false、code=-1、message=系统异常并保留traceId，列表与计数不返回。校验、路由、数据库运行时或组装异常由代理转APIException：优先透传LYException/LYRuntimeException码与消息，否则code=-1并使用异常消息；Facade再组装失败响应。null请求在Facade生成trace前解引用，可能直接NPE。
【测试Oracle】断言create_time倒序且count/页数一致；三类日期开闭边界；票号/PNR无命中、原单或退票单冲突为成功空列表且仍有状态计数；票号/PNR与refundSerialNoList取交集；supplyChannel=2包含NULL；needRetryEvent false不过滤、true仅非0；firstName/lastName改变不影响结果；orderSerialNoList按refund_serial_no验证；状态概览仅随平台/采购商/env变化；page=2,size=20偏移20而size=0不使用默认；PSI只补完整item；失败语义和数据库零写入。

### 完整业务分析

#### 业务目的

提供SaaS退票管理端只读分页检索、PSI商品摘要和平台/采购商全状态概览。

#### 适用场景

用于列表展示、订单定位、人工处理队列及异常事件筛选；不用于详情全量、乘客姓名筛选或任何写操作。

#### 输入、默认值与过滤分页语义

已覆盖全部请求字段、默认值、过滤/忽略规则、票号PNR派生与交集、环境条件及枚举。

#### 返回组装与空结果语义

已覆盖公共响应、分页、主单、PSI/item装配深度、状态计数口径与空结果。

#### 完整业务流程

Facade路由至Invoker；Service预处理条件并分页读主表，逐单读item/PSI，另做全状态计数后组装。

#### 重要条件分支、计算与外部调用

覆盖票号/PNR空或冲突、supplyChannel=2兼容NULL、事件筛选、日期边界、姓名忽略和orderSerialNoList实际列。

#### 异常与失败处理

覆盖OrderException固定失败、其他异常代理转换、null请求NPE可能性、请求内部补写及无写/无远程副作用。

#### 测试 Oracle

覆盖排序分页、日期边界、条件交集、成功空结果、特殊供应渠道、忽略字段、状态概览独立口径、装配深度和失败只读断言。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
