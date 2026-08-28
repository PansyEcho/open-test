# Design

## Current root cause and data flow

The V1 analyzer used an empty synthetic field when a reachable calculation or downstream call had no entry-parameter binding. The resulting `ProgramSemanticGap` became a mandatory AI item because semantic-draft validation required exact equality with every gap. Knowledge stored prose rather than typed prerequisites, so the compiler could not bridge a real entry to an existing Recipe. The workspace then called `preview()` per entry and rendered raw pipeline objects.

The new flow is:

```text
latest scan entry
-> ProgramCaseAnalysis/v2 conditions
-> exact formal Entry Fact knowledge
-> FrozenCoverageManifest
-> deterministic stateful Recipe resolver
-> immutable Generation
-> explicit QA Attempt
-> business-facing projection
```

## Condition protocol

`INPUT_COVERAGE` alone adds factors or decision/boundary combinations after an exact entry-field influence is proven. `STATEFUL_ENTITY_PRECONDITION` resolves Setup Facts. `ORACLE_REQUIREMENT` adds observations. `FAULT_TRIGGER_REQUIREMENT`, `SEQUENCE_REQUIREMENT`, `ASYNC_WAIT_CONDITION` and `ENVIRONMENT_CAPABILITY` affect readiness through existing capabilities. `DATA_RELATION_CONSTRAINT` validates related Facts. `INTERNAL_DIAGNOSTIC` retains evidence but never enters the denominator or blocks generation. Semantic AI resolves only conditions whose owner is `AI`. Each Resolution must name the exact Gap and Condition and replace it with a compatible typed obligation. Legacy `ADD_OBLIGATION` and `NO_ADDITIONAL_OBLIGATION` remain readable but cannot close V2 gaps; an unsupported condition produces an explicit blocker instead of deleting the program Requirement.

## Structured entry knowledge and trust

Formal entry knowledge contains `requires_facts`, `produces_facts`, `state_transitions`, `candidate_operations`, `binding_paths` and `evidence_refs`. Each assertion has a stable ID and one source: `CODE_PROVEN`, `KNOWLEDGE_CONFIRMED`, `USER_CONFIRMED` or `AI_CANDIDATE`. AI candidates live only in a draft candidate set. Confirmation promotes exact selected assertion IDs after re-reading source evidence, validating current Fact contracts, checking exact Published Action request schemas, validating latest candidate operations and checking relation types. A cross-system candidate operation freezes the provider system, latest scan, baseline and normalized evidence commit independently from the consumer knowledge baseline; provider source drift invalidates that operation proof. Whole-node confirmation never promotes sibling candidates.

When a Fact contract version changes, the same exact confirmation command may name the formal assertion IDs superseded by each selected candidate. The server accepts replacement only for the same requirement/product slot or the same binding slot and request path. `CODE_PROOF_REQUIRED` replacement reuses the current deterministic proof engine and publishes every selected assertion as `CODE_PROVEN`; if any proof is incomplete, the whole command fails and leaves both formal knowledge and candidates unchanged. User confirmation remains `USER_CONFIRMED`. This is a bounded assertion migration, not a node overwrite or a second publication system, and unrelated formal assertions and sibling candidates are preserved.

Formal facts are stable semantics, not workflows. Producer Recipe publication references exact formal assertion IDs. Producer requirements must equal the producer Entry's formal requirements; create/query steps and produced states must be formally proven. `produces_facts` never fabricates a response identity.

Automatic draft publication never promotes `entry_fact_candidates`. Direct knowledge regeneration preserves already-formal facts only when both source scan and baseline are exactly unchanged; a new source generation requires the assertions to be proven or confirmed again. Case-agent handoff consumes formal entry facts but does not become a second confirmation path for knowledge candidates.

## Stateful entity model

Existing `SetupFactContractDefinition` adds `state_path` and named predicates over real states. Existing Recipe assets add required Facts, produced state, output relations, `QUERY|CREATE|VERIFY|WAIT`, `QUERY_ONLY|CREATE_ONLY|QUERY_THEN_CREATE`, selection priority and explicit query availability/extraction.

Availability supports `COLLECTION_NOT_EMPTY`, `VALUE_NOT_NULL`, `BOOLEAN_EQUALS` and a disjoint `RESULT_CODE_MAP`. Collection/value presence is structural; Boolean and result-code meanings must be frozen on the exact formal `CANDIDATE_OPERATION` assertion and referenced by the Recipe step. A successful query with no such proof is a Setup protocol failure and can never enter CREATE. `FIRST_ITEM` requires maximum cardinality one or a stable unique ordering path. Query misses are distinct from provider failures and verification failures.

A conditional-create node freezes two identities when the CREATE response actually exposes the entity: `output_fact_name` is the final queried and state-verified Fact bound to the target Action, while `created_fact_name` is the unique same-contract Fact emitted by the exact CREATE step. The latter is used only for Producer Finalization and cannot make an unverified create response satisfy the Action precondition. A real CREATE operation may instead return only success metadata. In that bounded QTC form, `created_fact_name` stays empty, the final Query MUST bind a required dependency Fact's business identity, and the final target Fact MUST prove the matching relation back to that same dependency. Only the relation-verified final Query entity becomes the Producer Finalization identity; a failed or missing final Query remains failed/quarantined and cannot fabricate a cleanup success.

For refund, `RefundOrder.CANCELLABLE` maps to `PENDING_APPLY`, `WAIT_REFUND`, `AUDITED`, `REFUND_FAIL` and `RESHOPING`. `createOrder` proves `RefundOrder(PENDING_APPLY)`, which satisfies `CANCELLABLE`. `TicketOrder(ISSUED)` is formal only when proven by bound Booking knowledge or exact user confirmation.

## Recursive Recipe resolution

The resolver keys nodes by Fact contract, state predicate, policy, constraints and relations; it chooses the single lowest-priority exact producer and reports equal-priority ambiguity. An active recursion stack detects cycles deterministically.

`QUERY_THEN_CREATE` is a specialised conditional node, not a general workflow engine. Execution queries the target first. Only an explicit miss evaluates create-branch dependency nodes and then executes CREATE/WAIT/VERIFY/final QUERY. A hit, provider failure or timeout never evaluates create dependencies. Producer output relations are verified only on the create branch. A target-entry relation that depends on a create-only dependency is rejected during compilation because the query-hit branch cannot obtain that Fact. When CREATE has no entity output, publication additionally requires the dependency-identity/final-relation anchor above; this is a narrow protocol for real APIs such as createOrder, not a relaxation that accepts an arbitrary post-create Query.

## Four phase boundary

Knowledge generation reads registered source and produces typed candidates without QA. Capability publication freezes program-derived local-binding paths but does not require the current laptop to hold a non-empty Token. Case generation reads formal knowledge and Published assets, compiles a fixed DAG and writes an immutable Generation without reading local QA values, accessing QA or creating an Attempt. AI may submit typed drafts only for unresolved semantics or missing producers and cannot publish knowledge directly. Explicit execution first validates every frozen binding against the requested environment; a missing value produces a preflight-blocked Attempt before RUNNING or any OperationExecution. Only a successful preflight may query or create QA entities, verify state, bind Action inputs, execute Oracle and run frozen finalization.

Host-local query reuse is protected by sorted `threading` plus `fcntl.flock` gates keyed by environment, provider system and Fact contract. Locks span Query through Action and Finalization. They do not claim cross-host uniqueness; without a Published atomic claim capability, multi-host use requires `CREATE_ONLY`.

Cleanup uses the existing plan model with an explicit bounded resource scope. `ACTION_EFFECT` resolves an Action Fact or the root slot's final verified Setup Fact. When exact formal state-transition knowledge proves that the target Action moves the root entity outside its reusable predicate, and the current Action Oracle proves that transition or successful consumption, the bounded `CONSUMED_BY_ACTION` strategy reuses the same Attempt evidence instead of issuing a second business call. It is valid only after both Action and Oracle pass; an unproven result is blocked and isolated. `STATEFUL_PRODUCER` resolves the exact CREATE Fact captured for that stateful slot when the response exposes it; for the success-only CREATE protocol it resolves only the relation-verified final Query Fact after that Query succeeds. Finalization never infers an identity from a success code or dependency Fact, and never treats Action consumption and Producer cleanup as interchangeable.

## Status and user projection

The API exposes independent `generation_lifecycle`, `readiness_status`, `latest_execution_status` and `finalization_status`. No Generation is neutral `NOT_GENERATED`. Query miss is Setup `BLOCKED`, never an assertion failure. A shared `UserFacingCaseStatus` provides title, summary, missing items, impact, recommended actions, scope and folded technical data.

Display priority is failure, blocked/needs-input, verified pass, executable and then generated. A blocked latest Attempt is therefore visible even when formal assets remain executable for retry. `PASSED` execution with `NOT_APPLICABLE` Finalization is still shown as passed for read-only work, while the four raw axes remain unchanged. A same-entry, same-scan handoff projects `GENERATING` only after its persisted task records a started Agent turn or while the server validates a submitted draft. A merely waiting, manually required, blocked or failed handoff never impersonates active work. Each Scenario derives guidance only from its own blockers and latest Variant Attempts, so another Scenario cannot leak missing items or technical failures into it.

The generation progress projection uses four stable business steps: formal asset compilation, optional AI asset completion, deterministic validation and Scenario compilation. It reports a safe title, summary and update time without exposing raw blocker or asset identifiers. For a task with a persisted start receipt it also reads the existing Codex thread summary without starting a turn: a completed turn with no accepted asset becomes needs-input, and a failed turn becomes failed instead of remaining active forever. The browser polls only the two active phases and stops on waiting, needs-input, blocked, ready or failed states.

Case generation invokes Codex only when the frozen blocker is AI-owned and the program can prove a legal input surface. Semantic Resolution requires an exact typed program gap. Capability or Recipe work requires a current schema-complete Candidate or current Published capability from the consumer or an authorised provider. Missing scans, incomplete generic DTO schemas, unconfirmed knowledge facts and unavailable environment capabilities remain program-visible blockers; repeatedly calling Codex cannot substitute for those facts. A READY Generation returns directly without creating a Codex thread, and every generation path remains outside QA.

The directory reads all real latest-scan Facade, MQ and Job entries without calling `preview()`. Entry details contain only the Entry projection and persisted Scenario summaries. A separate Entry-plus-Scenario API returns overview, prerequisites, coverage, variants, assertions/finalization and recent results. Raw Generation, Scenario, Variant and Attempt objects remain available only inside folded `technical_details`.

## Compatibility and migration

V1 Program catalogs and V2 Recipes are parsed only into legacy summaries. New scans write Program V2; new Recipes write V3. Old Generations, Runs and manually maintained Cases remain immutable. Repeated generation from the same frozen facts, rules and Recipes preserves deterministic obligations and Variants.

After deployment, regenerate the refund source scan and knowledge for `RefundFacade#cancel` and `RefundFacade#createOrder`. Confirm `cancel.requires RefundOrder(CANCELLABLE)` and `createOrder.produces RefundOrder(PENDING_APPLY)`. Publish `createOrder.requires TicketOrder(ISSUED)` only with formal Booking evidence or exact user confirmation; otherwise retain the candidate and one friendly blocker.

## Why no broader framework

Only stable stateful business entities have a demonstrated consumer and execution failure model. Files, quotes, sessions, resource pools, graph traversal and a generic workflow runtime would add persistence and scheduling without a current requirement, so this change adds a bounded conditional stateful DAG to the existing Recipe architecture only.
