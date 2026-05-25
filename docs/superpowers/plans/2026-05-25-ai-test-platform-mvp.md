# AI Test Platform MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a runnable local AI test platform MVP that completes the required V1 workflow against the travelsystem Java project.

**Architecture:** Use a standard-library Python HTTP server with focused service modules and a static frontend. Store platform assets as versioned files under `AI_TEST_PLATFORM_HOME`, keeping the business source directory read-only.

**Tech Stack:** Python 3.11 stdlib, pytest, HTML/CSS/vanilla JavaScript, existing local `CLI-Anything/scriptgen`.

---

### Task 1: Regression Core Tests

**Files:**
- Create: `tests/test_execution_service.py`
- Create: `tests/test_mvp_flow.py`

- [x] **Step 1: Write failing tests**

Tests cover assertion operations, variable interpolation, stdout JSON parsing, the complete draft-confirm-snapshot-run workflow, and no-LLM execution markers.

- [ ] **Step 2: Implement minimal services**

Create `ai_test_platform/` modules that satisfy these tests.

- [ ] **Step 3: Run focused tests**

Run: `python3 -m pytest tests/test_execution_service.py tests/test_mvp_flow.py -q`

### Task 2: Web API And UI

**Files:**
- Create: `ai_test_platform/server.py`
- Create: `ai_test_platform/cli.py`
- Create: `ai_test_platform/web/index.html`
- Create: `ai_test_platform/web/styles.css`
- Create: `ai_test_platform/web/app.js`

- [ ] **Step 1: Expose API routes for every MVP action**

Routes mirror the PRD: agents, projects, skills, knowledge, cli, cases, snapshots, runs.

- [ ] **Step 2: Build the frontend workflow**

The UI provides project configuration, generation/confirmation panels, snapshot creation, run execution, and failed-step details.

- [ ] **Step 3: Smoke test via browser**

Start the server and verify the full flow in a browser.
