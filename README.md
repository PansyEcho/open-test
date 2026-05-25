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

浏览器打开 `http://127.0.0.1:8787`，点击“一键跑通 MVP”即可按默认配置完成：

1. 创建本地项目
2. 选择 travelsystem 业务代码目录
3. 检测并选择 Codex / Claude Code
4. 绑定任意 Skill 目录
5. 生成并确认知识库
6. 生成并确认 CLI
7. 生成并确认 Case
8. 创建 snapshot
9. 不调用 LLM 执行主流程回归
10. 查看失败步骤、命令、stdout JSON、断言差异和绑定版本
