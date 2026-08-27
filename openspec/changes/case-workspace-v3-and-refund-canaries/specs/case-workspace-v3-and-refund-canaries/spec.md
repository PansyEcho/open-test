# case-workspace-v3-and-refund-canaries Specification

## ADDED Requirements

### Requirement: Program-owned V3 execution lifecycle

The system MUST execute a V3 Variant from its frozen Scenario, Published Setup, optional Fault plan, deterministic Oracle and validated Cleanup plan. Candidate operations MUST NOT be executable. Cleanup and installed-Fault rollback MUST be attempted after downstream failure, and their result MUST influence the final Attempt status.

#### Scenario: Oracle succeeds and cleanup is verified

- **WHEN** every Setup and Action operation succeeds, Oracle expectations match and Cleanup plus recovery Oracle succeed
- **THEN** the system persists one `PASSED` Attempt with ordered stage evidence

#### Scenario: Cleanup fails after an Action failure

- **WHEN** the Action or Oracle fails and Cleanup also fails
- **THEN** the system persists a non-passing Attempt with both original and Cleanup evidence

#### Scenario: Generation still has blockers

- **WHEN** a generation is `WITH_BLOCKED` or `BLOCKED`
- **THEN** the service refuses QA execution, writes no Attempt, and the workspace does not show an execute action

### Requirement: Independent attempts

Each execution MUST create a new Attempt under exactly one Variant. Runtime fixtures and raw request inputs MUST NOT be copied into the Attempt record.

#### Scenario: One Variant is run twice

- **WHEN** the same Variant is executed twice
- **THEN** two Attempt identities and evidence histories exist

#### Scenario: Handwritten passed attempt has no production proof

- **WHEN** an Attempt claims `PASSED` but one provider-backed step cannot be related to the uniquely expected existing Operation execution for the exact Attempt ordinal, stage, status and frozen capability or resource
- **THEN** the workspace reports `BLOCKED_ATTEMPT_PROVENANCE_MISSING` or `BLOCKED_ATTEMPT_PROVENANCE_INVALID` and MUST NOT project the Entry as `PASSED`

#### Scenario: Real operation identity cannot hide a forged oracle

- **WHEN** a `PASSED` Attempt references a real Operation execution but the stored result cannot reproduce Setup/Action facts, deterministic or effect Oracle expectations, Fault entity expectations, or Cleanup recovery expectations
- **THEN** the workspace reports the corresponding result-replay blocker and MUST NOT project the Entry as `PASSED`

### Requirement: Source-bound real entry pipeline

The system MUST project lifecycle status only for current scan Entries with generated or confirmed knowledge. A target MUST NOT become `PASSED` without a production-invoker V3 Attempt whose Setup, Action, Oracle and Cleanup evidence belongs to that Entry's frozen graph.

Lifecycle status MUST be derived by the same rule/compiler/generation and runtime-current validators used by the write and execution paths. Asset counts are informational and MUST NOT advance a pipeline stage.

#### Scenario: MQ listener is not a real Entry

- **WHEN** a semantic method exists but the current scan does not classify it as an MQ Entry and no entry knowledge exists
- **THEN** the workspace does not display it as a Case target

### Requirement: V3 Case workspace

The browser MUST show Scenario templates, child Variants, independent Attempts, rule provenance, blockers, steps and evidence. It MUST NOT offer matrix confirmation or use retired V2 Case write endpoints.

#### Scenario: Failed variants are reviewed

- **WHEN** a generation contains failed or blocked Attempts
- **THEN** the workspace makes those results visible with their failure code and stage evidence
