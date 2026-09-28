## ADDED Requirements

### Requirement: Controlled model decision benchmark
The standalone benchmark SHALL compare jev-1.13.0, gpt-5.6-sol/xhigh and gpt-5.6-sol/low on the same contract, candidate values and Chinese inputs, with ten development cases and twenty held-out cases repeated three times per arm.

#### Scenario: Frozen held-out comparison
- **WHEN** the held-out benchmark runs
- **THEN** every arm receives the frozen rubric and equivalent inputs without expected labels
- **AND** failures remain in accuracy denominators and output includes correctness, unsafe routing, unresolved decisions, client latency, available token usage and separately observable CLI startup time
- **AND** historical 162.4-second execution is identified as a different workflow rather than a matched model baseline

#### Scenario: Protected credentials and identities
- **WHEN** the benchmark calls an external model
- **THEN** Jev credentials are read at runtime and sent only to the official API
- **AND** real business identifiers are replaced by locally reversible candidate placeholders and are absent from model inputs and shareable reports

### Requirement: Verified QA cancellation pilot
The experiment SHALL use the same deterministic business workflow for all arms, with three distinct real QA refund orders per arm, existing request-ID deduplication and actual identity/state readback.

#### Scenario: Successful cancellation
- **WHEN** a model selects an unambiguous cancellation with a valid single target and supported reason policy
- **THEN** the pilot queries the real ticket, validates the unique refund and current cancellable state, invokes the fixed cancel operation and independently reads back REFUND_CANCEL for the same refund
- **AND** the evidence distinguishes data preparation, model decision, business calls and total workflow time

#### Scenario: Ambiguous decision or unknown write result
- **WHEN** a decision is invalid, ambiguous, negated, targets another operation, or a write outcome is unknown
- **THEN** no alternative business write is dispatched and the uncertainty or error remains in the report
- **AND** an unknown write is inspected using the existing execution record and business state without a new write request ID

### Requirement: Evidence-based adoption recommendation
The report SHALL recommend further Jev integration only when held-out accuracy is at least 95 percent, negative or ambiguous cases have zero unsafe cancellation routes, all nine QA outcomes are verified, and Jev median client decision latency is at most half the low-effort baseline.

#### Scenario: Experiment does not meet adoption criteria
- **WHEN** a model fails any adoption criterion
- **THEN** the report preserves that failure without changing expected answers or silently falling back to another model
- **AND** existing application behavior and global model settings remain unchanged
