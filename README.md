# AI 自动测试平台 MVP

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
