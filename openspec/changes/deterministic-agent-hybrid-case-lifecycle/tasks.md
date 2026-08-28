# Tasks

## 1. Condition classification and Program Analysis V2

- [x] **Goal:** classify real input coverage separately from stateful setup, Oracle, fault, sequence, async, environment, relation and internal diagnostic evidence.
- [x] **Expected files:** `opentest/domain/models.py`, `opentest/application/program_case_analysis.py`, `opentest/application/case_rules.py`, `tests/v2/test_program_case_analysis.py`, `tests/v2/test_typed_case_compiler_phase5.py`.
- [x] **Domain changes:** add the nine-kind `CaseCondition` protocol, resolution ownership and Program Artifact V2; retain legacy semantic gaps only for read compatibility.
- [x] **Service/API changes:** only exact entry-field influence creates input obligations; semantic drafts may replace only an exact AI-owned condition with a compatible typed obligation; legacy add/no-additional actions cannot delete the program denominator, unsupported types remain blocked, and diagnostic evidence cannot block.
- [x] **Frontend changes:** none in this stage.
- [x] **Tests:** cover `AbstractFacade#createErrorResponse(...)`, bound branch/calculation influence, effect-to-Oracle projection, real Fault blockers, diagnostic denominator exclusion, exact typed replacement and fail-closed legacy/unsupported resolutions.
- [x] **Completion:** unbound error-response/downstream code no longer creates business partition blockers, while proven entry-field coverage remains mandatory.
- [x] **Dependency:** none.

## 2. Structured knowledge and existing Fact/Recipe extension

- [x] **Goal:** make stable entity prerequisites and products available as formal entry knowledge, while keeping AI proposals isolated until exact confirmation.
- [x] **Expected files:** `opentest/domain/models.py`, `opentest/adapters/knowledge_tracing.py`, `opentest/application/knowledge.py`, knowledge stores, `opentest/application/data_setup_recipes.py`, `opentest/adapters/data_setup_recipe_store.py`, knowledge and Recipe tests.
- [x] **Domain changes:** add `entry_fact_knowledge`, `entry_fact_candidates`, assertion-level source, state predicates, Recipe requirements, operation roles, selection priority, availability/extraction and typed relations.
- [x] **Service/API changes:** update knowledge prompts; auto-publish never promotes candidates; confirm exact assertion IDs only after latest-source, Fact, Action-schema and candidate-operation validation; bind semantic Boolean/result-code miss rules to the exact formal query assertion; validate unique CREATE identity and recursive Recipe inputs.
- [x] **Frontend changes:** keep the existing knowledge confirmation entry compatible; unified presentation is stage 4.
- [x] **Tests:** prove automatic publication isolation, selected-ID-only promotion, stale scan and invalid evidence/state rejection, same-generation formal-fact preservation, new-generation invalidation, rejection of cross-assertion query proof splicing, semantic miss proof and deterministic Recipe publication.
- [x] **Completion:** formal knowledge stores all six structured collections; AI candidates cannot enter a formal node; unknown contracts, dangling bindings, ambiguous selection and unsafe `FIRST_ITEM` are rejected without QA access.
- [x] **Dependency:** stage 1 condition protocol.

## 3. Knowledge-to-Generation compiler and explicit execution

- [x] **Goal:** compile formal prerequisites into a fixed recursive stateful DAG and execute only the frozen plan after explicit user action.
- [x] **Expected files:** `opentest/application/case_rules.py`, `opentest/application/typed_case_compiler.py`, `opentest/application/hybrid_case_generation.py`, `opentest/application/hybrid_case_handoffs.py`, `opentest/application/case_execution_v3.py`, `opentest/application/cleanup_plans.py`, compiler/generation/execution tests.
- [x] **Domain changes:** freeze stateful slots, dependency IDs, final `output_fact_name`, optional exact CREATE `created_fact_name`, Action bindings, create relations, acquisition policy, Cleanup `resource_scope` and a bounded `CONSUMED_BY_ACTION` proof.
- [x] **Service/API changes:** read exact formal entry knowledge; select a unique Producer recursively; detect cycles; freeze local-binding paths without reading their values during publication or Generation; block a user Attempt before RUNNING/OperationExecution when its requested environment lacks a frozen binding; run QTC only on formally proven explicit miss; allow a CREATE success-only response only when the final Query is anchored by a required Fact business identity and matching output relation; reject query-hit relations whose dependencies only exist on the create branch; classify Setup miss/failure separately; hold host-local query gates through Finalization; accept only unresolved external Fixture fields; reuse passed Action/Oracle evidence when a formal transition proves the root entity is consumed, without a second QA call.
- [x] **Frontend changes:** execution API contract stops requiring identities already resolved from Setup; UI relocation is stage 4.
- [x] **Tests:** prove hit skips a real dependency, miss recursively prepares it, provider failure never creates, CREATE-without-identity requires a dependency relation anchor and stores only the verified final Query entity for cleanup, cycles block, state/relation/Action binding validation, Setup miss semantics, in-process and cross-process contention, timeout/OSError release, `CREATE_ONLY` bypass and separate Action/Producer cleanup identities.
- [x] **Completion:** a formal stateful requirement compiles deterministically without QA; execution contains no runtime AI; Action uses the final verified Fact, a proven Action consumption never invokes the Action twice, and Producer Finalization uses either the exact CREATE Fact or the relation-verified final Query Fact according to the frozen Recipe contract.
- [x] **Dependency:** stages 1 and 2.

## 4. Business workspace projection and simple Case page

- [x] **Goal:** list every real latest entry and replace the internal pipeline console with Entry and Scenario business views.
- [x] **Expected files:** `opentest/domain/models.py`, `opentest/application/foundation.py`, `opentest/api.py`, `opentest/web/app.js`, `opentest/web/index.html`, `opentest/web/styles.css`, workspace and console tests.
- [x] **Domain changes:** expose four independent status axes, `UserFacingCaseStatus`, attempt summaries, directory summaries, Entry detail and Scenario detail DTOs.
- [x] **Service/API changes:** derive the directory directly from latest scan without per-entry preview; keep Entry detail limited to business summaries; load a six-section Scenario DTO on demand; keep raw Generation, Scenario and Attempt evidence only in Scenario `technical_details`.
- [x] **Frontend changes:** render the simple hierarchy, Entry summary and six-section Scenario view; move Fixture to advanced external input; fold technical IDs/codes/JSON; bump static asset versions and enforce stale-page protection.
- [x] **Tests:** verify no-knowledge entries, neutral no-Generation, blocked-before-executable priority, PASSED with no Finalization, scenario aggregation, hidden technical values and static version contracts.
- [x] **Completion:** refreshed HTTP serves the new version; main views contain business language only; blocked, failed, passed and finalization results remain distinct and technical evidence is still available on demand.
- [x] **Dependency:** stage 3 stable Generation and Attempt projection.

## 5. Refund knowledge regeneration, compatibility and final verification

- [ ] **Goal:** regenerate current refund analysis/knowledge through the real registered workflow and verify truthful executable assets or exact blockers.
- [ ] **Expected files:** current refund knowledge assets, this Change, and only task defects found by verification.
- [ ] **Domain changes:** no new architecture; verify legacy Program/Recipe/Generation reads and new immutable writes.
- [ ] **Service/API changes:** prove formal refund assertions reach `CaseRulePreview.conditions` and a new Generation; do not create a second confirmation route through Case handoff.
- [ ] **Frontend changes:** only fix task-scoped HTTP findings; every behavior change continues to bump the static version.
- [ ] **Tests:** add a non-skippable real-asset acceptance for `RefundFacade#cancel` that copies the repository knowledge into an isolated root, fails on any QA or Codex call, generates twice, and requires the same deterministic business result. Until a complete formal Recipe exists, the accepted intermediate result is one `BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED` with zero Scenario/Variant/Attempt; once the Recipe is published, the same test must advance to deterministic Scenario/Variant content. Then run focused suites, `tests/v2`, strict OpenSpec validation and refreshed HTTP checks for directory, Entry, Scenario, business blocker, progress and technical details.
- [ ] **Completion:** regenerate `RefundFacade#cancel` and `RefundFacade#createOrder`; confirm `cancel.requires RefundOrder(CANCELLABLE)` and `createOrder.produces RefundOrder(PENDING_APPLY)` only from real evidence; keep `TicketOrder(ISSUED)` absent from formal knowledge unless proven by current Booking source or exact user confirmation. Current acceptance must prove generation terminates without QA or unconditional Codex and exposes the single truthful Recipe blocker. Final completion still requires cancel Generation `READY`, Scenario count > 0, Variant count > 0, blocker count = 0, Attempt/OperationExecution/QA/Codex counts = 0; preserve historical blocked Generations, manual Cases and Runs; stop only task-started services and recheck 8788.
- [ ] **Dependency:** stages 1 through 4.

Current blocker (2026-08-28): page version `20260828-02` now shows terminal generation progress and keeps the technical payload collapsed. Current-scan formal knowledge contains `cancel.requires RefundOrder(CANCELLABLE)`, the cancel request binding, `createOrder.produces RefundOrder(PENDING_APPLY)`, and the refund QUERY/CREATE candidate operations as `CODE_PROVEN` assertions. The current scan also has three real Published capabilities: cancel Action, createOrder CREATE and queryList QUERY. `CaseRulePreview.conditions` contains the formal cancel `STATEFUL_ENTITY_PRECONDITION`; `AbstractFacade#createErrorResponse(...)` remains non-blocking `INTERNAL_DIAGNOSTIC`.

The earliest executable-chain blocker is now the formal recursive Recipe boundary. Current Booking source and transport metadata do not prove that its query result carries `TicketOrder(ISSUED)`, so `createOrder.requires TicketOrder(ISSUED)` is not present in formal knowledge and no truthful `TicketOrder -> createOrder -> RefundOrder(CANCELLABLE)` Recipe can be published. Generation `hybrid-generation-07e0f94029804c6da214` therefore terminates as `BLOCKED` with exactly one `BLOCKED_STATEFUL_ENTITY_PRODUCER_REQUIRED`, zero Scenarios, zero Variants and zero Attempts. The real-asset acceptance generates twice with the same business projection and fails on any QA or Codex call. Keep this stage unchecked until current Booking evidence or exact user confirmation supports the missing state contract and a complete Published Recipe compiles the frozen Setup chain. No QA access, Fixture business identity, fake provider or fabricated PASSED result was used.
