## ADDED Requirements

### Requirement: Nullable compilation errors remain recoverable
The system SHALL accept valid JSON Schema type arrays and SHALL report incompatible types as located validation issues. Internal compilation failures with saved unpublished drafts SHALL be recoverable in the same handoff while preserving frozen source, receipts and revision checks.

#### Scenario: Resume the failed cancel draft
- **WHEN** a draft containing a nullable string comparison fails internally
- **THEN** continuing restores revision capability and normal validation can publish the corrected draft without any QA execution
- **AND** old request receipts remain idempotent and stale revisions remain rejected

### Requirement: Independent operation contracts describe business fields
The system SHALL expose target-level operation contracts without requiring legacy knowledge nodes. Supplements SHALL accept purpose, input or response descriptions independently, with source evidence and existing input-only request compatibility. MQ SHALL expose consumer message fields, and Facade responses SHALL distinguish business payload from execution envelopes.

#### Scenario: Update a contract without old knowledge
- **WHEN** a user opens an entry with no legacy node or updates only its purpose or response fields
- **THEN** the page displays the independent contract and its actual scan and task status, and offers generation or update
- **AND** internal implementation narratives and state-machine knowledge do not appear in the main knowledge directory

#### Scenario: Contract supplement belongs to a previous source scan
- **WHEN** the selected scan has no current supplement but an earlier scan contains one for the same operation
- **THEN** the entry is stale and offers an update using the selected source contract
- **AND** a current READY supplement with the matching source commit clears that stale status independently of historical narratives

### Requirement: Downstream discovery does not require provider registration
The system SHALL show direct downstream systems grouped by caller-scanned identity and their currently referenced interfaces. Missing provider registration SHALL NOT produce per-method error cards. Task-scoped downstream search SHALL inspect fixed registered scans or explicitly declared local Maven interface metadata without granting execution permissions or expanding the static directory.

#### Scenario: Inspect an unregistered provider
- **WHEN** a caller references several methods in one unregistered DSF system
- **THEN** the system appears once with expandable referenced interfaces and maintained meanings
- **AND** unrelated systems' gaps do not appear

#### Scenario: Browse external interfaces in a historical scan
- **WHEN** the user switches the knowledge workspace to a historical scan
- **THEN** its external systems and referenced interfaces use that same immutable scan as contract details
- **AND** a delayed latest system-relations response cannot replace the historical interface tree

#### Scenario: A Case needs another downstream method
- **WHEN** existing referenced interfaces cannot meet a Case need
- **THEN** the task can search additional public signatures and DTO metadata from authorized fixed sources or dependencies
- **AND** unavailable documentation remains unknown and newly found methods are not automatically executable

### Requirement: Code enums remain read-only code facts
The system SHALL classify semantically proven enums independently of entry usage, normalize historical matching candidates using existing scan facts and retain manual notes and ignore choices. Enum names and values SHALL NOT require human completion.

#### Scenario: Historical enum was classified as a term
- **WHEN** the current scan proves an enum stored as a stale business term
- **THEN** it appears as a read-only enum with constants and available source descriptions, retaining historical notes

### Requirement: Native continuation has one executor
The system SHALL start one web Agent automatically and SHALL allow native continuation only after that worker has stopped. A successful task-scoped transfer SHALL preserve task, handoff, revision and session before returning the Codex link; native answers SHALL NOT restart the web Runner.

#### Scenario: Answer in the original Codex conversation
- **WHEN** the web Agent saves a question and exits, and the user selects native continuation
- **THEN** the transfer succeeds before the original session opens, and the user's direct answer continues the same task
- **AND** duplicate transfer requests do not create another executor or conversation

#### Scenario: Background analysis remains active
- **WHEN** native continuation is requested while the web worker is active
- **THEN** the server rejects the transfer and the page keeps showing the authoritative web progress
