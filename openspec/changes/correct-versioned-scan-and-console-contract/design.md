# 单主线Case生命周期设计

## Decision

`POST /api/v2/systems/{system_id}/case-generations`只创建Codex handoff。DSL提交完成后写入不可变Generation并结束生成状态，不调用Operation。`POST /api/v2/systems/{system_id}/case-generations/{generation_id}/executions`创建独立Execution，按Generation中冻结的Variant顺序串行执行。一次Generation可多次显式执行，但同一环境同时只能有一个RUNNING Execution。

写接口模板必须包含结构化Cleanup。缺少或无效Cleanup的Variant仍保存在Generation中，但带阻塞原因且执行器不得调用其TARGET。已尝试TARGET后，无论TARGET或ORACLE结果如何都在finally语义中尝试Cleanup；Cleanup失败使Variant失败，并保留各阶段证据。

公共API使用`/api/v2`作为传输协议版本。领域类和历史JSON暂保留内部V4 contract字符串以严格读取既有不可变产物，但页面、文档和Skill不展示V2/V3/V4产品代际。

## Plugin diagnostics

插件清单命令非零退出时先返回经过脱敏的真实配置诊断。只有清单命令成功后，才根据清单区分未安装与禁用。任何前置失败都发生在线程创建和模型调用之前。

## Rollout

前端行为变化同步更新页面版本和静态资源URL。插件Skill修改后更新manifest cachebuster、校验插件并从现有本地marketplace重新安装；新任务用于验证新Skill。
