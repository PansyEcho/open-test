# OpenTest Java 系统接入修复：跨电脑交接

更新时间：2026-10-05，Asia/Shanghai。第1–8节保留2026-09-30原机交接现场；第9节为新电脑继续后的最新状态。当前**未完成整体验收**。

## 1. 先读与现场身份

1. 读根目录 `AGENTS.md`，再读本文件、同目录 `proposal.md`、`design.md`、`tasks.md` 和本 change 的 delta specs。
2. 当前唯一选定 change：`simplify-java-system-onboarding`。尚未归档；不要扫描其他 active change 或 archive。
3. 保存时分支：`test`；基准 HEAD：`ba0e1b9efa18fd52ee33568397c71c1e065a5d7f`。实现全部在未提交工作区；本轮开始时工作区干净。没有提交、推送或创建 PR。
4. 首先查看当前机器 `git status` 和完整 diff。后续如果有新改动，不得把它们当作本轮遗留随意覆盖。补丁仅适合相同基准；已有相同改动时不要重复应用。
5. 数据真相在共享 MySQL；代码、当前未提交 diff、本机配置、源码绑定、Agent 进程和日志不会自动随 MySQL 跨机器迁移。

## 2. 用户确认的方案与不可改变的边界

- 当前已知 DTO、扫描诊断、目录发布、上下游、MQ 关联缺陷全部由程序修复。第一阶段验收禁用解析 AI；不能只删除告警或把 partial 改成 complete。
- 复用现有 Java 语义分析和 `JavaDependencyCatalog`，按实际 Maven classpath 的精确 JAR 版本解析，不猜别的版本，不另写解析器，不加补单/booking/refund 专属分支。
- 局部缺口只影响对应目标。可靠接口、资源、契约、关系正常发布；latest 只指向已发布结果，失败扫描不抢占；任务冻结扫描/契约版本，旧 Case 不变。
- 连接检测独立于业务校验 Profile；按项目 QA/UAT 配置执行 DB 只读查询、Redis PING、MQ 路由查询。连接成功不能冒充业务验证成功；历史失败保留。
- 背景只有系统定位、核心主流程、责任边界三项。首次自动生成，人工可改，不要核心对象必填或人工确认门禁。重扫不覆盖已有内容，重新生成明确选范围，生成期间的人工修改优先。
- 统一页面按钮、表单、帮助图标、状态色和间距；局部错误局部显示。新资源 URL、旧页面版本检查、桌面/窄屏均需真实 HTTP 验证。
- MySQL 是唯一生产运行数据源。历史文件/SQLite 只用于离线迁移恢复，不作为启动失败的回退。删除重复代码和数据以实际依赖为准，不新增通用框架或清理台账。
- 未知未来缺口的 AI 补充在程序验收后独立建设，沿用 Agent/契约任务，必须校验类型、字段路径、源码证据和冲突，结果写现有 MySQL 任务记录，失败不循环重试。
- 最终仍需补单查询的取数 → Case → 执行 → 断言、清理后重启、OCR delegation 独立审查、严格 OpenSpec 校验和归档。

## 3. 已实现及已验证的事实

### 3.1 程序扫描

原补单故障不是14个接口都不可解析：旧扫描识别了4个 Facade、14个方法，唯一空请求是依赖 JAR 中的 `JobRequest`；未启用的 JobTypeEnum 规则又产生告警；partial 提前返回导致接口表和 latest 未发布，关系返回404。

当前实现涉及 `opentest/application/operations.py`、`source_analysis.py`、`system_relations.py` 和 `opentest/adapters/source_analysis.py`：

- 新 `resolve_facade_contracts` 将已有源码/JAR解析接到本地发布接口，补充没有 Facade 后缀但有发布声明的入口，冻结 Schema 和依赖坐标。
- 将不适用旧 Job 告警标为 `JOB_RULE_NOT_APPLICABLE`；已补齐 DTO 标为 `FACADE_DTO_RESOLVED`；真实缺口按接口定位。
- partial 也发布可靠接口、零版契约和关系，推进已发布指针；未扫描系统关系空态。
- `_listener_methods` 沿实际继承关联 `process/onMessage/consumeMessage/onUniformEvent`，补单两参数 `onUniformEvent` 已关联，不把框架包装类型猜成业务消息 DTO。
- 本地 Facade 与外部 DSF 都可从冻结 Schema 展示字段（`operation_input_knowledge.py`）。

**补单真实验证，解析 AI 未调用：**

| 项目 | 结果 |
| --- | --- |
| 系统 | `ifightchainsaas.java.account.supplement.core` |
| 固定 commit | `c9f52e57682c3233657f2820f964966b0e49a6da` |
| 最新验证扫描 | `scan-20260930073444-ab9ea92d65-9c1a92c5`，complete |
| Facade | 14个方法 |
| JobRequest | `traceId/operator/jobName/startDate/ext` 五字段 |
| 精确依赖 | `com.chainsaas.flight:common-model:1.1.29` |
| 下游 | 4组：endorse、refund、booking、resource；保存实际 gs_name，不按系统名映射 |
| MQ | 5个消费者均有真实处理方法，其中 SupplementBinlogListener 绑定 `onUniformEvent` |

真实源码原机器路径：`/Users/user/data/code/tc/ifightchainsaas.java.account.supplement.core`。不要将其硬编码到另一台机器。临时验证脚本曾把 `app.agent_runner.run` 替换为抛错函数，再运行程序扫描，未触发 AI。

### 3.2 资源检测

涉及 `application/resources.py`、`adapters/qa_active_worker.py`、`adapters/resource_inventory.py`、Java `ActiveOperationService.java`：

- `RESOURCE_PROBE` 复用 Java Worker：DB `SELECT 1`、Redis PING、MQ 路由查询，不需要业务 Profile，不发送 MQ 消息。
- 修复 Redis 应用名：从项目 `tcbase.appName` 读取，不能拿仓库系统名替代缓存 SDK appName。补单的实际值与仓库名不同。
- 每项独立记录，失败计数用枚举真实大写值；`probe_environment` 标明最近探测 QA/UAT。
- 补单真实 QA 4/4成功：`task-6fd2348351a54538`。
- 补单真实 UAT 4/4成功：`task-c22c985f1cd7469c`。
- 以上四组为两个 MQ 集群、MySQL、Redis；业务校验仍为 UNVERIFIED，这是正确结果。
- 旧失败任务保留；曾有早期测试任务把失败误算成成功，计数已修，旧记录未篡改。不要把历史失败当成本轮未重测。

### 3.3 背景和页面

- 三字段编辑器、补齐空白、按单字段重生接口已接入。接口使用不再依赖背景确认；保留历史核心对象数据但不再显示为必填。
- 生成后在事务内重读，保留生成期间人工改动。已补单元测试，最后一次4项全部通过。
- 最初背景 Agent 没读到源码，虽退出成功却生成全是“未知”。这不算有效背景，已重新生成。
- 当前背景生成先通过注册源码安全读取/脱敏函数准备固定 Java 片段，再让 AI 总结。仅取入口和有限调用范围，100,000字符总上限；未读到证据报错，不保存空洞猜测。
- 最新背景任务：`task-ff0adc96fd104683`；run `agent-16cbd25c121b46d5`。已产生有业务内容的三项并写入 MySQL；具体边界仍有未知，内容质量需继续检查，不能称为全面理解。
- 发现 CLI 版本问题：PATH 上 npm Codex `0.142.4` 不支持配置的模型；本机已安装的桌面附带 CLI `0.159.0` 可运行。新增本机 `codex_executable` 设置并为本机填写该路径，**未升级全局 CLI**。另一台机器必须配置自己的有效路径。
- Agent 命令已给已授权的源码 MCP/任务桥设置非交互批准，且背景请求也遵守所选模型；Case 未单配模型时使用 OpenTest 的 `codex_model`。
- **MCP 工具实际可用性尚未验证通过**：新 CLI 背景 run 仍出现零源码工具调用。背景预读方案有实际内容，但 Case 任务仍未完成，不能据此声称任务工具链已修复。
- JS/CSS 已改统一绿色主按钮、中性次按钮、帮助图标、长路径换行、任务按钮及时间解析。面板读失败返回局部失败，不再重复抛全局“页面部分数据读取失败”。
- 当前源码版本 `20260930-03`，API常量、HTML meta/JS/CSS URL一致。真实浏览器验证过 `20260930-02`：补单14 Facade/5 MQ、4下游、资源检测环境均显示；**03版完整复验、资源区域截图和窄屏仍未完成**。旧页面版本检查保留，须复验。

### 3.4 MySQL与未来AI补充

- `OpenTestApplication._initialize_persistence` 现在强制 MySQL 配置与 `SELECT 1`，失败不创建本地替代库；删掉 foundation 多处文件/SQLite分支。
- 其他适配器仍有可选文件分支，部分由离线迁移和单元测试使用。尚未完成“生产路径零回退”调用链审查，不要盲删迁移代码。
- 未知字段补充初稿在 `operation_contracts.py` 与 `data_capabilities.py`：只接受已有路径、同一固定声明、可由现有 Java 标量规则复核的 Schema，不覆盖已知类型。复杂未知对象/缺失依赖仍拒绝，**不是通用复杂 DTO AI 修复器**。
- 现有任务 JSON 保存 trigger/gaps/supplement/adoption/reason；拒绝后不自动循环。此路径仅有部分单元验证，还需 MySQL 任务成功/失败持久化与幂等验证及审查。
- 没有新增表、迁移或常驻清理服务。

## 4. 交接时确认的未解决问题（按优先级继续）

1. **补单真实 Case 闭环未通过。** 查询入口：`facade:com.ly.flight.chainsaas.account.supplement.core.facade.TaskFacade#queryTaskList`。任务 `task-e6380ce8bcdbca61`，handoff `case-template-handoff-bebcc88ee6894fe8bc35`，预留 generation `case-template-generation-0a4758e94549408e85ec`。2026-09-30 15:52:09 CST最终状态 failed：Agent已结束但尚未发布正式产物。最后 web_run `agent-50d630f30b3d4fcf`；本机常规 agent-runs目录未找到它，需先诊断为何出现该状态。不能把预留 generation ID当成正式Case。先读 MySQL task/context/执行记录，再决定继续，不重放未知业务请求。已用 request IDs：`onboarding-query-20260930-01`、`onboarding-query-continue-20260930-01`、`onboarding-query-run-20260930-02`。HTTP `/tasks/{id}/runs` 要求真实 `expected_revision`，从响应 `context.revision` 取，不猜0。
2. **booking/refund 通用验收尚未通过。** booking：`scan-20260930073818-207e53b9cd-b3276ca8`，100入口、partial。仍有 DistributionRequest、DistributionCallBackRequest、JobRequest、BookProcessingRequest、NotificationsRequest 等请求未解析，部分语义类型只有简单名；先核查 imports/FQN 与实际依赖，不能猜 JAR 版本。另有 `sof_event_dispatch_unresolved`。refund：`scan-20260930074029-66619d80f6-3a8fb459`，34入口、partial；QA filter `mq.saas.arc.bsp.change.sender.group/topic` 冲突及2项 SOF事件派发缺口。可靠目录已发布；不得把这些未解决诊断直接静默删掉。
3. **MySQL-only 改动使旧应用测试夹具失效。** 最新 `test_source_analysis.py` + `test_operation_contracts.py`：66通过、9失败。失败均是夹具仍直接 `OpenTestApplication(tmp_path)`，未提供 MySQL配置。涉及CLI扫描、partial任务历史、Facade/MQ详情、MQ证据、HTTP历史目录、跨扫描契约状态。需迁移测试夹具或用明确的组件级组装；不要为了旧测试恢复生产文件回退，也不要无说明跳过。其他24个测试文件也存在相同应用构造，尚未做完整回归。
4. **扫描契约还有边界需复核。** `contract_gap` 对单个目标是否完整传到契约状态；无参接口空模板不应误报；未知响应/嵌套字段应保留缺口；部分旧scriptgen模板带静态字段 `serialVersionUID`，需按真实字段修饰符处理而非名字黑名单。非Facade命名、XML/注解、泛型/JAR的样例已覆盖一部分，未满足所有真实系统验收。
5. **背景实现需小幅审查。** `_background_source_evidence` 当前 `selected.update(generator)` 会在遍历调用边时读取同时被扩展的集合，可能超出注释所称“两层”；先形成本层集合再更新更准确。同文件片段只取首个命中方法的180行，覆盖可能不足。同步 `analyze_source` 当前仅程序扫描，自动背景只在异步扫描入口；需确定产品入口的一致要求。背景进度 UI 可能写到隐藏的系统面板。`save_background`完成时间字段曾误放到`save_narrative`，已移回并通过4项测试，但仍需独立审查。
6. **新CLI/MCP需独立诊断。** `--ignore-user-config`、模型、MCP工具是否真正可调用，不能仅看Agent退出码；不要把CLI不兼容或工具没调用隐藏成AI“未知”。本机路径配置是临时环境修复，非跨机器解决方案。
7. **资源与UI收尾。** QA/UAT真实探测通过；最近探测环境已标明，但跨环境历史业务证据展示语义仍应复查。`_shared_discovery`改为已发布pointer后真实重启已能读，旧partial缓存版本查询/旧注释还有冗余可收敛。完成03版桌面和窄屏、长路径、错误重试、旧页阻止写入测试。
8. **本地数据清理、清理后重启、OCR review均未执行。** 不要据当前进度勾选整项完成或归档。

## 5. 验证记录与复跑入口

这些是不同阶段的结果，不能相加当成最终总通过数。最新完整改动尚未做一次统一回归。

| 范围 | 已观察结果 |
| --- | --- |
| dependency_interfaces + resource_service + system_relations | 64 passed（之后又有小改动） |
| resource_service（新增UAT测试后） | 9 passed |
| source_analysis + operation_contracts 最近全文件 | 66 passed / 9 failed，原因见上 |
| onboarding_runtime 最新 | 4 passed，启动失败边界、人工改动保留、Agent命令 |
| Node system-settings + native-handoff | 14 passed（03版文案小改后未统一重跑） |
| Java qa-oracle-worker | `mvn -q -o -f workers/qa-oracle-worker/pom.xml test package` 已通过 |
| execution_profiles 早期检查 | 两项外部DSF空请求Schema测试失败，原执行代码未改；需与基准复核，不能随意归为本轮或忽略 |
| git diff --check | 交接时通过 |
| OpenSpec | 交接时本change严格校验通过；当前43项spec严格校验全部通过，仍未归档 |
| OCR | 未运行；后续选 delegation，不能称为已审查 |

常用命令（项目根，先完成本机配置；真实MySQL测试明确启用独立身份）：

```sh
.venv/bin/python -m pytest -q tests/v2/test_dependency_interfaces.py tests/v2/test_resource_service.py tests/v2/test_system_relations.py tests/v2/test_onboarding_runtime.py
.venv/bin/python -m pytest -q tests/v2/test_source_analysis.py tests/v2/test_operation_contracts.py
node --test tests/web/system-settings.test.js tests/web/native-handoff.test.js
mvn -q -o -f workers/qa-oracle-worker/pom.xml test package
openspec validate simplify-java-system-onboarding --strict --no-interactive
openspec validate --specs --strict --no-interactive
```

真实共享库测试参考 `tests/v2/test_mysql_workspace_integration.py`：通过 `OPENTEST_MYSQL_TEST_CONFIG` 显式启用，每次唯一 `mysql-test-*` 系统，finally仅清理本次身份。不要拿历史已归档 `train-booking-core` 做固定ID测试，更不能清空共享表。

## 6. 本地清理规则与当前体积

**本轮尚未删除任何历史业务文件或扫描缓存。** 最近新增扫描让缓存从原约924MB增长到约1.1GB。以下均为原机器路径 `open-test-knowledge/.opentest/`：

| 内容 | 最近大小 / 处理 |
| --- | --- |
| cache | 约1.1GB；含scans与generated-tools。确认MySQL manifest/tools可恢复且无活动任务后清理 |
| scans | 839MB；旧文件副本，逐身份/版本/内容/引用回查后删除匹配文件 |
| operation-executions | 175MB；比对 ot_execution 对应 operation 记录 |
| data-capabilities | 137MB；定义、handoff、execution分别比对相应表 |
| case-template-v4 | 114MB；Generation、handoff、执行等逐类型比对 |
| agent-runs | 37MB；本轮诊断尚有价值，尤其失败/源码读取证据，不整体删除 |
| archives | 6.1MB；local_only归档必须保留 |
| source-snapshots | 原约22MB；固定源码任务仍可能引用，不能只看目录日期删除 |
| tools / tasks / drafts / question-cycles | 旧文件需逐身份比对；运行锁/心跳和未迁移数据不能按扩展名清空 |

- 可清：Python/pytest缓存、旧页面测试产物、只有pyc的退役 `ai_test_platform` 目录（先再次确认无源码）。不要顺手删 `.venv`。
- 保留：项目根 `.opentest/metadata-mysql.yaml`、`.opentest/settings.yaml`；知识根 `.opentest/environments/`、`source-bindings.json`、本机系统/扫描配置及源码。
- 已知必须保留的本地归档：`archive-20260813T053636-c4e3533e`，`restore_scope=local_only`。保留原文件及它恢复所需的全部内容。
- 可复用离线工具的严格模型比较：`portable_scope_payload`、`StandaloneAssetMigrator`的按类型对比、`MetadataMigration._verify_references`、`SourceScanArtifactStore.ensure_tool_bundle`。**不要为“验证”直接重跑 migration.run()**，它会写库并可能恢复旧 latest 指针。
- 不同机器路径通过模型明确的SourceBaseline规范化比较，不能随意删掉业务字典字段后宣布一致。不一致/库中缺失/引用不完整则保留并报告。
- 不整体删除运行目录，不新建清理数据库、清理台账或常驻任务。清理后重启实际读取历史Case和最新扫描才算验收。

## 7. 另一台电脑继续所需环境

- 先带走代码 diff 与本交接文档。仅clone/pull当前分支不会包含未提交实现。已另准备 `opentest-onboarding-handoff-20260930.patch`，包含本轮源码、测试、AGENTS与OpenSpec交接文档，不含配置密码、Agent认证、业务响应、依赖或生成JAR。补丁不是Git提交，也未推送。
- 在另一台机器的相同基准、干净工作区先执行 `git apply --check /path/to/opentest-onboarding-handoff-20260930.patch`，通过后执行 `git apply /path/to/opentest-onboarding-handoff-20260930.patch`。若基准不一致或已有改动，先检查差异；不要force、reset或覆盖现有工作。应用后立即读AGENTS及本文件。
- MySQL连接配置自行安全配置为同一共享库，但新工作台使用自己的 `workspace_id`，不要复制原workspace身份来伪装任务所有者。共享任务可读，别机任务可能只读；必要时从明确的后继/新请求继续，先查原执行，保持去重。
- 重新绑定三个源码仓库和固定commit。原机器源码在 `/Users/user/data/code/tc/`，scriptgen在 `/Users/user/data/code/other/CLI-Anything/scriptgen/agent-harness`，JAR在本机Maven仓库；这些路径不能直接套到家里电脑。
- 准备可访问公司依赖/QA/UAT/MySQL的网络与Maven缓存，构建项目需要的Java Workers；补丁不包含生成的JAR、源码快照、依赖JAR或数据目录。
- 本机 `codex_executable` 当前设为 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`，仅本机有效。另一电脑选择实际已安装并支持所选模型的CLI；认证单独保留。当前知识模型 `gpt-5.6-luna`，推理low；不要擅自切换模型以掩盖工具问题。
- 正常HTTP默认8788；本轮为避免碰用户旧服务使用8790，并仅在临时服务实例把 `web_generation.api_root` 改成8790。**产品里 api_root 默认仍固定8788**，另开端口验证时必须同步绑定，不能让新服务Agent误调用旧服务。临时 `/tmp/opentest_review_server.py` 不应成为项目依赖。
- 交接时本轮8790服务已停止；检查8788和8790均无监听。MySQL本workspace pending/running任务查询为空。下一次开工重新检查，不凭旧PID停止进程。

## 8. 后续AI的工作顺序与审查要求

1. 恢复代码/环境，先核对上述task、scan和diff；修复真实Case失败和booking/refund确定性缺口，仍禁用解析AI兜底。
2. 迁移受MySQL-only影响的测试夹具，检查契约缺口和背景/CLI边界，完成统一回归与页面验证。
3. 将已确认重复代码和数据按规则清理，实际重启验证；未来AI补充仅保留有真实消费者及校验的最小实现。
4. 代码完成初验后进行一次OCR delegation独立审查；修合理High/Medium并复验。仅接受审查修复改变行为时进行一次同模式复审，总共最多两轮、最多一个只读审查子agent。未完工前不要提前归档或声称无风险。
5. 更新tasks/specs，严格验证均通过且所有验收真正完成后再用OpenSpec CLI归档；停止本任务启动的所有服务，检查8788。

本轮用户额外编码验收规则须延续：新改函数必须有说明业务目的、参数、返回值及重要副作用/异常的文档注释，非平凡阶段有解释“为何”的内部注释；遵循项目语言与日志格式。日志工作流入口绑定trace/filter1/filter2并用现有上下文管理器/finally清理，不泄露载荷。默认最多5个显式参数；私有6–7参数仅在少量调用、生命周期不同且包装更差时有文档说明；不要为凑数引入一次性Context/Map。清晰单次无副作用表达式保持直接，多阶段I/O、状态变化、复杂空值/集合查找应命名拆开。完成前检查整个diff。

独立审查选择：已知本机OCR 1.8.8配置的Responses端点要求流式、direct review不兼容；直接选delegation，不先重现失败。读 `open-code-review` skill，运行 `ocr delegate preview --background ...` 核对本任务文件，再 `ocr delegate rule <task-owned-paths...> --background ...`，向一个只读子agent提供规则、完整本任务patch、用户验收要求和上下文。metadata工具失败则给同一子agent显式patch与规则；不改Git状态隔离diff，不把本机配置/凭据送审。High/Medium争议集中发回同一子agent仲裁。后续最终报告注明review范围、接受修复、拒绝及仲裁、复验和是否产生代码变更。

## 9. 新电脑继续记录（2026-10-05）

### 9.1 迁移与环境

- 新工作目录：`/Users/shizhen/virtualMacOS/code/open-test`。原交接39文件实现已包含在提交`502d22f`（父提交`ba0e1b9`），无需重打原补丁。开工时只有`.idea/misc.xml`和`.idea/open-test.iml`两处用户修改，均未改动。
- 新机器没有`.opentest/metadata-mysql.yaml`、原机本地运行配置、源码绑定或运行数据目录。未连接共享库、未查询/重放原Case任务、未创建共享workspace身份、未清理任何历史数据或归档。
- 使用本机已有Python 3.12.14建立项目`.venv`并安装`.[dev,qa]`。PyCharm可选择`/Users/shizhen/virtualMacOS/code/open-test/.venv/bin/python`；系统`/usr/bin/python3`为3.9.6，不满足项目要求。虚拟环境基础解释器来自`/Users/shizhen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`。
- PATH没有Maven，但已找到`/Applications/IntelliJ IDEA.app/Contents/plugins/maven/lib/maven3/bin/mvn`。使用现有JDK25成功构建Java语义分析器，28项Java测试通过，生成JAR仅位于Git忽略的target目录。
- `qa-oracle-worker`及`qa-dsf-worker`离线构建失败：本机缺少精确公司依赖，如`com.ly.dsf:dsf-client:2.5.11`、`com.ly.turbomq:*:4.2.5`和`com.ly.tcbase:configcenterclient:6.2.8`，且`~/.m2/settings.xml`不存在。需恢复公司Maven私服配置/网络或相同版本依赖缓存，不能换版本冒充通过。
- 只找到`/Users/shizhen/virtualMacOS/code/ifightchainsaas.java.refund.core`，其当前HEAD是`e51e1a8c`；尚未与共享库固定commit核对。未找到指定补单、`ifightchainsaas.java.booking.core`及scriptgen agent-harness。现有`travelsystem.java.dsf.supplychain.booking.core`不是同一仓库，不可替换。
- PATH上的Codex为`/Applications/ChatGPT.app/Contents/Resources/codex`，报告`0.154.0-alpha.6.2`；只验证版本，未验证模型认证或MCP实际调用，也未更换所选模型。
- 待用户提供本机共享MySQL配置文件路径（或安全放到项目`.opentest/metadata-mysql.yaml`）、上述源码及scriptgen路径，以及公司Maven配置。MySQL配置需要host/port/user/password或password_env/database；不要复制旧workspace_id，留空由项目生成本机身份。不要把密码发到对话或写入Git。

### 9.2 本轮代码、验证与审查

- 复现并修复`_background_source_evidence`三项缺陷：调用边按顺序迭代时突破两层、同文件首个片段掩盖远端方法、空白Java被当作有效背景证据。
- 每层调用先物化再合并；按文件/行号取片段，同文件只读一次，已覆盖行不重复计入预算；保留注册源码校验及脱敏，每段最多10,000字符、总计100,000字符。只改背景取证，不替代未完成的CLI/MCP、同步扫描和页面验收。
- 修复前6文件基线为135 passed / 9 failed；9项均为第4节记录的旧应用测试夹具未配置MySQL，未通过放宽生产启动规则或跳过测试掩盖。
- 修复后`dependency_interfaces + resource_service + system_relations + onboarding_runtime`为74 passed；新增背景回归含两种调用边顺序、同文件远端覆盖/去重/脱敏、空白拒绝及字符预算。`system-settings + native-handoff`为14 passed。这些结果不可累加成全项目统一通过数。
- 本轮代码选择OCR delegation审查。新机器无`ocr`命令或`open-code-review` skill，`ocr delegate preview`和`ocr delegate rule`均确认不可用；按AGENTS明确回退规则给一个只读子agent完整本轮patch及项目审查要求。
- 审查范围为本轮`foundation.py::_background_source_evidence`、新增测试与对应delta/design，排除预存IDE修改和已提交的旧实现。独立运行`test_onboarding_runtime.py`为9 passed；无High/Medium/Low发现、无拒绝项、无审查驱动代码变化，无需第二轮。完整接入实现的最终审查仍须待真实环境和整体初验后完成。
- 临时安装OpenSpec 1.14.0于`/private/tmp/opentest-onboarding-tools`。本change严格校验通过；`openspec validate --specs --strict --no-interactive`为0 passed / 43 failed，全部命中既有Purpose占位说明在新版严格模式下的规则。未为此次局部修复批量改写其他规范，也未降级CLI掩盖结果。
- 已更新本change的design、delta、tasks；不归档。没有启动OpenTest HTTP服务；本轮结束检查8788/8790均无监听。

### 9.3 恢复环境后的下一步

先用新workspace配置只读核对共享任务`task-e6380ce8bcdbca61`及执行状态，绑定三个真实仓库的既有固定commit并验证scriptgen、公司JAR和CLI/MCP，然后继续第4节全部开放项。测试夹具迁移、真实查询Case闭环、三系统扫描、QA/UAT与页面复验、安全清理/重启和整体验收均未完成。需要同时处理新版OpenSpec的Purpose校验问题，全部实际完成后才能归档。
