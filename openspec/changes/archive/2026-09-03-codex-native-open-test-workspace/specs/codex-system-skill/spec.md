## ADDED Requirements

### Requirement: Every registered system has an explicit Codex operation skill

The plugin synchronization SHALL generate one explicit-only skill per registered system with a deterministic lower-case hyphenated name and a hard-bound system ID.

#### Scenario: Dotted system ID

- **WHEN** the system ID is `ifightchainsaas.java.refund.core`
- **THEN** the generated invocation name is `$open-test-ifightchainsaas-java-refund-core`
- **AND** implicit skill invocation remains disabled

#### Scenario: Missing business input

- **WHEN** the selected operation requires fields absent from the user request
- **THEN** the skill instructs Codex to request only those fields
- **AND** execution is not called with invented business identifiers
