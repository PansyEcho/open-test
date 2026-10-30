## MODIFIED Requirements

### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL resolve one visible Facade entry in the selected fixed code baseline and published/mine view and reuse valid target knowledge or prepare a linked knowledge prerequisite before Case compilation.

#### Scenario: Start generation for an eligible Facade

- **WHEN** a caller prepares an visible Facade in the selected baseline through the v2 Case API
- **THEN** the result identifies a persisted task and frozen handoff, or its linked knowledge prerequisite
- **AND** web mode starts execution while native mode remains in the calling Agent

#### Scenario: Web prompt uses the persisted task environment

- **WHEN** a web Case task starts or resumes analysis using a persisted TaskRecord
- **THEN** prompt and coverage lookup use the environment frozen in task result without requiring an undeclared TaskRecord field
- **AND** only legacy tasks lacking that field use the existing QA default

#### Scenario: Target or required knowledge is unavailable

- **WHEN** the target is valid but required knowledge is missing
- **THEN** only knowledge needed for that interface is prepared and Case generation continues after the knowledge draft is available to the same employee or explicitly published
- **AND** absent or ambiguous targets remain precise errors without fabricated QA results


## ADDED Requirements

### Requirement: Shared Case revisions preserve current visibility and frozen task scope

The system SHALL reject whole-Generation continuation of terminal shared-baseline tasks before creating a successor task or restoring a continuation receipt. Revisions SHALL start from one currently visible Case, select current visible knowledge for its actual dependencies once, and freeze those references for the new task.

#### Scenario: Terminal shared task requests continuation

- **WHEN** a shared-baseline task with completed, partial or blocked compiled output requests either continuation intent through the task API or core service
- **THEN** the request is rejected before any successor task, handoff, or receipt is created or restored
- **AND** the caller is directed to current single-Case revisions, with hidden sibling and replaced content remaining hidden and the existing environment unchanged

#### Scenario: Active shared draft resumes

- **WHEN** an employee continues an active shared-baseline draft with the correct revision
- **THEN** the original task resumes with its baseline, employee, environment, source scopes and saved draft preserved
- **AND** no successor is created

#### Scenario: Revising a Case affected by updated dependency knowledge

- **WHEN** a new single-Case revision is created after knowledge of an actually used dependency changes
- **THEN** the new task selects the current visible dependency knowledge in its chosen view and freezes that version
- **AND** a target rescanned at the same commit uses only its newly selected target scan, without inheriting the old target scan
- **AND** later publication changes do not mutate an already active task's frozen references

#### Scenario: Same-system dependency stays on its frozen scan

- **WHEN** a Case freezes a dependency contract from an earlier same-commit scan of the target system and later selects that dependency while the target remains on the current scan
- **THEN** selection uses the capability from the frozen contract's scan and keeps the current target scan in the handoff
- **AND** draft scope merging preserves every same-system scan identity and rejects only different code baselines, never pairing a frozen contract with a capability from another scan

#### Scenario: Downstream resolution and shared-function checks keep scan identity

- **WHEN** a Case has multiple same-system scans and resolves a downstream dependency or validates an embedded shared function
- **THEN** resolution updates only the caller's exact scan and leaves other selected scans unchanged
- **AND** shared-function validation compares every called operation's frozen scan, independent of scope list order
- **AND** a frozen dynamic dependency recovers its registered definition from its contract scan when the original source scope is gone

#### Scenario: Data preparation and cleanup use distinct dependency identities

- **WHEN** a selected Case calls a database Runtime function such as an operation's `:query` or `:data` alias, or references an interface only through cleanup
- **THEN** revision seeding and final Case bindings resolve the actual provider operation and source system from the frozen Runtime catalog or cleanup operation
- **AND** the required source scope and knowledge version remain attached to that Case for compilation and publication checks

#### Scenario: Shared Case executes on a computer without the author's source repository

- **WHEN** an employee executes selected shared Cases in QA or UAT on another computer
- **THEN** the target and any explicitly selected provider Facade read their configuration from materialized source for their frozen scans
- **AND** an external DSF reference from a frozen scan executes with the declaring caller's frozen DSF profile, without requiring the provider's source material
- **AND** missing or unrelated local repository bindings cannot change either execution profile
- **AND** missing frozen caller source, or missing frozen source for an explicitly selected provider Facade, produces an explicit error before business execution without mutating global source bindings or another execution's profiles

#### Scenario: External dependency executes with the caller profile

- **WHEN** a shared Case data or observation step calls an external DSF reference declared by a frozen caller scan
- **THEN** execution uses that caller's frozen DSF client profile and the caller's selected QA or UAT environment
- **AND** the provider's registration state, latest scan or missing source material does not block the call
- **AND** no provider source scope is added solely to resolve the external reference's execution profile

### Requirement: Explicit step schemas close incomplete fixed response contracts
The system SHALL merge an explicitly declared step or observer output schema into branches that the fixed dependency response contract leaves open (for example `list={}` or `saasOrderVO={}`), while scanned types and constraints remain authoritative. A complete scanned schema SHALL NOT be widened by an agent declaration, and repeated resolution SHALL NOT replace an existing closed response contract with an open one.

#### Scenario: Fixed dependency exposes an empty nested response field
- **WHEN** a DATA step calls a fixed operation whose response schema only registers `list={}` or `saasOrderVO={}`, and the agent declares a complete `output_schema` from the fixed source
- **THEN** compilation merges the missing branches and resolves downstream step outputs, arguments and assertions without UNKNOWN_STEP_OUTPUT
- **AND** scanned types and constraints remain authoritative; a complete scanned schema cannot gain assertion paths from the declaration
- **AND** resolving the same interface again with only empty branches keeps the last closed response contract and does not downgrade fixed knowledge

### Requirement: Classification follows exact contracts across execution and discovery
The system SHALL overlay classification from every scope's frozen operation revisions for Case and data runtime descriptors. Selected dependencies SHALL not follow latest; missing explicit revisions SHALL fail. Unversioned historical scopes SHALL retain scanning semantics. Discovery SHALL keep unselected visible candidates and show classifications from their visible exact contracts.

#### Scenario: Dependency receives a new analysis after a Case starts
- **WHEN** a frozen dependency gets a new classification revision
- **THEN** the existing task uses its original classification while a new task uses its selected visible revision

#### Scenario: A candidate is not yet selected
- **WHEN** an Agent discovers an available query candidate
- **THEN** it remains discoverable before selection and its returned contract and runtime descriptor use the same visible revision

#### Scenario: An unselected candidate has a missing visible contract
- **WHEN** one visible discovery candidate has no content at its referenced contract revision
- **THEN** discovery preserves the candidate with `mutability: null`, `contract_available: false` and a recovery reason, without failing the other candidates or granting runtime access
- **AND** missing contracts for selected or frozen operations still fail closed; the UI labels explicitly unavailable contracts as unavailable rather than unanalyzed

#### Scenario: Data draft selects several new operations from one scope
- **WHEN** a single draft save freezes several new operations from the same source scope
- **THEN** it reads that scope's visible revision index once and chooses matching-scan personal READY revisions before published revisions
- **AND** the index is not retained across saves and existing frozen revisions remain unchanged

#### Scenario: Historical selected data operation has no revision mapping
- **WHEN** an existing data task reads or saves a draft using an already selected operation without a contract revision mapping
- **THEN** contract details, runtime descriptors and newly materialized revision mappings retain revision zero semantics
- **AND** a later visible analysis does not silently upgrade that task

#### Scenario: A personal draft belongs to another scan
- **WHEN** a data task selects an operation from its fixed scan and the employee has a READY draft from another scan
- **THEN** selection uses an available published contract matching the fixed scan instead of allowing the unrelated personal scan to block it

### Requirement: Classification is visible and analysis remains explicit
The interface and Case UI SHALL distinguish unanalyzed, analyzed READ_ONLY, analyzed WRITE and analyzed UNKNOWN with a reason. Explicit analysis SHALL prepare the existing contract-completion workflow for the selected fixed baseline and scan. Reading a page SHALL not start analysis or block Case generation.

#### Scenario: User opens an unanalyzed target
- **WHEN** its contract has no semantic classification
- **THEN** the UI shows unanalyzed with an explicit analysis action and no automatic model run

#### Scenario: Stale page attempts analysis after a frontend update
- **WHEN** the loaded page version differs from the service
- **THEN** state-changing actions require reload before preparing a task

### Requirement: Dependency blockers identify actionable recovery steps
The system SHALL preserve contract, visibility, source and execution boundaries while identifying the missing step and known dependency identities in diagnostic errors. Missing dependency source material alone SHALL NOT block generation when fixed evidence already suffices.

#### Scenario: Dependency selection or execution lacks a prerequisite
- **WHEN** a provider contract is not visible or closed, an operation has only been resolved, or a legacy source baseline cannot be read
- **THEN** the diagnostic identifies the relevant system, operation or scan and directs contract completion/publication, explicit selection through the task's supported tool, or restoration of frozen source material as appropriate
- **AND** ambiguous visible providers return actual `provider_baseline_id` choices without silently selecting one

#### Scenario: A required enum mapping cannot be proven
- **WHEN** a scenario requires an enum code mapping absent from its fixed contract and accessible source evidence
- **THEN** generation instructions require saving the affected type/field and evidence gap in `unresolved`, preserving independent verifiable scenarios instead of guessing a value or repeatedly reading unavailable source
- **AND** the task blocker summary includes saved unresolved reasons even if question diagnostics have not been populated

### Requirement: Task-resolved caller dependencies preserve exact evidence and sharing state
The system SHALL allow an explicitly selected external DSF reference proved by the caller's frozen source and exact dependency contract to execute in that task without requiring a provider-shared publication. Resolution SHALL return the exact contract revision actually registered; selection SHALL freeze that revision, create or reuse the employee's READY interface draft in the caller baseline, and record the resulting interface reference in the Case's actual dependencies. The reference SHALL remain visible to the owning employee's task and SHALL block shared Case publication until the caller-owned interface is explicitly published.

#### Scenario: Caller-resolved external reference is selected in a published-view task
- **WHEN** an employee explicitly selects an external DSF operation already resolved from the caller's fixed scan and exact dependency artifact
- **THEN** selection returns that operation and its exact contract revision without listing or publishing a provider contract
- **AND** the employee's READY interface draft and stable interface reference are created in the caller baseline
- **AND** the operation becomes available to the task's DATA and ORACLE runtime directory under its actual schema and classification

#### Scenario: Case binding records the task-local dependency
- **WHEN** a compiled Case actually calls a task-resolved external dependency
- **THEN** its frozen Case binding contains the exact interface reference rather than omitting the dependency
- **AND** saving, continuing revision, and reading the Case after a service restart use the same caller route and contract revision
- **AND** the employee's personal Case remains executable in the mine view

#### Scenario: Shared publication encounters an unshared task-local dependency
- **WHEN** an employee attempts to publish a Case whose actual dependency is still an unpublished caller-owned interface
- **THEN** publication is blocked with the operation, baseline and contract revision
- **AND** the message directs the employee to publish that caller-owned interface contract before sharing
- **AND** no shared pointer or dependency record is silently skipped

#### Scenario: Provider-owned dependency remains publication-gated
- **WHEN** the selected dependency is a provider Facade rather than the caller's external DSF reference
- **THEN** the existing provider publication and visibility checks remain in force
- **AND** a provider route mismatch is not silently replaced by another provider version

#### Scenario: Data preparation uses the same task-local contract
- **WHEN** a data task selects a caller-resolved external operation
- **THEN** it freezes the same exact contract revision and does not require a provider publication
- **AND** its selection does not create a second contract or an unrelated latest reference

### Requirement: Exact dependency bytecode can prove enum constants without source jars
The system SHALL expose a task-scoped read-only dependency type reader that locates a requested Java type in the exact resolved classpath or the exact artifact POM's local dependency set. When the type is an enum and its constructor/static initialization is statically decodable, the reader SHALL return each proven constant's name and `getCode()` value. The compiler SHALL consume this typed evidence for explicit enum values without inventing Java source lines or treating constant names, display labels or observed QA values as a complete code mapping. If the bytecode cannot prove the mapping, the tool SHALL fail explicitly and the affected values remain unproven.

#### Scenario: Enum source jar is absent but exact bytecode proves codes
- **WHEN** the task selects an external dependency whose exact classpath contains an enum declared as `ARC("ARC", ...)` / `BSP("BSP", ...)`, but no sources jar exists
- **THEN** `read_dependency_type` returns the proven name/code pairs and records task-private evidence
- **AND** the compiler accepts explicit `enum.values` pairs that match that evidence
- **AND** no synthetic `.java` path or line is created and no unproven constant is inferred

#### Scenario: Bytecode cannot prove the mapping
- **WHEN** the enum uses computed values or its getter/constructor cannot be statically aligned
- **THEN** the reader returns a precise failure instead of a guessed mapping
- **AND** only scenarios that need the unproven values remain unavailable

#### Scenario: Another employee's unpublished contract is not copied
- **WHEN** a task-resolved external dependency has an unpublished contract authored by another employee
- **THEN** selection rebuilds the contract from this task's frozen definition instead of copying the other employee's content
- **AND** the resulting draft is authored by the current employee and contains no other employee's private supplements

#### Scenario: Typed enum evidence is additive
- **WHEN** typed dependency evidence exists but does not contain a requested enum value that is already proven by valid read source text
- **THEN** the compiler still accepts the source-proven value
- **AND** typed evidence cannot invalidate existing valid source evidence

### Requirement: 成功场景必须用真实数据建立并验证前置条件

系统 SHALL 仅在运行期查询结果参与后续 predicate、目标参数、输出、match_source 或验证步骤时，把它作为场景证据。只执行但未使用的查询 MAY 作为诊断记录，SHALL NOT 被表述为前置条件已被证明。成功/业务处理场景 SHALL 至少包含对实际目标响应身份、状态或关联关系的必经断言；目标预期值 SHALL 来自固定源码/契约，通用编译器/执行器 SHALL NOT 写死业务状态值。

#### Scenario: 查询结果被间接使用
- **WHEN** 运行期查询结果经过转换、传给后续调用、用于 match_source 或验证步骤
- **THEN** 校验识别该间接使用，不把它误报为死查询

#### Scenario: 查询执行但未被使用
- **WHEN** 只读查询结果未被任何后续 predicate、参数、输出、match_source 或验证步骤消费
- **THEN** 仅记录为诊断证据缺口，不把它当作目标业务前置条件已成立的证明

#### Scenario: 成功响应被断言
- **WHEN** 生成的场景期望成功或业务处理分支
- **THEN** 场景包含对实际目标响应身份、状态或关联关系的必需断言
- **AND** 预期值来自固定源码/契约；通用编译器/执行器不硬编码业务状态

#### Scenario: 数据不足
- **WHEN** 合理查询和现有数据准备能力无法建立前置条件
- **THEN** 把受影响场景记录为数据缺口，不伪造成功，也不用无关的幂等或失败场景替代

#### Scenario: Actual classpath wins over POM fallback
- **WHEN** the exact classpath and a local POM fallback contain different versions of the requested type
- **THEN** the reader uses the actual classpath version
- **AND** the POM fallback is used only when the type is absent from the actual classpath

#### Scenario: Computed getCode is not treated as a field value
- **WHEN** `getCode()` concatenates, replaces or otherwise transforms a field before returning
- **THEN** the bytecode reader rejects the mapping as unproven
- **AND** it does not return the raw constructor field value as the code

### Requirement: Successful scenarios derive identity from real existing business records
The system SHALL derive a successful or idempotent scenario from a real existing business record and its current state, then query the provider interface by that real business identity and bind request fields from the returned provider object. It SHALL NOT treat an arbitrary first list row, a display value, a fixed sample or a hard-coded success result as proof that the target operation succeeded.

#### Scenario: Existing completed business record yields an idempotent success
- **WHEN** a real existing business record in a completed state is associated with the provider object returned for the same business identity
- **THEN** the generated Case asserts the actual success response fields returned by the target operation
- **AND** request fields are bound from the returned provider object, not from a hard-coded success result
- **AND** the target returns the existing business result rather than creating a duplicate

#### Scenario: No associated existing record is available
- **WHEN** no real existing business record in a completed state can be associated with the provider object
- **THEN** the system may generate verifiable failure or pending-confirmation scenarios
- **AND** it SHALL report the missing association as a scenario-level data gap rather than claiming a success scenario was covered

### Requirement: 逐项执行证据与真实生命周期
系统 SHALL 在每条 Variant 完成后先持久化其结果与实际开始结束时间，再推进完成计数；使用既有行锁、执行所有权和最新记录合并，终态不可被迟到回调覆盖，异常退出保留已完成证据。生成时间 SHALL 来自 Task 的实际工作启动与首次真实终态，不用产物创建时间冒充启动。

#### Scenario: 中途失败
- **WHEN** 10条执行中前3条已完成而后续异常
- **THEN** 页面立即可见前3条结果，最终失败保留这些证据，其余明确未执行或失败

#### Scenario: 等待与恢复
- **WHEN** 任务排队、等待原生 Agent 或恢复执行
- **THEN** 排队不伪造启动，等待不展示结束，恢复不重置首次启动，首次终态时间保持稳定
