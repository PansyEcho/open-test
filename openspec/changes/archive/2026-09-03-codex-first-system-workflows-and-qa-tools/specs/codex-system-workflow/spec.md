## ADDED Requirements

### Requirement: Codex exposes explicit global and per-system OpenTest workflows

The plugin SHALL expose an explicit-only `$open-test` skill for registration, update, scan and system-skill synchronization, and one explicit-only hard-bound system skill for source analysis, knowledge, cases and QA operations.

#### Scenario: Sequential multi-interface knowledge

- **WHEN** a user names multiple interface methods in one system skill command
- **THEN** the skill prepares, submits and publishes them in user order
- **AND** existing valid knowledge is skipped unless regeneration is explicit

#### Scenario: System skill refresh

- **WHEN** a system scan completes and system skills are synchronized
- **THEN** the response returns the generated invocation name
- **AND** states that a fresh Codex task is required after plugin refresh

### Requirement: System source analysis stays within the current scan baseline

The system skill SHALL read registered source only through audited list, search and read tools bound to the selected current scan.

#### Scenario: Source changed after scan

- **WHEN** the registered source no longer matches the selected scan baseline
- **THEN** source analysis and knowledge preparation fail before returning source content
- **AND** the user is instructed to rescan
