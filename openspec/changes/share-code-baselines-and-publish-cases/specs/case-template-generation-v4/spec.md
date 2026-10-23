## MODIFIED Requirements

### Requirement: V4 resolves any eligible latest Facade entry

The system SHALL resolve one visible Facade entry in the selected fixed code baseline and published/mine view and reuse valid target knowledge or prepare a linked knowledge prerequisite before Case compilation.

#### Scenario: Start generation for an eligible Facade

- **WHEN** a caller prepares an visible Facade in the selected baseline through the v2 Case API
- **THEN** the result identifies a persisted task and frozen handoff, or its linked knowledge prerequisite
- **AND** web mode starts execution while native mode remains in the calling Agent

#### Scenario: Web prompt uses the persisted task environment

- **WHEN** a web Case task starts or resumes analysis using a persisted TaskRecord
- **THEN** prompt and coverage lookup use the environment frozen in task result without requiring an undeclared TaskRecord field
- **AND** only legacy tasks lacking that field use the existing QA default

#### Scenario: Target or required knowledge is unavailable

- **WHEN** the target is valid but required knowledge is missing
- **THEN** only knowledge needed for that interface is prepared and Case generation continues after the knowledge draft is available to the same employee or explicitly published
- **AND** absent or ambiguous targets remain precise errors without fabricated QA results


## ADDED Requirements

### Requirement: Shared Case revisions preserve current visibility and frozen task scope

The system SHALL reject whole-Generation continuation of terminal shared-baseline tasks before creating a successor task or restoring a continuation receipt. Revisions SHALL start from one currently visible Case, select current visible knowledge for its actual dependencies once, and freeze those references for the new task.

#### Scenario: Terminal shared task requests continuation

- **WHEN** a shared-baseline task with completed, partial or blocked compiled output requests either continuation intent through the task API or core service
- **THEN** the request is rejected before any successor task, handoff, or receipt is created or restored
- **AND** the caller is directed to current single-Case revisions, with hidden sibling and replaced content remaining hidden and the existing environment unchanged

#### Scenario: Active shared draft resumes

- **WHEN** an employee continues an active shared-baseline draft with the correct revision
- **THEN** the original task resumes with its baseline, employee, environment, source scopes and saved draft preserved
- **AND** no successor is created

#### Scenario: Revising a Case affected by updated dependency knowledge

- **WHEN** a new single-Case revision is created after knowledge of an actually used dependency changes
- **THEN** the new task selects the current visible dependency knowledge in its chosen view and freezes that version
- **AND** a target rescanned at the same commit uses only its newly selected target scan, without inheriting the old target scan
- **AND** later publication changes do not mutate an already active task's frozen references

#### Scenario: Data preparation and cleanup use distinct dependency identities

- **WHEN** a selected Case calls a database Runtime function such as an operation's `:query` or `:data` alias, or references an interface only through cleanup
- **THEN** revision seeding and final Case bindings resolve the actual provider operation and source system from the frozen Runtime catalog or cleanup operation
- **AND** the required source scope and knowledge version remain attached to that Case for compilation and publication checks

#### Scenario: Shared Case executes on a computer without the author's source repository

- **WHEN** an employee executes selected shared Cases in QA or UAT on another computer
- **THEN** the target and any explicitly selected provider Facade read their configuration from materialized source for their frozen scans
- **AND** an external DSF reference from a frozen scan executes with the declaring caller's frozen DSF profile, without requiring the provider's source material
- **AND** missing or unrelated local repository bindings cannot change either execution profile
- **AND** missing frozen caller source, or missing frozen source for an explicitly selected provider Facade, produces an explicit error before business execution without mutating global source bindings or another execution's profiles

#### Scenario: External dependency executes with the caller profile

- **WHEN** a shared Case data or observation step calls an external DSF reference declared by a frozen caller scan
- **THEN** execution uses that caller's frozen DSF client profile and the caller's selected QA or UAT environment
- **AND** the provider's registration state, latest scan or missing source material does not block the call
- **AND** no provider source scope is added solely to resolve the external reference's execution profile

### Requirement: Explicit step schemas close incomplete fixed response contracts
The system SHALL merge an explicitly declared step or observer output schema into branches that the fixed dependency response contract leaves open (for example `list={}` or `saasOrderVO={}`), while scanned types and constraints remain authoritative. A complete scanned schema SHALL NOT be widened by an agent declaration, and repeated resolution SHALL NOT replace an existing closed response contract with an open one.

#### Scenario: Fixed dependency exposes an empty nested response field
- **WHEN** a DATA step calls a fixed operation whose response schema only registers `list={}` or `saasOrderVO={}`, and the agent declares a complete `output_schema` from the fixed source
- **THEN** compilation merges the missing branches and resolves downstream step outputs, arguments and assertions without UNKNOWN_STEP_OUTPUT
- **AND** scanned types and constraints remain authoritative; a complete scanned schema cannot gain assertion paths from the declaration
- **AND** resolving the same interface again with only empty branches keeps the last closed response contract and does not downgrade fixed knowledge
