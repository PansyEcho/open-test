---
node_id: rule:create-order:hk-payment-verify
system_id: train-booking-core
kind: business_rule
title: 港币支付逐乘客价格校验
summary: 仅HK_PAYMENT逐乘客校验foreignTicketPrice；为空或低于有效路线报价时失败，无路线报价则继续，异常时fail-open返回true。
aliases:
- hkPaymentVerify
- foreignTicketPrice
- 港币支付
source_refs:
- repository: ''
  path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java
  symbol: OrderBuilder#verifyHkPayment
  line: 359
  commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
status: code_verified
confidence: 1.0
tags: []
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
updated_at: '2026-08-11T09:26:51.535480Z'
---

<!-- kb:auto-start -->
## 业务结论

仅HK_PAYMENT逐乘客校验foreignTicketPrice；为空或低于有效路线报价时失败，无路线报价则继续，异常时fail-open返回true。

## 源码证据

- `app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/builder/OrderBuilder.java:359 OrderBuilder#verifyHkPayment`
<!-- kb:auto-end -->

## 补充说明

<!-- 以下为人工补充区域，自动更新不会覆盖 -->
