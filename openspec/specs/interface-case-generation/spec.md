# interface-case-generation Specification

## Purpose
TBD - created by archiving change codex-first-system-workflows-and-qa-tools. Update Purpose after archive.
## Requirements
### Requirement: Interface cases can be saved before knowledge completion

The system SHALL create an interface matrix and persist a Case from the latest scan even when interface or coverage knowledge is missing or not user-confirmed.

#### Scenario: Missing knowledge and execution data

- **WHEN** an interface exists in the latest scan but knowledge, business input or oracle is incomplete
- **THEN** the matrix and Case are saved with an `operation_id` execute step
- **AND** only the affected variant is marked `BLOCKED` with its missing reason

### Requirement: Scenario execution supports operation identities

An execute step SHALL contain exactly one of legacy `tool_id` or unified `operation_id`.

#### Scenario: Operation step execution

- **WHEN** a runnable Case contains an `operation_id`
- **THEN** execution uses the same idempotent operation service as the system skill
- **AND** persists the complete business result or real business error

