# OpenTest

## V2：单系统DSF闭环

V2位于 `opentest` 包，使用FastAPI、Pydantic、Git Markdown/YAML知识真相和可删除重建的SQLite索引。当前验证目标是 `train-booking-core` 的 `TradeFacade#createOrder`；不使用向量数据库，也不验证跨系统知识。

安装开发依赖并启动：

```bash
python3 -m pip install -e '.[dev]'
uvicorn opentest.api:app --host 127.0.0.1 --port 8788
```

打开 `http://127.0.0.1:8788/console`。CLI可通过 `opentest --help` 查看；源码扫描还需设置 `--scriptgen-pythonpath` 或环境变量 `OPENTEST_SCRIPTGEN_PYTHONPATH`。

知识与Case位于 `open-test-knowledge/`；SQLite、扫描工具、任务、Snapshot、QA环境和运行报告位于被Git忽略的 `open-test-knowledge/.opentest/`。真实执行前按 [QA本地环境配置](docs/development/qa-environment.md) 创建本地YAML并通过环境变量引用密钥。

开发进度见 [docs/status.md](docs/status.md)，架构见 [docs/architecture/overview.md](docs/architecture/overview.md)。

## Legacy MVP

本项目是一个本地 Web MVP，用 Python 标准库实现后端服务和静态前端，不依赖外部安装包。

## 启动

```bash
python3 -m ai_test_platform.cli --host 127.0.0.1 --port 8787
```

可选数据目录：

```bash
AI_TEST_PLATFORM_HOME=/tmp/ai-test-platform python3 -m ai_test_platform.cli --port 8787
```

浏览器打开 `http://127.0.0.1:8787`。推荐手工操作顺序：

1. 创建本地项目
2. 选择 travelsystem 业务代码目录
3. 检测并选择 Codex / Claude Code
4. 进入 CLI 工具，生成并确认 CLI
5. 进入知识库，配置“从代码生成知识库的 Skill 目录”
6. 在知识库聊天页生成项目背景
7. 在右侧树点击某个接口，例如“创建订单”，通过聊天生成或重新生成子知识库
8. 点击子知识库查看内容，可人工编辑，也可通过内容中的知识链接跳转
9. 生成并确认 Case
10. 创建 snapshot
11. 不调用 LLM 执行主流程回归
12. 查看失败步骤、命令、stdout JSON、断言差异和绑定版本

也可以点击“一键跑通 MVP”，它会按 `CLI -> 知识库聊天 -> Case -> Snapshot -> 回归` 的顺序自动跑完。
