# Change: Evaluate a Jev refund workflow behind one Codex tool call

## Why
The first experiment measured a fast Jev decision, but did not include the outer Codex tool-selection and final-response turns. The user now wants a practical path from the historical 162.4-second cancellation toward ten seconds, without another low-effort arm.

## What Changes
- Add an isolated benchmark that compares gpt-5.6-sol/xhigh using atomic OpenTest tools with the same model using one Jev-backed cancellation workflow tool.
- Reuse the established Jev rubric, current registered operation contracts, real QA execution service and request-ID deduplication.
- Measure complete CLI interaction, tool execution, Jev decision, business calls and remaining outer-agent time separately; include a direct invocation of the same workflow when needed to establish the ten-second path.
- Prepare distinct real targets dynamically, verify cancellations independently and report failures and ten-second completion counts.

## Impact
Experiment scripts and focused tests only. The existing page, installed plugin, global model settings and production business code are not changed. Historical timings remain reference data rather than a matched baseline.
