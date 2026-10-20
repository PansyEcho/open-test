# Case 生成完善：需求评审简版

2026-10-19。实现、两次真实 QA 闭环及 OCR delegation 独立审查已完成。本文说明需求与使用边界，最终交付记录见 `add-coverage-assisted-case-generation` 的 tasks。

**本次实施准入已通过：** 退款样本 `7b962925db34b181f66e39a9262356585a8fcc03` 的构建 WAR、源码及 QA 覆盖数据已取得，可比较的 300 条业务类 class ID 匹配、不匹配为 0；用户已明确允许该 QA agent reset。每轮运行仍须取得所选版本的实际构建制品并核对 class ID，缺制品或不匹配只跳过增强，基础 Case 及原有验证继续。

覆盖辅助生成 Case 时提供可选的 `source_revision` 输入，填写 commit/tag；留空则解析 `qa` 分支当时的最新提交。开始生成前将其固定为完整 commit，复用已有源码 pin 和扫描结果，重试、继续及增强版本继承该固定基线，不跟随分支或 tag 后续移动。非增强历史生成未指定版本时保持既有行为。本次选择 `7b962925`，固定值为上述完整 commit。手选或默认版本都不保证 QA 正在运行该版本；本期不以自动识别部署版本作为开工前提。

## 需要解决什么

| 需求 | 要做什么，以及为什么 |
| --- | --- |
| 1. 用 JaCoCo 反馈补充遗漏代码流程 | 基础 Case 先返回，在现有自动验证前后采集覆盖率，最多补充一轮。只向模型提供有界的实测缺口；未解决项不阻断基础发布或改变原执行结果。 |
| 2. 动态发现实例，按需采集 | 本期仅支持人工确认单实例的 QA 应用，从最近有效天网日志取得候选 IP；允许清零时在执行前 reset，完成后立即采集。实例发现通过可替换接口接入，本期实现天网适配器。 |
| 3. 增强可选、进度可恢复 | 数据库保存进度和精确执行关联；重启后恢复已保存的分析或原模型运行。业务执行中断则结束失效测量，不自动重跑；确认执行进程退出后解除其遗留 RUNNING 占用。未启用或缺依赖不影响基础 Case。 |
| 4. 保存效果和分析材料 | 保存覆盖前后变化、缺口处置、复核意见、最终决定及成本，便于判断优化是否有效。大报告先按系统＋环境保留最近一轮，保留粒度可调整。 |

数据函数固定版本复用、each/pairwise/cartesian 展开及变体执行均使用现有能力，不作为新增需求；现有编译上限为 100 个 Variant。本期不实现业务场景／参数组合穷尽判断。

**MySQL／Redis 操作识别及校验本期不交付，单独开 OpenSpec change。** 该独立需求的关注规则独立配置，业务数据操作按实际语义设计断言，同一调用链的重复命中合并；“每接口最多 10 项”只是待样本验证的建议值。识别不确定或框架调用不自动变成校验义务。

本期由使用者人工保证：目标应用在 QA 的整个测量期间只有一个承接请求的实例，且采集的是该实例。“单实例”指一个服务容器／JVM，不是同一台主机上可以有多个副本。程序暂不判断副本数量，不以入口方法是否命中推断请求归属；不新增确认弹窗或确认状态字段。

启用覆盖增强时，生成页面展示提示：

> 覆盖率辅助生成仅适用于 QA 单实例应用，请人工确认测试期间只有一个服务实例。多实例可能让请求落到其他实例，造成覆盖率偏低、误报缺口或重复补充 Case。多实例时请关闭覆盖率辅助生成，基础 Case 仍可正常生成。

容器查询 API 接入后，由可替换的实例发现实现核对运行实例数；超过一个实例时跳过覆盖增强，不影响基础生成。本期不实现该自动检查。

## JaCoCo 增强的实际流程

```text
选择 source_revision（空为 qa）→ 解析完整 commit 并固定源码 pin/scan
  → 基础 Generation 编译落盘 → 立即返回前端，并保存增强状态
  → 仅 READY、generate_and_verify、QA 且启用增强的版本进入采集
  → 原有后台执行入口检查实例、制品存在性、工具及 reset 条件（准备总预算 10 秒）
  → reset → 原有自动验证执行 → dump → 下载／解析固定版本制品，形成可分析基线
  → 去重并选取最多 30 项代码缺口 → AI 补充／忽略／标明未解决
  → 对忽略项独立复核 → 生成模型作最终决定
  → 以 continue 编译落盘增强 Generation
  → 增强版为 READY：reset → 原有自动验证 → dump，作为最终复测
    增强版为 PARTIAL：保留原有验证和自动后继，跳过复测采集 → 结束
```

“最多一轮”指一次补充循环，不是限制整个过程只能调用模型一次。AI 说“已解决”不能作为覆盖证据，须看复测结果；仍未覆盖的项保留为未解决。增强完成也不等于业务场景已经全部覆盖。

基线复用现有 generate_and_verify；每个不可变 Generation，本增强流程最多调度一次完整 Variant 集合验证。发布重试按增强记录保存的 baseline_case_execution_id／verification_case_execution_id 读取原执行，即使后来关闭增强开关也保留绑定；不取最近一次手动或其他环境执行，也不重新派发。数据函数草稿试跑、取数／造数、诊断及回查仍允许，安排在基线 dump 之后、复测 reset 之前等测量窗口之外。完整验证内部的数据准备和断言正常执行。

只有预先绑定到增强任务的那一次自动验证会采集；手动执行不会触发 reset、dump 或重新增强。锁被占用时立即跳过采集，原有验证照常进行；并发生成时，重叠轮次可能因此跳过。制品下载、解包和匹配分析放在 dump 后，不占用前置 10 秒预算；执行前按固定源码 commit 选定具体构建制品引用，不能事后取“最新包”。该选择不代替与运行数据的 class ID 核对。

PARTIAL 基础版登记时直接记 SKIPPED，保留原有验证和自动后继，不做覆盖采集；派发补充模型前再检查是否已有其他后继。generate_only 不 reset、不执行。实例发现等准备超时、依赖不足或采集失败时，原有验证照常进行；采集错误不得改写真实业务执行结果。

增强版若发布为 PARTIAL，保留增强版本引用，覆盖流程以 PARTIAL 结束，不 reset 或自动重跑；窗口失效也不自动重放业务。手动重跑只执行业务，本期不新增独立的覆盖重测入口。

恢复使用独立的增强 TaskRecord，绑定真正派发业务执行的服务进程；不借用原生成任务，也不增加 Case 执行字段。服务启动及现有维护回调触发检查：确认原进程退出后，仅把本轮绑定且仍为 RUNNING 的执行记为 FAILED，保留已有结果并注明远端业务结果可能未知。基线中断则结束增强、不补充；复测中断则保留增强版，以 PARTIAL 结束。心跳超时或 TaskRecord 标为 INTERRUPTED 本身不足以证明进程退出，不能据此释放执行占用或重跑。已持久化的有效测量可继续分析，模型阶段只接续原运行，不重开第二轮。

增强后继创建后会占用基础版唯一的“继续”位置。页面此时显示增强进度，并提示等待增强版发布后从增强版继续；中断或失败时转到已有后继任务恢复，不创建第二个后继，本期不新增取消增强入口。

reset 会清掉同一个 agent 的累计数据，可能影响精准测试等其他使用方。第一版要求先确认不存在冲突，或已协调允许清零，再配置 `jacoco_reset_allowed=true`；默认 false 时跳过覆盖增强。不 reset 的两次 dump 差异只代表新命中的探针，例如某探针前后均为 true，无法判断本次是否再次执行，不能替代本轮覆盖率；本期不实现该替代模式。[JaCoCo 探针与 reset 语义](https://www.jacoco.org/jacoco/trunk/doc/api/org/jacoco/core/data/ExecutionData.html)

缺口去重规则：整个方法未执行只报一项 METHOD；已执行方法先报遗漏分支行 BRANCH_LINE，再合并其余连续未覆盖行为 LINE_BLOCK。按已证明的入口关联和调用距离排序，每轮最多 30 项；超限记录未处理数量，不能当作已忽略。30 是待真实样本评估的初始预算。

现有调用图无法可靠包含所有状态机、Actor 或线程池分派。本期只分析已证明的入口范围，并标明范围不完整；不能承诺自动补齐退款 cancel 的所有隐式流程。覆盖缺口、漏答和忽略争议不形成业务断言失败。

例如 `coverage_assistance.enabled=false` 时，仅跳过覆盖增强，generate_and_verify 仍执行原有验证；设为 true 后，还须满足 READY、QA、允许 reset 及依赖可用等条件，才追加采集和补充流程。generate_only 始终不执行。各模块只检查自身依赖；天网适配器缺 key 时记录跳过原因，其他发现方式不受天网配置影响。

## 什么叫“复核”

以本期代码缺口为例：生成模型先提出忽略理由，独立模型取得**原始源码、调用上下文和该理由**后判断，返回“认可／拒绝／证据不足”及原因；生成模型再结合意见确认最终处理。两份意见和最终理由都保留，独立模型拒绝不会无限阻断生成。

以下只展示复核相关字段，采用英文属性和中文注释；实际 JSON 传输时去掉注释：

```jsonc
{
  "gap_id": "gap-001", // 程序选中的代码缺口编号
  "kind": "METHOD", // 该方法在采集实例的窗口内未执行
  // 生成模型首次提出的处理意见
  "proposal": {
    "gap_id": "gap-001", "action": "IGNORE",
    "reason": "属于框架回调，没有业务调用方",
    "case_variant_ids": [], "final": false
  },
  // 独立模型根据源码、调用上下文和忽略理由复核
  "review": {
    "gap_id": "gap-001",
    "verdict": "REJECT", // ACCEPT：认可；REJECT：拒绝；INSUFFICIENT_EVIDENCE：证据不足
    "reason": "调用上下文显示入口可达该方法，不能仅因它是回调就忽略"
  },
  // 生成模型作最终决定，并说明是否采纳复核意见
  "decision": {
    "gap_id": "gap-001", "action": "ADD_CASE",
    "reason": "采纳复核意见，补充触发该路径的变体",
    "case_variant_ids": ["case-variant-v4-0123456789abcdef0123"], // 示意；须在最终编译版本中存在
    "final": true
  },
  "verification": "NOT_MEASURED" // 程序更新；已有复测但无法归因时为 INCONCLUSIVE
}
```

生成模型也可以坚持忽略，但要记录理由；补充项由程序执行并更新结果，忽略不等于验证通过。代码缺口只对本轮选中的有界清单要求处置，漏答记未解决。

## 天网怎么取 IP

每个系统的配置页面新增两个选填项：**天网 appId**（skyeye_app_id，字符串）和 **天网 api-token**（skyeye_api_token）。使用天网实例发现时需要两项都已配置；日志地址、时间窗及分页参数由适配器提供。

两项配置保存在同一系统级本机文件 `.opentest/environments/{system_id}/system.yaml`，各系统独立、QA/UAT 共用，不按环境重复填写。本期覆盖增强仍只支持 QA。

页面同时提供覆盖辅助开关和报告保留粒度。天网设置走独立的本机 API，GET 仅返回 appId 和 token_configured；PUT 省略 Token 表示保留，空串表示清除。页面空密码框保留旧值，只有勾选清除才清除；错误与日志均不回显凭据。

适配器将当前系统配置的字符串组成 `appIds=[skyeye_app_id]`。退款系统的 appId 配置值为 `3265415`；其他系统填写各自的天网 appId，该值不写入通用程序逻辑。查询成功后须核对返回记录属于目标应用。

适配器向日志查询地址发送 **POST JSON**。按参考接口协议，页面填写的 api-token 放入请求头 `token`；页面名称与 HTTP 请求头名称分别定义。QA 地址 `http://skynetapi.dss.qa.17usoft.com/log/real/list` 作为平台级默认值；应用标识读取当前系统配置，日志环境由 QA 的平台映射转换，必要时使用日志环境的 YAML 覆盖值。

下面展示程序组装后的请求结构，并非页面输入项。当前不依赖服务排序，使用 `pageSize=500` 有界读取窗口后选择最新有效记录：

```json
{
  "appIds": ["<当前系统配置的skyeye_app_id>"],
  "env": "<由当前执行环境转换的日志环境值>",
  "beginTime": "2026-10-19 10:00:00.000",
  "endTime": "2026-10-19 10:10:00.000",
  "pageSize": 500,
  "operationType": "next",
  "lastRowTime": 0,
  "lastRowData": ""
}
```

从 `result.list[].ip` 取候选，同时核对应用、环境、IP、appUk 及最近 10 分钟内的日志时间。上海时区请求带毫秒，按 timestamp/id 游标最多读 5 页；窗口未读完或游标异常就跳过，不用第一页冒充最新。真实 QA 已验证认证、候选发现和采集；跨页及恰好时间边界使用受控测试，未在平台实造这些日志。发现函数返回候选，之后受许可和准备预算限制的 JaCoCo reset 验证协议连通性；历史日志不保证实例仍存活。

未填写 api-token 或 skyeye_app_id 时，记录增强不可用原因，基础 Case 及原有验证继续。应用标识只从当前系统配置读取，不从 token、system_id 或 DSF 名称猜测。

协议参考来自 `travelsystem.java.dsf.supplychain.distribute_order` 的 `ProcessVisualBuilder#querySkyeyeInfo`；OpenTest 的适配器已单独读取 IP 等字段，不修改该业务项目的 DTO。

## JaCoCo 怎么获取和使用

**工具：** 从 [JaCoCo 官方下载页](https://www.jacoco.org/jacoco/index.html) 获取发布包，解压后的 `lib/jacococli.jar` 是命令行工具。选择与实际部署 agent 兼容的版本，并将安装路径配置给采集程序。

工作台高级本机设置可编辑 jacoco_cli_path、jacoco_java_command（默认 java）和可选 coverage_review_model。独立复核使用独立上下文，模型未指定时沿用现有 Case 模型及 Codex 执行通道。

QA 的 coverage_connection 还需明确实际包来源。本地方式填写 deployed_artifact_path、source_archive_path、artifact_commit；FTP 方式填写固定 archive_version、归档位置和凭据环境变量引用，不自动寻找最新部署。准备阶段冻结具体包，dump 后再取包匹配。真实归档的 WAR 位于 `<appUk>/war/qa/<version>/<commit>/`，源码位于 `<appUk>/qa/<version>/<commit>/out.tar.gz`。

**服务端：** 示例部署配置包含 `output=tcpserver,address=0.0.0.0,port=6300`，因此示例连接 6300。采集端口必须与目标应用的实际配置一致。该模式可直接导出运行数据，结合部署字节码生成全量报告；已启用此模式的应用无需仅为全量报告修改构建命令。[Agent 配置说明](https://www.jacoco.org/jacoco/trunk/doc/agent.html)

以下步骤只适用于已确认允许 reset 的 agent；未确认时只能做不带 `--reset` 的只读 dump，所得是累计快照。将 CLI 路径替换为实际安装位置，并填写从日志发现的 IP：

```bash
JACOCO_CLI='/实际安装目录/lib/jacococli.jar'
JACOCO_IP='<从天网取得的当前容器IP>'
JACOCO_PORT=6300
COVERAGE_DIR="$(mktemp -d /tmp/opentest-coverage.XXXXXX)"
```

**第一步：导出旧数据并 reset。** `--reset` 请求服务端在导出执行数据后清零；`before-reset.exec` 不计入本轮报告。只有该步骤成功，才进入本轮测量。

```bash
java -jar "$JACOCO_CLI" dump \
  --address "$JACOCO_IP" --port "$JACOCO_PORT" \
  --destfile "$COVERAGE_DIR/before-reset.exec" --reset --retry 0
```

**第二步：此时执行 Case，等待业务完成，再采集。** 不能跳过执行而直接运行下一条。

```bash
java -jar "$JACOCO_CLI" dump \
  --address "$JACOCO_IP" --port "$JACOCO_PORT" \
  --destfile "$COVERAGE_DIR/after-cases.exec" --retry 0
```

**第三步：生成 XML 和 HTML 报告。** 将下面两个示例目录替换为真实路径；XML 给 OpenTest 分析，HTML 供人工查看。reset、dump、report 均为 [JaCoCo CLI 原生能力](https://www.jacoco.org/jacoco/trunk/doc/cli.html)。

```bash
java -jar "$JACOCO_CLI" report "$COVERAGE_DIR/after-cases.exec" \
  --classfiles '/实际QA部署产物中的业务类目录或JAR' \
  --sourcefiles '/与该部署版本对应的源码目录' \
  --xml "$COVERAGE_DIR/coverage.xml" \
  --html "$COVERAGE_DIR/html"
```

业务类在多个目录或 JAR 时重复指定 `--classfiles`；报告分母应包含分析范围内的全部类，包括未执行的类。WAR 应用还需纳入 `WEB-INF/lib` 中相关业务 JAR。字节码必须与实际运行版本匹配，否则可能出现错误的零覆盖；插桩的 includes/excludes 范围也需纳入解释。[字节码匹配说明](https://www.jacoco.org/jacoco/trunk/doc/classids.html)

本期以人工确认 QA 单实例为使用前提；天网返回一个 IP 不等于程序已验证只有一个实例，单实例也不隔离其他人的请求。因此 attribution 仍为 UNVERIFIED，已采集缺口的验证结论为 INCONCLUSIVE，verified_resolved_count 为 null（无法判定，不是零效果）。仍可比较实例快照计数、补充 Variant 的实际执行结果及模型成本，不声称覆盖增长由补充 Case 导致。

## 保存什么，详细设计在哪里

- **小结果：** 每轮状态、两段覆盖计数、有界缺口、proposal/review/decision 和模型引用保留历史；页面按当前 Generation 精确读取其增强。
- **大报告：** 每组保留最近一轮可用终态的 exec 与固定材料定位，原始 result 使用既有 gzip JSON；新可用包保存后才裁剪同工作台旧包。XML/HTML 临时生成，重建依赖仍可取得且匹配的字节码和源码。
- **分析依据：** 两次实例快照、缺口意见、最终编译 Variant 与精确绑定的真实执行、模型 token 和耗时可回查。不存在独立净增统计字段；未知值为 null，不能据此宣称因果收益。
- **读取边界：** 固定材料包含本机路径或 FTP 定位与凭据环境变量名称，随 gzip 保存，但不含真实凭据；只有采集工作台后端可读取。页面／模型只拿不含原始 exec 和私有定位的工作流投影。
- **存储：** 已复用现有 MySQL 的 workflow/task/execution，类型模型及存取已实现，不新增物理表、列、索引或 Generation 可变状态。

详细文档：

1. [覆盖率辅助 Case 生成设计](coverage-assisted-case-generation.md)：制品前提、最小接口、执行复用、缺口预算、恢复和保留策略。
2. [数据结构与存储设计](coverage-assisted-case-generation-data-design.md)：每个字段的注释、修改理由及现有表映射。

这两份详细文档覆盖本期 JaCoCo 增强及代码缺口复核。通用 MySQL／Redis 识别与校验不在本期交付范围，需单独开 change。
