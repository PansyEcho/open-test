## MODIFIED Requirements

### Requirement: Database operations are restricted and purpose-bound

The operation catalog SHALL expose scanned databases only for a single parameterized `SELECT`, `SHOW`, `EXPLAIN`, `INSERT`, `UPDATE` or `DELETE`. Database use SHALL require interface insufficiency, an explicit user request, or a Case database step.

#### Scenario: Explicit database write

- **WHEN** an explicit write request or Case submits one parameterized INSERT, UPDATE or DELETE
- **THEN** the Worker selects the WRITE pool and commits the transaction
- **AND** rolls back on failure

#### Scenario: Unsafe SQL

- **WHEN** SQL contains multiple statements, DDL, comments or a parameter-count mismatch
- **THEN** execution fails before a database connection is opened

