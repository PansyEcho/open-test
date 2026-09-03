## MODIFIED Requirements

### Requirement: V4 uses the current Codex user Provider and validated model profile

The system SHALL obtain the visible model catalog from Codex App Server `model/list`, SHALL NOT read or copy Provider credentials, and SHALL resolve model settings in the order request override, saved V4 default, then Codex catalog default.

#### Scenario: Create the first V4 turn

- **WHEN** the selected model and reasoning effort are supported by the current user's Provider
- **THEN** one App Server owner starts the thread, verifies the scoped MCP server, names the thread and starts the first turn in the same App Server session with the frozen Provider, model and effort
- **AND** the first prompt is the turn input with the V4 tool scope

#### Scenario: Model profile is invalid or Provider authorization fails

- **WHEN** the model is absent, the effort is unsupported, or thread/turn startup returns a Provider error
- **THEN** the request is rejected before thread creation or the handoff converges to `FAILED`
- **AND** it does not remain indefinitely in `WAITING_FOR_AGENT`

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
