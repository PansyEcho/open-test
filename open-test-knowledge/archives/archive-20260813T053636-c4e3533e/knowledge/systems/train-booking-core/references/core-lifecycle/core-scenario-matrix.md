---
node_id: flow:core-order-lifecycle:scenario-matrix-v2
system_id: train-booking-core
kind: common_logic
title: 单系统DSF核心订单31场景矩阵
summary: 一期回归固定为十二类三十一个业务变体，覆盖真实创单、占座、出票、二次分单、港铁港币、联程、取消、撤单超时和HT幂等。
aliases: [31场景, 核心回归矩阵, 订单主流程]
status: inferred
confidence: 0.9
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
source_refs:
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CreateOrderServiceInvoker.java, symbol: CreateOrderServiceInvoker}
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/ticket/OccupyServiceInvoker.java, symbol: OccupyServiceInvoker}
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/ticket/AbstractRejectIssueServiceInvoker.java, symbol: AbstractRejectIssueServiceInvoker}
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/manager/trade/CancelOrderServiceInvoker.java, symbol: CancelOrderServiceInvoker}
---

<!-- kb:auto-start -->
## 固定覆盖矩阵

| 类别 | 数量 | 变体 |
|---|---:|---|
| 境内普通实时分单成功 | 2 | EBK、API；均从创单走到出票成功 |
| 实时分单失败降级收单 | 2 | 同步返回空、同步调用异常；真实收单后由分单Job继续 |
| 普通占座完整成功 | 2 | EBK、API；创单、占座成功、申请出票、出票成功 |
| 抢票即时失败 | 3 | 临近发车、非可售时间、无供应商 |
| 占座失败与二次分单 | 2 | 最终失败、换供应商或票机再占座 |
| 出票驳回 | 4 | 最终失败、换票机、换供应商、无票收单 |
| 港铁订单 | 2 | 普通港铁、12306港铁电子票 |
| 港币支付多乘客 | 3 | 成人儿童全部有价、部分缺价、价格校验不一致 |
| 联程订单 | 3 | 二程、三程、批量驳回或部分失败补偿 |
| 取消订单 | 4 | TICKETING、OCCUPY_SUCCESS、OCCUPYING未锁立即取消、OCCUPYING已锁延迟取消 |
| 撤单与超时 | 2 | 真实超时Job、供应商批量撤单 |
| HT幂等与不可复用 | 2 | 幂等成功状态重复创单、终态HT返回REPEAT_BOOK |

矩阵清单的机器可读真相源是 `cases/suites/core-order-lifecycle-coverage.yaml`。每个变体有独立稳定ID，不使用裸笛卡尔积；EBK/API、失败原因、乘客价格、联程程数和锁单状态都作为具有业务意义的分区。

## 当前可执行性

源码只能证明入口、分支和状态边，不能提供QA可用订单、乘客身份、供应商控制、驳回原因及安全清理能力。因此31个变体全部保持 `blocked`，每个文件分别列出 `missing_conditions`。这表示矩阵定义完成但不能执行，不表示场景预期已由QA验证。
<!-- kb:auto-end -->

## 人工确认

<!-- 人工补充区域，增量扫描不得覆盖 -->
