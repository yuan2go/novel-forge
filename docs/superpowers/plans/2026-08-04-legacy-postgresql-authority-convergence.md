# Legacy to PostgreSQL Authority Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PostgreSQL the fail-closed backend authority, convert frozen Legacy records into native typed AssetVersions, provide a complete backend Compose plane, and bind the resulting engineering evidence to the exact tested HEAD.

**Architecture:** Extend the existing PostgreSQL Command Kernel, fenced Attempt runtime, AssetVersion store, projections, audit, and outbox. Legacy remains an explicit frozen-snapshot import or development compatibility profile; the default API, CLI, workers, and Compose plane never use LocalStorage as authority or fallback. A process-local psycopg3 pool registry supplies short transaction scopes and bounded SQLSTATE retries.

**Tech Stack:** Python 3.12, psycopg3 and psycopg_pool, PostgreSQL 16/pgvector, FastAPI, Docker Compose, unittest, existing Novel Forge Command Kernel.

## Global Constraints

- No Web page implementation.
- No real-provider, real-novel, long-form-quality, multi-book, or production proof claims.
- PostgreSQL failures fail closed; there is no silent Legacy fallback and no permanent dual write.
- Existing published migrations keep their historical meaning; schema changes use new forward migrations.
- Frozen snapshot imports are hash-addressed, resumable, replay-safe, reconciled, and quarantine unsafe records with evidence.
- Provider calls and object-store uploads never execute while a database transaction is held.

---

### Task 1: Current-tree Legacy inventory and plan

**Files:**
- Modify: `src/novel_forge/tools/legacy_authority_migration_inventory.py`
- Modify: `tests/unit/test_legacy_authority_migration_inventory.py`
- Modify: `docs/reports/legacy-authority-migration-inventory.json`
- Modify: `docs/reports/legacy-authority-migration-inventory.md`

**Interfaces:**
- Consumes: `authority_coverage_manifest.build_manifest(repo_root)` and exact source evidence.
- Produces: inventory schema v2 with `domain`, `file`, `symbol`, `entrypoint`, `read_or_write`, `current_authority`, `target_authority`, `production_reachable`, `migration_strategy`, `status`, `evidence`, and `remaining_action`.

- [ ] Write tests requiring the v2 fields, allowed status enum, deterministic artifact hash, and zero `LEGACY_PRODUCTION_BLOCKER`/`UNCLASSIFIED` only when no Authority entrypoint finding violates the explicit boundary.
- [ ] Implement exact entrypoint/path classification; do not use a directory-wide production exemption.
- [ ] Regenerate JSON and Markdown from the current source-tree hash.
- [ ] Run `PYTHONPATH=src .venv/bin/python -m unittest -v tests.unit.test_legacy_authority_migration_inventory tests.architecture.test_postgresql_authority_production_boundary`.
- [ ] Commit the inventory, plan, tests, and generated reports.

### Task 2: Typed native migration codecs and lifecycle

**Files:**
- Create: `src/novel_forge/modules/legacy_migration/codecs.py`
- Modify: `src/novel_forge/modules/legacy_migration/application.py`
- Modify: `src/novel_forge/modules/legacy_migration/definitions.py`
- Modify: `src/novel_forge/modules/legacy_migration/service.py`
- Create: `src/novel_forge/storage/migrations/versions/v20260804_0055_legacy_native_conversion.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Create: `tests/unit/test_legacy_migration_codecs.py`
- Modify: `tests/integration/test_authority_legacy_migration_postgres.py`

**Interfaces:**
- Consumes: `LegacySnapshotRecord` plus frozen snapshot and record hashes.
- Produces: `TypedMigrationCodecRegistry.resolve(source_type)`, native `AuthorityHandlerOutput`, per-item phase/codec/reconciliation evidence, and quarantine records.

- [ ] Write registry tests for supported production asset families, stable identity, scope/reference validation, native content conversion, activation policy, unsupported types, and large-object quarantine metadata.
- [ ] Add forward schema columns and indexes for migration phase, codec identity, native target type/hash, reconciliation evidence, and original quarantine evidence.
- [ ] Replace the generic candidate handler with one frozen operation definition/registration per typed codec.
- [ ] Persist `SCAN -> CLASSIFY -> IMPORT_CANDIDATE -> SEMANTIC_CONVERT -> VALIDATE -> QUALIFY -> ACTIVATE|QUARANTINE -> RECONCILE` evidence and resume checkpoints.
- [ ] Reconcile source hash, counts, identities, references, AssetVersion, qualification, activation, operation, audit, and outbox without creating duplicate versions on replay.
- [ ] Run unit and PostgreSQL migration/import tests, then commit.

### Task 3: Fail-closed backend cutover and architecture gates

**Files:**
- Modify: `src/novel_forge/infrastructure/settings.py`
- Modify: `src/novel_forge/api/app.py`
- Modify: `src/novel_forge/cli/__init__.py`
- Modify: `.env.example`
- Modify: `Makefile`
- Create: `tests/architecture/test_legacy_production_reachability.py`
- Modify: `tests/unit/test_postgresql_authority_api_boundary.py`
- Modify: `tests/unit/test_postgresql_authority_cli_boundary.py`

**Interfaces:**
- Consumes: explicit `legacy` CLI/profile request only.
- Produces: PostgreSQL defaults for development/production, explicit Legacy compatibility entry, and AST/config gates for fallback/dual-write/direct LocalStorage production imports.

- [ ] Write failing tests for PostgreSQL defaults, explicit Legacy command, production Legacy rejection, no default fallback, no unapproved dual write, codec coverage, and inventory zero blockers.
- [ ] Change settings/CLI/Make defaults and keep migration scanner/import commands Authority-backed.
- [ ] Run focused architecture/unit tests and commit.

### Task 4: Complete Authority backend Compose and operational readiness

**Files:**
- Create: `compose.yml`
- Create: `compose.override.yml`
- Create: `compose.legacy.yml`
- Modify: `compose.authority-only.yml`
- Modify: `Dockerfile`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `src/novel_forge/storage/worker_health.py`
- Modify: `src/novel_forge/modules/command_kernel/worker_execution.py`
- Modify: Authority worker entrypoints under `src/novel_forge/workers/`
- Create: `scripts/verify_authority_compose.py`
- Create: `tests/unit/test_authority_compose_contract.py`

**Interfaces:**
- Consumes: migration head, object-store probe, operation definitions, runtime-group registration, provider mode, and worker health projection.
- Produces: `/liveness`, `/startup`, `/readiness`, worker drain/counter evidence, and an automated empty-volume/restart/recovery smoke report.

- [ ] Add Compose contract tests for complete default backend services and an explicit Legacy profile only.
- [ ] Add one-shot migration dependency, runtime groups, bounded concurrency/connection budgets, health checks, restart/stop/resource/log/read-only/non-root controls.
- [ ] Add readiness probes and provider `BLOCKED`/fixture evidence boundary.
- [ ] Add graceful worker drain and pool shutdown hooks.
- [ ] Run Compose config validation and smoke when Docker is available, then commit.

### Task 5: Unified database runtime and transaction governance

**Files:**
- Create: `src/novel_forge/storage/database_runtime.py`
- Modify: `src/novel_forge/storage/authority_uow.py`
- Modify: `src/novel_forge/storage/production_uow.py`
- Modify: direct Authority psycopg callers found by the architecture scan
- Modify: `pyproject.toml`
- Create: `tests/unit/test_database_runtime.py`
- Create: `tests/integration/test_database_runtime_postgres.py`
- Create: `tests/architecture/test_database_runtime_boundary.py`

**Interfaces:**
- Produces: `DatabaseRuntime`, `ConnectionPoolRegistry`, `TransactionExecutor`, `DatabaseHealthProbe`, role budgets, pool/transaction/retry metrics, and `close_all_database_runtimes()`.

- [ ] Add official psycopg pool dependency and tests for pool reuse, bounded exhaustion, session parameters, SQLSTATE classification, idempotency-required retries, business-conflict rejection, and metrics.
- [ ] Route Authority/Production UoWs and direct Authority query adapters through the shared pool; leave only migration runner and documented maintenance/import paths allowlisted.
- [ ] Enforce statement/lock/idle-transaction timeouts, application name, timezone, search path, rollback/return, connection leak detection, and total-budget validation.
- [ ] Add PostgreSQL tests for timeout, deadlock/serialization retry, restart recovery, drain/close, and no transaction across provider calls.
- [ ] Run focused unit/integration/architecture tests and commit.

### Task 6: Exact-HEAD regression evidence and documentation

**Files:**
- Create: `docs/reports/current-head-sha-baseline.json`
- Create: `docs/reports/current-head-sha-baseline.md`
- Create: `docs/reports/native-migration-codec-registry.md`
- Create: `docs/architecture/authority-runtime-architecture.md`
- Create: `docs/runbooks/authority-compose.md`
- Create: `docs/adr/0004-database-connection-and-transaction-governance.md`
- Create: `docs/reports/database-connection-budget.md`
- Create: `docs/reports/authority-failure-and-recovery-matrix.md`
- Modify: `docs/project-current-state.md`

**Interfaces:**
- Consumes: a committed, clean migration/cutover/runtime HEAD and freshly executed command evidence.
- Produces: SHA-bound machine-readable and human-readable baseline with evidence levels and explicit unproved fields.

- [ ] Run compile, formatting/lint/type checks available in this repository, architecture/manifests, focused unit/contract suites, clean PostgreSQL migration/integration tests, FK-index audit, Compose config/smoke, and fault injection.
- [ ] Commit code/docs except the final SHA baseline, verify the worktree is clean, capture the new HEAD, and rerun the final matrix on that exact SHA.
- [ ] Generate baseline artifacts with command counts/durations/skips/failures and `real_provider_proven=false`, `longform_proven=false`, `multi_book_proven=false`, `production_verified=false`.
- [ ] Commit evidence documents only when their `commit_sha` accurately identifies the code-under-test SHA; record the evidence-commit SHA separately to avoid circular self-reference.
- [ ] Run `git diff --cached --check`, final status/HEAD commands, and commit the final evidence update.
