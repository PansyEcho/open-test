## MODIFIED Requirements

### Requirement: Environment selection loads before slow workspace catalogs
The console SHALL load configured environments when entering a visible workspace that offers environment-dependent actions, without waiting for local settings, scan history or other catalogs. Hidden workspaces SHALL NOT fetch environment data on startup or system selection. The console SHALL distinguish loading, empty configuration and failure.

#### Scenario: Scan history is slow
- **WHEN** the visible configuration or execution workspace has a slow scan-history request
- **THEN** environment selection loads independently and does not wait for history

#### Scenario: Environment read fails or system changes
- **WHEN** the environment request fails or belongs to an obsolete system
- **THEN** failure is visible without blocking other catalogs and obsolete responses do not update current selectors

#### Scenario: Initial workspace has no environment action
- **WHEN** the user starts on the workbench, knowledge or tasks page
- **THEN** only that workspace's necessary queries run and environment loading is deferred
