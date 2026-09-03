## ADDED Requirements

### Requirement: External DSF operations come from caller source

The operation catalog SHALL expose only external DSF methods proven by a caller `sof:reference` and explicit method declaration in the same current scan.

#### Scenario: External query execution

- **WHEN** Codex selects an external READ operation
- **THEN** OpenTest uses the caller scan's fixed gs, service, version and action
- **AND** requires `dsf.service.config.env=qa` and `dsf.service.config.targetenv=test`

### Requirement: MQ sends target a scanned QA consumer

The operation catalog SHALL derive an MQ send operation from each scanned consumer with fixed NameServer and Topic configuration keys.

#### Scenario: Broker acknowledges a message

- **WHEN** an explicitly authorized MQ operation sends one message
- **THEN** no automatic retry occurs
- **AND** the result contains broker send status and message ID without connection configuration

### Requirement: Database operations are restricted and purpose-bound

The operation catalog SHALL expose scanned databases only for a single parameterized `SELECT`, `SHOW`, `EXPLAIN`, `INSERT` or `UPDATE`. Database use SHALL require interface insufficiency, an explicit user request, or a Case database step.

#### Scenario: Explicit database write

- **WHEN** an explicit write request or Case submits one parameterized INSERT or UPDATE
- **THEN** the Worker selects the WRITE pool and commits the transaction
- **AND** rolls back on failure

#### Scenario: Unsafe SQL

- **WHEN** SQL contains multiple statements, DELETE, DDL, comments or a parameter-count mismatch
- **THEN** execution fails before a database connection is opened

### Requirement: QA results preserve business data but not credentials

Facade, Job, external DSF, MQ, database, Case and oracle records SHALL preserve complete business fields and real business errors while removing configuration tokens, credentials and connection addresses.

#### Scenario: Business response contains identity fields

- **WHEN** QA returns order, passenger, merchant or contact fields
- **THEN** those business values remain in the execution record
- **AND** credential-named fields and connection values remain redacted
