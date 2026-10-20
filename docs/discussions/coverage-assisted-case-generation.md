# 覆盖率辅助 Case 生成设计

2026-10-19。实现、两次真实 QA 闭环及 OCR delegation 独立审查已完成。实施 change 为 `add-coverage-assisted-case-generation`，完成情况以其 [tasks](../../openspec/changes/archive/2026-10-19-add-coverage-assisted-case-generation/tasks.md) 为准。

本期先返回基础 Case，再以一次 JaCoCo 反馈补充方法、分支行和代码行缺口。不交付 MySQL／Redis 操作识别、业务状态穷尽或参数组合穷尽。现有数据函数、变体展开、100 个 Variant 上限和业务断言继续复用。

评审入口：[需求简版与操作示例](case-generation-requirements-review.md)。准确字段、类型及既有表映射见[数据结构与存储契约](coverage-assisted-case-generation-data-design.md)。

## 1. 源码、制品及适用条件

覆盖策略启用且选择 `generate_and_verify` 时，生成请求可填 `source_revision`（短／完整 commit 或 tag），留空使用当时的 `qa`。开始生成前解析完整 commit，复用已有 pin、source_scopes 和 source_scan_id；发布重试、continue 和增强继承该基线，不重新解析已移动的分支或 tag。非增强路径未指定版本时保持原行为，显式 ref 按用户选择处理。

源码选择不是运行版本证明。本期不自动识别部署版本；每轮按固定 commit 选取实际构建 WAR/JAR、完整业务类和配套源码，核对 dump 中可比较业务类的 class ID。无交集、缺制品、源码不对应、class ID 不匹配或固定文件身份变化，只结束增强，基础 Case 和原验证继续。本地重编译及仅含已加载类的 classdumpdir 不能替代完整实际构建制品。[JaCoCo 字节码匹配要求](https://www.jacoco.org/jacoco/trunk/doc/classids.html)

本次退款样本 `7b962925db34b181f66e39a9262356585a8fcc03` 已取得实际 WAR 和源码，300 条可比较业务类匹配、0 条不匹配，28 条运行期生成类未比较。用户已允许该系统 QA agent reset，满足实施准入。样本匹配不证明其他部署，也不代替自动闭环验收。

使用者人工保证整轮只有一个承接请求的服务容器／JVM。页面提示多实例风险，本期不增加副本检测、确认字段、定向路由、请求归属证明或流量隔离。单实例仍可能包含其他流量、数据准备和断言，因此 `attribution=UNVERIFIED`、已测缺口 `verification=INCONCLUSIVE`、`verified_resolved_count=null`。快照变化不能写成新 Case 的净增效果。

reset 会清除同一 agent 的累计探针，须先协调其他消费者；`jacoco_reset_allowed` 默认 false。不采用两次无 reset dump 的差集替代窗口：前后都为 true 的探针无法说明本轮是否执行。[JaCoCo 探针语义](https://www.jacoco.org/jacoco/trunk/doc/api/org/jacoco/core/data/ExecutionData.html)

## 2. 配置与替换边界

| 位置 | 已实现配置 | 作用 |
| --- | --- | --- |
| 系统共享策略 | `coverage_assistance.enabled`、`instance_discovery`、`report_retention_scope` | 默认关闭；当前发现方式 LATEST_SKYEYE_LOG；页面可选系统环境或接口保留粒度 |
| 每系统本机 `system.yaml` | `skyeye_app_id`、`skyeye_api_token` | 系统页面编辑，QA/UAT 共用且系统间隔离；不把 system 当环境 |
| 本机 `qa.yaml` | `coverage_connection` | 端口、reset 许可、日志环境覆盖、本地实际包或固定 FTP 归档引用；只有增强读取 |
| 工作台 `settings.yaml` | `jacoco_cli_path`、`jacoco_java_command`、`coverage_review_model` | 高级本机设置页面编辑；Java 默认 java，审查模型为空时沿用 Case 模型 |

私有系统设置使用 GET/PUT `/api/v2/systems/{system_id}/skyeye-settings`，仅回环访问，响应只有 appId 和 token_configured。省略 Token 保留，显式空串清除；页面空密码框不清除旧值。沿用原子写入、0600 和环境变量引用保护，错误、日志、共享策略及模型不含实际 Token。普通系统编辑省略 coverage_assistance 时保留原策略。跨环境复用配置不扩大本期 QA 测量范围。

`InstanceDiscovery` 是明确保留的替换接口，本期实现 `SkyeyeInstanceDiscovery`。采集、制品读取与协调使用普通模块，不预建通用插件体系。所选模块检查自身依赖，缺 appId、Token、工具或制品只跳过增强。容器 API 后续接入时应确认唯一可用实例，本期未实现该检查。

实际包支持两种明确输入：本地 `deployed_artifact_path`、`source_archive_path`、`artifact_commit` 必须齐全且 commit 匹配；FTP 则配置主机、根目录、固定 `archive_version` 及 `${ENV:NAME}` 凭据引用，appUk 来自身份已核对的日志。真实构建脚本布局为：

```text
WAR:  <archive_root>/<appUk>/war/qa/<archive_version>/<完整commit>/*.war
源码: <archive_root>/<appUk>/qa/<archive_version>/<完整commit>/out.tar.gz
```

准备时固定具体路径及 stat 或 SIZE/MDTM，dump 后才复制／下载、解包、核对。归档路径可被覆盖，commit 目录不能独自证明字节码相同。`deployment_label` 是人工说明，不是自动部署映射。

## 3. 天网取得候选 IP

适配器向平台 QA 默认地址 `http://skynetapi.dss.qa.17usoft.com/log/real/list` 发 POST JSON，以 `token` Header 认证。请求使用 `appIds=[skyeye_app_id]`、QA 日志环境、上海时区最近 10 分钟毫秒时间窗及 timestamp/id 游标。appId 只来自当前系统配置，不从源码、DSF 名称或 Token 猜测；不调用业务接口或注入 UUID。

实现使用 pageSize=500、最多 5 页，不假设结果倒序。读完窗口后，从身份、环境、有效 IP、appUk 和时间均合格的记录中选择最大日志时间。游标异常、重复、达到上限仍未读完或预算耗尽均返回不可用，不将局部第一页称为最新。真实 QA 已验证认证、当前窗口候选发现和采集；跨页及恰好时间边界使用受控测试，未在平台实造这些日志。

`DiscoveredCoverageInstance` 只含 ip、port、app_uk、log_record_id、log_time，不包含副本证明或额外持久状态。发现函数只返回候选；随后受许可和预算约束的 JaCoCo reset 验证实际协议连通性。日志不保证实例仍存活，DSF 当前也不支持本期所需的目标 IP 定向调用；失败不能通过重执行业务补救错过的窗口。

## 4. 原验证上的两个窗口

```text
固定源码 → 基础 Generation 落盘并返回，登记增强
  → READY、generate_and_verify、QA 且策略开启
  → 短事务登记自动 Execution、专属任务真实 owner、精确绑定
  → 最外层提交后交给原 TaskManager 线程池
  → 零等待取锁；10 秒共享预算内发现、选包、工具检查和许可 reset
  → reset → 原 Variant 数据准备、目标调用、断言 → dump → 释放锁
  → 下载固定材料、匹配、临时报告 → 有界基线缺口
  → 最多一轮补充、忽略独立复核、生成模型最终裁决
  → continue 发布增强版
  → READY：再测量增强集合一次，保存 verification
    PARTIAL：保留原验证及自动后继，覆盖流程 PARTIAL，不采集复测
```

基础 PARTIAL 直接 SKIPPED，不占额度；generate_only 不执行、不 reset。关闭策略不取消原验证或既有绑定恢复。只有 `_finish_execution` 的 execution_id 精确匹配基线／复测绑定，且系统、Generation、QA、阶段一致才采集；手动、历史和未绑定执行不能补认成基线。

每个不可变 Generation 最多完整执行一次。发布重试先读非空精确绑定，即使策略已关闭或插入手动/UAT 执行，也不改绑、不重派。非空 ID 缺失或错配时报错，不退回最近执行；直接 SKIPPED 等合法空引用继续原路径。

测量锁使用已有 MySQL 命名锁、独立 autocommit 连接、零等待，同库同系统互斥。忙时跳过采集，原验证继续，不排队补测。10 秒准备预算包括锁、发现分页、工具、固定制品引用和 reset，不包括生成前 pin/scan、dump 后取包分析。HTTP/FTP 准备使用可终止的只读子进程，绝对预算覆盖 DNS、建连和慢速响应；超时先终止并回收，不遗留迟到 reset。未知 reset 不重试；退款 QA 已完成真实准备与采集。

两阶段分别记录窗口状态、原因、IP、时间及分析。下载与解析在释放锁后进行，不在长写事务内持锁。采集失效不改 Case 结果、不重放业务。补充中的数据函数试跑、取数、修正和回查安排在自身两个窗口之间；执行内部数据准备和断言仍进入快照，其他流量未隔离。

## 5. 完成同步与退出恢复

独立 `operation=coverage-enhancement` TaskRecord 的已有 owner 字段记录真正派发业务的服务进程，模型身份另存 model_runs；不借用原生成任务或新增 Case owner 字段。

`_finish_execution` 的 finally 统一同步正常返回、可捕获异常、锁忙和采集失败。绑定 Case 仍 RUNNING 或尚有分析、补充、复测时不能提前完成总任务。覆盖错误不能替换业务结果或掩盖原异常；存储不可用不声称终态已保存。已开启窗口的有限时 dump 与锁连接释放采用嵌套 finally。

线程池提交拒绝由派发边界收尾确定未启动的精确记录，保留 ID，不借重试补跑。进程 kill 无法依赖 finally，由持久恢复处理。HTTP lifespan 启动一次恢复，既有 maintenance callback 只向原线程池投递有界作业，Future 去重；普通 GET 只读，心跳线程不做数据库、ps 或恢复事务。

恢复只查询当前工作台 RUNNING 增强，以及增强终态但精确绑定 Case 仍 RUNNING 的记录，先查 ID 再读必要 payload。仅 PID 明确不存在，或可靠非空启动标识已改变，才证明退出。心跳失活、INTERRUPTED、权限不足、字段缺失和探测失败只保存 `EXECUTION_OWNER_UNCONFIRMED`，不接管、不释放占用、不重派；活进程线程卡死不自动修复。

确认退出后，短事务重读 owner、revision、绑定及执行，只将仍 RUNNING 的精确 Case 改 FAILED，保留结果、回执和远端结果可能未知的说明。基线缺有效窗口则 FAILED，复测则 PARTIAL 并保留增强版；原 SKIPPED 等终态不改。业务终态和有效 dump 都已保存时只续分析；模型只接续原 turn／结果，未知派发找不到不新开一轮。

复测换进程必须前一绑定已终态且持久交接完成。不修改 `DataCapabilityService._recover_execution`，不接管普通手动／历史 Case，不新增调度器或持久队列。已通过真实子进程终止并回收后的 MySQL 精确恢复测试；心跳、启动标识及权限边界另由受控测试覆盖。

## 6. 有界缺口与单轮模型

范围沿已有 RESOLVED、confidence ≥ 0.9、目标在 Manifest 内的入口闭包，保留未解析出边。缺动态完整性证据时 scope_status=PARTIAL，不承诺全部 Actor、状态机或线程池路径。XML 分支计数不能独自指出真假业务条件。

整个方法未执行只报 METHOD；已执行方法先报 BRANCH_LINE，剩余未覆盖可执行连续行合并 LINE_BLOCK，避免重复。按入口距离、类型和位置稳定排序，最多 30 项，保存候选数和截断数。截断、漏答或忽略争议不能变成 OBSERVATION_FAILED 或发布门禁。

模型输入包含固定源码、调用上下文、基础 Case、数据函数、断言、基线和逐 Variant 阶段结果。仅所有 Variant 都明确在 TARGET 前失败时跳过；全部 FAILED、零成功或缺记录不够。聚合 exec 不能归到单个 Variant。

补充模型的首段提示明确逐缺口目标与清单，覆盖上下文优先展示，避免只修正已有 Case 的断言。缺口答复与当前未发布草稿修订绑定；旧请求重试、并发晚到或发布后请求只返回已有状态，不能回退最终裁决。

派发前复查已有后继，沿用父锁和唯一后继约束；其他后继存在则跳过且不占额度。正式派发前保存 round_used=1，恢复不清零。模型逐项填写 ADD_CASE／IGNORE／UNRESOLVED、理由和 case_variant_ids；程序核对最终编译版本中的 ID。

忽略项以独立上下文读取原始源码与调用证据，返回 ACCEPT／REJECT／INSUFFICIENT_EVIDENCE，不可用单列 UNAVAILABLE。生成模型在原上下文最终裁决，保留 proposal、review、decision；独立拒绝不强阻断。model_runs 只有 SUPPLEMENT／REVIEW，记录已知 provider/model、耗时和 token；最终裁决不增加第三种角色。

增强通过 continue 继承源码，READY 才测量 verification；PARTIAL 保留原验证和自动后继，不递归增强。未答和无效关联保留未解决；发布补充版不等于已经证明缺口解决。

## 7. 持久化、展示与验收

增强复用 `ot_workflow_record`，报告复用 `ot_execution` 的 coverage gzip 详情；enhancement_id 同时是报告 execution_id，不增物理表、列、索引或 Generation 可变状态。已有 owner/revision 保护更新。工作流保存状态、精确执行引用、两段分析、最多 30 项缺口及两类模型引用，没有独立 statistics 或净增收益字段；Variant 结果仍在原 Case 执行中。

报告 result 的 baseline／verification 保存 Base64 exec 和 `FrozenCoverageArtifact`。固定材料含本机包路径或 FTP 定位、凭据环境变量名称，不含实际用户名、密码或天网 Token。这些私有定位随 gzip 入库，不能声称共享库不含本机路径。原始读取先核对 owner 再解压；仅原工作台后端恢复或重建，前端／模型只消费不含原始包及定位的工作流 projection。

完整 XML/HTML 临时生成，不入库。原工作台在材料仍可取得且身份／class ID 合格时重建 HTML ZIP，响应完成清理临时目录。材料缺失或已裁剪则明确不可重建，摘要和缺口历史仍在。

报告按 SYSTEM_ENVIRONMENT 或 OPERATION 分组保留最近一轮可用终态；新包成功保存且有效后才裁剪同 owner、同组旧终态 result。不裁剪活动材料、其他工作台、工作流历史或 Case 回执；切换粒度不恢复已裁剪材料。

页面分别显示基础生成、业务验证及增强状态，提供 source_revision 和默认 qa 提示；已有增强后继时引导查看或恢复原任务，不新增取消或独立重测入口。浏览器行为修改同步资源版本和旧页面写保护，并须在运行中的 HTTP 页面验收。

验收包含两次真实 QA 自动闭环；第二次 2 个 Variant 均 PASSED，接口范围方法快照 1/3 → 3/3、行快照 3/16 → 13/16，仍无请求归因证明。3 项漏答保留 UNRESOLVED；本次没有 IGNORE，独立忽略复核以自动测试验收。Python 合并套件 284 项、JS 49 项通过；最后发布前填处置的提示澄清另跑受影响 26 项通过。OCR delegation 两轮已收敛，清理、严格校验及归档记录见 OpenSpec tasks。
