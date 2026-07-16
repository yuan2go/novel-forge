# PostgreSQL-only Single-Chapter Handler Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the runbook's deterministic one-project, one-chapter PostgreSQL-only handler chain from ChapterPlan through verified Export Blob without using LocalStorage as command authority.

**Architecture:** Add a focused `chapter_authority` application module above the existing Command Kernel. Typed node handlers produce immutable output descriptions; a fenced runtime atomically materializes each output as an authoritative AssetVersion with qualification, binding, audit, and outbox evidence. A small orchestrator dynamically admits each downstream child only after its upstream AssetVersion is frozen, uses the fenced Saga coordinator for readiness/root completion, and routes Export bytes through the Generic ExternalEffect/Blob protocol.

**Tech Stack:** Python 3.11 dataclasses/protocols, psycopg 3, existing PostgreSQL Authority Unit of Work, existing Command Kernel Attempt/Completion/Saga/Asset/Blob/ExternalEffect services, `unittest` PostgreSQL integration tests.

## Global Constraints

- PostgreSQL `authority_*` tables are the only command-side authority for this slice.
- No handler writes LocalStorage or `nf_*` projection tables.
- No real model provider and no 30/50/100-chapter generation is executed.
- Every child uses standard admission, Attempt lease/fencing, result submission, Completion, operation-scoped AssetVersion binding, audit, and outbox evidence.
- Export bytes use Generic ExternalEffect dispatch, receipt, Blob verification, and AssetVersion binding.
- Retry and replay must not create duplicate authoritative outputs.

---

### Task 1: Define the chapter operation catalog and typed handler boundary

**Files:**
- Create: `src/novel_forge/modules/chapter_authority/__init__.py`
- Create: `src/novel_forge/modules/chapter_authority/contracts.py`
- Create: `src/novel_forge/modules/chapter_authority/definitions.py`
- Test: `tests/unit/test_chapter_authority_definitions.py`

**Interfaces:**
- Produces: `ChapterNode`, `ChapterHandlerRequest`, `ChapterHandlerOutput`, `ChapterHandlerRegistry`, `chapter_operation_definitions()`.
- Consumes: the existing OperationDefinition repository contract.

- [x] **Step 1: Write failing catalog and registry tests**

Assert the eight ordered node definitions have closed command schemas, unique handler keys, frozen completion contracts, output selectors, and explicit compensation metadata where applicable. Assert duplicate or missing registry handlers fail closed.

- [x] **Step 2: Run the focused unit test and verify RED**

Run: `.venv/bin/python -m unittest tests.unit.test_chapter_authority_definitions -v`

- [x] **Step 3: Implement immutable contracts, catalog, and fail-closed registry**

Use `dataclass(frozen=True, slots=True)`, `Protocol`, explicit node enums, version `1.0.0`, and no runtime imports of LocalStorage or model adapters.

- [x] **Step 4: Run the focused unit test and verify GREEN**

Run: `.venv/bin/python -m unittest tests.unit.test_chapter_authority_definitions -v`

### Task 2: Add fenced, idempotent authoritative output materialization

**Files:**
- Create: `src/novel_forge/storage/chapter_authority_repositories.py`
- Modify: `src/novel_forge/storage/authority_repositories.py`
- Create: `src/novel_forge/modules/chapter_authority/runtime.py`
- Test: `tests/integration/test_chapter_authority_runtime_postgres.py`

**Interfaces:**
- Consumes: `WorkerLeaseCommand`, a registered handler, frozen operation input snapshots.
- Produces: `execute_chapter_handler(...) -> ChapterExecutionResult` and one idempotent authoritative output binding.

- [x] **Step 1: Write a failing PostgreSQL handler-runtime test**

Admit a node, create/lease/start an Attempt, execute a handler, and assert one ACTIVE/ELIGIBLE/CLEAR AssetVersion, latest ELIGIBLE qualification, operation output binding, handler audit, and handler outbox record. Replay with the same fenced execution and assert no duplicate output.

- [x] **Step 2: Run the focused PostgreSQL test and verify RED**

Run: `NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge@127.0.0.1:55432/novel_forge_authority_test .venv/bin/python -m unittest tests.integration.test_chapter_authority_runtime_postgres -v`

- [x] **Step 3: Implement the repository/runtime transaction**

Lock the Attempt and Operation, validate the current fencing token, load only the frozen input AssetVersions, execute the typed handler outside neither project nor operation scope, derive stable IDs/content hash, and atomically insert or replay Asset, AssetVersion, qualification, binding, StateEvent, AuditLog, and Outbox.

- [x] **Step 4: Run the focused PostgreSQL test and verify GREEN**

Run the command from Step 2.

### Task 3: Implement deterministic single-chapter handlers and the Saga orchestrator

**Files:**
- Create: `src/novel_forge/modules/chapter_authority/handlers.py`
- Create: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Test: `tests/integration/test_postgresql_only_chapter_slice.py`

**Interfaces:**
- Consumes: `ChapterContentProvider` and existing admission/Attempt/Completion/Saga services.
- Produces: `run_single_chapter_slice(...) -> ChapterSliceResult` for ChapterPlan, ContextBundle, Draft, Review, Revision, Canon, Quality Gate, and Export.

- [x] **Step 1: Write the failing end-to-end deterministic fixture test**

Run one chapter with a fake provider; assert every child followed admission/Attempt/Completion, every output is operation-bound, dependencies are linear, the root/Saga succeed, review evidence drives revision, and no LocalStorage/`nf_*` rows are used as authority.

- [x] **Step 2: Run the focused integration test and verify RED**

Run: `NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge@127.0.0.1:55432/novel_forge_authority_test .venv/bin/python -m unittest tests.integration.test_postgresql_only_chapter_slice -v`

- [x] **Step 3: Implement handlers and dynamic child admission**

Admit the root, start the Saga, then for each node admit a child with upstream content hashes frozen in `input_asset_snapshot`, register the step/dependency, let the fenced coordinator set READY, run a leased Attempt, materialize output, and submit Completion. Inject a single retryable pre-output failure through the public Attempt result path and let Saga forward recovery create the next Attempt.

- [x] **Step 4: Run the focused integration test and verify GREEN**

Run the command from Step 2.

### Task 4: Complete Export through Generic ExternalEffect and emit the evidence manifest

**Files:**
- Modify: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Create: `src/novel_forge/modules/chapter_authority/evidence.py`
- Modify: `tests/integration/test_postgresql_only_chapter_slice.py`

**Interfaces:**
- Consumes: injected Generic ExternalEffect adapter and existing Blob commands.
- Produces: verified Export Blob binding and `build_chapter_slice_evidence_manifest(...)`.

- [x] **Step 1: Extend the fixture test for upload/reconciliation evidence**

Assert export reserves a Blob, plans one project-scoped upload Effect, records a post-send UNKNOWN outcome, blocks retry in reconciliation, accepts a reconciled receipt, rejects stale fencing, replays duplicate receipt safely, verifies/binds the Blob, and only then completes Export/root.

- [x] **Step 2: Run the focused integration test and verify RED**

Run the Task 3 command.

- [x] **Step 3: Implement export delivery and the read-only evidence manifest**

Use the Generic ExternalEffect adapter/receipt/reconciliation services only. The manifest must contain root/Saga status, definitions, Operations, Attempts, output hashes, qualifications, Blob/effect/receipt states, and counts for StateEvent/Audit/Outbox without mutating runtime state.

- [x] **Step 4: Run the focused integration test and verify GREEN**

Run the Task 3 command.

### Task 5: Document, audit, and regress

**Files:**
- Modify: `docs/06-operations/postgresql-only-chapter-slice-runbook.md`
- Modify: `docs/architecture/command-kernel-authority-boundary.md`
- Modify: `docs/reports/command-kernel-authority-closure-report.md`

**Interfaces:**
- Produces: accurate implementation status, runtime command, limitations, and future production-provider migration boundary.

- [x] **Step 1: Update docs from readiness-only to implemented deterministic proof**

Keep real-provider and long-form proof explicitly unclaimed.

- [x] **Step 2: Run targeted and Authority regressions**

Run the two new test modules, `python scripts/run_authority_postgres_tests.py`, related architecture tests, `make lint`, `make validate`, `make check-skills`, and `git diff --check`.

- [x] **Step 3: Review the complete diff against AGENTS.md and the runbook**

Check for LocalStorage writes, direct SQL lifecycle mutation in behavioral tests, missing fencing, non-idempotent outputs, provider fallback, missing trace/cost evidence, and premature root success.

- [x] **Step 4: Commit implementation and documentation intentionally**

Create small commits for contracts/runtime, slice proof, and documentation/evidence.
