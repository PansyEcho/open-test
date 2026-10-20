## ADDED Requirements

### Requirement: 覆盖增强必须核对实际构建制品及 reset 条件

系统 SHALL 按本轮固定源码 commit 取得实际构建 WAR/JAR、完整业务类和对应源码，并与 JaCoCo dump 中可比较类的 class ID 核对；允许由生成请求选择源码版本，不要求自动识别当前部署版本或部署升级映射。reset 必须具有目标环境的明确许可。

#### Scenario: 所选源码与运行字节码缺少匹配依据
- **WHEN** 所选 commit/tag 或默认 qa 对应的实际构建制品缺失、源码不对应，或可比较 class ID 不匹配
- **THEN** 跳过覆盖增强，基础 Case 及原有验证继续；不能以手选版本、归档路径或未发现 mismatch 单独证明完整制品或 QA 运行版本一致

#### Scenario: reset 使用条件未确认
- **WHEN** 尚未确认其他消费者不存在冲突或已经协调允许清零
- **THEN** jacoco_reset_allowed 保持默认 false，跳过覆盖增强，基础生成与原有验证继续，不采用无 reset 的累计差分替代

#### Scenario: 选择固定的本地或归档制品
- **WHEN** QA coverage_connection 提供实际构建材料
- **THEN** 本地方式要求 deployed_artifact_path、source_archive_path、artifact_commit 齐全且 commit 匹配；FTP 方式使用明确 archive_version、归档位置及凭据环境变量引用，遵循实际 WAR 和 out.tar.gz 的分离目录，不寻找事后最新包
- **AND** 执行前固定原生文件身份或 SIZE/MDTM，dump 后取得材料并复查身份及 class ID；文件变化不能被路径或人工 deployment_label 替代证明

### Requirement: 覆盖辅助生成必须固定所选源码版本

系统 SHALL 在覆盖辅助生成请求中提供可选 source_revision，接受 commit/tag；空值使用 qa 分支当时的最新提交。开始生成前解析为完整 commit，并复用已有源码 pin、source_scopes 和 source_scan_id，不创建平行的版本状态。

#### Scenario: 明确选择 commit 或 tag
- **WHEN** 用户为覆盖辅助生成填写可解析的短/完整 commit 或 tag
- **THEN** 固定其解析出的完整 commit 并使用对应 pin/scan；本次示例 `7b962925` 对应 `7b962925db34b181f66e39a9262356585a8fcc03`，示例值不得硬编码进通用逻辑

#### Scenario: 覆盖辅助任务未填写版本
- **WHEN** 覆盖策略启用、选择 generate_and_verify 且 source_revision 为空
- **THEN** 在本次生成开始时解析 qa 分支最新提交并固定完整 commit；该默认值不改变非增强历史生成的既有版本行为

#### Scenario: 分支或 tag 在重试前移动
- **WHEN** 同一任务发布重试、continue 或执行覆盖补充时 qa 分支或原 tag 已指向新提交
- **THEN** 继承已固定 commit 和 pin/scan，不重新解析或替换基线；所选版本是否与 QA 字节码相符仍通过实际构建制品和 class ID 核对

### Requirement: 覆盖增强应为有明确边界的可选能力

系统 SHALL 仅对启用增强、READY、generate_and_verify、QA 的基础版本尝试测量；增强结果与业务验证结果分开，采集不可用不得阻断基础 Case。

#### Scenario: 基础版本不符合测量条件
- **WHEN** 增强关闭、依赖缺失、非 QA，或基础版为 PARTIAL
- **THEN** 记录跳过原因并保留原验证及自动后继；PARTIAL 不占补充额度；generate_only 不执行业务或 reset

#### Scenario: 单实例适用条件
- **WHEN** 用户启用覆盖增强
- **THEN** 页面提示其人工保证 QA 整轮只有一个承接请求的服务容器/JVM，以及多实例误报风险；本期不增加确认字段、副本检测或入口命中门槛

#### Scenario: 快照无法归因
- **WHEN** 展示实例覆盖计数或缺口复测结果
- **THEN** attribution 固定 UNVERIFIED，已测缺口为 INCONCLUSIVE，verified_resolved_count 为 null；不得宣称接口独占覆盖率、因果增益或全部业务场景已覆盖

### Requirement: 实例发现与配置应与生成流程解耦

系统 SHALL 通过可替换 InstanceDiscovery 接口及配置组装发现方式，仅由所选实现检查自身依赖；本期实现最新有效天网日志适配器。

#### Scenario: 查询天网候选实例
- **WHEN** 天网凭据和可靠 appId 可用
- **THEN** 适配器发送带 token Header 的 POST JSON，按上海时区使用最近 10 分钟毫秒时间窗，以 pageSize=500 和 timestamp/id 游标最多查询 5 页；完整读完窗口后从 appId、env、IP、appUk 和时效均合格的记录选择最新日志，不依赖第一页排序
- **AND** 分页不完整、游标异常或预算耗尽时跳过；发现仅返回候选，后续受许可和预算约束的 JaCoCo reset 验证协议连通性，不通过调用业务接口或注入 UUID 发现实例

#### Scenario: 应用标识或凭据缺失
- **WHEN** 当前系统未配置 skyeye_app_id，或未配置 token
- **THEN** 分别记录 APP_ID_UNRESOLVED 或凭据缺失原因并跳过增强，不从 system_id、DSF 名称或 token 猜测；凭据只存系统级本机配置，不进入共享记录或模型

#### Scenario: 配置和替换边界
- **WHEN** 配置覆盖增强或接入另一实例发现实现
- **THEN** 共享策略保存 enabled、发现方式和报告保留粒度，系统页面可编辑开关和粒度；选填天网 appId 与 token 保存于该系统本机 system.yaml，切换 QA/UAT 不重复填写；QA YAML 保存采集连接及日志环境覆盖，工作台高级本机设置可编辑 jacoco_cli_path、jacoco_java_command 和 coverage_review_model
- **AND** 普通系统或运行设置更新省略新增字段时保留已有值，普通 DSF 执行不解析覆盖连接；替换发现实现无需修改生成流程，容器 API 接入时只有唯一可用实例才允许测量

#### Scenario: 系统应用标识用于日志查询
- **WHEN** 当前系统配置 skyeye_app_id
- **THEN** 适配器将该值按字符串放入 appIds 单元素数组，并核对响应应用身份；不同系统独立保存，环境切换不覆盖其他系统配置，不在业务流程中写死退款 appId

#### Scenario: 私有系统设置读取和更新
- **WHEN** 本机页面调用系统级 skyeye-settings GET/PUT
- **THEN** 仅允许回环访问，响应只返回 skyeye_app_id 和 token_configured；PUT 省略 Token 保留、空串清除，页面空密码框保留旧值，显式清除才发送空串
- **AND** 文件原子写入且权限 0600，保留环境变量引用，Token 不进入普通序列化、错误响应、日志、共享策略或模型

### Requirement: 自动执行必须在提交后按精确绑定派发

系统 SHALL 在短事务中登记自动 Execution、专属增强 TaskRecord 的实际 TaskManager 进程 owner 及增强执行引用，最外层事务提交后才向同一现有线程池派发。每个不可变 Generation 在本增强中至多完整执行一次。

#### Scenario: 原有后台执行接入采集
- **WHEN** _finish_execution 开始
- **THEN** 仅 execution_id 精确匹配 baseline_case_execution_id 或 verification_case_execution_id，且系统、版本、QA 环境和阶段一致时采集；手动及未绑定执行只走原有业务路径

#### Scenario: 已绑定版本发布重试
- **WHEN** 本版本已有非空自动执行绑定，即使期间插入手动/UAT 执行或关闭 enabled
- **THEN** 返回精确绑定记录，不读取最近执行、不替换 owner、不重派；该 ID 指向记录缺失或身份不符时报告关联错误

#### Scenario: 合法空绑定
- **WHEN** 登记时直接 SKIPPED 或增强版 PARTIAL 导致本版本执行引用合法为空
- **THEN** 保持原验证路径，不伪造绑定或将合法空值当关联损坏；无增强绑定的原发布重试不由本能力扩展修复

### Requirement: 测量窗口应复用原验证并保持非阻断

系统 SHALL 非阻塞取得同系统 QA 的测量锁，在初始 10 秒共享准备预算内完成发现、工具、制品存在和固定引用、端口及许可 reset 检查，再在原验证后 dump；下载和报告分析在 dump 后释放锁再执行。

#### Scenario: 锁忙或准备超时
- **WHEN** 锁被占用或准备总预算耗尽
- **THEN** 立即跳过本次采集，停止准备及其子进程，原验证继续，不排队补测或留下后台 reset；基线记 SKIPPED，复测保留增强版并以 PARTIAL 结束

#### Scenario: dump 后取得报告制品
- **WHEN** 业务和断言结束并取得 dump
- **THEN** 下载执行前按固定 commit 选定的实际构建制品并匹配分析，不取事后最新包；归档同路径重新上传仍须核对实际字节码，下载、匹配、采集失败不改真实 Case 结果、不调用补充模型或重放业务

#### Scenario: 两个独立测量阶段
- **WHEN** 基础版和 READY 增强版分别执行
- **THEN** 各自记录 reset、dump、计数及有效性；本轮补充试跑安排在自身两个窗口之间，执行内部数据准备和断言照常，不禁止其他业务调用或声称已扣除其覆盖

#### Scenario: 业务或采集异常时释放测量窗口
- **WHEN** 已开启窗口内业务执行异常、dump 超时或清理失败
- **THEN** 在 finally 中有限时地尝试必要采集，并用嵌套 finally 释放测量锁和连接；清理异常不覆盖原业务异常或结果，失效窗口不产生有效覆盖结论
- **AND** 测量锁使用独立连接和零等待，不在整个窗口持有数据库写事务

### Requirement: 专属 TaskRecord 必须反映实际执行并统一同步

系统 SHALL 复用独立的 operation=coverage-enhancement TaskRecord 标识实际服务执行进程，并在 _finish_execution 的 finally 中同步其执行完成状态和增强进度，不使用原模型生成任务或新增 Case owner 字段。

#### Scenario: 正常或异常退出执行入口
- **WHEN** _finish_execution 正常 return、发生可捕获异常、采集失败或锁忙
- **THEN** 都经过 finally 的专属任务同步；依据真实业务结果及增强阶段处理，不因仅派发 background 任务就提前完成，不把覆盖错误改为业务失败

#### Scenario: Case 完成但增强仍有后续步骤
- **WHEN** 业务执行已结束而分析、补充或复测尚待执行
- **THEN** finally 只同步已完成阶段与进度，不将增强总流程或专属协调任务提前标为完成

#### Scenario: 增强跳过而业务仍运行
- **WHEN** 准备失败或锁忙已使增强为 SKIPPED，但绑定 Case 仍 RUNNING
- **THEN** 专属 TaskRecord 保留实际执行 owner 和运行期，直到业务完成或按严格退出证据收尾

#### Scenario: 线程池提交失败
- **WHEN** 记录已提交但线程池拒绝派发，_finish_execution 尚未进入
- **THEN** 派发边界处理确定未启动的执行及任务状态，不依赖 finally，不借发布重试重新派发；保存原执行身份和错误

#### Scenario: 同步存储不可用或进程被杀
- **WHEN** finally 的持久化失败，或进程 kill 导致 finally 未运行
- **THEN** 不宣称数据库终态已保存，不掩盖原异常、不重放业务；记录可取得的诊断并由持久恢复按已有事实处理，不能保证数据库不可用时仍成功落盘

### Requirement: 恢复必须依据严格进程证据且不得重放业务

系统 SHALL 复用真实 HTTP lifespan 和既有 maintenance callback，将有界、进程内去重的恢复作业交给原线程池，只处理本工作台增强关联；普通 GET 保持只读，心跳线程不执行查询、ps 或持锁恢复。

#### Scenario: 心跳失活但退出未确认
- **WHEN** TaskRecord 为 INTERRUPTED、心跳超时、PID/启动标识缺失、权限或读取失败，且没有严格退出证据
- **THEN** 保存 EXECUTION_OWNER_UNCONFIRMED 线索，不修改 Case、不转移 owner、不释放执行占用或重派；继续观察，活进程线程卡死不自动修复

#### Scenario: 绑定执行进程确认退出
- **WHEN** 原 PID 明确不存在，或原、新可靠非空启动标识不同
- **THEN** 短事务中重读关联、owner、revision 和精确执行，仅将仍 RUNNING 的绑定 Case 改 FAILED，保留 variant_results、回执和远端结果可能未知的说明；已终态结果不覆盖，测量、工作流和任务同步收尾

#### Scenario: 基线或复测窗口中断
- **WHEN** 原进程退出且业务终态与完整有效 dump 未同时持久化
- **THEN** 基线以 FAILED / EXECUTION_INTERRUPTED 结束且不补充；复测以 PARTIAL / EXECUTION_INTERRUPTED 结束并保留增强版；已 SKIPPED 等终态保留原原因，但遗留 RUNNING 仍须收尾

#### Scenario: 只读步骤能够恢复
- **WHEN** 完整业务终态和有效 dump 已保存，或模型原 turn/结果仍可取得
- **THEN** 只续做分析或接续原模型运行；未知派发找不到时保持未完成，不新开一轮；提交后派发前退出与执行中途退出均不重放业务

#### Scenario: 所有权边界
- **WHEN** 复测需换服务进程或检查其他工作台记录
- **THEN** 只有前一执行终态且阶段持久交接后才更新本工作台专属任务 owner；不检查他机 PID、不接管普通手动/历史执行、不修改 DataCapabilityService._recover_execution

### Requirement: 代码缺口必须有界并诚实表达范围

系统 SHALL 基于有效数据及已有证据的入口范围去重代码缺口，不将动态未知调用或覆盖建议转换为业务执行义务。

#### Scenario: 去重和截断
- **WHEN** 方法、分支行和代码行存在遗漏
- **THEN** 整个未执行方法只产生 METHOD；其余先 BRANCH_LINE，再合并不重复的 LINE_BLOCK；稳定排序选至多 30 项，保存候选和截断数量，不把截断项当已覆盖或已忽略

#### Scenario: 动态范围不足
- **WHEN** resolved-only 调用闭包不能证明全部动态行为完整
- **THEN** scope_status 为 PARTIAL 并保留理由，不承诺全部 Actor/状态机流程，不推测 JaCoCo XML 未提供的分支真假身份

#### Scenario: 执行失败上下文
- **WHEN** 存在准备、TARGET 或断言失败
- **THEN** 将既有逐 Variant 阶段结果提供模型；仅全部明确 TARGET 前失败才跳过补充，不以全部 FAILED、零成功或缺少记录替代，不声称聚合 exec 可定位单个失败 Variant 的路径

### Requirement: 补充与忽略复核最多形成一轮增强

系统 SHALL 以固定源码、基础 Case、数据函数、真实执行和选中缺口为输入，最多进行一轮补充、忽略独立复核及生成模型最终裁决；模型结论不作为实测解决证明。

#### Scenario: 补充职责先于普通生成上下文
- **WHEN** 已绑定的补充任务启动模型
- **THEN** 初始提示首先明确逐缺口处理目标、选中清单和 ADD_CASE/IGNORE/UNRESOLVED 协议；read_context 与 get_handoff 将覆盖上下文放在大型 handoff 和 Schema 之前，普通生成任务保持原职责
- **AND** 说明草稿修订已完成编译，模型应在发布前从 read_context 的 handoff.draft_variants 读取真实 ID 并修订处置，不能发布后再补填

#### Scenario: 旧草稿回执不能回退新处置
- **WHEN** 草稿请求重试返回旧修订回执、等待期间修订已推进或版本已经发布
- **THEN** 在同一 handoff 保护范围核对当前修订与状态，旧答复仅返回当前覆盖投影，不覆盖较新的最终处置，不再次启动审查

#### Scenario: 处置与独立审查
- **WHEN** 模型对选中项提出 ADD_CASE、IGNORE 或 UNRESOLVED
- **THEN** 保存理由和 case_variant_ids；忽略项使用独立上下文审查原始源码及调用上下文，返回 ACCEPT/REJECT/INSUFFICIENT_EVIDENCE，调用不可用为 UNAVAILABLE；生成模型最终决定并保留分歧，漏答记未解决而不阻断基础发布

#### Scenario: 唯一后继和额度
- **WHEN** 即将派发补充
- **THEN** 复查并复用现有唯一后继约束；其他后继存在则跳过且不占额度，正式派发前持久化 round_used=1，恢复不清零；增强版以 continue 继承原固定基线，关联 ID 必须在最终编译结果中有效

#### Scenario: 增强版部分完成
- **WHEN** 增强 Generation 为 PARTIAL
- **THEN** 保存 enhanced_generation_id，以 PARTIAL 结束覆盖流程且 verification 及其执行引用为空；保留原业务验证和自动后继，不递归登记覆盖增强

### Requirement: 增强结果应持久化并按配置保留诊断材料

系统 SHALL 复用 MySQL 的类型化 workflow、task 和 execution 聚合保存增强结果，不新增物理表、列、索引或 Generation 可变状态；小摘要、至多 30 项逐项理由及模型引用保留历史。

#### Scenario: 报告写入和未知效果
- **WHEN** 保存同一轮 baseline 和 verification
- **THEN** 使用 execution_id 等于 enhancement_id 的同一 coverage 报告，result 按阶段保存 Base64 exec 和 FrozenCoverageArtifact 的 gzip JSON，完整 XML/HTML 仅临时生成；写入失败保留可取得的分类诊断，不声称成功落盘
- **AND** 两段计数和至多 30 项 proposal/review/decision 保存在工作流，真实 Case 结果通过精确执行引用查询，SUPPLEMENT/REVIEW 的已知 provider/model、耗时和 token 可回查；未知值不替换为零，不维护第二套净增统计

#### Scenario: 原始报告和固定材料只供 owner 后端读取
- **WHEN** 原始 result 包含恢复所需的本机包／源码路径或 FTP 固定位置、原生文件身份及凭据环境变量名称
- **THEN** 不保存解析后的实际凭据；存储层先核对采集工作台 owner 再解压，其他工作台不可读原始包；前端及模型只读取不含 exec、私有固定定位和凭据引用的工作流投影
- **AND** HTML 重建仅由原工作台后端使用仍可取得并通过身份／class ID 检查的材料完成，临时目录随响应清理；材料缺失或已裁剪时明确不可重建

#### Scenario: 两种报告保留粒度
- **WHEN** report_retention_scope 为 SYSTEM_ENVIRONMENT 或 OPERATION
- **THEN** 分别按系统环境或系统环境接口保留最近一轮可用终态报告；只有新可用报告持久化后才裁剪旧 result，不删除活动恢复材料、缺口历史、业务执行或回执；已裁剪材料不因切换策略自动恢复

#### Scenario: 较旧窗口迟于新窗口完成
- **WHEN** 较新有效报告已终态并保存，而较旧窗口此后才完成分析
- **THEN** 在同 owner 和保留分组内按报告创建顺序重新确定最新有效终态，较旧完成回调须裁剪自身原始 result；仍活动的报告不裁剪，较新失效或空报告不能替换上一份可用材料

#### Scenario: 人工查看与前端状态
- **WHEN** 用户查看后台增强或继续基础版本
- **THEN** 分开展示生成、业务执行与增强状态；覆盖辅助生成入口提供可选 commit/tag 输入并提示留空使用 qa 分支最新提交；已有增强后继时引导查看/恢复原任务，不新增取消或独立重测入口；HTML 重建仅在对应字节码和所需源码可取得时提供，前端变更通过更新资源版本和真实 HTTP 页面验证
