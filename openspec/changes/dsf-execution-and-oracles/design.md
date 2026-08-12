# DSF执行与Oracle设计

## Decisions

### 逻辑工具解析

Scenario只保存 `facade.trade.create_order` 等逻辑ID。执行时从Snapshot绑定的ScanManifest取ToolDefinition，并验证脚本仍位于该manifest的tool_root、状态为ready且路径不含platform固定shim。请求写入权限受限临时文件并以无shell参数 `--request-file` 调用，避免身份数据出现在进程参数列表。

### 类型化执行内核

变量只允许 `${inputs.*}`、`${steps.<id>.output.*}` 与 `${qa.*}` 三个命名空间。核心生命周期文档的 `${fixtures.*}` 在发布时确定性编译为 `${qa.fixtures.*}`。完整占位符保留原类型；字符串内插仅接受标量；残留或非白名单占位符在调用前拒绝。generated、user_edited以及执行边界都要求至少一个非空业务断言，每个Oracle步骤也必须有自己的稳定断言；空断言作为契约错误，不表示“零差异通过”。

### Oracle边界

OracleRequest声明dsf、mysql、tidb、redis或mq、逻辑资源、固定操作和稳定预期，并作为 `action: oracle` 的ScenarioStep进入正常执行编排。DSF继续使用Snapshot绑定工具；MySQL、TiDB和Redis统一交给Java QA Worker。Worker只接受Snapshot绑定操作目录中的 `operation_id`，拒绝SQL文本、任意Redis命令、动态环境与连接参数。异步结果由统一Poller把剩余deadline传入每次读取，所有观察值写入本地证据。MQ没有只读轨迹接口时只允许登记 `EFFECT_ONLY` 业务效果证据。

### Java QA Worker

Worker是当前仓库中的Java 8 Maven模块，不加载booking.core完整Spring/Web/Job/MQ组件。OpenTest只向子进程传递PATH、JAVA_HOME、语言、时区和临时目录白名单，并设置 `appName=travelsystem.java.dsf.supplychain.booking.core` 与 `environment=qa`，Worker启动后再次校验身份。数据库必须取得READ池并直接使用只读数据源，READ池缺失时不得回退WRITE；TiDB绑定独立逻辑资源。Redis只允许固定Key模板和读操作。每个资源探测任务或Case Run使用独立Worker进程，结束时关闭数据源并退出JVM。

请求仅包含request、系统、环境、资源、操作、业务参数、deadline和目录摘要；响应只返回白名单投影、耗时与稳定错误码。SDK日志单独捕获并脱敏，不进入Agent上下文或API响应。

### 资源状态与业务证据

源码扫描发现逻辑数据源、Redis Group、MQ生产者/消费者和Topic配置Key，并保存源码证据。状态按 `DISCOVERED / CONNECTED / READY / BLOCKED / EFFECT_ONLY / STALE` 管理。连接探测只更新资源状态；只有Snapshot绑定的业务Case中对应Oracle步骤真实通过、断言非空且存在观察证据后，资源才可携带步骤ID与断言摘要进入READY或EFFECT_ONLY。页面不得展示Host、账号、密码、Token、远程配置原文或SDK异常。

### 回归套件与全局Job

核心业务变体按Suite批量执行，每个变体仍生成独立RunRecord。`cases/custom` 由CaseStore严格编译为统一ScenarioVariant，BLOCKED原因原样保留。全局Job运行前从Snapshot manifest重读工具ID、脚本SHA和URL，再生成只读影响预估和五分钟一次性确认Token；执行请求必须显式携带 `allow_global_job=true`。非QA环境、过期Token或工具URL环境不一致均在调用前拒绝。

### Snapshot

Snapshot包含源码基线、知识Git HEAD（如有）、知识树摘要、Case摘要、工具manifest与每个脚本字节摘要、Worker Jar摘要、Oracle操作目录摘要和Skill摘要。任何摘要变化都会形成新Snapshot ID；读取时重新校验内容寻址身份，执行只能引用未漂移的已保存Snapshot。

## Failure Strategy

- 工具越界、shim或版本不匹配：执行前拒绝。
- 变量缺失：步骤失败且不把空字符串代入。
- JSON解析或硬断言失败：保留stdout/stderr摘要和结构化diff。
- Oracle截止时间：失败并保存最后观察证据。
- Worker身份、READ池、操作目录或资源路由不满足：返回稳定错误码并将资源标为BLOCKED。
- MQ只有下游效果证据：Case可以按声明的效果断言通过，但资源状态保持EFFECT_ONLY。
- 全局Job没有有效确认Token或环境不一致：执行前拒绝。
- 清理失败：运行失败并单独标记，避免假装环境已恢复。
