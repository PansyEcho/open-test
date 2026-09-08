# Restore usable knowledge, Case and QA workflows

## Why

Valid dynamic DSL references are serialized with an implicit `value: null` and then rejected on reload, making existing drafts unrecoverable. Web generation only prepares a waiting task without an executor. QA confirmation, mandatory cleanup and read-only DATA restrictions prevent the explicitly authorized test workflow.

## What Changes

- Preserve strict DSL round trips and narrowly read existing affected handoffs without discarding drafts or revisions.
- Run web-owned generation and clarification in the web console while native Skills retain their current conversation.
- Automatically prepare missing target knowledge before Case generation and return actionable validation issues.
- Default explicit test execution to configured QA; permit QA data preparation and DML, including DELETE, with optional cleanup.
- Refresh the shipped plugin and verify both real user entry points before completion.

## Impact

Changes affect task APIs, the existing local Agent runner, V4 draft storage/compiler/executor, console, system Skill generator and QA SQL worker. Existing tasks and immutable Generations remain recoverable. No new model service, database schema or deployment infrastructure is introduced.
