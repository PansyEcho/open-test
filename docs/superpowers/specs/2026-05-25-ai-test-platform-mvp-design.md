# AI Test Platform MVP Design

## Goal

Build a local Python web project that completes the V1 loop for a backend test platform: create a project, bind a source directory, select Codex or Claude Code, bind a Skill directory, generate and confirm knowledge/CLI/case drafts, create a snapshot, and run confirmed cases without invoking an LLM.

## Architecture

The MVP uses a dependency-free Python HTTP server plus a static browser UI. The backend is split into services for projects, agents, skills, knowledge, CLI generation, cases, snapshots, diffs, and regression execution. Persistent state is stored as JSON files under a platform data root, defaulting to `~/.ai-test-platform` and overridable with `AI_TEST_PLATFORM_HOME`.

Agent support follows the Open Design adapter idea: platform code detects local CLIs and records adapter commands for `codex-local` and `claude-code-local`, but generation services do not embed a model. In automated MVP mode they create deterministic drafts plus agent-run prompts/results so the loop is testable locally; an `execute_agent` flag can shell out to the selected local agent later.

## Data Flow

1. `ProjectService` creates `projects/{project_key}` outside the business source directory and records a git baseline.
2. `SkillService` validates and hashes arbitrary Skill directories.
3. `KnowledgeService`, `ScriptgenService`, and `CaseService` write drafts and diff proposals.
4. Confirmation copies drafts into `versions/kb`, `versions/cli`, and `versions/cases` and updates active pointers.
5. `SnapshotService` binds active KB, CLI, Case, code baseline, selected agent, and Skill hash.
6. `ExecutionService` resolves `tool://`, `skill://`, and relative script references, executes scripts, parses stdout JSON, runs assertions, and writes step logs/reports.

## MVP Boundaries

The UI is an operational app, not a marketing page. The CLI generator attempts to use the existing scriptgen package and also writes offline shim tools for reliable local regression. Regression execution never calls AgentService and records `llm_invocations: 0` in reports.
