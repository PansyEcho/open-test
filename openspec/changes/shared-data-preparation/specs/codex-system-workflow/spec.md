## MODIFIED Requirements

### Requirement: Codex exposes explicit global and per-system OpenTest workflows

The plugin SHALL expose an explicit-only `$open-test` skill for registration, update, scan and system-skill synchronization, and one explicit-only hard-bound system skill for source analysis, contracts, shared data methods, cases and explicitly requested QA operations.

#### Scenario: Reuse a data method from the native system skill
- **WHEN** the user requests data preparation in the current system
- **THEN** the skill searches shared methods and reads an explicit owner, capability and version before execution
- **AND** missing methods or contracts use a persisted task and existing task-scoped source, draft and publication tools without first generating a Case or internal-knowledge prose

#### Scenario: System skill refresh

- **WHEN** a system scan completes and system skills are synchronized
- **THEN** the response returns the generated invocation name
- **AND** states that a fresh Codex task is required after plugin refresh
