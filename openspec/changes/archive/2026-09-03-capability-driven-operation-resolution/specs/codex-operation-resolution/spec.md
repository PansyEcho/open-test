## ADDED Requirements

### Requirement: Codex resolves equivalent read operations without technical questions

The explicit system Skill SHALL select one sufficient READ operation from semantic search results and SHALL ask only for missing business facts that cannot be inferred from the request or field evidence.

#### Scenario: Query refund numbers by ticket number

- **WHEN** more than one READ operation can return refund numbers for the supplied ticket number
- **THEN** Codex selects one ranked operation without asking the user to choose a Facade
- **AND** pagination is chosen or omitted by the model
- **AND** an unrelated optional platform filter is not requested
- **AND** exactly one provider call is made

### Requirement: Execution preserves model-submitted arguments

The execution layer SHALL validate runtime constraints without filling, rewriting or retrying arguments.

#### Scenario: Omitted documented field

- **WHEN** a field has only documentation-required evidence and is absent from the submitted arguments
- **THEN** execution does not reject it as runtime-required
- **AND** the provider receives the exact submitted argument object

