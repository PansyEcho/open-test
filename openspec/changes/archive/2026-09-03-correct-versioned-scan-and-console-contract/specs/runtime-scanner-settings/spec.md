## MODIFIED Requirements

### Requirement: Resource configuration environment is explicit and scan-bound

The system SHALL allow each registered system to select `test`, `qa`, `uat` or `auto` as the resource configuration environment and SHALL freeze the actually selected property-file suffix into the resulting scan and DSF profile.

#### Scenario: User selects a concrete environment

- **WHEN** the user selects `test`, `qa` or `uat` and starts a new scan
- **THEN** discovery reads safe filter files matching `*.<environment>` and combines their values with the main `dsf_application.properties` template when present
- **AND** later DSF, database and MQ Operation resolution uses that scan-bound environment instead of a hard-coded QA suffix
- **AND** resource types without a scan-bound executable adapter remain unsupported rather than reading an unrelated environment definition

#### Scenario: Auto compatibility mode is selected

- **WHEN** the setting is `auto`
- **THEN** scanning prefers matching `*.qa` filters and falls back to matching `*.test` filters only when QA filters are unavailable
- **AND** the actual choice is recorded so execution does not guess again
