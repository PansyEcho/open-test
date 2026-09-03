# Codex Project Guide

## Project

OpenTest is a local FastAPI application for DSF system configuration, source scanning, knowledge publishing, Operation execution, and regression Case generation/execution. The only product package is `opentest`; the console is served from `opentest/web` and all current transport routes use `/api/v2`.

## Runtime

```bash
python3 -m pip install -e '.[dev]'
uvicorn opentest.api:app --host 127.0.0.1 --port 8788
```

Open `http://127.0.0.1:8788/console`.

## Current Case Contract

- Generation analyzes, compiles, validates, and persists immutable Variants without accessing QA.
- Execution requires a second explicit page or Skill action and runs every runnable Variant in the selected Generation.
- Variant order is frozen in the Generation. Each runnable Variant executes `DATA → TARGET → ORACLE → CLEANUP`.
- Write Variants without structured Cleanup remain visible but are `BLOCKED`; the executor must not call their target.
- Each explicit run has an independent `execution_id` and report.
- UI and Skills do not expose implementation-version labels.

## Codex Plugin and Skills

The OpenTest plugin must be installed and enabled before knowledge or Case tasks are created. A failed Codex configuration load is reported as `CODEX_CONFIG_INVALID`; an empty valid plugin list is `PLUGIN_NOT_INSTALLED`; an installed disabled plugin is `PLUGIN_DISABLED`.

The system Skill is `$open-test-ifightchainsaas-java-refund-core`. Case tools are `generate_interface_cases`, `get_case_generation`, `execute_case_generation`, and `get_case_execution`. A generation request never implies execution.

## Verification

```bash
python3 -m pytest -q
openspec validate correct-versioned-scan-and-console-contract --strict --no-interactive
openspec validate --specs --strict --no-interactive
```

After browser changes, validate through the running HTTP service using a newly opened or hard-refreshed page. Stop every development service before handoff and confirm port 8788 is not listening.
