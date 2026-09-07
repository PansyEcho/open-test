## REMOVED Requirements

### Requirement: New knowledge clarification stays in the original Codex task

**Reason:** 原生Agent主流程以持久业务task、handoff、问题和草稿为恢复边界，要求原Codex thread继续存在会让网页预建或占用第二个交互会话，并使会话丢失后的业务任务无法继续。

**Migration:** 旧记录的thread_id和deep link保持只读；历史任务首次继续时按既有task/handoff恢复，新会话通过task_id接手，不修改Codex私有会话状态。

### Requirement: The right pane lists Codex tasks

**Reason:** 任务可见性不能以持久Codex thread为筛选条件，且知识页不再承担第二套完整聊天和任务中心。

**Migration:** 工作台汇总活动与近期业务任务，知识页只紧凑展示当前目标任务、问题、失败原因和继续入口；历史thread存在时仅提供可选只读跳转。

## MODIFIED Requirements

### Requirement: Historical page questions are read-only

The system SHALL retain historical question-cycle data without allowing retired page-answer or reanalysis endpoints to mutate it. New native-Agent task questions SHALL use the durable task-scoped question and confirmation tools.

#### Scenario: Legacy question mutation request

- **WHEN** a client calls a historical question-cycle mutation endpoint
- **THEN** the API returns a retired-flow error and, when a linked business task exists, its task_id and continuation instruction
- **AND** no historical record is changed and no Agent thread is created

## ADDED Requirements

### Requirement: New knowledge clarification stays in the original business task

The system SHALL preserve one business task, handoff, draft batch and frozen scan per knowledge generation attempt and SHALL persist missing user input as task questions and confirmations independently of any Agent thread.

#### Scenario: Candidate needs business input

- **WHEN** a native-Agent candidate needs a high-impact fact that source and confirmed knowledge cannot prove
- **THEN** the same task becomes waiting for input and exposes the persisted question in task context
- **AND** the user answers in the current Agent conversation and the Agent records that answer through the task tool
- **AND** an unknown answer remains open and an omitted question is not automatically dismissed

#### Scenario: Original Agent conversation is unavailable

- **WHEN** thread_id is empty or the original Agent conversation no longer exists
- **THEN** a new conversation resumes the same task, handoff, questions, answers, draft and validation diagnostics by task_id
- **AND** OpenTest does not create or take ownership of a replacement thread

#### Scenario: Retired background Agent owner is gone

- **GIVEN** a historical background Agent task is still `PENDING` or `RUNNING` but its owning OpenTest process is no longer alive
- **WHEN** a new OpenTest service instance reads the shared task directory
- **THEN** the service marks that task `INTERRUPTED` and preserves any existing Agent evidence for read-only diagnosis
- **AND** it does not adopt the historical writer, kill an external process or block a new native-Agent business task while waiting for takeover

### Requirement: Knowledge page projects durable business tasks

The knowledge page SHALL show the current target's durable waiting, answering, repair and terminal business states without requiring thread_id, while the workbench SHALL expose active and recent tasks across targets.

#### Scenario: Web task waits for pickup

- **WHEN** a web knowledge task has been prepared but no native Agent has used its task_id
- **THEN** the page shows waiting for pickup and a copyable system-skill instruction
- **AND** it does not label the task as generating or render inferred Agent progress

### Requirement: Archive integrity failures are isolated per archive

The system SHALL validate each system archive independently for listing and SHALL expose a safe integrity state without changing the archived files or their recorded digests. Full restore SHALL continue to verify every recorded file.

#### Scenario: One historical archive has a digest mismatch

- **WHEN** one archive manifest is valid but a recorded knowledge, Case or derived file is missing or has a different digest
- **THEN** the archive list marks only that archive as damaged and disables its restore action
- **AND** other archives and unrelated native-Agent tasks remain available
- **AND** a direct restore attempt still fails the complete archive verification

#### Scenario: An archive has already been restored

- **WHEN** the active registry already contains the archived system and the archive manifest remains for audit
- **THEN** the archive list marks the record as restored instead of reporting its intentionally moved files as damaged
- **AND** the page does not offer a second restore action
