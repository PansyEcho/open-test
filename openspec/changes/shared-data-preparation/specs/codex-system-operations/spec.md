## MODIFIED Requirements

### Requirement: Codex execution is QA-only and idempotent

The system SHALL execute only indexed operations in logical `qa` or `uat` environments resolved through each target project's own non-production `qa`, `test`, `dev` or `uat` profile and SHALL persist request-ID deduplication before dispatch. An explicit request to execute authorizes the necessary steps within its fixed task scope without repeated per-step confirmation; invoking a Skill or requesting generation alone SHALL NOT authorize runtime execution.

#### Scenario: Duplicate write tool call

- **WHEN** Codex submits the same request ID more than once
- **THEN** OpenTest returns the original execution record
- **AND** the provider is invoked exactly once

#### Scenario: Incomplete or unsafe operation

- **WHEN** the selected environment is unavailable or production, or the operation has unknown mutability or missing target project profile
- **THEN** execution fails before provider initialization

#### Scenario: Shared method generation without execution

- **WHEN** a user invokes the system Skill only to supplement a data method, contract or Case plan
- **THEN** the Agent may inspect scoped source and publish the validated definition without creating a QA execution
- **AND** an independent explicit execution request chooses the environment and permitted read or write scope before any business operation
