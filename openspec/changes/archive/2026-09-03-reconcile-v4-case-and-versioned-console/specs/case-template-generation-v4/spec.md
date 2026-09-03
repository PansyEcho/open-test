## ADDED Requirements

### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL accept a raw `fully.qualified.Facade#method` or canonical Facade Entry ID, resolve exactly one Entry from the target system's latest scan, and require current READY input knowledge before creating a Case generation handoff.

#### Scenario: Start generation for an eligible Facade

- **WHEN** a caller posts an existing latest READY Facade identity to `/api/v4/systems/{system_id}/case-generations`
- **THEN** the system returns `202` with a handoff ID, thread ID, turn ID, polling URL and Codex deep link
- **AND** the handoff freezes the target Entry, source scan and directly authorized source-system scopes

#### Scenario: Target or required knowledge is unavailable

- **WHEN** the identity is absent, ambiguous, stale or lacks READY input knowledge
- **THEN** the system rejects the request before model execution
- **AND** it does not fabricate a request, Variant or successful QA result

### Requirement: V4 uses the current Codex user Provider and validated model profile

The system SHALL obtain the visible model catalog from Codex App Server `model/list`, SHALL NOT read or copy Provider credentials, and SHALL resolve model settings in the order request override, saved V4 default, then Codex catalog default.

#### Scenario: Create the first V4 turn

- **WHEN** the selected model and reasoning effort are supported by the current user's Provider
- **THEN** one App Server owner starts the thread and first turn atomically with the frozen Provider, model and effort
- **AND** the first prompt is the turn input with the V4 tool scope

#### Scenario: Model profile is invalid or Provider authorization fails

- **WHEN** the model is absent, the effort is unsupported, or thread/turn startup returns a Provider error
- **THEN** the request is rejected before thread creation or the handoff converges to `FAILED`
- **AND** it does not remain indefinitely in `WAITING_FOR_AGENT`

### Requirement: V4 source and outer-interface discovery is scoped and version-frozen

The system SHALL expose bounded `list_source_files`, `search_source`, `read_source` and on-demand `read_outer_api_info` tools only within the handoff's authorized source scopes, while keeping registered absolute source roots out of the public catalog.

#### Scenario: Working tree changes after handoff creation

- **WHEN** source files change after the source scope has frozen a Git commit snapshot
- **THEN** all V4 source reads continue against the frozen snapshot
- **AND** evidence cannot silently move to the later working tree

#### Scenario: Codex needs a provider operation

- **WHEN** the target system cannot construct a required business identity and a scanned direct dependency exposes an authorized provider Facade
- **THEN** Codex may request that exact provider Operation contract on demand
- **AND** unrequested third-party interfaces and credentials are not added to the prompt or tool result

### Requirement: V4 DSL is finite, typed and provenance-checked

The system SHALL accept only structured `data_functions`, `case_templates` and `unresolved`, and every cross-stage value SHALL use a typed source such as `data_output(call_id, output_name)` or `step_output(step_id, path)` instead of a free-form reference.

#### Scenario: Compile executable business variants

- **WHEN** source evidence proves business states and all required identities trace to real Runtime Operation outputs
- **THEN** the compiler expands the supported enum code/name values into deterministic Variants
- **AND** request fields, projections, defaults and output paths are type-checked before QA access

#### Scenario: Business identity uses a fabricated seed

- **WHEN** a required DATA query condition ultimately comes from an arbitrary literal, random value, placeholder or function input wrapping such a value
- **THEN** compilation returns a precise issue or `BLOCKED`
- **AND** the target mutation is not invoked

#### Scenario: Variant expansion exceeds the limit

- **WHEN** a template would compile to more than 100 Variants or exceed its operation limit
- **THEN** the template is blocked without silently truncating the product

### Requirement: V4 oracles and execution results are machine-verifiable

The system SHALL model every Oracle as a channel, controlled function or observer, typed arguments and structured assertions, and SHALL preserve actual requests, responses, execution IDs, expected values, actual values and assertion outcomes.

#### Scenario: Execute a generated Variant

- **WHEN** a READY generation uses `QA_AFTER_GENERATION`
- **THEN** execution is dispatched after DSL persistence and runs data preparation, target Operation and validated Oracles in order
- **AND** every completed Operation trace remains visible even if a later DATA step blocks or an execution fails

#### Scenario: AI proposes a database, Redis or MQ observer

- **WHEN** the observer has matching source evidence, authorized resource ownership, read-only syntax, bound parameters and a closed output schema
- **THEN** it may be compiled as a handoff-scoped Runtime Function
- **AND** missing evidence or unsupported observer capability produces `BLOCKED` instead of an unverified natural-language Oracle

