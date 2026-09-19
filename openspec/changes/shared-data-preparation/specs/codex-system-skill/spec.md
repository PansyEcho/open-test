## MODIFIED Requirements

### Requirement: Every registered system has an explicit Codex operation skill

The plugin synchronization SHALL generate one explicit-only skill per registered system with a deterministic lower-case hyphenated name and a hard-bound system ID.

#### Scenario: Dotted system ID

- **WHEN** the system ID is `ifightchainsaas.java.refund.core`
- **THEN** the generated invocation name is `$open-test-ifightchainsaas-java-refund-core`
- **AND** implicit skill invocation remains disabled

#### Scenario: Missing business input

- **WHEN** the selected operation requires fields absent from the user request
- **THEN** the skill first searches reusable data methods and verifies a selected fixed version can acquire data satisfying the user's actual conditions
- **AND** only necessary unresolved business input is requested from the user; execution is not called with invented business identifiers or unverified user conditions
