## ADDED Requirements

### Requirement: Generation follows the initiating interaction surface
The system SHALL accept `interaction_mode` as `native` or `web`, default to native preparation, and run web generation with the existing local Codex runner and task-scoped tools. Both surfaces SHALL share authoritative handoffs and published assets.

#### Scenario: Web generation starts useful work
- **WHEN** the console requests knowledge or Case generation with web interaction
- **THEN** the task starts a real local Agent run and displays progress or an actionable failure
- **AND** completing the workflow does not require copying an instruction or taking over a desktop thread

#### Scenario: Native preparation
- **WHEN** a system Skill prepares generation without web interaction
- **THEN** the current Agent receives the handoff and continues in the current conversation
- **AND** OpenTest does not start another Agent

#### Scenario: Agent reads a large handoff
- **WHEN** the knowledge handoff contains a large frozen business context
- **THEN** the Agent receives the submission schema and saved typed candidate without truncation
- **AND** repeated context reads do not duplicate frozen analysis instructions

#### Scenario: Agent corrects source evidence
- **WHEN** a candidate contains an invalid source symbol or disconnected trace steps
- **THEN** validation identifies the exact reference or adjacent symbols and gives a focused correction hint
- **AND** Java parameter-list commas are not interpreted as multiple methods; declaration and read-range checks still apply

### Requirement: Task questions and runs are resumable
The system SHALL expose task context, answers and `POST /api/v2/tasks/{task_id}/runs`, preserve request identity and revision checks, and resume web-owned work after answers.

#### Scenario: Answer and continue
- **WHEN** a user answers a web task question
- **THEN** the answer is persisted in the same handoff and the web Agent continues from that revision
- **AND** an unknown answer remains open without an automatic repeated-question loop
- **AND** answer projection and run settlement serialize task updates so an old projection cannot restore a finished run

#### Scenario: Refresh or repeat a request
- **WHEN** a page refreshes, a run request repeats, or the service restarts
- **THEN** the same task, draft and run evidence are recovered without duplicating a live Agent or QA mutation
- **AND** an unavailable run is shown as a recoverable interruption

### Requirement: Case generation prepares missing target knowledge
The system SHALL reuse current input knowledge and automatically prepare missing knowledge for the requested target before continuing Case generation.

#### Scenario: Knowledge is absent
- **WHEN** Case generation cannot resolve the target's published input knowledge
- **THEN** a linked prerequisite task generates that target's knowledge
- **AND** publication allows the original Case workflow to continue without a second user command

### Requirement: DSL persistence preserves source semantics
The system SHALL serialize valid dynamic sources without implicit literal fields, retain explicit literal null and preserve existing affected drafts through bounded storage compatibility.

#### Scenario: Dynamic reference is saved and reread
- **WHEN** a draft, variant or receipt includes a dynamic source
- **THEN** persistence and reload retain its source kind and references without introducing an explicit literal value

#### Scenario: An existing affected handoff is opened
- **WHEN** a stored typed source contains the known default `value: null` defect
- **THEN** private storage normalizes that default and preserves the task identity, revision, questions, draft and receipts
- **AND** new invalid public submissions remain rejected without corrupting the existing handoff

### Requirement: Explicit QA testing authorizes its data lifecycle
The system SHALL default an unspecified test environment to configured available `qa`, permit required QA data preparation and single parameterized DML including DELETE, and make cleanup optional. ORACLE SHALL remain read-only.

#### Scenario: Generate and execute in QA
- **WHEN** a user requests Case generation and execution without another environment
- **THEN** execution uses available canonical qa without an additional permission question
- **AND** required setup writes and existing QA data can be used without per-operation confirmation

#### Scenario: No cleanup is required
- **WHEN** a QA write Case omits cleanup
- **THEN** it can be published and executed without a cleanup blocker
- **AND** a declared cleanup still runs and contributes its real outcome to the report

#### Scenario: Only generation is requested
- **WHEN** a user requests only knowledge or Case generation
- **THEN** no QA Operation or Execution is invoked

#### Scenario: Execution fails
- **WHEN** a DATA, TARGET, ORACLE or declared CLEANUP step fails
- **THEN** the report retains the real operation evidence and failure
- **AND** an unknown write result is observed by execution identity instead of being blindly replayed
