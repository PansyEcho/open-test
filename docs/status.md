# OpenTest 开发状态

## 当前Change

`dsf-execution-and-oracles`

## 已完成任务

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

## 进行中任务

- 等待首条境内EBK金丝雀的本地QA Fixture、清理能力和新轮换Labrador Token注入后执行真实业务闭环。
- 等待Booking.Core业务TiDB READ池恢复，再执行依赖TiDB硬断言的生命周期Case。

## 待开始任务

- 完成DSF与MySQL同订单交叉验证后，再分批执行31个核心生命周期变体。
- 当前change归档后，正式创建 `booking-core-business-lifecycle-regression` change；现有31项资产作为其输入基线。

## 阻塞项

- 当前Codex执行环境检查结果为 `OPENTEST_QA_LABRADOR_TOKEN=UNSET`；正在监听的Uvicorn进程是否注入新轮换Token仍未验证。禁止读取进程环境原文、在聊天/Git/本地YAML传递Token或复用旧知识库曾暴露的值。
- 尚未提供Booking.Core非敏感QA Fixture引用：EBK/API供应商、主备票机、操作员、成人/儿童测试身份、港铁与二/三程路线。
- Git忽略的 `qa.yaml` 安全骨架已创建，但31组 `values.fixtures` 仍为空；共130个路径已记录在 `docs/development/qa-fixture-checklist.md`，当前不会猜测或自动拼装请求。
- 首条EBK金丝雀已写入可由源码证明的逐响应和逐Oracle断言；其余30个custom Case仍缺经业务确认的非空断言，空断言门禁会阻止执行或假绿。
- 5个含Job工具的Case所对应扫描脚本仍绑定 `test` 地址；完成QA重扫或显式QA重绑前禁止执行。
- 全局Job影响Oracle和隔离口径尚未确认，因此不能签发一次性确认Token。
- Booking.Core业务TiDB和分析TiDB均未暴露可验证READ池；安全Worker不允许回退WRITE，依赖TiDB硬断言的Case必须保持 `BLOCKED`。

## 最近验证结果

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

- 在Git忽略的本地 `qa.yaml` 中准备首条 `domestic_ebk` Fixture与外部清理能力；请求和身份值不得写入聊天、Git、页面或报告。
- 由QA资源维护方提供TiDB READ池或确认不承载核心生命周期数据；不允许使用WRITE池或MySQL结果冒充TiDB。
- 在Uvicorn进程安全注入新Token并补齐Fixture后，先执行境内普通EBK创单与出票金丝雀，并用DSF、MySQL、临时库、Item、Redis及MQ效果证据交叉确认路由。
- 金丝雀通过后按业务域分批执行31项；所有必需Oracle通过且OCR delegation收口后，才归档当前change并启动下一change。
