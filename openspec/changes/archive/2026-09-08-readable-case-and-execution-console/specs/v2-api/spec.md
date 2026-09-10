## ADDED Requirements

### Requirement: Execution read responses preserve recorded value presence

Execution list and detail GET responses SHALL distinguish an absent persisted field from an explicitly recorded null, empty object, empty array, empty string, zero or false. This read-only serialization SHALL NOT change execution writes, stored records or unrelated API null rules.

#### Scenario: Historical operation omits actual values

- **WHEN** the persisted operation or assertion does not contain an actual-value field
- **THEN** the corresponding GET response omits that field instead of manufacturing a default value
- **AND** explicitly present empty values, zero and false remain present and unchanged

#### Scenario: Historical defaults cannot be distinguished

- **WHEN** stored defaults and actual observations cannot be distinguished by available evidence
- **THEN** presentation states that the distinction is unavailable rather than reconstructing an observation
