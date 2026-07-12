# Core OS Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a PostgreSQL-authoritative, fail-closed production kernel capable of bounded real-Codex chapter acceptance.

**Architecture:** Add an additive PostgreSQL operation/event/outbox substrate behind focused repositories and a ProductionUnitOfWork. Adapt the existing Kernel and model gateway to consume immutable context projections and completion gates without introducing another child-run state machine. Retain LocalStorage only for artifacts and explicit local/test mode.

**Tech Stack:** Python 3.12, psycopg 3, PostgreSQL, existing JSON asset schemas, unittest, Codex CLI.

## Global Constraints

- Production state authority is PostgreSQL; no silent LocalStorage fallback.
- Codex uses `CODEX_HOME=~/.codex-claude`, never API keys.
- All migrations are additive and idempotent.
- Each task adds characterization/failure tests before its implementation and commits independently.
- Real Provider and human evidence are explicitly classified; fixtures cannot satisfy them.

---

### Task 1: CI and current characterization boundary

**Files:**
- Create: `.github/workflows/core-os-ci.yml`
- Create: `tests/unit/test_core_os_characterization.py`
- Modify: `docs/reports/core-os-current-fact-map.md`

**Interfaces:**
- Produces a required commit-SHA-bound CI matrix and a characterization test suite.

- [ ] Write tests that assert current Kernel registry, production storage mode, and context prompt boundary.
- [ ] Add a CI workflow that records `${{ github.sha }}`, runs Python tests/lint/validate/skill drift and web test/build.
- [ ] Run focused tests and validate workflow YAML structurally.
- [ ] Commit `test(runtime): characterize core os baseline`.

### Task 2: PostgreSQL production operation UoW

**Files:**
- Create: `src/novel_forge/storage/production_uow.py`
- Create: `src/novel_forge/storage/production_repositories.py`
- Create: additive migration under `src/novel_forge/storage/migrations/versions/`
- Create: `tests/integration/test_production_uow_postgres.py`

**Interfaces:**
- `ProductionUnitOfWork(database_url)` atomically records operation, event, outbox, audit, and idempotency.
- Repositories provide compare-and-set lifecycle update and project-scoped reads.

- [ ] Write real PostgreSQL tests for rollback, idempotency conflict, optimistic locking, and cross-project denial.
- [ ] Add additive tables/indexes and idempotent migration.
- [ ] Implement transaction-scoped repositories and atomic commit.
- [ ] Run migration and integration tests against isolated database.
- [ ] Commit `feat(storage): add production operation unit of work`.

### Task 3: Transactional outbox and lifecycle commands

**Files:**
- Modify: `src/novel_forge/storage/production_uow.py`
- Modify: `src/novel_forge/modules/production_kernel/service.py`
- Create: `tests/integration/test_production_outbox_postgres.py`

**Interfaces:**
- Versioned lifecycle commands are idempotent and expected-version guarded.
- Outbox claim uses `FOR UPDATE SKIP LOCKED`, lease expiry and dead-letter states.

- [ ] Write concurrent claim/lease-expiry/duplicate-delivery tests.
- [ ] Implement command records, attempts, leases, and outbox consumer state transitions.
- [ ] Bind Kernel production mode to the UoW and reject unavailable PostgreSQL.
- [ ] Commit `feat(outbox): add postgres transactional outbox`.

### Task 4: ContextManifest and ProviderInputProjection

**Files:**
- Create: `src/novel_forge/modules/context_builder/provider_projection.py`
- Modify: `src/novel_forge/model_adapters/prompts.py`
- Modify: drafting/topic/world/character service call paths
- Create: `tests/unit/test_provider_input_projection.py`

**Interfaces:**
- `build_provider_input_projection()` returns immutable manifest, projection and hash within per-section budgets.
- Codex adapter accepts only a projection in production.

- [ ] Write negative tests for nested ContextBundle/retrieved context/KG leakage and cross-project refs.
- [ ] Implement deterministic compact/select/re-estimate loop and fail-closed budget behavior.
- [ ] Connect projection hash to ModelCallLog and runtime evidence.
- [ ] Commit `feat(context): add bounded provider input projection`.

### Task 5: Completion and content-validity gates

**Files:**
- Create: `src/novel_forge/modules/production_governance/completion_gate.py`
- Create: `src/novel_forge/modules/production_governance/content_validity_gate.py`
- Create: `tests/unit/test_production_completion_gate.py`

**Interfaces:**
- Completion accepts only complete evidence sets.
- Content validity evaluates real prose advancement independently of asset count.

- [ ] Add failure tests for missing evidence and non-advancing prose.
- [ ] Implement gate reports and bind them before Kernel completion.
- [ ] Commit `feat(quality): add completion and content validity gates`.

### Task 6: Story state events, reducers, snapshots and performance budgets

**Files:**
- Create: `src/novel_forge/modules/story_state/reducer.py`
- Create: `tests/integration/test_story_state_postgres.py`
- Modify: chapter/longform consumers to use project-scoped snapshot reads.

**Interfaces:**
- Event append, deterministic reduction, snapshot hash, rebuild and drift detection.

- [ ] Write replay-hash, duplicate-event and cross-project tests.
- [ ] Implement snapshot persistence and indexed reads; instrument write/scan budgets.
- [ ] Commit `feat(longform): add postgres story state reducer`.

### Task 7: Entrypoint migration and real-domain vertical slice

**Files:**
- Modify: Workflow, Agent Scheduler, Chapter Bus, legacy pipeline and operation registry.
- Modify: Topic/World/Character services and tests.
- Create: acceptance tests for single/three-chapter parent operations.

- [ ] Migrate all production creation/control paths to the Kernel boundary.
- [ ] Bind Topic/World/Character production calls to real Codex route/evidence/projection.
- [ ] Run PostgreSQL integration, Codex smoke, one chapter and three chapter acceptance.
- [ ] Commit each independently verified vertical slice.
