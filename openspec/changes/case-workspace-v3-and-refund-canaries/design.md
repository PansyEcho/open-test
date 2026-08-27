# Design

## Runtime ownership

The program resolves every execution stage from frozen V3 assets. It executes Setup Recipe steps in order, maps Published outputs to facts, installs/verifies a selected Fault plan, invokes the Action, evaluates controlled Oracle expressions, rolls the Fault back and always attempts Cleanup. AI does not choose operations or alter the graph during a run.

Every stage records bounded structured evidence. A failed Oracle, Fault rollback, Cleanup or cleanup Oracle prevents `PASSED`. Runtime input values are not copied into the Attempt record.

Each provider-backed step also records the owning system, exact operation ID, immutable Published reference when applicable, and the existing `OperationExecutionRecord` identity. The workspace re-reads that record and checks the exact Attempt ordinal/stage request identity, unique execution identity, operation, system and expected status. Normal operations must be `COMPLETED`; the target Action of a successful Fault case must instead be the exact planned `FAILED` operation with the planned error outcome. A syntactically valid or manually written Attempt without this proof remains blocked and never advances an Entry to `PASSED`.

The workspace does not trust local `ORACLE` or `CLEANUP_ORACLE` step labels. It replays Setup and Action fact mapping from the stored Operation results, evaluates the deterministic Oracle and effect observations again, verifies Fault entity states and lifecycle outputs, and re-evaluates the Cleanup recovery query result. Reusing a real Operation record with a forged local `PASSED` label therefore cannot complete the entry.

## Invocation boundary

Production execution maps a Published capability back to exactly one current indexed fixed provider binding. Missing, stale, ambiguous or asynchronous bindings block the Attempt; the executor never falls back to a Candidate.

## Real entry pipeline

The workspace catalog is a read-only projection of current scan Entries with generated or confirmed knowledge. It reports the earliest missing verified stage and never inserts a business class, method or fact name. An entry is `READY` before execution, `PASSED` only after a production-invoker Attempt completes Setup, Action, Oracle and Cleanup, and otherwise exposes the exact blocker or latest failure. A failed latest Attempt takes precedence over missing or running Variant progress, and `PASSED` remains executable so a user can create an independent repeat Attempt.

Before a Generation exists, the workspace uses the same read-only rule preview, typed compiler and Hybrid generation builder as the write path. It does not infer readiness from Published, Recipe or Cleanup counts. After a Generation exists, it uses the runtime catalog's no-Fixture current validation and the Generation's exact Action Profile, Oracle, Setup, Fault and Cleanup relations. Historical generations remain readable but cannot drive the current pipeline when system, scan, baseline, Entry or coverage scope differs.

## Page

The Case workspace reads the generic entry pipeline, legacy read-only Case assets, V3 generations and Attempts. It emphasizes failed and blocked Variants, while expanding each Scenario to show graph, rules/obligations, factors, lifecycle IDs and step evidence. There is no matrix confirmation control.
