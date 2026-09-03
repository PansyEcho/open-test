# OpenTest

OpenTest 是面向 DSF 系统的本地测试工作台。当前主线只保留四个页面入口：工作台、系统、知识库、回归 Case。页面、`$open-test` 与系统专属 Skill 共用 `opentest` 后端和 `/api/v2` 传输接口。

## 启动

```bash
python3 -m pip install -e '.[dev]'
uvicorn opentest.api:app --host 127.0.0.1 --port 8788
```

打开 `http://127.0.0.1:8788/console`。源码扫描还需在系统页面配置 scriptgen `agent-harness` 路径。

知识与不可变 Case Generation 位于 `open-test-knowledge/`；扫描任务、QA 配置和 Execution 报告位于 Git 忽略的 `open-test-knowledge/.opentest/`。真实执行前在系统页明确配置 QA 环境和 Operation 网关。

## 标准 SOP

1. 修复 Codex 环境：从 `~/.codex/config.toml` 删除无效的 `[agents] enabled=true`，保留 `[features] multi_agent=true`；重启 Codex，确认 OpenTest 插件已启用，并在新任务中确认 `$open-test-ifightchainsaas-java-refund-core` 可见。
2. 配置系统：填写代码库、扫描基线、QA 环境和 Operation 网关，保存后确认系统状态完整。
3. 扫描：确认接口、资源、调用关系和候选 Operation 已产生；先处理阻塞项，不复用旧扫描冒充成功。
4. 生成并发布知识：在页面点击“在 Codex 中生成”或使用 `$open-test`。发布知识版本并同步系统 Skill 后，可用 `$open-test-ifightchainsaas-java-refund-core 帮我退 pnr=xxx 的订单` 验证自然语言 Operation。
5. 只生成 Case：选择接口并点击“生成 Case”，或调用 `generate_interface_cases`。此阶段不得访问 QA；检查 Generation 的 `READY/PARTIAL/BLOCKED`、冻结 Variant 顺序和 Cleanup 完整性。
6. 显式执行：选择 QA 环境并点击“执行本次 Generation 的全部 Variant”，或调用 `execute_case_generation`。系统逐 Variant 严格执行 `DATA → TARGET → ORACLE → CLEANUP`。
7. 查看报告：按 `execution_id` 查看整体状态、逐阶段状态及有界脱敏输入/输出摘要。修复知识、数据或 Cleanup 后创建新的 Generation，再显式执行；旧 Generation 不原地修改。

`READY` 会执行全部 Variant；`PARTIAL` 只执行可运行 Variant并在报告中保留其余 `BLOCKED`；`BLOCKED/FAILED` 不允许启动。一次 Generation 可以多次显式执行，每次产生独立 `execution_id`。
