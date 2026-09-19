## MODIFIED Requirements

### Requirement: External DSF operations come from caller source

The operation catalog SHALL expose external DSF methods proven by caller sof:reference and explicit method declarations. Execution SHALL require the actual remote project to be registered; historical caller-owned operations SHALL NOT silently change identity, while new cross-project plans prefer the provider project's own Facade. Fixed operation coordinates and contracts SHALL be separate from the once-resolved logical qa/uat execution profile.

#### Scenario: External query execution
- **WHEN** an explicitly executed historical external READ operation targets a registered remote project
- **THEN** its fixed caller operation coordinates and identity remain intact and the registered remote project's selected logical profile provides current non-production qa/test/dev/uat routing
- **AND** an unregistered remote project is blocked before Worker dispatch rather than bypassing registration through the caller
