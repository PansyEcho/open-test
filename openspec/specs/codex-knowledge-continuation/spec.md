# codex-knowledge-continuation Specification

## Purpose
TBD - created by archiving change codex-native-open-test-workspace. Update Purpose after archive.
## Requirements
### Requirement: New knowledge clarification stays in the original Codex task
The system SHALL persist questions in the authoritative task and SHALL support transferring a stopped web analysis to its original Codex session. After transfer, clarification SHALL remain in that native conversation and SHALL NOT start another web Runner.

#### Scenario: Candidate needs more evidence
- **WHEN** an incomplete candidate requires source analysis
- **THEN** validation gaps remain revisable in the same task and only indispensable business questions wait for the user

#### Scenario: Web analysis needs an answer
- **WHEN** the Agent saves a business question and the worker exits
- **THEN** the page offers native continuation after a successful task transfer
- **AND** the user can directly answer in the original Codex conversation without a separate start action

### Requirement: Historical page questions are read-only

The system SHALL retain historical question-cycle data without allowing new page answers or reanalysis submissions.

#### Scenario: Legacy question mutation request

- **WHEN** a client calls a historical question-cycle mutation endpoint
- **THEN** the API returns a retired-flow error and an available Codex deep link
- **AND** no historical record is changed

### Requirement: The right pane lists Codex tasks
The knowledge page SHALL expose persistent current-object tasks and the task center SHALL retain progress, questions, failures and published outcomes.

#### Scenario: Incomplete task
- **WHEN** a task has no active executor or needs a business answer
- **THEN** its card offers safe continuation using the same task identity
- **AND** progress and answers survive page refresh and service restart

