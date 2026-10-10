# Tasks

2026-10-05新电脑继续：原交接实现已随提交`502d22f`迁移；本轮背景取证修复在工作区。共享MySQL、指定源码绑定和scriptgen尚未迁移，整体仍未验收。详细证据、环境缺口与继续顺序见[handoff.md](handoff.md)第9节。主任务保留未完成；只勾选已有实际验证的子项。

- [x] 1. 程序扫描、契约、MQ关联和部分发布完成通用验收
  - [x] 补单扫描在不调用解析AI时发布14个Facade、5个JobRequest字段、4组下游、5个MQ真实处理方法。
  - [x] 接入现有精确JAR解析；不适用Job诊断与已解决DTO诊断分开；可靠partial可发布。
  - [x] 更名/更包、非Facade命名、继承泛型JAR样例和相关资源/关系单元测试通过过一轮。
  - [x] 修复booking当前请求类型缺口，诊断refund配置冲突和SOF事件缺口；再次真实验证三系统同一路径。2026-10-09：booking请求类型缺口根因是本地Maven缓存缺jar（offline模式掩盖），经公司Nexus按声明版本补齐后复扫`scan-20261009123045-207e53b9cd-13feee78`转complete_baseline；分析器超时改由`SourceScanRequest.timeout_seconds`贯通（原硬编码180）。refund：filter冲突为同文件重复键，按Java Properties后出现值生效（跨文件仍判冲突）；SOF缺口根因是resolve()先解实参链、Lombok生成访问器不可见导致整体失败，改接收者类型判定+唯一同名同参数方法回推事件类型，复扫`scan-20261009131148-66619d80f6-f579722a`转complete_baseline；supplement`scan-20260930073444-ab9ea92d65-9c1a92c5`保持complete_baseline。三系统同一路径全部complete。
  - [x] 复核无参接口、未知响应、静态字段、单目标契约阻塞和历史冻结，完成最新代码统一回归。2026-10-10：三系统操作契约审计发现6个操作的`input_schema`混入嵌套`serialVersionUID`（scriptgen模板回退，原名称黑名单只拦顶层）；改为Java分析器输出`static_field_names`、按真实修饰符沿基类/列表/引用类型剪除静态字段，删除名称黑名单。复扫supplement `scan-20261010025152-ab9ea92d65-52d51ce0`、booking `scan-20261010025325-207e53b9cd-07ad4b10`、refund `scan-20261010025942-66619d80f6-bd8347e8`均complete_baseline，静态字段与契约命中均为0，操作/阻塞数不变（32/15、100/25、59/7）；旧scan持久化契约保持原样（历史冻结）。真实数据中无参操作均为未解析外部引用（阻塞并提示resolve_downstream_operation）；未知嵌套响应发布为`{}`且保留证据路径；单目标契约阻塞与无参`ping`由`test_dependency_interfaces.py`覆盖。统一回归Python 946 passed / 2 skipped、Node 41/41、Java 30/30。
- [x] 2. 资源探测与任务结果完成最终回归
  - [x] 无业务Profile时，补单QA和UAT各4组资源真实连接均通过，保留历史失败。
  - [x] 使用扫描资源及实际环境配置；修复Redis appName与失败计数；记录最近探测环境。
  - [x] 复核跨环境历史业务证据、最新资源页面和失败任务展示，完成最终统一回归与审查。2026-10-10经8788页面：同commit重扫后补单4项资源全部误判“已过期SOURCE_DIGEST_DRIFT”，根因是源码摘要包含扫描ID、捕获时间和托管快照目录；改为只绑定源码身份与资源投影（新增同源重扫/资源声明变化回归测试）。页面先QA检测`task-ed648d0c87b647c4`（3成功，dpms MQ因QA NameServer无该Topic路由失败），再UAT检测`task-b0d21000ad94490f`（4项成功），资源页标明UAT；任务详情原只显示数量，现从任务结果展示检测环境与逐项失败原因（版本`20261010-04`，378px无溢出）。修复后同commit重扫`scan-20261010032031-ab9ea92d65-76f9437d`资源保持已连接。跨环境业务证据保护由`test_resource_service.py`覆盖；真实系统尚无READY业务证据。
- [x] 3. 三项背景、Agent入口和页面完成验收
  - [x] 三项编辑/补齐/范围重生已接入，移除核心对象必填和确认门禁。
  - [x] 人工内容及生成期间编辑保留的测试通过；补单三项有固定源码片段支持的背景已保存。
  - [x] HTTP浏览器验证过02版目录、关系和探测环境；Node相关测试14项通过过一轮。
  - [x] 诊断CLI/MCP实际工具调用，收敛背景证据覆盖与同步/异步扫描行为、背景任务进度可见性。2026-10-09：成功Case运行`agent-8ea232c122e54c6a`的provider-output记录44次`opentest_source` MCP调用全部完成零错误（search_source/read_source/get_handoff/revise_case_draft/execute_operation/execute_data_draft/publish_case_generation等全流程）；扫描经POST /scans异步任务+GET /tasks轮询（booking/refund各两次实测），任务详情返回stage/stage_index/stage_total/current_item真实进度；背景证据覆盖修复已于2026-10-05回归并经只读审查。
  - [x] 2026-10-05修复背景调用超过两层及同文件远端方法遗漏，拒绝空白源码；两种边顺序、远端覆盖、去重、脱敏和字符预算回归通过，独立审查无发现。
  - [x] 对当前03版重新验证桌面/窄屏、长路径、帮助图标、错误重试、时区和旧页面写入拦截。2026-10-10经8788真实浏览器复验：发现并修复轮询失败提示在恢复后滞留、窄屏下关系证据长facade ID被裁切两项缺陷（版本升为`20261010-02`）；约1000px与378px下六个工作区均无横向溢出或越界元素；帮助气泡悬停显示且在视口内；模拟任务读取500后保留已加载卡片并提示，恢复后自动回到READY；UTC `11:52:55Z`按CST显示19:52:55；后端升版后旧`20260930-03`页面点击“检测连接”零请求并显示刷新提示，刷新后加载新版本资源。Node 40/40，页面契约Python 38 passed。
- [x] 4. MySQL-only、测试迁移和安全清理完成
  - [x] 应用启动强制MySQL配置与连接，无配置/连接失败的单元测试通过。
  - [x] 修复旧应用夹具导致的9项已知失败，检查其他直接构造应用的测试和适配器生产路径。2026-10-09测试统一使用每测试独立MySQL库与`publish_manifest`生产路径；文件权限/符号链接类测试随文件存储退役删除；修复事务回滚吞掉失败状态（知识客户端候选确认、Web生成启动）和MySQL检索命中契约示例两处生产缺陷。
  - [x] 逐身份/版本/内容/引用验证本地重复数据；保留local_only归档、配置、源码绑定后清理。2026-10-10只读核对（与迁移同一模型规范化比较）：旧文件扫描24份、旧工具目录24个、operation/data/case执行865/39/16条及其请求索引、MySQL下载缓存64份均与库内同身份同内容；按用户选择移入同盘备份`/Users/user/opentest-cleanup-backup-20261010`（保留相对路径，共2.88GB，由用户确认后自行删除），退役`ai_test_platform`（仅5个pyc）一并移入。保留：库中缺失的6个工具目录、15个已退役覆盖分析文件、2个旧latest指针、接口缓存、local_only归档`archive-20260813T053636-c4e3533e`、agent-runs、源码快照、环境与绑定、tasks、Case handoffs。共享库行未删除。
  - [x] 清理后实际重启读取最新扫描、历史Case与任务，证明可从MySQL恢复。2026-10-10重启8788：三系统latest扫描从MySQL重新下载并complete_baseline；refund历史扫描24份及2026-08-27旧扫描可读；Generation`case-template-generation-6b215469517a4a2abb19` READY、执行`case-generation-execution-1d02560609104eb7a550` PASSED；refund Case执行20条、data执行56条、已移出的operation执行按ID可读；任务160条；页面READY。
- [x] 5a. 程序覆盖分析整体删除
  - [x] 2026-10-09 delta specs更新：program-case-analysis全部REMOVED；case-template-generation-v4、shared-mysql-workspace、candidate-operation-catalog相应调整，change严格校验通过。
  - [x] 删除program_case_analysis、case_coverage_v4及相关模型/适配器/调用方；历史MySQL记录旧字段读取忽略，不做数据迁移；相关测试删除或改写。
  - [x] 全量回归通过（2026-10-09本机MySQL全量934 passed / 2 skipped，已满足）；真实Case不再出现静态扫描义务合成的OBSERVATION_FAILED，真实观测失败仍FAILED/OBSERVATION_FAILED。2026-10-10复核：补单两次真实执行`case-generation-execution-1d02560609104eb7a550`、`case-generation-execution-1da312ab0ca747f589f8`均PASSED且报告零OBSERVATION_FAILED；真实观测失败分类由`test_case_template_v4.py`、`test_shared_data_capabilities.py`、`test_data_capability_execution.py`与`case-view.test.js`覆盖并通过。
- [x] 5. 未知缺口AI补充、真实Case、独立审查与交付
  - [x] 验证当前字段补充初稿的类型/证据/冲突校验及MySQL任务采纳/拒绝记录；不得用它掩盖已知扫描缺陷。2026-10-10真实验证补单`CallbackFacade#reportCallBack`字段`ext`（Map<String,String>）：任务`task-2d62b634d1bd4ea9`提交与源码类型冲突的object Schema被拒，任务FAILED、采纳记录rejected且拒绝重复提交；任务`task-cda128d36f144aeb`只补说明被采纳，契约revision 0→1，ext Schema仍为`{}`。修复拒绝后重复提交的错误覆盖失败摘要、丢失拒绝原因的缺陷（新增`test_contract_supplement_records_rejection_and_adoption_in_task`）。
  - [x] 查询Case闭环：2026-10-09补单`TaskFacade#queryTaskList`网页任务`task-ffac22d362158368`发布`case-template-generation-6b215469517a4a2abb19`；数据函数经本系统数据源`:query`在QA动态取得真实任务，目标按其渠道/PNR/票号/状态查询，执行`case-generation-execution-1d02560609104eb7a550` PASSED（6项断言）。旧任务task-e6380ce8bcdbca61的缺口为已删除的覆盖校验，不再续跑。日期窗口仍为literal（DSL无运行期当前时间函数）。
  - [x] 初验后运行OCR delegation独立审查，修合理High/Medium并复验，最多两轮和一个只读审查agent。2026-10-10同一只读agent两轮：第1轮2 Medium/5 Low，修复SOF接收者不可求解时静默丢缺口、受保护文件名经搜索入口暴露存在性、继承重载未计入唯一性、filter同文件多值比较、自引用DTO静态字段剪除、测试库建表失败泄漏；拒绝“旧Generation的observation_failures不再判失败”（program-case-analysis Migration明确忽略旧覆盖字段）。第2轮核实上述修复，新报1 Medium（继承泛型方法返回类型变量被当事件类型）/1 Low（无扩展名受保护文件存在性差异），均已修复并补测试；真实refund/booking快照复跑SOF告警0、派发候选边6/14与修复前一致。复验Python 946 passed / 2 skipped，Node 41/41，Java 33/33。
  - [x] 2026-10-05本轮背景取证修复完成一次delegation只读审查，9项独立测试通过；无发现、无审查驱动代码变化。此前完整接入实现的最终审查仍待整体初验。
  - [x] 最终严格OpenSpec校验、所有验收通过后归档（2026-10-10 change与specs严格校验通过后归档）；交接时禁止归档。未归档的`shared-data-preparation`同样修改/移除program-case-analysis（另含case-template-generation-v4、candidate-operation-catalog、generalized-knowledge-workflow）；两者后归档者需按当时`openspec/specs`重基delta，否则REMOVED/MODIFIED目标不存在会导致归档失败。
  - [x] 2026-09-30现场交接时停止本轮8790服务；8788/8790均无监听，所属workspace无pending/running任务。
  - [x] 下次启动的服务在最终交付前再次全部停止，并检查8788。2026-10-10停止8788（uvicorn 42623/42624）与测试mysqld 49015，`lsof`复查8788/33061均无监听。

2026-10-05环境验证：`.venv`已建立（Python 3.12.14）；语义分析器构建及28项Java测试通过，相关后端4文件74项、前端14项通过。原6文件基线仍有9项旧MySQL夹具失败（135通过），未恢复文件生产回退。业务Worker缺少公司依赖及Maven私服配置。OpenSpec 1.14.0对本change严格校验通过；全局43项spec因既存Purpose占位文案违反新版严格规则而失败，不代表本轮引入43项行为回归，尚未归档。

交接文档与规范校验不代表上述代码/产品验收完成。

交接校验：`openspec validate simplify-java-system-onboarding --strict --no-interactive`通过；`openspec validate --specs --strict --no-interactive`为43 passed / 0 failed。该结果只验证规范格式，未归档。
