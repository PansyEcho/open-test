# 实施设计

以 [定稿开发计划](../../../docs/discussions/shared-baselines-case-publication-development-plan.md) 的第 3 至 13 节为数据结构、表字段、事务、迁移及验收设计。

## 关键决定

- 新增七张表并扩展五张现有表，不新增覆盖任务平台或文件式业务存储。
- 员工归属与执行工作台分离；本机内存登录及 MCP 凭据按各自生命周期校验。
- 个人草稿与当前共享指针分离；旧内容保留但不通过产品入口重新开放。
- 发布同步逐项短事务，复用工作流回执固定请求范围；外部调用与扫描不进入发布事务。
- 对象存储只发布上传完成的实际材料，使用标准 SDK 与 path-style；材料默认不过期。
- 测量锁为系统和环境，重试只属于原员工；未知业务结果不重放。
- 当前部署的隔离属于应用约束，不能阻止持有共享数据库和对象存储凭据者直接访问。

## 实施依赖

公司应用登记/回调和 newWorkId 字段契约按计划在真实登录验收前核实；UAT 网关与归档实物在对应联调前核实。缺失资料不得用伪造身份或 QA 回退代替验收，其他独立开发继续。

## 验证与交付

逐阶段完成最小相关验证，最终验证双用户、双机器、QA/UAT 和历史迁移闭环。所有代码遵循方法注释、日志上下文及参数设计要求；使用 OCR delegation 模式独立审查本次差异。完成前停止本次服务并检查 8788。

## 实际接入与切换

- 公司登录沿用 Demo 的公司授权策略和员工核验接口。默认回调来源为 `http://127.0.0.1:8788`，可由 `OPENTEST_PUBLIC_ORIGIN` 配置；浏览器和本机用户工具凭据一小时到期，服务重启后需重新登录。工具每次读取 `~/.opentest/credentials.json`，可由 `OPENTEST_CREDENTIAL_FILE` 指定本机路径。
- RustFS 使用知识目录父目录下的 `.opentest/object-storage.yaml`；endpoint、bucket、region、path-style 均可配置。凭据仅保存在忽略版本控制的本机配置中，本次不改变公司应用登记。
- 旧共享库必须先备份并停止旧写入客户端，再执行结构升级和历史回填。应用启动只读检查结构，未升级时明确拒绝启动，不偷偷执行 DDL。

以下从项目根目录执行。命令默认只读预览；核对后在相应命令末尾追加 `--apply` 才写入。两步按顺序执行，历史回填需要结构升级完成。

```sh
.venv/bin/python -m opentest.adapters.shared_schema_upgrade --knowledge-root open-test-knowledge
.venv/bin/python -m opentest.adapters.shared_history_migration --knowledge-root open-test-knowledge
```

历史预览中的未处置异常必须逐条修复，或明确提供 `--unavailable <原记录ID> --confirmed-by <员工newWorkId>`；该操作保留原数据，不能代替解决结构错误或本期功能缺陷。原源码可通过历史迁移命令的 `--source-baseline <基准ID> --source-repository <包含原commit的仓库>` 预览补传，再显式追加 `--apply`。缺少原始材料不得上传当前工作树冒充。

验收记录以 tasks.md 为准。公司策略接口连通、模拟公司边界的认证测试、HTTP 页面夹具以及隔离数据库演练，不等同于真实员工授权、真实 QA/UAT 业务执行或团队共享库已上线。
