## MODIFIED Requirements

### Requirement: External DSF operations come from caller source

The operation catalog SHALL expose only external DSF methods proven by a caller `sof:reference` and explicit method declaration in the same current scan. Execution SHALL use the declaring caller system's frozen DSF client profile and the frozen caller scan's gs, service, version and action; a frozen resolved dependency definition may carry its provider-resolved version. Provider registration or provider source availability SHALL NOT change that profile.

#### Scenario: External query execution

- **WHEN** Codex selects an external READ operation from a scan bound to a selected resource configuration
- **THEN** OpenTest uses that frozen caller scan's gs, service and action together with the caller system's frozen DSF client profile
- **AND** a frozen resolved dependency definition, when present, supplies its provider-resolved version for that operation
- **AND** the caller profile supplies the routing and target environments, both of which must belong to the allowed non-production `qa`, `test` or `uat` set

#### Scenario: Registered provider does not own the caller profile

- **WHEN** an external DSF reference's provider is a registered project with its own source and profile
- **THEN** the call still uses the declaring caller's fixed profile and never resolves the provider as the execution profile owner
- **AND** a provider profile or missing provider source cannot block or redirect that external reference
