## Context

示例系统真实审计得到90个Facade、36个Job和126个scriptgen工具，另外3个工具来自legacy固定shim，因此V2必须以scriptgen `scan-manifest.json` 与 `tool-manifest.json` 为唯一工具来源。源码仓库可能处于dirty状态，扫描结果必须能够重现其精确基线。

## Goals / Non-Goals

**Goals:**

- 在不修改业务源码的前提下捕获Git基线并运行真实扫描。
- 输出结构化入口、逻辑工具、状态机转换和可核查源码位置。
- 让扫描成为带 `task_id` 的本地长任务，日志可按系统与任务关联。
- 明确分离Git真相元数据和可删除的大型工具产物。

**Non-Goals:**

- 不追踪Facade后的完整调用图，不生成业务规则正文。
- 不生成Case，不调用QA环境，不验证跨系统入口。
- 不把HTTP网关地址当作场景的稳定工具标识。

## Decisions

### Git基线包含dirty摘要

commit和branch通过只读Git命令获取。dirty摘要对已跟踪diff和未跟踪文件的相对路径、大小与内容摘要做稳定哈希，避免只记录 `dirty=true` 却无法判断两次扫描是否相同。不得把源码内容写入日志。

### scriptgen适配器不做业务兜底

适配器执行 `python -m cli_anything.scriptgen build-tools`，验证两个manifest并将原始工具ID规范为逻辑工具ID。运行失败时任务失败并保留精简日志证据；不补固定工具、不伪造入口。

### 扫描产物分层

`source.yaml`保存最新源码基线；`.opentest/scans/<system_id>/<scan_id>.json`保存结构化扫描结果；`.opentest/tools/<system_id>/<scan_id>/`保存scriptgen生成脚本。后两者均可由源码重建且不提交Git。扫描manifest记录经过源码根范围校验的绝对源码/工具路径及对应相对证据路径，Snapshot后续绑定其摘要。

发布采用两阶段顺序：先准备不可变manifest，再原子更新单系统 `source.yaml`，最后原子切换 `latest.json`。一期扫描在应用内串行，扫描前后基线不一致时不发布latest。

### Java结构扫描独立于scriptgen

状态机 `@State(from,to)` 和MQ监听注解通过只读Java文本扫描补充。解析器输出节点、转换、注解行与源文件，不把状态机伪装为可执行工具。无法解析的注解进入warnings而不是猜测。

## Risks / Trade-offs

- [正则无法覆盖完整Java语法] → 一期只解析已知注解形态并保留warning，后续可替换JavaParser适配器。
- [dirty内容哈希成本] → 只在显式扫描时计算，跳过target与Git内部文件。
- [scriptgen输出契约变化] → 入口处严格校验manifest版本和必要字段，给出明确失败。
- [本地工具路径不可移植] → 通过配置注入，并在缺失时返回结构化配置错误。

## Migration Plan

1. 为一期系统捕获基线并运行真实扫描。
2. 验证结果只含scriptgen真实工具，数量与manifest一致。
3. 用 `TradeFacade#createOrder` 和至少一个状态机做结构断言。
4. 后续知识change只读取V2扫描产物，不读取legacy草稿。

## Open Questions

MQ框架在目标仓库中的全部注解形态可能不止一种；本change先记录已识别形态和warning，知识纵向切片再补目标系统实际模式。
