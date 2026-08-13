# QA Oracle Worker

该模块是 OpenTest 与公司远程配置资源之间的最小安全边界。它是 Java 8 单请求、单进程、文件协议 Worker，不启动 booking.core 的 Spring、Web、Job 或 MQ Consumer。

## 安全约束

- 固定 `system_id=travelsystem.java.dsf.supplychain.booking.core`、`environment=qa`。
- 进程必须使用 `-DappName=travelsystem.java.dsf.supplychain.booking.core -Denvironment=qa`。
- 启动器必须清除 `DAOKEAPPUK` 和 `DAOKEENV`；Worker 检测到继承值会拒绝运行。
- 请求只能使用 `OperationCatalog` 中的 `operation_id + parameters`，不能传 SQL、JDBC URL、Host、密码、Token、Redis命令、MQ URL或HTTP路径。
- JDBC SPI 只能返回已标记的 READ 连接。READ池缺失或返回非只读连接时直接阻塞，绝不回退WRITE。
- Redis SPI 只暴露 `PING / EXISTS / GET后等值比较 / SISMEMBER / TTL`，没有任何写方法；GET原值不会进入响应。
- 没有消息轨迹端点时，MQ只返回 `EFFECT_ONLY`，不声称直接验证了消息。
- 请求文件和响应目标必须预先创建为0600普通文件，不允许符号链接或相对路径。
- 响应通过同目录0600临时文件、`fsync`和原子替换写入；stdout/stderr仅允许安全日志，不承载响应协议。
- `catalog.yaml` 使用 V2 公共 `snake_case` 契约，只批准内置 `operation_id/resource_id`、展示元数据及摘要，不能提供或覆盖SQL、Redis模板。

## 公司远程配置适配器

模块已内置真实 `CompanySdkResourceFactory`，并通过 Java `ServiceLoader` 注册：

```text
META-INF/services/com.opentest.qaoracle.resource.CompanyResourceFactory
```

适配器使用 `dal-new:3.6.6`、`cache:3.6.8` 和 `configcenterclient:6.2.8`，固定使用上述 appName 和 QA 环境，由SDK在Worker进程内从远程配置解析连接，不接收或输出连接地址与密钥：

- `resource:travelsystem.java.dsf.supplychain.booking.core:mysql:database:bookingcoredatasource`：订单主库 READ 池；
- `resource:travelsystem.java.dsf.supplychain.booking.core:mysql:database:temporderdatasource`：收单临时库 READ 池；
- `resource:travelsystem.java.dsf.supplychain.booking.core:tidb:database:bookingcoretidbdatasource`：业务 TiDB READ 池；
- `resource:travelsystem.java.dsf.supplychain.booking.core:tidb:database:bookingcoretidbanalydatasource`：分析 TiDB READ 池；
- `resource:travelsystem.java.dsf.supplychain.booking.core:redis:cache:redissionproxy`：Redis逻辑资源的只读包装。适配器不得直接暴露Redisson可写客户端；
- `resource:travelsystem.java.dsf.supplychain.booking.core:mq:consumer:jobmessagelistener`：源码发现的实际 Consumer 逻辑资源；一期不连接MQ，仅声明下游效果验证模式。

数据库映射来自 booking.core 的 `bookingcore-db-beans.xml`：订单主库、临时库、业务TiDB和分析TiDB分别固定到
`TETravelTrainSupplychainOrder`、`TETravelTrainScTempOrder`、`TETravelTrainSupplychainOrder_tidb` 和
`TETravelTrainSupplychainOrder_tidb_analy`。Redis Group 固定为
`travelsystem.java.dsf.supplychain.booking.core`。

`UnavailableCompanyResourceFactory` 仅是 ServiceLoader 未找到实现时的 fail-closed 阻塞实现，不是生产占位SPI；本模块打包时由服务文件加载真实SDK实现。DAL 初始化后必须存在非空 `DataSourceType.READ` 池，只调用
`switchToReadDB()`，随后设置并复核 JDBC `readOnly`；任何一步失败都返回稳定阻塞码，绝不调用或回退
`switchToWriteDB()`。Worker自己的日志和响应不记录SDK异常原文；公司SDK自身日志应由启动器写入受限本地文件并按公司规范脱敏。

## 固定操作目录

Python包中的 `opentest/assets/booking_core_validation_catalog.yaml` 是不含SQL、Key模板或连接信息的交付模板；注册Booking.Core后会原子复制到对应系统知识目录。内置目录固定为16个
`operation_id/resource_id` 复合绑定、11个唯一 `operation_id`：

| operation_id | 资源 | 请求参数 | 安全投影/结果 |
|---|---|---|---|
| `order.primary_detail` | 订单MySQL | `order_serial_no, transaction_serial_no` | HT/TX、订单/操作/锁状态、商户与出票机ID、占位/连接类型、币种、验价、删除状态、环境 |
| `order.list_transactions_by_ht` | 业务TiDB | `order_serial_no` | 同HT的TX、状态、商户/出票机、改签次数、币种 |
| `order.items_by_transaction` | 订单MySQL | `transaction_serial_no` | Item ID、`passengerType`、席别、安全价格字段、删除状态；经OPSI关联且不返回乘客ID或隐私 |
| `order.tidb_projection` | 业务TiDB | `order_serial_no, transaction_serial_no` | 订单状态、路由、金额、外币金额、汇率、验价 |
| `order.query_tasks` | 业务TiDB | `order_serial_no` | TX、任务类型/状态/重试次数 |
| `collection.detail` | 临时MySQL | `order_serial_no` | 收单连接/次数/类型、港币优先级、占位、乘客数、席别、订单类型 |
| `redis.ticket_machine_pending_membership` | Redis | `ticket_machine_id, order_serial_no, transaction_serial_no` | `exists, valueMatches, ttlSeconds` |
| `redis.merchant_pending_membership` | Redis | `merchant_id, order_serial_no, transaction_serial_no` | `member, ttlSeconds` |
| `redis.order_done_status` | Redis | `order_serial_no, transaction_serial_no` | `exists, ttlSeconds` |
| `resource.probe` | 4个数据库/TiDB + Redis | 无 | `connected`；分别形成5个复合绑定 |
| `mq.trace_match` | MQ逻辑资源 | `trace_id` | `directVerified=false, evidenceMode=downstream_effect_only` |

列表查询最多允许100行。SQL和JDBC驱动最多读取101行用于识别超限；发现第101行时返回
`RESULT_LIMIT_EXCEEDED`，不会把静默截断的部分结果当作成功证据。

## 请求示例

调用方对本次使用的 `catalog.yaml` 原始文件字节计算 SHA-256，并把同一摘要绑定到 Snapshot 和请求。
Worker 会在解析并验证 catalog 后重新计算文件摘要；该摘要与内置操作集合摘要不是同一个概念：

```json
{
  "request_id": "req-001",
  "system_id": "travelsystem.java.dsf.supplychain.booking.core",
  "environment": "qa",
  "resource_id": "resource:travelsystem.java.dsf.supplychain.booking.core:mysql:database:bookingcoredatasource",
  "operation_id": "order.primary_detail",
  "parameters": {
    "order_serial_no": "HT...",
    "transaction_serial_no": "..."
  },
  "deadline_ms": 20000,
  "catalog_digest": "<catalog-file-sha256>"
}
```

知识库 `catalog.yaml` 单项示例（实际文件必须完整保留全部15个绑定）：

```yaml
schema_version: 1
system_id: travelsystem.java.dsf.supplychain.booking.core
operations:
  - operation_id: order.primary_detail
    resource_id: resource:travelsystem.java.dsf.supplychain.booking.core:mysql:database:bookingcoredatasource
    kind: mysql
    title: 订单主表状态查询
    parameter_names:
      - order_serial_no
      - transaction_serial_no
    result_fields:
      - orderSerialNo
      - transactionSerialNo
      - orderState
      - operateState
      - lockState
    evidence_level: direct
  # Git知识库中的 catalog.yaml 已完整列出其余绑定
```

顶层和操作对象均拒绝未知字段。`kind` 必须与内置资源类型一致，MQ 操作 `mq.trace_match` 必须使用
`evidence_level: effect_only`；公开参数名和结果字段只用于展示及契约核对，不参与生成 SQL 或 Redis Key。
资源连通性统一使用 `operation_id: resource.probe`，但 catalog 必须分别列出并绑定上述 5 个数据库/Redis
资源；Worker 使用 `(operation_id, resource_id)` 复合键匹配，任何额外资源都会返回 `UNKNOWN_RESOURCE`。

响应统一为以下类型化结构。成功响应的 `error_code` 为空；失败响应的 `status` 为 `failed`、
`resource_status` 为 `BLOCKED`，并带稳定错误码：

```json
{
  "request_id": "req-001",
  "status": "success",
  "resource_status": "CONNECTED",
  "value": {"connected": true},
  "elapsed_ms": 8,
  "error_code": null,
  "message": "ok"
}
```

## 构建与测试

```bash
mvn -f workers/qa-oracle-worker/pom.xml test
mvn -f workers/qa-oracle-worker/pom.xml test package
```

运行Jar时只在命令行传递不含业务数据的绝对文件路径：

```bash
java -DappName=travelsystem.java.dsf.supplychain.booking.core \
  -Denvironment=qa \
  -jar workers/qa-oracle-worker/target/opentest-qa-oracle-worker.jar \
  --request-file /absolute/run/request.json \
  --response-file /absolute/run/response.json \
  --catalog /absolute/snapshot/catalog.yaml
```
