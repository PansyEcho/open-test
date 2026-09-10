## ADDED Requirements

### Requirement: Scan history reuses bounded in-memory summaries

The system SHALL cache only lightweight scan-history summaries by system, path, file modification time and size. It SHALL parse only new or changed manifests one at a time, release complete manifests, enforce cache entry and byte limits and obtain latest identity without parsing complete manifests.

#### Scenario: Repeated history read
- **WHEN** scan files are unchanged
- **THEN** cached summaries are reused without reparsing full manifests and latest is evaluated from the current pointer

#### Scenario: Scan files change or cache fills
- **WHEN** a scan is added, changed or deleted, or the cache exceeds its limits
- **THEN** new or changed files are parsed, deleted summaries are removed and least recently used summaries are evicted
- **AND** invalid or cross-system manifests still fail validation rather than serving a known stale summary
