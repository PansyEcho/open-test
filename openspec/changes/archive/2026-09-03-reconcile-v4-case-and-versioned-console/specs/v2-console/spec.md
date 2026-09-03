## ADDED Requirements

### Requirement: Console shows scan Git identity with the bound knowledge catalog

The console SHALL show the selected scan's full commit, revision, branch, dirty state and scan ID beside the scan catalog, and SHALL update the knowledge catalog and Git card as one versioned selection.

#### Scenario: Historical catalog load succeeds

- **WHEN** the user changes the scan-history selection
- **THEN** the console loads that scan's catalog and knowledge tree before declaring the new Git baseline current

#### Scenario: Historical catalog load fails

- **WHEN** the selected historical catalog cannot be loaded
- **THEN** the console restores the previously confirmed scan selection and baseline
- **AND** it does not label the old visible knowledge tree with the failed new commit

### Requirement: Regression Case page exposes the V4 workflow and raw artifacts

The console SHALL allow a user to enter any eligible Facade path, choose generation-only or generation-plus-QA, start and poll the V4 handoff, open the bound Codex task, and inspect the raw generation and execution JSON.

#### Scenario: V4 handoff reaches a terminal state

- **WHEN** the handoff becomes `COMPLETED`, `PARTIAL`, `BLOCKED` or `FAILED`
- **THEN** the page shows the frozen model, turn state, DSL, Variants, Operation request/response traces, structured assertions and source-scan Git mappings that are present
- **AND** missing or failed data remains explicit in the JSON

#### Scenario: User switches from polling to generation history

- **WHEN** the user requests the existing V4 Generation list while a handoff request is in flight
- **THEN** the console invalidates both late successful responses and late errors from the older view
- **AND** the user-selected Generation JSON is not overwritten by stale polling

