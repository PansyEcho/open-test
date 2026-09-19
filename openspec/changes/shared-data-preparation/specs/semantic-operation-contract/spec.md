## MODIFIED Requirements

### Requirement: Operation contracts expose source evidence without platform defaults

The system SHALL expose field types, business descriptions, annotations, literal source initializers and runtime-required evidence. Contracts SHALL be derived from a fixed scan independently of internal-knowledge prose and supplemented through source-backed JSON revisions. Required, conditional, enum and business-identity conclusions SHALL distinguish confirmed execution-path evidence from unknown constraints. The system SHALL NOT treat comments, field names or unconfirmed validation annotations as executed checks, classify an initializer as a safe default, or add omitted arguments during execution.

#### Scenario: Refund list pagination evidence

- **WHEN** `RefundOrderQueryRequest` declares initializers for `page` and `pageSize` and only documents `platFormId` with `@required`
- **THEN** the capability exposes the initializer values as source evidence
- **AND** none of those fields becomes runtime-required without evidence that the relevant validation actually executes
- **AND** OpenTest does not add them to an execution request

#### Scenario: On-demand contract supplementation
- **WHEN** a task needs an unconfirmed field constraint and reads its matching fixed source
- **THEN** a validated supplement is saved as a new contract revision while existing generations keep their embedded contract
- **AND** unresolved constraints are marked unknown and do not block tasks that do not depend on them
