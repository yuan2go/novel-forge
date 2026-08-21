# Post-Merge Correctness Closure Implementation Plan

> **Status:** IMPLEMENTED; final proof level is recorded by the current tests
> and Draft PR, not by the original unchecked execution checklist below.
> **Implementation branch:** `codex/post-merge-correctness-closure`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 0094 upgrade gap, production Agent Harness composition, accepted Arc/Obligation semantics, and Memo-driven Context Retrieval without creating parallel authorities or provider runtimes.

**Architecture:** Migration 0095 registers durable repair work; live acceptance and repair share one pure canonical projector; all external model/embedding turns use the existing PEP ExternalEffect/Receipt path. Book Acceptance persists deterministic accepted projections and follow-up signals, while Chapter Context adds one immutable retrieval operation between Memo and Context Build.

**Tech Stack:** Python 3.11+, PostgreSQL/psycopg, FastAPI, pytest, existing Command Kernel, RuntimeJob, Book/Chapter Authority, Production Execution Gateway, Capability Runtime, PlanChange Authority, and Artifact lineage/invalidation tables.

## Global Constraints

- Keep migration 0094 byte-for-byte unchanged; add forward-only migration 0095.
- Rebuild and live acceptance use the same deterministic long-form projector.
- Planned or expected Arc contribution never becomes Actual without accepted evidence.
- Authoritative repair completion is independent from semantic retrieval readiness.
- Book active projection activation is one fenced terminal CAS after complete validation.
- Controlled Agent permissions come only from a server-resolved frozen policy.
- Agent and embedding provider calls use the existing PEP, ExternalEffect, Receipt, model-call log, and cost ledger.
- Book Acceptance performs no external call, ArcRevision generation, or PlanChange invocation.
- ChapterMemo queries drive a durable retrieval operation before Context Build.
- Lexical retrieval is named PostgreSQL Full-Text Search / FTS ranking.
- Do not run long campaigns, sustained multi-Book generation, load tests, or large provider qualifications.

---

### Task 1: Add 0095 Repair and Retrieval Projection Schema

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260821_0095_post_merge_correctness_repair.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Create: `tests/unit/test_post_merge_correctness_repair_migration.py`
- Modify: `tests/unit/test_agent_collaboration_migration.py`
- Modify: `tests/unit/test_capability_pack_authority_migration.py`
- Modify: `tests/unit/test_corrective_action_terminal_lineage_migration.py`
- Modify: `tests/unit/test_progressive_narrative_design_migration.py`
- Modify: `tests/unit/test_source_import_runtime_migration.py`
- Modify: `tests/unit/test_source_intelligence_router_migration.py`
- Modify: `tests/unit/test_postgres_migrations.py`
- Modify: `tests/integration/test_authority_migrations_postgres.py`

**Interfaces:**
- Produces repair registration/checkpoint tables, Arc follow-up outbox, retrieval-result metadata, and embedding projection status required by later tasks.
- Preserves existing 0094 schema and data.

- [ ] **Step 1: Write migration unit tests**

Assert `DOWN_REVISION` equals 0094, `FORWARD_ONLY` is true, repair discovery selects both null and stale pointers, the migration contains no long-form reducer SQL, and repair/semantic statuses are distinct.

- [ ] **Step 2: Run the migration tests and observe the missing module failure**

Run: `uv run --no-sync pytest -q tests/unit/test_post_merge_correctness_repair_migration.py`

Expected: import failure for the 0095 module.

- [ ] **Step 3: Implement the forward migration**

Create tables with these stable ownership keys:

```python
MIGRATION_ID = "20260821_0095_post_merge_correctness_repair"
DOWN_REVISION = "20260820_0094_industrial_autonomous_novel_os"
FORWARD_ONLY = True
```

`authority_book_projection_repair` is unique by `book_run_id` and stores source accepted chapter, target evidence digest, authoritative/semantic statuses, cursor, terminal digest, fence metadata, error, and timestamps. `authority_book_projection_repair_checkpoint` is unique by repair/chapter. Migration discovery inserts affected Books without constructing projection payloads.

- [ ] **Step 4: Update migration registration and historical head assertions**

Register 0095 last in `VERSION_MODULES`. Historical tests must assert their migration is in the chain rather than incorrectly remaining the latest head; only the new migration test asserts `LATEST_MIGRATION_ID` equals 0095.

- [ ] **Step 5: Add PostgreSQL fresh and pre-existing-0094 discovery tests**

Apply through 0094 manually, seed one accepted Book with null pointers, apply 0095, and assert one REGISTERED repair with no projection business rows written by migration SQL.

- [ ] **Step 6: Run targeted migration tests and commit**

Run: `uv run --no-sync pytest -q tests/unit/test_post_merge_correctness_repair_migration.py tests/unit/test_postgres_migrations.py`

Commit: `feat: register post-0094 correctness repair`

### Task 2: Extract the Shared Canonical Long-Form Projector

**Files:**
- Create: `src/novel_forge/modules/book_authority/longform_projection.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/modules/longform_narrative/reducers.py`
- Modify: `src/novel_forge/modules/narrative_state/reducers.py`
- Create: `tests/unit/test_canonical_longform_projector.py`
- Modify: `tests/unit/test_book_production_domain.py`

**Interfaces:**
- Produces `AcceptedLongformEvidence`, `LongformProjectionPayload`, and `project_accepted_longform(evidence)`.
- Consumed by live acceptance and Task 3 repair.

- [ ] **Step 1: Write projector equality and legacy evidence tests**

Test that the same accepted input produces the same payload/digest in live and rebuild modes. Test that missing historical Arc evidence yields `NOT_OBSERVED`/`UNKNOWN` with adaptation provenance and never uses planned expected contribution.

- [ ] **Step 2: Run tests and observe missing projector types**

Run: `uv run --no-sync pytest -q tests/unit/test_canonical_longform_projector.py`

- [ ] **Step 3: Implement pure evidence and projection contracts**

Use frozen dataclasses. Normalize all lists/maps before hashing. Include source asset IDs/hashes, contract adaptation, projector version, Arc plans, previous accepted projections, and accepted outcome evidence in the digest.

- [ ] **Step 4: Move existing live projection construction behind the projector**

`build_longform_projection_set()` becomes a compatibility wrapper or is replaced by `project_accepted_longform()`. Book Acceptance resolves authoritative inputs, calls the pure projector, and passes its payload to the existing repository transaction.

- [ ] **Step 5: Add missing-evidence invariants**

Reject any adapter that maps `expected_progress`, `expected_contribution`, or ChapterPlan milestones into observed Actual fields. Persist explicit adaptation evidence when older outcome contracts lack modern Arc/obligation fields.

- [ ] **Step 6: Run projector and live acceptance unit tests and commit**

Run: `uv run --no-sync pytest -q tests/unit/test_canonical_longform_projector.py tests/unit/test_book_production_domain.py tests/unit/test_longform_narrative_contracts.py tests/unit/test_narrative_state_semantics_v2.py`

Commit: `refactor: share canonical accepted projection reducer`

### Task 3: Implement Durable Projection Repair and Terminal CAS

**Files:**
- Create: `src/novel_forge/modules/book_authority/projection_repair.py`
- Modify: `src/novel_forge/modules/book_authority/composition.py`
- Modify: `src/novel_forge/modules/book_authority/governed_scheduler.py`
- Modify: `src/novel_forge/modules/runtime_job/application.py`
- Modify: `src/novel_forge/storage/book_authority_repositories.py`
- Modify: `src/novel_forge/cli/authority.py`
- Create: `tests/unit/test_book_projection_repair.py`
- Create: `tests/integration/test_book_projection_repair_postgres.py`

**Interfaces:**
- Produces `BookProjectionRepairAuthority.tick(repair_id, worker_id)` and a CLI repair/status command.
- Calls `project_accepted_longform()` from Task 2.

- [ ] **Step 1: Write deterministic repair unit tests**

Cover bounded chapter batches, matching-checkpoint skip, digest conflict, incomplete terminal state, idempotent rerun, and semantic readiness independent from authoritative completion.

- [ ] **Step 2: Write PostgreSQL upgrade fixtures for paths A and B**

Path A applies through 0093, seeds accepted chapters using historical tables, applies 0094 and 0095, repairs, and admits N+1. Path B begins with 0094 already recorded and the same null-pointer accepted Book, then applies 0095 and repairs.

- [ ] **Step 3: Implement repair evidence loading and checkpoint persistence**

Load committed acceptances in chapter order, resolve only accepted/frozen assets, call the shared projector, persist one chapter transaction, and checkpoint source/projection digests under the active attempt fence.

- [ ] **Step 4: Implement terminal validation and CAS**

Validate continuous `1..N`, exact source hashes, COMPLETE rows, matching acceptance pointers, and final chapter. Update `active_longform_projection_set_id` with expected Book version, accepted chapter, prior pointer, and repair fence in one conditional statement; zero updated rows means stale/conflict.

- [ ] **Step 5: Bind repair to existing RuntimeJob and scheduler**

Use a new job kind under the current runtime job registry, with Operation/Attempt/Lease/Fence and retry/dead-letter behavior. Do not create a separate polling framework.

- [ ] **Step 6: Add operator CLI and observability**

Expose discovery/status/run commands returning repair ID, cursor, authoritative status, semantic status, attempts, terminal digest, and recovery instruction.

- [ ] **Step 7: Run unit and PostgreSQL upgrade tests and commit**

Run unit tests first. When PostgreSQL is available, run both integration paths plus migration smoke.

Commit: `feat: rebuild accepted projections with durable repair`

### Task 4: Resolve Server-Side Agent Tool Policy and Fail-Closed Admission

**Files:**
- Create: `src/novel_forge/modules/agent_runtime/tool_policy.py`
- Modify: `src/novel_forge/modules/agent_runtime/contracts.py`
- Modify: `src/novel_forge/modules/agent_runtime/application.py`
- Modify: `src/novel_forge/modules/agent_runtime/definitions.py`
- Modify: `src/novel_forge/api/routers/agent_runtime.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Create: `tests/unit/test_agent_server_tool_policy.py`
- Modify: `tests/unit/test_agent_runtime_api_contract.py`

**Interfaces:**
- Produces `ServerAgentToolPolicyResolver.resolve(definition, role, capability_pack, skills, environment)` and `AgentHarnessReadiness`.
- Admission consumes the resolved immutable snapshot and validates an optional client digest for equality only.

- [ ] **Step 1: Write escalation and unbound admission tests**

Test client-added AUTHORITY_COMMAND rejection, Skill cannot grant permission, missing production model binding rejection before session/operation persistence, and exact requested-policy equality acceptance.

- [ ] **Step 2: Implement the policy resolver**

Intersect server Agent Definition, role, active Capability Pack deployment, server tool registry, Authority policy, and environment. Treat Skills only as instruction-version inputs. Hash and persist the normalized snapshot.

- [ ] **Step 3: Add readiness to admission composition**

Build readiness from the shared production execution composition and registered tool bindings. Controlled admission fails before creating a READY operation if route/provider/budget/tool bindings are invalid.

- [ ] **Step 4: Remove client policy authority**

Keep the API field only as a requested snapshot/digest compatibility check or replace it with intent; never pass it directly to Harness execution.

- [ ] **Step 5: Run policy/API tests and commit**

Commit: `fix: make agent tool policy server authoritative`

### Task 5: Bind Production Agent Turns and Three Tool Kinds to Existing Runtime

**Files:**
- Create: `src/novel_forge/modules/agent_runtime/production_model_turn.py`
- Modify: `src/novel_forge/modules/agent_runtime/harness_runtime.py`
- Modify: `src/novel_forge/modules/agent_runtime/scheduler.py`
- Modify: `src/novel_forge/modules/production_execution/gateway.py`
- Modify: `src/novel_forge/modules/production_execution/routing.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Create: `tests/unit/test_agent_production_composition.py`
- Modify: `tests/integration/test_agent_harness_scheduler_postgres.py`

**Interfaces:**
- Produces a PEP-backed `AgentModelTurnPort` and production handlers for READ_ONLY_QUERY, TYPED_CAPABILITY, and AUTHORITY_COMMAND.
- Uses existing ExternalEffect adapter and Receipt reconciliation.

- [ ] **Step 1: Write controlled composition and receipt recovery tests**

Use a counting PEP adapter: provider succeeds, crash before transcript materialization, new worker reconciles the same receipt, invocation count remains one. Also test stale fence, cancellation, turn/token/cost limits.

- [ ] **Step 2: Register the Agent Model Turn PEP route/binder**

Add an `agent` domain stage to existing routing and gateway composition. Stable effect identity includes session, operation, attempt generation, turn ordinal, transcript digest, and route snapshot.

- [ ] **Step 3: Implement production model-turn materialization**

Reserve budgets, plan/submit/reconcile ExternalEffect, validate the structured turn result, and return effect/receipt/model/cost evidence for transcript persistence. Never invoke a provider adapter directly.

- [ ] **Step 4: Bind production tools through applications**

`narrative.query_accepted` uses an accepted-boundary query service. The typed tool submits the existing Capability Runtime and returns immutable candidate/operation IDs. The Authority tool calls an Authority Application admission method and returns submitted command/operation ID. No handler receives repositories or SQL access.

- [ ] **Step 5: Make scheduler selection match admission readiness**

Remove the fixture-factory-only filter. Select production sessions only when their persisted binding snapshot matches the worker composition; otherwise fail/recover explicitly rather than remain READY.

- [ ] **Step 6: Run unit/integration tests and commit**

Commit: `feat: compose production agent harness through pep`

### Task 6: Implement Deterministic Obligation Lifecycle and Arc Inputs

**Files:**
- Modify: `src/novel_forge/modules/narrative_state/contracts.py`
- Modify: `src/novel_forge/modules/narrative_state/reducers.py`
- Modify: `src/novel_forge/modules/longform_narrative/contracts.py`
- Modify: `src/novel_forge/modules/longform_narrative/reducers.py`
- Modify: `src/novel_forge/modules/book_authority/longform_projection.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/domain.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/execution.py`
- Create: `tests/unit/test_accepted_obligation_and_arc_checkpoint.py`

**Interfaces:**
- Produces deterministic obligation evaluation and real `ArcCheckpointInput` derived from frozen ArcPlan plus accepted states.

- [ ] **Step 1: Write lifecycle and checkpoint tests**

Cover due, overdue, stale, fulfilled, violated, payoff evidence, dependency completed/blocked/unknown/abandoned, target window, completion criteria, and all five checkpoint decisions.

- [ ] **Step 2: Extend frozen contracts without creating a new authority**

Normalize ArcPlan completion criterion IDs, dependency Arc IDs, target chapter window, expected progress, and milestone IDs. Normalize obligation target window, stale interval, violation policy, payoff evidence, dependency state, and urgency inputs.

- [ ] **Step 3: Implement accepted obligation reducer**

Derive lifecycle solely from accepted chapter/evidence, previous accepted state, and frozen policy. Reject provider-supplied authoritative status when its required accepted evidence is absent.

- [ ] **Step 4: Feed real values into the shared projector**

Replace production empty defaults with derived overdue/stale/violated obligations and dependency blockers. Compute completion only from accepted criterion/milestone/resolution evidence.

- [ ] **Step 5: Run invariant tests and commit**

Commit: `fix: derive accepted arc and obligation checkpoints`

### Task 7: Add Post-Acceptance ArcRevision to PlanChange Follow-Up

**Files:**
- Create: `src/novel_forge/modules/book_authority/arc_followup.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/modules/book_authority/supervisor.py`
- Modify: `src/novel_forge/modules/plan_change_authority/application.py`
- Modify: Artifact lineage repository methods only where required
- Create: `tests/unit/test_arc_revision_followup.py`
- Create: `tests/integration/test_arc_revision_plan_change_postgres.py`

**Interfaces:**
- Acceptance emits a durable signal; post-commit worker creates ArcRevision Candidate and submits the existing PlanChange proposal.

- [ ] **Step 1: Write transaction-boundary tests**

Assert Acceptance persists checkpoint and outbox only, makes no model/Application call, and leaves Actual committed even if follow-up fails.

- [ ] **Step 2: Persist durable follow-up signals transactionally**

For `CORRECT` and `REPLAN_REQUIRED`, write reason codes, accepted evidence refs, checkpoint ID, target frozen plans, trace IDs, and idempotency key in the Acceptance transaction.

- [ ] **Step 3: Implement the post-acceptance workflow**

Lease the signal, create/validate an immutable ArcRevision Candidate, obtain a proposed future-plan asset through the existing candidate generation boundary, and submit `PlanChangeProposalCommand`. Do not decide or activate it.

- [ ] **Step 4: Add minimal lineage and freshness/invalidation invariant**

Link checkpoint -> ArcRevision Candidate -> proposed plan -> PlanChange proposal. Assert legacy freshness and Artifact invalidation agree for assets changed by this path.

- [ ] **Step 5: Run unit/PostgreSQL tests and commit**

Commit: `feat: route arc corrections through plan change authority`

### Task 8: Produce Accepted Retrieval Documents and Governed Embedding Projections

**Files:**
- Create: `src/novel_forge/modules/context_builder/projections.py`
- Create: `src/novel_forge/modules/context_builder/embedding_projection.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/storage/book_authority_repositories.py`
- Modify: `src/novel_forge/modules/production_execution/retrieval_execution.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Create: `tests/unit/test_accepted_retrieval_projection.py`
- Create: `tests/integration/test_retrieval_embedding_projection_postgres.py`

**Interfaces:**
- Produces typed accepted retrieval documents with metadata and a PEP-backed rebuildable embedding projection.

- [ ] **Step 1: Write real-producer tests**

Given accepted prose/outcome/StoryState/Canon/Arc/obligation/knowledge fixtures, assert meaningful document kinds and non-empty entity, character, relationship, Arc, obligation, chapter/scene, source, provenance, and projection hashes where source evidence exists.

- [ ] **Step 2: Extract accepted projection builders**

Build deterministic documents for recent prose/archive locator, outcome/episode/scenes, character/relationship histories, Canon, StoryState, Arc, obligation, and governed knowledge. L0-L9 is stored as taxonomy metadata on shared rows.

- [ ] **Step 3: Persist document projection at accepted boundary**

Write document metadata and semantic status without making an external call in Acceptance. Schedule embedding projection follow-up through existing durable operation infrastructure.

- [ ] **Step 4: Implement governed document embeddings**

Use PEP ExternalEffect/Receipt and persist model/provider/version/dimension/input hash/route/effect/receipt provenance with a versioned projection identity. Retry reconciles Receipts.

- [ ] **Step 5: Run projection unit/PostgreSQL tests and commit**

Commit: `feat: project accepted narrative retrieval evidence`

### Task 9: Add Memo-Driven Retrieval Operation and Immutable Result

**Files:**
- Create: `src/novel_forge/modules/context_builder/runtime.py`
- Modify: `src/novel_forge/modules/context_builder/retrieval.py`
- Modify: `src/novel_forge/modules/context_builder/domain.py`
- Modify: `src/novel_forge/modules/chapter_authority/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Modify: `src/novel_forge/modules/chapter_authority/scheduler.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Create: `tests/unit/test_memo_driven_retrieval.py`
- Modify: `tests/unit/test_context_authority_domain.py`
- Modify: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`

**Interfaces:**
- Adds `ChapterNode.RETRIEVAL`, an immutable `retrieval_result` artifact, and Context Build consumption of its source AssetVersions.

- [ ] **Step 1: Write graph-order and Memo-query tests**

Assert exact order PLAN -> EXECUTION_INTENT -> MEMO -> RETRIEVAL -> CONTEXT -> DRAFT and every qualified Memo retrieval query appears in the normalized query plan.

- [ ] **Step 2: Move historical selection out of Book dispatch**

Book dispatch freezes accepted boundary, protected accepted refs, and policy refs only. Remove the pre-Memo historical selection path.

- [ ] **Step 3: Implement retrieval query plan and PostgreSQL FTS candidate stage**

Use Intent/Memo plus accepted structured signals. Filter future/stale/policy-ineligible documents at the frozen boundary. Capture `ts_rank` as `postgresql_fts`.

- [ ] **Step 4: Add governed query embedding and hybrid rerank**

When frozen policy requires/allows semantic retrieval, create/reconcile a PEP query-embedding effect and include its receipt/model/version. Combine FTS, semantic, entity, character, relationship, temporal, recency, Arc, and obligation signals under a versioned deterministic policy.

- [ ] **Step 5: Persist RetrievalResult and freeze Context inputs**

The operation output contains boundary, Intent/Memo refs, query plan, selected/rejected docs and source hashes, signals/scores, embedding provenance, compression traces, policy, and fingerprint. Context operation inputs include the RetrievalResult and every selected source AssetVersion.

- [ ] **Step 6: Enforce protected overflow and replayable compression**

Protected context is not compressed. Retrievable compression records method, source/provenance, input/output sizes, and output fingerprint. Context Manifest replay must reproduce the same selected/rejected partition and digest.

- [ ] **Step 7: Run unit/PostgreSQL vertical tests and commit**

Commit: `feat: retrieve accepted context from chapter memo`

### Task 10: Remove Parallel Paths, Reconcile Docs, and Produce Release Evidence

**Files:**
- Modify: `docs/architecture/canonical-narrative-architecture.md`
- Modify: `docs/architecture/runtime.md`
- Modify: `docs/architecture/narrative-state.md`
- Modify: `docs/architecture/production-execution.md`
- Modify: `docs/product/novel-production-flow.md`
- Modify: `docs/superpowers/specs/2026-08-20-industrial-autonomous-novel-os-convergence-design.md`
- Delete: `docs/superpowers/plans/2026-08-20-industrial-autonomous-novel-os-convergence.md`
- Modify: transitional path code/tests identified by reachability checks
- Create: `docs/development/post-merge-correctness-closure.md`

**Interfaces:**
- Produces final canonical docs, proof matrix, test commands, remaining qualification list, and Draft PR description.

- [ ] **Step 1: Run reachability searches for old paths**

Audit old Arc contribution/checkpoint tables, old Plan freshness, obsolete Agent binding APIs, pre-Memo candidate selection, controlled scripted Harness reachability, and stale migration-only adapters. Delete dead paths or mark compatibility-only with tests proving canonical runtime cannot reach them.

- [ ] **Step 2: Reconcile canonical documentation**

Describe only final runtime call chains and earned proof levels. Mark the prior spec SUPERSEDED, remove its obsolete implementation plan, and use PostgreSQL FTS terminology.

- [ ] **Step 3: Run focused unit suites**

Run the new tests plus affected Book, Agent, Arc, obligation, Context, migration, PlanChange, architecture, and API suites. Record exact pass/fail/skip counts.

- [ ] **Step 4: Run targeted PostgreSQL smoke suites**

Run migration paths A/B, projection repair, Agent receipt recovery, ArcRevision/PlanChange, retrieval projection, and Book-to-Chapter vertical tests. Do not run campaigns or load suites.

- [ ] **Step 5: Run static repository checks**

Run `git diff --check`, migration-chain validation, architecture boundary tests, and the repository's configured lint/type checks when present.

- [ ] **Step 6: Write evidence report and final docs commit**

Report each WP with DEFINED, WIRED, RUNTIME_REACHABLE, PERSISTED, AUTHORITY_GOVERNED, RECOVERY_PROVEN, UNIT_TESTED, POSTGRES_SMOKE_TESTED, PROVIDER_WIRED, PROVIDER_PROVEN, and PRODUCTION_QUALIFIED. Explicitly list real-provider and long-form qualifications not run.

Commit: `docs: reconcile correctness closure runtime evidence`

- [ ] **Step 7: Clean, push, and open Draft PR**

Verify a clean worktree, inspect every commit/diff, push `codex/post-merge-correctness-closure`, and create one Draft PR against `main`. Include start/final SHAs, migrations, call chains, tests, NOT_PROVEN items, and qualification recommendation.
