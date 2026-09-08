## ADDED Requirements

### Requirement: Web run diagnostics explain revision and identify the actual conversation
The console SHALL distinguish validation during an active Agent run from a stopped workflow and SHALL provide read-only diagnostics for the actual task-bound web run for both knowledge and Case generation. A Codex conversation link SHALL be shown only after the run records a valid session identity. Questions and continuation SHALL remain on the initiating interaction surface.

#### Scenario: Agent is correcting a draft
- **WHEN** an active web run has draft validation issues
- **THEN** the dialog explains that the Agent is revising the draft and places technical issue details in a collapsed disclosure
- **AND** a later refresh reflects cleared issues and the published Generation

#### Scenario: Agent stopped without publication
- **WHEN** a web run stops with unresolved validation issues
- **THEN** the dialog retains those issues and the existing failure or continuation actions without claiming that automatic revision is still active

#### Scenario: View the real Codex conversation
- **WHEN** the user expands run diagnostics for a web Case or knowledge task
- **THEN** the server reads the task's web run evidence instead of a legacy handoff run
- **AND** the console offers the recorded Codex session link only after a successful diagnostics response
- **AND** opening the link does not create a task, resume an Agent or move questions out of the web page

#### Scenario: Session is not yet available
- **WHEN** the run has no recorded session identity or diagnostics cannot be read
- **THEN** the console explains the unavailable state without constructing a link from a run ID or breaking the task context
- **AND** explicit progress refresh rereads a completed or failed diagnostics request for the same run while keeping its disclosure open, so a newly recorded session becomes visible
- **AND** an in-flight diagnostics request is reused instead of duplicated
