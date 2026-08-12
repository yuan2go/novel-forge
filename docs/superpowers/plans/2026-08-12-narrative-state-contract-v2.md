# Narrative State Contract v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Narrative State v1's append-list and duplicated temporal semantics with one typed accepted-event contract, deterministic current-state materialization, accepted-only as-of replay, and compact governed context.

**Architecture:** ChapterOutcome v2 stores normalized state events and becomes authoritative only through committed Book acceptance. StoryState v2 materializes keyed current state with typed reducers; PostgreSQL exposes accepted event/current views, while Temporal Query and Production Preparation remain read-only consumers. Persisted v1 evidence is supported only by a deterministic adapter/rebuild path.

**Tech Stack:** Python 3.12, dataclasses and `StrEnum`, PostgreSQL 16 JSONB/views, psycopg, pytest, Ruff, existing Command Kernel/AssetVersion/Book Authority/Context Builder.

## Global Constraints

- Start from `55b33675f223488fe7193d672ecdfc7e7df28737` on `refactor/narrative-state-contract-v2`.
- Preserve Canon, ChapterOutcome, StoryState, Temporal Query, Plan, Context and Knowledge ownership boundaries.
- Do not add a second Authority, scheduler, workflow, provider runtime, state runtime, universal state table, or generic JSON aggregate.
- New production assets emit v2 semantics only; v1 support is read/rebuild-only.
- Never use `created_at` as narrative time and never update/delete historical Authority evidence.
- Context keeps exact immutable refs, source isolation, token budgets and selected/rejected manifests.
- `.idea/modules.xml` must remain untouched.

---

### Task 1: Shared Narrative State contract and v1 evidence adapter

**Files:**
- Create: `src/novel_forge/modules/narrative_state/__init__.py`
- Create: `src/novel_forge/modules/narrative_state/contracts.py`
- Create: `tests/unit/test_narrative_state_contract_v2.py`
- Modify: `architecture/manifests/module-manifest.yaml`
- Modify: `architecture/manifests/test-manifest.yaml`

**Interfaces:**
- Consumes: governed Canon patch dictionaries and v1 ChapterOutcome AssetVersion content.
- Produces: `NarrativeStateEvent`, `NarrativeStateKind`, `ReducerSemantics`, `events_from_canon_patch(...)`, and `events_from_chapter_outcome(...)`.

- [ ] **Step 1: Write failing contract tests**

Cover deterministic event IDs, Project/Book/entity scope, source/effective boundaries, evidence/confidence/coverage, the sole `supersedes_event_id` field, missing identity, future-effective failure, and deterministic conversion of v1 fields.

- [ ] **Step 2: Verify the contract tests fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_narrative_state_contract_v2.py -q`
Expected: import failure for `novel_forge.modules.narrative_state`.

- [ ] **Step 3: Implement the immutable contract**

Use frozen dataclasses for scope, identity, coordinate, mutation, provenance and event. Normalize state-specific identities, forbid aliases on v2 input, validate `effective_from_chapter <= source_chapter`, and hash canonical JSON for `event_id`.

- [ ] **Step 4: Add the one-way v1 adapter**

Map `occurred_events`, typed delta/action arrays, legacy chapter names and legacy supersession aliases into v2 events only when reading persisted `chapter-outcome-v1`; never emit those names from a v2 outcome.

- [ ] **Step 5: Run contract and architecture-manifest tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_narrative_state_contract_v2.py tests/architecture/test_architecture_manifests.py -q`
Expected: all pass.

### Task 2: Typed deterministic reducers and replay

**Files:**
- Create: `src/novel_forge/modules/narrative_state/reducers.py`
- Create: `src/novel_forge/modules/narrative_state/projections.py`
- Create: `tests/unit/test_narrative_state_semantics_v2.py`
- Modify: `src/novel_forge/modules/chapter_outcome/domain.py`

**Interfaces:**
- Consumes: ordered `NarrativeStateEvent` tuples and optional StoryState v2 content.
- Produces: `reduce_story_state_v2(...)`, `rebuild_story_state(...)`, `compact_current_state_facts(...)`, and v2 `StoryStateSnapshot` content.

- [ ] **Step 1: Write the readable 1-to-100 chapter semantic suite**

Use Lin/Hangzhou/Secret-X/Mei/Beijing/Promise-P/WorldRule-R/Resource-X/Foreshadow-F/PlotThread-T fixtures. Assert current state, chapters 1/9/10/29/30/39/40/69/70/79/80/89/90/99/100, replay equality, duplicate-head idempotence, out-of-order failure, missing state and supersession.

- [ ] **Step 2: Verify append-list v1 fails the suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_narrative_state_semantics_v2.py -q`
Expected: missing reducer/projection APIs.

- [ ] **Step 3: Implement policy-specific reducers**

Implement keyed upsert, declared-from transition, lifecycle open/close, world-rule activation/supersession, checked resource balance, power transition, character knowledge set updates, derived narrative debt, and append-only timeline/reward/theme policies. Reject unknown kinds, cross-scope events, supersession identity drift and invalid terminal reopening.

- [ ] **Step 4: Replace ChapterOutcome/StoryState canonical emission**

`build_chapter_outcome()` emits `chapter-outcome-v2`, plan/Canon/release lineage and `state_events`. `reduce_story_state()` delegates to v2 and emits `story-state-snapshot-v2` without historical append lists.

- [ ] **Step 5: Run reducer and existing ChapterOutcome tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_narrative_state_semantics_v2.py tests/unit/test_chapter_outcome_story_state.py -q`
Expected: all pass with v2 assertions.

### Task 3: Canon current snapshot and acceptance ownership

**Files:**
- Modify: `src/novel_forge/modules/canon_graph/domain.py`
- Modify: `src/novel_forge/modules/chapter_authority/domain_handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Modify: `src/novel_forge/modules/chapter_authority/provider_output_contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Modify: `src/novel_forge/modules/chapter_outcome/handlers.py`
- Modify: `src/novel_forge/modules/chapter_outcome/contracts.py`
- Modify: `src/novel_forge/modules/chapter_outcome/application.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Test: `tests/unit/test_stateful_canon_domain.py`
- Test: `tests/unit/test_chapter_provider_output_contracts.py`
- Test: `tests/integration/test_chapter_outcome_story_state_postgres.py`

**Interfaces:**
- Consumes: current StoryState facts in Context plus governed extraction and Canon decisions.
- Produces: `canon-snapshot-v2`, `chapter-outcome-v2`, `story-state-snapshot-v2`; actual acceptance is still `authority_book_chapter_acceptance`.

- [ ] **Step 1: Add failing Canon/acceptance ownership tests**

Assert Canon emits a cumulative keyed current snapshot, ChapterOutcome binds Canon patch/draft/plan Operation+Trace lineage, orphan outputs are not accepted, and Book acceptance points at the v2 current Canon and StoryState versions.

- [ ] **Step 2: Introduce explicit Book identity in Chapter commands**

Add `book_id` to `SingleChapterRequest`, command schemas and controlled Book dispatch. Standalone Chapter fixtures use an explicit standalone Book identity; no v2 event may have an empty Book scope.

- [ ] **Step 3: Make Canon snapshots actual snapshots**

Materialize current Canon facts by semantic identity and stop emitting non-Canon change arrays with `role=state_snapshot`. Provider Canon change schemas require state-kind identities and accept only `supersedes_event_id` for v2 supersession.

- [ ] **Step 4: Bind v2 outcome construction to immutable source AssetVersions**

Pass Canon patch AssetVersion, draft AssetVersion, source Operation and Trace into event normalization. Bump ChapterOutcome operation/handler contracts and qualification policies to v2.

- [ ] **Step 5: Run focused Canon, provider and PostgreSQL tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_stateful_canon_domain.py tests/unit/test_chapter_provider_output_contracts.py tests/unit/test_chapter_outcome_story_state.py -q`
Run with test PostgreSQL: `NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge:novel_forge@localhost:55432/novel_forge_authority_test PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_chapter_outcome_story_state_postgres.py -q`
Expected: all pass.

### Task 4: Forward-only PostgreSQL projections and Temporal Query

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260812_0082_narrative_state_contract_v2.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Modify: `src/novel_forge/storage/story_state_repositories.py`
- Modify: `src/novel_forge/modules/temporal_query/service.py`
- Create: `tests/unit/test_narrative_state_migration_v2.py`
- Modify: `tests/unit/test_temporal_query_domain.py`
- Create: `tests/integration/test_narrative_state_v2_postgres.py`

**Interfaces:**
- Consumes: committed Book acceptance rows, accepted ChapterOutcome v1/v2 AssetVersions, and accepted StoryState/Canon AssetVersions.
- Produces: `authority_narrative_state_event_projection`, `authority_narrative_current_state_projection`, accepted-only `TemporalQueryService` results and read-only rebuild comparison.

- [ ] **Step 1: Add failing migration and Temporal tests**

Assert migration head/lineage, forward-only metadata, v2/v1 event branches, Project/Book/chapter indexes, inclusive as-of semantics, future exclusion, accepted-only state and deterministic rebuild.

- [ ] **Step 2: Implement migration 0082**

Create accepted-outcome-rooted event/current views. Add reducer evidence columns for semantics, source/accepted chapter, event IDs and prior snapshot. Do not mutate historical rows.

- [ ] **Step 3: Rewrite Temporal Query on the shared contract**

Require Project and Book scope, load only committed accepted events through the view, replay with shared reducers, expose current/as-of/changes queries, return explicit missing state, and keep `recorded_at` audit-only.

- [ ] **Step 4: Implement read-only rebuild comparison**

Load accepted outcomes in chapter order, adapt v1 only at the input boundary, replay and return rebuilt content/hash versus the stored accepted snapshot without persisting changes.

- [ ] **Step 5: Run migration and PostgreSQL proof**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_narrative_state_migration_v2.py tests/unit/test_temporal_query_domain.py -q`
Run: `NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge:novel_forge@localhost:55432/novel_forge_authority_test PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_authority_migrations_postgres.py tests/integration/test_narrative_state_v2_postgres.py -q`
Expected: all pass.

### Task 5: Accepted compact state in Production Preparation and Context

**Files:**
- Modify: `src/novel_forge/modules/production_preparation/contracts.py`
- Modify: `src/novel_forge/modules/production_preparation/policies.py`
- Modify: `src/novel_forge/modules/production_preparation/resolver.py`
- Modify: `src/novel_forge/modules/production_preparation/service.py`
- Modify: `src/novel_forge/modules/context_builder/domain.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/context_views.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/api/models.py`
- Modify: `src/novel_forge/api/routers/chapter_authority.py`
- Test: `tests/unit/test_authority_production_preparation.py`
- Test: `tests/unit/test_quality_context_authority.py`
- Test: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`

**Interfaces:**
- Consumes: immediately preceding committed StoryState/Canon snapshot for the same Project/Book.
- Produces: frozen compact `ContextCandidate`/ContextBundle segments with exact snapshot/event lineage.

- [ ] **Step 1: Add failing future-leak and compact-context tests**

Create accepted Chapter N state plus active-but-unaccepted Chapter N+1 assets. Assert preparation for N+1 selects only accepted N, rejects wrong Book/boundary, and Context contains one current entity fact instead of its historical changes.

- [ ] **Step 2: Scope production requests by Book**

Require `book_id` for controlled continuing chapters and propagate it through API, supervisor, command, manifest and Context refs.

- [ ] **Step 3: Resolve state through Book acceptance only**

Specialize PostgreSQL state lookup to committed acceptance. Continuing chapters require only v2 StoryState and Canon current snapshots; legacy per-kind snapshots cannot satisfy the production canonical path.

- [ ] **Step 4: Render compact current facts without rewriting Context Builder**

Use `compact_current_state_facts()` in candidate construction, retain source isolation/token budget/selected-rejected manifests, and make Canon/Quality historical views expand the compact accepted state.

- [ ] **Step 5: Run preparation, Context and Book integration tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_authority_production_preparation.py tests/unit/test_quality_context_authority.py -q`
Run: `NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge:novel_forge@localhost:55432/novel_forge_authority_test PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_book_to_chapter_authority_vertical_postgres.py -q`
Expected: all pass.

### Task 6: Architecture, ownership and documentation closure

**Files:**
- Modify: `docs/architecture/narrative-state.md`
- Modify: `docs/product/novel-production-flow.md`
- Modify: `docs/product/capability-map.md`
- Create: `tests/architecture/test_narrative_state_boundaries.py`
- Modify: `architecture/manifests/test-manifest.yaml`

**Interfaces:**
- Consumes: final v2 code paths.
- Produces: executable ownership assertions and current-code documentation.

- [ ] **Step 1: Write failing architecture tests**

Assert Narrative State reducers are storage-free, Temporal/Context/Plan modules cannot import mutation Authorities, production preparation does not treat per-kind v1 snapshots as canonical state, and Canon/StoryState ownership remains distinct.

- [ ] **Step 2: Update architecture and product docs**

Document the event/current/as-of layers, accepted boundary, reducer matrix, sole supersession/time names, rebuild process, Context behavior, v1 removal and qualification ceiling.

- [ ] **Step 3: Run architecture and head-integrity gates**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/architecture/test_narrative_state_boundaries.py -q`
Run: `make architecture-manifests-check architecture-fitness-check head-integrity-check`
Expected: all pass.

### Task 7: Full qualification, publication and Draft PR

**Files:**
- Verify all modified files; do not modify `.idea/modules.xml`.

**Interfaces:**
- Consumes: complete implementation and test evidence.
- Produces: clean branch, pushed commit(s), Draft PR to `main`, evidence-bounded delivery report.

- [ ] **Step 1: Run local gates**

Run: `make validate`
Run: `make authority-test`
Run: `make test`
Expected: all applicable checks pass; existing deprecation warnings remain non-blocking.

- [ ] **Step 2: Run clean PostgreSQL migration and full Authority integration**

Run: `make postgres-authority-test-down && make postgres-authority-test-up && make postgres-authority-test`
Expected: all non-skippable PostgreSQL tests pass with migration head `20260812_0082_narrative_state_contract_v2`.

- [ ] **Step 3: Run final integrity checks**

Run: `make sync-skills-dry-run && make check-skills`
Run: `git diff --check && git status --short --branch`
Expected: no skill drift, no whitespace errors, no unrelated or protected local state.

- [ ] **Step 4: Commit and push**

Stage only Narrative State v2 files, commit with an intentional message, and run `git push -u origin refactor/narrative-state-contract-v2`.

- [ ] **Step 5: Create a Draft PR**

Use the authenticated GitHub path to open a Draft PR against `main`. The body records start/final SHA, root cause, contract/reducer/migration/context changes, exact tests, PostgreSQL proof and explicit non-goals/qualification ceiling.
