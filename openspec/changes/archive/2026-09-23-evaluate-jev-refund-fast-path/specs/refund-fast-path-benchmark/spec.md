## ADDED Requirements

### Requirement: Agent entry and inner workflow are measured separately
The experiment SHALL compare an atomic-tool gpt-5.6-sol/xhigh agent, a single-workflow-tool gpt-5.6-sol/xhigh agent and direct invocation of that same Jev-backed workflow, without a low-effort arm.

#### Scenario: Full entry measurement
- **WHEN** the experiment submits a Chinese cancellation request
- **THEN** agent elapsed time includes process startup, tool selection, actual business execution and final response
- **AND** inner workflow, model decision and business-call timings are identified separately
- **AND** CLI results are not represented as measurements of desktop rendering or of the historical task

### Requirement: Jev operates on prepared semantic facts
Jev SHALL receive the masked user request, original-text target candidates, verified operation meaning and closed answer choices, while deterministic code owns operation selection, real identifiers, current-state checks and execution.

#### Scenario: Target or request is not executable
- **WHEN** the decision is negated, ambiguous, missing a target, directed at another operation or unsupported by the current cancellation policy
- **THEN** the workflow does not dispatch a cancellation
- **AND** the outcome remains visible in the experiment evidence

#### Scenario: Successful real cancellation
- **WHEN** the workflow executes an authorized single-target QA cancellation
- **THEN** its target comes from a real ticket query with unique cancellable-state validation
- **AND** it uses the existing operation service and stable request IDs
- **AND** an independent readback proves refund identity, ticket association and REFUND_CANCEL

#### Scenario: Existing cancellable QA data is exhausted
- **WHEN** the comparison needs more real refund targets
- **THEN** a fixed-version preparation function dynamically queries registered business interfaces and creates a new refund from verified eligible booking data
- **AND** each measured cancellation uses a distinct independently verified refund identity without directly modifying target database states
- **AND** preparation time is reported separately and unknown create outcomes are inspected without blindly replaying writes

### Requirement: Ten-second recommendation uses complete observations
The report SHALL retain all attempted samples, failures and time components, report the observed fraction completed within ten seconds, and identify the actual entry for which a ten-second recommendation is supported.

#### Scenario: Inner workflow is fast but the agent is slow
- **WHEN** the direct workflow meets the pilot timing target but the full agent path does not
- **THEN** the report states the remaining outer-agent cost and recommends direct routing only as justified by the measured path
- **AND** it does not claim that the existing Codex chat has achieved ten seconds
