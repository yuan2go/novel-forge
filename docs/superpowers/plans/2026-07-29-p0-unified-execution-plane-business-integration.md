# P0 Unified Production Execution Plane Business Integration Plan

> Execute this plan test-first. Preserve PostgreSQL Authority as the sole
> production authority and reuse the existing Command Kernel.

**Goal:** Route book-to-chapter scheduling, Reader Outcome, and Long-form Recap
through the existing governed production execution plane, close production
LocalStorage bypasses, and make legacy parity machine-verifiable.

**Architecture:** Add business operation definitions and handlers on the existing
Authority runtime. Book coordination persists stable references to Chapter
Authority operations instead of copying chapter execution state. Reader Outcome
uses the existing Production Execution Gateway and ExternalEffect lifecycle.
Long-form Recap is a governed observer that emits immutable proposals. PostgreSQL
views expose rebuildable projections.

**Technology:** Python 3.11+, dataclasses/Pydantic-compatible JSON contracts,
PostgreSQL migrations, pytest/unittest, existing Novel Forge Command Kernel.

---

## Task 1: Authority parity manifest

**Files**

- Create: `config/authority/authority-parity-manifest.json`
- Create: `src/novel_forge/tools/authority_parity_manifest.py`
- Test: `tests/architecture/test_authority_parity_manifest.py`
- Modify: `Makefile`
- Modify: authority CLI command registration

**Steps**

1. Write failing tests for exact legacy-step coverage, unique mappings, registered
   operation definitions/handlers, output contracts, and truthful evidence levels.
2. Define controlled parity statuses and a typed loader.
3. Populate all twelve real legacy steps with many-to-many Authority mappings.
4. Add a CI-friendly JSON report and non-zero failure exit.
5. Run the focused architecture test and `make authority-parity-check`.

## Task 2: Production bypass guards

**Files**

- Modify: `src/novel_forge/storage/local.py`
- Modify: `src/novel_forge/modules/longform_recap/service.py`
- Test: `tests/architecture/test_unified_execution_business_boundaries.py`
- Test: focused long-form/legacy unit tests

**Steps**

1. Write failing tests proving LocalStorage and legacy Recap mutation fail closed
   under `production`, `staging`, and `production_like`.
2. Add explicit non-authoritative/rebuildable metadata to LocalStorage.
3. Apply one environment-policy guard at write boundaries and a clear legacy Recap
   entry guard.
4. Verify development fixtures remain available.
5. Statistically forbid authority API, CLI, scheduler, and Book Authority imports
   or calls that bypass command ports.

## Task 3: Reader Outcome governed operation

**Files**

- Create/modify: Book follow-up authority contracts, definitions, codecs, registry,
  application, and query modules
- Modify: shared authority handler request metadata
- Modify: chapter model effects and execution-gateway route map
- Test: unit and PostgreSQL integration tests

**Steps**

1. Write contract and handler tests for typed inputs, structured Reader State,
   explainable gate outcomes, issues, and immutable asset outputs.
2. Register `reader_outcome.evaluate` with retry, cancel, timeout, lease, fence,
   effect, input, output, and evidence contracts.
3. Route provider work through the existing ExternalEffect-backed Production
   Execution Gateway; never call a provider directly.
4. Emit `reader_outcome_report`, `reader_state_transition`, and
   `reader_issue_set` AssetVersions atomically.
5. Prove replay idempotency, invalid-output repair classification, retry, and
   projection reads.

## Task 4: Long-form Recap governed operation

**Files**

- Create/modify: shared Book follow-up authority modules
- Test: unit and PostgreSQL integration tests

**Steps**

1. Write tests for trigger policies and typed deviation classification.
2. Register `longform.recap` with frozen input snapshots and full operation policy.
3. Emit `longform_recap`, `longform_deviation_report`, and
   `plan_adjustment_proposal`; emit `replan_request` only when warranted.
4. Ensure the handler cannot mutate Canon or plan state.
5. Prove idempotency, retry/recovery, and projection reads.

## Task 5: Book Authority to Chapter Authority

**Files**

- Create: PostgreSQL migration for book runs, chapter requests, follow-up links,
  constraints, indexes, and projections
- Modify/create: Book Authority command application, coordinator, queries, API/CLI
- Test: unit and PostgreSQL integration tests

**Steps**

1. Write failing tests for stable chapter submission idempotency and plan-version
   supersession.
2. Persist a book run state machine and Chapter Authority references.
3. Submit `SingleChapterRequest` through `ChapterAuthorityApplication.admit`.
4. Reconcile from Chapter Authority query state after response loss or projection
   lag; never rerun unknown work blindly.
5. Submit Reader Outcome after final chapter/canon outputs; submit Recap on a due
   checkpoint; advance the book checkpoint only from governed results.
6. Test retryable/terminal chapter failure, pause/resume, stale plan, and recovery.

## Task 6: Vertical and PostgreSQL proof

**Files**

- Create/modify: end-to-end PostgreSQL integration tests
- Modify: migration-current assertions

**Steps**

1. Prove Book Authority → Chapter Authority → fake Provider → Final Draft → Canon
   → Reader Outcome → Book Checkpoint.
2. Prove repeated submission does not duplicate root operations or charge/effect
   dispatch.
3. Prove stale fences cannot persist outputs.
4. Prove Reader Outcome failure preserves completed draft/canon and is retryable.
5. Prove checkpoint cadence creates one Recap operation and exposes its proposal.
6. Prove all migrations, architecture guards, and parity checks.

## Task 7: Documentation and complete regression

**Files**

- Create/update the unified execution, parity, Book-to-Chapter, Reader Outcome, and
  Recap architecture documents under the existing architecture tree
- Create: `docs/reports/p0-unified-execution-plane-implementation-report.md`
- Modify: current-state documentation, Makefile/CLI/environment docs if affected

**Steps**

1. Run focused tests while implementing.
2. Run PostgreSQL Authority integration.
3. Run the complete existing test suite.
4. Run formatting/type/static checks already defined by the repository.
5. Record exact command counts, durations, skips, failures, and evidence levels.
6. Declare completion only if all requested gates are factual; otherwise use the
   precise partial status and list blockers.
