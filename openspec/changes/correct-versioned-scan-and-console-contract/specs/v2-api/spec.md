## MODIFIED Requirements

### Requirement: API覆盖单系统闭环

FastAPI SHALL 通过`/api/v2`提供系统配置、扫描、知识、资源、Operation、Case Generation与独立Execution接口，不再提供Scenario、Snapshot、MVP、Suite或历史Case编译与执行入口。

#### Scenario: 从扫描到显式执行

- **WHEN** 调用方依次配置系统、扫描、发布知识、创建Generation并显式创建Execution
- **THEN** Generation和Execution保持`system_id`、`source_scan_id`、`generation_id`与`execution_id`追溯链
- **AND** 只有Execution入口允许Case流程访问QA

#### Scenario: 调用已移除的Case路由

- **WHEN** 调用方请求历史Scenario、Snapshot、typed Case、Hybrid Case或单Variant执行路由
- **THEN** 服务返回`404`
- **AND** 不创建任何Case或访问QA

### Requirement: API exposes recoverable native-Agent tasks

FastAPI SHALL expose task listing, task context, durable questions, Case draft validation, formal publication and explicit continuation through `/api/v2`, and every generation start SHALL return a persisted task identity.

#### Scenario: Continue a task without a thread

- **WHEN** a caller requests a persisted knowledge or Case task whose thread_id is empty or unavailable
- **THEN** the API returns its handoff, questions, answers, draft, validation result and continuation actions
- **AND** it does not create a replacement Agent thread

### Requirement: API pins an immutable source version

FastAPI SHALL persist a managed local Git tag and full commit for each Git-backed system, SHALL use that pin for ordinary scans, and SHALL expose a separate explicit source-version update that changes the pin and starts a scan.

#### Scenario: Register a Git-backed system

- **WHEN** a caller registers a system with an optional source revision
- **THEN** the service resolves the revision to a full commit, creates or reuses the matching local managed tag and persists both before the first scan
- **AND** it does not checkout, modify or push the registered repository

#### Scenario: Ordinary scan cannot switch versions

- **WHEN** a registered system has a source pin and an ordinary scan omits a revision
- **THEN** the scan reads the pinned commit even if the working tree HEAD, branch or dirty state changed
- **AND** an ordinary request naming a different revision is rejected without changing the pin

#### Scenario: User explicitly updates the source baseline

- **WHEN** a loopback user invokes `POST /api/v2/systems/{system_id}/source-version` with a valid revision
- **THEN** the service creates or reuses the managed tag, persists the new pin and returns the associated scan task
- **AND** a deleted, moved or conflicting managed tag blocks the operation instead of being forced or silently replaced

### Requirement: API preserves scan publication truth

FastAPI SHALL expose each immutable scan manifest's actual completeness and publication outcome in scan history and in the terminal scan task result. A scan task MAY finish successfully while its business result is a partial projection, but that result SHALL NOT be reported as a complete baseline.

#### Scenario: Reliable partial scan finishes

- **WHEN** scanning publishes reliable new results but one or more required components are partial
- **THEN** the task lifecycle is `completed` with result `completeness=partial` and `publication_outcome=partial_projection`
- **AND** scan history reports the same values with `latest=false` when the prior complete baseline remains current

#### Scenario: Read a legacy scan manifest

- **WHEN** a historical manifest predates explicit completeness and publication outcome fields
- **THEN** it remains readable using the established complete-baseline compatibility defaults
