## ADDED Requirements

### Requirement: Input contracts preserve enum and normalized schema consistency

The system SHALL treat source-proven enum fields as scalar leaves when deriving operation fields. Input field schemas SHALL equal their corresponding nodes in the final request schema after source-required rules are applied; nested DTOs and collections SHALL retain their supported shapes.

#### Scenario: Request contains an enum with internal fields
- **WHEN** createOrder declares channelEnum whose enum class has code and desc members
- **THEN** the request contract includes channelEnum as a scalar field without channelEnum.code or channelEnum.desc bindings
- **AND** source type evidence remains available and inconsistent paths remain blocked

#### Scenario: Collection items contain runtime-required arrays
- **WHEN** input knowledge removes runtime-derived required arrays from collection item schemas
- **THEN** the field schema and final request schema remain equal and only explicit source-required rules are applied

### Requirement: Previously blocked input contracts are re-evaluated

The system SHALL rebuild an existing BLOCKED input contract from its requested scan when preparing Case generation, while retaining valid current READY contracts and historical persisted artifacts.

#### Scenario: A program projection bug has been fixed
- **WHEN** the stored contract is BLOCKED but deterministic derivation now produces a valid contract
- **THEN** generation can prepare with the corrected in-memory contract without rewriting published knowledge or invoking QA

#### Scenario: The blocker still exists
- **WHEN** re-derivation still finds incomplete or conflicting evidence
- **THEN** generation remains blocked with a precise reason
