# OpenTest 开发状态

## 当前Change

`codex-native-open-test-workspace` 已完成实现并收敛为“完善背景 → 在Codex生成与补全 → 使用与修订”三步流程；右栏只展示持久化Codex任务并返回原线程，历史问题周期只读保留。知识详情使用有界内存投影，Facade/Job操作通过独立索引、operations MCP和显式系统Skill暴露；本轮仅用fake provider验收，未执行真实QA写入或Job。已完成的`semantic-knowledge-workspace`及其历史任务结论保持不变。`dsf-execution-and-oracles`保持`WAITING_QA_INPUT`。

2026-08-24 当前实现将Codex客户端知识生成升级为`gpt-5.6-sol` Low/Medium（默认Medium）、全仓库单活动聊天、0600全局业务Prompt模板及完整合成预览。Facade候选新增安全与内容完整度分层，缺口在原聊天最多自动补全两轮，完整后自动发布；接口`invocation_contract`以结构化附属字段和独立能力索引保存，明确排除普通Markdown、FTS和知识问答上下文。旧`queryList`拒绝聊天已固化为`CANCELLED`并释放全局名额。真实页面已用`gpt-5.6-sol / medium`创建唯一新聊天`01a03270-708f-79d1-80a6-62491ecb863d`，任务`task-c0b2de4673b01efa`在同一线程完成两轮补全并自动发布：真实路径覆盖Facade、`RefundOrderListQueryInvoker`、Service的列表/计数方法、DAO/Mapper和分页边界，候选为`1个节点 / 4步路径 / 0个疑点 / 0个完整度缺口`，调用契约独立保存。Prompt只提供入口、业务背景、术语、确定性契约和确认事实，未预告下游类名；刷新与补全未创建第二个聊天。首次页面尝试`task-c9480ab5887f2a85`因PATH中的旧Codex CLI不认识目标模型而在调用模型前失败、未产生费用；App Server现优先使用桌面应用内置且已验证支持该模型的可执行文件。真实候选暴露的Java到XML Mapper相邻校验崩溃也已加入回归并修复。

## 已完成任务

- 2026-08-24：OpenTest内存加速与Codex原生操作change完成。真实21.401 MiB扫描`scan-20260822121007-6b0d5d1222-8ade0ea6`包含99个目标：冷投影`1161.143 ms`，此前tracemalloc测得投影存活约`0.589 MiB`、解析峰值`134.127 MiB`；按实测校准后的缓存权重`779364 bytes`，100次完整后端`RefundFacade#queryList`详情路径为p50 `31.159 ms`、p95 `37.163 ms`、最大`38.918 ms`，缓存`100 hits / 1 miss / 1 rebuild`。投影采用跨进程revision、单飞重建、latest优先的`128 MiB / 32 entries`加权LRU及失败恢复。独立`OperationCapability`索引、持久request reservation去重、QA-only固定scan provider、Schema门禁、Facade同步/Job异步契约和四工具operations MCP已由fake provider覆盖；真实意图“帮我生成退票自愿退票单”唯一命中`RefundFacade#createOrder`并识别必填`refundDetailApiDTO`、`orderChannelSource`，未执行。系统Skill`$open-test-ifightchainsaas-java-refund-core`为显式调用，插件已校验并刷新为`0.1.0+codex.20260824080841`。页面不再调用问题周期、旧聊天或确认写接口，后端统一返回410及已有Codex深链，App Server恢复只新增无副作用`thread/read`能力。最终门禁：V2 `424 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `11 tests / 0 failures`、OpenSpec strict `33 passed / 0 failed`，compileall、Node语法、`pip check`、Skill/插件校验及diff检查通过。OCR delegation preview/rule成功解析本次干净基线上的`28 reviewable / 36 total`范围；唯一只读代理在创建前因当前Codex会话仍引用插件刷新前的已移除缓存路径而无法初始化，未产生代理实例或审查结果，故按项目fallback完成两遍主代理完整diff审查：初审`0 High / 9 Medium / 0 Low`全部修复，唯一follow-up为`0 High / 0 Medium / 0 Low`且无代码变更，无拒绝项。`queryList`未重新生成，发布文件SHA-256保持`13ada1181d643138fab239d4b4742a182121bd89ac213988658e2e89a5f31aa1`，任务`task-c0b2de4673b01efa`与线程`01a03270-708f-79d1-80a6-62491ecb863d`不变；未访问QA或Fixture正文，未执行DSF金丝雀、真实写接口、Job或31个生命周期Case。
- 2026-08-24：Codex快速完整知识与独立调用契约最终验收通过。真实页面以`gpt-5.6-sol / medium`为`RefundFacade#queryList`创建唯一聊天并在同一线程完成两轮补全、自动发布；切换接口立即显示加载态且不保留旧正文，刷新恢复同一任务和会话，调用契约独立折叠展示。最终门禁：V2 `412 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `11 tests / 0 failures`、OpenSpec strict `32 passed / 0 failed`，compileall、Node语法、`pip check`和diff检查通过。OCR delegation由同一个只读代理完成两轮：初审`5 High / 2 Medium`与唯一复审`0 High / 2 Medium / 1 Low`均已修复，代理未修改文件。未访问QA或Fixture正文，未执行DSF金丝雀、写接口或31个生命周期Case。
- 完成现有MVP架构、测试和真实scriptgen扫描审计。
- 确认采用同仓库旁路重构、Git知识真相源和SQLite派生索引。
- 初始化OpenSpec，并严格校验首个V2 change。
- 建立V2领域模型、统一错误、日志上下文和本地任务管理。
- 实现单系统Git知识存储、人工区域保护和SQLite FTS5派生索引。
- 建立共享应用服务、FastAPI基础接口和V2 CLI。
- 完成foundation两轮OCR delegation独立审查并修复全部High/Medium发现。
- 实现Git/非Git源码基线、真实scriptgen、MQ Consumer和状态机结构扫描。
- 建立扫描manifest、真实工具隔离目录、CLI与FastAPI扫描入口。
- 对真实火车票项目验证 `TradeFacade#createOrder` 纵向扫描入口。
- 完成源码扫描两轮OCR delegation审查，并修复3 High与后续全部Medium发现。
- 完成 `TradeFacade#createOrder`、Validator、ServiceInvoker、OrderBuilder与订单状态机的纵向知识追踪。
- 完成V2引导式控制台与系统接入：九个左侧工作区、DSF注册自动扫描、90/36/5/1/19真实目录、MQ单集群聚合、结果校验能力抽屉和可访问帮助提示。
- 完成本地Labrador Token安全边界：回环读写、原子0600保存、旧文件读取前收紧、文件与目录符号链接拒绝、环境引用兼容及共享产物泄漏测试。
- 完成资源连接与业务验证双状态持久化，临时连接失败不会抹掉Snapshot业务证据；旧MQ资源ID在探测、证据和Snapshot边界统一规范化为集群ID。
- 已归档`v2-guided-console-and-system-onboarding`并同步8项主规格要求；创建并严格校验`generalized-knowledge-case-and-natural-language-workflow`的proposal、specs、design和tasks。
- 完成Git知识发布、人工确认保护、高影响问题批次和SQLite重建闭环。
- 增加最小权限AgentRunner、知识CLI与FastAPI入口。
- 对真实项目生成10个知识节点、10条关系和2个高影响问题，港币规则证据定位到OrderBuilder第359和594行。
- 完成createOrder覆盖目标、业务约束、等价类、边界值和确定性pairwise变体生成。
- 完成Git Case存储、自然语言约束编译、缺失条件返回及CLI/FastAPI入口。
- 从真实知识生成5个CoverageTarget和12个当前变体：8个具备硬业务断言，4个因口径或内部状态Oracle未就绪而明确blocked。
- 完成Snapshot完整版本摘要、真实生成工具DsfExecutor、类型化变量绑定、JSON断言diff和运行证据。
- 建立DSF、MySQL、Redis和MQ Oracle边界及统一deadline轮询器。
- 增加本地QA环境引用、敏感命令脱敏、Snapshot/执行CLI和FastAPI入口。
- 为真实项目创建绑定源码、知识、12个当前Case变体、126个真实工具和Skill的Snapshot；7个历史变体保留为stale审计资产。
- 完成V2控制台、Case编辑、深层关系展开和完整 `/api/v2` 资源路由；前端静态契约确认不调用legacy API。
- Case变体增加generated/user_edited/blocked/stale生命周期，自动迭代保护人工编辑并拒绝执行陈旧或未形成可靠判定的变体。
- createOrder Case改为从真实scan请求模板构造DTO；报价结果只作为数据前置条件，不再混入接口请求。
- 增量Case采用合并语义和系统级跨进程锁，Snapshot绑定真实脚本字节并验证内容寻址身份。
- Oracle步骤已接入正常Scenario执行，任务管理增加PID、实例心跳和死亡所有者恢复。
- 港币报价数据前置条件执行前必须匹配本地QA观察值并提供非空证据，验证证据会脱敏写入RunRecord。
- NoAdult及业务拒绝Case不再执行订单号清理；提前拒绝的NoAdult只覆盖成人Validator，不虚报深层港币规则。
- Snapshot与源码发布共享系统事务锁，stale历史Case不阻塞新scan；Oracle轮询设半秒下限与最大尝试次数。
- OCR delegation初审8 High/11 Medium及唯一复审新增2 High/6 Medium均已接受并修复，无拒绝或仲裁项。
- FastAPI、HTTPX、PyMySQL和Redis驱动已安装到当前Python环境，`pip check`无破损依赖。
- FastAPI TestClient与V2控制台HTTP契约测试通过；完整V2测试已包含API路由验证。
- 已归档foundation、源码扫描、知识生成、场景生成和API/控制台5个完成change；主规格已同步到 `openspec/specs/`。
- 完成Booking.Core安全Oracle控制面：源码发现2个MySQL、2个TiDB、1个Redis、8个MQ Consumer和11个MQ Producer，页面统一展示资源状态和批准操作数。
- 完成Java 8 QA Worker源码：固定QA身份、DAL READ池硬门禁、Cache只读命令、0600文件协议、15个operation/resource绑定和敏感错误脱敏。
- `order.items_by_transaction` 通过OPSI安全关联乘客类型，支持成人/儿童逐Item价格断言且不返回乘客ID、姓名、证件或电话。
- 完成Snapshot的Worker Jar与Oracle目录摘要绑定，Python生产Oracle链不再直接读取Booking.Core数据库或Redis连接密码。
- 完成回归Suite、资源证据状态、全局Job影响预估与五分钟一次性确认Token门禁，并接入FastAPI和V2控制台。
- 按用户确认矩阵生成12类31个核心生命周期业务Case；当前31项全部为 `blocked`，缺少Fixture或业务口径时不会绿色假通过。
- 增加31项资产闭合测试；首条EBK金丝雀补强后共校验91个Oracle步骤、5个Job门禁、MQ `EFFECT_ONLY` 和公开目录安全边界。
- 修复核心生命周期OCR delegation初审的5个High与3个Medium：默认Suite现可由生产Reader严格加载，31个custom Case可编译为ScenarioVariant，5个Job绑定Snapshot工具事实，空断言和非QA单Case在执行前拒绝，资源证据绑定真实步骤与断言摘要，Worker环境改为允许列表且POM使用稳定版本。
- 完成同一只读代理的唯一修复后OCR delegation复审；初审5个High与3个Medium全部闭合，复审无新增High、Medium或Low，审查未修改文件且未访问QA。
- 修复Java Worker正式Oracle目录测试的资产定位：Maven模块改为读取Git知识库唯一真相源，不复制第二份目录且不放宽生产路径安全校验；本次精确补丁OCR delegation审查无High、Medium或Low。
- Java Worker已完成完整离线Maven验证与打包：40个JUnit全部通过，生成 `workers/qa-oracle-worker/target/opentest-qa-oracle-worker.jar`；后续依赖未变化时使用 `mvn -o`，无需访问Nexus或写入新的依赖缓存。
- 修复公司SDK静态初始化错误的稳定响应边界：只捕获 `LinkageError` 并返回 `RESOURCE_PROVIDER_UNAVAILABLE`，不捕获JVM其他致命错误，也不返回远程配置异常。
- 完成该稳定错误边界的OCR delegation独立审查；High、Medium、Low均为0，审查未修改文件且未访问QA。
- 创建绑定修复后Worker Jar、Oracle目录、当前源码、知识、Case、真实工具与Skill的Snapshot `snapshot-e2d6a1e5d432eb38f0afd2cc`。
- 用户本机OpenTest服务已在 `127.0.0.1:8788` 启动，实际页面验收覆盖资源面板、Oracle目录、自然语言编译、Snapshot和Suite报告。
- 页面真实探测24项资源：订单主库、临时库和Redis为 `CONNECTED`；两个TiDB均因 `READ_POOL_UNAVAILABLE` 保持 `BLOCKED`；19项MQ按源码发现展示且效果证据文案为 `EFFECT_ONLY`。
- 修复两份生命周期知识的非法 `mixed/flow` frontmatter，生产 `GitKnowledgeStore.list_nodes()` 可完整解析全部知识；自然语言港币多乘客场景恢复为 `needs_input` 并返回18项明确缺失条件。
- 创建当前页面Snapshot `snapshot-f90421b5402fb1bd8c3888b7`，已绑定当前源码、知识、31个Case、真实工具、Worker Jar、Oracle目录和Skill摘要。
- 页面提交核心Suite得到 `0 passed / 0 failed / 31 blocked`，所有变体无业务 `run_id`，确认门禁未触发DSF或全局Job。
- 在Git忽略目录创建安全 `qa.yaml` 骨架，只保存Labrador环境变量引用与空Fixture结构，不包含Token、身份、Host、账号或密码。
- 生命周期知识契约补丁完成OCR delegation初审和唯一复审；接受并修复1个Medium，复审无High、Medium或Low。
- 完成首条境内EBK金丝雀可执行契约：真实创单响应、`TICKETING(5)`中间态、同步实时分单临时库0行、出票回填响应、`ISSUE_SUCCESS(6)`终态、逐乘客Item无序匹配、Redis稳定Key和MQ `EFFECT_ONLY` 均有独立断言。
- 执行内核支持响应 `assert` 步骤和 `request_base + request_overrides` 安全合成；所有动作字段严格互斥，空工具执行、夹带配置和歧义请求封装会在真实DSF调用前拒绝。
- 逐乘客Item断言改为二分图一对一匹配，支持重复业务行以及宽泛/具体期望候选重叠，不依赖SQL返回顺序。
- 首条金丝雀的外部清理键改为引用真实创单输出HT，不再要求Fixture预填不存在的订单号。
- 本轮OCR delegation初审发现2个Medium、唯一复审发现1个Medium，全部接受并修复；最终无遗留High/Medium、无拒绝或仲裁项，审查代理未修改文件且未访问QA或密钥。
- 远程审批恢复后重新执行完整本地门禁：V2 `131 passed`、legacy `43 passed`、Worker `40 passed`，OpenSpec strict、compileall和diff检查通过。
- 重新提交24项QA只读探测任务 `task-9c4d0d8ad319466d`：订单主库、临时库和Redis当前为 `CONNECTED`；两个TiDB仍为 `BLOCKED / READ_POOL_UNAVAILABLE`；MQ保持源码发现和 `EFFECT_ONLY` 边界。
- 创建最终内容绑定Snapshot `snapshot-c3a234935513e2d9452accbb`，绑定当前源码基线、知识、31个Case、真实工具、最新Worker Jar、Oracle目录和Skill摘要。
- 完成通用深层知识追踪：Facade、Job、MQ Listener、状态Actor、Event Listener和共享公共逻辑均生成源码可证明草稿；`TradeFacade#createOrder`专用深层知识未退化。
- 完成知识可信闭环：后台串行生成、最小权限本地Agent增强、集中去重问题、答案传播、开放High/Medium问题发布门禁、人工确认发布和SQLite索引重建。
- 完成回归Case三阶段流程：场景矩阵草稿、人工确认、Case与执行步骤；非createOrder入口和缺少Fixture/结果校验能力的场景明确保持`BLOCKED`，31个人工Booking.Core Case未被覆盖。
- 完成自然语言业务流程：业务描述生成唯一不可变预览、业务表单答案写回结构化约束、确认前不探测QA或创单、按当前系统结果校验能力解析资源、执行后可保存Git长期回归Case。
- 完成V2控制台知识树、Case树、自然语言预览和动态帮助交互；浏览器验收确认90个Facade、36个Job、19条状态流转、单MQ集群、结果校验能力抽屉和390×844移动布局。
- 完成`generalized-knowledge-case-and-natural-language-workflow` OCR delegation：初审4 High/1 Medium与唯一复审新增1 Medium全部接受并修复，无拒绝、仲裁或遗留High/Medium。
- 已严格校验并归档`generalized-knowledge-case-and-natural-language-workflow`，同步新增`confirmed-case-generation`、`generalized-knowledge-workflow`和`natural-language-test-workflow`三份主规格。
- 完成多系统注册表合并更新和系统内资产隔离；更新一个系统不会重写其他系统。
- 完成可恢复系统归档与恢复：公开知识和本地派生资产分别归档，清单记录大小与SHA-256，恢复前校验冲突并重建SQLite。
- 当前混合 `train-booking-core` 已归档为 `archive-20260813T053636-c4e3533e`，613个文件摘要全部复验通过，本地清单权限为0600；活动系统列表和SQLite索引已清空，未永久删除资产。
- 本机scriptgen路径已保存到Git忽略的 `.opentest/settings.yaml`，动态启动诊断为 `READY / local_settings`；扫描提交前门禁不再依赖Uvicorn启动时环境变量。
- 完成本地QA网关前缀、不含Token的Facade Curl结构API，以及跨进程全局排他长任务和页面刷新活动状态API。
- 系统接入改为“先占用全局门禁、再发布配置与任务”的可回滚事务；扫描冲突或线程池提交失败不会留下半注册、半更新或本地设置漂移。
- 成功扫描Manifest固化数据库、Redis与MQ资源事实；资源主表不再读取尚未成功扫描的工作区改动，旧Manifest和未扫描系统保留安全兼容行为。
- 控制台系统切换增加请求代次与显式系统作用域，旧系统异步响应不会覆盖当前Token、扫描、资源或问题状态；Facade Curl对Token、JSON与URL使用POSIX单引号安全包装。
- 完成多系统可靠性唯一复审收口：已有QA配置使用UTF-8原文快照精确恢复，回滚自身失败不再掩盖提交根因或泄漏全局锁，Booking校验目录安装失败不会遗留孤儿系统，同ID可以安全重试。
- 重扫、扫描目录和Facade Curl的成功/失败回写均绑定请求系统代次；切换系统后迟到响应不会污染新系统页面。
- 已严格校验并归档`multi-system-console-reliability-and-reset`，混合数据归档`archive-20260813T053636-c4e3533e`保持613个文件可验证恢复，活动系统列表为空。
- 完成知识访谈和修订闭环：项目背景、上下游、分单关系和术语可集中维护，答案传播到受影响草稿；用户反馈先形成问题、影响清单和前后差异，人工确认后才发布Git知识并重建索引。
- 自然语言缺少确认知识时返回带扫描、生成知识和回答问题入口的`BLOCKED`预览，确认前不读取Fixture、不探测资源且不创建订单。
- 完成Booking.Core `TradeFacade#createOrder` MVP本地Fixture、Snapshot摘要和排他执行编排；完整请求只写Git忽略0600文件，API、任务和报告只返回安全摘要。
- MVP固定校验真实DSF响应、MySQL主库、临时收单库、逐乘客Item和Redis；异步票机仅在明确观察到从空到有时记录MQ `EFFECT_ONLY`，TiDB保持`BLOCKED`。
- Worker Jar或结果校验目录缺失时，MVP计划会在构造DSF客户端前保持`BLOCKED`，避免创建订单后才发现无法完成业务断言。
- 完成知识与createOrder MVP的OCR delegation独立审查：初审1 High/3 Medium、唯一复审1 Medium全部接受并修复；Fixture非法JSON不再回显输入，无效乘客或跨系统历史Fixture均在QA前转为可恢复`BLOCKED`，知识访谈与修订状态机不会截断人工内容或接受重复回答。
- 修复普通DSF扫描未使用系统本地QA网关的问题：显式扫描前缀优先，否则动态读取当前系统`qa_gateway_prefix`；Labrador Token不会进入扫描请求、任务、Manifest或scriptgen参数。
- 修复扫描失败后的错误反馈链：失败或中断终态会停止扫描历史和Manifest读取，保存或重扫只有在任务完成且目录加载成功后才显示成功提示。
- 对退款系统`ifightchainsaas.java.refund.core`完成不访问QA的真实源码重扫：34个Facade均生成可用真实工具，`CallbackFacade#refundApplyCallback`已恢复，扫描Manifest包含1个状态机。
- 收紧Facade网关基础URL校验：畸形IPv6、非法端口、userinfo、query、fragment和空白均在scriptgen启动前转换为稳定领域错误。
- 完成系统专属知识发现：上下文、业务术语、外部应用、统一问题和人工答案按`system_id`隔离保存，增量重扫保留人工含义并把变化项标记为待复核、消失项标记为过期。
- 退款系统真实本地发现得到18个活跃候选（12个业务术语、6个外部应用）和19个开放问题；通用页面不再加载港币、EBK、票机、收单、HT或createOrder专属输入。
- 完成知识目标工作区和统一进度契约：Facade按类/方法分层，点击叶子加载证据、草稿、正文、问题与反馈；扫描、知识、资源、Case、执行和索引任务均可持久化并恢复真实阶段与处理数量。
- 完成侧边栏左侧收起/恢复、桌面端和390×844移动端验收；浏览器无横向溢出或控制台错误，本轮未访问QA。
- 完成系统专属知识Change的OCR delegation审查：初审2个Medium均接受修复，唯一复审确认全部闭合且无新增High/Medium/Low；Java符号链接不能逃逸源码根，进度越界返回稳定领域异常。
- 完成独立Java 8 DSFProxy Worker、DSF客户端Profile/provider操作发现、全局操作索引、调用系统确认绑定、0600只读金丝雀Fixture和脱敏执行API；写操作与非QA环境继续在Worker启动前阻断。
- Snapshot已绑定调用方扫描、Profile、确认allowlist、跨系统provider定义和DSF Worker字节；历史扫描不再混入latest Profile，纯consumer也不会漏记Worker版本。
- 完成JavaParser + Symbol Solver本地语义Sidecar与可替换Python端口；公共逻辑共享节点带真实入口`CALLS`边，状态枚举支持`name/desc/description`字段及getter真实绑定。
- 知识页已改为目录、当前知识、常驻问题三栏；中栏只读展示已确定知识和修订式聊天，所有开放问题及精确变更提案统一进入右栏，问题完整性由持久化周期管理。
- Booking.Core与Refund.Core本地Spike达到调用边召回率1.0、模式精确率1.0、22条人工调用边全中、Refund状态标签全中，111个高置信模式无意外误报。
- 将知识访谈改为持久化问题周期：当前分析发现的全部开放问题一次展示，单题只暂存，全部填写并显式完成后才统一应用人工答案和启动本地重算；支持刷新恢复、stale冲突、重复完成幂等与任务失败重试。
- 唯一高置信枚举映射自动以`CODE_VERIFIED`吸收，和`USER_CONFIRMED`严格分离；Java语义协议升级为schema 3并输出类型/常量Javadoc及直接领域字段关系，技术依赖不再冒充核心业务对象。
- 原Refund.Core周期`question-cycle-acfb5c9fdfff420f`使用既有29项答案幂等恢复成功：原失败任务`task-5f7712d5bc324d9c`保留，新任务`task-3acd419161364532`完成，最终进度消息为`剩余问题 0，已知未知 0`。
- 完成Refund.Core新版本地只读重扫，发布Manifest `scan-20260822121007-6b0d5d1222-8ade0ea6`：39个入口、39个工具、1个状态机和73个候选；扫描任务为`task-df330e7782044fbe`。
- 业务枚举从普通术语拆为独立目录；原15个缺名和82个未解析值问题所在周期`question-cycle-12056ee6a75d4fbc`已安全转为`STALE`，没有丢失历史审计。
- 枚举现在按“常量Javadoc → 唯一高置信构造描述 → 稳定常量名”形成可人工修订默认知识；Refund.Core 36个业务枚举全部进入目录，当前周期`question-cycle-632f4bd1533445ca`保持`0/0 OPEN`。
- `OrderLockEnum`已按用户确认显示为“退票单锁单类型”，名称来源为`USER_CONFIRMED`；`LOCK → 锁定`和`UN_LOCK → 未锁定`继续保持`CODE_VERIFIED`，没有笼统升级整份枚举来源。
- 枚举详情支持从业务背景、接口、公共逻辑和左栏直选返回来源，恢复聊天作用域、问题筛选和移动抽屉；系统变化清栈，同系统刷新重基有效返回栈代次。
- 完成问答Tab与中栏只读聊天改造的OCR delegation：初审4 High/5 Medium、唯一复审新增1 High/2 Medium，全部接受并修复；闭合证据规范化、服务端真实diff、写目标冲突、任务竞态、0700/0600权限、迟到响应、跨会话精确快照、部分发布stale和索引恢复，无拒绝或仲裁项。
- 完成本轮业务枚举与重算恢复OCR delegation：初审0 High/5 Medium全部接受并修复；唯一复审确认原问题闭合并发现1个Medium，同样接受。复审代理违反只读约束直接修改`app.js`和对应契约测试，主流程已独立检查并保留正确修复；未开启第三轮审查，无拒绝或仲裁项。
- 完成枚举默认知识策略OCR delegation：初审1 High/2 Medium/1 Low，全部接受并修复；唯一复审确认原问题闭合并发现1个一对多匹配Medium，改为完整匹配图后闭合。按两轮上限未开启第三轮，无拒绝或仲裁项，代理全程只读。
- 补齐最低底线知识生成SOP：背景问题归零后，顶部与右栏统一显示“生成全部接口与公共逻辑知识”及准确目标数；批量入口固定禁用Agent/QA，确定性代码事实自动发布，业务缺口进入右栏，整轮确认后自动收敛为人工知识，稳定历史答案在重复生成时继续复用。
- 修复Refund.Core批量知识生成在`OuterRefundFacadeImpl#pageBusinessLog`中断的问题：方法体定位跳过`@Indicator`同名参数和数组花括号；仅能证明入口存在的目标发布最小代码事实并进入右栏确认，页面失败后保留常驻摘要和错误Toast。
- 完成本轮OCR delegation两轮只读审查：接受并修复多批次答案传播、人工正文保护、背景门禁、周期刷新和新增人工口径安全追加等合理High/Medium，修正文案Low；撤销已由`write_questions`合并契约覆盖的问题丢失误报，并按用户最新口径拒绝恢复97项枚举问题，无遗留High/Medium。
- 完成知识库四步SOP：四项核心背景首次确认后永久完成且仍可编辑；背景和术语显式保存后只标记知识过期，不自动调用Agent或产生费用。
- 知识生成改为全局显式选择Codex或Claude Code，请求和任务全程记录实际Agent，提交前展示当前对象与费用确认；两种Agent互不兜底，单目标Agent失败保留代码事实。
- 页面暂时下掉“生成全部”，旧批量契约只兼容一个目标；Codex JSONL与Claude Code stream-json由独立工作进程持续落盘，关闭stdin且不设固定分析超时，SSE断线只续传事件而不重复调用。
- 服务优雅重启只分离当前观察线程，独立Agent继续形成事件和证据，由新服务无费用接管；供应商大结果保留完整私有输出，页面仅接收有界公开事件，高频Claude增量会合并后推送。
- 重叠服务启动通过持久handoff标记、孤儿付费任务门禁和所有权心跳协调恢复；知识聊天没有接管实现，因此关闭服务时不会错误分离共享Runner。
- Agent续跑必须绑定首次等待时的固定问题周期及摘要，只有该周期完成后才能再次确认费用；续跑中断会保留原问题来源和最近会话检查点，不会因运行ID变化丢失人工答案。
- Agent需要高影响答案时先发布代码事实并进入`WAITING_FOR_INPUT`；用户完成问题周期并再次确认费用后只续接原thread/session，人工答案与Agent解释继续分别保持`USER_CONFIRMED`和`INFERRED`。
- 移除固定业务口径问题，右栏只保留代码和背景仍无法判断的高影响疑点；目录区分已生成、仅代码事实、待确认、已确认、已过期和失败，并增加全部问题入口与对象范围自动切换。
- 知识页增加四步流程条、全范围Loading、持久化任务恢复和轻量详情；修复状态机父目标重复、旧摘要误判过期及热态详情重复加载问题。
- 修复Codex严格结构化输出：动态摘要Map改为全字段必填的摘要数组和最小源码引用，Codex/Claude共用启动前本地Schema预检，无效Schema不会启动Agent或产生费用。
- Agent失败且代码事实已保存时任务明确显示`partial`和独立失败计数；历史误记completed的安全错误任务只读投影为部分完成，页面刷新恢复原任务并禁用重复生成。
- 本轮OCR delegation初审发现3 High/4 Medium，唯一复审发现2 High/2 Medium，全部接受并修复；覆盖私有完整结果、旧入口费用确认、服务关闭边界、恢复会话、续传性能和重叠服务接管，无拒绝或仲裁项，按两轮上限不再启动第三轮。

## 进行中任务

- `dsf-execution-and-oracles`处于`WAITING_QA_INPUT`，任务5.4保持未完成且不归档；等待Fixture与TiDB READ池期间不视为正在编码的核心change。
- `semantic-knowledge-workspace`单目标流式改造已完成源码、桌面/移动验收、完整离线门禁和两轮OCR delegation；Refund.Core仍为39个接口和59个公共逻辑/状态目标，全局Agent未选择，本轮未提交任何真实生成任务。
- `dsf-proxy-execution-and-agent-tools`除全量Facade切换、两个真实只读金丝雀和金丝雀后的Labrador移除外均已完成；当前不会自动确认操作或访问QA。

## 待开始任务

- 对Booking.Core与Refund.Core完成一次本地重扫后，在页面核对新发现的Profile和固定操作候选。
- 两个只读DSF金丝雀都成功后才切换Facade工具并移除Labrador；之后仍只执行一项经确认的createOrder写金丝雀，不运行31个Case。

## 阻塞项

- Booking.Core活动Manifest仍生成于DSF Profile扫描能力接入前，页面安全显示`Profile缺失`；Refund.Core已完成新基线只读重扫，后续问题周期固定复用该Manifest。
- 尚未在本地0600 Fixture页填写有效Booking HT/TX/merchant，以及一笔存在退票记录的原订单号；这些值不得进入聊天、Git、Snapshot、日志或报告。
- createOrder写金丝雀仍缺一份可成功完整请求、预期EBK供应商/票机模式、清理策略及DSF/MySQL/TiDB/Redis/MQ业务Oracle。
- Git忽略的 `qa.yaml` 安全骨架已创建，但31组 `values.fixtures` 仍为空；共130个路径已记录在 `docs/development/qa-fixture-checklist.md`，当前不会猜测或自动拼装请求。
- 首条EBK金丝雀已写入可由源码证明的逐响应和逐Oracle断言；其余30个custom Case仍缺经业务确认的非空断言，空断言门禁会阻止执行或假绿。
- 5个含Job工具的Case所对应扫描脚本仍绑定 `test` 地址；完成QA重扫或显式QA重绑前禁止执行。
- 全局Job影响Oracle和隔离口径尚未确认，因此不能签发一次性确认Token。
- TiDB不再作为DSFProxy整体前置阻塞；只在用户单独确认后复测Booking.Core两个已扫描TiDB的`READ + switchToReadDB()`路径，Refund.Core不探测数据源，且永不回退WRITE池。

## 最近验证结果

- 2026-08-23：知识Agent受控全路径扫描与会话诊断最终门禁通过：V2 `368 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `11 tests / 0 failures`、OpenSpec strict `32 passed / 0 failed`；compileall、Node语法、`pip check`和diff检查通过。Codex/Claude均只开放OpenTest注册源码读取MCP，文件名/目录名的QA、Fixture、测试及大写缩写变体被拒绝，疑似认证赋值脱敏，搜索为线性字面量且逐级`O_NOFOLLOW`打开；所有Agent引用与行号必须落在实际`read_source`区间。Facade严格`trace_steps`要求`entry → 可选invoker → service → data_access/remote_boundary`，仅到Invoker的回归被拒绝，读取Service与DAO后才允许完成。页面可回看精确Prompt、公开推理摘要/消息、源码访问、最终输出、会话ID和手动resume命令，过大输出显式标记截断且不展示隐藏思维链。OCR delegation初审`2 High / 3 Medium / 2 Low`、唯一复审`1 High / 1 Medium`，全部修复；按两轮上限由主流程完成最终结构化路径与大写缩写边界自检。桌面与390×844诊断布局已在本轮前段真实浏览器通过，最终布局未变且本地console DOM再次只读验证。未运行真实Agent，未访问项目QA、Fixture正文、DSF、写接口或31个生命周期Case，Refund.Core历史`queryList`知识未自动重生成。
- 2026-08-23：Codex严格Schema、部分失败和刷新恢复修复最终门禁通过：V2 `361 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `11 tests / 0 failures`、OpenSpec strict `32 passed / 0 failed`；compileall、Node语法、`pip check`和diff检查通过。无网络假CLI覆盖全字段必填Schema、无副作用预检、重启后非法信封降级、`partial`计数、历史投影、SSE终止及重复POST `409 / Runner调用1次`；桌面与390×844只读页面均显示历史任务`partial · 仅代码事实1 · Agent失败1 · 确定性失败0`且无横向溢出。OCR delegation初审`0 High / 2 Medium / 2 Low`，唯一复审`0 High / 0 Medium / 2 Low`；初审项全部闭合，复审两项低风险页面竞态由主流程修复并完成最终自检。未运行真实Agent，未访问QA、Fixture正文、DSF、写接口或31个生命周期Case。
- 2026-08-23：单目标知识生成与AI流式进度最终门禁通过：V2 `351 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `11 tests / 0 failures`、OpenSpec strict `32 passed / 0 failed`；compileall、Node语法、`pip check`和diff检查通过。桌面与390×844页面验收通过，未运行真实Agent，未访问QA、Fixture正文、DSF、写接口或31个生命周期Case。
- 2026-08-23：知识目录Facade层级与误确认状态修复完成：左栏按Facade类名分组后展示方法叶子；`RefundDistributionFacade#queryList`已从误标的人工确认一致恢复为仅代码事实，历史问题为open且答案为空。真实页面验收通过；V2 `337 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar成功打包、OpenSpec strict `32 passed / 0 failed`，compileall、Node语法、`pip check`和diff检查通过。OCR delegation本轮`0 High / 0 Medium / 0 Low`，审查代理全程只读。
- 2026-08-23：知识库四步流程最终门禁通过：V2 `336 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `11 tests / 0 failures`并成功打包；OpenSpec strict `32 passed / 0 failed`、compileall、Node语法和`pip check`通过。
- 2026-08-23：本任务OCR delegation初审发现3 High/4 Medium/1 Low；接受并修复人工知识刷新、Agent执行级源码边界、聊天费用确认、旧入口绕过、历史疑点、对象切换竞态、长任务轮询和接口说明问题。唯一复审确认6项闭合并指出1 High/1 Medium及Codex MCP残余边界，随后按两轮上限由主流程清空MCP与hooks、修复新增答案和证据元数据刷新，并以定向及完整V2回归闭合；无拒绝或仲裁项，审查代理全程只读。
- 2026-08-23：知识Agent不再自行浏览工程：应用只提供确定性追踪引用附近、根内校验且总量受限的源码窗口；Codex与Claude Code均关闭文件、命令、浏览器、MCP和扩展工具，OpenTest不读取、记录或展示认证凭据。
- 2026-08-23：Refund.Core热态轻量详情连续实测约`1.24–1.27秒 / 4,841字节`，持久化问题周期读取约`3–4毫秒`；切换对象后50毫秒采样点已出现可见Loading。页面目标严格保持39个接口和59个公共逻辑/状态目标，未再重复投影状态机子节点。
- 2026-08-23：桌面与390×844真实页面验收通过：四步流程条、当前Agent、全部问题入口、当前对象范围和移动双抽屉均可用，页面无横向溢出或控制台warning/error；全局Agent保持未选择，未提交98项生成任务，未访问QA、Fixture正文、DSF、写接口或31个生命周期Case。
- 2026-08-23：批量知识生成热修最终门禁通过：V2 `329 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `11 tests / 0 failures`并成功打包；OpenSpec strict `32 passed / 0 failed`、compileall、Node语法、`pip check`和 staged/unstaged diff检查均通过。19个本任务新增/修改Python方法均有文档注释，显式参数超过5个为0。
- 2026-08-23：OCR delegation初审发现2 High/2 Medium/1 Low，全部接受并修复；唯一复审确认初审项闭合后新增1 High（`>`表达式调用与泛型返回类型混淆），已接受并通过声明深度门禁及Lambda/比较/显式泛型调用回归修复。按两轮上限不再启动第三轮，主流程完成最终diff自检和全量回归；无拒绝或仲裁项，审查代理只读且未修改文件。
- 2026-08-23：批量知识生成热修逐项目标验证通过：当前Refund.Core 98个目标只读追踪为`98成功 / 0失败`，其中10项按最小代码事实边界处理；`pageBusinessLog`恢复识别两个真实返回阶段且证据定位到真实声明第59行。完整离线门禁与审查修复后的最终计数见本节最新记录。
- 2026-08-22：本轮未实际提交98项目标写入任务，未访问Agent、QA、Fixture、DSF、退票写接口或31个生命周期Case；修复发布后可直接在页面重试“生成全部接口与公共逻辑知识”。
- 2026-08-22：最低底线知识生成SOP门禁通过：V2 `321 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar测试及打包成功；OpenSpec strict `32 passed / 0 failed`、compileall、Node语法、`pip check`和 staged/unstaged diff检查均通过。
- 2026-08-22：Refund.Core桌面与390×844真实页面显示“生成全部接口与公共逻辑知识（98）”；移动端问题抽屉入口可见可用，业务背景显示“背景已确认”。验收未点击生成，因此没有运行98项目标、Agent、QA、DSF或业务写接口。
- 2026-08-22：审查修复后，同一稳定问题会传播到全部历史批次；重复生成不覆盖既有`USER_CONFIRMED`正文，新周期明确答案可在保留旧自动区与人工区的前提下安全追加；周期成功后使用真实`loadKnowledgeInterview`刷新背景门禁。
- 2026-08-22：枚举默认知识策略最终门禁通过：V2 `320 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar测试及打包成功；OpenSpec strict `32 passed / 0 failed`、compileall、Node语法、`pip check`和 staged/unstaged diff检查均通过。
- 2026-08-22：Refund.Core复用原Manifest完成确定性投影，没有重新扫描源码；36个业务枚举全部可见，旧97题周期转为`STALE`，当前周期为`question-cycle-632f4bd1533445ca`且问题数为0。`OrderLockEnum`人工名称继续保持`USER_CONFIRMED`。
- 2026-08-22：人工单值覆盖重扫保护已补强：候选不会回退为纯代码状态，同名类型冲突出现或消失时按全限定源码符号迁移；非法或缺失值级代码证据在落盘前被拒绝。
- 2026-08-22：本地重算恢复与业务枚举目录最终门禁通过：V2 `313 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `10 tests / 0 failures`并成功打包；OpenSpec strict `32 passed / 0 failed`、compileall、Node语法、`pip check`和 staged/unstaged diff检查均通过。
- 2026-08-22：Refund.Core原29项答案未丢失且恢复完成；新版Manifest为`scan-20260822121007-6b0d5d1222-8ade0ea6`，页面显示21个已命名业务枚举和97个新缺口。`OrderLockEnum`显示“退票单锁单类型”，名称与两个值的人工/代码来源严格分离。
- 2026-08-22：桌面与390×844真实页面验收通过：背景摘要不再混入枚举长列表，`RefundFacade#createOrder`展示相关业务枚举，来源返回会恢复聊天、问题范围和移动抽屉；页面及两个抽屉横向溢出为0，浏览器console error/warning为0。
- 2026-08-22：本轮OCR delegation初审0 High/5 Medium、唯一复审新增1 Medium，全部接受并闭合；无遗留或拒绝High/Medium。复审代理意外写入的两处最小修复已由主流程检查并通过完整回归。
- 2026-08-22：全程未访问QA、未读取Fixture正文、未运行本地知识Agent、DSF金丝雀、退票/createOrder写接口或31个生命周期Case，也未完成当前0题周期。
- 2026-08-21：问答Tab与中栏只读聊天最终门禁通过：会话定向 `23 passed`、V2 `293 passed / 1 skipped`、legacy `43 passed`、Java语义Sidecar `8 passed`并成功打包；OpenSpec strict、compileall、Node语法、`pip check`和 staged/unstaged diff检查均通过。
- 2026-08-21：Refund.Core桌面与390×844实际页面验收通过：7/29暂存答案跨刷新恢复，22个缺答使完成按钮保持禁用，移动问题抽屉无横向溢出，浏览器error为0。
- 2026-08-21：本阶段未访问QA、未执行DSF金丝雀、createOrder/退票写接口或31个生命周期Case，也未读取Fixture正文。首次使用修复前旧页面时只请求过本地Fixture安全摘要端点；随后已移除知识页默认初始化读取，响应不含请求正文或敏感值。
- 2026-08-20：最终本地门禁通过：V2 `251 passed / 1 skipped`、legacy `43 passed`，Java语义、DSF Worker和Oracle Worker三个模块均离线`test package`成功；OpenSpec strict `32 passed / 0 failed`，compileall、Node语法、`pip check`和diff检查通过。
- 2026-08-20：OCR delegation初审发现4 High/7 Medium/1 Low，唯一复审发现1 High/4 Medium，全部接受并修复；历史Snapshot、共享语义调用边、背景访谈阶段门禁、枚举getter绑定及Spike误报门禁均闭合，无拒绝或仲裁项。
- 2026-08-20：最终主代理完整diff复核未发现遗留High/Medium；审查和修复均未访问QA、Fixture正文、Token或31个Case。
- 2026-08-20：实际浏览器验收桌面三栏为`270px / 461px / 350px`，中栏问题卡为0，全部/当前对象问题切换为`6 / 3`；390×844目录与问题抽屉互斥，页面及三栏横向溢出为0，控制台warning/error为0。
- 2026-08-13：系统专属知识与任务进度最终门禁通过：定向`16 passed`、V2 `218 passed / 1 skipped`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；OpenSpec strict、compileall、Node语法、`pip check`和diff检查通过。
- 2026-08-13：本轮OCR delegation初审发现2个Medium并全部接受修复，唯一复审确认符号链接源码逃逸和进度异常类型问题均闭合，无新增High/Medium/Low；审查代理只读且未访问QA、Token、Fixture或网络。
- 2026-08-13：真实退款系统本地发现得到18个活跃候选（12个术语、6个外部应用）和19个开放问题；所有活跃外部应用均绑定受影响入口，证据行号落在真实源码范围，`POST`和`UTF`已按增量规则标记为`STALE`。
- 2026-08-13：桌面端与390×844浏览器验收通过：退款Facade三级目录、叶子详情、问题红点和侧栏收起恢复正常，浏览器warning/error为0；只调用本地GET接口，未访问QA。
- 2026-08-13：DSF扫描网关与反馈热修最终门禁通过：定向`42 passed`、V2 `201 passed / 1 skipped`、legacy `43 passed`、Worker `45 passed`且Maven `BUILD SUCCESS`；OpenSpec strict、compileall、Node语法和diff检查通过。
- 2026-08-13：本轮OCR delegation初审发现1个Medium并接受修复，唯一复审确认原问题闭合且High/Medium/Low均为0；审查代理只读，未访问QA、Token或Fixture。
- 2026-08-13：退款系统真实本地重扫任务`task-23ec7bdb3dd3467b`完成，发布`scan-20260813090627-9d02e3d62a-5c2117d5`：34个Facade、34个ready工具、1个状态机；未访问QA。项目缺少`JobTypeEnum.java`，因此0个Job并保留独立`JOB_TYPE_ENUM_MISSING`提示。
- 2026-08-13：严格校验后归档`knowledge-interview-and-create-order-mvp`，新增并同步`create-order-mvp`、`knowledge-interview-and-revision`和`natural-language-blocked-guidance`三份主规格。
- 2026-08-13：知识访谈与createOrder MVP最终门禁通过：定向 `23 passed`、V2 `192 passed / 1 skipped`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；OpenSpec strict、compileall、Node语法和diff检查通过，全程未访问QA。
- 2026-08-13：本轮OCR delegation初审发现1 High/3 Medium，唯一复审新增1 Medium，全部接受并修复；无拒绝或仲裁项，审查代理只读且未访问QA、Token或Fixture正文。
- 2026-08-13：知识访谈与createOrder MVP本地门禁通过：V2 `180 passed / 1 skipped`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；OpenSpec strict、compileall、Node语法和diff检查通过。
- 2026-08-13：MVP前置校验补强定向测试 `12 passed`；Worker Jar或校验目录缺失时计划在DSF前阻塞，未访问QA或创建订单。
- 2026-08-13：当前代码浏览器验收通过：空系统引导、知识访谈/修订、MVP Fixture区、28个帮助提示和自然语言业务化阻塞文案正常，MVP执行按钮保持禁用，浏览器warning/error为0；未提交表单或访问QA。

- 2026-08-13：多系统可靠性唯一复审发现2 High/4 Medium，全部接受并修复：本地设置快照类型、回滚异常锁释放、Booking固定目录孤儿、重扫未声明作用域、扫描目录和Curl迟到失败覆盖；无拒绝或仲裁项，审查代理只读且未访问QA、Token或Fixture。
- 2026-08-13：最终门禁通过：V2 `169 passed / 1 skipped`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；compileall、Node语法、diff检查和OpenSpec strict通过。
- 2026-08-13：当前代码重启本机服务后实际浏览器验收通过：活动系统为空、scriptgen为READY，空系统表单展示4项字段错误，侧栏收起/恢复正常，浏览器warning/error为0；未访问QA或发送Curl。

- 2026-08-13：多系统可靠性OCR delegation初审发现2 High/4 Medium，全部接受并修复：接入半状态、跨系统异步回写、归档预览/Run缺口、活动摘要发布窗口、资源绕过成功扫描边界、Curl shell转义；无拒绝或仲裁项。
- 2026-08-13：审查修复后的完整门禁通过：V2 `165 passed / 1 skipped`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；compileall、Node语法、注释AST检查、diff检查和OpenSpec strict通过。
- 2026-08-13：审查修复后重启本机服务并实际浏览器复验，活动系统仍为空、归档`613 + 1`摘要与scriptgen READY正常、无横向溢出，浏览器错误日志为空；未访问QA或执行Curl。
- 2026-08-13：多系统可靠性Change完整本地门禁通过：V2 `163 passed / 1 skipped`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；compileall、Node语法、diff检查和OpenSpec strict通过。
- 2026-08-13：最新版控制台实际浏览器验收通过：活动系统为空、归档显示`613个可恢复文件 + 1个审计元数据`、scriptgen为`READY / local_settings`、必填字段逐项提示、Toast、侧栏折叠恢复及390×844布局正常，浏览器错误日志为空；未访问QA或提交业务请求。
- 2026-08-13：真实Booking.Core只读扫描在临时知识目录得到`90 Facade / 36 Job / 5 MQ Consumer / 1状态机 / 19流转 / 126工具 / 0 warning`；注册流程已补齐QA Job规则，扫描未写入活动系统。

- 2026-08-12：通用知识与自然语言工作流最终验证通过：V2 `157 passed`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；compileall、Node语法、diff检查通过；归档后OpenSpec strict `20 passed / 0 failed`。
- 2026-08-12：通用工作流OCR delegation初审发现4 High/1 Medium，唯一复审确认原发现闭合并新增1 Medium；全部接受并修复。最终无遗留High/Medium、无拒绝或仲裁项，审查代理未修改文件、未访问QA、Token或Fixture。
- 2026-08-12：浏览器验收完成知识后台生成、90/36/19目录、MQ单集群、结果校验能力抽屉、31个人工Case保护、非createOrder阻塞原因和390×844移动布局；未发布生产知识、未读取Fixture、未触发真实DSF调用。
- 2026-08-12：引导式控制台OCR delegation初审为0 High、4 Medium、2 Low；全部接受并修复。唯一复审为0 High、1 Medium、0 Low，接受并修复符号链接路径问题；无拒绝或仲裁项，审查代理未修改文件、未访问QA或密钥。
- 2026-08-12：最终引导式控制台验证通过：V2 `143 passed`、legacy `43 passed`、Worker `45 passed`且离线Maven `BUILD SUCCESS`；compileall、Node语法、diff检查和OpenSpec strict通过。本地现有`qa.yaml`权限已收紧为`0600`。
- 2026-08-12：引导式控制台定向测试、完整V2测试和legacy测试通过：V2 `137 passed`、legacy `43 passed`；Worker新增MQ只读路由成功、无路由、异常脱敏和请求参数封闭测试后为 `45 passed`，离线Maven `BUILD SUCCESS`。
- 2026-08-12：真实Booking Manifest页面投影为90个Facade、36个Job、5个MQ Consumer、1个状态机和19条流转；19个MQ Producer/Consumer交互按 `mq.nameSrvAddress` 聚合为1个集群资源。
- 2026-08-12：新版控制台浏览器验收通过：九个左侧导航、全局与行级结果校验能力抽屉、知识树、18个可访问帮助提示、无QA JSON自然语言入口和390px移动布局均正常；未点击连接探测或触发QA业务执行，浏览器错误日志为空。

- 2026-08-11：legacy测试 `43 passed`。
- 2026-08-11：真实示例项目扫描得到90个Facade、36个Job和129个工具。
- 2026-08-11：V2与legacy非HTTP测试 `58 passed`，覆盖任务、日志、存储、索引、CLI和无索引降级。
- 2026-08-11：OCR delegation两轮审查完成；首轮2 High/5 Medium、复审1 Medium均已修复，修复后测试通过。
- 2026-08-11：V2与legacy非HTTP测试 `79 passed`，新增严格manifest、跨进程发布锁、基线回滚和CLI任务覆盖。
- 2026-08-11：V2真实扫描得到90个Facade、36个Job、5个MQ Consumer、126个真实工具和19条状态转换；固定shim为0。
- 2026-08-11：源码扫描OCR delegation两轮完成；初审3 High/5 Medium、复审3 Medium均已修复，最终真实复扫0 warning。
- 2026-08-11：知识纵向切片定向测试 `21 passed`；真实createOrder知识生成、中文搜索和关系展开通过。
- 2026-08-11：场景与知识定向测试 `10 passed`；真实知识生成5个覆盖目标和13个受约束变体。
- 2026-08-11：执行、场景与知识定向测试 `18 passed`；本地真实脚本、清理、Snapshot和Oracle轮询闭环通过。
- 2026-08-11：非HTTP完整测试 `101 passed`，其中legacy保持 `43 passed`；四个当前OpenSpec change均通过strict校验。
- 2026-08-11：真实项目最新Snapshot `snapshot-3e9ff75ba486c9e60e05bc18` 创建成功；真实QA调用等待本地配置。
- 2026-08-11：OCR delegation初审发现8 High/11 Medium，已全部接受并修复后进入唯一复审，无争议项。
- 2026-08-11：OCR delegation唯一复审新增2 High/6 Medium，全部接受并修复；无拒绝High/Medium、无仲裁项，复审代理未修改文件。
- 2026-08-11：V2非HTTP测试 `79 passed`，legacy测试 `43 passed`，合计 `122 passed`；compileall、Node语法、两个Skill和6个OpenSpec strict校验均通过。
- 2026-08-11：AST检查新建/修改函数缺失文档注释为0；仅既有 `AgentRunner._evidence` 保留6个显式参数并有私有范围例外说明。
- 2026-08-11：真实当前Case为12个非陈旧变体（8 generated、4 blocked），DTO虚构字段为0；7个历史变体为stale；最新内容绑定Snapshot为 `snapshot-7c59d0f3e194df495986a1dd`。
- 2026-08-11：当前NoAdult变体清理步骤为0且仅声明成人Validator覆盖；全部当前港币变体声明 `hk_quote_status` 数据前置条件。
- 2026-08-11：FastAPI `0.141.1`、HTTPX `0.28.1`、PyMySQL `1.2.0`、Redis `7.4.1`、Uvicorn `0.41.0` 已可用，`pip check` 报告 `No broken requirements found`。
- 2026-08-11：FastAPI/控制台定向测试 `5 passed`；完整V2测试 `83 passed`、legacy测试 `43 passed`，合计 `126 passed`。
- 2026-08-11：5个已完成OpenSpec change严格校验并归档；`dsf-execution-and-oracles` 以14/15任务保持唯一活动change。
- 2026-08-11：真实资源清单为24项：2 MySQL、2 TiDB、1 Redis、8 MQ Consumer、11 MQ Producer；因Worker Jar尚未构建，状态均为 `DISCOVERED`，未声称连接成功。
- 2026-08-11：公开Oracle目录包含15个operation/resource绑定和11个唯一operation ID；31个业务Case共88个Oracle步骤全部通过资源、参数和证据等级闭合校验。
- 2026-08-11：核心生命周期矩阵严格为12类31项，31项均保留 `blocked + missing_conditions`；5个Job Case均带QA环境、影响预估和一次性确认门禁。
- 2026-08-11：V2测试 `119 passed`，legacy测试 `43 passed`；compileall、Node语法、`pip check` 和当前OpenSpec strict校验通过。
- 2026-08-11：Java 8主源码静态编译和catalog实际加载校验通过；Maven/JUnit/package因外部执行审批服务503尚未运行，不能据此声称Worker Jar或QA资源可用。
- 2026-08-11：生产 `RegressionSuiteReader + GitCaseStore` 已闭合默认Suite的31个稳定ID，编译88个Oracle步骤并保留31个BLOCKED；5个Job目标均绑定当前扫描manifest工具事实且真实环境为 `test/test`，QA门禁会确定性拒绝。
- 2026-08-11：空断言、非QA单Case、Snapshot Job脚本/URL漂移、自定义Case扫描绑定、资源步骤证据与Worker环境白名单测试补齐；V2 `123 passed`、legacy `43 passed`，OpenSpec strict、compileall、Node语法、`pip check` 与diff检查通过。
- 2026-08-11：OCR delegation唯一复审确认初审5 High/3 Medium全部修复，无新增发现、无拒绝或仲裁项，复审未产生代码修改。
- 2026-08-11：生成安全QA Fixture清单，生产31个Case引用的31组130个路径与文档逐项闭合，缺失0、额外0；未写入任何真实身份、请求值或密钥。
- 2026-08-12：用户明确授权Maven访问公司Nexus/写入 `~/.m2` 以及OpenTest监听 `127.0.0.1:8788`；两条命令仍在启动前因外部自动审批服务503被拦截，未产生Maven、JUnit、Jar、服务监听或浏览器验收结果。
- 2026-08-12：用户本机Maven首次实际运行得到 `Tests run: 39, Failures: 0, Errors: 1`；已修复唯一错误的正式catalog路径定位。修复后OpenSpec strict、diff检查和OCR delegation精确补丁审查通过，尚待本机重跑Maven确认39项全通过并生成Jar。
- 2026-08-12：本机依赖缓存就绪后，Codex在沙箱内执行 `mvn -o -f workers/qa-oracle-worker/pom.xml test package` 成功；`Tests run: 39, Failures: 0, Errors: 0`，fat Jar打包完成。以后仅新增或升级依赖时需要联网Nexus审批。
- 2026-08-12：最新修复后Snapshot为 `snapshot-e2d6a1e5d432eb38f0afd2cc`；沙箱单资源复测稳定返回 `RESOURCE_PROVIDER_UNAVAILABLE`，未再退化为 `QA_WORKER_EXIT_1`，但真实连接状态仍需在用户本机公司网络下探测。
- 2026-08-12：用户本机页面实际探测订单主库、临时库和Redis为 `CONNECTED`；两个TiDB均为 `BLOCKED / READ_POOL_UNAVAILABLE`，未回退WRITE。
- 2026-08-12：生命周期知识生产读取回归修复后，定向测试 `6 passed`、V2测试 `124 passed`、legacy测试 `43 passed`、OpenSpec strict和diff检查通过。
- 2026-08-12：自然语言港币成人儿童多乘客场景实际返回 `needs_input + 18 missing_conditions`；页面创建Snapshot `snapshot-f90421b5402fb1bd8c3888b7`。
- 2026-08-12：核心Suite页面报告 `BLOCKED`，31项全部保留阻塞身份，`passed=0`、`failed=0`、`blocked=31`，没有业务执行或虚假绿色结果。
- 2026-08-12：生命周期知识契约OCR delegation初审发现1个Medium并已修复，唯一复审无新增High、Medium或Low，审查未修改文件且未访问QA。
- 2026-08-12：首条EBK金丝雀补强后，31个生命周期Case共91个Oracle步骤；定向测试覆盖响应断言、请求合成、Item无序一对一匹配与MQ Worker路由。
- 2026-08-12：本轮OCR delegation初审2 Medium与唯一复审1 Medium全部修复，最终V2 `131 passed`、legacy `43 passed`、Worker `40 passed`，OpenSpec strict、compileall和diff检查通过。
- 2026-08-12：审批恢复后的真实只读资源复探任务 `task-9c4d0d8ad319466d` 完成；MySQL主库/临时库与Redis仍CONNECTED，两个TiDB仍因READ池缺失BLOCKED，未回退WRITE。
- 2026-08-12：最终Snapshot为 `snapshot-c3a234935513e2d9452accbb`；当前31组Fixture仍为0且Token注入未得到安全存在性证明，因此未发起真实DSF创单或假报QA通过。

## 下一步

- 保持`dsf-execution-and-oracles`为`WAITING_QA_INPUT`；只有真实QA金丝雀和31个业务Case完成后才归档。
- 在本地重新扫描Booking.Core并核对客户端Profile和provider/consumer操作候选；Refund.Core后续访谈继续复用`scan-20260822121007-6b0d5d1222-8ade0ea6`，不重复完整扫描。
- Refund.Core枚举不再形成集中问题；后续只在业务口径需要变更时人工修订具体名称或值，当前0题周期保持不完成，不在本阶段生成测试场景。
- 仅在本地0600 Fixture页填写Booking查询标识和Refund原订单号，不要粘贴到聊天中；每次真实QA探测继续单独确认。
- 先执行Booking.Core自调用`OrderFacade.orderDetail`，成功后再以Booking.Core身份调用Refund.Core `RefundFacade.queryListByOrderNo`。
- 两个只读金丝雀均成功后再切换全部DSF Facade工具、删除Labrador输入/网关API/脚本执行器；HTTP Job和历史`generated_cli`审计保持原样。
- createOrder阶段补齐成功请求、路由/票机预期、清理和完整业务Oracle后，只执行一项经确认写金丝雀；31组130个Fixture继续留空并保持全部`BLOCKED`。
