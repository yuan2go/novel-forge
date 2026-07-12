# PostgreSQL Command Kernel Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all production LocalStorage/JSON authority with a
PostgreSQL-only Command Kernel, authoritative domain write model, and
rebuildable PostgreSQL Read Models.

**Architecture:** Commands enter one PostgreSQL-backed Kernel and execute
registered domain handlers under short UoWs. Long-running and external work is
represented by Attempt/Lease and ExternalEffect/Dispatch, with Outbox/Inbox
result commands. Asset versions and Blob references are authoritative in
PostgreSQL; projections are explicitly non-authoritative.

**Tech Stack:** Python, psycopg/PostgreSQL, existing migration runner, Celery,
MinIO-compatible object storage, FastAPI, unittest.

## Global Constraints

- PostgreSQL write models are the only production business authority.
- No production LocalStorage import, JSON fallback, dual-write, or direct
  mutating domain-service call survives the final gate.
- UoW transactions never contain model, tool, object-store, connector, or
  publishing calls.
- All enabled OperationDefinitions require a frozen Completion Contract and
  Authority Coverage Manifest evidence.
- Use PostgreSQL integration tests for every transactional/concurrency rule.

---

## Planned file structure

| Path | Responsibility |
|---|---|
| `src/novel_forge/storage/migrations/versions/v20260712_0007_postgres_command_kernel_authority.py` | authority tables, constraints, indexes |
| `src/novel_forge/storage/authority_repositories.py` | focused write/query repositories |
| `src/novel_forge/storage/authority_uow.py` | short transaction boundary |
| `src/novel_forge/modules/command_kernel/*` | definitions, admission, lifecycle, completion, query facade |
| `src/novel_forge/modules/authority_assets/*` | AssetVersion, qualification, Blob/reference handlers |
| `src/novel_forge/modules/external_effects/*` | effect/dispatch/reconciliation handlers and workers |
| `src/novel_forge/modules/read_models/*` | projection consumers and watermark queries |
| `src/novel_forge/tools/authority_coverage_manifest.py` | build-generated manifest |
| `tests/integration/test_command_kernel_authority_*.py` | PostgreSQL authority acceptance |

### Task 1: Establish PostgreSQL authority schema and invariants

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260712_0007_postgres_command_kernel_authority.py`
- Create: `tests/integration/test_command_kernel_authority_schema.py`
- Modify: `src/novel_forge/storage/migrations/__init__.py`

**Produces:** Asset/AssetVersion/AssetQualification/Blob/AssetVersionBlobReference,
Operation/Dependency/Attempt/Lease, ExternalEffect/Dispatch, Inbox, projection
watermark, quarantine, migration-run, and release-evidence tables.

- [ ] Write integration assertions for every invariant listed in the approved design.
- [ ] Run the test against the isolated PostgreSQL database; verify it fails before migration.
- [ ] Add the migration using check constraints, foreign keys and partial unique indexes for active Attempt and ACTIVE AssetVersion.
- [ ] Run migration status and the integration test; verify all constraints reject invalid writes.
- [ ] Commit `feat(storage): add command kernel authority schema`.

### Task 2: Build short-UoW repositories and Kernel admission

**Files:**
- Create: `src/novel_forge/storage/authority_repositories.py`
- Create: `src/novel_forge/storage/authority_uow.py`
- Create: `src/novel_forge/modules/command_kernel/definitions.py`
- Create: `src/novel_forge/modules/command_kernel/service.py`
- Create: `tests/integration/test_command_kernel_admission.py`

**Consumes:** Task 1 schema. **Produces:** `admit(command) -> Operation`,
idempotency replay/rejection, immutable definition/contract snapshots, state
event/audit/outbox atomic creation.

- [ ] Test same-key/same-digest replay and same-key/different-digest rejection.
- [ ] Test that admission commits operation, idempotency, event, audit and Outbox together, or rolls all back.
- [ ] Implement repositories and explicit `commit()` UoW; prohibit external executor dependencies in this package.
- [ ] Register the five existing definitions as a characterization starting point, then require all definitions to be explicit.
- [ ] Run targeted integration tests and commit `feat(kernel): add postgres command admission`.

### Task 3: Implement lifecycle, Attempt, Lease and cancellation protocol

**Files:**
- Create: `src/novel_forge/modules/command_kernel/lifecycle.py`
- Create: `src/novel_forge/modules/command_kernel/attempts.py`
- Create: `tests/integration/test_command_kernel_attempts.py`

**Produces:** CAS lifecycle commands, one-active-Attempt enforcement, monotonic
fencing, late-result rejection, versioned cancellation and dead-letter rules.

- [ ] Test every approved Operation/Attempt/Lease transition and illegal transition rejection.
- [ ] Test concurrent lease acquisition and a stale worker result after lease expiry.
- [ ] Implement token-checked checkpoint/result commands and cancellation that creates reconciliation/compensation work when required.
- [ ] Run PostgreSQL concurrency tests and commit `feat(kernel): add attempts leases and cancellation`.

### Task 4: Implement authoritative assets, qualifications and Blob protocol

**Files:**
- Create: `src/novel_forge/modules/authority_assets/service.py`
- Create: `src/novel_forge/modules/authority_assets/blob_worker.py`
- Create: `tests/integration/test_authority_assets_and_blobs.py`
- Modify: `src/novel_forge/storage/object_store.py`

**Produces:** immutable AssetVersions/references, independent lifecycle/
eligibility/governance fields, qualification evidence, upload intent, verified
Blob availability, corruption and reference-safe deletion.

- [ ] Test only ACTIVE+ELIGIBLE+CLEAR assets can satisfy a production contract.
- [ ] Test hash/size mismatch produces CORRUPT; test Blob delete rejection for asset/audit/release/provider/legal-hold references.
- [ ] Implement object-store calls only in the worker, with result commands returning to Kernel.
- [ ] Run integration tests and commit `feat(assets): add authoritative versions and blobs`.

### Task 5: Implement ExternalEffect, Outbox and transactional Inbox

**Files:**
- Create: `src/novel_forge/modules/external_effects/service.py`
- Create: `src/novel_forge/modules/external_effects/dispatcher.py`
- Create: `src/novel_forge/modules/read_models/consumer.py`
- Create: `tests/integration/test_external_effects_and_inbox.py`
- Modify: `src/novel_forge/storage/production_repositories.py`

**Produces:** logical effects, immutable dispatch generations, receipt handling,
UNKNOWN reconciliation, outbox claiming, payload-hash Inbox dedup and alerts.

- [ ] Test duplicate delivery is idempotent, while same message ID/different hash alerts and rejects.
- [ ] Test retry generation is blocked after UNKNOWN unless reconciliation or provider idempotency evidence permits it.
- [ ] Implement dispatch outside UoW and result/receipt commands inside UoW.
- [ ] Run integration tests and commit `feat(runtime): add effects dispatch and inbox`.

### Task 6: Add operation graph, Saga and Completion Contract enforcement

**Files:**
- Create: `src/novel_forge/modules/command_kernel/saga.py`
- Create: `src/novel_forge/modules/command_kernel/completion.py`
- Create: `tests/integration/test_command_kernel_completion.py`

**Produces:** parent/root/causation/workflow/saga/step/dependency control and
Completion Contract evaluation that does not wait for projections.

- [ ] Test Review/Revision/Canon as child Operations rather than special Operation statuses.
- [ ] Test a missing asset qualification, gate, audit/cost evidence, terminal effect, or Outbox prevents completion.
- [ ] Implement parent/child dependency transitions and compensating children.
- [ ] Run tests and commit `feat(kernel): enforce sagas and completion contracts`.

### Task 7: Replace domain persistence and create PostgreSQL query/read models

**Files:**
- Create: `src/novel_forge/modules/read_models/service.py`
- Modify: `src/novel_forge/api/services/product.py`
- Modify: `src/novel_forge/api/app.py`
- Modify: all mutating `src/novel_forge/modules/**/service.py` and matching API routers identified by the Coverage Manifest generator
- Create: `tests/integration/test_postgres_read_models.py`

**Produces:** authoritative repository-backed handlers and PostgreSQL
projections/watermarks; no production LocalStorage access.

- [ ] Start with a static inventory of every mutating symbol, assign an OperationDefinition, then make the test fail for any unassigned symbol.
- [ ] Replace each service's LocalStorage write/read authority with a domain repository and typed Kernel handler.
- [ ] Route pure reads to write-model queries or read models according to consistency requirement.
- [ ] Test read-your-writes from write models and pending/minimum-watermark behavior from projections.
- [ ] Commit domain migrations in bounded family-focused commits, preserving the complete coverage inventory after each commit.

### Task 8: Rewire API, CLI, workflows, workers and scheduler

**Files:**
- Modify: `src/novel_forge/api/routers/*.py`
- Modify: `src/novel_forge/cli/__init__.py`
- Modify: `src/novel_forge/workers/tasks.py`, `runtime.py`, `dispatch.py`
- Modify: `src/novel_forge/workflows/pipeline.py`, `industrial.py`, `status.py`
- Modify: `src/novel_forge/modules/agent_scheduler/*.py`, `workflow_nodes/*.py`, `loop_kernel/service.py`
- Create: `tests/integration/test_authority_entrypoints_e2e.py`

**Produces:** adapters that only submit Kernel commands; workers that only
claim Outbox work and submit fenced result commands.

- [ ] Characterize every existing production/governance route and worker task as command or query.
- [ ] Replace direct mutating service calls with typed Kernel adapters; retain pure GET queries outside Kernel.
- [ ] Replace Celery post-task sync with Attempt/ExternalEffect execution and result commands.
- [ ] Run API/CLI/worker/scheduler E2E tests for all enabled definitions.
- [ ] Commit `refactor(runtime): route all side effects through command kernel`.

### Task 9: Implement frozen-snapshot migration and Quarantine

**Files:**
- Create: `src/novel_forge/tools/import_frozen_json_snapshot.py`
- Create: `src/novel_forge/modules/migration_quarantine/service.py`
- Create: `tests/integration/test_frozen_snapshot_import.py`
- Modify: `src/novel_forge/workflows/industrial.py`

**Produces:** optional, read-only JSON importer with content-hash validation,
selective asset migration, Quarantine evidence and critical-failure gate.

- [ ] Test fixtures/caches/failed residue are skipped and valid meaningful assets preserve identity/lineage.
- [ ] Test malformed/cross-project/hash-invalid input is quarantined; identity/lineage-breaking input blocks release.
- [ ] Implement importer as an explicit offline command with no production runtime dependency.
- [ ] Run migration integration tests and commit `feat(migration): import frozen snapshot into authority model`.

### Task 10: Generate and enforce Authority Coverage Manifest

**Files:**
- Create: `src/novel_forge/tools/authority_coverage_manifest.py`
- Create: `tests/unit/test_authority_coverage_manifest.py`
- Create: `tests/architecture/test_no_production_localstorage.py`
- Modify: CI workflow files and release validation scripts

**Produces:** canonical immutable manifest, artifact hash, PostgreSQL
ReleaseEvidence record, static bypass/unknown-path failure.

- [ ] Test the generator finds direct mutating service calls, LocalStorage imports, unregistered routes and unbound consumers.
- [ ] Implement AST/registry/runtime/E2E evidence aggregation and canonical JSON hash.
- [ ] Fail CI and release when unknown paths or bypasses are nonzero.
- [ ] Commit `feat(verification): enforce authority coverage manifest`.

### Task 11: Remove LocalStorage authority, fallbacks and dual-write code

**Files:**
- Delete or move: `src/novel_forge/storage/local.py` production implementation
- Delete: `src/novel_forge/api/services/postgres_fallback_policy.py`
- Modify/delete: `src/novel_forge/storage/postgres.py`, `workers/runtime.py`, `workflows/industrial.py`, `infrastructure/settings.py`
- Modify: tests importing LocalStorage to use PostgreSQL fixtures
- Create: `tests/integration/test_postgresql_only_runtime.py`

**Produces:** production image/configuration that cannot instantiate local JSON
authority, synchronize from it, or fall back to it.

- [ ] Make production configuration fail without PostgreSQL/object storage and fail if legacy settings are supplied.
- [ ] Remove sync/write-through/strict-local modes and legacy fallback tests.
- [ ] Retain only isolated test-fixture/frozen-import code with architecture-layer protection.
- [ ] Run full test matrix and commit `refactor(storage): remove local production authority`.

### Task 12: Run release acceptance and create the PostgreSQL-only baseline

**Files:**
- Create: `docs/reports/postgresql-authority-release-evidence.json`
- Modify: `TESTING.md`, deployment/configuration documentation
- Test: all unit, PostgreSQL integration, architecture and E2E suites

**Produces:** immutable release evidence linking migration version, Coverage
Manifest hash, E2E results, projection rebuild, recovery drills and backup
restore validation.

- [ ] Run full migration on a clean database and run optional frozen-snapshot import on a copy.
- [ ] Run coverage generator; require zero bypasses and zero unknown write paths.
- [ ] Run reconciliation, lease-loss, late-result, external UNKNOWN,
compensation, Inbox mismatch, Blob corruption/delete, and projection rebuild drills.
- [ ] Verify production image contains no LocalStorage authority path or JSON fallback configuration.
- [ ] Commit `docs: record postgresql-only authority release evidence`.
