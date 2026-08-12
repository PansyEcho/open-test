---
node_id: flow:core-order-lifecycle:recovery-flows
system_id: train-booking-core
kind: common_logic
title: 订单生命周期与失败恢复分支
summary: 主状态流之外，实时分单降级、二次分单、无票收单、联程补偿和延迟取消决定失败是否成为终态。
aliases: [二次分单, 降级收单, 延迟取消, 联程补偿]
status: inferred
confidence: 0.9
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
source_refs:
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java, symbol: CreateOrderServiceInvoker}
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OccupyFailPreActor.java, symbol: OccupyFailPreActor}
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/TickeFailPostActor.java, symbol: TickeFailPostActor}
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CancelOrderServiceInvoker.java, symbol: CancelOrderServiceInvoker}
---

<!-- kb:auto-start -->
## 确定的主状态边

- 普通出票创单：`INIT -> TICKETING`；占座类创单：`INIT -> OCCUPYING`。
- 占座结果：`OCCUPYING -> OCCUPY_SUCCESS` 或 `OCCUPY_FAIL`。
- 占座成功后申请出票：`OCCUPY_SUCCESS -> TICKETING`。
- 出票结果：`TICKETING -> ISSUE_SUCCESS` 或 `ISSUE_FAIL`。
- 取消Actor允许 `INIT`、`OCCUPYING`、`OCCUPY_SUCCESS`、`OCCUPY_FAIL`、`TICKETING` 进入 `CANCEL`，但取消入口对失败态会直接幂等返回。
- 撤单Actor允许 `OCCUPYING` 或 `TICKETING` 进入 `REVOKE`。

## 恢复路径不能简化为状态枚举

实时分单没有有效结果或调用异常时，是否降级收单取决于业务分支和配置；后续处理需要真实 `distribution_single_order` Job和任务/收单表证据。占座失败和出票驳回也可能是最终失败、换供应商、换票机或无票收单，单看 `OCCUPY_FAIL`/`ISSUE_FAIL` 不足以判断整条业务已结束。

联程批量驳回需要逐程观察，部分失败时是否补偿、补偿哪些程和是否原子回滚尚需业务确认。`OCCUPYING`取消分为立即与延迟：API取消成功或EBK未锁单可立即转 `CANCEL`；已锁单会先记录客户端取消意图并等待供应商回填，不能把接口成功直接等同最终状态已取消。

## 境内普通EBK实时分单金丝雀

普通非占座订单若实时分单同步返回非空 `merchantId`，`AbstractCollectionPreTransitActor#dealCollection` 会更新订单商户信息而不会调用 `collectionVOService.save`，随后同步进入 `TICKETING(5)`。因此金丝雀必须在出票回填前查询主库证明 `merchantType=EBK(1)`、`orderState=5`，并在Fixture明确该同步成功条件后断言临时收单库为0行；若出现收单记录，应判定为降级分支、HT污染或Fixture不符合实时成功条件。

`TicketFacade#issueTicket` 是供应商出票结果回填而不是发起出票。成功调用会同步把订单从 `TICKETING(5)` 转为 `ISSUE_SUCCESS(6)`；逐Item的 `seatClass` 与 `merchantTicketPrice` 取自对应乘客的出票请求。Item查询结果不得依赖行序，必须按业务字段做无序逐项匹配。出票成功PostActor还会异步提交清理票机Redis的任务并触发订单处理完成事件，所以Redis完成状态和MQ只能在有界轮询内分别作为直接结果与 `EFFECT_ONLY` 证据，不能声称直接读取到消息轨迹。

## HT重复创单

`CreateOrderServiceInvoker#exist` 对未落入不可复用集合的既有订单返回既有成功结果；对 `INIT`、`ISSUE_FAIL`、`OCCUPY_FAIL`、`REVOKE`、`CANCEL` 返回 `REPEAT_BOOK`。测试必须在调用前后用 `order.list_transactions_by_ht` 对比交易集合，不能仅凭响应断言“没有重复建单”。
<!-- kb:auto-end -->

## 人工确认

<!-- 人工补充区域，增量扫描不得覆盖 -->
