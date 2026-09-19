## MODIFIED Requirements

### Requirement: Resource configuration environment is explicit and scan-bound

The system SHALL retain each scan's selected discovery filter as source evidence while each project's logical qa/uat execution profile independently selects its current non-production qa/test/dev/uat configuration. Runtime connections SHALL be resolved once per execution; scan-bound operation identity and business contracts SHALL remain unchanged.

#### Scenario: User selects a concrete environment
- **WHEN** a project chooses a concrete qa/test/dev/uat configuration filter for scanning
- **THEN** discovery resolves that filter and records its source evidence
- **AND** a later execution uses the target project's chosen logical qa/uat profile for routing and resources rather than freezing runtime connections to the scan

#### Scenario: Auto compatibility mode is selected
- **WHEN** an existing qa profile uses auto
- **THEN** the existing qa-then-test selection is resolved once and retained for the current execution
- **AND** the UI offers explicit filter selection for newly configured profiles, never guesses a logical environment from a legacy test selector
