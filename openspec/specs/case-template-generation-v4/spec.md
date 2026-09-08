# case-template-generation-v4 Specification

## Purpose
TBD - created by archiving change reconcile-v4-case-and-versioned-console. Update Purpose after archive.
## Requirements
### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL resolve one current Facade entry and reuse valid target knowledge or prepare a linked knowledge prerequisite before Case compilation.

#### Scenario: Start generation for an eligible Facade

- **WHEN** a caller prepares an existing latest Facade through the v2 Case API
- **THEN** the result identifies a persisted task and frozen handoff, or its linked knowledge prerequisite
- **AND** web mode starts execution while native mode remains in the calling Agent

#### Scenario: Target or required knowledge is unavailable

- **WHEN** the target is valid but required knowledge is missing
- **THEN** only knowledge needed for that interface is prepared and Case generation continues after publication
- **AND** absent or ambiguous targets remain precise errors without fabricated QA results

### Requirement: V4 uses the current Codex user Provider and validated model profile

Web generation SHALL use the existing local Codex runner, native Provider configuration and saved project model settings without copying credentials. Native generation SHALL use the current Agent.

#### Scenario: Create the first V4 turn

- **WHEN** a web task starts
- **THEN** one local runner receives only task-scoped OpenTest tools and the configured model and effort
- **AND** its output can update only the bound workflow and its linked prerequisite

#### Scenario: Model profile is invalid or Provider authorization fails

- **WHEN** Codex rejects model settings or Provider authorization
- **THEN** the task displays the recoverable run failure with its existing draft intact
- **AND** no successful generation is claimed without a readable published artifact

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

#### Scenario: AI proposes a MySQL observer

- **WHEN** an authorized database Runtime Function, matching source and resource evidence, one bounded parameterized read-only SELECT and a closed output schema are all present
- **THEN** the Observer may be compiled as a handoff-scoped Runtime Function
- **AND** any missing ownership, SQL, binding, evidence or schema constraint produces `BLOCKED`

#### Scenario: AI proposes a Redis or MQ observer

- **WHEN** the frozen Runtime Function registry contains an independently authorized read-only Redis or MQ observer with matching evidence, typed arguments and a closed output schema
- **THEN** the Observer may be compiled and executed through that function
- **AND** a send-only MQ Operation, missing observer function or unsupported capability produces `BLOCKED` instead of an unverified natural-language Oracle

