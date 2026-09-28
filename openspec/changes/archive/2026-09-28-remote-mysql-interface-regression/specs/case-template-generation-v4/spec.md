## MODIFIED Requirements

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

## ADDED Requirements

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
