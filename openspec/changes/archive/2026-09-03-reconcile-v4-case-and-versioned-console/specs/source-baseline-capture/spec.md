## ADDED Requirements

### Requirement: Scan history exposes the revision used by knowledge and Cases

The system SHALL return `scan_id`, full commit, requested revision, resolved branch, dirty state and capture time for each successful scan, and every generated Case SHALL retain the source scan identity it used.

#### Scenario: User inspects a historical knowledge version

- **WHEN** the user selects a historical scan created from a branch, tag or commit
- **THEN** the scan catalog and knowledge tree are loaded from that exact scan
- **AND** the displayed Git baseline identifies the same immutable commit and original revision

#### Scenario: Case uses more than one source system

- **WHEN** a V4 handoff reads the target system and an authorized provider system
- **THEN** its result exposes each safe `source_system_id` and `source_scan_id`
- **AND** the console can map every source scan back to its Git baseline without exposing source-root paths

