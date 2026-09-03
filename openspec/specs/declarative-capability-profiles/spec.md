# declarative-capability-profiles Specification

## Purpose
TBD - created by archiving change capability-driven-operation-resolution. Update Purpose after archive.
## Requirements
### Requirement: Business identities are data, not production control-flow literals

The system SHALL load system matching, operation aliases, Job scan rules, Worker identity and legacy workflow identities from validated Capability Profiles. Production control flow SHALL NOT compare business identity fields with concrete business literals or module constants.

#### Scenario: A second system profile is installed

- **WHEN** a reviewed profile defines a different system and operation alias
- **THEN** the same catalog, search and execution code resolves it
- **AND** no source-code branch is added for that system or method name

