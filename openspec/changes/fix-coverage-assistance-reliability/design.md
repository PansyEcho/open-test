# 实施约束

## 证据与终态

dump/report 与 VALID/ANALYZING 原子保存之后，分析提交失败不能走采集失败路径。已有 analysis 时只续收尾。首次与恢复提交共用进程内 Future 去重，完成或提交失败释放登记，关闭线程池不另建替代池。

小终态在已有 system_transaction 内提交：重新读取工作流/owner、报告列状态及摘要、专属任务终态。只更新报告状态，不以旧 gzip 覆盖 result；coverage 报告读取在同一查询取 owner/status/payload，以列状态覆盖压缩包旧状态。Agent 证据读取、大包解析、prune 在终态事务外。

确需裁剪时，在已有 reason_codes 保存 `INTERNAL_REPORT_RETENTION_PENDING`；失败保留、成功清除。维护纳入该候选，只补裁剪。所有公开投影、模型上下文、任务摘要均过滤 `INTERNAL_` 前缀。终态不复活，重复 finish 不修改既定终态、ended_at 或已裁剪材料；历史半收尾可补齐。

## 恢复与所有权

同工作台原 owner 的 PID 明确不存在或可靠启动标识不同才可认定退出；心跳不足不能证明退出。健康其他 owner 只观察，无变化不写入。

事务外取得退出证据，system_transaction 内重新核对完整 owner、增强 revision、精确 Case 绑定，收尾旧进程遗留 RUNNING Case 后原子写入当前 owner 和增强 revision。即使测量无变化，也必须留下接管事实。所有专属 owner 写入和 sync_task 全量保存走同一系统锁并重新读取，防止旧 owner 写回。只接管 coverage 协调任务，不改补充 child 的 Agent owner。

活动 Agent、回执、web_run 或人工接续证据由原 web_generation 恢复/附着，覆盖层不能抢先结束。确认原 owner 退出且无可恢复派发证据、非明确 GATE_BUSY 时以 PARTIAL/派发结果未知结束，不重派。明确门禁拒绝保留同 child/request 的等待；坏候选逐条隔离。

## 源码与后继

完成可靠性阶段验收后再修改源码入口。显式 commit/tag 只能使用该 commit 的 clean、目标可解析、同扫描契约可用的扫描；允许可靠 PARTIAL，缺缓存先物化共享工具，真正无材料时明确提示系统页扫描。留空优先 QA 最新可用扫描，无法获得则走原基础路径并记跳过辅助原因，冻结实际 scan/commit。内部 start 支持指定 scan，不改系统 pin/latest、不扫描、不占全局扫描门禁，HTTP/MCP 仍同步返回 handoff。

从 Generation 沿 predecessor 链检查增强祖先，含循环/缺失保护；任意增强祖先不再次增强，未知只跳过辅助。普通无增强祖先 READY 后继可以作为基础。迟到发布保留既有 Generation 关联，不重开终态增强。页面投影后继并在点击时复核，唯一后继后端约束继续生效。

## 兼容和采集

保留 DATA_PREPARATION_FAILED 的正向目标前失败判定；无 TARGET 不能单独证明未调用。只补请求已发出但记录缺失的回归测试，不新增阶段字段。旧草稿回执缺 coverage_dispositions 按 [] 比较。可选上下文查询失败不阻断基础流程，精确执行绑定错误仍严格报错。

本地 WAR、普通 JAR、BOOT-INF 布局共用现有安全解压和业务类筛选；公司 FTP 保留已确认 WAR 布局。禁用天网重定向，reset 异常清理临时文件，BaseException 释放测量锁；准备/下载/分析超时分类区分，GET_LOCK NULL 不当作锁忙。

未消费旧字段、枚举、MATCHED、脱敏处理器保留；不做无关清理。
