# Industrial Autonomous Novel OS Convergence Implementation Plan

> **Design:** `docs/superpowers/specs/2026-08-20-industrial-autonomous-novel-os-convergence-design.md`
> **Base:** `4fdf6adaa25ef085e4e6abab1f5b6ac71d86607a`
> **Branch:** `codex/industrial-autonomous-novel-os`
> **Goal:** converge the existing Authority/Durable Runtime into the approved Novel OS + ARC + InkOS intelligence architecture without parallel truth or execution planes.

## Execution rules

- Write/adjust the narrow failing test before each production behavior.
- Keep every model/network/retrieval effect outside Book Acceptance.
- Use forward-only migration `20260820_0094`; do not edit historical migrations.
- Extend current modules and composition roots; do not create empty hierarchy/Authority shells.
- Stage explicit files and commit by coherent vertical slice.
- Report implementation evidence separately from provider/long-form/production qualification.

## Task 1 — Canonical long-form contracts and plan/actual invariant

**Files**

- Add: `src/novel_forge/modules/longform_narrative/__init__.py`
- Add: `src/novel_forge/modules/longform_narrative/contracts.py`
- Add: `src/novel_forge/modules/longform_narrative/reducers.py`
- Modify: `src/novel_forge/modules/chapter_outcome/domain.py`
- Modify: `src/novel_forge/modules/narrative_state/contracts.py`
- Modify: `src/novel_forge/modules/narrative_state/reducers.py`
- Test: `tests/unit/test_longform_narrative_contracts.py`
- Test: `tests/unit/test_chapter_outcome_longform_evidence.py`

**Steps**

1. Add failing tests for `ArcPlan`, `ArcActualState`, `ArcProgress`, `ArcOutcome`, `ArcCheckpoint`, `ArcRevision` and explicit observation states.
2. Add failing tests proving expected ChapterPlan contributions cannot construct actual evidence.
3. Implement immutable typed contracts and deterministic reducers.
4. Extend `chapter-outcome-v3` with qualified `arc_evidence`, `obligation_events` and typed `scene_outcomes`; preserve the accepted v2 read adapter.
5. Complete obligation types/fields and accepted-only lifecycle validation.
6. Run the two focused suites and existing Narrative State tests.

## Task 2 — Atomic accepted projection set

**Files**

- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/modules/book_production/checkpoints.py`
- Modify: `src/novel_forge/modules/chapter_outcome/application.py`
- Modify: `src/novel_forge/storage/book_authority_repositories.py`
- Add: `src/novel_forge/storage/migrations/versions/v20260820_0094_industrial_autonomous_novel_os.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Test: `tests/unit/test_book_acceptance_longform_reduction.py`
- Test: `tests/integration/test_book_acceptance_projection_set_postgres.py`
- Test: `tests/unit/test_industrial_autonomous_novel_os_migration.py`

**Steps**

1. Add tests that missing Arc evidence yields `NOT_OBSERVED`, never planned `ACTUAL`.
2. Add tests for deterministic Arc/Obligation materialization inside the same acceptance transaction and idempotent replay.
3. Add tables/current pointers for accepted Arc state/progress/checkpoints/outcomes and obligation state/history, keyed by acceptance boundary.
4. Move deterministic long-form reduction into the Book Acceptance transaction; leave no model/retrieval call in the UoW.
5. Make post-acceptance checkpointing consume committed materialization instead of synthesizing actuals.
6. Gate Chapter N+1 readiness on one complete accepted projection set.
7. Run migration, unit and dependency-backed integration tests where PostgreSQL is available.

## Task 3 — Scene typed children, ChapterExecutionIntent and ChapterMemo

**Files**

- Modify: `src/novel_forge/modules/hierarchical_planning/domain.py`
- Modify: `src/novel_forge/modules/chapter_authority/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Modify: `src/novel_forge/modules/chapter_authority/scheduler.py`
- Modify: `src/novel_forge/modules/chapter_authority/provider_output_contracts.py`
- Test: `tests/unit/test_chapter_execution_artifacts.py`
- Test: `tests/unit/test_chapter_scene_contracts.py`
- Test: `tests/unit/test_chapter_runtime_definitions.py`

**Steps**

1. Define addressable/versioned `ScenePlan`/`SceneOutcome` children and embedded `Beat` contracts without new Authority roots.
2. Add `CHAPTER_EXECUTION_INTENT` and `CHAPTER_MEMO` durable Chapter nodes between Plan and Context.
3. Implement deterministic Intent preparation and model-backed/typed Memo candidate production with exact Plan/accepted-boundary lineage.
4. Reject degraded/unqualified artifacts before Context/Draft.
5. Make Context and Draft consume both versions; ensure neither can mutate Plan.
6. Update Chapter saga dependencies/definitions/budgets and run focused scheduler/orchestrator tests.

## Task 4 — Context Contract v2 and layered Narrative Memory

**Files**

- Modify: `src/novel_forge/modules/context_builder/domain.py`
- Add: `src/novel_forge/modules/context_builder/retrieval.py`
- Add: `src/novel_forge/modules/context_builder/memory.py`
- Modify: `src/novel_forge/modules/production_preparation/service.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify migration `v20260820_0094_industrial_autonomous_novel_os.py`
- Test: `tests/unit/test_context_contract_v2.py`
- Test: `tests/unit/test_hybrid_narrative_retrieval.py`
- Test: `tests/unit/test_narrative_memory_layers.py`
- Test: `tests/integration/test_context_retrieval_postgres.py`

**Steps**

1. Add tests for Protected vs Retrievable classification and fail-closed protected overflow.
2. Define L0–L9 ownership/rebuild rules and Manifest v2 fields.
3. Add PostgreSQL retrieval documents/projections with accepted-boundary, lexical/full-text, embedding metadata, entities, relationships, characters, temporal coordinates, Arc and obligation tags.
4. Implement hybrid candidate scoring and deterministic rerank; use PEP for optional remote embedding/rerank/compression only.
5. Record retrieval reasons/scores, token partitions, compression lineage and fingerprint.
6. Wire production preparation and Chapter Context node to latest complete accepted boundary plus Intent/Memo.
7. Test that unaccepted/future evidence cannot be selected.

## Task 5 — Best Candidate and bounded revision convergence

**Files**

- Add: `src/novel_forge/modules/chapter_authority/candidate_selection.py`
- Modify: `src/novel_forge/modules/chapter_authority/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Modify: `src/novel_forge/modules/chapter_authority/scheduler.py`
- Modify migration `v20260820_0094_industrial_autonomous_novel_os.py`
- Test: `tests/unit/test_best_candidate_selection.py`
- Test: `tests/unit/test_chapter_revision_convergence.py`

**Steps**

1. Add tests for hard blocker/regression precedence, minimum net improvement, tie behavior and previous-best retention.
2. Add typed `CandidateComparison` and `BestCandidateSnapshot` contracts.
3. Add durable comparison/best-selection node after Re-review and before extraction/quality consumers.
4. Persist exact candidate/review/policy lineage and rollback pointer.
5. Route extraction, Quality, export and acceptance evidence to the selected best, not the latest Revision.
6. Implement stop reasons: satisfied, budget exhausted, marginal improvement, deterministic blocker, escalation.

## Task 6 — Unified Agent Harness and taxonomy convergence

**Files**

- Modify: `src/novel_forge/modules/agent_runtime/contracts.py`
- Add: `src/novel_forge/modules/agent_runtime/session.py`
- Add: `src/novel_forge/modules/agent_runtime/tools.py`
- Modify: `src/novel_forge/modules/agent_runtime/definitions.py`
- Modify: `src/novel_forge/modules/agent_runtime/application.py`
- Modify: `src/novel_forge/modules/agent_runtime/scheduler.py`
- Modify: `src/novel_forge/modules/agent_runtime/repository.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify migration `v20260820_0094_industrial_autonomous_novel_os.py`
- Test: `tests/unit/test_agent_harness_contracts.py`
- Test: `tests/unit/test_agent_harness_session.py`
- Test: `tests/unit/test_agent_harness_authority_boundary.py`
- Test: `tests/integration/test_agent_harness_postgres.py`

**Steps**

1. Define autonomous roles, session/turn/transcript/tool/Skill/budget contracts and committed-request restoration.
2. Define three Tool classes only: accepted-boundary query, Typed Capability invocation, Authority Command submission.
3. Implement a bounded turn loop whose model turns and remote Tool calls are ExternalEffects.
4. Enforce role/operation allowlists, Skill provenance, cancellation/deadline and token/cost/turn/effect hard stops.
5. Persist append-only transcript events with sequence CAS; checkpoint/resume from PostgreSQL.
6. Reject direct Canon/State/Arc/Obligation/Plan/Acceptance mutation tools.
7. Retain `agent.candidate.execute` as the Typed Capability bridge only where still consumed; remove the false implication that every Chapter model stage is an autonomous Agent.

## Task 7 — Unified artifact lineage and semantic invalidation

**Files**

- Add: `src/novel_forge/modules/artifact_lineage/__init__.py`
- Add: `src/novel_forge/modules/artifact_lineage/domain.py`
- Add: `src/novel_forge/modules/artifact_lineage/application.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/application.py`
- Modify: `src/novel_forge/modules/book_design_authority/application.py`
- Modify: `src/novel_forge/modules/book_replan/coordinator.py`
- Modify: `src/novel_forge/modules/source_import/application.py`
- Modify migration `v20260820_0094_industrial_autonomous_novel_os.py`
- Test: `tests/unit/test_artifact_lineage.py`
- Test: `tests/unit/test_semantic_invalidation.py`
- Test: `tests/integration/test_artifact_lineage_postgres.py`

**Steps**

1. Define one typed edge, semantic diff, impact and invalidation lifecycle for new writes.
2. Add traversal tests proving selective future invalidation and accepted-history immunity.
3. Persist canonical lineage/dependency/invalidation records.
4. Move Planning, Book Design and Source consumers to the canonical application.
5. Keep old tables read-only migration compatibility until consumers move; forbid normal dual-write.
6. Requalification never restores active pointers without owning Authority activation.

## Task 8 — Composition, legacy cleanup and architecture boundaries

**Files**

- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/modules/book_authority/composition.py`
- Modify: `architecture/manifests/module-manifest.yaml`
- Modify: `architecture/manifests/production-entry-manifest.yaml` if entry ownership changes
- Modify: `tests/architecture/test_core_functional_loop_boundaries.py`
- Add/Modify architecture tests for Agent, Context, lineage and acceptance boundaries

**Steps**

1. Wire every new contract through current API/worker compositions and existing schedulers.
2. Convert the two stale architecture tests to state-semantics and sidecar-ownership behavior assertions.
3. Search and remove/isolate direct Provider, Canon/State mutation, duplicate Context, false autonomous-Agent, dual dependency-write and fixture production bypass paths.
4. Update manifests and architecture fitness rules.
5. Prove one canonical mutation path per authoritative state class.

## Task 9 — Verification, commits and Draft PR

**Commands**

1. Run focused unit tests after each task.
2. Run `make lint`, `make lint-authority`, `make lint-ratchet`.
3. Run architecture manifest/fitness checks.
4. Run modified unit + architecture suites.
5. Run dependency-backed PostgreSQL migration/repository/integration smoke tests when available.
6. Do not run long-form/provider/multi-book campaigns.
7. Inspect `git diff --check`, exact committed diff and worktree cleanliness.
8. Create coherent commits for long-form acceptance, chapter/context/intelligence, Agent/lineage convergence, and final tests/docs.
9. Push `codex/industrial-autonomous-novel-os` and create a Draft PR against `main` with explicit evidence classes and NOT_PROVEN items.
