# Agentic Knowledge Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert knowledge generation from single-turn auto-write into multi-turn local-agent interviewing, with user-confirmed document write.

**Architecture:** The backend keeps chat sessions as the source of truth and treats agent replies as conversation output plus an optional draft document. A bundled SKILL.md defines interviewing behavior for project background, Facade, Job, public, and custom knowledge nodes. The frontend keeps chat open, mirrors the latest draft on the right, and writes to the knowledge base only when the user confirms.

**Tech Stack:** Python standard-library backend, static HTML/CSS/JS frontend, local Codex/Claude CLI invocation.

---

### Task 1: Built-In Interactive Knowledge Skill

**Files:**
- Create: `ai_test_platform/default_skills/interactive-knowledge-builder/SKILL.md`
- Modify: `ai_test_platform/services.py`
- Test: `tests/test_knowledge_catalog_flow.py`

- [ ] Add a bundled skill that instructs the agent to interview first, ask adaptive questions, scan only when useful, and mark final documents with `<<<KNOWLEDGE_DOCUMENT>>>`.
- [ ] Add tests that project creation can resolve this skill and that prompts include its body.
- [ ] Implement helper methods to read the configured skill, falling back to the bundled skill.

### Task 2: Multi-Turn Chat Contract

**Files:**
- Modify: `ai_test_platform/services.py`
- Test: `tests/test_knowledge_catalog_flow.py`

- [ ] Add failing tests showing `send_knowledge_chat()` appends the agent reply but does not write node content by default.
- [ ] Add tests showing a final document marker is saved as `session["draft_content"]`, not committed to node files.
- [ ] Add tests for `confirm_knowledge_chat()` writing the draft into the selected node and updating the catalog status.

### Task 3: Context-Aware Prompt Composition

**Files:**
- Modify: `ai_test_platform/services.py`
- Test: `tests/test_knowledge_catalog_flow.py`

- [ ] Add tests for project background, Facade, Job, and custom node prompt sections.
- [ ] Include node metadata, active CLI index summary, existing project background, dependencies, and previous messages.
- [ ] Keep local-agent invocation style from Open Design: prompt via stdin, `--add-dir` for source/workspace/skill directories.

### Task 4: Frontend Chat UX

**Files:**
- Modify: `ai_test_platform/web/app.js`
- Modify: `ai_test_platform/web/index.html`
- Modify: `ai_test_platform/web/styles.css`
- Test: `tests/test_frontend_contract.py`
- Test: `tests/test_knowledge_frontend_contract.py`

- [ ] Update send behavior so chat remains open and does not auto-switch to preview.
- [ ] Render assistant model label as local agent chat, show latest draft on the right, and make “确认写入” call the confirm endpoint.
- [ ] Keep manual editing and cancel behavior intact.

### Task 5: Verification

**Files:**
- Modify as needed based on failures.

- [ ] Run focused tests for knowledge chat and frontend contracts.
- [ ] Run full `python3 -m pytest -q`.
- [ ] Restart local server, perform browser flow, and capture screenshots proving multi-turn chat and correct Facade tree.
