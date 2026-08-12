# Narrative Runtime Convergence Implementation Plan

> **For agentic workers:** Execute inline in this session. Each task must retain PostgreSQL
> Authority, immutable evidence, and fail-closed proof boundaries.

**Goal:** Complete the executable long-form Narrative Runtime contract on the current
Authority and production composition without creating parallel owners.

**Architecture:** Extend Narrative State reducers and Context manifests over accepted
ChapterOutcome evidence, then expose consumption and proof projections from PostgreSQL.
Reuse PlanChange, Book Replan, Capability Pack, Source Intelligence, and MKAOS Authority.

**Tech Stack:** Python 3.12, PostgreSQL 16, psycopg, pytest, Ruff, mypy, JSONB Authority assets.

## Global Constraints

- `main` at start SHA `42944de24bc083ca1e6dd12c68cbfa0f96602807` is the code baseline.
- `.idea/modules.xml` must not be modified, staged, stashed, or committed.
- No new Narrative Authority, scheduler, provider runtime, vector store, or Skill.
- Immutable historical v1/v2 evidence is replay-only; new production output uses the
  converged contract.
- Engineering validation must not be reported as `LONGFORM_PROVEN`, `MULTIBOOK_PROVEN`, or
  `PRODUCTION_PROVEN`.

---

### Task 1: Complete temporal state and obligation semantics

**Files:**
- Modify: `src/novel_forge/modules/narrative_state/contracts.py`
- Modify: `src/novel_forge/modules/narrative_state/reducers.py`
- Modify: `src/novel_forge/modules/temporal_query/service.py`
- Test: `tests/unit/test_narrative_runtime_convergence.py`

**Interfaces:**
- Produce `NarrativePosition`, richer `NarrativeCoordinate`, new state kinds, and unified
  `narrative_obligation` reducer semantics.
- Preserve `events_from_chapter_outcome()` as the immutable evidence adapter.

- [x] Add failing contract, lifecycle, temporal-range, knowledge-boundary, and reducer tests.
- [x] Implement typed positions, state kinds, identity rules, payload validation, and reducers.
- [x] Route new Canon obligation fields into one lifecycle and keep old kinds replay-only.
- [x] Extend Temporal Query for knowledge, belief, world, and obligation as-of reads.
- [x] Run the focused unit and architecture tests.

### Task 2: Make Context Builder a reproducible Narrative Context Engine

**Files:**
- Modify: `src/novel_forge/modules/context_builder/domain.py`
- Modify: `src/novel_forge/modules/chapter_authority/domain_handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Test: `tests/unit/test_narrative_context_manifest.py`

**Interfaces:**
- Produce `narrative-context-manifest-v1` with task/capability, narrative position,
  Authority boundary, selection reasons, exact version/hash lineage, knowledge usage,
  replay algorithm identity, budget, and digest.

- [x] Add failing reproducibility, future-boundary, and knowledge-lineage tests.
- [x] Build the manifest from frozen candidates and the current ChapterPlan.
- [x] Require accepted StoryState/Canon boundaries for continuing chapters.
- [x] Freeze the manifest into all downstream Chapter model inputs.
- [x] Run focused Chapter handler and Context tests.

### Task 3: Propagate planning constraints and governed actions

**Files:**
- Modify: `src/novel_forge/modules/story_planning_runtime/domain.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/application.py`
- Modify: `src/novel_forge/modules/content_quality_loop/domain.py`
- Modify: `src/novel_forge/modules/book_followup_authority/domain.py`
- Modify: `src/novel_forge/modules/book_replan/coordinator.py`
- Test: `tests/unit/test_narrative_governed_actions.py`

**Interfaces:**
- Produce a deterministic `constraint_envelope` and typed
  `Observation -> Evidence -> Issue -> RequiredAction -> Gate` decision payload.
- Map actions to `LOCAL_REPAIR`, `CHAPTER_ADJUSTMENT`, `ARC_REPLAN`, `VOLUME_REPLAN`, or
  `BOOK_STRATEGIC_REPLAN`; only existing PlanChange/Book Replan can activate a plan change.

- [x] Add failing scope-escalation and invariant-preservation tests.
- [x] Freeze parent constraints and accepted-state boundaries into Planning candidates.
- [x] Normalize Quality/Reader required actions without adding another Judge.
- [x] Enforce affected scope and invariant evidence at Book Replan admission.
- [x] Run Planning, Quality, Reader, and Replan tests.

### Task 4: Add runtime consumption and proof evidence

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260812_0083_narrative_runtime_convergence.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Modify: `architecture/manifests/test-manifest.yaml`
- Create: `src/novel_forge/modules/narrative_state/measurements.py`
- Test: `tests/unit/test_narrative_runtime_migration.py`
- Test: `tests/integration/test_narrative_runtime_convergence_postgres.py`

**Interfaces:**
- Produce read-only `authority_context_runtime_usage_projection` and
  `authority_mkaos_runtime_usage_projection`.
- Produce deterministic measurement records for leakage, contradiction, obligation,
  context, planning, action-effect, usage/cost, and trace evidence.

- [x] Add migration and measurement tests.
- [x] Add continuous migration 0083 and register it in all manifests.
- [x] Verify Source methodology/profile hashes and Capability Pack bindings remain canonical.
- [x] Run PostgreSQL migration and production-path integration tests.

### Task 5: Full validation and review

**Files:**
- Modify only files required by failures exposed by this change.

- [x] Run focused unit and PostgreSQL tests.
- [x] Run `make validate`.
- [x] Run `make authority-test` and `make authority-postgres-test`.
- [x] Run `git diff --check`, inspect dead code and protected local state.
- [x] Review the complete diff against the design and proof ceiling.
- [x] Commit the deliverable on `main` and record the final SHA.
