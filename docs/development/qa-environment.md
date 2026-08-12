# Booking.Core QA 环境与 Fixture

## 安全边界

Booking.Core 的 MySQL、TiDB 和 Redis 连接由 Java QA Worker 使用目标应用身份从公司远程配置中心加载。OpenTest、Python进程、LLM、Case和Git知识库都不接收以下内容：

- 数据库或Redis的Host、端口、账号、密码；
- 远程配置原文；
- MQ管理凭据；
- SDK原始异常堆栈。

因此，不再为Booking.Core配置 `connections`，也不再使用旧版 `MYSQL_PASSWORD`、`REDIS_PASSWORD` 或任意SQL参数。Worker只接受 `resource_id + operation_id`，SQL、Redis Key模板和投影逻辑固化在Worker制品中。

## 本地QA配置

真实DSF调用仍需新的Labrador Token；该Token只通过进程环境注入，不进入Git、页面或报告。配置文件位于被Git忽略的：

```text
open-test-knowledge/.opentest/environments/train-booking-core/qa.yaml
```

最小结构：

```yaml
system_id: train-booking-core
environment: qa
values:
  tool_environment:
    LABRADOR_TOKEN: ${ENV:OPENTEST_QA_LABRADOR_TOKEN}

  fixture_catalog:
    test_prefix: OPENTEST_QA_
    ebk_merchant_ref: null
    api_merchant_ref: null
    primary_ticket_machine_ref: null
    secondary_ticket_machine_ref: null
    operator_ref: null
    adult_identity_ref: null
    child_identity_ref: null
    mtr_route_ref: null
    connected_two_leg_route_ref: null
    connected_three_leg_route_ref: null

  # 31个Case实际读取的已解析输入；完整字段见qa-fixture-checklist.md。
  fixtures: {}

  validated_preconditions: {}
connections: {}
```

Fixture只保存非敏感业务引用或本地密钥管理器中的引用名，不保存真实乘客姓名、证件、手机号。字段为 `null` 时，相关Case必须保持 `BLOCKED`，不得猜测供应商、票机、操作员、路线或身份枚举。

`fixture_catalog`用于维护可复用的非敏感引用；生产Case实际从 `values.fixtures.<case_group>.*` 读取已解析请求和业务键。31组完整输入契约见 [QA Fixture清单](qa-fixture-checklist.md)。当前不会根据引用自动猜测或拼装DSF请求；没有受信Fixture构建器时，应仅在Git忽略的本地配置中准备请求，并保持缺失Case为 `BLOCKED`。

旧知识库中曾出现的Labrador Token必须先轮换。当前实现不得读取或复用该值。

## Worker应用身份

每次资源探测或业务Case Run启动独立Java进程：

```text
appName=travelsystem.java.dsf.supplychain.booking.core
environment=qa
```

控制面只向Worker传递 `PATH / JAVA_HOME / LANG / LC_* / TZ / TMPDIR` 白名单，不继承 `DAOKEAPPUK`、`DAOKEENV`、Token、API Key、云凭据或数据库变量。Worker校验最终身份，只使用数据库READ池；READ池不存在时返回稳定 `BLOCKED` 错误，不回退WRITE。TiDB是独立资源，不作为MySQL失败后的兜底。

构建与验证命令：

```bash
mvn -o -f workers/qa-oracle-worker/pom.xml clean test package
```

依赖已下载到本机 `~/.m2` 后，默认使用离线模式，日常测试和打包不再访问公司Nexus。仅新增或升级依赖、或者本地Maven缓存被清理时，才去掉 `-o` 并申请联网执行权限。

产物固定为：

```text
workers/qa-oracle-worker/target/opentest-qa-oracle-worker.jar
```

## 批准Oracle

首批固定业务操作：

- `resource.probe`
- `order.primary_detail`
- `order.list_transactions_by_ht`
- `order.items_by_transaction`
- `order.tidb_projection`
- `order.query_tasks`
- `collection.detail`
- `redis.ticket_machine_pending_membership`
- `redis.merchant_pending_membership`
- `redis.order_done_status`
- `mq.trace_match`

`resource.probe`只证明远程配置和只读资源可连接，对应页面状态为 `CONNECTED`，不计入业务Case。只有Snapshot绑定的业务Case Oracle通过后，资源才能进入 `READY`。MQ缺少只读轨迹端点时，`mq.trace_match` 返回 `EFFECT_ONLY` 或 `BLOCKED`；`EFFECT_ONLY`只证明消费后的业务效果。

## 全局Job

全局Job执行前必须完成批准只读影响Oracle，并在页面展示：

- 预计处理数量；
- 本轮测试订单数量；
- 非本轮订单数量。

三类计数不闭合时不签发Token。确认Token五分钟有效、只能使用一次，并绑定系统、Suite、变体、Snapshot、脚本摘要和目标URL。执行请求还必须携带 `allow_global_job=true`；任何非QA、脚本漂移或URL环境漂移都会在Runner调用前被拒绝。

## 真实QA执行顺序

1. 轮换旧Labrador Token，并只设置新的 `OPENTEST_QA_LABRADOR_TOKEN` 环境变量。
2. 在本地Git忽略配置中补齐非敏感Fixture引用。
3. 构建Worker，创建绑定Worker和Oracle目录摘要的新Snapshot。
4. 在“QA资源与MQ”页面运行探测；连接成功只显示 `CONNECTED`。
5. 先执行一个境内普通成人订单金丝雀，并用同一订单的DSF与MySQL结果交叉确认路由。
6. 分批运行31个业务变体；TiDB最长轮询180秒，MQ业务效果最长180秒，全局Job最长600秒。
7. 所有必需Oracle通过后才显示 `READY`；Fixture或环境不满足的Case保留 `BLOCKED`。

## 本地服务与网络边界

OpenTest页面验收和真实资源探测使用仅绑定回环地址的本地服务：

```bash
python3 -m uvicorn opentest.api:app --host 127.0.0.1 --port 8788
```

该进程需要保持运行。Codex沙箱可能无法监听本地端口，也可能无法解析公司远程配置域名；此时由用户本机终端启动服务，后续页面触发的Worker会继承本机公司网络条件。沙箱内出现 `RESOURCE_PROVIDER_UNAVAILABLE` 只表示当前执行网络无法初始化公司SDK，不能据此判断QA资源本身不可用。
