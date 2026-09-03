# codex-system-operations Specification

## Purpose
TBD - created by archiving change codex-native-open-test-workspace. Update Purpose after archive.
## Requirements
### Requirement: Indexed Facade and Job operations are available to Codex

The system SHALL derive a stable `OperationCapability` for every executable latest-scan Facade and Job without changing the read-only invocation contract.

#### Scenario: Refund createOrder discovery

- **WHEN** the Refund system scan contains `RefundFacade#createOrder` and a complete DSF provider binding
- **THEN** the operation catalog exposes the Facade entry ID, request schema and WRITE mutability
- **AND** arbitrary provider service fields are not accepted from the caller

#### Scenario: Job discovery

- **WHEN** a Job entry has a valid generated HTTP trigger tool
- **THEN** the catalog exposes a JOB capability bound to that fixed tool

### Requirement: Codex execution is QA-only and idempotent

The system SHALL execute only indexed operations in QA and SHALL persist request-ID deduplication before dispatch. Explicit skill invocation is the only user confirmation step.

#### Scenario: Duplicate write tool call

- **WHEN** Codex submits the same request ID more than once
- **THEN** OpenTest returns the original execution record
- **AND** the provider is invoked exactly once

#### Scenario: Incomplete or unsafe operation

- **WHEN** the environment is not QA or the operation has unknown mutability or incomplete binding
- **THEN** execution fails before provider initialization

