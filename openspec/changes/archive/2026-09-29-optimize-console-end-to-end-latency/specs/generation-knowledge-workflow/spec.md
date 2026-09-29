## MODIFIED Requirements

### Requirement: Code enums remain read-only code facts
The system SHALL classify semantically proven enums independently of entry usage, normalize historical matching candidates using existing scan facts during explicit upgrade or scan publication, and retain manual notes and ignore choices. Enum names and values SHALL NOT require human completion. Reading saved background SHALL NOT perform normalization, take a system write lock or write metadata.

#### Scenario: Historical enum was classified as a term
- **WHEN** the explicit idempotent upgrade or scan publication proves an enum stored as a stale business term
- **THEN** the saved context exposes a read-only enum with constants and available source descriptions, retaining historical notes
- **AND** subsequent GET requests only read this persisted result
