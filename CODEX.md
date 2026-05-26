# Codex Project Guide

## Project

This repository is the local MVP for an AI backend automation test platform. It is a Python web app with a static frontend. The platform manages local business-code projects, scans Java Facade and Job entrypoints into CLI tools, guides knowledge-base generation through local agents, generates main-flow cases, snapshots version bindings, and runs regression without LLM calls.

## Runtime

Start the app from the repo root:

```bash
python3 -m ai_test_platform.cli --host 127.0.0.1 --port 8787
```

Use an isolated data directory when testing:

```bash
AI_TEST_PLATFORM_HOME=/private/tmp/ai-test-platform-dev python3 -m ai_test_platform.cli --host 127.0.0.1 --port 8787
```

The UI is served at `http://127.0.0.1:8787`.

## Important Paths

- `ai_test_platform/services.py`: core platform orchestration, project config, CLI scan, knowledge catalog/chat, cases, snapshots, regression runs, and local-agent invocation.
- `ai_test_platform/server.py`: HTTP API and static file server.
- `ai_test_platform/web/index.html`: static HTML shell.
- `ai_test_platform/web/app.js`: frontend state, API calls, navigation, knowledge chat/editor behavior.
- `ai_test_platform/web/styles.css`: UI styling.
- `tests/`: backend and frontend-contract tests.
- `scripts/run_mvp_flow.py`: deterministic end-to-end MVP flow without LLM usage.

External local tools referenced by the product:

- CLI scanner/generator: `/Users/user/data/code/other/CLI-Anything/scriptgen`
- Open Design reference for local-agent style: `/Users/user/data/code/other/open-design`
- Example Java project: `/Users/user/data/code/tc/travelsystem.java.dsf.supplychain.booking.core`
- Knowledge builder skill example: `/Users/user/temp/self-skill/code-knowledge-builder-cl`
- Case builder skill example: `/Users/user/temp/self-skill/knowledge-case-builder-cl`

## Agent Integration

The app supports local `codex` and `claude` CLI profiles. Knowledge chat sends prompts through the local agent command when `execute_agent=true` or the frontend sends `force_agent=true`.

Codex invocation is intentionally based on an Open Design style local-agent substrate:

- command starts with `codex exec --json`
- prompt is passed through stdin, not as a shell argument
- allowed directories are added with `--add-dir`
- the working directory is the generated `agent-runs/<id>` directory
- stdout/stderr/prompt/result are persisted under the project workspace

If the local agent is unavailable or returns no agent message, the knowledge chat should show an explicit failure instead of silently generating fake content.

## Knowledge Catalog Rules

Knowledge nodes are seeded from the confirmed CLI version. Facade grouping must come from scan metadata:

- `TradeFacade -> createOrder【下单】`
- `TicketFacade -> issueTicket【出票】`

Do not group all Facade methods under a generic label such as `交易接口`. Existing confirmed CLI indexes may be stale, so `services.py` re-enriches `platform-tool-index.json` from `_meta/scan-manifest.json` at read time.

The knowledge page keeps chat and editable content visible together. Sending a chat message should keep the user in chat mode, update the selected knowledge draft, and leave confirmation/cancel controls available.

## Verification

Run focused tests while changing behavior:

```bash
python3 -m pytest tests/test_knowledge_catalog_flow.py -q
python3 -m pytest tests/test_frontend_contract.py tests/test_knowledge_frontend_contract.py -q
```

Run the full suite before finishing:

```bash
python3 -m pytest -q
```

Run deterministic MVP regression without LLM calls:

```bash
python3 scripts/run_mvp_flow.py --data-root /private/tmp/ai-test-platform-mvp
```

The regression flow intentionally includes a failing sample case so the report can display failed steps, command, stdout JSON, assertion diff, and bound snapshot versions.
