## 1. 生成与执行分离

- [x] 1.1 增加独立Execution领域模型、私有存储和显式应用服务
- [x] 1.2 删除生成模式和DSL提交自动执行分支，保证生成阶段零QA访问
- [x] 1.3 增加写接口Cleanup门禁及finally执行证据
- [x] 1.4 将唯一Case API发布到`/api/v2`并更新插件MCP工具

## 2. 控制台与SOP

- [x] 2.1 收敛四个页面入口并删除旧Case、自然语言、MVP、Suite页面逻辑
- [x] 2.2 在回归Case页提供独立生成、执行、历史和报告
- [x] 2.3 更新README和通用SOP，移除legacy启动说明

## 3. 插件与Skill

- [x] 3.1 修正配置错误、插件缺失和插件禁用的错误分类
- [x] 3.2 更新全局及系统Skill的生成、执行和查询语义
- [ ] 3.3 校验并重新安装本地插件，确认新任务可发现正确Skill名（源码校验已通过；实际重装被`~/.codex/config.toml:24`的无效`[agents] enabled=true`阻塞，需用户修复配置并重启Codex后完成）

## 4. 清理与验证

- [x] 4.1 删除legacy包、脚本及被替代的V2/V3 Case代码和跟踪资产
- [x] 4.2 覆盖生成零QA、显式执行、重复执行、Cleanup和插件诊断测试
- [x] 4.3 通过运行中HTTP服务验证新页面版本与完整SOP
- [x] 4.4 运行OpenSpec strict和OCR delegation审查并处理结论
