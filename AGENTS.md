## Offline testing and verified outcomes

- 线下环境的数据服务于测试。用户要求生成Case、准备数据或执行业务操作，即授权在该任务范围内自主查询、创建、修改、删除测试数据及调用业务接口，无需逐步确认；生产环境不在此授权范围。
- 默认完成“发现接口、构建或复用数据函数、实际取数或造数、回查、生成Case、执行目标与断言”。只有用户明确要求不执行时才只生成；扫描本身只发现和登记，不执行业务调用。
- 用户未指定测试数据时自行寻找合适数据源；目录不足时按实际依赖实时发现并登记接口，不默认要求用户提供capability ID、订单号或完整第三方契约。
- 第三方数据准备应形成可复用、固定版本的函数；每次运行动态取得数据，不把一次试跑订单固化为共享方法。查询条件、创建成功响应和工具完成状态都不能代替结果回查。
- 每个具体业务请求使用稳定request ID去重。允许必要的查询、准备、诊断、修正请求和回查；结果未知时先查执行记录和业务状态，不盲目重复写请求。
- 以真实业务结果和验证为完成标准。不得编造标识、替换用户指定对象、篡改预期或通过直接修改目标结果掩盖业务缺陷；明确记录仍未解决的业务或环境问题。
- 项目扫描应登记本项目实际使用或生效声明的接口，包括依赖JAR配置、自动装配及Client/Repository封装引入的下游，供Case和自然语言操作共同复用。

## Bounded implementation and anti-overengineering policy

Default to the smallest complete change that satisfies the user's stated request and acceptance criteria.

### Scope boundaries

- Treat the user's request as the complete scope.
- Do not expand the task into adjacent cleanup, refactoring, architecture, governance, observability, security hardening, documentation, migrations, or future-proofing unless required for the requested behavior.
- Touch the minimum set of files and preserve the existing architecture, conventions, and supported execution path.
- Do not make "while I am here" changes.
- Report unrelated findings without fixing them.
- Do not create worklogs, manifests, status files, planning documents, ADRs, helper frameworks, or maintenance machinery unless explicitly requested.

### Complexity gate

Do not add any of the following unless it passes the complexity gate:

- hashes, checksums, fingerprints, digests
- snapshots, signatures, provenance records, forensic records, ledgers
- extra persistent state, tables, schemas, columns, indexes, or migrations
- retries, fallbacks, reconciliation flows, schedulers, locks, queues
- approval gates, review gates, compatibility layers, feature flags
- new abstractions, frameworks, infrastructure, or dependencies

A mechanism passes the complexity gate only when at least one condition is true:

1. It is explicitly required by the user or product contract.
2. A reproduced failure demonstrates that it is necessary.
3. A concrete security, legal, destructive-operation, or trust boundary requires it.
4. Existing architecture already requires it and the current change must remain compatible.

Before adding such a mechanism, identify all of the following:

- the independent requirement;
- the real consumer;
- the concrete failure model;
- the live decision that changes because of it.

If any item is missing, do not add the mechanism.

A hash, checksum, fingerprint, or digest is justified only when:

- it replaces a materially more expensive operation; and
- match versus mismatch changes a real runtime decision.

Prefer direct comparison, existing database constraints, or Git when they already answer the question.

Agent-created code, tests, documentation, schemas, migrations, and state are not independent evidence that a capability is required. Do not preserve speculative machinery merely because it was added in an earlier step.

Verify the existing framework, library, provider, and runtime behavior before building a parallel local substitute.

Do not add retries or fallbacks to hide an unknown root cause. First establish the concrete failure being handled.

### Planning and execution

- For a bounded task, make at most one short plan with no more than five bullets, then implement.
- Do not produce multiple alternative architectures unless the user asks for alternatives.
- Re-plan only when new evidence materially changes the implementation direction.
- Prefer the direct root-cause fix over defensive layers around the symptom.
- Validate after a coherent change slice using the smallest relevant test or command.
- Do not repeatedly run broad audits after every small edit.
- Do not ask for approval for ordinary implementation choices that remain within scope.

### Stopping condition

- Stop as soon as the stated acceptance criteria pass.
- Do not continue polishing, generalizing, documenting, refactoring, or future-proofing after the task is complete.
- Do not invent follow-up work in order to keep working.
- If completion genuinely requires a wider architecture, persistence, migration, or compatibility change, state the concrete blocker and the smallest viable option before implementing the wider change.

### Frontend static asset freshness

- Every behavior-changing edit to a browser-loaded JavaScript or CSS asset must also change the asset URL referenced by the HTML. Prefer a human-readable version query such as `/assets/app.js?v=20260825-01`; renaming files is allowed when the existing build or packaging flow already owns the names. Do not rely on the browser noticing that the contents behind an unchanged URL changed.
- Treat an already-open page as still running its previously loaded JavaScript even after the backend restarts. Before validating a frontend change, reopen the page or perform a hard reload, then confirm from the served HTML or browser network record that the new versioned asset URL was actually loaded.
- When an OpenTest page is expected to remain open across backend restarts, a behavior-changing frontend update must include a lightweight page-version mismatch check. A stale page must block state-changing actions and ask the user to reload, or reload automatically when doing so cannot discard unsaved input.
- Frontend completion evidence must exercise the application through the running HTTP service, not only inspect source files or run isolated JavaScript tests. For workflows that launch another application, verify the required API request occurred and succeeded before the external deep link was opened.
- Do not report a frontend fix complete while testing in a tab that predates the asset change, and do not use manual cache deletion as the permanent solution.

### Development service lifecycle

- After completing development work, stop every service process started for that work before handing off to the user.
- In particular, ensure port `8788` is no longer listening so the user can start the service from PyCharm without an "address already in use" error.
- Before reporting completion, verify the service was stopped with `lsof -nP -iTCP:8788 -sTCP:LISTEN`; if it reports a process started for the task, stop that exact PID and recheck the port.

## OpenSpec context rules

- Treat `openspec/specs/**` as the current source of truth.
- For implementation, read only the explicitly selected active change.
- Do not scan `openspec/changes/archive/**` by default.
- Read archived changes only when investigating historical decisions,
  regressions, migrations, or the reason behind an existing design.

### OpenSpec maintenance gate

- Every behavior-changing implementation MUST select an existing active change or create one before modifying runtime code, tests, configuration, API contracts, persistence, or browser behavior.
- Keep the selected change's `proposal.md`, delta specs, design decisions and `tasks.md` consistent with the implementation throughout the task. Mark a checkbox complete only after the corresponding implementation and verification actually pass.
- When implementation changes an existing requirement, update the requirement and all of its scenarios in the selected delta spec; when it introduces a distinct capability, add a focused delta spec. Tests and code comments are not substitutes for an OpenSpec requirement.
- Before reporting completion, run `openspec validate <change> --strict --no-interactive` and `openspec validate --specs --strict --no-interactive`. Fix validation errors in task-owned specs.
- Once every task in a change is complete and the implementation is verified, archive it with the OpenSpec CLI so its delta is merged into `openspec/specs/**`. Do not archive a change with unfinished tasks or known unmet acceptance criteria.
- Every completion report for behavior-changing work MUST name the selected OpenSpec change and state whether it was archived or which verified tasks remain open; do not report a change as complete while its progress record is stale.
- Documentation-only edits that do not alter product behavior may update the current specs directly only when no change history is needed; otherwise use the same change workflow.
