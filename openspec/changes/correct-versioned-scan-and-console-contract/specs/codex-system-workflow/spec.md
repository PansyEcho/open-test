## MODIFIED Requirements

### Requirement: Codex exposes explicit global and per-system OpenTest workflows

The plugin SHALL expose an explicit-only `$open-test` skill for registration, update, scan and system-skill synchronization, and one explicit-only hard-bound system skill for source analysis, knowledge, Case generation, explicit Generation execution, execution reporting and QA operations.

#### Scenario: Sequential multi-interface knowledge

- **WHEN** a user names multiple interface methods in one system skill command
- **THEN** the skill prepares, submits and publishes them in user order
- **AND** existing valid knowledge is skipped unless regeneration is explicit

#### Scenario: Generate interface Cases

- **WHEN** the user asks the system skill to generate Cases
- **THEN** the skill calls only the generation workflow and reports the Generation status
- **AND** it never interprets generation intent as authorization to execute QA

#### Scenario: Execute one Generation

- **WHEN** the user explicitly asks to execute a named Generation in QA
- **THEN** the skill creates one Generation Execution, queries that execution and returns its report
- **AND** it does not substitute the legacy single-Variant execution tool

#### Scenario: System skill refresh

- **WHEN** a system scan completes and system skills are synchronized
- **THEN** the response returns the generated invocation name
- **AND** states that a fresh Codex task is required after plugin refresh

## ADDED Requirements

### Requirement: Plugin preflight reports the real blocking layer

The system SHALL distinguish an invalid Codex configuration, an absent OpenTest plugin and a disabled OpenTest plugin before creating a Codex task or invoking a model.

#### Scenario: Codex configuration cannot be parsed

- **WHEN** `codex plugin list --json` exits non-zero with a configuration diagnostic
- **THEN** the API returns `CODEX_CONFIG_INVALID` with a bounded, redacted diagnostic and config path
- **AND** it does not return `PLUGIN_NOT_INSTALLED`

#### Scenario: Plugin is absent or disabled

- **WHEN** the plugin list command succeeds with a structurally valid installed-plugin list
- **THEN** an absent plugin returns `PLUGIN_NOT_INSTALLED` and an installed disabled plugin returns `PLUGIN_DISABLED`
- **AND** neither case creates a task or invokes a model

#### Scenario: Plugin list output is malformed

- **WHEN** the plugin list command exits successfully but its JSON root, `installed` collection, or any installed entry's `pluginId`, `installed` or `enabled` field is structurally invalid
- **THEN** preflight returns `CODEX_CONFIG_INVALID`
- **AND** it does not misclassify the untrusted output as an absent plugin
