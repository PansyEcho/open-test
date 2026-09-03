# Change: 收敛OpenTest主线并分离Case生成与执行

## Why

当前控制台同时暴露V2、V3和V4 Case链路，V4 DSL提交还可在生成后自动访问QA。插件状态检查又会把Codex配置解析失败误报为插件未安装，导致知识生成和系统Skill均不可用。需要保留唯一Case实现、把生成与执行拆成两个明确动作，并给用户一条可重复的SOP。

## What Changes

- Case只保留CaseTemplate编译器和执行器，公共接口统一到`/api/v2`且不再向用户展示内部版本名。
- Case生成只编译、校验和持久化，显式执行接口才允许访问QA。
- 为一次Generation保存独立Execution历史，按冻结Variant顺序执行并保留DATA、TARGET、ORACLE和CLEANUP证据。
- 控制台收敛为工作台、系统、知识库和回归Case四个入口。
- 区分Codex配置错误、插件缺失和插件禁用，并同步更新OpenTest系统Skill。
- 删除legacy MVP和已被唯一主线取代的V2/V3 Case入口及跟踪资产；Git外真实执行证据不自动删除。

## Out of Scope

- 不实现跨接口AI排序、批量调度器或额外调度状态。
- 不自动修改用户的`~/.codex/config.toml`。
- 不自动删除`open-test-knowledge/.opentest`中的本地运行证据。
