# 覆盖率辅助 Case 生成设计

## 状态和准入

本次实施准入、实现、两次真实 QA 闭环及 OCR delegation 独立审查已完成，清理及严格校验已通过，随本 change 归档；证据见 tasks。采用生成时选择源码版本，不要求自动识别当前部署版本或部署升级映射；完成情况以 tasks 为准。

1. 本次选择 `7b962925db34b181f66e39a9262356585a8fcc03`，对应实际构建 WAR、完整业务 JAR、源码及 QA dump 已取得，300 条可比较业务类 class ID 匹配、不匹配为 0，28 条运行期生成类未比较。该样本已满足实施准入；每轮仍核对实际取得的构建制品，无 mismatch 不能证明未加载类或以后部署的版本身份，`classdumpdir` 或本地重编译不能替代实际构建制品。
2. 确认同一 JaCoCo agent 无冲突或已协调允许 reset。2026-10-19 用户已明确允许退款系统 QA agent reset，该系统本次许可已满足；其他系统及环境仍须各自确认。`jacoco_reset_allowed` 通用默认 false；未确认不得清零。已有导出文件不能恢复其他消费者尚未取得的累计数据。

覆盖辅助生成请求提供可选 source_revision（commit/tag），空值解析 qa 分支当时的最新提交。生成前将其解析为完整 commit，复用 GitSourceRepository 的源码 pin 及既有 source scan；发布重试、continue 和本轮增强继承固定基线，不重新解析移动后的 qa 或 tag。此默认值只适用于覆盖辅助任务，非增强的历史生成保持既有版本行为。

手选或默认版本不保证 QA 正在运行该版本。按固定 commit 选定实际构建制品及配套源码，缺失、无可比较业务交集、class ID 不匹配或固定文件身份变化时跳过增强而保留基础生成与原验证；不预建多提供者框架。本机包输入为 `deployed_artifact_path`、`source_archive_path`、`artifact_commit`，须齐全并匹配固定 commit；FTP 输入固定 archive_version，凭据只能用环境变量引用。不得以本地重编译包替代实际构建包。

已发现的归档候选来源是 `ftp://scmpf.corp.elong.com/flight/accurate/`，不在文档或共享配置保存其凭据。只读核对的构建脚本使用以下目录：

```text
WAR/JAR: <appUK>/war/<envType>/<normalizedVersion>/<GIT_COMMIT>/
源码包:  <appUK>/<envType>/<normalizedVersion>/<GIT_COMMIT>/out.tar.gz
```

`normalizedVersion` 来自构建变量 Version：点替换为连字符，符合脚本 qa/uat 版本模式时归一为 qa/uat。退款 appUK 为 `iflightchainsaas.java.dsf.refund.core`，仅为样本配置，不写死在通用程序。脚本允许同路径重新上传，因此 commit 与归档路径只用于选包，不能单独证明字节码相同；分析实际取得的制品时仍核对 class ID，不改取不属于固定 commit 的最新归档。

本次归档版本为 `-8`；天网配置 appId=3265415 查询和 `10.175.78.54:6300` 的只读 dump 已成功，完整业务 JAR 的累计报告已生成。IP、appId、commit 和归档版本均为样本事实，不写死在通用程序；实例累计覆盖不等于本次 Case 的覆盖或归因证明。

## 范围与配置

仅 READY、generate_and_verify、QA 且启用增强的基础 Generation 尝试采集；PARTIAL 基础版直接 SKIPPED，原验证和自动后继不变。generate_only 不执行、不 reset；关闭增强不取消原验证或既有绑定的恢复。

使用者人工保证整轮仅一个承接请求的服务容器/JVM。页面提示多实例风险，本期不新增确认字段、入口命中门槛、副本检测、定向路由或流量隔离。报告 attribution 固定 UNVERIFIED，已测缺口 verification 为 INCONCLUSIVE，verified_resolved_count 恒为 null。

配置沿用数据定稿的严格模型：

- `SystemDefinition.coverage_assistance` 保存共享 enabled（默认 false）、instance_discovery（LATEST_SKYEYE_LOG）和 report_retention_scope（SYSTEM_ENVIRONMENT 或 OPERATION，默认前者）；系统页面可编辑开关和粒度，普通系统更新省略时保留已有值。
- 系统级本机 `system.yaml` 保存选填 skyeye_app_id 和 skyeye_api_token；系统页面增加这两个天网输入项，各系统独立保存、QA/UAT 共用。凭据复用保护及环境变量解析，不进入共享载荷、日志或模型。查询 appIds 使用该系统 appId 的单元素字符串数组，不再新增环境级 appId 覆盖或源码解析兜底。
- QA YAML 的 coverage_connection 保存实际端口（默认 6300）、reset 使用条件、本地实际包／源码／commit 或固定 FTP 归档参数、版本说明及日志环境覆盖值；只有选择增强才解析，错误不影响普通 DSF 执行。缺 appId 或 token 只跳过增强，基础生成与原验证继续。
- 工作台 settings 及高级本机设置页面保存 jacoco_cli_path、jacoco_java_command（默认 java）和可选 coverage_review_model；审查复用现有 Codex 通道及独立上下文，不新增模型路由。

系统私有 GET/PUT `/api/v2/systems/{system_id}/skyeye-settings` 只允许回环访问，响应只有 skyeye_app_id 和 token_configured。Token 省略保留，显式空串清除；页面空密码框不清空旧值。凭据不出现在错误、日志、共享策略和模型中。

InstanceDiscovery 是本期唯一需要可替换的接口。天网适配器向 QA 平台端点发送带 `token` Header 的 POST JSON，以上海时区最近 10 分钟毫秒时间窗查询。pageSize=500、最多 5 页，不假设服务倒序；完整读完窗口后，按日志时间从 appId/env、IP、appUk 和时效均合格的记录选最新候选。分页未完整、游标异常或预算不足就跳过，不能用局部第一页称为最新。真实 QA 已验证认证、当前窗口候选发现和后续采集；跨页及时间边界由受控测试验证，未在平台制造完整多页或恰好边界日志。

返回实例只含 ip、port、app_uk、log_record_id、log_time；发现本身不探测 JaCoCo，后续受许可和预算限制的 reset 验证协议连通性。替换发现实现不修改生成流程，只有所选实现检查自身依赖。容器 API 接入时须确认唯一可用实例，多个实例返回不支持；本期不实现该适配器。

## 自动执行与测量

基础发布、增强意图和所需任务在短事务中提交。自动 Execution、专属增强 TaskRecord、实际派发进程 owner 及精确执行引用在同一短事务中登记；最外层提交后由同一 TaskManager 的原线程池派发。网络、reset、模型调用不在事务内。

只有 `_finish_execution` 的 execution_id 精确匹配 baseline_case_execution_id 或 verification_case_execution_id，且系统、Generation、环境、阶段一致时采集。每个不可变 Generation 在本增强中至多完整执行一次。手动、历史及未绑定执行不采集，也不补认成基线。

发布重试先读取已有增强关联：本版本有非空绑定时精确读取，不受当前 enabled 影响，不改 owner、不重新派发；非空 ID 指向记录缺失或身份不符时报关联错误，不退回最新执行。直接 SKIPPED、PARTIAL 增强版等合法空绑定继续原有路径；无增强绑定的原发布重试问题不在本 change 范围。

同系统 QA 使用现有 MySQL 命名锁，等待为 0；锁忙立即跳过采集、照常验证，不排队补测。准备共享 10 秒初始总预算，包含锁调用、发现、工具与端口检查、固定 commit 对应的具体构建制品引用确认和 reset。源码解析与 pin/scan 在生成前完成，不占采集准备预算。HTTP 查询与 FTP 引用确认在可终止的只读子进程内执行；父进程的绝对截止覆盖 DNS、连接和慢速响应，超时先终止并回收进程，不遗留后台 reset。reset 仍使用独立的 JaCoCo 有界调用，未知结果不盲目重试。

顺序为 reset → 原有业务执行及断言 → dump → 释放测量锁 → 下载固定 commit 所选的实际构建制品、匹配、临时生成并解析报告。下载不占准备预算，不能事后取最新包；commit/tag 或默认 qa 不代替运行数据的 class ID 核对。采集、制品或解析失败只结束增强，不改真实 Case 结果、不重放业务。基线与复测分别保存窗口和有效性；不提供无 reset 的差分替代。

## 专属任务同步与退出恢复

`CoverageEnhancement.task_id` 指向 operation=coverage-enhancement 的专属 TaskRecord，复用其 owner_workspace_id、owner_pid、owner_started_at、owner_instance_id；不是模型生成任务，也不是 MCP 客户端或模型进程。该任务覆盖实际业务执行，即使增强已因锁忙记 SKIPPED，绑定 Case 未结束时不能提前完成任务。模型身份单独保存在 model_runs。

**执行完成同步放在 `_finish_execution` 的 `finally`。** 正常 return、可捕获异常、准备/采集失败及锁忙均经过同一同步边界，依据持久执行结果与增强阶段更新专属任务。Case 结果不被覆盖错误替换；仍有分析、补充或复测步骤时，仅同步阶段与进度，不把增强工作流或总协调任务提前终态。异常不能被同步逻辑掩盖。若元数据不可用，记录同步失败并保留恢复依据，不宣称终态已落盘，也不重执行业务。

已开启窗口的有界 dump 尝试与释放同样纳入清理边界，使用嵌套 finally 保证 dump 失败仍释放测量锁及连接；清理异常只保留诊断，不覆盖原业务异常或已保存结果。未成功 reset 或窗口已失效时不能构造有效测量。测量命名锁用独立连接、等待 0，不原样套用现有等待 10 秒且绑定写事务的任务创建锁。制品下载和报告解析始终在释放后执行。

线程池提交失败发生在 `_finish_execution` 进入前，由派发边界处理：元数据可写时将确定未启动的绑定执行和任务按实际状态收尾；保留原 ID，不借发布重试补跑。进程 kill 无法保证 finally 执行，由持久恢复处理。

真实 HTTP lifespan 组装完成后触发一次恢复，并注册现有 maintenance callback；回调仅向原线程池投递一项有界恢复作业，以进程内 Future 去重。数据库查询、ps 和短事务不在心跳线程；普通 GET 保持只读，发布重试可检查自己的绑定。

只查询本工作台未完成增强，以及增强已终态但绑定 Case 仍 RUNNING 的记录。INTERRUPTED 或 `_owner_is_alive=false` 只是线索。只有 PID 明确不存在，或原、新可靠非空启动标识不同，才能判定原进程退出；心跳过期、字段缺失、权限和读取失败保留 EXECUTION_OWNER_UNCONFIRMED，不改 Case、不转 owner、不重派。活进程线程卡死不自动修复。

确认退出后，在短事务内重读 owner、revision、关联及精确执行，仅将仍 RUNNING 的绑定 Case 改 FAILED，保留已有结果和请求回执，说明远端完成结果可能未知。缺失有效窗口的基线以 FAILED / EXECUTION_INTERRUPTED 结束，复测以 PARTIAL 结束并保留增强版；早已 SKIPPED 等终态保留原状态及原因。测量、工作流与任务同步提交，已终态业务结果不覆盖。完整业务终态和有效 dump 均已持久化时可续做只读分析；模型只读原结果或附着原 turn，未知派发找不到时不新开一轮。

复测若换进程，仅当前一绑定已终态且阶段已持久交接后更新 owner。恢复不新增调度器、持久队列或 Case owner 字段，不修改 DataCapabilityService._recover_execution，也不接管普通手动/历史执行。

## 有界分析和单轮补充

仅使用已有 RESOLVED、confidence ≥ 0.9 且目标在 Manifest 内的入口闭包，保留未解析出边的范围限制。没有额外完整性证据时 scope_status=PARTIAL，不承诺全部 Actor、状态机或线程池范围。

整方法未执行只报 METHOD；已执行方法先选遗漏分支行 BRANCH_LINE，再将其余连续未覆盖可执行行合为 LINE_BLOCK，同一目标不重复。按入口关联、已解析距离、类型及源码位置稳定排序，至多 30 项；保存 candidate_gap_count/deferred_gap_count，不为截断项伪造结论。缺口、漏答及忽略争议不生成 OBSERVATION_FAILED，也不阻断基础发布。

模型输入复用固定源码、基础 Case、数据函数、真实阶段结果及缺口。仅全体 Variant 有明确 TARGET 前失败证据时跳过补充；全部 FAILED、零成功或缺少记录不够。聚合 exec 不能归给单个失败 Variant。

补充任务的模型首段明确逐缺口目标及清单，覆盖上下文前置于大型 handoff/Schema；修正原断言不替代缺口答复。处置仅接纳当前未发布草稿修订，核对与保存使用同一 handoff 保护范围；旧草稿回执、并发晚到和发布后的提交不得回退最终裁决或重新审查。

派发前复查已有后继，沿用父锁及唯一后继约束；其他后继存在则 SKIPPED，round_used 不增加。正式派发前将 round_used 置 1，模型填写 ADD_CASE/IGNORE/UNRESOLVED、理由和最终有效 case_variant_ids。独立上下文审查忽略，返回 ACCEPT/REJECT/INSUFFICIENT_EVIDENCE；不可用单列 UNAVAILABLE。生成模型最终裁决，保留双方理由，不强阻断。增强版以 continue 继承固定源码，READY 才采集 verification；PARTIAL 保留原验证及自动后继，不递归增强。

本轮补充的数据草稿试跑、取数/造数、修正和回查安排在自身两个窗口之间，不禁止其他业务调用；执行内部的数据准备和断言仍可能进入快照。

## 持久化、界面和验证

复用 ot_workflow_record 的 coverage_enhancement 聚合、专属 task，以及 ot_execution 的 coverage 记录；不新增物理表/列/索引。增强进度用 revision 和 owner 保护；Case Generation 不增加可变状态字段，coverage_id/program_analysis 不作新报告身份。

CoverageEnhancement 实际状态为 RUNNING/COMPLETED/PARTIAL/FAILED/SKIPPED；阶段为 REGISTERED、BASELINE_EXECUTING、BASELINE_ANALYZING、SUPPLEMENT_PENDING、SUPPLEMENT_RUNNING、VERIFICATION_EXECUTING、VERIFICATION_ANALYZING、FINISHED。保存精确引用、两段 CoverageMeasurement、最多 30 项带 proposal/review/decision 的缺口及 SUPPLEMENT/REVIEW 模型引用；无独立 statistics、completed_at、report_execution_id 或净增收益字段。Variant 真实结果沿用精确关联的 Case 执行。

CoverageReport.execution_id 直接使用 enhancement_id，generation_id 使用基础版本；result 按 baseline/verification 保存 Base64 exec 和 FrozenCoverageArtifact。固定材料含本机包及源码路径或 FTP 固定路径、原生文件元数据、凭据环境变量名称，不含实际凭据；这些定位随既有 gzip JSON 持久化。原始读取先核对 owner 再解压，仅原工作台后端可恢复和重建；前端和模型只消费不含原始 exec、固定定位及凭据引用的工作流 projection。不能宣称共享库完全不存本机路径。

XML/HTML 仅临时使用。按 SYSTEM_ENVIRONMENT 或 OPERATION 分组保留最近一轮可用报告；新可用终态持久化后，短事务锁定同 owner、同组终态，按创建顺序确定最新有效且原始包非空的保留项。较旧窗口晚完成时也裁剪自身，失效或空的新报告不能挤掉上一份可用材料；不清理活动恢复材料、工作流或业务回执。未知计数和模型成本保持 null；快照变化不当作新 Case 的净增证明。

前端在覆盖辅助生成入口提供可选 commit/tag 输入 source_revision，提示“留空使用 qa 分支最新提交”，并从增强投影分别展示基础生成、业务验证及增强状态，提示人工单实例限制。唯一后继被增强占用时展示/恢复已有任务，不新增取消、后继槽位或重测入口。HTML 按需生成依赖核对过的构建字节码及固定源码仍可取得。前端行为修改须同步资源版本并通过真实 HTTP 页面验证。

验收覆盖准入、异常/中断矩阵、精确重试、锁忙、最终同步、非阻断、缺口去重/限制、后继并发、报告保留和成本记录。具体证据见 tasks：已完成真实子进程终止并回收后的 MySQL 恢复、两次 QA 自动闭环、HTTP 页面及报告下载；写入失败使用故障注入。第二次 2 个 Variant 均通过，接口范围行快照 3/16 → 13/16，3 项漏答仍 UNRESOLVED。真实 QA 未出现 IGNORE，独立忽略复核以自动测试验收。独立代码审查已完成；最终校验、清理及归档状态见 tasks。完整字段以[数据契约](../../../../docs/discussions/coverage-assisted-case-generation-data-design.md)及对应严格模型为准。
