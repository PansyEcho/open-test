## MODIFIED Requirements

### Requirement: Codex execution is QA-only and idempotent
The system SHALL execute only indexed operations in explicitly authorized QA/UAT environments and SHALL persist request-ID deduplication before dispatch. Unknown mutability SHALL NOT itself block task-scoped execution, but SHALL NOT grant read-only query or Oracle eligibility.

#### Scenario: Duplicate write tool call
- **WHEN** Codex submits the same request ID more than once
- **THEN** OpenTest returns the original execution record
- **AND** the provider is invoked exactly once

#### Scenario: Incomplete or unsafe operation
- **WHEN** the environment is not an authorized QA/UAT environment or the operation has incomplete binding or an actual contract gap
- **THEN** execution fails before provider initialization with its operation identity and reason

#### Scenario: Unknown mutability target
- **WHEN** a task-scoped operation has complete fixed binding and contract but unknown mutability
- **THEN** Facade and external DSF execution both permit it as a potential write
- **AND** read-only query, verification and Oracle steps reject it

#### Scenario: Legacy eligibility cache cannot be written
- **WHEN** fixed scan facts permit recalculating an obsolete UNKNOWN blocker but the local projection cache cannot be written
- **THEN** the catalog returns the verified capability and logs the cache failure without changing shared scan facts or removing genuine contract blockers
