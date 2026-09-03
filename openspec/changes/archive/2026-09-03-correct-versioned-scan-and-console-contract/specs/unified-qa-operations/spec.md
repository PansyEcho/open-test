## MODIFIED Requirements

### Requirement: External DSF operations come from caller source

The operation catalog SHALL expose only external DSF methods proven by a caller `sof:reference` and explicit method declaration in the same current scan.

#### Scenario: External query execution

- **WHEN** Codex selects an external READ operation from a scan bound to a selected resource configuration
- **THEN** OpenTest uses that caller scan's fixed gs, service, version, action, routing environment and target environment
- **AND** both routing and target environments must belong to the allowed non-production `qa`, `test` or `uat` set
