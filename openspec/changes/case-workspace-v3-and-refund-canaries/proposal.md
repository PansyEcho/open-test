# Change: Case Workspace V3 and Real Entry Pipeline

## Why

V3 generation owns Scenario templates, parameterized Variants and explicit blockers, but runtime Attempt truth and a generic real-entry pipeline are not yet complete. The browser must derive every target from the current scan and published knowledge instead of production target constants.

## What Changes

- Execute one V3 Variant through Published Setup, Fault, Action, Oracle and Cleanup stages and persist an independent `ExecutionAttempt`.
- Expose V3 generation, attempt and real-entry pipeline APIs without reintroducing matrix confirmation.
- Project lifecycle readiness only for current scan Entries with generated or confirmed knowledge.
- Replace the regression Case page's matrix presentation with Scenario / Variant / Attempt, rule-hit, blocker, step and evidence views.
- Bump the browser asset version and verify the changed page through the running HTTP service.

## Impact

- Affected specs: `case-workspace-v3-and-refund-canaries` (historical change ID retained)
- Affected code: V3 runtime models/store/service, application/API composition, console HTML/JS and contract tests
- Existing V2 Case read APIs remain compatible; retired V2 writes remain blocked.
