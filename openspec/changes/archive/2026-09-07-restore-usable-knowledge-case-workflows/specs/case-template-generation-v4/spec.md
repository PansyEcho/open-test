## MODIFIED Requirements

### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL resolve one current Facade entry and reuse valid target knowledge or prepare a linked knowledge prerequisite before Case compilation.

#### Scenario: Start generation for an eligible Facade

- **WHEN** a caller prepares an existing latest Facade through the v2 Case API
- **THEN** the result identifies a persisted task and frozen handoff, or its linked knowledge prerequisite
- **AND** web mode starts execution while native mode remains in the calling Agent

#### Scenario: Target or required knowledge is unavailable

- **WHEN** the target is valid but required knowledge is missing
- **THEN** only knowledge needed for that interface is prepared and Case generation continues after publication
- **AND** absent or ambiguous targets remain precise errors without fabricated QA results

### Requirement: V4 uses the current Codex user Provider and validated model profile

Web generation SHALL use the existing local Codex runner, native Provider configuration and saved project model settings without copying credentials. Native generation SHALL use the current Agent.

#### Scenario: Create the first V4 turn

- **WHEN** a web task starts
- **THEN** one local runner receives only task-scoped OpenTest tools and the configured model and effort
- **AND** its output can update only the bound workflow and its linked prerequisite

#### Scenario: Model profile is invalid or Provider authorization fails

- **WHEN** Codex rejects model settings or Provider authorization
- **THEN** the task displays the recoverable run failure with its existing draft intact
- **AND** no successful generation is claimed without a readable published artifact
