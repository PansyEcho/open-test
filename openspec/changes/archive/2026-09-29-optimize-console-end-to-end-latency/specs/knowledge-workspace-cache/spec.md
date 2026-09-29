## MODIFIED Requirements

### Requirement: Knowledge details use a bounded revision-aware projection
The system SHALL serve catalog and target lookup data from lightweight persisted scan fields and a bounded projection cache keyed by system, resolved scan and shared workspace revision. A single target SHALL be queried by its exact identity without first constructing the entire knowledge catalog. It SHALL NOT retain complete parsed scan manifests in the console cache.

#### Scenario: Repeated latest target reads
- **WHEN** the latest scan and workspace revision have not changed
- **THEN** catalog requests reuse the same lightweight projection and target details read the exact contract and associated nodes
- **AND** neither path parses complete scan manifests

#### Scenario: Cross-process knowledge publication
- **WHEN** another process publishes knowledge and increments the workspace revision
- **THEN** the next catalog request rebuilds the projection once and the next target read observes the published contract
- **AND** browser navigation does not bypass this shared version check with a stale local detail

### Requirement: Projection memory is bounded
The system SHALL enforce both byte and entry limits and release evicted projections. File mode MAY preload latest projections sequentially. MySQL mode SHALL serve cold requests from persisted lightweight summaries without requiring startup prewarming.

#### Scenario: Cache pressure
- **WHEN** historical projections exceed either configured limit
- **THEN** least-recently-used entries are evicted
- **AND** an individually oversized projection is served without being retained

### Requirement: Scan history reuses bounded in-memory summaries
The system SHALL query MySQL scan history from existing baseline and summary metadata without downloading manifests. File mode SHALL retain bounded summaries keyed by system, path, modification time and size, parse changed manifests one at a time, and obtain latest identity without parsing complete manifests.

#### Scenario: Repeated history read
- **WHEN** history is read again
- **THEN** MySQL reads only metadata while unchanged files reuse their summaries, and latest is evaluated from the current pointer

#### Scenario: Scan files change or cache fills
- **WHEN** a file scan is added, changed or deleted, or the cache exceeds its limits
- **THEN** changed files are parsed, deleted summaries are removed and least recently used summaries are evicted
- **AND** invalid or cross-system manifests still fail validation rather than serving a known stale summary
