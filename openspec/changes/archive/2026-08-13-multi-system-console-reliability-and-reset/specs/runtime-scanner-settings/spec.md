## ADDED Requirements

### Requirement: scriptgen 在每次扫描前动态解析并验证

系统 SHALL 按环境变量、本地运行设置、已安装模块的优先级动态选择 scriptgen，并在提交任务前验证目录、模块入口和启动能力。

#### Scenario: 本地设置提供有效路径
- **WHEN** `.opentest/settings.yaml` 指向可启动的 scriptgen agent harness
- **THEN** PyCharm 与终端启动的 OpenTest 均报告扫描器就绪并可提交扫描

#### Scenario: 配置路径无效
- **WHEN** 所有候选均不可用
- **THEN** 页面禁用自动扫描并展示稳定修复建议，后端拒绝请求且不创建必然失败的任务

### Requirement: 本地运行设置不进入共享产物

系统 SHALL 以 `0600` 原子写入 Git 忽略的本地设置，并不得把路径以外的本机敏感配置复制进日志、Agent 输入、Snapshot 或报告。

#### Scenario: 更新扫描器路径
- **WHEN** 回环客户端保存新的 scriptgen 路径
- **THEN** 后续扫描立即使用新设置，无需重启 Uvicorn
