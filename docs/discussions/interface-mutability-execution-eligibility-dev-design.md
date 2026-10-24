# 接口读写分类与执行资格 开发详设

日期：2026-10-25（实施版）。状态：开发、专项回归及独立复审通过；原任务业务 Case 验收未完成，详见选定 change 的 P18 任务。
上游设计：[接口语义分类与上游触发 Case 设计](interface-effects-and-upstream-case-design.md)。本文只承接「读写语义分类 + 执行资格」部分，上游触发与数据闭环不在本文范围内（另立 change）。

适用 OpenSpec change：`share-code-baselines-and-publish-cases`。

## 0. 结论摘要

| 阶段 | 内容 | 规模 | 目的 |
| --- | --- | --- | --- |
| P0 | 分离「读写分类」与「执行资格」；按当前规则重算存量扫描的执行资格 | 3 处判断 + 1 处文案 + 资格重算 | 让原固定扫描的 `billSupplement` 真正解除误阻塞 |
| P1 | 契约修订承载 AI 读写分类与证据；按精确修订在四个消费点叠加 | 2 个模型 + 4 处叠加 + 草稿/作者接通 | 让 AI 分类进入执行链，且不影响他人 |
| P2 | 目标为 UNKNOWN 时暴露「未分析」并按需创建契约补充任务 | 复用 `contract-completion` 任务链 | 让分类可补，不自动烧模型 |

不做的事：不在基准流水线里调用 AI、不新增表/列、不改扫描启发式动词表、不做上游触发。

## 1. 根因（已核实）

| 现象 | 位置 | 结论 |
| --- | --- | --- |
| 生成 Case 报 `CaseTemplate target Operation is not executable` | [case_template_v4.py:1570](../../opentest/application/case_template_v4.py:1570) | 报错把真实原因丢掉了 |
| 真实原因 | [operations.py:598-599](../../opentest/application/operations.py:598) | `mutability == UNKNOWN` 被写成 `blocked_reason`，于是 `executable=False` |
| UNKNOWN 的来源 | [dsf_operations.py:890](../../opentest/adapters/dsf_operations.py:890) | 纯方法名/action 动词表，`billSupplement` 不命中 |
| 入口不一致 | [operations.py:2484](../../opentest/application/operations.py:2484)、[dsf_operations.py:387](../../opentest/application/dsf_operations.py:387) 阻塞；[operations.py:510](../../opentest/application/operations.py:510)、[dsf_operations.py:459](../../opentest/application/dsf_operations.py:459) 放行 | 同一接口从 Facade 和外部 DSF 进入结论不同 |
| 执行资格在扫描时被持久化 | [system_relations.py:243](../../opentest/application/system_relations.py:243)、[operations.py:217](../../opentest/application/operations.py:217) | 改判定规则不改变已发布扫描 |
| 扫描定义整体比较，不能新增键 | [system_relations.py:220-225](../../opentest/application/system_relations.py:220) | 除 `resolved_operation` 外任何差异都会报"原始事实冲突" |
| 分类无处落库 | [models.py:479](../../opentest/domain/models.py:479) | 契约没有 mutability |
| 契约补充未绑定作者与本人草稿 | [operation_contract_store.py:257](../../opentest/adapters/operation_contract_store.py:257)、[publication.py:336](../../opentest/application/publication.py:336) | 新版本没有 `author_user_id`，`save_interface_draft` 会拒绝 |
| 规则与现行 spec 冲突 | [codex-system-operations/spec.md:33](../../openspec/specs/codex-system-operations/spec.md:33) vs [autonomous-offline-testing/spec.md:47](../../openspec/specs/autonomous-offline-testing/spec.md:47) | 后者已写明「授权任务可执行、但不得充当只读观察」 |

## 2. 目标规则

分类来源优先级：

1. 契约中**已分析**的分类（`mutability_analyzed = true`），包括分析后仍为 UNKNOWN
2. 扫描启发式
3. 都没有 = UNKNOWN

| 状态 | 表示 | 对扫描 READ_ONLY 的影响 |
| --- | --- | --- |
| 未分析 | `mutability_analyzed=false` | 沿用扫描分类 |
| 已分析·只读 | `READ_ONLY, analyzed=true` | 允许只读 |
| 已分析·写入 | `WRITE, analyzed=true` | 撤销只读 |
| 已分析·无法确定 | `UNKNOWN, analyzed=true` + 原因 | **撤销只读**，只允许按潜在写操作执行 |

| 使用位置 | READ_ONLY | WRITE | UNKNOWN |
| --- | --- | --- | --- |
| 已授权 QA/UAT 的 Case 目标、触发动作 | 允许 | 允许 | 允许，按潜在写操作执行 |
| DATA 中明确创建/调整步骤 | 允许 | 允许 | 允许，必须回查 |
| 数据查询、验证、只读 Oracle、轮询 | 允许 | 不允许 | 不允许 |
| 路由缺失、契约缺字段、环境错误、超出任务范围 | 阻塞 | 阻塞 | 阻塞 |

## 3. P0：执行资格

### 3.1 判定规则改动

| 文件 | 位置 | 改动 |
| --- | --- | --- |
| `opentest/application/operations.py` | `_facade_capability` | 删除 `elif mutability == UNKNOWN` 分支；把阻塞条件抽成 `_facade_execution_blocker(entry, provider_count, request_template)` 供 3.2 复用 |
| `opentest/application/operations.py` | `_validate_request` | 条件简化为 `not capability.executable` |
| `opentest/application/dsf_operations.py` | `execute_indexed` | 删除 UNKNOWN 拦截 |
| `opentest/application/case_template_v4.py` | `_compile_draft` | 报错带上 `operation_id` 与 `blocked_reason` |

抽取后的 `_facade_execution_blocker` 只检查固定扫描中的 provider 唯一性、`contract_gap` 和请求模板是否为字典。UNKNOWN 不参与资格判断，不重新解析源码、重建 Schema、读取知识摘要或更新 workspace_revision。

### 3.2 存量扫描的执行资格重算

旧扫描在 `$.operation` 中保存了 UNKNOWN 阻塞。旧判断位于 `contract_gap` 之前，因此不能直接清空原因。

实施采用更小的修复：`derive()` 从数据库或现有 `.interfaces.json` 读出能力后，只识别旧的精确阻塞原因 `Facade操作的读写属性尚未确定。`。针对这些条目读取原 Manifest，复用资格判断函数，仅更新内存能力的 `executable` / `blocked_reason`，并写入既有本地缓存。

- 不新增 `operation_current`、派生版本号或共享持久状态；
- 不修改数据库中的原始 `operation`、后补定义、引用或契约；
- 不重建 Schema、字段证据、说明、来源和 workspace_revision；
- 修正后的缓存不再含旧阻塞原因，后续读取无需重复加载 Manifest；缓存删除后从相同原始事实重建；
- `SystemRelationService.prepare_interfaces` 的事实一致性比较保持原样。使用原扫描事实重放不会因本次修复产生冲突；不承诺重新派生所有业务字段仍与历史快照相等。

验收：冷/热读取一致；除两个资格字段外逐项不变；带 `contract_gap` 的扫描仍然阻塞；共享事实修复前后完全相同。

### 3.3 必须保留的行为

- [case_template_registries.py:132](../../opentest/application/case_template_registries.py:132)、[case_template_compiler_v4.py:244](../../opentest/application/case_template_compiler_v4.py:244)、[data_capabilities.py:519](../../opentest/application/data_capabilities.py:519) 三条只读门禁不变。
- 请求去重、任务授权、环境校验、参数 Schema 校验、真实绑定与契约缺口阻塞不变。

## 4. P1：数据改造

### 4.1 契约模型新增字段

`OperationInputKnowledgeContract`：

```python
mutability: Literal["READ_ONLY", "WRITE", "UNKNOWN"] = "UNKNOWN"
mutability_analyzed: bool = False
mutability_reason: str = Field(default="", max_length=1_000)
mutability_evidence_refs: list[SourceReference] = Field(default_factory=list)
```

- 零版契约保留默认 `mutability=UNKNOWN`、`mutability_analyzed=false`，有效分类仍来自扫描；
- 只有经 `supplement()` 写入的修订才可能 `true`；
- `analyzed=true` 时 `mutability=UNKNOWN` 合法且有意义（撤销只读）。

约束：`contract_revision == 0` 时 `analyzed` 必须 false；`analyzed` 且非 UNKNOWN 时证据不得为空；`analyzed` 且 UNKNOWN 时原因不得为空。

零版构造保持不变，避免新增提示字段导致历史零版重放内容冲突。消费方在未分析时读取扫描分类。

### 4.2 补充请求模型

`OperationContractSupplement` 增加 `mutability: Literal[...] | None = None`、`mutability_reason`、`mutability_evidence_refs`。`None` 表示不改分类。工具 Schema 由模型自动生成（[data_capabilities.py:217](../../opentest/application/data_capabilities.py:217)）。

### 4.3 服务端校验（修正 UNKNOWN 分支）

```python
if request.mutability is not None:
    if request.mutability == "UNKNOWN":
        evidence = []
        if request.mutability_evidence_refs:
            reachable = self._reachable_methods(manifest, operation_id)
            evidence = self._validate_evidence(request.mutability_evidence_refs, manifest, reachable, source_root)
    else:
        reachable = self._reachable_methods(manifest, operation_id)
        evidence = self._validate_evidence(request.mutability_evidence_refs, manifest, reachable, source_root)
        if request.mutability == "READ_ONLY":
            if {(e.path, e.line) for e in evidence} != {(r.path, r.line) for r in reachable.values()}:
                raise KnowledgeValidationError("只读分类必须覆盖目标入口的全部可达方法")
            if _scan_mutability(operation) == DsfOperationMutability.WRITE:
                raise KnowledgeValidationError("扫描事实含写操作，不能补充为只读")
```

要点：

- UNKNOWN 无证据时直接保存原因；有证据时才按可达方法构造并校验，不会因为现有 `supplement()` 里 `reachable` 默认为 `{}` 而误拒；
- WRITE 只需一条可达方法证据；
- READ_ONLY 要求覆盖全部可达方法，且与扫描写事实冲突时拒绝；
- 分析后 UNKNOWN 显式覆盖扫描 READ_ONLY，撤销只读资格。

### 4.4 保存与本人草稿的接通

现状：`OperationContractStore.save()` 的共享路径只 INSERT `(interface_id, revision, contract_json)`（[operation_contract_store.py:257](../../opentest/adapters/operation_contract_store.py:257)），没有 `author_user_id`；而 `save_interface_draft()` 要求 `content["author_user_id"] == scope.user_id`（[publication.py:336](../../opentest/application/publication.py:336)）。因此"保存新修订 → 新 Case 就能冻结"目前不成立。

补齐：

1. `OperationContractStore.save()` 增加 `author_user_id` 参数并写入该列；历史文件存储格式不增加作者字段；运行模式仍为 MySQL-only。
2. `supplement()` 的起始版本不再取存储层 latest：契约任务创建时把 `contract.contract_revision` 写入 handoff，补充内容从精确冻结修订读取；`latest+1` 仅分配新序号，不继承其内容。个人草稿和发布指针使用各自独立的 CAS 修订。
3. 保存后在同一系统事务内调用 `save_interface_draft(PublicationScope(system_id, baseline_id, user_id), InterfaceDraftUpdate(...))`，推进本人接口草稿引用：

```python
InterfaceDraftUpdate(
    operation_id=operation_id, interface_id=interface_id,
    contract_revision=new_revision, status="READY" if ... else "INCOMPLETE",
    expected_draft_revision=..., expected_publication_revision=...,
)
```

4. 共享视图不自动变化：仍需走现有发布流程（`publish_interface`），发布后才对其他员工生效。
5. 作者不是任务员工时拒绝。

### 4.5 分类叠加位置：按精确修订，覆盖四个消费点

**不能**在 `OperationCapabilityCatalog.derive()` 里按 `ot_interface.latest_contract_revision` 全局叠加：它是存储层最新版本，包含未发布草稿，且 `derive()` 没有员工/基准/视图上下文。

叠加函数：

```python
def _apply_mutability(capability, contract) -> OperationCapability:
    """用已解析的精确契约修订覆盖读写分类；其余字段不变。"""
    if contract is None or not contract.mutability_analyzed:
        return capability
    return capability.model_copy(update={"mutability": OperationMutability(contract.mutability)})
```

四个消费点：

| 消费点 | 位置 | 修订来源 | 说明 |
| --- | --- | --- | --- |
| Case 运行时能力 | `_runtime_capabilities`（[case_template_v4.py:3610](../../opentest/application/case_template_v4.py:3610)） | 每个 `scope.contract_revisions`；目标由 [case_template_v4.py:308](../../opentest/application/case_template_v4.py:308) 冻结 | 只覆盖已选操作 |
| 发现索引 | `get_handoff()` 的 `indexed_capabilities`（[case_template_v4.py:735-753](../../opentest/application/case_template_v4.py:735)） | 候选可见契约修订（`list_interface_summaries` 的 `contract_revision`） | **不能复用已选列表**：该索引刻意另读全量目录，否则刚建任务时查询接口还没被选中，Agent 找不到它们（[case_template_v4.py:729-730](../../opentest/application/case_template_v4.py:729) 注释） |
| 外部接口展开 | `read_outer_api_info`（[case_template_v4.py:992](../../opentest/application/case_template_v4.py:992)） | `_visible_dependency_knowledge` 已解析的 `fixed_contract` | 在 `_operation_descriptor` / `runtime_registry` 之前叠加 |
| 数据任务读取 | `read_contract`（[data_capabilities.py:406-416](../../opentest/application/data_capabilities.py:406)） | 已解析的 `contract` | 在 `_operation_descriptor` 之前叠加 |

规则：

- 只改 `mutability`，不改 `executable` / `blocked_reason`；
- 未分析时沿用扫描值；旧任务缺少冻结修订按修订 0 处理，不跟随 latest；
- 叠加结果不写回 `.interfaces.json`。

### 4.6 消费方清单

| 消费方 | 是否改动 |
| --- | --- |
| `OperationCapabilityCatalog.derive` | 只加 P0 的资格重算 |
| `_runtime_capabilities` / 发现索引 / `read_outer_api_info` / 数据任务 `read_contract` | 加分类叠加 |
| Runtime 函数只读标记、查询/验证门禁、数据函数查询门禁 | 不改，自动读叠加后的值 |
| `_validate_request`、`execute_indexed` | P0 改 |
| Case 目标上下文 | 加分类、分析状态与原因 |
| 覆盖增强 | 不改 |

## 5. P1：流程改造

### 5.1 AI 分析流程（契约补充任务）

| 任务链 | 创建位置 | 任务类型 | 可用工具 |
| --- | --- | --- | --- |
| 知识长文 | `prepare_native_knowledge_generation`（[foundation.py:3862](../../opentest/application/foundation.py:3862)） | `knowledge-codex-client-handoff` | 知识正文 |
| 契约补充 | `prepare_data_capability(kind="contract")`（[data_capabilities.py:129-149](../../opentest/application/data_capabilities.py:129)） | `contract-completion` | `supplement_contract` |

必须走后者。

流程：页面按 Case 冻结的 `source_scan_id` 创建契约任务 → Agent 读实现与可达方法 → `supplement_contract` 提交分类与证据 → 服务端校验、写版本、写作者、推进本人草稿 → 重新开始时 Case 冻结新修订。

**必须补的缺口**：现有入口固定读 `latest`（[data_capabilities.py:125](../../opentest/application/data_capabilities.py:125)）。改为请求携带显式 `scan_id`/`baseline_id`，核验该扫描属于目标基准后构造 `_source_scopes`；扫描不存在时明确报错，不回退 latest。

### 5.2 Agent 上下文

`read_context` 增加：

```json
{"mutability": "UNKNOWN", "mutability_analyzed": false, "mutability_reason": "",
 "evidence_count": 0}
```

分析说明追加：任一可达分支写入即 WRITE；READ_ONLY 必须覆盖全部可达方法；无法确认时提交 UNKNOWN 并写明原因。

### 5.3 界面

四态展示：`未分析` / `已分析·只读` / `已分析·写入` / `已分析·无法确定（原因）`；`related_interface_index` 追加 `mutability_analyzed`、`mutability_reason`；未分析时提供跳转到契约补充任务的入口并注明基准与扫描；前端资源更新 `?v=` 并在运行中的 HTTP 服务验收。

## 6. P2：按需分析

- Case handoff 的 `target` 增加 `classification: {"mutability": ..., "mutability_analyzed": bool, "mutability_reason": ..., "evidence_count": ...}`；
- `analyzed=false` 时暴露跳转入口，参数固定为该 Case 的基准与扫描；
- 不自动创建任务、不自动调用模型、不设为生成前置阻塞。

## 7. 兼容与迁移

| 场景 | 处理 |
| --- | --- |
| 旧契约 JSON 无新字段 | `mutability_analyzed` 默认 false，沿用扫描分类 |
| 旧扫描投影 | 由 3.2 按需重算资格，不需要重新发布 |
| 旧任务冻结在修订 0 | 始终按扫描分类运行；需要分析结果须重新开始任务 |
| 未发布的个人草稿分类 | 不影响共享页面和其他员工 |
| 分类由 READ_ONLY 改判 WRITE/UNKNOWN | 新修订生效；依赖它做查询的 Case 下次编译报 `QUERY_MUST_BE_READ_ONLY` |
| 页面已打开 | 资源 URL 和页面版本同步更新，旧页沿用现有版本检查，阻止过期页写入并提示刷新 |

## 8. 测试与验收

### 8.1 单元/集成

- 契约校验：WRITE 无证据、READ_ONLY 证据不全、分析后 UNKNOWN 无原因，分别失败；
- 零版契约 `analyzed` 恒 false；
- 分析后 UNKNOWN 覆盖扫描 READ_ONLY，只读门禁随之拒绝；
- 纯分类提交带证据时，证据按可达方法校验通过（不被默认为 `{}` 的 `reachable` 误拒）；
- 保存的新版本带 `author_user_id`，`save_interface_draft` 通过，本人视图可见，他人 published 视图不变；
- 叠加只改 `mutability`，其他字段不变；四个消费点各自读到精确修订；
- 发现索引仍能看到未选中的候选接口，且显示其可见修订的分类；
- 资格重算：数据库冷/热缓存两条路径一致；刷新前后除执行资格外字段逐项相同；`contract_gap` 仍阻塞；
- 修复不改数据库原始扫描事实，原事实可继续重放。

### 8.2 真实业务

1. 原扫描 `scan-20261020062539-c796af848b-6894bbf5` 的 `RefundFacade#billSupplement` 完成真实草稿编译；
2. 契约补充任务提交 WRITE + 证据，本人草稿可见，Case 上下文与运行时目录都显示 WRITE；
3. 真实只读查询接口提交 READ_ONLY 后可作查询/Oracle；证据不全被拒；
4. 提交"分析后仍无法确定"，确认扫描 READ_ONLY 被撤销；
5. 外部 DSF 与 Facade 分类一致；
6. 未分析状态下 `billSupplement` 可执行，用它做查询的步骤被明确拒绝。

## 9. OpenSpec 落点

| 文件 | 变更 |
| --- | --- |
| `specs/codex-system-operations/spec.md` | MODIFIED `Incomplete or unsafe operation`：移除 unknown mutability 阻塞条件 |
| `specs/unified-qa-operations/spec.md` | ADDED `Unknown mutability executes as a potential write`；ADDED `Persisted eligibility follows current rules` |
| `specs/shared-baseline-collaboration/spec.md` | ADDED `Contract revision carries evidenced mutability`：字段、分析状态、作者与本人草稿、按 scope 冻结修订叠加、不使用存储层 latest |
| `specs/case-template-generation-v4/spec.md` | ADDED `Target classification is visible and blockers are precise` |

`tasks.md` 使用 P18.1–P18.5 跟踪本次实现、版本隔离、页面、原任务回放、独立评审及校验；其他 change 任务保持原状态。

## 10. 明确不做

- 不修改扫描启发式动词表；
- 不在基准流水线内调用 AI；
- 不新增表、列或独立服务；不保存第二份完整能力；
- 不在能力目录里按存储层 latest 叠加分类；
- 不实现上游触发、数据造数、有界轮询；
- 不为 UNKNOWN 增加逐步审批。
