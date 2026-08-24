## ADDED Requirements

### Requirement: New knowledge clarification stays in the original Codex task

The system SHALL preserve one Codex thread per generation attempt and represent missing user input as continuation in that thread instead of creating a new page question cycle.

#### Scenario: Candidate needs more evidence

- **WHEN** a Codex candidate remains incomplete
- **THEN** the task becomes `WAITING_FOR_COMPLETION`
- **AND** the page opens the persisted deep link for the same thread

### Requirement: Historical page questions are read-only

The system SHALL retain historical question-cycle data without allowing new page answers or reanalysis submissions.

#### Scenario: Legacy question mutation request

- **WHEN** a client calls a historical question-cycle mutation endpoint
- **THEN** the API returns a retired-flow error and an available Codex deep link
- **AND** no historical record is changed

### Requirement: The right pane lists Codex tasks

The knowledge page SHALL keep the three-pane layout and replace question controls with current-system Codex generation attempts.

#### Scenario: Incomplete task

- **WHEN** an attempt has a persisted Codex thread and a nonterminal client status
- **THEN** its card shows current stage, last update and “在 Codex 中继续”
- **AND** clicking the card opens the stored thread without creating or resuming another thread
