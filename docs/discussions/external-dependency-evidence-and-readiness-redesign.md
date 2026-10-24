# 外部依赖可用性与就绪诊断改造方案

日期：2026-10-25（第二版，supplement.core 已接入）。状态：设计方案，未实施。
适用 change：`share-code-baselines-and-publish-cases`，外部依赖部分建议单列 delta。

## 0. 结论

近几次 `billSupplement` 失败是同一类问题：

> 任务需要的外部接口/类型/数据对象，在"能不能用"这件事上有多个独立条件，但系统没有任何一处把这些条件**一次性检查并说明**。条件不满足时，各消费点只报自己那句"不可用"，于是只能一步一步试错。

`supplement.core` 已接入，说明问题不在"没接入"，而在下列三层中的某一层，而当前系统无法区分。

## 1. 分层诊断：外部接口为什么不可用

外部 DSF 依赖要被 Case 使用，必须依次通过三层。任何一层失败，当前都落到同一句"没有可见契约"。

### 第 1 层：provider 侧是否声明了这条路由

provider 的路由来自它自己扫描到的**发布声明**（发布 XML + 接口源码）：

- `_publish_operations` 从发布 XML 得到 `gsName`、`version`，再从接口源码的类头 `@Path` 或文件名推导 `service_name`（[dsf_operations.py:820-852](../../opentest/adapters/dsf_operations.py:820)）。
- 只有 `provider_system_id == 自身` 的定义才会写成"发布"，并带 `route_key`、`protocol='DSF'`（[system_relations.py:259-265](../../opentest/application/system_relations.py:259)）。

若 provider 的扫描没有包含对应发布 XML，或接口路径不在扫描范围，provider 侧就没有这条记录，`route_key` 为空。

### 第 2 层：两侧路由是否完全一致

调用方按 `route_key = [gsName, serviceName, version, action]` 精确匹配（[case_template_v4.py:1239](../../opentest/application/case_template_v4.py:1239)、[system_relations.py:561](../../opentest/application/system_relations.py:561)）。

调用方的 `serviceName` 来自引用 XML 属性；provider 的 `serviceName` 来自类头 `@Path` 或文件名推导。两者只要有一项不同（例如调用方 `distribution`、provider 推导成 `report`；或版本 `1.0.0.3` 对 provider 的 `1.0.0.14`），就**匹配不上**。

关系索引用的 `_discovery_route` 虽然忽略版本（[system_relations.py:368-386](../../opentest/application/system_relations.py:368)），但共享依赖查找用的是完整 `route_key`，两者口径也不一致。

### 第 3 层：provider 接口是否已发布、契约是否可见

即使路由匹配上，还要求：

- `ot_baseline_interface.availability='AVAILABLE'` 且 `current_interface_id` 已设置；
- 该版本契约 `READY`、请求/响应 Schema 闭合；
- 当前员工能在所选基准看到它（published，或 mine 视图下本人 READY 草稿）。

`resolve_downstream_operation` 生成的调用方本地定义只写 `ot_interface` + 零版契约，**没有容器行、没有作者、没有草稿**（[downstream_interfaces.py:295-329](../../opentest/application/downstream_interfaces.py:295)），所以它永远不满足第 3 层。

### 结果

三层任一失败 → `read_outer_api_info` 报"没有可见契约"。用户和 Agent 都无法知道是"provider 没声明"、"路由不一致"还是"没发布"，只能反复尝试。

## 2. 目标：一次说清，而不是逐个试错

引入**依赖就绪评估**（只读），输入"任务要用的外部操作 + 固定扫描"，输出完整状态与恢复动作：

| 状态 | 判定 | 恢复动作 |
| --- | --- | --- |
| `SHARED_READY` | 三层全过 | 直接选用 |
| `PROVIDER_ROUTE_NOT_FOUND` | 所有已接入系统都没有该路由 | 列出被检查的系统；提示接入/重扫 provider 或使用本任务解析证据 |
| `PROVIDER_ROUTE_MISMATCH` | 有同 action 的候选但 gs/service/version 不一致 | 列出每个候选的差异分量，允许显式 `provider_baseline_id` 选择 |
| `PROVIDER_CONTRACT_UNPUBLISHED` | 路由匹配但没有可见契约 | 提供"发布该接口"动作；`mine` 视图可用本人 READY 草稿 |
| `TASK_RESOLVED_READY` | 调用方固定源码 + 依赖字节码解析、结构闭合、已登记 | 允许本任务使用，标注"未共享" |
| `EVIDENCE_GAP` | 结构闭合但枚举取值等证据缺失 | 列出缺口；场景标记为不可生成，不阻塞其他场景 |
| `ABSENT` | 无法解析路由或 Schema | 阻塞 |

`read_outer_api_info`、`execute_operation`、源码工具、失败摘要全部消费同一份评估结果，不再各写一句。

## 3. 改造内容

### A. 路由匹配升级为"分项诊断"

`_shared_provider_candidates` 现在只做完整 `route_key` 等值查询。改为两步：

1. 先按完整路由精确匹配（保持现状语义）；
2. 未命中时，按 `action` + 方法符号在全部已接入系统中找候选，逐个比较 `gsName`、`serviceName`、`version`、`action`，输出差异。

不自动放宽匹配：差异候选只作为**可选**项返回，由调用方显式选择（`provider_baseline_id`），避免误连到不同版本的服务。

### B. 解析结果进入可用生命周期

`_register_resolved` 增加两步（幂等）：

1. `ensure_interface(scope, operation_id)` 生成稳定的 `ot_baseline_interface` 容器（`UNPUBLISHED`）；
2. 零版契约写入 `author_user_id`（解析者）。

这样 `InterfaceKnowledgeRef.baseline_interface_id` 有真实值，现有发布、覆盖、依赖记录都不用改结构。

### C. 两种证据等级

- `SHARED`：provider 已发布、三层全过。现有路径不变。
- `TASK_RESOLVED`：调用方固定源码 + 依赖字节码解析、路由由 `sof:reference` 证明、请求/响应 Schema 闭合、已在同一固定扫描登记。

`_visible_dependency_knowledge` 增加 `TASK_RESOLVED` 分支，放行条件全部满足才生效：

- `kind == EXTERNAL_DSF` 且 `provider_definition.dependency_coordinate` 非空；
- `provider.system_id == handoff.system_id`（不跨基准）；
- 同一固定扫描存在已登记契约且 Schema 闭合；
- 容器行属于当前基准。

使用时的边界：

- 可用于数据准备、上游触发、目标调用；
- 不能充当只读查询，除非分类为 `READ_ONLY`；
- **共享发布 Case 时要求该依赖已 `SHARED`**，否则拒绝并指出要发布的接口与基准（其他员工没有同一份字节码证据，不共享不可复现）。

### D. 依赖证据缺口前置

1. `DsfOperationDefinition` 增加 `evidence_gaps: list[str]`。
2. `type_schema` 生成枚举时，若 sources.jar 缺失，记录 `<coordinate>: <Type> 枚举值映射未知`；DTO 分支未闭合同样记录。
3. `read_outer_api_info`、`get_operation`、数据任务 `read_contract` 返回 `evidence_gaps`。
4. Case 生成在 `start` 与首次提交时检查：请求值引用了"取值映射未知"的字段 → 该场景标记不可生成并给出恢复动作（安装 sources.jar / 配置依赖源码），其余场景继续。
5. 不把常量名当 `getCode()` 值。

### E. 任务开始前的外部依赖体检

在 Case 生成任务进入 Agent 探索之前，对目标接口**可达调用图中的全部 DSF 引用**执行第 2 节的评估，一次性返回：

```json
{"blockers": [
  {"code": "PROVIDER_ROUTE_MISMATCH", "operation": "dsf:...:reportQueryList",
   "checked_systems": ["account-supplement-core"], "diff": {"service": ["distribution", "report"]},
   "recovery": {"action": "choose_provider_baseline", "params": {"system_id": "...", "baseline_id": "..."}}}
]}
```

- 可达图来自扫描的调用边，不需要 Agent 先探索；
- 只报告问题项，不阻塞读取源码；
- 若目标可达的 DSF 引用很多，按"是否被目标方法直接/间接调用"排序并设上限，超出部分标注未检查。

这样本次 `reportQueryList` 会在开工时就以"路由不一致"或"接口未发布"出现，而不是等 Agent 试到一半。

### F. 数据能力就绪

在草稿提交前做一次只读比对：从目标与已选依赖的请求 Schema 提取业务身份字段（补单 ID、账单、订单号等），与可用数据函数输出比对，缺失项输出：

```json
{"code": "DATA_CAPABILITY_GAP", "object": "supplementId",
 "recovery": {"action": "create_data_function", "inputs": ["..."]}}
```

复用现有数据函数 Schema，不新增场景模型。

## 4. 改动清单

| 文件 | 改动 |
| --- | --- |
| `downstream_interfaces.py` | 分项路由诊断；`_register_resolved` 建容器、带作者、记录 `evidence_gaps` |
| `domain/models.py` | `DsfOperationDefinition.evidence_gaps` |
| `case_template_v4.py` | `_visible_dependency_knowledge` 增加 `TASK_RESOLVED`；任务启动前依赖体检 |
| `operation_contract_store.py` | `register_operation` 返回 `interface_id` |
| `publication.py` | 共享发布校验依赖已 `SHARED` |
| `data_capabilities.py` | 数据能力就绪（只读） |
| `web_generation.py` | 拒绝信息改为消费统一就绪结果 |

不新增表、列、服务或持久缓存。

## 5. 分阶段与验收

1. **A + E**：分项诊断 + 开工体检。验收：原任务在 Agent 开始前就报告 `reportQueryList` 的具体差异分量或"未发布"。
2. **B + C**：解析结果可用。验收：provider 未发布时也能在任务内选中并进入执行目录，结果页标注"未共享依赖"。
3. **D**：证据缺口前置。验收：`ReportSourceEnum` 缺口在选中时即可见，不再出现源码越权尝试。
4. **F**：数据能力就绪。验收：缺少补单 ID/账单的场景在提交草稿前给出明确缺口。

## 6. 复杂度门禁

| 机制 | 独立需求 | 真实消费者 | 失败模型 | 改变的决策 |
| --- | --- | --- | --- | --- |
| 分项路由诊断 | 用户要求不再逐个试错 | `read_outer_api_info`、失败摘要 | 已复现：路由不一致被报成"没有可见契约" | 下一步动作 |
| 任务前依赖体检 | 同上 | 任务启动、Agent 上下文 | 已复现：试到一半才发现依赖不可用 | 是否开始生成 |
| `TASK_RESOLVED` 等级 | 用户要求能真正使用上游接口 | Case 编译、执行目录 | 已复现：已解析却不可选用 | 是否允许本任务使用 |
| `evidence_gaps` | 已复现的枚举缺口 | 工具返回、失败摘要 | sources.jar 缺失导致反复试读 | 场景是否可生成 |

## 7. 不做

- 不自动放宽路由匹配、不自动选择不同版本的 provider；
- 不自动发布任何契约、不自动接入 provider；
- 不为未共享依赖放宽只读或分类规则；
- 不猜测枚举取值、不伪造业务身份；
- 不新增场景建模框架或工作流引擎。
