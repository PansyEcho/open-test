# Design: Codex 原生 OpenTest 工作区

## Knowledge projection cache

`ScanCatalogService` owns a weighted LRU keyed by system, resolved scan and a persisted workspace revision. Startup prewarms latest scans sequentially. A snapshot contains only immutable `ScanCatalog` and target lookup data; parsed `ScanManifest` instances are released after construction. Same-key rebuilds are single-flight and revision changes never serve a known stale entry.

The revision store lives under `.opentest/workspace-revisions`. Scan publication and Git knowledge mutations bump the revision after their successful write boundary. Cache limits are 128 MiB and 32 entries by default; oversized snapshots remain uncached.

## Operation model and execution

`OperationCapability` is a separate contract from `KnowledgeInvocationContract`. Facade entry IDs and Job entry IDs are stable public operation IDs; provider DSF IDs and generated Job tools remain internal bindings. Capabilities are derived from the latest manifest and persisted into a separate SQLite table.

Operation execution accepts only an indexed operation ID, structured arguments and a caller-provided request ID. A persisted execution store deduplicates the request ID before dispatch. Runtime profiles must resolve to QA. Unknown or incomplete bindings fail before any provider call. WRITE and Job calls are never automatically retried.

## Codex plugin

The knowledge handoff MCP remains unchanged. A second operations MCP maps four tools to loopback APIs: search, get, execute and get execution. Generated system skills hard-bind the system ID, disable implicit invocation and instruct Codex to gather required business fields before one execution.

Skill names are lower-case hyphenated, shorter than 64 characters and use a stable hash on truncation or collision. Plugin synchronization owns only generated folders carrying its marker, updates the cachebuster and requires a new Codex task to load the updated skills.

## Codex-only continuation

New client knowledge tasks use `WAITING_FOR_COMPLETION` whenever the original Codex task needs more user input. No new question cycle is created. Existing question records and read APIs remain compatible; mutation APIs return a retired response. The right pane lists persisted generation attempts and opens their saved `codex://threads/<id>` deep link without starting, resuming or forking a thread.
