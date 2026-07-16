# LocalStorage Authority Hard Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every production LocalStorage/JSON authority path with PostgreSQL Command Kernel commands, authoritative asset versions, controlled external effects, and rebuildable PostgreSQL projections.

**Architecture:** Preserve the approved whole-system hard-cutover decision in `docs/superpowers/specs/2026-07-12-postgresql-command-kernel-authority-design.md`. Development proceeds in dependency-ordered slices behind a non-production cutover boundary, but the release gate permits no production dual write, JSON fallback, direct mutating service entrypoint, or LocalStorage import. Existing domain algorithms are extracted behind typed input/output ports; Command Kernel handlers alone materialize state, asset versions, evidence, and outbox records.

**Tech Stack:** Python 3.12, frozen/slots dataclasses, PostgreSQL 16, psycopg 3, JSONB, Command Kernel Operation/Attempt/Completion/Saga protocols, transactional Inbox/Outbox, Generic ExternalEffect, unittest, Ruff, mypy.

## Global Constraints

- Preserve the user-owned `.idea/novel-forge.iml` modification and all unrelated worktree changes.
- PostgreSQL is the sole production command authority after cutover; `nf_*` tables are projection-only.
- LocalStorage may exist only in isolated tests and the explicit read-only frozen-snapshot importer.
- No production dual write, fallback, best-effort persistence, direct lifecycle SQL, or silent exception suppression.
- Every mutation enters an enabled, versioned OperationDefinition and produces StateEvent, AuditLog, and Outbox evidence in the authority transaction.
- Asset completion evidence is operation-scoped and version-specific; historical project assets cannot satisfy a current operation.
- Model, object-store, connector, and publisher calls execute outside the PostgreSQL transaction and return through fenced result or receipt commands.
- Reruns create new Attempt/Operation/version records; immutable accepted assets are never edited in place.
- Production requires an explicit PostgreSQL DSN and object-store configuration and fails closed when legacy settings are supplied.

---

### Task 1: Add the authoritative asset document port and logical locator

**Files:**
- Create: `src/novel_forge/storage/authority_asset_store.py`
- Create: `src/novel_forge/modules/command_kernel/asset_commands.py`
- Create: `src/novel_forge/storage/migrations/versions/v20260716_0022_authority_asset_locator.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `src/novel_forge/storage/migrations/__init__.py`
- Modify: `src/novel_forge/storage/asset_blob_repositories.py`
- Test: `tests/integration/test_authority_asset_store_postgres.py`
- Test: `tests/unit/test_authority_asset_locator.py`

**Interfaces:**
- Consumes: `AuthorityUnitOfWork`, `authority_asset`, `authority_asset_version`, `authority_asset_qualification`, `authority_operation_output_asset`.
- Produces: `AuthorityAssetRef`, `AuthorityAssetDocument`, `AuthorityAssetQuery`, `AuthorityAssetWriter.materialize_output(...)`, and project-scoped logical locator rows.

- [ ] Write tests proving project-scoped locator uniqueness, immutable version creation, optimistic expected-version rejection, read-your-writes, current-version lookup, category/type/project listing, and cross-project reference rejection.
- [ ] Add `authority_asset_locator(project_id, logical_ref, category, asset_id, current_asset_version_id, created_at, updated_at)` with foreign keys and indexes for `(project_id, category, updated_at DESC)` and `(project_id, asset_id)`.
- [ ] Implement typed document reads that return JSON content plus immutable identity/version/hash metadata without materializing filesystem paths.
- [ ] Implement writes only as an admitted Operation output; require `operation_id`, `project_id`, expected current version, lifecycle, eligibility, governance, output key, role, trace, and event metadata.
- [ ] Use `SELECT ... FOR UPDATE` on the locator/current asset row and content-derived SHA-256 identity; reject stale writes with `AUTHORITY_ASSET_VERSION_CONFLICT`.
- [ ] Run `python -m unittest tests.unit.test_authority_asset_locator` and the targeted PostgreSQL integration test.
- [ ] Commit `feat(storage): add authoritative asset document store`.

### Task 2: Convert the chapter production algorithms into storage-free handler ports

**Files:**
- Create: `src/novel_forge/modules/chapter_authority/domain_handlers.py`
- Create: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/runtime.py`
- Modify: `src/novel_forge/modules/chapter_plan/service.py`
- Modify: `src/novel_forge/modules/context_builder/service.py`
- Modify: `src/novel_forge/modules/drafting/service.py`
- Modify: `src/novel_forge/modules/review/service.py`
- Modify: `src/novel_forge/modules/revision/service.py`
- Modify: `src/novel_forge/modules/canon_graph/service.py`
- Modify: `src/novel_forge/modules/publishing/service.py`
- Test: `tests/unit/test_chapter_authority_domain_handlers.py`
- Test: `tests/integration/test_postgresql_only_chapter_domain_handlers.py`

**Interfaces:**
- Consumes: `AuthorityAssetQuery`, typed chapter node commands, ContextBundle and KnowledgePack version references, `ModelEffectPort`.
- Produces: storage-free `ChapterNodeResult` values and explicit model/external-effect intents; persistence remains owned by `ChapterAuthorityRuntime`.

- [ ] Characterize the existing ChapterPlan, ContextBundle, Draft, Review, Revision, Canon, Quality, and Export behavior with deterministic tests using authoritative input documents.
- [ ] Extract pure normalization, validation, gate, and payload-building functions from legacy services; they accept dictionaries/dataclasses and never receive a storage object.
- [ ] Represent model generation as a versioned ExternalEffect intent with provider/runtime profile, prompt/skill versions, token/cost ceilings, input hashes, and completion policy.
- [ ] Submit model results through the existing fenced Attempt/result path; record ModelCallLog and CostLedger evidence before completion.
- [ ] Replace in-place JSON edits with new AssetVersions bound to the current Operation.
- [ ] Run unit tests, one deterministic PostgreSQL-only chapter, and one mocked model-effect success/failure/retry scenario.
- [ ] Commit `refactor(chapter): run production handlers on postgres authority`.

### Task 3: Migrate production control-plane domains

**Files:**
- Create: `src/novel_forge/modules/authority_handlers/control_plane.py`
- Create: `src/novel_forge/modules/read_models/authority_queries.py`
- Modify: `src/novel_forge/modules/production_kernel/`
- Modify: `src/novel_forge/modules/production_chain/`
- Modify: `src/novel_forge/modules/chapter_production_bus/`
- Modify: `src/novel_forge/modules/agent_registry/`
- Modify: `src/novel_forge/modules/agent_runs/`
- Modify: `src/novel_forge/modules/agent_scheduler/`
- Modify: `src/novel_forge/modules/loop_kernel/`
- Modify: `src/novel_forge/modules/workflow_nodes/`
- Modify: `src/novel_forge/modules/permission_center/`
- Modify: `src/novel_forge/modules/runtime_ledger/`
- Test: `tests/integration/test_postgresql_authority_control_plane.py`

**Interfaces:**
- Consumes: Command Kernel admission/lifecycle, Saga coordinator, authoritative assets, Inbox/Outbox.
- Produces: PostgreSQL-only WorkflowRun/AgentRun/LoopRun/control commands and projection events.

- [ ] Register and execute typed definitions for every mapped control-plane mutation in the current coverage catalog.
- [ ] Replace LocalStorage queue/lease/checkpoint/gate/dead-letter state with Operation, Attempt, Lease, Saga, and authoritative evidence.
- [ ] Make legacy `ProductionOperation`, AgentRun, WorkflowRun, LoopRun, and ChapterProductionRun query-only projections keyed to authority operation IDs.
- [ ] Add bounded budget/SLA/provider hard-stop, cancellation, retry, dead-letter, resume, and rollback tests without direct lifecycle SQL.
- [ ] Commit `refactor(runtime): move production control plane to command kernel`.

### Task 4: Migrate content, governance, knowledge, and publishing domains

**Files:**
- Create: `src/novel_forge/modules/authority_handlers/content_domains.py`
- Modify: all mutating services under `src/novel_forge/modules/` reported by `authority_coverage_manifest.py`
- Modify: `src/novel_forge/modules/source_intake/`
- Modify: `src/novel_forge/modules/mkaos/`
- Modify: `src/novel_forge/modules/novel_kg/`
- Modify: `src/novel_forge/modules/continuity_graph/`
- Modify: `src/novel_forge/modules/review_issue/`
- Modify: `src/novel_forge/modules/feedback/`
- Modify: `src/novel_forge/modules/publishing/`
- Test: `tests/integration/test_postgresql_authority_domain_families.py`

**Interfaces:**
- Consumes: authoritative asset document port, domain-specific OperationDefinitions, Generic ExternalEffect.
- Produces: immutable project-scoped asset versions, effective qualifications, story-state transitions, review issues, source governance, feedback, and publishing effects.

- [ ] Migrate one catalog family at a time and regenerate coverage after each family; no mapped write may remain on LocalStorage.
- [ ] Preserve source isolation, copyright lineage, effective qualification, Canon/StoryState current tables plus append-only events, review/revision gates, and publishing receipt semantics.
- [ ] Route vector/search/analytics updates through Outbox projections; they cannot block or decide command completion.
- [ ] Add cross-project, stale-version, revoked-qualification, missing-evidence, and projection-lag tests per family.
- [ ] Commit bounded family-focused commits with regenerated coverage evidence.

### Task 5: Rewire every adapter and enforce zero bypasses

**Files:**
- Modify: `src/novel_forge/api/app.py`
- Modify: `src/novel_forge/api/routers/*.py`
- Modify: `src/novel_forge/api/services/*.py`
- Modify: `src/novel_forge/cli/__init__.py`
- Modify: `src/novel_forge/workers/*.py`
- Modify: `src/novel_forge/workflows/*.py`
- Modify: `src/novel_forge/tools/authority_coverage_manifest.py`
- Modify: `tests/architecture/test_authority_coverage_baseline.py`
- Create: `tests/architecture/test_no_production_localstorage.py`
- Create: `tests/integration/test_authority_entrypoints_e2e.py`

**Interfaces:**
- Consumes: typed command/query application facade.
- Produces: API/CLI/worker/scheduler/callback adapters with no direct domain writes.

- [ ] Classify every public entrypoint as command or query and bind every command to a versioned enabled definition.
- [ ] Replace app-global LocalStorage construction with required PostgreSQL authority/query dependencies.
- [ ] Make workers consume Outbox work and return fenced results; remove post-task PostgreSQL synchronization.
- [ ] Extend AST architecture checks to fail on production LocalStorage imports, direct mutating service calls, JSON fallback settings, unbound callbacks, and projection writes used as authority.
- [ ] Require coverage summary `unknown=0`, `unmapped_side_effects=0`, `fallback=0`, `sync=0`, and no production LocalStorage imports.
- [ ] Commit `refactor(entrypoints): enforce postgres command authority`.

### Task 6: Import the frozen LocalStorage snapshot with quarantine

**Files:**
- Create: `src/novel_forge/tools/import_frozen_json_snapshot.py`
- Create: `src/novel_forge/modules/migration_quarantine/service.py`
- Test: `tests/integration/test_frozen_snapshot_import.py`
- Modify: `docs/06-operations/postgresql-authority-migration-runbook.md`

**Interfaces:**
- Consumes: read-only snapshot root, authoritative asset writer, migration/quarantine tables.
- Produces: idempotent migration run, imported asset versions, quarantine evidence, and signed summary.

- [ ] Refuse writable snapshot mounts and record snapshot tree hash before reading records.
- [ ] Import only meaningful project assets with valid identity, project scope, content hash, references, and lineage.
- [ ] Skip rebuildable projections/caches and quarantine malformed, cross-project, hash-invalid, missing-reference, or policy-invalid records with explicit reason codes.
- [ ] Make identity/lineage-breaking critical violations fail the cutover gate; allow noncritical quarantine only when the signed report enumerates every row.
- [ ] Test rerun idempotency, crash/resume, quarantine, and transaction rollback.
- [ ] Commit `feat(migration): import frozen local snapshot`.

### Task 7: Remove production LocalStorage and legacy PostgreSQL synchronization

**Files:**
- Move or restrict: `src/novel_forge/storage/local.py`
- Delete: `src/novel_forge/api/services/postgres_fallback_policy.py`
- Refactor: `src/novel_forge/storage/postgres.py`
- Modify: `src/novel_forge/infrastructure/settings.py`
- Modify: `src/novel_forge/storage/__init__.py`
- Modify: tests importing LocalStorage
- Test: `tests/integration/test_postgresql_only_runtime.py`

**Interfaces:**
- Consumes: PostgreSQL authority DSN and object-store configuration.
- Produces: a production runtime that cannot instantiate JSON authority, dual-write, or fallback.

- [ ] Keep LocalStorage only under an import boundary reachable by isolated fixtures and the frozen importer; production import tests must reject it.
- [ ] Remove `PostgresAssetStore.sync_from_local`, `sync_asset`, post-task sync, write-through/strict-local flags, and fallback modes.
- [ ] Fail startup without PostgreSQL/object-store configuration and fail on any supplied legacy authority setting.
- [ ] Convert remaining tests to PostgreSQL fixtures except explicit local-fixture/importer tests.
- [ ] Commit `refactor(storage): remove local production authority`.

### Task 8: Prove and document the PostgreSQL-only release baseline

**Files:**
- Create: `docs/reports/postgresql-authority-release-evidence.json`
- Create: `docs/reports/localstorage-authority-hard-cutover-report.md`
- Modify: `docs/project-current-state.md`
- Modify: `docs/architecture/command-kernel-authority-boundary.md`
- Modify: `TESTING.md`

**Interfaces:**
- Consumes: migrations, coverage/catalog artifacts, test evidence, recovery drills, projection rebuild, backup/restore evidence.
- Produces: HEAD-bound release evidence and an accurate authority declaration.

- [ ] Run clean-database migrations, frozen-snapshot import on a copy, targeted domain suites, authority PostgreSQL suite, full unit/integration/architecture suites, lint, validate, skills check, and diff check.
- [ ] Run lease-loss, late-result, cancellation, external UNKNOWN, reconciliation, compensation, Inbox mismatch, Blob corruption/delete, projection rebuild, and backup/restore drills.
- [ ] Regenerate the coverage baseline/catalog/action map at final HEAD and require zero bypasses, unknown writes, fallbacks, sync paths, and production LocalStorage imports.
- [ ] Record commands, counts, failures/skips, migration IDs, artifact hashes, quarantine counts, and residual non-authority local fixture usage.
- [ ] Commit `docs: establish postgresql-only authority baseline` and leave the worktree clean except explicitly preserved user changes.

