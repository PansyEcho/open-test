## MODIFIED Requirements

### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL accept a raw `fully.qualified.Facade#method`, canonical Facade Entry/Operation ID, or a `SimpleFacade#method` that resolves uniquely at the current `/api/v2` Case generation endpoint, resolve exactly one Entry from the target system's latest complete scan, and require current READY input knowledge before creating a persistent business task and Case generation handoff.

#### Scenario: Start generation for an eligible Facade

- **WHEN** a caller posts an existing latest READY Facade identity to `/api/v2/systems/{system_id}/case-generations`
- **THEN** the system returns `202` with a task ID, handoff ID, preallocated generation ID, context URL and copyable system-skill instruction
- **AND** the handoff freezes the target Entry, source scan and directly authorized source-system scopes
- **AND** no Agent thread, model turn or QA Operation is started

#### Scenario: Target or required knowledge is unavailable

- **WHEN** the identity is absent, ambiguous, stale or lacks READY input knowledge
- **THEN** the system rejects the request before creating a source-frozen handoff
- **AND** it does not fabricate a request, Variant or successful QA result

#### Scenario: Resolve a short Facade identity

- **WHEN** a caller submits `SimpleFacade#method` and exactly one Facade Entry in the latest complete scan has that simple class name and method
- **THEN** the handoff freezes that Entry's canonical fully qualified identity
- **WHEN** no Entry matches, the endpoint returns an explicit not-found error
- **WHEN** more than one Entry matches, the endpoint returns an ambiguity error that requires a fully qualified identity
- **AND** it never consults a partial scan projection or guesses a package

#### Scenario: Current Agent reads a newly prepared handoff

- **WHEN** the handoff has a preallocated Generation ID but no immutable Generation artifact yet
- **THEN** the task context returns the target, schemas, questions, draft diagnostics and tool contract with `generation: null`
- **AND** it does not attempt to read a not-yet-created Generation file

### Requirement: V4 DSL is finite, typed and provenance-checked

The system SHALL accept only structured `data_functions`, `case_templates` and `unresolved`, and every cross-stage value SHALL use a typed source such as `data_output(call_id, output_name)` or `step_output(step_id, path)` instead of a free-form reference. Draft validation SHALL return precise revisable issues without creating an immutable BLOCKED Generation while the current Agent can repair the draft or answer an open business question.

#### Scenario: Compile executable business variants

- **WHEN** source evidence proves business states and all required identities trace to real Runtime Operation outputs
- **THEN** the compiler expands the supported enum code/name values into deterministic Variants
- **AND** request fields, projections, defaults and output paths are type-checked before QA access

#### Scenario: Business identity uses a fabricated seed

- **WHEN** a required DATA query condition ultimately comes from an arbitrary literal, random value, placeholder or function input wrapping such a value
- **THEN** draft validation returns a precise issue and keeps the handoff revisable
- **AND** no formal Generation is published and the target mutation is not invoked

#### Scenario: Variant expansion exceeds the limit

- **WHEN** a template would compile to more than 100 Variants or exceed its operation limit
- **THEN** the draft returns a bounded validation issue without silently truncating the product
- **AND** a formal BLOCKED Generation requires a later explicit eligible final-blocked publication

### Requirement: V4 oracles and execution results are machine-verifiable

The system SHALL model every Oracle as a channel, controlled function or observer, typed arguments and structured assertions, SHALL preserve bounded redacted DATA, TARGET, ORACLE and CLEANUP input/output summaries, statuses, errors and Operation execution IDs, and SHALL access QA only after a caller explicitly creates an Execution for an immutable Generation.

#### Scenario: Generate executable business variants

- **WHEN** the current Agent submits a valid draft and explicitly publishes the eligible generation handoff
- **THEN** the system persists the immutable Generation and its deterministic Variant order only once
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

### Requirement: V4 source and outer-interface discovery is scoped and version-frozen

The system SHALL expose bounded `list_source_files`, `search_source`, `read_source` and on-demand `read_outer_api_info` tools only within the business handoff's authorized source scopes, while keeping registered absolute source roots out of the public catalog. Those tools SHALL be callable by the current native Agent and SHALL NOT require a server-owned Agent thread.

#### Scenario: Working tree changes after handoff creation

- **WHEN** source files change after the source scope has frozen a Git commit snapshot
- **THEN** all source reads continue against the frozen snapshot
- **AND** evidence cannot silently move to the later working tree

#### Scenario: Current Agent needs a provider operation

- **WHEN** the target system cannot construct a required business identity and a scanned direct dependency exposes an authorized provider Facade
- **THEN** the current Agent may request that exact provider Operation contract on demand
- **AND** unrequested third-party interfaces and credentials are not added to the context or tool result

## REMOVED Requirements

### Requirement: V4 uses the current Codex user Provider and validated model profile

**Reason:** OpenTest no longer starts a Case Agent or controls the model and reasoning effort of the user's current native Agent session. Keeping this requirement would preserve the nested `Agent A → OpenTest → Agent B` flow and the thread ownership problem.

**Migration:** Historical handoff model, effort, thread and turn fields remain read-only. New Case tasks use prepare/context/draft/publish tools and can be resumed by task_id from any native Agent conversation.

## ADDED Requirements

### Requirement: Case generation is prepared for the current native Agent

The system SHALL persist a business task and a source-frozen handoff before analysis, SHALL expose bounded context, source, question, draft-validation and publication tools to the current Agent, and SHALL NOT create or start another interactive Agent thread.

#### Scenario: Web task waits for Agent pickup

- **WHEN** a user starts Case generation from the console
- **THEN** the response contains the persisted task and handoff plus a copyable system-skill instruction
- **AND** the task remains waiting for pickup until that same task is used by a native Agent tool call
- **AND** no Codex thread, model turn or QA operation is started

### Requirement: Case drafts support durable questions and safe revision

The system SHALL persist the latest draft, validation issues, questions, confirmations and a monotonically increasing handoff revision before creating an immutable Generation.

#### Scenario: Correct a failed draft in the same handoff

- **WHEN** a new request_id submits the expected current revision and validation returns a repairable DSL, evidence or type issue
- **THEN** the handoff persists the draft and precise issue, advances exactly one revision and remains revisable
- **AND** it does not create an empty BLOCKED Generation

#### Scenario: Answer a Case business question

- **WHEN** the current Agent records a user answer for a persisted Case question
- **THEN** the answer remains available after restart and to a new Agent session
- **AND** the answer does not become source evidence or bypass Schema and type validation
- **AND** an unknown answer remains open and cannot be silently dismissed
- **AND** an answered question does not rewrite the submitted `unresolved` DSL; the Agent must submit a new revision that applies the answer before any terminal publication
- **AND** a path, line or symbol token cannot dismiss a business-equivalence question as a source-proven fact

### Requirement: Case writes use revision checks and persistent idempotency

The system SHALL serialize each write by request identity and handoff lock, SHALL compare expected_revision and write revision+1 in the same protected operation, and SHALL return the first persisted outcome for an identical retry.

#### Scenario: Concurrent revisions race

- **WHEN** two different requests submit the same expected_revision
- **THEN** at most one request writes and the other receives a revision conflict containing the current revision

#### Scenario: Request identity is reused

- **WHEN** the same request_id is retried with identical normalized parameters
- **THEN** the first persisted response is returned even when the revision has advanced
- **AND** different parameters with the same request_id return an idempotency conflict

#### Scenario: Generation was written before task linking completed

- **WHEN** a publication retry finds the preallocated immutable Generation already written but the handoff or task was not advanced
- **THEN** identical content returns that same Generation and repairs only the missing status links
- **AND** different content returns a conflict without overwriting or publishing a second artifact

### Requirement: Formal Generation revisions are immutable successors

The system SHALL automatically create a linked successor task, handoff and Generation identity when a formal Generation is continued or regenerated, SHALL record predecessor_generation_id, and SHALL never rewrite the predecessor artifact.

#### Scenario: Continue versus regenerate latest

- **WHEN** a caller continues an existing task
- **THEN** the successor uses the predecessor's frozen scan and source scopes
- **AND** an unavailable predecessor baseline blocks that continuation instead of silently switching to latest
- **WHEN** a caller explicitly requests regenerate_latest
- **THEN** the successor freezes the latest complete scan and revalidates all source evidence, fields and types

#### Scenario: Successor write is interrupted before predecessor linking

- **WHEN** a continuation retry finds its request receipt on a successor handoff but the predecessor does not yet contain the successor link
- **THEN** it reuses that same successor task, handoff and preallocated Generation identity and repairs only the predecessor link
- **AND** it does not create a second successor or advance the predecessor revision more than once

#### Scenario: Publish available independent variants

- **WHEN** at least one Variant is independently runnable while persisted questions affect only other outputs and the caller explicitly publishes available work
- **THEN** an immutable PARTIAL Generation is created and a linked successor work item preserves the open questions
- **AND** the root business work is not reported as fully complete

#### Scenario: Final blocked publication

- **WHEN** no runnable Variant exists, no repairable issue or open question remains, and the caller explicitly finalizes the deterministic blocker
- **THEN** an immutable BLOCKED Generation may be created
- **AND** schema-valid unresolved input alone never ends the task as BLOCKED

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

The system SHALL expose waiting-for-Agent, waiting-for-input, revision-needed and ready-to-publish states from the task and handoff before a Generation artifact exists, SHALL expose `READY`, `PARTIAL` or `BLOCKED` only from an immutable Generation artifact, and SHALL derive execution eligibility only from that artifact.

#### Scenario: Generation is still being produced

- **WHEN** the handoff has not persisted an immutable Generation
- **THEN** task and handoff queries return the actual durable business state, revision, open questions and validation issues
- **AND** a task waiting for native Agent pickup is not labelled as generating
- **AND** the execution action is unavailable

#### Scenario: Execute a partially runnable Generation

- **WHEN** an immutable Generation is `PARTIAL`
- **THEN** explicit execution runs every runnable Variant in frozen order
- **AND** preserves every non-runnable Variant as a `BLOCKED` result without invoking its DATA or TARGET stages

#### Scenario: Generation cannot be executed

- **WHEN** an immutable Generation is `BLOCKED` or the associated task/handoff has failed before publication
- **THEN** the execution endpoint returns `409` with the Generation status
- **AND** no Execution or QA workflow is started

### Requirement: Write-interface Cleanup uses identities from the actual target response

The system SHALL require each write Variant to declare a structured Cleanup action, SHALL validate its Operation, input Schema, required arguments, value sources, response paths and source evidence during Generation, and SHALL allow Cleanup arguments to reference the actual TARGET response from the same Variant.

#### Scenario: Refund createOrder canary is cleaned up

- **WHEN** a `RefundFacade#createOrder` Variant successfully creates an order
- **THEN** its Cleanup calls `RefundFacade#cancel` with `refundSerialNo` extracted from the exact response path proved by the target Operation's scanned output fields
- **AND** it does not use a fixed order number or shared QA identity
