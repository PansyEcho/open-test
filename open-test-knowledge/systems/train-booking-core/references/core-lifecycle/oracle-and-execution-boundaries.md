---
node_id: flow:core-order-lifecycle:oracle-boundaries-v2
system_id: train-booking-core
kind: data_source
title: 核心31场景Oracle与执行边界
summary: Case只引用已确认逻辑资源和固定操作目录；数据库与Redis为直接证据，MQ只能登记EFFECT_ONLY。
aliases: [Oracle操作目录, QA Worker, EFFECT_ONLY]
status: code_verified
confidence: 1.0
metadata:
  scan_id: scan-20260811091050-dc8391e426-0a843ec3
  source_commit: 1f43c3b0e3ee2893e53c50b7fc36f479890e903e
source_refs:
- {path: workers/qa-oracle-worker/src/main/java/com/opentest/qaoracle/catalog/OperationCatalog.java, symbol: OperationCatalog}
- {path: app/biz/src/main/java/com/ly/travel/train/supplychain/bookingcore/biz/job/collection/TimeOutCancelJob.java, symbol: TimeOutCancelJob}
---

<!-- kb:auto-start -->
## 已确认资源

| 角色 | resource_id |
|---|---|
| 订单主MySQL | `resource:train-booking-core:mysql:database:bookingcoredatasource` |
| 收单临时MySQL | `resource:train-booking-core:mysql:database:temporderdatasource` |
| 业务TiDB | `resource:train-booking-core:tidb:database:bookingcoretidbdatasource` |
| 分析TiDB | `resource:train-booking-core:tidb:database:bookingcoretidbanalydatasource` |
| 运行态Redis | `resource:train-booking-core:redis:cache:redissionproxy` |
| Job消息监听 | `resource:train-booking-core:mq:consumer:jobmessagelistener` |

MQ资源必须来自具体扫描到的consumer/producer。本批只在真实Job相关变体使用已确认的 `jobmessagelistener`，未给普通事件自造通用MQ资源。

## 首批固定操作

- 订单与交易：`order.primary_detail`、`order.list_transactions_by_ht`、`order.items_by_transaction`、`order.tidb_projection`、`order.query_tasks`。
- 收单：`collection.detail`。
- Redis：`redis.ticket_machine_pending_membership`、`redis.merchant_pending_membership`、`redis.order_done_status`。
- MQ效果：`mq.trace_match`，证据等级固定为 `EFFECT_ONLY`。
- `resource.probe` 只用于连接探测，不作为业务Case通过证据。

三个Redis操作都使用固定模板。票机集合查询必须传 `ticket_machine_id + order_serial_no + transaction_serial_no`；商户集合查询必须传 `merchant_id + order_serial_no + transaction_serial_no`；完成状态查询必须传 `order_serial_no + transaction_serial_no`。Case不得写入Key模板或Redis命令。

## 全局Job门禁

`distribution_single_order`、`lack_ticket_retry_job`、`new_distribution_multiple_connect_order` 和 `time_out_cancel_job` 可能影响一批订单。包含这些工具的变体必须先生成只读影响预估，并取得绑定Snapshot、脚本摘要、URL、Suite和变体的一次性QA确认Token；缺少任一条件时保持 `blocked`。当前扫描工具README显示Job脚本默认URL为测试网关而非已确认QA绑定，因此这些变体还显式缺少 `qa_job_url_binding`。本知识生成过程未执行任何Job或QA请求。
<!-- kb:auto-end -->

## 人工确认

<!-- 人工补充区域，增量扫描不得覆盖 -->
