# generation-knowledge-workflow Specification

## Purpose
TBD - created by archiving change fix-generation-and-knowledge-workflow. Update Purpose after archive.
## Requirements
### Requirement: Nullable compilation errors remain recoverable
The system SHALL accept valid JSON Schema type arrays and SHALL report incompatible types as located validation issues. Internal compilation failures with saved unpublished drafts SHALL be recoverable in the same handoff while preserving frozen source, receipts and revision checks.

#### Scenario: Resume the failed cancel draft
- **WHEN** a draft containing a nullable string comparison fails internally
- **THEN** continuing restores revision capability and normal validation can publish the corrected draft without any QA execution
- **AND** old request receipts remain idempotent and stale revisions remain rejected

### Requirement: Independent operation contracts describe business fields
The system SHALL expose target-level operation contracts without requiring legacy knowledge nodes. Supplements SHALL accept purpose, input or response descriptions independently, with source evidence and existing input-only request compatibility. MQ SHALL expose consumer message fields, and Facade responses SHALL distinguish business payload from execution envelopes.

#### Scenario: Update a contract without old knowledge
- **WHEN** a user opens an entry with no legacy node or updates only its purpose or response fields
- **THEN** the page displays the independent contract and its actual scan and task status, and offers generation or update
- **AND** internal implementation narratives and state-machine knowledge do not appear in the main knowledge directory

#### Scenario: Contract supplement belongs to a previous source scan
- **WHEN** the selected scan has no current supplement but an earlier scan contains one for the same operation
- **THEN** the entry is stale and offers an update using the selected source contract
- **AND** a current READY supplement with the matching source commit clears that stale status independently of historical narratives

### Requirement: Downstream discovery does not require provider registration
The system SHALL register interfaces used or actively declared by the caller during project scanning, including dependency JAR configuration and client wrappers. Case and natural-language tasks SHALL reuse one operation catalog and resolve additional dependency interfaces on demand. A provider need not be registered when caller-owned configuration proves a non-production execution route. Discovery alone SHALL NOT fabricate a callable route or business contract.

#### Scenario: Inspect an unregistered provider
- **WHEN** a caller uses several methods in one unregistered downstream system
- **THEN** the system appears once with referenced interfaces, contracts, wrapper mappings and source evidence
- **AND** a proven route can execute with the caller's configured non-production client

#### Scenario: Browse external interfaces in a historical scan
- **WHEN** the user selects a historical scan
- **THEN** the external interface tree uses that immutable scan and its fixed dependency definitions
- **AND** later registrations cannot replace contracts frozen in an existing Generation

#### Scenario: A Case needs another downstream method
- **WHEN** existing registered interfaces do not satisfy the data requirement
- **THEN** the Agent searches multiple keywords or exact methods and resolves a selected dependency operation
- **AND** validated operation definitions become reusable by subsequent tasks without rewriting older artifacts
- **AND** a partial keyword match still searches for unmet keywords and pagination includes deduplicated results

#### Scenario: Different downstream services use different versions
- **WHEN** the selected method belongs to a uniquely identified service and version
- **THEN** resolution uses that service version even when other services in the same downstream group use different versions

### Requirement: Code enums remain read-only code facts
The system SHALL classify semantically proven enums independently of entry usage, normalize historical matching candidates using existing scan facts and retain manual notes and ignore choices. Enum names and values SHALL NOT require human completion.

#### Scenario: Historical enum was classified as a term
- **WHEN** the current scan proves an enum stored as a stale business term
- **THEN** it appears as a read-only enum with constants and available source descriptions, retaining historical notes

### Requirement: Native continuation has one executor
The system SHALL start one web Agent automatically and SHALL allow native continuation only after that worker has stopped. A successful task-scoped transfer SHALL preserve task, handoff, revision and session before returning the Codex link; native answers SHALL NOT restart the web Runner.

#### Scenario: Answer in the original Codex conversation
- **WHEN** the web Agent saves a question and exits, and the user selects native continuation
- **THEN** the transfer succeeds before the original session opens, and the user's direct answer continues the same task
- **AND** duplicate transfer requests do not create another executor or conversation

#### Scenario: Background analysis remains active
- **WHEN** native continuation is requested while the web worker is active
- **THEN** the server rejects the transfer and the page keeps showing the authoritative web progress

### Requirement: Dependency configuration and wrappers contribute scan registrations
The scanner SHALL use the resolved Maven classpath and trace used client methods through active Spring XML imports, component scans, Import/ImportResource and Boot auto-configuration metadata. It SHALL read source or binary metadata without starting the business application, distinguish inactive or unresolved conditions, and retain call-site, dependency, configuration and remote-boundary evidence.

#### Scenario: CRM repository is wired by an imported JAR resource
- **WHEN** refund code calls SupplierRepository.findSupplierBySupplierId and imports supplier-client-info.xml from its CRM dependency
- **THEN** the scan registers the wrapper and its proven downstream operation with typed contracts and an inspectable mapping

#### Scenario: Auto configuration or transitive dependency introduces a client
- **WHEN** an active auto-configuration or imported configuration wires a used client from a resolved transitive dependency
- **THEN** the client is discovered even when no project-local RPC XML declares it
- **AND** unactivated configurations and unrelated library methods are not registered as executable operations

#### Scenario: Only binary dependency metadata is available
- **WHEN** the dependency has no sources JAR
- **THEN** class signatures, annotations and necessary bytecode establish supported mappings
- **AND** genuinely unresolved route or conditional configuration is visible as a precise gap instead of silently omitted

#### Scenario: An inactive configuration contains downstream clients
- **WHEN** a declared startup root does not reach a source configuration, or an XML profile or supported class/property condition is inactive
- **THEN** its interfaces are excluded from registration
- **AND** unsupported dynamic conditions and overloaded routes remain explicit resolution gaps
- **AND** shorthand property conditions, project-local class conditions and Boot annotation exclusions participate in the same activation decision

#### Scenario: An explicit bean implements an injected repository
- **WHEN** XML or Import activates a binary implementation of the interface used at a project call site
- **THEN** the scanner records the interface-to-implementation mapping and follows the implementation to its actual boundary
- **AND** Boot annotations without an explicit scan package retain default package scanning even when other annotation parameters are present

#### Scenario: A registered provider has a complete frozen contract
- **WHEN** an additional method is published in the task's fixed provider scan with an independent input/output contract
- **THEN** resolution uses that contract and route without requiring another local dependency JAR
- **AND** subsequent tasks reuse the registered definition while earlier scans and embedded definitions remain unchanged

