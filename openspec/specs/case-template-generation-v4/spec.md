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

The system SHALL model every Oracle as a channel, phase, controlled function, typed arguments and structured assertions, and SHALL preserve actual requests, responses, execution IDs, expected values, actual values and assertion outcomes. Before observations SHALL run after data preparation and before the target, and after observations MAY reference a unique before observation's known output path. Required MQ sends, internal RPC calls, Redis commands and call order without a direct observation source SHALL produce failed assertions and `FAILED` / `OBSERVATION_FAILED` while preserving independently obtained results. Return values, route probes and OpenTest's own outgoing call log SHALL NOT substitute for internal event evidence.

#### Scenario: Execute a generated Variant
- **WHEN** a persisted READY generation is executed
- **THEN** execution runs data preparation, before observations, target Operation and after observations in order
- **AND** every completed Operation trace remains visible even if a later step or observation fails

#### Scenario: AI proposes a MySQL observer
- **WHEN** an authorized database Runtime Function, matching source and resource evidence, one bounded parameterized read-only SELECT and a closed output schema are all present
- **THEN** the Observer may be compiled as a handoff-scoped Runtime Function
- **AND** an asserted database effect must match the exact resource, table and known modified fields rather than an unrelated query
- **AND** field existence alone does not discharge a write obligation; until the fixed scan proves how the affected business row is bound to this request, matching SQL observations still retain an explicit `OBSERVATION_FAILED` responsibility while preserving their independent assertion results

#### Scenario: A matching table query reads an unrelated business row
- **WHEN** an Oracle queries a matching table and changed field but the frozen evidence does not prove its row key belongs to the target write
- **THEN** the Oracle cannot establish write coverage, even if its expected value matches or its query argument references a request field
- **AND** a mere field-exists assertion is rejected as an insufficient effect observer

#### Scenario: AI proposes a Redis or MQ observer
- **WHEN** the frozen Runtime Function registry contains an independently authorized read-only Redis or MQ observer with matching evidence, typed arguments and a closed output schema
- **THEN** the state Observer may be compiled and executed through that function
- **AND** a send-only MQ operation, route probe or Redis state read does not prove a send or command occurred; a required direct observation remains an explicit failed assertion when unavailable

#### Scenario: Compare actual before and after values
- **WHEN** an after assertion references a prior observation's declared field
- **THEN** expected_value comes from the actual before read and actual_value comes from the after read, and both are persisted
- **AND** duplicate observation IDs, unknown output paths, self references and before references to target_response are rejected before execution

#### Scenario: An observation fails
- **WHEN** a before or after observer is unavailable or its arguments cannot resolve
- **THEN** the result contains a failed observation assertion, independent observations continue, and the final Variant is `FAILED` with `OBSERVATION_FAILED`

### Requirement: Input contracts preserve enum and normalized schema consistency

The system SHALL treat source-proven enum fields as scalar leaves when deriving operation fields. Input field schemas SHALL equal their corresponding nodes in the final request schema after source-required rules are applied; nested DTOs and collections SHALL retain their supported shapes.

#### Scenario: Request contains an enum with internal fields
- **WHEN** createOrder declares channelEnum whose enum class has code and desc members
- **THEN** the request contract includes channelEnum as a scalar field without channelEnum.code or channelEnum.desc bindings
- **AND** source type evidence remains available and inconsistent paths remain blocked

#### Scenario: Collection items contain runtime-required arrays
- **WHEN** input knowledge removes runtime-derived required arrays from collection item schemas
- **THEN** the field schema and final request schema remain equal and only explicit source-required rules are applied

### Requirement: Previously blocked input contracts are re-evaluated

The system SHALL rebuild an existing BLOCKED input contract from its requested scan when preparing Case generation, while retaining valid current READY contracts and historical persisted artifacts.

#### Scenario: A program projection bug has been fixed
- **WHEN** the stored contract is BLOCKED but deterministic derivation now produces a valid contract
- **THEN** generation can prepare with the corrected in-memory contract without rewriting published knowledge or invoking QA

#### Scenario: The blocker still exists
- **WHEN** re-derivation still finds incomplete or conflicting evidence
- **THEN** generation remains blocked with a precise reason

### Requirement: V4 coverage is verified against frozen scan obligations

The system SHALL freeze per-entry ProgramCaseAnalysisArtifact with the production-source Generation and compare actual compiled request partitions and Oracle bindings against its immutable coverage denominator. Missing or false AI bindings SHALL identify exact obligations for targeted supplementation. A validated Semantic Draft MAY append typed obligations but SHALL NOT delete program requirements. Existing historical generations without this asset SHALL remain readable; new starts and explicit regenerate-latest SHALL obtain the selected scan's asset.

#### Scenario: AI reports a branch outcome without a matching request
- **WHEN** a coverage binding claims FALSE but all compiled input vectors evaluate to TRUE
- **THEN** generation reports `DECISION_OUTCOME_UNCOVERED` and does not accept the declared outcome as proof

#### Scenario: AI omits a required program partition
- **WHEN** a fixed decision, boundary or factor has no matching bindings or required values
- **THEN** compilation returns a precise missing-coverage issue without reducing the denominator

#### Scenario: A newer scan is published
- **WHEN** an existing Generation is continued or executed after another scan appears
- **THEN** its scan identity, program obligations and expected values remain fixed, and execution records differences for human judgment
- **AND** only explicit regenerate-latest creates a successor using newer scan assets

