# Change: Evaluate Jev refund cancellation decisions

## Why
The observed Codex cancellation took 162.4 seconds with 19 MCP calls. A controlled experiment must distinguish model decision latency from business execution and CLI overhead before changing the application.

## What Changes
- Add a standalone, reproducible three-arm benchmark: Jev 1.13.0 and gpt-5.6-sol with xhigh/low reasoning.
- Freeze ten development and twenty held-out Chinese cases, with three held-out repetitions per arm.
- Validate three distinct QA cancellations per arm through existing OpenTest operations and verify actual final states.
- Produce local measurements and a redacted comparison report without changing product APIs, UI, MCP tools, global configuration or dependencies.

## Impact
- New capability: refund-model-benchmark.
- Standalone scripts and focused tests only; reuse existing environment, capability and execution contracts.
