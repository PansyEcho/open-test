## MODIFIED Requirements

### Requirement: Codex exposes explicit global and per-system OpenTest workflows

The plugin SHALL expose an explicit-only `$open-test` skill for registration, update, scan and system-skill synchronization, and one explicit-only hard-bound system skill for source analysis, knowledge, Case generation, explicit Generation execution, execution reporting and QA operations.

#### Scenario: Sequential multi-interface knowledge

- **WHEN** a user names multiple interface methods in one system skill command
- **THEN** the skill prepares, submits and publishes them in user order
- **AND** existing valid knowledge is skipped unless regeneration is explicit

#### Scenario: Generate interface Cases

- **WHEN** the user asks the system skill to generate Cases
- **THEN** the current Agent prepares or resumes one business task, uses bounded source and draft tools, and reports the persisted Generation status after explicit publication
- **AND** it never interprets generation intent as authorization to execute QA

#### Scenario: Execute one Generation

- **WHEN** the user explicitly asks to execute a named Generation in QA
- **THEN** the skill creates one Generation Execution, queries that execution and returns its report
- **AND** it does not substitute the legacy single-Variant execution tool

#### Scenario: System skill refresh

- **WHEN** a system scan completes and system skills are synchronized
- **THEN** the response returns the generated invocation name
- **AND** states that a fresh Codex task is required after plugin refresh
