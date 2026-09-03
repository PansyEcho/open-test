## ADDED Requirements

### Requirement: Resource configuration environment is explicit and scan-bound

The system SHALL allow each registered system to select `test`, `qa`, `uat` or `auto` as the resource configuration environment and SHALL freeze the actually selected property-file suffix into the resulting scan and DSF profile.

#### Scenario: User selects a concrete environment

- **WHEN** the user selects `test`, `qa` or `uat` and starts a new scan
- **THEN** discovery reads only the matching `dsf_application.properties.<environment>` resources
- **AND** later Operation, database, Redis and MQ resolution uses that scan-bound environment instead of a hard-coded QA suffix

#### Scenario: Auto compatibility mode is selected

- **WHEN** the setting is `auto`
- **THEN** scanning prefers QA configuration and falls back to test only when QA configuration is unavailable
- **AND** the actual choice is recorded so execution does not guess again

