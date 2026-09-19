## MODIFIED Requirements

### Requirement: The right pane lists Codex tasks

The knowledge page SHALL stop displaying the global task list in its right pane. A unified task center SHALL reuse persisted task records, handoffs, answers, runs and diagnostics for knowledge history, contracts, Case generation and data-method tasks; business pages SHALL retain only their related task entry points.

#### Scenario: Incomplete task
- **WHEN** a task has no active executor or needs a business answer
- **THEN** its task-center detail offers continuation, saved questions, failure reasons and available results using the existing task identity
- **AND** progress survives refresh and service restart, while the knowledge page shows only the selected object's related task

#### Scenario: Agent exits without a business result
- **WHEN** the Agent session ends without a readable published asset or verified data execution result
- **THEN** the task remains failed or awaiting required information and is not marked successful solely because the session completed
