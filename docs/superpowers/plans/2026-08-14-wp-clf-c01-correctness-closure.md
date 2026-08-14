# WP-CLF-C01 Correctness Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four canonical long-form correctness gaps on the exact `ac7719e119966f6fab490622d7558f770200593e` main baseline and qualify one final exact SHA.

**Architecture:** Keep Story Design Authority, Hierarchical Planning, Book Authority, Narrative State, Command Kernel, and the Production Execution Gateway as the only authorities and execution plane. Semantic evaluation becomes a provider-backed ExternalEffect inside the existing independent evaluation Durable Job; the other fixes are deterministic contract and projection changes over immutable Authority AssetVersions.

**Tech Stack:** Python 3.11+, PostgreSQL 16/pgvector, psycopg 3, FastAPI, pytest, Docker Compose, Next.js 16, TypeScript.

## Global Constraints

- Do not create a second Evaluation Authority, Workflow Engine, Provider Plane, Arc state, realization service, debt service, or policy runtime.
- Production and controlled environments fail closed without a real provider route, frozen policy, exact lineage, current evidence, and trusted evaluator principal.
- Provider I/O remains outside business transactions and is governed by ExternalEffect, budget, Attempt/Lease/Fence, timeout, cancellation, replay, and reconciliation semantics.
- Every accepted output binds project, workspace, book, operation, attempt, actor, AssetVersion, content hash, policy/profile version and hash, trace, and provider/cost evidence where applicable.
- `SCRIPTED_FIXTURE` remains available only when `RuntimeEnvironment.fixture_allowed` is true and is never a production fallback.
- Add one forward-only migration after `20260814_0091_canonical_longform_runtime_completion`; do not edit historical migrations.

---

### Task 1: Provider-backed Narrative Semantic Evaluation

**Files:**
- Modify: `src/novel_forge/modules/story_design_authority/evaluation_runtime.py`
- Create: `src/novel_forge/modules/story_design_authority/evaluation_execution.py`
- Modify: `src/novel_forge/modules/book_design_authority/application.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/application.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/api/routers/book_design_authority.py`
- Test: `tests/unit/test_progressive_narrative_qualification.py`
- Test: `tests/integration/test_authority_book_design_postgres.py`

**Interfaces:**
- Consumes: `AuthorityHandlerRequest`, `ProductionExecutionGatewayExternalEffectAdapter`, frozen evaluator route, exact candidate AssetVersion, `required_qualification_profiles()`.
- Produces: `NarrativeSemanticEvaluationApplication.evaluate_candidate(...)` that performs provider execution without caller-authored evaluation JSON and returns `NarrativeSemanticEvaluationResult` bound to the provider ModelCallLog.

- [ ] Write a failing public-boundary test proving a model-provider command accepts candidate lineage but no evaluation payload/evidence IDs and invokes the shared PEP.
- [ ] Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_progressive_narrative_qualification.py` and retain the expected contract failure.
- [ ] Implement an evaluator execution port that freezes profiles/schema/prompt/route/input manifest, plans one idempotent `model.invoke` ExternalEffect, settles budget, persists ModelCallLog/CostLedger, validates the returned evaluation, and reuses a succeeded effect during takeover.
- [ ] Change the evaluation handler to call the port for `MODEL_PROVIDER`, forbid production fixture execution, and bind the returned exact ModelCallLog to the qualification output.
- [ ] Change BookDesign and StoryPlanning entry points to construct evaluation intent rather than accept caller-authored evaluation JSON; retain an explicitly named fixture-only test path.
- [ ] Run the unit test and PostgreSQL evaluation integration tests until failure, retry, replay, stale candidate, wrong actor/evidence, and qualification dedupe are green.

### Task 2: Global Arc Portfolio and Cursor Projection

**Files:**
- Modify: `src/novel_forge/modules/book_authority/input_resolver.py`
- Modify: `src/novel_forge/modules/book_authority/queries.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/application.py`
- Test: `tests/unit/test_book_production_authority.py`
- Test: `tests/integration/test_hierarchical_planning_postgres.py`
- Test: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`

**Interfaces:**
- Consumes: all CURRENT qualified ArcPlan bindings and the selected current VolumePlan.
- Produces: immutable `arc_portfolio_plan_versions` plus `current_relevant_arc_plan_versions`; scheduling/chapter planning receives only the latter while qualification and relations retain the former.

- [ ] Write a failing 5-Volume/3-Arc PostgreSQL test with scopes V1-V3, V2-V4, and V4-V5 and cursor assertions in V1, V2, V4, and V5.
- [ ] Validate every Arc scope only against the global Volume portfolio, including non-empty scope, unique members, segment containment, and relation endpoints in the portfolio.
- [ ] Project current relevant Arcs by current Volume membership without changing their canonical CURRENT freshness.
- [ ] Enforce scheduling and ChapterPlan Arc references as subsets of the frozen current relevant set.
- [ ] Verify replan invalidation changes the portfolio and projection hashes and never returns a stale current projection.

### Task 3: Per-entity Progressive Realization

**Files:**
- Modify: `src/novel_forge/modules/hierarchical_planning/domain.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/execution.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/domain.py`
- Test: `tests/unit/test_story_planning_runtime.py`
- Test: `tests/integration/test_hierarchical_planning_postgres.py`

**Interfaces:**
- Consumes: a plan horizon plus typed immutable Authority references for world and character dimensions.
- Produces: entity-specific `realization_level` values constrained by the horizon and exact reference records containing project/book scope, asset identity/type, version/hash, freshness, and frozen upstream lineage.

- [ ] Write a failing test for one plan containing ACTIVE protagonist/city, DETAILED faction, DEFINED next-volume actor, and ANCHOR distant empire.
- [ ] Replace equality to the plan-level realization with per-entity membership in `HORIZON_REALIZATION_LEVELS[planning_horizon]` and require at least the plan contract's minimum execution precision only for entities used by operational transitions.
- [ ] Validate every important realization reference as a typed object with `asset_version_id`, `asset_type`, `content_hash`, `project_id`, `book_id`, `freshness`, and `frozen_by_operation_id`.
- [ ] Preserve entity identity across elaboration and require monotonic ANCHOR→DEFINED→DETAILED→ACTIVE supersession/requalification instead of plan copying.
- [ ] Run unit and PostgreSQL planning tests for mixed precision, stale/wrong-scope refs, supersession, and requalification.

### Task 4: Authoritative Narrative Load Policy and Exact Debt Actions

**Files:**
- Modify: `src/novel_forge/modules/narrative_state/measurements.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/domain.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/application.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/execution.py`
- Modify: `src/novel_forge/modules/book_authority/input_resolver.py`
- Test: `tests/unit/test_story_planning_runtime.py`
- Test: `tests/unit/test_narrative_runtime_convergence.py`
- Test: `tests/integration/test_narrative_runtime_convergence_postgres.py`

**Interfaces:**
- Consumes: frozen production/serialization policy AssetVersion and accepted NarrativeLoadProjection.
- Produces: `NarrativeLoadPolicyRef` with exact version/hash/scope and deterministic limits for active/dormant arcs, open/overdue obligations, payoff congestion, character gap, new concepts, and state transitions.

- [ ] Write failing tests proving a Candidate cannot raise inherited limits and unrelated `PAYOFF Y` cannot clear overdue obligation X.
- [ ] Freeze the policy AssetVersion in Book Production input and propagate the same policy ref/hash through Planning, Replan, Context, and Chapter generation.
- [ ] Reject missing, stale, wrong-scope, or mismatched candidate policy values and enforce overload fail-closed.
- [ ] Require each overdue obligation identity to have `PAYOFF`, `RESOLVE`, `RESCHEDULE`, or an immutable governed override targeted to that exact identity.
- [ ] Verify replan retains policy lineage unless an independently governed scoped override supersedes it.

### Task 5: Forward Migration and Exact-SHA Qualification

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260814_0092_canonical_longform_correctness_closure.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Modify: `architecture/manifests/test-manifest.yaml`
- Test: `tests/unit/test_canonical_longform_correctness_closure_migration.py`
- Test: `tests/integration/test_authority_migrations_postgres.py`

**Interfaces:**
- Consumes: migration head 0091 and existing Authority tables/views.
- Produces: head 0092 constraints/indexes/views/columns for evaluation provider evidence, Arc portfolio/current projection, realization lineage, and frozen narrative-load policy.

- [ ] Write the migration contract test first and observe head/manifest failure.
- [ ] Add the forward-only migration, registry entry, manifests, constraints, indexes, and queryable projections without altering migrations 0001-0091.
- [ ] Prove fresh database→0092, 0091→0092, manifest consistency, restart readability, and schema/FK/index/view identities.
- [ ] Run `make validate`, `make authority-test`, `make authority-postgres-test`, `make authority-query-plan-release`, `npm --prefix web/admin run lint`, `npm --prefix web/admin test`, `npm --prefix web/admin run build`, `make authority-compose-config-check`, and `git diff --check`.
- [ ] Review `git diff ac7719e119966f6fab490622d7558f770200593e...HEAD` against repository standards and this plan, fix findings, commit, freeze final SHA, rerun all qualification commands on that SHA, push, and open a Draft PR to `main`.
