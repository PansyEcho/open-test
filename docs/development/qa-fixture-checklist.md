# Booking.Core QA Fixture清单

## 决策

31个核心生命周期Case统一从Git忽略配置的 `values.fixtures` 读取已解析输入。CaseStore只把Git资产中的 `${fixtures.*}` 确定性转换为 `${qa.fixtures.*}`，不会猜测订单、供应商、票机、身份或请求字段。

敏感测试身份和完整请求只允许存在于本地Git忽略文件或后续受信Fixture构建器中，不写入本文件、Git知识库、页面或报告。尚未准备好的字段保持缺失，相关Case继续显示 `BLOCKED`。

本地配置路径：

```text
open-test-knowledge/.opentest/environments/train-booking-core/qa.yaml
```

## 31组Fixture与必填字段

| Fixture组 | 必填字段 |
|---|---|
| `domestic_ebk` | `create_request`, `issue_request`, `expected_passenger_count`, `expected_issue_items` |
| `domestic_api` | `create_request`, `issue_request`, `order_serial_no`, `transaction_serial_no` |
| `empty_fallback` | `create_request`, `job_args`, `order_serial_no`, `transaction_serial_no`, `trace_id` |
| `exception_fallback` | `create_request`, `job_args`, `order_serial_no`, `transaction_serial_no`, `trace_id` |
| `ebk_occupy` | `create_request`, `occupy_success_request`, `apply_issue_request`, `issue_success_request`, `order_serial_no`, `transaction_serial_no` |
| `api_occupy` | `create_request`, `occupy_success_request`, `apply_issue_request`, `issue_success_request`, `order_serial_no`, `transaction_serial_no` |
| `grab_approach` | `create_request`, `order_serial_no`, `transaction_serial_no` |
| `grab_outside_sale` | `create_request`, `order_serial_no` |
| `grab_no_merchant` | `create_request`, `order_serial_no`, `transaction_serial_no` |
| `occupy_final_fail` | `request`, `order_serial_no`, `transaction_serial_no` |
| `occupy_second_dispatch` | `request`, `job_args`, `order_serial_no`, `transaction_serial_no`, `trace_id`, `expected_merchant_id`, `expected_ticket_machine_id` |
| `reject_final` | `request`, `order_serial_no`, `transaction_serial_no` |
| `reject_switch_machine` | `request`, `order_serial_no`, `transaction_serial_no`, `expected_transaction_serial_no`, `expected_ticket_machine_id` |
| `reject_switch_merchant` | `request`, `order_serial_no`, `transaction_serial_no`, `expected_transaction_serial_no`, `expected_merchant_id` |
| `reject_lack_ticket` | `request`, `order_serial_no`, `transaction_serial_no` |
| `mtr_standard` | `create_request`, `order_serial_no`, `transaction_serial_no` |
| `mtr_12306` | `create_request`, `order_serial_no`, `transaction_serial_no` |
| `hkd_all_priced` | `create_request`, `order_serial_no`, `transaction_serial_no` |
| `hkd_partial_missing` | `create_request`, `order_serial_no` |
| `hkd_price_mismatch` | `create_request`, `order_serial_no` |
| `connect_two_leg` | `first_create_request`, `second_create_request`, `first_order_serial_no`, `second_order_serial_no`, `first_transaction_serial_no`, `second_transaction_serial_no`, `wisdom_travel_serial_no` |
| `connect_three_leg` | `first_create_request`, `second_create_request`, `third_create_request`, `first_order_serial_no`, `second_order_serial_no`, `third_order_serial_no`, `first_transaction_serial_no`, `second_transaction_serial_no`, `third_transaction_serial_no`, `wisdom_travel_serial_no` |
| `connect_reject` | `batch_request`, `job_args`, `first_order_serial_no`, `second_order_serial_no`, `first_transaction_serial_no`, `second_transaction_serial_no`, `wisdom_travel_serial_no`, `trace_id` |
| `cancel_ticketing` | `request`, `order_serial_no`, `transaction_serial_no` |
| `cancel_occupy_success` | `request`, `order_serial_no`, `transaction_serial_no` |
| `cancel_occupying_unlocked` | `request`, `order_serial_no`, `transaction_serial_no`, `merchant_id` |
| `cancel_occupying_locked` | `request`, `order_serial_no`, `transaction_serial_no`, `merchant_id` |
| `timeout_job` | `args`, `order_serial_no`, `transaction_serial_no`, `trace_id` |
| `supplier_batch_revoke` | `request`, `batch_key`, `first_order_serial_no`, `second_order_serial_no`, `first_transaction_serial_no`, `second_transaction_serial_no` |
| `ht_active` | `original_create_request`, `order_serial_no` |
| `ht_terminal` | `repeat_create_request`, `order_serial_no` |

## 可执行前的额外门禁

- 每个Oracle步骤必须写入经确认的非空 `assertions`；`expected_business_outcome`不会自动冒充数据库断言。
- Job Case还必须完成QA URL重绑、只读影响预估和五分钟一次性Token确认。
- `order_serial_no`、`transaction_serial_no`等运行后才能产生的值，应由Fixture准备步骤或前序步骤输出注入，不能预填虚构值。首条EBK金丝雀已改为直接消费 `execute-create` 的真实输出。
- `domestic_ebk.expected_issue_items` 按业务键做无序逐Item匹配；每项只写预计 `passengerType / seatClass / merchantTicketPrice` 等白名单业务字段，不依赖数据库返回顺序，也不保存姓名、证件或手机号。
- Token只通过 `OPENTEST_QA_LABRADOR_TOKEN`进程环境注入，不写入本地YAML。
