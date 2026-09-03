# case-workspace-truth-recovery Specification

## Purpose
TBD - created by archiving change case-workspace-truth-recovery. Update Purpose after archive.
## Requirements
### Requirement: Workspace entries come only from real knowledge targets

The Case workspace MUST derive Facade, Job and MQ entries from the latest scan and published knowledge catalog. Production code and browser assets MUST NOT add target-specific entries.

#### Scenario: Knowledge exists without V3 assets

- **WHEN** an entry has generated or confirmed knowledge but no V3 generation
- **THEN** the workspace shows the entry in its normal source directory
- **AND** reports the earliest missing pipeline stage without inventing a Case

#### Scenario: Source entry is absent

- **WHEN** a class or method is not a current scan Entry and has no published knowledge target
- **THEN** the workspace does not display it

### Requirement: Legacy and V3 assets remain readable together

The workspace MUST expose legacy read-only Case statistics and generation records alongside V3 Scenario, Variant and Attempt records, linked by canonical Entry identity and read-only aliases.

#### Scenario: Legacy Case is blocked

- **WHEN** a real knowledge entry has only blocked legacy Variants
- **THEN** the workspace shows the entry and its blocked counts
- **AND** does not classify those Variants as V3 PASSED evidence

### Requirement: Recovery is read-only

Refreshing the workspace MUST NOT publish capabilities, generate Cases, mutate scan or knowledge assets, or access QA.

#### Scenario: User refreshes the workspace

- **WHEN** the browser requests the workspace projection for a current registered system
- **THEN** the service reads the latest scan, knowledge and existing Case assets only
- **AND** no Published capability, V3 Generation, Attempt, scan or knowledge asset is written and QA is not accessed

