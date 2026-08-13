---
node_id: state-machine:OrderStateEnum
system_id: train-booking-core
kind: state_machine
title: 订单状态机
summary: createOrder根据占座类型和业务分支进入TICKETING、OCCUPYING或OCCUPY_FAIL。
aliases:
- OrderStateEnum
- 订单状态
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/ConfirmOccupyTicketingPostActor.java
  symbol: ConfirmOccupyTicketingPostActor
  line: 27
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/ConfirmOccupyTicketingPreActor.java
  symbol: ConfirmOccupyTicketingPreActor
  line: 29
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/ImmediateFailPreActor.java
  symbol: ImmediateFailPreActor
  line: 31
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OccupyFailPostActor.java
  symbol: OccupyFailPostActor
  line: 35
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OccupyFailPreActor.java
  symbol: OccupyFailPreActor
  line: 29
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OccupySuccessPostActor.java
  symbol: OccupySuccessPostActor
  line: 31
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OccupySuccessPreActor.java
  symbol: OccupySuccessPreActor
  line: 29
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OccupyingPostActor.java
  symbol: OccupyingPostActor
  line: 31
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OccupyingPreActor.java
  symbol: OccupyingPreActor
  line: 19
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OrderCancelPostActor.java
  symbol: OrderCancelPostActor
  line: 33
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OrderCancelPreActor.java
  symbol: OrderCancelPreActor
  line: 31
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/RevokePostActor.java
  symbol: RevokePostActor
  line: 39
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/RevokePreActor.java
  symbol: RevokePreActor
  line: 35
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/TickeFailPostActor.java
  symbol: TickeFailPostActor
  line: 39
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/TicketFailPreActor.java
  symbol: TicketFailPreActor
  line: 29
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/TicketSuccessPostActor.java
  symbol: TicketSuccessPostActor
  line: 45
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/TicketSuccessPreActor.java
  symbol: TicketSuccessPreActor
  line: 29
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/TicketingPostActor.java
  symbol: TicketingPostActor
  line: 31
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/TicketingPreActor.java
  symbol: TicketingPreActor
  line: 18
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.536108Z'
---

<!-- kb:auto-start -->
## 业务结论

createOrder根据占座类型和业务分支进入TICKETING、OCCUPYING或OCCUPY_FAIL。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/ConfirmOccupyTicketingPostActor.java:27 ConfirmOccupyTicketingPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/ConfirmOccupyTicketingPreActor.java:29 ConfirmOccupyTicketingPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/ImmediateFailPreActor.java:31 ImmediateFailPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OccupyFailPostActor.java:35 OccupyFailPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OccupyFailPreActor.java:29 OccupyFailPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OccupySuccessPostActor.java:31 OccupySuccessPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OccupySuccessPreActor.java:29 OccupySuccessPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OccupyingPostActor.java:31 OccupyingPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OccupyingPreActor.java:19 OccupyingPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/OrderCancelPostActor.java:33 OrderCancelPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/OrderCancelPreActor.java:31 OrderCancelPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/RevokePostActor.java:39 RevokePostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/RevokePreActor.java:35 RevokePreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/TickeFailPostActor.java:39 TickeFailPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/TicketFailPreActor.java:29 TicketFailPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/TicketSuccessPostActor.java:45 TicketSuccessPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/TicketSuccessPreActor.java:29 TicketSuccessPreActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/post/TicketingPostActor.java:31 TicketingPostActor`
- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/actor/pre/TicketingPreActor.java:18 TicketingPreActor`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
