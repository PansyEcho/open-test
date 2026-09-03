## MODIFIED Requirements

### Requirement: Regression Case page exposes the V4 workflow and raw artifacts

The console SHALL allow a user to enter any eligible Facade path, choose generation-only or generation-plus-QA, start and poll the V4 handoff, open the bound Codex task, and inspect the raw generation and execution JSON. Every asynchronous success and error path SHALL verify the request generation and active view before changing shared V4 page state.

#### Scenario: V4 handoff reaches a terminal state

- **WHEN** the handoff becomes `COMPLETED`, `PARTIAL`, `BLOCKED` or `FAILED`
- **THEN** the page shows the frozen model, turn state, DSL, Variants, Operation request/response traces, structured assertions and source-scan Git mappings that are present
- **AND** missing or failed data remains explicit in the JSON

#### Scenario: User switches from polling to generation history

- **WHEN** the user requests the existing V4 Generation list while a handoff request is in flight
- **THEN** the console invalidates both late successful responses and late errors from the older view
- **AND** the user-selected Generation JSON is not overwritten by stale polling

#### Scenario: Invalidated handoff request fails after the view switch

- **WHEN** an older handoff poll or initial status read rejects after the user has selected Generation history
- **THEN** its error handler does not replace the Generation status, error area or raw JSON
- **AND** no retry timer is scheduled for the invalidated handoff view
