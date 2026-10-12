# Fix onboarding review findings

## Why
An independent review of the `simplify-java-system-onboarding` commits reproduced four defects:
- A web Agent run whose RUNNING record fails to save keeps the process-wide long-task gate, so every later long task is rejected until restart.
- Re-running metadata migration on a scan saved before a model field with a default value existed (`static_field_names`) reports a false identity conflict.
- An unqualified `fireEvent(...)` inside a type that inherits `SOFContext` is silently dropped when full symbol resolution fails.
- Importing `opentest.api` during test collection builds the module-level app against the workspace's real shared metadata MySQL.

## What Changes
- Release the global gate when the web run launch fails after the gate is reserved but before RUNNING is committed.
- Compare a replayed scan with the stored one after validating both through the current `ScanManifest` model.
- Resolve unqualified `fireEvent` by the enclosing type and its ancestors; record a dispatch gap when they cannot be resolved.
- Redirect the test session's knowledge root and metadata loader before collection to a per-session temporary database.

## Impact
`web_generation.py`, `source_analysis.py` (artifact store), the Java semantic analyzer and `tests/conftest.py`. No new tables, fields or runtime mechanisms.
