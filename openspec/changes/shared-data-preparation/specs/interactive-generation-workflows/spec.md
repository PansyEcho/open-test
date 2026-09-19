## MODIFIED Requirements

### Requirement: Generation follows the initiating interaction surface
The system SHALL accept `interaction_mode` as `native` or `web`, default to native preparation, and run web generation with the existing local Codex runner and task-scoped tools. Both surfaces SHALL share authoritative handoffs and published assets.

#### Scenario: Web generation starts useful work
- **WHEN** the console requests contract, shared-data-method or Case generation with web interaction
- **THEN** the task starts a real local Agent run and displays progress or an actionable failure
- **AND** completing the workflow does not require copying an instruction or taking over a desktop thread

#### Scenario: Native preparation
- **WHEN** a system Skill prepares generation without web interaction
- **THEN** the current Agent receives the handoff and continues in the current conversation
- **AND** OpenTest does not start another Agent

#### Scenario: Agent reads a large handoff
- **WHEN** a task handoff contains a large frozen business context
- **THEN** the Agent receives the task-specific submission schema and saved typed draft without truncation
- **AND** repeated context reads do not duplicate frozen analysis instructions

#### Scenario: Agent corrects source evidence
- **WHEN** a candidate contains an invalid source symbol or disconnected trace steps
- **THEN** validation identifies the exact reference or adjacent symbols and gives a focused correction hint
- **AND** Java parameter-list commas are not interpreted as multiple methods; declaration and read-range checks still apply

### Requirement: Case generation prepares missing target knowledge

The system SHALL obtain the requested target's independent scan-bound contract and supplement necessary constraints on demand, without generating internal implementation prose or a linked long-form knowledge prerequisite.

#### Scenario: Knowledge is absent
- **WHEN** Case generation finds no published internal knowledge for its target
- **THEN** it prepares the same Case task using the matching Operation contract and scoped source tools
- **AND** only unresolved information needed by the requested Case remains a blocker

### Requirement: Explicit QA testing authorizes its data lifecycle
The system SHALL default an unspecified test environment to configured available `qa`, permit required QA data preparation and single parameterized DML including DELETE, and retain prepared data without requiring, generating or executing cleanup. ORACLE SHALL remain read-only.

#### Scenario: Generate and execute in QA
- **WHEN** a user requests Case generation and execution without another environment
- **THEN** execution uses available canonical qa without an additional permission question
- **AND** required setup writes and existing QA data can be used without per-operation confirmation

#### Scenario: No cleanup is required
- **WHEN** a QA write Case omits cleanup
- **THEN** it can be published and executed without a cleanup blocker
- **AND** historical cleanup declarations remain readable but are excluded from new dispatch, operation limits and success judgment

#### Scenario: Only generation is requested
- **WHEN** a user requests only contract/data-method supplementation or Case generation
- **THEN** no QA Operation or Execution is invoked

#### Scenario: Execution fails
- **WHEN** a DATA, TARGET or ORACLE step fails
- **THEN** the report retains the real operation evidence and classifies preparation, environment/dependency, observation failure or actual behavior difference separately
- **AND** an unknown write result is observed by execution identity instead of being blindly replayed

### Requirement: Web run diagnostics explain revision and identify the actual conversation
The console SHALL distinguish validation during an active Agent run from a stopped workflow and SHALL provide read-only diagnostics for the actual task-bound web run for knowledge history, contract supplementation, shared data methods and Case generation. A Codex conversation link SHALL be shown only after the run records a valid session identity. Questions and continuation SHALL remain on the initiating interaction surface.

#### Scenario: Agent is correcting a draft
- **WHEN** an active web run has draft validation issues
- **THEN** the dialog explains that the Agent is revising the draft and places technical issue details in a collapsed disclosure
- **AND** a later refresh reflects cleared issues and the published Generation

#### Scenario: Agent stopped without publication
- **WHEN** a web run stops with unresolved validation issues
- **THEN** the dialog retains those issues and the existing failure or continuation actions without claiming that automatic revision is still active

#### Scenario: View the real Codex conversation
- **WHEN** the user expands run diagnostics for a web Case, contract, shared-data-method or historical knowledge task
- **THEN** the server reads the task's web run evidence instead of a legacy handoff run
- **AND** the console offers the recorded Codex session link only after a successful diagnostics response
- **AND** opening the link does not create a task, resume an Agent or move questions out of the web page

#### Scenario: Session is not yet available
- **WHEN** the run has no recorded session identity or diagnostics cannot be read
- **THEN** the console explains the unavailable state without constructing a link from a run ID or breaking the task context
- **AND** explicit progress refresh rereads a completed or failed diagnostics request for the same run while keeping its disclosure open, so a newly recorded session becomes visible
- **AND** an in-flight diagnostics request is reused instead of duplicated
