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

- [x] 3.1 完成旧App Server插件前置错误分类（该后台前置检查由5.4移除，项目仍校验并同步自有Skill源码）
- [x] 3.2 更新全局及系统Skill的生成、执行和查询语义
- [ ] 3.3 校验并重新安装本地插件，确认新任务可发现正确Skill名（源码校验已通过；实际重装被`~/.codex/config.toml:24`的无效`[agents] enabled=true`阻塞，需用户修复配置并重启Codex后完成）

## 4. 清理与验证

- [x] 4.1 删除legacy包、脚本及被替代的V2/V3 Case代码和跟踪资产
- [x] 4.2 覆盖生成零QA、显式执行、重复执行、Cleanup和插件诊断测试
- [x] 4.3 通过运行中HTTP服务验证新页面版本与完整SOP
- [x] 4.4 运行OpenSpec strict和OCR delegation审查并处理结论

## 5. 原生Agent、修订与扫描恢复

- [x] 5.1 增加Case业务任务、持久草稿/问答、revision与request_id并发幂等协议
- [x] 5.2 拆分草稿校验与正式发布，支持READY/PARTIAL/BLOCKED的安全发布条件
- [x] 5.3 增加continue与regenerate_latest后继handoff/Generation并保持旧产物不可变
- [x] 5.4 增加通用任务列表、上下文和网页待接手/恢复入口，移除后台Case Codex启动
- [x] 5.5 增加扫描组件完整性、部分资源来源合并和真实探测时间
- [x] 5.6 覆盖并发、幂等、中断恢复、无QA生成、资源与页面HTTP回归
- [x] 5.7 固定Git系统managed tag与完整commit，普通扫描只使用pin，并按路径、commit和分析器兼容性修正知识新鲜度
- [x] 5.8 精确兼容两个历史Case handoff执行字段，并验证未知字段、幂等和新建任务不受旧记录阻断
- [x] 5.9 聚合真实Redis初始化bean、修正待关注任务栏与基准展示，并完成随机端口页面及原生Skill回归
- [x] 5.10 解除已退役Facade HTTP脚本对源码扫描的错误门禁，并保留Job工具严格就绪校验
- [x] 5.11 让扫描历史、任务结果和页面提示一致保留partial projection业务状态
