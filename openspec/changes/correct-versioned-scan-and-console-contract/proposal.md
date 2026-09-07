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
- Case生成改为当前原生Agent通过prepare、受控源码、草稿校验和正式发布工具完成；网页只创建可恢复业务任务，不再后台启动交互Codex。
- Case问题、答案、草稿、revision和失败诊断持久化；正式Generation修订通过带predecessor的后继handoff/Generation完成。
- 扫描按组件区分完整、部分与失败；可靠部分结果可展示，无关warning不阻断，只有完整扫描成为知识与Case的新基线。
- 系统配置显式固定一个本地managed tag和完整Git commit；普通扫描只读取该不可变版本，只有“更新代码基准并扫描”才能切换版本。
- 兼容只含已确认历史执行字段的Case handoff，并按Redis初始化配置键聚合资源；未知历史字段和损坏记录仍严格拒绝。

## Out of Scope

- 不实现跨接口AI排序、批量调度器或额外调度状态。
- 不自动修改用户的`~/.codex/config.toml`。
- 不自动删除`open-test-knowledge/.opentest`中的本地运行证据。
- 不批量重算损坏归档摘要，不让部分扫描资源冒充新一代完整源码证据。
