## ADDED Requirements

### Requirement: Case generation uses independent fixed operation contracts
OpenTest SHALL use the entry purpose and independent request/response contract for Case generation and dependency selection. A missing legacy knowledge bundle, internal-flow narrative or migration review marker SHALL NOT block a READY contract. Case agents SHALL inspect the fixed source on demand, while source identity, employee visibility, actual input/output validation and execution authorization remain enforced.

#### Scenario: Ready target has no legacy narrative
- **WHEN** an employee generates or explicitly retries a Case whose fixed READY contract matches the selected entry and scan, with absent, empty or migration-marked legacy knowledge
- **THEN** allow both generate-only and generate-and-verify preparation without requiring a knowledge interview, full narrative or shared publication of the employee's own contract draft
- **AND** keep the same fixed contract references and use source analysis for business branches and expectations

#### Scenario: Preparation dependency has only an independent contract
- **WHEN** the Case agent selects a visible preparation or result-check operation with a fixed READY contract and no legacy knowledge body
- **THEN** return its contract and authorized runtime functions; optional historical narratives do not determine availability
- **AND** missing or mismatched contracts, unavailable routes and unauthorized operations remain explicit errors without changing the selected baseline

#### Scenario: Interface draft contains purpose and field descriptions only
- **WHEN** a source-validated independent interface contract is saved or explicitly published
- **THEN** persist its purpose and request/response fields without requiring or synthesizing a legacy business-logic knowledge bundle
- **AND** Case dependency compatibility compares the independent contract; historical narrative edits do not alone invalidate a Case

### Requirement: 所有产品入口使用公司员工身份
OpenTest SHALL 在页面、业务 API 和 Agent 工具使用前完成公司登录，以经过服务端核验的 newWorkId 保存员工归属，以 name-newWorkId 展示；不得信任请求自报员工或将机器身份视为员工身份。

#### Scenario: 未登录调用业务能力
- **WHEN** 浏览器或独立 Agent 工具没有有效凭据
- **THEN** 拒绝业务读取及写入并明确提示先登录；认证回调和必要健康检查除外

#### Scenario: 浏览器和独立插件会话到期
- **WHEN** 24 小时本机会话到期、注销、切换员工或服务重启
- **THEN** Cookie 和绑定的用户 bearer 同时失效；页面明确提示重新登录
- **AND** 插件每次调用重新读取当前用户可读的本机凭据，重新登录后原聊天可继续使用

#### Scenario: 已授权任务遇到浏览器退出
- **WHEN** 已启动任务运行期间浏览器会话过期或注销
- **THEN** 独立任务凭据仍只允许原员工、基准、知识、环境和任务范围内的后续步骤
- **AND** 任务终止、取消、超时或服务重启使旧任务凭据失效，恢复只能由已验证的服务端恢复流程重新签发；task_id 不足以换取凭据

#### Scenario: 非本机页面尝试携带 Cookie 写入
- **WHEN** Host、Origin 或 CSRF 不符合本机登录会话规则
- **THEN** 服务端拒绝请求且不创建业务任务；有效 bearer 工具调用按其独立凭据规则校验

#### Scenario: 插件安装目录或凭据位置不同
- **WHEN** 员工在另一电脑安装插件，或使用自定义 OPENTEST_CREDENTIAL_FILE
- **THEN** MCP 从实际插件安装目录启动并接收该凭据路径，不依赖开发者的绝对工作区路径

#### Scenario: 持久任务鉴权查询较慢
- **WHEN** 任务活动或私有对象归属查询等待数据库
- **THEN** 同步查询不阻塞 HTTP 事件循环或持有整段会话锁，其他登录请求仍可响应
- **AND** 查询期间被撤销或过期的任务凭据不能因迟到结果再次有效

### Requirement: 共享固定基准与个人查看选择
OpenTest SHALL 按系统和完整 commit 唯一保存共享基准。当前查看的系统、基准和 QA/UAT 环境 SHALL 只影响本人页面，任务创建时冻结选择，后续切换不得改写运行中任务。

#### Scenario: 创建同 commit 的另一来源
- **WHEN** branch 和 tag 解析为已有基准相同的完整 commit
- **THEN** 复用该基准并保留首个创建来源，后续请求来源保留在任务记录；不创建第二套共享 Case

#### Scenario: 新建基准
- **WHEN** 已登录员工选择 branch、tag 或 commit 创建基准
- **THEN** 固定源码、扫描、资源校验并生成全部接口知识；仅复制业务背景和术语，Case 初始为空
- **AND** 已完成源码上传的基准可被其他员工选择，接口知识和 Case 仍需分别发布才能共享

#### Scenario: 创建过程被中断
- **WHEN** 源码上传、扫描或知识生成中的后续阶段失败
- **THEN** 使用已有任务记录保留成功阶段，续跑只处理缺失或失效阶段；不重复已知业务写入

#### Scenario: 基准任务提交与开始之间中断
- **WHEN** 任务已提交但创建记录尚未收到 worker 回填，或提交进程退出后没有可查证的已提交任务
- **THEN** 续跑先查证并关联原任务；仅证明原提交进程已退出且不存在原任务时才重新提交，不因空 task_id 永久阻塞或并行重复创建

#### Scenario: 资源探测抛出异常
- **WHEN** 源码及扫描成功但资源探测失败或抛出异常
- **THEN** 保存明确失败的资源结论后继续生成接口知识，整体不能把资源校验显示为成功

#### Scenario: 保存基准业务背景
- **WHEN** 员工只更新背景和术语
- **THEN** 保留该基准已有访谈和问题，仍用原修订号检测并发更新

#### Scenario: 历史基准包含大段背景正文
- **WHEN** 员工读取包含大量历史背景、访谈或问题正文的基准列表
- **THEN** 列表按创建时间降序、相同时间基准ID升序返回完整可见内容，不因数据库对大JSON排序耗尽缓冲区而不可用
- **AND** 本人的未完成基准和历史共享基准继续遵守原可见性规则，不暴露其他员工尚未共享的基准
- **AND** 基准列表及详情复用既有压缩传输读取完整 JSON，避免大正文长期占用数据库读连接，不改变业务返回字段

### Requirement: 对象存储保存可跨机器读取的实际材料
OpenTest SHALL 使用标准 S3 SDK 和可配置 endpoint、region、bucket、path-style 保存源码、扫描依赖及覆盖材料；MySQL 保存业务记录和对象引用。材料默认永久保留，私密配置不得进入共享记录、模型或日志。

#### Scenario: 员工没有原作者仓库目录
- **WHEN** 另一员工选择共享基准并需要读取源码或扫描依赖
- **THEN** 后端取得同一固定材料并物化本机缓存，不要求原作者路径、Git 权限或本机 Maven 缓存
- **AND** 材料缺失时明确不可用，不用当前工作区或最新包替代

#### Scenario: 无源码绑定机器首次执行与校验
- **WHEN** 员工只持有共享数据库和对象存储访问配置，首次执行已发布 Case 或独立资源校验
- **THEN** 先物化该次操作固定扫描的源码，使用其 QA/UAT 配置解析目标及实际下游调用方
- **AND** 不要求原作者目录，不使用另一版本本地仓库配置，也不修改系统全局源码绑定

#### Scenario: 上传未完成
- **WHEN** 对象上传中断或引用登记失败
- **THEN** 不发布材料可用状态，后续依据已有阶段确认对象是否可用后继续

### Requirement: 个人草稿与当前发布内容分离
OpenTest SHALL 在共享数据库保存按员工隔离的接口和 Case 草稿，提供 published 与 mine 视图；扫描和生成完成不等于发布。发布数据粒度 SHALL 支持单接口和单个可执行 Case，页面支持当前基准全部发布。

#### Scenario: 草稿未发布
- **WHEN** 员工甲完成接口扫描或 Case 生成
- **THEN** 员工乙不能读取甲的未发布内容，同一员工换电脑仍能读取自身草稿

#### Scenario: 换机器保存本人固定 Generation
- **WHEN** 员工在另一台机器继续本人的 Case 草稿并保存
- **THEN** 按持久化载荷比较同一不可变 Generation，不因本机源码目录投影不同拒绝草稿
- **AND** 固定内容、绑定或依赖实际变化时仍拒绝保存

#### Scenario: 同 Generation 只发布一个 Case
- **WHEN** 一份 Generation 包含多个 Variant 而仅一个 Case 已发布
- **THEN** 其他员工只能取得该 Case 的精确 Variant 和必要模板、数据函数及执行投影，不得到整份 Generation DSL

#### Scenario: 完整共享列表包含大量知识及重复 Generation
- **WHEN** 员工读取 published 或 mine 接口和 Case 列表
- **THEN** 根据已授权的固定指针批量读取精确版本，单 Case 投影保持不变，不逐条重复查询
- **AND** 同一请求中的每份 Generation 只读取、解压和严格解析一次，不建立跨请求内容缓存，也不暴露其他员工草稿或私有兄弟 Case

#### Scenario: 页面读取接口目录与基准列表
- **WHEN** 页面读取当前基准的接口列表或系统基准列表
- **THEN** 接口列表只返回身份、状态、修订、用途摘要和是否已有知识，不传输契约、知识正文及每份知识冻结的业务背景；基准列表不携带背景、访谈和问题正文
- **AND** 单个接口的契约与知识正文通过单项读取按需取得，可见条件与列表相同；他人草稿、未发布或跨基准身份返回不存在，单项响应不重复携带业务背景
- **AND** 业务背景与术语只通过基准背景入口读取和保存

#### Scenario: 读取连接池耗尽
- **WHEN** 请求在既有读连接池等待上限内未取得连接
- **THEN** 返回 HTTP 503 和 metadata_unavailable，保留等待耗时，不作为未分类的 HTTP 500
- **AND** 不扩大连接池、不自动重试，不把 SQL 执行中其他驱动错误改记为连接池等待错误
- **AND** 私有路由归属校验和任务凭据活动检查阶段同样返回该错误；不能绕过身份校验，也不能在下游响应开始后再发送第二份错误响应

#### Scenario: 共享内容被替换
- **WHEN** 同接口或 Case 发布新内容
- **THEN** 页面和旧 ID 入口只允许当前发布内容，旧记录留在数据库；已发布草稿不能通过 mine 重新开放被替换内容

### Requirement: 发布使用固定范围与可解决的并发冲突
OpenTest SHALL 同步逐项短事务发布，使用既有工作流回执固定请求身份、草稿列表及修订；每项比较预期共享修订，不以重试自动覆盖他人发布。

#### Scenario: 全部发布请求重试
- **WHEN** 首次全部发布后又生成新草稿，同 request_id 因网络失败重试
- **THEN** 仅重放原冻结列表的回执，不把期间新草稿发布；相同 request_id 不同显式内容报冲突

#### Scenario: 两人发布同一接口
- **WHEN** 第二位员工的预期共享修订已经过期
- **THEN** 保留草稿并展示当前共享差异，允许放弃草稿或明确保留自己修改后基于最新修订重新提交；内容等价时返回已与共享一致

#### Scenario: 部分发布失败
- **WHEN** 批次中某些条目失败或冲突
- **THEN** 已成功条目保持成功并逐项返回结果，重试不重复发布成功项

#### Scenario: 单项草稿材料损坏或范围不一致
- **WHEN** 某项草稿存在可识别的范围、缺失材料或结构解析错误
- **THEN** 回滚该项写入并保存脱敏的 BLOCKED 回执，继续处理批次其他条目
- **AND** 等价比较前校验当前与候选独立契约及固定身份，旧知识正文不参与可执行性或等价判定
- **AND** 数据库故障或未知程序异常仍明确失败，不能伪装成已确定的草稿错误或吞掉未知提交结果

#### Scenario: 发布中元数据库暂时无法连接
- **WHEN** 连接配置、凭据或驱动连接失败，当前条目尚无确定提交结果
- **THEN** 返回 HTTP 503 和 metadata_unavailable，不保存永久 BLOCKED 结论
- **AND** 连接恢复后同 request_id 继续原冻结集合，已成功条目不重复发布

### Requirement: 接口发布只影响相关 Case
OpenTest SHALL 将发布状态与影响状态分离，使用当前共享指针判断发布，使用 CURRENT、NEEDS_UPDATE、INTERFACE_REMOVED 判断已有 Case 影响；不确定影响以 REVIEW_REQUIRED 原因明确显示需复核。

#### Scenario: 接口发布新增或变化
- **WHEN** 发布包含新增接口、契约变化和无关接口
- **THEN** 新增接口显示未生成 Case，受影响已有 Case 显示待更新或需复核，无关 Case 保留

#### Scenario: 为受影响Case创建修改版本
- **WHEN** 员工对待更新 Case 创建新的单项修订
- **THEN** 创建时解析实际使用依赖在当前选定视图中的知识及扫描，再冻结到新任务
- **AND** 不把旧目标扫描重复选为新任务目标，不改写仍在运行任务的已冻结引用

#### Scenario: 复核确认 Case 无需修改
- **WHEN** 员工为待更新 Case 建立个人草稿，明确发布与当前共享内容等价的 Case，且全部固定依赖及当前接口可执行性校验通过
- **THEN** 在同一发布事务内清除影响状态和复核原因，恢复 CURRENT，不要求人为改动 DSL，不推进等价内容的共享修订或更换指针
- **AND** 缺失或非 READY 的独立契约、契约不匹配和已移除接口不能借等价发布解除阻断；仅缺旧正文或带旧迁移标记不阻止有效契约通过显式复核
- **AND** 回执重放不消除之后新产生的影响状态，后续写入失败时复核状态清除也一并回滚

#### Scenario: 接口移除
- **WHEN** 已明确确认移除接口并发布
- **THEN** 相关 Case 显示接口已移除并禁止执行，不删除旧记录

#### Scenario: 数据函数被草稿使用
- **WHEN** Case 草稿创建或更新数据函数
- **THEN** 函数继续遵循已有成功试跑后显式发布规则，已发布固定版本按系统共享，不随 Case 草稿自动共享

### Requirement: 知识和资源操作遵循基准与环境范围
OpenTest SHALL 使页面和 Agent 知识读取使用固定基准及 published/mine bundle，环境选择影响资源校验和 Case 执行；用户可对已有基准独立重新执行资源校验。

#### Scenario: 切换到 UAT 校验
- **WHEN** 用户对当前基准选择 UAT 并请求资源校验
- **THEN** 服务端解析当前可见接口的精确扫描引用并校验 UAT，不重扫源码或读取系统 latest_scan 代替

#### Scenario: Agent 请求其他人的草稿
- **WHEN** 工具提供不属于当前员工或任务冻结范围的知识引用
- **THEN** 拒绝读取，不能绕过 UI 视图限制

#### Scenario: 生成时依赖接口无法解析
- **WHEN** 固定源码的已声明下游接口无法从当前固定契约和依赖材料中解析
- **THEN** 无候选时明确报告缺失接口及已知依赖材料缺口，不把缺失材料误报为方法重载
- **AND** 只有多个匹配候选时才要求精确签名；不下载或猜测其他版本，不以接口用途描述替代可执行输入输出契约

#### Scenario: Maven 仅完成部分模块的依赖解析
- **WHEN** 固定源码的离线 Maven 解析只输出部分模块的实际 classpath，其他模块的精确直接依赖已有本地 JAR 或源码包
- **THEN** 保留成功模块的 classpath 顺序，并补入固定 POM 已证明且版本唯一的直接依赖，不因部分成功丢弃已有接口材料
- **AND** Maven 已解析的依赖版本优先；未被 Maven 解析且存在多版本声明的依赖保留歧义缺口，不按本地文件可用性猜选版本
- **AND** 完整 Maven 解析及已冻结的扫描依赖仍使用原结果，不扩大为其他版本或任意本机 JAR 搜索

### Requirement: 历史共享资产迁移可核对且不静默丢失
OpenTest SHALL 提供显式 dry-run/apply 升级和可重复回填；历史接口与 Case 按基准、接口和明确替代链建立初始共享集合，无法证明作者的记录保留空归属。独立 Case 集 SHALL 保留，不用每接口最新一份猜测替代关系。

#### Scenario: 历史基准没有 S3 源码
- **WHEN** 旧成果可读但原固定材料尚未上传
- **THEN** 共享成果仍可见并明确材料缺失，只禁止依赖缺失材料的操作，允许按原固定材料补传

#### Scenario: 背景术语迁移
- **WHEN** 从现有系统 context_json 建立首批基准
- **THEN** 复制迁移时的背景和术语并标记共同来源，不伪造各历史时间点内容

#### Scenario: 历史入口只有独立契约
- **WHEN** 迁移入口有与固定身份及扫描匹配的 READY 独立契约，但没有旧知识正文
- **THEN** 不补造完整知识正文，不仅因缺正文新增 Case 复核阻断；是否兼容依据实际 Case 契约和已保存依赖判定
- **AND** 缺少、非 READY 或身份不匹配的契约仍保留复核，已存复核状态不因读取或迁移重跑自动消除

#### Scenario: 历史同 commit 扫描范围不同
- **WHEN** 同系统、同干净 commit 的扫描范围不同，旧接口只存在于组内较早扫描
- **THEN** 使用组内接口并集及最近已知材料，不仅因首选扫描缺项而新增复核原因或推断接口已移除
- **AND** 脏扫描、缺少 commit 或不同系统的扫描不得合并，独立契约缺失或实际依赖不一致仍需复核，不覆盖新模型已明确发布的 REMOVED 结论
- **AND** 已保存的旧复核状态不因迁移重跑自动放行，仍经显式复核发布解除

#### Scenario: 旧记录没有员工归属
- **WHEN** 原执行工作台恢复或收尾 owner 为 NULL 的旧工作流或执行记录
- **THEN** 保持 NULL，不因当前登录上下文认领；工作台限制和已有非空员工归属仍受保护
- **AND** 不因此开放旧私有记录的匿名访问或员工读取权限

#### Scenario: 历史 Case 业务载荷原样保留
- **WHEN** 为历史 Generation 回填基准和单项 Case 身份，或再次执行相同迁移
- **THEN** 只补充身份关联，原输入契约、输入值、断言和 DSL 保持不变，不能通过模型重序列化补写原本未提供的业务默认字段
- **AND** 原 Generation 和 Variant ID 保持不变，重复执行不会增加重复的 Case 或覆盖后来发布的内容

#### Scenario: 历史条目异常无法补齐
- **WHEN** 人工确认某个历史条目不能恢复
- **THEN** 可将该条目标为不可用并保留原数据及处置理由，视为该条目已处理
- **AND** schema 失败、系统性映射错误、身份隔离失败或数据丢失不能据此豁免

### Requirement: 旧整份资产读取在调用方迁移后退役
OpenTest SHALL 先迁移页面、插件和基准脚本使用安全 Case 接口，再将旧整份 Generation 和整份执行读取返回 410；生成请求、任务进度及专用覆盖入口按用途保留并校验身份范围。

#### Scenario: 发布后的旧 URL 被请求
- **WHEN** 已迁移调用方后请求退役的整份资产读取入口
- **THEN** 返回 410 和新入口提示，不因旧 ID 暴露私有或被替换内容

#### Scenario: 共享终态任务请求整批继续
- **WHEN** 通过旧 API 或 MCP 对已完成的共享任务请求创建整批后继
- **THEN** 在新任务和后继写入前拒绝，提示从当前可见的单 Case 创建修订；活动草稿继续保持原冻结范围恢复

#### Scenario: 已完成网页生成请求重放
- **WHEN** 浏览器重发已完成任务的同一创建请求
- **THEN** 返回当前仍可见单 Case 的安全投影，不返回旧整份草稿，不再次派发模型或执行

#### Scenario: 已经打开的旧页面执行写入
- **WHEN** 页面资源版本与服务版本不符
- **THEN** 阻止写操作并提示刷新，保留尚未提交的输入；更新后通过真实 HTTP 页面验证新的资源版本

### Requirement: Contract revisions carry evidenced mutability under personal publication scope
The system SHALL store mutability, analyzed state, reason and source evidence in existing contract JSON. An analyzed UNKNOWN SHALL override scanning READ_ONLY. WRITE requires reachable method evidence; READ_ONLY requires all parsed reachable methods and no scanning WRITE conflict. Unanalyzed contracts retain the scan hint.

#### Scenario: Analysis cannot establish read-only semantics
- **WHEN** analysis submits UNKNOWN with a reason, including when semantic analysis is unavailable
- **THEN** the result is saved as analyzed and cannot authorize query or Oracle use

#### Scenario: Employee supplements a visible fixed interface
- **WHEN** the employee explicitly requests classification for a selected baseline, scan and visible contract revision
- **THEN** the task freezes that version and employee scope, validates evidence against that scan, and saves a new authored revision plus the employee draft pointer atomically using existing draft/publication CAS
- **AND** another employee's later draft cannot become the content base or appear in the published view without explicit publication

#### Scenario: Unrelated contract revision advances during analysis
- **WHEN** a different revision is saved after task creation
- **THEN** the task retains its original content base and conflicts with changed personal/publication pointers instead of silently rebasing

#### Scenario: Personal draft CAS fails after contract supplementation
- **WHEN** the native contract tool appends a revision but its personal draft CAS conflicts
- **THEN** the enclosing system transaction rolls back the appended contract and latest revision together, preserving the preexisting draft pointer
- **AND** standalone contract supplementation continues to own its own transaction; combined writes require a caller-owned system transaction
