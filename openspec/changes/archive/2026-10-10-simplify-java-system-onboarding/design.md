# Design decisions

1. Program discovery owns source facts. Reuse actual classpath and existing JAR schema resolution. Missing types remain scoped diagnostics; AI is excluded from known-defect acceptance.
2. Publication means reliable results are available, not that every component is complete. Publish a scan and its catalog/contracts/relations before advancing latest; failed publication preserves the previous pointer. Consumers freeze exact versions.
3. Connection status and business validation are independent. Reuse project environment resolution and Java SDK execution for read-only probes; keep each resource outcome.
4. Background consists of purpose, primary flow and responsibility boundaries. Initial generation fills absent content; subsequent replacement is explicit. AI never invents scan facts.
5. MySQL owns runtime records. Local configuration and recoverable caches remain local. Delete legacy copies only after identity/version/content/reference parity is proven; local_only archives are retained.
6. Future unknown-gap assistance reuses task/contract supplementation and validates type paths and evidence. Failed assistance preserves the gap without automatic loops.
7. Program coverage analysis is removed entirely (2026-10-09). Real scans showed its obligations were almost all framework noise (supplement: 14 interfaces, 330 pending partitions, 38 call sequences, zero business branch predicates) and it blocked a real query Case with 27 synthetic missing-coverage issues. A Variant result is decided only by the assertions it actually executes; scans no longer produce a ProgramCaseAnalysisCatalog and generations no longer freeze coverage assets or accept coverage bindings/semantic drafts. Legacy fields in stored MySQL records are ignored on read without data migration. Genuine observation failures (observer unavailable or arguments unresolvable for an assertion the Case itself contains) still fail as FAILED/OBSERVATION_FAILED.

## 实现中发现的约束（2026-09-30，尚待最终审查）

- 背景Agent成功退出不能证明读过源码。背景入口先复用注册源码安全读取与脱敏提供有界固定Java证据，再归纳三项；没有证据不写背景。当前两层调用选择和片段覆盖仍需复核，见handoff。
- 本机旧CLI与已选模型不兼容。使用既有Runner配置接入本机`codex_executable`设置，不硬编码机器路径进程序；未单配Case模型时继承OpenTest模型。新CLI的MCP工具实际可用性仍需端到端验证。
- 当前未知字段AI补充初稿仅支持已有路径、固定字段声明和现有规则可复核的Java标量；复杂缺失类型保持缺口。任务采纳/拒绝写现有JSON，不新增表。
- MySQL-only应用入口已实现，旧文件应用测试夹具尚未迁移，9项相关测试失败。不能为通过这些测试恢复生产回退。
- 用户已要求跨电脑交接，当前暂停继续实现，保留任务未完成。方案、实际验证和开放问题以handoff与tasks同步维护；所有验收完成后才归档。

## 新电脑继续（2026-10-05）

- 背景证据的每一层调用先完整收集再合并，严格保持两层边界；源码片段按文件、行号读取，同文件远端方法分别取证，重叠行不重复消耗100,000字符总预算。空白片段不视为有效证据。
- 旧实现已随提交`502d22f`迁移。新机器仍需本地MySQL配置、源码绑定和scriptgen；缺失环境不应通过恢复文件生产回退或更换固定源码版本绕过。
