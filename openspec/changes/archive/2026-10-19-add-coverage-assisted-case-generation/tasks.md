## 0. 现场准入（已通过）

- [x] 0.1 验证本次选定 commit `7b962925db34b181f66e39a9262356585a8fcc03` 的实际构建 WAR、完整业务 JAR、源码和 QA dump：300 条可比较业务类 ID 匹配、0 条不匹配；生成累计报告并单列 28 条未比较生成类。
- [x] 0.2 取得目标 JaCoCo agent 允许 reset 的明确依据：2026-10-19 用户明确允许退款系统 QA agent reset；其他系统及环境未确认时保持 jacoco_reset_allowed=false。
- [x] 0.3 将样本匹配、reset 许可与源码选择契约记录到本 change：source_revision 可填 commit/tag，空值默认 qa 并固定完整 commit；不以自动部署映射作为开工门槛，手选版本仍须逐轮核对构建制品与 class ID。

当前样本验证和 reset 许可满足实施准入，真实 QA 闭环结果见第 6 节。缺制品或 class ID 不匹配时跳过增强，基础 Case 及原验证继续；非增强的历史生成保持原有版本行为。

## 1. 配置与存储

- [x] 1.1 实现共享开关/发现方式/保留策略，本机系统级 appId 与 token 的页面配置、QA coverage_connection 和工作台工具/审查模型配置；验证系统间隔离、QA/UAT 复用，保持缺配置非阻断及凭据保护。
- [x] 1.2 增加严格的增强、缺口、模型引用和报告聚合模型，复用现有 MySQL JSON/gzip 存储、owner/revision 保护及查询；不增加物理表/列/索引或 Generation 状态字段。
- [x] 1.3 在覆盖辅助生成请求接入可选 source_revision，空值默认 qa，解析完整 commit 并复用既有源码 pin/scan；验证短 commit/tag、qa/tag 移动后的重试继承和非增强路径兼容。

验证依据：系统私有设置 store/API、共享策略保留及工具字段测试通过；浏览器配置状态及真实 HTTP 设置保存通过。严格类型、真实独立 MySQL CAS/owner/查询/锁测试通过；source_revision 固定与重试兼容测试通过。

## 2. 实例发现与采集

- [x] 2.1 实现实例发现接口及天网适配器，读取该系统配置的 appId，验证 QA 映射、认证、时区/毫秒边界、排序、分页、日志时效和候选协议可达性。
- [x] 2.2 按固定 commit 接入实际构建制品取得，执行前选定具体构建引用，dump 后下载并核对 class ID/源码；缺制品、不匹配或同路径内容变化时跳过增强并保留诊断，不要求自动识别运行版本。
- [x] 2.3 接入非阻塞测量锁、共享 10 秒准备预算、许可 reset、原验证后 dump 和释放；失败不改变业务结果、不排队补测、不用累计差分替代。

验证依据：真实 QA 使用系统 appId/token 完成最近窗口查询、候选发现及 JaCoCo reset/dump；真实 FTP 分离目录和固定制品取得通过。时区/毫秒、乱序、错身份/错环境、分页不完整及慢速 HTTP/FTP/DNS 超时以受控测试验证，没有声称在平台制造过恰好时间边界或完整多页日志。平台未读完或游标异常时跳过，不能把局部结果当最新。采集解析覆盖无业务交集、方法/重载映射、全量未加载类、包变化、归档解包及仅保存 ENV 凭据引用。

## 3. 准确绑定、任务同步与恢复

- [x] 3.1 在最外层提交前原子登记自动 Execution、专属增强 TaskRecord 的实际进程 owner 和精确引用，提交后用同一原线程池派发；保持 READY/PARTIAL、QA、generate_only 及手动执行边界。
- [x] 3.2 实现非空绑定的精确发布重试，包含手动/UAT 插入、enabled 关闭、ID 缺失/错配和合法空绑定场景；已绑定执行不重派。
- [x] 3.3 在 `_finish_execution` finally 中统一同步专属 TaskRecord，覆盖正常 return、可捕获异常、采集失败及锁忙；有后续步骤时不提前终结总流程。派发失败在派发边界处理，元数据写失败不得伪称收尾成功。
- [x] 3.3.1 验证已开启窗口的有界 dump 与嵌套 finally 释放，覆盖业务异常、dump 超时、锁连接丢失及释放失败；不掩盖原异常、不伪造有效测量、不在长写事务内持有测量锁。
- [x] 3.4 复用真实 lifespan 与 maintenance callback 向现有线程池投递有界、进程内去重恢复作业；保持 GET 只读、心跳线程不做耗时检查。
- [x] 3.5 实现严格进程退出判定及精确 RUNNING 收尾，保留终态/回执；覆盖增强已 SKIPPED、心跳失活但 PID 存活、启动标识变化、权限/标识缺失、他工作台与基线/复测退出。
- [x] 3.6 从持久业务终态和有效 dump 恢复只读分析，模型接续原 turn/结果；不重放业务、不重开补充，不修改 DataCapabilityService._recover_execution 或扩展普通手动执行。

验证依据：真实独立 MySQL 的发布/精确绑定/提交回滚测试，以及协调、finally、dump 超时、清理、维护投递、进程证据、只读恢复和原模型身份接续测试通过；实际子进程终止并回收后，真实 MySQL 中的绑定 RUNNING 执行恢复为 FAILED，释放 active_for 且不重放业务。写入故障采用注入验证，不冒充真实数据库宕机演练。

## 4. 有界缺口与单轮模型

- [x] 4.1 按 resolved-only 范围形成 METHOD/BRANCH_LINE/LINE_BLOCK 去重清单，限制 30 项并保存截断量；标明动态范围和归因未知，不形成执行/发布门禁。
- [x] 4.2 复用逐 Variant 阶段结果作为上下文，仅全部明确 TARGET 前失败时跳过补充；不得按聚合 exec 伪造逐 Variant 路径归属。
- [x] 4.3 实现单轮补充、忽略独立复核、最终裁决与 case_variant_ids 校验，记录模型成本；复用唯一后继和 continue，READY 增强版才测量，不递归增强。

验证依据：缺口去重/30 项截断测试通过；补充测试覆盖唯一后继、忙时不占额度、仅明确 TARGET 前失败跳过、未知派发不重放、忽略审查不可用/拒绝后的最终裁决、漏答、有效 Variant 关联、独立源码上下文、原审查身份恢复和 token/耗时读取。真实补充生成新增非法分页场景，但漏填 3 项处置，已保留 UNRESOLVED；本次没有 IGNORE，独立忽略复核的验收依据是受控测试。随后补清发布前读取 handoff.draft_variants 并填处置的提示协议，受影响 26 项测试通过，不把提示修改算作第三次 QA 实跑。

## 5. 界面、报告和效果

- [x] 5.1 增加覆盖辅助生成的可选 commit/tag 输入及默认 qa 提示、appId 和 token 设置、单实例提示、增强状态投影及已有后继查看/恢复引导；更新资源版本与页面版本检查，验证真实 HTTP 页面。
- [x] 5.2 实现两种报告保留粒度、exec 压缩详情、临时 XML 和有条件的 HTML 重建；保留缺口及轻量效果历史，验证尺寸、写入失败和跨工作台裁剪边界。
- [x] 5.3 固定 UNVERIFIED/INCONCLUSIVE/null 语义，保存快照计数、真实 Case 结果、忽略争议及 token/耗时，不冒充因果增益。

5.1 通过实际 HTTP 页面保存 appId/token（200）、输入 commit、切换系统清空旧输入、显示增强终态及打开准确增强任务；确认加载资源版本 20261019-04。5.2 通过真实独立 MySQL 的 4 MiB exec gzip 往返、摘要排除 result、owner-only 读取、在途/他工作台保护和写失败注入；真实 QA HTML ZIP 下载成功（2,873,968 字节，1,564 个 HTML 文件）。两个保留粒度均验证旧窗口晚完成会裁剪自身、较新失效或空包不会替换上一有效包。5.3 保存两段分析、proposal/review/decision、两类 model_runs 和精确 Case 引用，不增独立净增统计。

## 6. 验证与交付

- [x] 6.1 完成相关单元/集成测试及准入系统的真实闭环，重点覆盖 finally、提交前后异常、进程 kill、数据库写入失败注入、恢复不重放、锁忙及启用开关变化。
- [x] 6.2 完成一次 OCR delegation 独立审查，处理合理 High/Medium 问题并运行受影响验证；检查本次完整 diff 的注释、日志和参数规则。
- [x] 6.3 执行 `openspec validate add-coverage-assisted-case-generation --strict --no-interactive` 及现行 specs 严格校验，停止本次启动的服务并确认 8788 未被本次服务占用。
- [x] 6.4 所有准入和实施验收实际完成后再归档本 change；未完成时保持上述任务和状态真实。

最终验证：相关 Python 合并套件 284 passed，浏览器逻辑 49 passed，提示协议最后调整后受影响 26 passed；重复运行不累加。真实 QA 两次完成 reset → 原验证 → dump → 制品匹配 → 单轮补充 → 复测 → 报告下载。第二次的增强版 2 个 Variant 均 PASSED；接口分析范围方法计数 1/3 → 3/3、行计数 3/16 → 13/16，仍为 UNVERIFIED/INCONCLUSIVE，verified_resolved_count=null，3 项未答仍是 UNRESOLVED。证据保存在本机受 Git 忽略的 `open-test-knowledge/.opentest/coverage-acceptance/7b962925/`。

独立审查采用 OCR delegation、同一只读审查 Agent 两轮，仅审本任务 diff：修复 3 项 Medium（旧草稿覆盖新裁决、晚完成报告错误保留、网络超时缺绝对截止）及页面刷新/版本输入等 Low 问题，没有拒绝的 High/Medium。复查没有遗留 High/Medium。最后的提示文本澄清由主 Agent 核对并完成上述 26 项验证，未开启第三轮审查。

交付清理：本次启动的 HTTP 8789/8790、临时 MySQL 33379 均已停止，临时 UI/QA 数据库及配置已清理。8788 仍由开工前已有的用户进程 PID 77030 监听，未停止；加载新功能需重启该原服务。归档前 change 及全部 43 项现行 specs 严格校验通过。

已通过 OpenSpec CLI 归档为 `2026-10-19-add-coverage-assisted-case-generation`，11 项 requirement 合入现行 `coverage-assisted-case-generation` 规范；归档后全部 44 项现行 specs 严格校验通过。
