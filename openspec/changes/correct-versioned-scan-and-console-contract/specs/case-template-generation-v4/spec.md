## MODIFIED Requirements

### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL accept a raw `fully.qualified.Facade#method` or canonical Facade Entry ID at the current `/api/v2` Case generation endpoint, resolve exactly one Entry from the target system's latest scan, and require current READY input knowledge before creating a Case generation handoff.

#### Scenario: Start generation for an eligible Facade

- **WHEN** a caller posts an existing latest READY Facade identity to `/api/v2/systems/{system_id}/case-generations`
- **THEN** the system returns `202` with a generation ID, handoff ID, thread ID, turn ID, polling URL and Codex deep link
- **AND** the handoff freezes the target Entry, source scan and directly authorized source-system scopes
- **AND** no QA Operation is called

#### Scenario: Target or required knowledge is unavailable

- **WHEN** the identity is absent, ambiguous, stale or lacks READY input knowledge
- **THEN** the system rejects the request before model execution
- **AND** it does not fabricate a request, Variant or successful QA result

#### Scenario: Codex reads a newly started handoff

- **WHEN** the handoff has a preallocated Generation ID but no immutable Generation artifact yet
- **THEN** the handoff catalog returns the target, schemas and tool contract with `generation: null`
- **AND** it does not attempt to read a not-yet-created Generation file

### Requirement: V4 oracles and execution results are machine-verifiable

The system SHALL model every Oracle as a channel, controlled function or observer, typed arguments and structured assertions, SHALL preserve bounded redacted DATA, TARGET, ORACLE and CLEANUP input/output summaries, statuses, errors and Operation execution IDs, and SHALL access QA only after a caller explicitly creates an Execution for an immutable Generation.

#### Scenario: Generate executable business variants

- **WHEN** Codex submits valid DSL for a generation handoff
- **THEN** the system persists the immutable Generation and its deterministic Variant order
- **AND** it does not run data preparation, the target Operation, Oracles or Cleanup

#### Scenario: Explicitly execute a generated Generation

- **WHEN** a caller posts a supported environment to `/api/v2/systems/{system_id}/case-generations/{generation_id}/executions`
- **THEN** the system creates a new Execution and processes every runnable Variant in frozen order
- **AND** each result preserves bounded input/output structure summaries, Operation execution IDs, assertion outcomes and Cleanup outcome without copying raw QA scalar values into the report

#### Scenario: QA Provider returns a detailed failure

- **WHEN** a DATA, TARGET, ORACLE or CLEANUP Operation fails with a stable error code and a raw Provider message
- **THEN** the Execution report preserves only the stable error code and structural summaries
- **AND** the raw Provider message remains available only through the protected Operation execution record

#### Scenario: Write Variant has no valid Cleanup

- **WHEN** a write-interface template omits Cleanup, references an unavailable Cleanup Operation, has invalid arguments, uses an unprovable value source or response path, or its evidence does not exactly match the declared Cleanup class and method
- **THEN** its Variants are persisted as blocked
- **AND** explicit execution does not invoke DATA or TARGET for those Variants

#### Scenario: Cleanup fails after a target attempt

- **WHEN** TARGET was attempted and TARGET, ORACLE or CLEANUP fails
- **THEN** Cleanup is still attempted when its arguments can be resolved
- **AND** Cleanup failure prevents a passing result while preserving each completed or pre-call blocked stage

#### Scenario: AI proposes a MySQL observer

- **WHEN** an authorized database Runtime Function, matching source and resource evidence, one bounded parameterized read-only SELECT and a closed output schema are all present
- **THEN** the Observer may be compiled as a handoff-scoped Runtime Function
- **AND** any missing ownership, SQL, binding, evidence or schema constraint produces `BLOCKED`

#### Scenario: AI proposes a Redis or MQ observer

- **WHEN** the frozen Runtime Function registry contains an independently authorized read-only Redis or MQ observer with matching evidence, typed arguments and a closed output schema
- **THEN** the Observer may be compiled and executed through that function
- **AND** a send-only MQ Operation, missing observer function or unsupported capability produces `BLOCKED` instead of an unverified natural-language Oracle

## ADDED Requirements

### Requirement: Explicit Generation executions are independent and repeatable

The system SHALL preserve every explicit execution as a separate report and SHALL prevent concurrent duplicate execution for the same Generation and environment.

#### Scenario: Re-run a completed Generation

- **WHEN** a previous Execution is terminal and the caller executes the same Generation again
- **THEN** the system creates a different execution ID and retains both reports

#### Scenario: Same Generation is already running

- **WHEN** another Execution for the same Generation and environment is RUNNING
- **THEN** the system returns `409` with the active execution ID
- **AND** it does not start another QA workflow

### Requirement: Generation status and executability are explicit

The system SHALL expose `QUEUED`, `GENERATING`, `READY`, `PARTIAL`, `BLOCKED` or `FAILED` for a Generation identity and SHALL derive execution eligibility only from the immutable Generation artifact.

#### Scenario: Generation is still being produced

- **WHEN** the handoff has not persisted an immutable Generation
- **THEN** the Generation query returns `QUEUED` before the Codex turn starts or `GENERATING` while the turn or validation is active
- **AND** the execution action is unavailable

#### Scenario: Execute a partially runnable Generation

- **WHEN** an immutable Generation is `PARTIAL`
- **THEN** explicit execution runs every runnable Variant in frozen order
- **AND** preserves every non-runnable Variant as a `BLOCKED` result without invoking its DATA or TARGET stages

#### Scenario: Generation cannot be executed

- **WHEN** an immutable Generation is `BLOCKED` or generation has `FAILED`
- **THEN** the execution endpoint returns `409` with the Generation status
- **AND** no Execution or QA workflow is started

### Requirement: Write-interface Cleanup uses identities from the actual target response

The system SHALL require each write Variant to declare a structured Cleanup action, SHALL validate its Operation, input Schema, required arguments, value sources, response paths and source evidence during Generation, and SHALL allow Cleanup arguments to reference the actual TARGET response from the same Variant.

#### Scenario: Refund createOrder canary is cleaned up

- **WHEN** a `RefundFacade#createOrder` Variant successfully creates an order
- **THEN** its Cleanup calls `RefundFacade#cancel` with `refundSerialNo` extracted from the exact response path proved by the target Operation's scanned output fields
- **AND** it does not use a fixed order number or shared QA identity
