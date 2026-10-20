## MODIFIED Requirements

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

系统 SHALL 在覆盖辅助生成请求中提供可选 source_revision，接受 commit/tag；空值优先使用 qa 分支当时最新提交的可用扫描，缺失时保留原基础生成并跳过本轮增强。任务冻结实际 commit、source_scopes 和 source_scan_id，不修改系统 pin/latest、不自动扫描或占扫描门禁。

#### Scenario: 明确选择 commit 或 tag
- **WHEN** 用户为覆盖辅助生成填写可解析的短/完整 commit 或 tag
- **THEN** 固定其解析出的完整 commit 并使用 clean、目标入口和同扫描契约可用的 scan；没有可用扫描时明确提示系统页扫描，不静默换版本；本次示例 `7b962925` 对应 `7b962925db34b181f66e39a9262356585a8fcc03`，示例值不得硬编码进通用逻辑

#### Scenario: 覆盖辅助任务未填写版本
- **WHEN** 覆盖策略启用、选择 generate_and_verify 且 source_revision 为空
- **THEN** 优先解析 qa 最新提交并复用可用扫描；无法获得时沿原有准入条件生成基础 Case、跳过增强并说明原因；冻结实际 scan/commit，重试不重新追踪 QA，非增强历史行为不变

#### Scenario: 分支或 tag 在重试前移动
- **WHEN** 同一任务发布重试、continue 或执行覆盖补充时 qa 分支或原 tag 已指向新提交
- **THEN** 继承已固定 commit 和 pin/scan，不重新解析或替换基线；所选版本是否与 QA 字节码相符仍通过实际构建制品和 class ID 核对

### Requirement: 恢复必须依据严格进程证据且不得重放业务

系统 SHALL 复用真实 HTTP lifespan 和既有 maintenance callback，将有界、进程内去重的恢复作业交给原线程池，只处理本工作台增强关联；普通 GET 保持只读，心跳线程不执行查询、ps 或持锁恢复。

#### Scenario: 心跳失活但退出未确认
- **WHEN** 存在 TaskRecord INTERRUPTED 或心跳失活线索，且没有严格退出证据
- **THEN** 保存 EXECUTION_OWNER_UNCONFIRMED 线索，不修改 Case、不转移 owner、不释放执行占用或重派；继续观察，活进程线程卡死不自动修复

#### Scenario: 绑定执行进程确认退出
- **WHEN** 原 PID 明确不存在，或原、新可靠非空启动标识不同
- **THEN** 短事务中重读关联、owner、revision 和精确执行，仅将仍 RUNNING 的绑定 Case 改 FAILED，保留 variant_results、回执和远端结果可能未知的说明；已终态结果不覆盖，测量、工作流和任务同步收尾

#### Scenario: 基线或复测窗口中断
- **WHEN** 原进程退出且业务终态与完整有效 dump 未同时持久化
- **THEN** 基线以 FAILED / EXECUTION_INTERRUPTED 结束且不补充；复测以 PARTIAL / EXECUTION_INTERRUPTED 结束并保留增强版；已 SKIPPED 等终态保留原原因，但遗留 RUNNING 仍须收尾

#### Scenario: 只读步骤能够恢复
- **WHEN** 完整业务终态和有效 dump 已保存，或模型原 turn/结果仍可取得
- **THEN** 只续做分析或接续原模型运行；确认原 owner 退出且无运行回执、活动 Agent、人工接续等可恢复证据、非明确 GATE_BUSY 时以 PARTIAL 结束派发未知，不新开一轮；提交后派发前退出与执行中途退出均不重放业务

#### Scenario: 所有权边界
- **WHEN** 复测需换服务进程或检查其他工作台记录
- **THEN** 只有前一执行终态且阶段持久交接后才更新本工作台专属任务 owner；不检查他机 PID、不接管普通手动/历史执行、不修改 DataCapabilityService._recover_execution

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
- **THEN** 分开展示生成、业务执行与增强状态；覆盖辅助生成入口提供可选 commit/tag 输入并提示留空优先 QA 最新可用扫描、缺失时保留基础生成并跳过增强；已有增强后继时引导查看/恢复原任务，不新增取消或独立重测入口；HTML 重建仅在对应字节码和所需源码可取得时提供，前端变更通过更新资源版本和真实 HTTP 页面验证

## ADDED Requirements

### Requirement: 有效证据与终态收尾必须可重入
系统 SHALL 在有效 dump 与分析阶段持久化后保留证据，分析派发和收尾失败不得作废已保存材料；分析结果存在时只补收尾。

#### Scenario: 派发失败或收尾异常
- **WHEN** report 已保存后 submit 失败，或 analysis 已保存后 finish 失败
- **THEN** 保留有效测量，既有维护入口只续分析或收尾；当前线程池不可用时等待正常恢复，不重放 Case

#### Scenario: 同进程和跨进程去重
- **WHEN** 初次派发与维护同时请求分析，或两个服务同时接管退出 owner
- **THEN** 活动 Future 按增强和阶段去重并在结束/提交失败后清理；系统事务内重读完整 owner、精确执行与增强 revision，执行已终态后原子写入唯一接管 owner/revision，失败者只观察
- **AND** 健康 owner 与未变化状态不写异常或重复保存；所有专属 owner 和整条任务更新在相同系统锁下重读，不写回旧 owner

#### Scenario: 小终态与报告状态
- **WHEN** finish 首次或重复收尾
- **THEN** 同一短事务保存工作流、报告列及摘要状态、任务终态；不重写旧报告 result，重复调用不改既定终态和结束时间；读取 coverage 报告使用同次查询的列状态覆盖压缩包旧状态
- **AND** 模型证据读取、大包解析及裁剪在终态事务外；损坏候选逐条隔离，历史终态但任务未完成可补齐

#### Scenario: 裁剪失败与内部标记
- **WHEN** 终态提交后原始材料裁剪失败或进程退出
- **THEN** 既有工作流使用 INTERNAL_ 前缀标记待裁剪，维护候选继续补裁剪，成功清除；公开投影、任务摘要、模型和页面均不显示内部标记；不得重算分析或重放业务

### Requirement: 后继和兼容性修复不得阻断基础生成
系统 SHALL 通过既有前驱与后继关联控制增强递归和页面行为，可选覆盖查询失败不得阻断原基础生成。

#### Scenario: 多层增强后继
- **WHEN** READY 候选自身或任意前驱是增强 Generation
- **THEN** 不再自动登记增强；有界遍历防循环，缺失或无法核实只跳过辅助；普通无增强祖先 READY 后继可登记

#### Scenario: 迟到发布与页面后继
- **WHEN** 增强已终态后又发布原 child，或用户在已有后继的基础版点击继续/重新生成
- **THEN** 保留产物关联且不重开增强；投影包含后继，展示和点击均引导原任务、禁用重复生成，后端唯一约束保留

#### Scenario: 旧回执与可选查询
- **WHEN** 旧草稿回执缺 coverage_dispositions，或覆盖投影/上下文记录损坏
- **THEN** 旧回执缺字段按空列表比较，非空变更仍冲突；可选查询安全降级，明确绑定的执行身份错配仍严格报错

### Requirement: 采集适配器必须符合声明的材料与清理边界
系统 SHALL 支持本地 WAR、普通 JAR 和 BOOT-INF 制品，并保持公司 FTP 已确认的 WAR 布局；凭据和采集资源不能因异常泄漏。

#### Scenario: 制品布局
- **WHEN** 固定材料为 WEB-INF、BOOT-INF 或普通根目录 class 布局
- **THEN** 按相同安全解压及业务类归属规则提取完整候选，不把不支持布局误报为业务类不存在

#### Scenario: 重定向与异常清理
- **WHEN** 天网返回重定向、reset 或准备阶段中断、锁服务返回 NULL 或后续下载超时
- **THEN** 不跟随重定向发送 token，清理 reset 临时目录并释放测量租约；锁错误与锁忙区分，准备与后续材料/分析超时分开诊断
