## MODIFIED Requirements

### Requirement: Generation follows the initiating interaction surface
The system SHALL accept native preparation and web automatic analysis using the existing runner. A stopped web task MAY transfer to its original Codex session through the task-scoped native-handoff API; both surfaces SHALL share authoritative handoffs and published assets.

#### Scenario: Web generation starts useful work
- **WHEN** the console requests knowledge or Case generation
- **THEN** a real local Agent starts once and the page displays authoritative progress
- **AND** any later native continuation happens only after the web worker stops

#### Scenario: Native preparation
- **WHEN** a system Skill prepares generation in native mode
- **THEN** the current Agent receives the handoff and OpenTest does not start another Agent

#### Scenario: Agent reads a large handoff
- **WHEN** a handoff contains a large frozen context
- **THEN** submission schema and typed candidates remain complete without duplicating frozen instructions

#### Scenario: Agent corrects source evidence
- **WHEN** source symbols or trace evidence are invalid
- **THEN** validation reports the exact missing evidence and allows same-task correction

### Requirement: Task questions and runs are resumable
The system SHALL preserve task context, answers, request identities and revisions. Native transfer SHALL serialize with web startup and answers; native answers SHALL NOT restart a web Agent.

#### Scenario: Answer and continue
- **WHEN** a user answers after native transfer
- **THEN** the original handoff records the answer and the native Agent continues from its current revision
- **AND** unknown answers remain open

#### Scenario: Refresh or repeat a request
- **WHEN** a run or transfer request repeats or the service restarts
- **THEN** task and run evidence are recovered without creating a duplicate executor or QA mutation

### Requirement: Case generation prepares missing target knowledge
The system SHALL use the independent operation contract and SHALL supplement missing fields on demand during the same Case workflow without requiring internal knowledge narratives.

#### Scenario: Knowledge is absent
- **WHEN** an entry has no legacy knowledge document
- **THEN** the Case workflow starts from its scan-derived contract and asks only for essential unresolved business information

### Requirement: Web run diagnostics explain revision and identify the actual conversation
The console SHALL distinguish active background analysis from stopped workflows. It SHALL open a Codex continuation link only after a successful transfer response proves that the original worker has stopped; completed-task history links remain read-only navigation.

#### Scenario: Agent is correcting a draft
- **WHEN** the web worker is active with validation gaps
- **THEN** the page shows actual background progress and does not offer premature desktop takeover

#### Scenario: Agent stopped without publication
- **WHEN** a web run stops without publication
- **THEN** its saved draft, validation issues and safe continuation remain available

#### Scenario: View the real Codex conversation
- **WHEN** a user requests native continuation of a stopped task
- **THEN** the server verifies worker termination and saves native ownership before returning the original session link
- **AND** following answers do not launch the web runner

#### Scenario: Session is not yet available
- **WHEN** the actual session identity is unavailable
- **THEN** the page explains that continuation is unavailable and never constructs a link from a run ID
