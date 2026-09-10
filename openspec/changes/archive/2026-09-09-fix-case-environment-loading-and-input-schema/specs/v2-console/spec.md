## ADDED Requirements

### Requirement: Case entry selector supports local filtering

The console SHALL provide a searchable single-selection entry combobox matching display names, canonical paths and entry types without case sensitivity. Search text SHALL remain separate from committed selection; only confirmation changes the entry, versions and generation target.

#### Scenario: Search and confirm an entry
- **WHEN** a user types part of an entry name or path
- **THEN** matching current and historical entries are shown, with all entries for empty search and a clear empty-result message
- **AND** mouse or arrow keys and Enter can confirm a result; Escape or blur cancels search and restores the committed label

#### Scenario: Refresh or switch the system
- **WHEN** the current system directory refreshes or another system is selected
- **THEN** refresh preserves a valid committed entry and a system change clears search and selection
- **AND** stale responses cannot restore another system's entries

### Requirement: Environment selection loads before slow workspace catalogs

The console SHALL load configured environments as soon as the system is selected, before waiting for local settings, scan history or other system catalogs. It SHALL distinguish loading, empty configuration and request failure.

#### Scenario: Scan history is slow
- **WHEN** scan history takes several seconds
- **THEN** environments are already selectable and environment rendering does not wait for history

#### Scenario: Environment read fails or system changes
- **WHEN** the environment request fails or belongs to an obsolete system
- **THEN** failure is visible without blocking other catalogs and obsolete responses do not update current selectors
