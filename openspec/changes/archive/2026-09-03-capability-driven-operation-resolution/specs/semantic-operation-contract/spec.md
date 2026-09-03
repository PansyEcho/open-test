## ADDED Requirements

### Requirement: Operation contracts expose source evidence without platform defaults

The system SHALL expose field types, business descriptions, annotations, literal source initializers and runtime-required evidence. It SHALL NOT classify a source initializer as a safe default or add any omitted argument during execution.

#### Scenario: Refund list pagination evidence

- **WHEN** `RefundOrderQueryRequest` declares initializers for `page` and `pageSize` and only documents `platFormId` with `@required`
- **THEN** the capability exposes the initializer values as source evidence
- **AND** none of those fields becomes runtime-required without a validation constraint
- **AND** OpenTest does not add them to an execution request

### Requirement: Historical scan truth remains immutable

The system SHALL rebuild the derived operation index for the current capability schema without changing an existing scan manifest, published knowledge or Codex task identity.

#### Scenario: A v3 manifest receives a v2 operation projection

- **WHEN** its registered source still matches the manifest baseline
- **THEN** deterministic semantic evidence may be recalculated for the derived index
- **AND** the manifest, published knowledge file, task and thread remain unchanged

### Requirement: DSF execution preserves distinct QA routing evidence

The system SHALL preserve `dsf.service.config.env` independently from `dsf.service.config.targetenv` and SHALL pass both source-proven values to DSF Client. A legacy immutable scan MAY derive the missing routing environment only when its remaining client identity still matches registered source evidence.

#### Scenario: QA routing environment differs from target environment

- **WHEN** registered source declares `env=qa` and `targetenv=test`
- **THEN** the Worker receives both properties without substituting one for the other
- **AND** DSF Client resolves the QA-prefixed service group
- **AND** the historical Manifest remains byte-for-byte unchanged

#### Scenario: DSF Worker returns a failed operation result

- **WHEN** the Worker protocol completes with a stable failed response
- **THEN** the outer operation execution is persisted as failed with the same safe error classification
- **AND** the same idempotency request does not dispatch the provider again
