## MODIFIED Requirements
### Requirement: V4 oracles and execution results are machine-verifiable

The system SHALL model every Oracle as a channel, phase, controlled function, typed arguments and structured assertions, and SHALL preserve actual requests, responses, execution IDs, expected values, actual values and assertion outcomes. Before observations SHALL run after data preparation and before the target, and after observations MAY reference a unique before observation's known output path. A Variant's result SHALL be determined only by the assertions it actually executes; the system SHALL NOT add assertions derived from static scan analysis. An assertion whose observation cannot be executed SHALL fail as `OBSERVATION_FAILED` without affecting independently obtained results. Return values, route probes and OpenTest's own outgoing call log SHALL NOT be reported as evidence of internal events.

#### Scenario: Execute a generated Variant
- **WHEN** a persisted READY generation is executed
- **THEN** execution runs data preparation, before observations, target Operation and after observations in order
- **AND** every completed Operation trace remains visible even if a later step or observation fails

#### Scenario: AI proposes a MySQL observer
- **WHEN** an authorized database Runtime Function, matching source and resource evidence, one bounded parameterized read-only SELECT and a closed output schema are all present
- **THEN** the Observer may be compiled as a handoff-scoped Runtime Function
- **AND** its assertions pass or fail on the values actually read

#### Scenario: AI proposes a Redis or MQ observer
- **WHEN** the frozen Runtime Function registry contains an independently authorized read-only Redis or MQ observer with matching evidence, typed arguments and a closed output schema
- **THEN** the state Observer may be compiled and executed through that function

#### Scenario: Compare actual before and after values
- **WHEN** an after assertion references a prior observation's declared field
- **THEN** expected_value comes from the actual before read and actual_value comes from the after read, and both are persisted
- **AND** duplicate observation IDs, unknown output paths, self references and before references to target_response are rejected before execution

#### Scenario: An observation fails
- **WHEN** a before or after observer is unavailable or its arguments cannot resolve
- **THEN** the result contains a failed observation assertion, independent observations continue, and the final Variant is `FAILED` with `OBSERVATION_FAILED`

#### Scenario: Historical generation carries frozen coverage gaps
- **WHEN** a Generation created before coverage analysis was removed is executed and its variants still contain frozen observation-failure records
- **THEN** those records are ignored and the Variant result reflects only its executed assertions

### Requirement: V4 source and outer-interface discovery is scoped and version-frozen

The system SHALL expose bounded `list_source_files`, `search_source`, `read_source` and on-demand `read_outer_api_info` tools only within the handoff's authorized source scopes, while keeping registered absolute source roots out of the public catalog. The handoff SHALL list discovery candidates from the full frozen target-scope scan, including same-Facade sibling operations and the target system's own DATABASE data sources, while execution remains limited to explicitly selected operations.

#### Scenario: Working tree changes after handoff creation

- **WHEN** source files change after the source scope has frozen a Git commit snapshot
- **THEN** all V4 source reads continue against the frozen snapshot
- **AND** evidence cannot silently move to the later working tree

#### Scenario: Codex needs a provider operation

- **WHEN** the target system cannot construct a required business identity and a scanned direct dependency exposes an authorized provider Facade
- **THEN** Codex may request that exact provider Operation contract on demand
- **AND** unrequested third-party interfaces and credentials are not added to the prompt or tool result

#### Scenario: Codex selects the target system's own data source

- **WHEN** only the target operation is selected and the frozen scan contains a same-system DATABASE data source
- **THEN** the handoff lists that data source as a candidate without adding it to the Runtime registry
- **AND** selecting it with `read_outer_api_info` returns every Runtime Function it registers, including its DATA-phase `:query` and `:data` functions

#### Scenario: Codex searches inside one known source file

- **WHEN** `search_source` receives a path naming a single readable source file
- **THEN** the search is limited to that file under the same file gate as `read_source`

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

#### Scenario: Database data function declares its SQL

- **WHEN** a DATA step calls a database `:query` or `:data` Runtime Function with literal `statement`, `purpose` or `parameters`
- **THEN** those SQL protocol fields are not treated as business identity seeds
- **AND** identities projected from the step must still come from the actual database response

#### Scenario: Variant expansion exceeds the limit

- **WHEN** a template would compile to more than 100 Variants or exceed its operation limit
- **THEN** the template is blocked without silently truncating the product

## REMOVED Requirements
### Requirement: V4 coverage is verified against frozen scan obligations
**Reason**: Program coverage analysis is removed. In real scans it produced almost only framework noise and blocked publication of real Cases.
**Migration**: New generations no longer freeze a ProgramCaseAnalysisArtifact or accept coverage bindings and semantic drafts; legacy fields in stored generations and handoffs are ignored on read.
