## ADDED Requirements

### Requirement: Test requests authorize preparation and verification in offline environments
The system SHALL default new Case tasks to generate_and_verify, allowing task-scoped non-production queries, data creation or adjustment, target calls and read-back assertions without stepwise permission. Explicit generate_only SHALL prohibit QA calls from that generation task. Scanning SHALL only discover and register interfaces.

#### Scenario: No reusable data method or order seed is supplied
- **WHEN** a Case requires real external business data and the user supplies no data source
- **THEN** the Agent discovers suitable operations, builds and tests a reusable data function, and queries or creates matching data
- **AND** it does not ask for a capability ID or order seed while an automatic discovery path remains

#### Scenario: Generate and verify a Case
- **WHEN** the validated Case is published in generate_and_verify mode
- **THEN** the task executes its runnable variants and preserves real DATA, TARGET and ORACLE evidence
- **AND** data and DSL defects are corrected without changing expectations to conceal target defects

#### Scenario: User prohibits execution
- **WHEN** a task is explicitly generate_only
- **THEN** it can resolve contracts and save a Generation but cannot execute data or business operations

### Requirement: Data functions remain reusable and version-fixed
The system SHALL execute a saved data-function draft by its revision, publish validated reusable versions, and embed full selected definitions in Cases. Every execution SHALL acquire and verify current business data rather than reuse a previous test order as its definition.

#### Scenario: Reuse the same data method in multiple tasks
- **WHEN** Case generation and natural-language preparation select the same fixed method version
- **THEN** both use the same typed steps and validations with independently acquired runtime data

### Requirement: Business operation completion requires correct parameters and verified results
Operation details SHALL expose independent contracts and distinguish unknown constraints from optional fields. A workflow MAY perform necessary queries, preparation, diagnosed corrections and read-back calls; each concrete request SHALL remain idempotent and unknown outcomes SHALL be inspected before another write.

#### Scenario: Cancellation wrapper needs a member identity
- **WHEN** the selected outer cancellation requires memberId through its lookup path
- **THEN** the Agent obtains that identity or chooses a sufficient order-number cancellation operation
- **AND** final cancellation is established by business response and order read-back

#### Scenario: A prior write result is unknown
- **WHEN** the request times out or loses its response
- **THEN** execution and business status are inspected before any further write, without blind request-ID replacement

#### Scenario: Bind dynamic passenger and segment collections
- **WHEN** a proven request schema contains nested arrays and runtime data supplies their leaf fields
- **THEN** indexed bindings construct bounded JSON arrays with those real values
- **AND** type conflicts and out-of-range indices stop execution before the target call

#### Scenario: A resolved offline operation has unknown mutability
- **WHEN** the operation has a proven route and request/response contract but its side effects remain unknown
- **THEN** task-scoped offline business execution may call it under the user's test authorization
- **AND** the operation remains ineligible for read-only query and Oracle steps until its read-only semantics are established

#### Scenario: A numeric transport serializes a Java integer as a decimal
- **WHEN** a data query returns an integral JSON number such as 1.0 for an integer request field
- **THEN** execution accepts the integral value without truncating fractions or accepting booleans and non-finite numbers

#### Scenario: A draft trial loses its owning process
- **WHEN** a trial has persisted operations but its execution process terminates before saving its final state
- **THEN** reading or repeating that concrete request returns the preserved evidence and an explicit unknown-outcome failure
- **AND** later draft revisions or publication do not replay that request

#### Scenario: Query and target use different date formats
- **WHEN** actual query dates use a format incompatible with a source-proven target converter
- **THEN** a bounded data transformation parses the explicit input format and emits the explicit target format at execution time
- **AND** malformed dates fail before dispatch, with the transformation fixed inside the shared version and Generation
