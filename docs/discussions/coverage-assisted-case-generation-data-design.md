# 代码覆盖率辅助生成的数据结构与存储契约

2026-10-19。以下对齐本期已落地的严格模型与存储实现，不把此前讨论过的候选字段视为已实现。实现、两次真实 QA 闭环及 OCR delegation 独立审查已完成；最终交付状态以 [OpenSpec tasks](../../openspec/changes/archive/2026-10-19-add-coverage-assisted-case-generation/tasks.md) 为准。

本期只做 JaCoCo 反馈驱动的一轮代码缺口补充。MySQL／Redis 操作识别、业务状态穷尽和参数组合穷尽另开 change。基础 Case、业务断言结果和增强结果分别保存，增强不可用不阻断基础生成及原验证。

## 1. 现有存储如何复用

| 位置 | 本期内容 | 边界 |
| --- | --- | --- |
| `ot_system.system_json` | `SystemDefinition.coverage_assistance` | 共享开关、发现实现、原始报告保留粒度；旧系统为空即关闭 |
| 本机 `.opentest/environments/{system_id}/system.yaml` | `skyeye_app_id`、`skyeye_api_token` | 每系统独立，QA/UAT 共用；Token 不进入共享库 |
| 本机 `qa.yaml` | `coverage_connection` | 仅选择增强时按需读取，普通 DSF 执行不解析这部分 |
| 工作台 `.opentest/settings.yaml` | JaCoCo 工具及忽略审查模型 | 本机高级设置页面可编辑 |
| `ot_workflow_record` | `record_kind=coverage_enhancement`；另复用 `task` | 小型进度、精确关联、至多 30 项缺口和模型引用；使用已有 owner 与 revision 列 |
| `ot_execution` | `execution_kind=coverage` | `summary_json` 排除 `result`；完整 `CoverageReport` 存入既有 gzip JSON |
| `ot_case_generation` | 既有基础版与 continue 后继 | 不增加 Generation 可变状态；`coverage_id`、历史 `program_analysis` 不复用为 JaCoCo 身份 |

不新增物理表、列或索引。不建立另一份本地业务状态真相。时间保存 UTC，只有天网请求按上海时区格式化。缺失计数或成本保留 null，不补零。

## 2. 源码选择及配置

生成请求的 `source_revision` 可填写短／完整 commit 或 tag。覆盖策略启用且选择 `generate_and_verify` 时，留空使用当时的 `qa` 分支；开始生成前解析完整 commit，复用已有源码 pin、source_scopes 和 source_scan_id。发布重试、continue 和本轮增强继承固定基线，不能随分支或 tag 移动。非增强路径未指定版本时保持原行为，显式指定 ref 始终按其解析。

手选版本不证明 QA 正运行该版本。实际制品及源码缺失、无可比较业务类交集或 class ID 不匹配，只结束增强，不改基础 Case 及真实业务结果。

### 共享策略 `CoverageAssistancePolicy`

| 字段 | 类型／默认 | 用途 |
| --- | --- | --- |
| `enabled` | bool，false | 系统页面开关；仍须满足 READY、QA、reset 许可和依赖就绪 |
| `instance_discovery` | `LATEST_SKYEYE_LOG` | 唯一已实现的发现方式；替换边界是 InstanceDiscovery |
| `report_retention_scope` | `SYSTEM_ENVIRONMENT` 或 `OPERATION`，默认前者 | 系统环境最近一份，或各接口最近一份；页面可选，不改变测量范围 |

### 系统级天网设置

私有模型为 `LocalSystemSkyeyeSettings(system_id, skyeye_app_id, skyeye_api_token)`，不是对旧 `LocalSystemSettings` 增加环境级凭据。两个值均为字符串，可空。appId 只从系统配置读取，按 `appIds=[skyeye_app_id]` 传出，不从源码、DSF 名称或 Token 猜测。

`GET/PUT /api/v2/systems/{system_id}/skyeye-settings` 仅允许回环访问。响应白名单为 `skyeye_app_id` 和 `token_configured`；Token 不回显、不进入模型表示或普通序列化。PUT 省略字段保留，Token 空字符串明确清除。页面留空密码框表示保留，单独清除选项才发送空串。支持 `${ENV:NAME}`，读取时仅在私有内存解析；文件使用原子替换及 0600 权限。普通系统编辑省略 coverage_assistance 时保留既有策略。

### 环境级 `LocalCoverageConnection`

| 字段 | 类型／默认 | 用途 |
| --- | --- | --- |
| `jacoco_port` | int，6300 | 目标实际 JaCoCo TCP 端口 |
| `jacoco_reset_allowed` | bool，false | 已有目标环境清零许可；未许可记 `RESET_NOT_AUTHORIZED` |
| `deployed_artifact_path` | string，空 | 本机实际构建 WAR/JAR 路径，不是本地重新编译产物 |
| `source_archive_path` | string，空 | 该实际构建的配套源码归档 |
| `artifact_commit` | 完整 commit 或空 | 本地包与源码声明的版本，须等于生成固定 commit |
| `deployment_label` | string，空 | 人工核对版本说明，不作为匹配证明 |
| `skyeye_log_environment_override` | string，空 | 特殊日志环境名称覆盖，默认 QA 使用 qa |
| `archive_host`、`archive_port` | string／int，空／21 | 可选公司 FTP 归档连接 |
| `archive_root`、`archive_version` | string，空 | 归档根目录及本轮明确选定的构建版本目录 |
| `archive_username_ref`、`archive_password_ref` | string，空 | 只能由采集器消费环境变量引用，不把实际凭据写进报告 |

两种取包方式：本地实际包必须同时填写 `deployed_artifact_path`、`source_archive_path`、`artifact_commit`；FTP 必须指定固定 `archive_version` 和凭据环境引用，不自动找最新部署。真实构建脚本布局为：

```text
WAR:  <archive_root>/<appUk>/war/qa/<archive_version>/<完整commit>/*.war
源码: <archive_root>/<appUk>/qa/<archive_version>/<完整commit>/out.tar.gz
```

选择本地包时优先读取本地配置；FTP appUk 从已核对身份的日志取得。准备阶段固定具体文件及 stat 或 SIZE/MDTM，dump 后才复制／下载、解包并匹配。归档路径可被覆盖，因此仍须检查原生文件身份变化和 class ID；固定路径、用户版本说明均不替代字节码核对。

### 工作台工具设置

`RuntimeToolSettings` 和高级本机设置页面包含 `jacoco_cli_path`（CLI JAR 路径，默认空）、`jacoco_java_command`（默认 java）、`coverage_review_model`（默认空，沿用 Case 模型）。普通扫描器或模板更新省略这些字段时保留。模型通道沿用当前 Codex，不新增 provider 路由。

## 3. 增强聚合 `CoverageEnhancement`

| 实际字段 | 类型／默认 | 含义 |
| --- | --- | --- |
| `enhancement_id` | string | 工作流 record_id；也直接用作报告 execution_id，无第二份报告 ID |
| `task_id` | string，必需 | operation=coverage-enhancement 的专属协调 TaskRecord |
| `system_id`、`operation_id` | string | 系统与入口；映射既有查询列 |
| `base_generation_id` | string | 基础不可变版本 |
| `enhanced_generation_id`、`supplement_task_id` | string，空 | 已预留的唯一增强后继与模型任务 |
| `source_scan_id`、`source_commit` | string | 本轮固定扫描和完整 commit，引用既有源码身份 |
| `environment_id` | qa | 本期自动测量范围 |
| `status` | RUNNING / COMPLETED / PARTIAL / FAILED / SKIPPED | 增强生命周期，不是 Case 业务结果 |
| `stage` | 下表阶段 | 持久步骤位置，供有界恢复使用 |
| `revision` | int，0 起 | CAS 保存后加一，旧版本不得覆盖新进度 |
| `round_used` | 0 或 1 | 已预留本轮补充额度，恢复不得重新清零派发 |
| `baseline_case_execution_id`、`verification_case_execution_id` | string，空 | 精确绑定原有自动 Case 执行，不查“最近执行”替代 |
| `baseline`、`verification` | CoverageMeasurement | 两段窗口的采集状态与分析 |
| `reason_codes` | string[] | 多条脱敏分类原因，不另存自由格式错误堆栈 |
| `gaps` | ReviewedCoverageGap[]，最多 30 | 程序缺口、提议、复核和最终处置 |
| `model_runs` | CoverageModelRun[]，最多 2 | SUPPLEMENT 与 REVIEW 的已有运行引用和已知成本 |
| `attribution` | 固定 UNVERIFIED | 实例快照不能归因到本轮或单个 Variant |
| `verified_resolved_count` | 固定 null | 不能据累计探针确认因果解决数量 |
| `report_retention_scope` | SYSTEM_ENVIRONMENT / OPERATION | 本轮报告采用的保留粒度 |
| `created_at`、`updated_at` | datetime | 创建及最近更新 |

实际阶段为 `REGISTERED`、`BASELINE_EXECUTING`、`BASELINE_ANALYZING`、`SUPPLEMENT_PENDING`、`SUPPLEMENT_RUNNING`、`VERIFICATION_EXECUTING`、`VERIFICATION_ANALYZING`、`FINISHED`。没有独立 QUEUED／INTERRUPTED 生命周期，也没有 WAITING／DISCOVERING／REVIEWING 等持久阶段。

owner_workspace_id 使用既有数据库列；执行 PID、启动标识及实例身份保存在专属 TaskRecord，不重复加入增强 payload 或 Case 执行。不存在此前讨论稿里的 `statistics`、`report_execution_id`、`discovery_provider`、`completed_at` 等字段。结束时间可从专属任务读取；效果分析从已有窗口、缺口、模型和精确 Case 引用读取，不维护第二套统计真相。

### 两段测量 `CoverageMeasurement`

字段为 `case_execution_id`、`status`（PENDING / VALID / INVALID / SKIPPED）、`reason_codes`、`ip`、`reset_at`、`dump_at`、`analysis`。没有独立 reset_status／dump_status；未知或失败通过状态、缺失时间及原因码表达。

`analysis` 只在有效分析后保存 `CoverageAnalysisResult`：

- `raw_counts`、`scope_counts`：完整业务制品和已证明入口范围的 method／line／branch 计数，每项只有 covered、missed。
- `class_match`、`source_match`：仅成功分析才为 MATCHED；失败不伪造分析对象或零覆盖。
- `matched_class_count`、`uncomparable_class_count`：可比较匹配与无法比较数量。
- `scope_status`、`scope_reason`：COMPLETE／PARTIAL 及理由；仅 resolved 调用闭包不保证动态范围完整。
- `gaps`、`candidate_gap_count`、`deferred_gap_count`、`warnings`：有界缺口与未处理范围。
- `xml_path`、`html_path`：仅内存临时路径，序列化排除。

## 4. 缺口、审查及模型成本

`CodeCoverageGap` 的字段为 `gap_id`、`kind`（METHOD / LINE_BLOCK / BRANCH_LINE）、`location`、`scope_status`（IN_SCOPE / UNCERTAIN）、`scope_reason`、`source_refs`、`before`。location 保存源码相对位置、类、可空方法名／描述符和行范围；before 是该行动单元的 covered／missed 计数。

`ReviewedCoverageGap` 在上述基础上增加：

| 字段 | 实际结构 | 含义 |
| --- | --- | --- |
| `proposal` | CoverageDisposition 或 null | 生成模型最初建议 |
| `review` | CoverageReview 或 null | 独立上下文的忽略理由审查 |
| `decision` | CoverageDisposition 或 null | 生成模型复核后的最终处置 |
| `verification` | NOT_MEASURED / INCONCLUSIVE | 是否已有无法归因的复测信息；不写成“已证明解决” |

CoverageDisposition：`gap_id`、`action`（ADD_CASE / IGNORE / UNRESOLVED）、`reason`、`case_variant_ids`、`final`。关联 ID 必须在最终编译版本中有效。CoverageReview：`gap_id`、`verdict`（ACCEPT / REJECT / INSUFFICIENT_EVIDENCE / UNAVAILABLE）、`reason`。漏答或无效关联保留未解决；独立拒绝不强阻断，由生成模型最终裁决且保留意见分歧。

CoverageModelRun：`role`（SUPPLEMENT / REVIEW）、`run_id`、`task_id`、`status`、`provider`、`model`、`elapsed_seconds`、`input_tokens`、`output_tokens`。未知耗时／token 为 null；最终裁决属于原补充上下文，不额外创造 FINALIZATION 角色。完整对话仍留在既有模型运行，不复制进增强聚合。

没有独立的“净增收益”或“采纳率”持久统计表。人工可比较两次实例快照、逐项意见、编译后的新增 Variant 和其真实执行，以及已记录的模型成本；这些材料不证明因果覆盖提升。

## 5. 原始报告和私有固定材料

`CoverageReport` 只有 `execution_id`、`system_id`、`generation_id`、`operation_id`、`environment_id=qa`、`status`、`result`、`created_at`。execution_id 等于 enhancement_id，generation_id 使用基础版本。owner 属于既有执行表列，不另加报告字段。

`result` 按 baseline／verification 保存 `CoverageRawCapture`：

```text
CoverageRawCapture
  exec_base64: 原始 exec 编码
  artifact: FrozenCoverageArtifact
    selection: CoverageArtifactSelection
    commit: 固定完整 commit
    transport: LOCAL 或 FTP
    artifact / source: ArtifactFileIdentity
```

FrozenCoverageArtifact 是恢复或重建所需的固定定位。selection 包含本机实际包／源码路径或固定 FTP 主机、根目录、版本目录，以及**环境变量引用名称**；不包含解析后的用户名／密码、天网 Token。ArtifactFileIdentity 保存 path、size、modified，LOCAL 另有 device、inode；不新增内容哈希。实际凭据只在 owner 后端读取环境变量时进入私有内存。

这些定位随 result 存在既有 gzip JSON 中，因此不能宣称“共享数据库完全不保存本机路径”。准确边界是：原始报告仅采集工作台后端可读、恢复和裁剪；存储层先校验 owner，再解压。其他工作台只能读取不含原始 exec、固定制品定位和凭据引用的工作流 projection。前端／模型只消费该投影，不直接接收 CoverageReport.result。

完整 XML/HTML 不持久化。原采集工作台可按需使用仍可取得且通过身份／class ID 检查的材料生成临时 HTML ZIP；下载完成清理临时目录。材料已裁剪或不可取得时明确不可重建，历史缺口和摘要仍保留。

## 6. 保留与查询

SYSTEM_ENVIRONMENT 按系统＋QA，OPERATION 再加接口。有效终态原始包已保存后，短事务锁定同 owner、同组终态报告，按创建顺序确定最新有效且原始包非空的保留项，再裁剪更旧 result。完成顺序不改变保留顺序：较旧窗口晚完成时会裁剪自身，更新的失效或空报告不能挤掉之前的可用包。保留 summary、工作流、缺口、Case 结果与回执；活动材料、其他工作台及其他系统不清理。切换粒度不能恢复已裁剪的材料。

`get` 精确读增强；`for_generation` 仅匹配基础或增强 Generation，`for_execution` 仅匹配两段绑定执行。恢复 `candidates(limit=20)` 先投影当前工作台 RUNNING 或终态但明确绑定 Case 仍 RUNNING 的 ID，再读取必要聚合，不通过 list_workflows 全量载荷轮询。页面按当前 Generation 查小投影，不能拿系统最近任务冒充当前接口的增强。

## 7. 事务、同步与恢复硬边界

1. 自动 Execution、专属 TaskRecord 的真实服务进程 owner 及精确引用在短事务提交后，才交给原线程池派发。generate_only、手动及未绑定执行不采集。
2. 同系统 QA 的命名锁使用独立 autocommit 连接，GET_LOCK 等待零。忙时跳过采集；10 秒准备预算共用于锁、发现、选包和 reset。整个测量窗口不持有数据库写事务。
3. `_finish_execution` 的 finally 统一同步专属任务；已开启窗口的有界 dump 与锁释放使用嵌套 finally。覆盖错误不替换 Case 结果；增强仍有步骤或绑定 Case 仍运行时，不提前终结总任务。写库失败不能声称已收尾。
4. HTTP lifespan 与既有维护回调只向原线程池投递有界恢复作业，Future 去重；心跳线程不做数据库查询、ps 或耗时恢复，普通 GET 不触发恢复。
5. 仅 PID 明确不存在，或可靠非空启动标识不同，才证明原进程退出。心跳超时、INTERRUPTED、权限不足、字段缺失不能代替该证据；保留 EXECUTION_OWNER_UNCONFIRMED，不接管他机。
6. 确认退出后短事务重读 owner、revision、绑定，只收尾仍 RUNNING 的精确 Case，保留结果和回执，说明远端结果可能未知。基线缺有效窗口则 FAILED，复测缺窗口则 PARTIAL；既有 SKIPPED 等终态保留。绝不重放业务或重开测量。
7. 业务终态和有效 dump 均已保存时，可继续只读分析。模型接续原 turn／结果，未知派发不另开一轮；复测换进程前须完成前一执行和持久交接。不修改 DataCapabilityService 的恢复，也不接管普通手动／历史 Case。

模型与存储依据：[coverage_workflow.py](../../opentest/domain/coverage_workflow.py)、[coverage.py](../../opentest/domain/coverage.py)、[coverage_store.py](../../opentest/adapters/coverage_store.py)、[environment_config.py](../../opentest/adapters/environment_config.py)。
