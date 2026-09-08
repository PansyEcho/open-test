## MODIFIED Requirements

### Requirement: New knowledge clarification stays in the original Codex task

The system SHALL keep clarification in the initiating interaction mode: native tasks use the current Codex conversation and web tasks use persisted task questions in the console. Both modes SHALL share authoritative handoffs and published knowledge.

#### Scenario: Candidate needs more evidence

- **WHEN** a candidate remains incomplete
- **THEN** validation gaps remain available in the same task for revision
- **AND** source-answerable gaps are handled by the Agent; only indispensable unresolved business questions wait for the user

#### Scenario: Web user answers a question

- **WHEN** the user answers a web task's open question
- **THEN** the answer is saved and the same workflow continues in the web runner
- **AND** unknown answers remain open and are not interpreted as confirmation

### Requirement: The right pane lists Codex tasks

The knowledge page SHALL display persisted business tasks with progress, questions, failures and published outcomes.

#### Scenario: Incomplete task

- **WHEN** a task has no active executor or needs a business answer
- **THEN** its card offers web continuation or answer controls using the existing task identity
- **AND** progress survives page refresh and service restart
