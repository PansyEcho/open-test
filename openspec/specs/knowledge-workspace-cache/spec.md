# knowledge-workspace-cache Specification

## Purpose
TBD - created by archiving change codex-native-open-test-workspace. Update Purpose after archive.
## Requirements
### Requirement: Knowledge details use a bounded revision-aware projection

The system SHALL serve catalog and target lookup data from an immutable projection keyed by system, resolved scan and persisted workspace revision. It SHALL NOT retain the complete parsed scan manifest after projection construction.

#### Scenario: Repeated latest target reads

- **WHEN** the latest scan and workspace revision have not changed
- **THEN** repeated target detail requests reuse the same projection
- **AND** the complete scan manifest is not parsed again

#### Scenario: Cross-process knowledge publication

- **WHEN** another process publishes knowledge and increments the workspace revision
- **THEN** the next request rebuilds the projection once
- **AND** no request receives the known stale projection

### Requirement: Projection memory is bounded

The system SHALL enforce both byte and entry limits, build latest projections sequentially during startup, and release evicted generations.

#### Scenario: Cache pressure

- **WHEN** historical projections exceed either configured limit
- **THEN** least-recently-used entries are evicted
- **AND** an individually oversized projection is served without being retained

