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
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/RefundFacade.java
  symbol: RefundFacade#cancel
  line: 84
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundFacadeImpl.java
  symbol: RefundFacadeImpl#cancel
  line: 292
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/validator/trade/RefundCancelValidator.java
  symbol: RefundCancelValidator#validate
  line: 19
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/request/RefundCancelRequest.java
  symbol: RefundCancelRequest
  line: 13
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/BaseRequest.java
  symbol: BaseRequest
  line: 14
  commit: ''
  content_digest: ''
- repository: ''
  path: app/facade/src/main/java/com/ly/flight/chainsaas/refund/facade/model/response/RefundCancelResponse.java
  symbol: RefundCancelResponse
  line: 3
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: RefundCancelServiceInvoker#invoke
  line: 80
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: RefundCancelServiceInvoker#innerInvoke
  line: 99
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/manager/refund/RefundCancelServiceInvoker.java
  symbol: RefundCancelServiceInvoker#doInvoke
  line: 114
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
  path: app/dal/src/main/resources/sqlmap/refundcore/SaasRefundOrderMapperExt.xml
  symbol: queryByRefundSerialNo
  line: 169
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor
  line: 25
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor#addTask
  line: 32
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderCancelPostActor.java
  symbol: RefundOrderCancelPostActor#addCancelReasonUpdateTask
  line: 52
  commit: ''
  content_digest: ''
- repository: ''
  path: app/biz/src/main/java/com/ly/flight/chainsaas/refund/biz/actor/post/RefundOrderManualCancelPostActor.java
  symbol: RefundOrderManualCancelPostActor
  line: 20
  commit: ''
  content_digest: ''
status: inferred
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260825075610-a0f437c374-8132c1a1
  tool_id: facade.refund.cancel
  analysis_depth: business
  branch_count: 0
  external_call_count: 0
invocation_contract: null
updated_at: '2026-08-26T01:52:09.369192Z'
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

## Agent代码解释（INFERRED）

POST /cancel 接收请求，生成或沿用 traceId，路由 CANCEL；异常转响应并清理日志上下文。

### 完整业务分析

#### 业务目的

将退票单置为 REFUND_CANCEL，阻止继续退票并保存取消原因、备注、操作日志；CBDS 自动化取消同步资源侧。

#### 适用场景

取消指定退票单；适用于申请、待退票、核价中、退票失败和审核通过状态的主动或超时取消；已取消重复调用幂等成功。无日期、分页，按退票单号查询单笔订单。

#### 输入、默认值与过滤分页语义

请求含 refundSerialNo、cancelReasonId、cancelReason、cancelRemark，公共字段含 traceId、operator。traceId、refundSerialNo、cancelReasonId、cancelReason 必填；cancelRemark 非必填；无日期、过滤、分页。

#### 返回组装与空结果语义

成功为 success=true、回传 traceId、orderSerialNo=refundSerialNo；失败由 facade 统一组装，显式失败构造为 success=false、code=-1、message=取消失败。

#### 完整业务流程

Facade 路由 CANCEL，Validator 校验；Invoker 加订单操作锁并查询。不存在报错，已取消直接成功；其余状态通过后转 REFUND_CANCEL。普通状态追加原因更新和取消日志，AUDITED 记录系统取消日志；CBDS/SAPL 非代金券订单调用 CBDS 取消。

#### 重要条件分支、计算与外部调用

REFUND_CANCEL 幂等成功；PENDING_APPLY、WAIT_REFUND、RESHOPING、REFUND_FAIL 使用普通取消 actor；AUDITED 使用人工取消 actor；仅非代金券且 gds=SAPL、officeNo 为 CBDS 时调用 CBDS。

#### 异常与失败处理

四个必填字段缺失时校验失败；订单不存在、状态不可取消、状态机异常转换为业务异常；Facade 转换 APIException 并 finally 清理日志上下文；并发由订单操作锁控制。

#### 测试 Oracle

有效可取消订单断言成功、状态 REFUND_CANCEL、traceId 和订单号正确；重复取消仍成功。缺字段、无订单、非法状态断言失败。普通状态断言原因更新及取消日志任务，AUDITED 断言 AUDITED_CANCEL，CBDS 非代金券断言调用取消，其他分支不调用。
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
