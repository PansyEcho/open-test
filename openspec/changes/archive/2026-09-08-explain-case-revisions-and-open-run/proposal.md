# Explain Case revisions and expose the actual Codex run

## Why
Task `task-06ac01cad3c72cfe` briefly displayed a raw MySQL evidence issue while its Agent was still revising, then published nine variants successfully. The console offered no Codex chat link because diagnostics recognized only legacy knowledge run fields.

## What Changes
- Distinguish automatic draft revision from a stopped workflow in the task dialog.
- Read diagnostics for the task-bound web run and expose its real Codex session as a viewing link for knowledge and Case tasks.
- Keep answers and continuation in the web workflow; opening a link never starts or resumes an Agent.

## Impact
Existing diagnostics endpoint, task dialog, asset version and focused regression tests. No task migration or QA calls.
