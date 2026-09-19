## MODIFIED Requirements

### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL resolve one current eligible Facade and derive its input contract from that fixed scan without requiring a published internal-knowledge node. Missing information SHALL be analyzed on demand in the same Case workflow; only gaps required by the current task may block it.

#### Scenario: Start generation for an eligible Facade
- **WHEN** a caller prepares an existing latest Facade through the v2 Case API
- **THEN** the result identifies a persisted task and frozen handoff containing the independent input contract
- **AND** web mode starts analysis while native mode remains in the calling Agent, and neither preparation mode invokes QA

#### Scenario: Target or required knowledge is unavailable
- **WHEN** the target exists but no internal-knowledge document has been published
- **THEN** the Case task starts from the scan contract and can read the matching source to supplement necessary constraints
- **AND** unknown unrelated fields do not block the task; an absent or ambiguous target produces a precise error

### Requirement: V4 DSL is finite, typed and provenance-checked

The system SHALL accept only structured `data_functions`, `case_templates` and `unresolved`, and shared data definitions SHALL be selected by owner, capability ID and version and embedded completely in existing `data_functions`; every cross-stage value SHALL use a typed source such as `data_output(call_id, output_name)` or `step_output(step_id, path)` instead of a free-form reference.

#### Scenario: Compile executable business variants

- **WHEN** source evidence proves business states and all required identities trace to real Runtime Operation outputs
- **THEN** the compiler expands the supported enum code/name values into deterministic Variants
- **AND** request fields, projections, defaults and output paths are type-checked before QA access

#### Scenario: Business identity uses a fabricated seed
- **WHEN** a required target identity is supplied as an invented literal or a caller condition is presented as a verified output
- **THEN** compilation or preparation rejects that unproven binding and the target mutation is not invoked
- **AND** real user conditions may be used in a query but the returned identity, ownership and relationships must be verified before use

#### Scenario: Shared method is updated after generation
- **WHEN** G1 embeds version 1 and version 2 is later published
- **THEN** G1 continues to use its embedded version 1 steps and fixed expectations while obtaining fresh business IDs at execution
- **AND** user-selected conditions are not silently replaced

#### Scenario: Variant expansion exceeds the limit

- **WHEN** a template would compile to more than 100 Variants or exceed its operation limit
- **THEN** the template is blocked without silently truncating the product

### Requirement: V4 oracles and execution results are machine-verifiable

The system SHALL model every Oracle as a channel, controlled function or observer, typed arguments and structured assertions, and SHALL preserve actual requests, responses, execution IDs, expected values, actual values and assertion outcomes, classifying behavior differences separately from data-preparation, environment/dependency and observation failures.

#### Scenario: Execute a generated Variant

- **WHEN** the user explicitly triggers an eligible persisted generation in a configured test environment
- **THEN** execution uses the generation-bound Operation and contract from its fixed scan, then runs data preparation, target Operation and validated Oracles in order
- **AND** every completed Operation trace remains visible even if a later DATA step blocks or an execution fails; cleanup is not dispatched or counted toward completion

#### Scenario: AI proposes a MySQL observer

- **WHEN** an authorized database Runtime Function, matching source and resource evidence, one bounded parameterized read-only SELECT and a closed output schema are all present
- **THEN** the Observer may be compiled as a handoff-scoped Runtime Function
- **AND** any missing ownership, SQL, binding, evidence or schema constraint produces `BLOCKED`

#### Scenario: AI proposes a Redis or MQ observer

- **WHEN** the frozen Runtime Function registry contains an independently authorized read-only Redis or MQ observer with matching evidence, typed arguments and a closed output schema
- **THEN** the Observer may be compiled and executed through that function
- **AND** a send-only MQ Operation, missing observer function or unsupported capability produces `BLOCKED` instead of an unverified natural-language Oracle

### Requirement: Input contracts preserve enum and normalized schema consistency

The system SHALL treat source-proven enum fields as scalar leaves when deriving operation fields. Input field schemas SHALL equal their corresponding nodes in the final request schema after proven execution-path constraints are applied; nested DTOs and collections SHALL retain their supported shapes.

#### Scenario: Request contains an enum with internal fields
- **WHEN** createOrder declares channelEnum whose enum class has code and desc members
- **THEN** the request contract includes channelEnum as a scalar field without channelEnum.code or channelEnum.desc bindings
- **AND** source type evidence remains available and inconsistent paths remain blocked

#### Scenario: Collection items contain runtime-required arrays
- **WHEN** the scanner finds annotations or inferred required arrays without evidence that the entry executes those checks
- **THEN** the field schema and final request schema remain equal and the uncertain requirement remains unknown rather than being accepted as a proven runtime constraint

### Requirement: Previously blocked input contracts are re-evaluated

The system SHALL rebuild an existing BLOCKED input contract from its requested scan when preparing Case generation, while retaining valid current READY contracts and historical persisted artifacts; internal knowledge publication SHALL NOT be needed for that derivation.

#### Scenario: A program projection bug has been fixed
- **WHEN** the stored contract is BLOCKED but deterministic derivation now produces a valid contract
- **THEN** generation can prepare with the corrected in-memory contract without rewriting published knowledge or invoking QA

#### Scenario: The blocker still exists
- **WHEN** re-derivation still finds incomplete or conflicting evidence required by the requested Case
- **THEN** generation remains blocked with a precise reason
