## 1. Contract

- [x] 1.1 Add proposal, design, tasks and delta specifications
- [x] 1.2 Add domain models for snapshots, operations and execution records

## 2. Fast knowledge reads

- [x] 2.1 Add persisted workspace revision and bounded single-flight projection cache
- [x] 2.2 Wire scan and knowledge mutation invalidation and startup prewarming
- [x] 2.3 Add cache correctness, concurrency, memory-bound and performance tests

## 3. Codex operations

- [x] 3.1 Derive and index Facade/Job operation capabilities
- [x] 3.2 Add QA-only idempotent execution service, persistence and local APIs
- [x] 3.3 Add fake-provider Facade/Job, rejection and deduplication tests

## 4. Plugin and skills

- [x] 4.1 Add operations MCP with four fixed tools
- [x] 4.2 Generate explicit-only per-system skills and validate naming/collision behavior
- [x] 4.3 Validate, cachebust and reinstall the local marketplace plugin

## 5. Codex-only page

- [x] 5.1 Replace the question pane with persisted Codex task cards and deep links
- [x] 5.2 Stop creating new question cycles and retire mutation APIs with legacy reads intact
- [x] 5.3 Add page contract, task recovery and historical compatibility tests

## 6. Verification

- [x] 6.1 Run V2, legacy, Java sidecar, OpenSpec strict, compileall, Node and pip gates
- [x] 6.2 Run one new-diff OCR delegation review cycle and resolve findings within its two-pass limit
- [x] 6.3 Record final evidence in `docs/status.md` without changing historical task conclusions
