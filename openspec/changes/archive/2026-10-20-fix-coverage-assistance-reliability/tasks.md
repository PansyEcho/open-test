# Tasks

- [x] 1. 证据与收尾：有效 dump/analysis 不因后续失败作废；Future 去重；仅小终态原子提交、status-only 读取一致；内部裁剪标记不公开，裁剪可恢复；finally 同步覆盖所有异常出口且不写回旧 owner。
- [x] 2. 恢复与补充：严格退出证据、系统锁下 owner/revision 原子 claim、健康 owner 不写异常；同进程恢复、坏记录隔离、半收尾补齐；Agent/人工接续不误杀，未知派发不重放，明确 GATE_BUSY 保留；真实 MySQL 及双进程验收通过后进入源码阶段。
- [x] 3. 源码独立验收：指定 scan 入口、历史扫描及共享工具复用、clean/入口/契约检查；显式无扫描失败、默认无扫描基础降级并跳过增强；重试固定 scan；不修改共享 pin/latest、不扫描、不占全局门禁。
- [x] 4. 后继与边界：多层增强祖先、终态守卫、后继页面与错误提示、可选投影降级、旧回执；WAR/JAR/BOOT-INF、重定向、超时/锁错误及清理；前端资源版本和实际 HTTP 验证。
- [x] 5. 最终验收：目标已调用但 TARGET 记录缺失、有效证据派发/收尾/裁剪故障、活动 Future、Agent 存活、真实 MySQL 并发与恢复全部实跑；保留 QA Case/执行历史；OCR delegation 独立审查；严格 OpenSpec 校验；停止本任务服务并检查 8788；全部通过后归档。

## 分阶段验证

第 1/2 阶段进入源码阶段前：隔离真实 MySQL 的 assistance/recovery/supplement/store/publication/web-generation 合计 121 passed；新增证据恢复故障 8 passed；新增存储边界 9 passed（已计入前述相关集）。双独立 Python 进程竞争同一恢复 claim 已实跑，均无跳过。

源码独立阶段：源码/Case 后继/发布/web-generation 联合 71 passed；真实 MySQL 验证不同 commit 并发任务固定各自扫描，共享 pin/latest 不变。历史选择按轻量扫描 ID 逐个读取并短路，单项损坏隔离。

独立审查采用 OCR delegation，按开工前快照提取全部任务补丁（不依赖中途外部提交后的 Git 工作区差异）。首轮 1 项 Medium：新增继承字段改变旧后继请求身份；已修为创建后锁内补充来源投影，旧请求可重放且异参拒绝。唯一复审未发现新的 High/Medium。相关修后 85 passed、0 skipped。

完整相关 Python 集合首次 236 passed、0 skipped；前端 56 passed。HTTP 验收发现并修复 API 页面版本常量未同步，HTML/meta/资源/API 均为 `20261020-01`，一致性断言已覆盖；最终相关前端回归另 22 passed。

实际 HTTP/浏览器已验证新页面无误报过期、单实例提示只显示一次、基础版发布后仍可查看、继续按钮切换到既有补充任务且重新生成禁用；点击后打开同一 `task-8c7dc18a93b34204`。错误提示、迟到响应和已有后继竞争由前端测试覆盖。

真实 detached Agent 存活补充验证：对本轮实际 worker/Agent 的状态文件和 PID 做只读核实，将其接入内存恢复场景；服务 owner 已退出标记存在时仍保持 SUPPLEMENT_RUNNING，未 finish、重派或创建后继。真实业务状态不作测试改写。

## 日常工作台 QA 结果（2026-10-20）

- 目标：`RefundFacade#queryList`，固定 `7b962925db34b181f66e39a9262356585a8fcc03`；使用历史扫描 `scan-20261020062539-c796af848b-6894bbf5`。验收前通过现有系统扫描流程准备材料并恢复原系统 pin/latest（`99b494d`）；Case 选择没有再次修改它们。
- 基础版 `case-template-generation-cec6f03af1aa438d9063`，执行 `case-generation-execution-3cdc55a569df45559870`；增强版 `case-template-generation-5d814822fb9143e69caa`，执行 `case-generation-execution-83cf033ef6644d589e76`。两版均 READY、两次执行均 PASSED，各一个 Variant，保留于用户日常数据库。
- 增强 `coverage-a72ec6b2f0e34cf3a4d2` 为 COMPLETED/FINISHED，round_used=1，两段测量 VALID，专属任务 completed 且 ended_at 已保存；公开 reason_codes 无内部待办。
- 实测解析范围为 **3/16 → 3/16 行**，未提升；独立复核拒绝三项 IGNORE，生成模型最终保留三项 UNRESOLVED。`attribution=UNVERIFIED`，不能把本次通过当作覆盖提升或业务场景完整证明。
- 报告重建 HTTP 200（ZIP），页面确认 10/20 14:46 的复测记录。私有验收材料在 `open-test-knowledge/.opentest/coverage-acceptance/20261020-reliability/`；不提交报告、凭据或真实业务 payload。
- 首次临时端口验收的模型误连原 8788 服务，发现后仅取消该模型、保留草稿，并在 8790 明确绑定工具 API 后接续同一任务；当时未发布或执行业务。未修改默认产品端口配置。
- 已停止本任务 8790 服务与 33379 隔离 MySQL，端口均无监听。8788 仍为开工前已存在的用户进程 77030，未擅自停止。OpenSpec change 与 44 项 current specs 严格校验通过。
