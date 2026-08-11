# Authority Runtime Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the interactive Legacy runtime, establish independent Production Execution ownership, restore Book authority boundaries, and reconstruct current-code documentation without adding a new execution plane.

**Architecture:** Preserve PostgreSQL Authority, Command Kernel, PEP, Attempt, ExternalEffect, RuntimeJob, and domain authority semantics. Delete the Legacy-only import closure, introduce one concrete process-scoped `ProductionExecutionComposition`, and move Book coordination reads/mutations behind concrete query and existing command boundaries.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL/psycopg, Docker Compose, pytest, Ruff, Node test runner, YAML/JSON architecture manifests.

## Global Constraints

- Baseline is `449c201b1dd4b9bd939bfe9bd0441926b50c4cce` on `refactor/authority-runtime-convergence`.
- Retained Legacy capability is `MIGRATION_ONLY`: snapshot schema/codec/parser/validator/mapper/import/status/verify/quarantine.
- Production API, workers, composition, and Command Kernel must not depend on migration-only modules.
- Do not add Compatibility Runtime, fallback, second scheduler, second state machine, service locator, generic repository framework, or speculative interface.
- Do not redesign Command Kernel, Operation/Saga, Attempt, Lease/Fence, ExternalEffect, RuntimeJob, Provider Runtime, narrative state, planning semantics, or long-form business behavior.
- Fixture evidence must not be described as real-provider or production proof.
- Existing PostgreSQL migrations are immutable.

---

### Task 1: Lock the migration-only boundary with executable architecture rules

**Files:**

- Create: `architecture/manifests/migration-surface-manifest.yaml`
- Create: `tests/architecture/test_migration_surface_boundary.py`
- Modify: `src/novel_forge/tools/architecture_fitness.py`
- Modify: `architecture/manifests/fitness-policy.yaml`
- Modify: `architecture/manifests/module-manifest.yaml`
- Modify: `architecture/manifests/console-script-manifest.yaml`
- Modify: `architecture/manifests/legacy-surface-manifest.yaml` (remove after replacement is enforced)
- Modify: `tests/architecture/test_architecture_fitness.py`
- Modify: `tests/architecture/test_architecture_manifests.py`
- Modify: `tests/architecture/test_legacy_surface_manifest.py` (replace with migration-boundary coverage)

**Interfaces:**

- Consumes: production roots from `fitness-policy.yaml` and the existing AST import graph.
- Produces: a manifest containing exact migration roots, allowed dependencies, forbidden runtime registrations, and retired path assertions.

- [ ] **Step 1: Add failing boundary tests**

Assert that production roots have zero paths to `novel_forge.modules.legacy_migration`, that migration modules cannot import API/Worker/PEP execution entrypoints, and that retired paths such as `api/legacy_app.py`, `storage/local.py`, `modules/agent_scheduler`, `modules/production_kernel`, and `compose.legacy.yml` do not exist.

- [ ] **Step 2: Run the tests and confirm the current tree fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/architecture/test_migration_surface_boundary.py tests/architecture/test_architecture_fitness.py -q`

Expected: failure because the manifest/rules do not exist and retired paths remain.

- [ ] **Step 3: Implement manifest parsing and graph checks**

Use concrete policy keys:

```json
{
  "migration_roots": ["src/novel_forge/modules/legacy_migration"],
  "production_forbidden_import_roots": ["novel_forge.modules.legacy_migration"],
  "migration_forbidden_import_roots": [
    "novel_forge.api",
    "novel_forge.workers",
    "novel_forge.modules.production_execution"
  ]
}
```

The actual manifest also lists the retained CLI migration entry and retired paths. Reuse the existing AST graph; do not add a second dependency analyzer.

- [ ] **Step 4: Run focused architecture checks**

Run: `make architecture-manifests-check && make architecture-fitness-check`

Expected: checks remain failing only for paths scheduled for Task 2 deletion.

- [ ] **Step 5: Commit the boundary contract with the retirement batch**

This task and Task 2 form one reviewable hard-cutover commit because the new absence rules cannot pass before deletion.

### Task 2: Delete the interactive Legacy product runtime and exclusive closure

**Files:**

- Delete: `compose.legacy.yml`
- Delete: `src/novel_forge/cli/legacy.py`
- Delete: `src/novel_forge/api/legacy_app.py`
- Delete: Legacy-only files under `src/novel_forge/api/routers/` and `src/novel_forge/api/services/`
- Delete: `src/novel_forge/workers/celery_app.py`
- Delete: `src/novel_forge/workers/dispatch.py`
- Delete: `src/novel_forge/workers/legacy_tasks.py`
- Delete: `src/novel_forge/workers/runtime.py`
- Delete: `src/novel_forge/workers/tasks.py`
- Delete: `src/novel_forge/storage/local.py`
- Delete: `src/novel_forge/workflows/`
- Delete: `src/novel_forge/modules/agent_scheduler/`
- Delete: `src/novel_forge/modules/agent_registry/`
- Delete: `src/novel_forge/modules/agent_runs/`
- Delete: `src/novel_forge/modules/agent_messages/`
- Delete: `src/novel_forge/modules/tool_gateway/`
- Delete: `src/novel_forge/modules/production_kernel/`
- Delete: `src/novel_forge/modules/workflow_nodes/`
- Delete: `src/novel_forge/modules/loop_kernel/`
- Delete: `src/novel_forge/agents/`
- Delete: `src/novel_forge/modules/production_execution/legacy.py`
- Delete: Legacy-only Context, Source Intake, Analysis, and local MKAOS implementation files proven outside Production and Migration closures
- Delete: exclusive Legacy tests under `tests/unit/` and `tests/integration/`
- Delete: exclusive Legacy scripts and Web feature modules after API-call verification
- Modify: `src/novel_forge/cli/__init__.py`
- Modify: `src/novel_forge/api/app.py` or delete it if no production entry consumes it
- Modify: `src/novel_forge/infrastructure/settings.py`
- Modify: `src/novel_forge/model_adapters/__init__.py`
- Modify: `src/novel_forge/modules/production_execution/__init__.py`
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Modify: `compose.yml`
- Modify: `Dockerfile`
- Modify: `.env.example`

**Interfaces:**

- Consumes: exact production and migration reachability evidence generated from the current checkout before each deletion batch.
- Produces: one Authority runtime plus one offline migration command surface; no LocalStorage/Celery/Legacy API runtime.

- [ ] **Step 1: Produce and inspect exact candidate lists**

For each candidate, search imports, entrypoints, workers, routers, registries, config, scripts, UI calls, migrations, and tests. Retain shared files if Production or Migration reaches them; remove package-level exports that create false reachability before recalculating the graph.

- [ ] **Step 2: Separate production and migration CLI modules**

Keep the user-visible migration actions `authority-import-legacy`, `authority-import-status`, `authority-verify-migration`, and `authority-quarantine-list`. The normal CLI dispatcher selects either an Authority command module or an offline migration command module. Production API and worker roots do not import the migration command module.

- [ ] **Step 3: Delete the first complete runtime closure**

Remove Compose, API, CLI, Worker/Celery, LocalStorage, Workflow, old Agent, and old Production Kernel files together with their exclusive tests and configs. Remove Redis/Celery dependencies and settings when no retained importer uses them.

- [ ] **Step 4: Delete old local Context/Source/MKAOS closures**

Retain PostgreSQL `source_authority`, `source_import`, `content_intelligence`, and `mkaos_authority`. Retain migration parsers/mappers. Remove only local JSON lifecycle services and tests whose callers belonged to the retired product runtime.

- [ ] **Step 5: Remove broken Legacy-only Web pages and clients**

Compare every Web API call with Authority API routes. Delete pages/clients that only target retired `/product/...` Legacy endpoints. Retain Authority-backed Source, MKAOS, Book, Chapter, Agent Runtime, Capability Pack, Temporal Query, and Content Intelligence surfaces.

- [ ] **Step 6: Run collection and architecture checks**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest --collect-only -q tests/unit tests/architecture tests/acceptance tests/integration
make architecture-manifests-check
make architecture-fitness-check
make head-integrity-check
npm --prefix web/admin test
```

Expected: no missing imports or registry targets, no retired runtime path, and no Production-to-Migration path.

- [ ] **Step 7: Run retained non-PostgreSQL suites**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit tests/architecture tests/acceptance`

Expected: all retained tests pass; no assertion is weakened to accommodate deletion.

- [ ] **Step 8: Commit**

Commit message: `refactor: retire interactive legacy runtime`

### Task 3: Establish the independent Production Execution composition

**Files:**

- Create: `src/novel_forge/infrastructure/production_execution_composition.py`
- Create: `tests/unit/test_production_execution_composition.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `src/novel_forge/modules/chapter_authority/application.py`
- Modify: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Modify: `src/novel_forge/modules/agent_runtime/execution.py`
- Modify: `src/novel_forge/modules/source_import/execution.py`
- Modify: `src/novel_forge/modules/story_planning_runtime/execution.py`
- Modify: affected Worker entrypoints under `src/novel_forge/workers/`
- Modify: composition-related unit, architecture, and PostgreSQL integration tests

**Interfaces:**

- Consumes: `IndustrialSettings`, runtime environment, Provider registry, existing PEP gateway/backend/recovery types, and object-store implementations.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class ProductionExecutionComposition:
    transport: ProductionExecutionGatewayExternalEffectAdapter
    object_store_adapter: ExternalEffectAdapter
    object_store_reader: LocalObjectStoreReader | MinioObjectStoreReader
    max_cost_per_call: str
    budget_caps: Mapping[str, str]
```

These are existing concrete or established port types; no new protocol is
created merely for this dataclass.

- [ ] **Step 1: Add failing ownership tests**

Tests assert that Agent, Source Import, Reader, Planning, and Book builders accept `ProductionExecutionComposition`, do not accept `ChapterAuthorityApplication` to obtain execution dependencies, and construct one shared transport per process composition.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_production_execution_composition.py tests/unit/test_chapter_authority_dependencies.py tests/unit/test_book_production_composition.py -q`

- [ ] **Step 3: Extract existing PEP construction without semantic changes**

Move route/profile/backend/object-store/admission/recovery construction out of `build_chapter_authority_application`. Preserve existing controlled-environment checks and exact gateway types.

- [ ] **Step 4: Make Chapter a peer consumer**

Build Chapter-specific binder and model port from the shared composition. Remove shared object-store/external-effect ownership from Chapter application where no Chapter domain behavior requires it.

- [ ] **Step 5: Rewire Agent, Source, Reader, Planning, Book, API, and Workers**

Pass the composition explicitly. Cancellation uses the shared execution composition rather than `chapter_application.external_effect_adapters`.

- [ ] **Step 6: Add architecture assertions**

Assert that peer modules do not reference `ChapterAuthorityApplication.model_port`, `chapter.object_store_adapter`, or Chapter execution internals as shared dependency sources.

- [ ] **Step 7: Run affected suites**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_production_execution_composition.py \
  tests/unit/test_chapter_authority_dependencies.py \
  tests/unit/test_book_production_composition.py \
  tests/unit/test_story_planning_runtime.py \
  tests/unit/test_agent_authority_scheduler.py \
  tests/architecture/test_production_execution_plane_boundaries.py \
  tests/architecture/test_core_functional_loop_boundaries.py
```

- [ ] **Step 8: Commit**

Commit message: `refactor: centralize production execution composition`

### Task 4: Converge API and Worker composition roots

**Files:**

- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `src/novel_forge/workers/agent_authority.py`
- Modify: `src/novel_forge/workers/chapter_authority.py`
- Modify: `src/novel_forge/workers/source_import.py`
- Modify: `src/novel_forge/workers/book_authority.py`
- Modify: other Authority workers only when they construct Production Execution resources
- Modify: `tests/unit/test_authority_api_surface.py`
- Modify: `tests/architecture/test_release_entrypoint_contract.py`
- Modify: `tests/architecture/test_production_execution_gateway_boundaries.py`

**Interfaces:**

- Consumes: the concrete Production Execution composition and existing Authority applications.
- Produces: one explicit object graph per API/worker process with deterministic construction order and shutdown.

- [ ] **Step 1: Add construction-count and dependency-direction tests**

Verify one execution composition per process builder, no Worker-to-API composition dependency, no hidden global cache, and no peer Application dependency borrowing.

- [ ] **Step 2: Move cross-domain construction to infrastructure composition**

Keep HTTP router registration in `authority_app.py` and process loops in workers. Keep builders concrete and shallow; do not create a factory per service.

- [ ] **Step 3: Preserve resource shutdown**

Ensure database pools, Provider processes, and execution resources follow existing process shutdown paths.

- [ ] **Step 4: Run focused API/Worker/architecture tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_authority_api_surface.py tests/unit/test_worker_health_readiness.py tests/architecture/test_release_entrypoint_contract.py tests/architecture/test_production_execution_gateway_boundaries.py -q`

- [ ] **Step 5: Commit**

Commit message: `refactor: converge authority composition roots`

### Task 5: Restore Book query and command boundaries

**Files:**

- Create: `src/novel_forge/modules/book_authority/query.py`
- Create: `tests/unit/test_book_production_query.py`
- Modify: `src/novel_forge/modules/book_authority/supervisor.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/modules/book_authority/composition.py`
- Modify: `src/novel_forge/workers/book_authority.py`
- Modify: `src/novel_forge/modules/book_authority/__init__.py`
- Modify: `tests/unit/test_book_production_supervisor.py`
- Modify: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`
- Modify: `tests/integration/test_core_functional_loops_postgres.py`
- Modify: `tests/architecture/test_core_functional_loop_boundaries.py`

**Interfaces:**

- Consumes: Book production tables and related Authority projections through a concrete PostgreSQL read class.
- Produces business-named reads such as active plan resolution, checkpoint eligibility, replan source projection, chapter execution plan projection, and coordination candidates.

- [ ] **Step 1: Add failing boundary tests**

Assert that `BookProductionSupervisor`, `BookProductionComposition`, and `workers/book_authority.py` do not import `AuthorityUnitOfWork`, call `.cursor.execute`, or contain SQL keywords. Test query methods independently with a stubbed unit of work or PostgreSQL integration fixtures as appropriate.

- [ ] **Step 2: Extract read projections**

Move Supervisor and Worker SELECT statements to `PostgresBookProductionQuery`. Keep joins cohesive around Book decisions; do not create per-table repositories.

- [ ] **Step 3: Route state mutation through Book Authority**

Replace Supervisor `_set_state` SQL with an existing or narrowly extended Book Authority command path using OperationDefinition admission, expected version, CAS, checkpoint, trace, outbox, and idempotency.

- [ ] **Step 4: Rewire composition and worker**

Inject the concrete query into Supervisor and use it for RuntimeJob candidate selection. Composition files remain SQL-free.

- [ ] **Step 5: Run Book unit and architecture tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_book_production_query.py tests/unit/test_book_production_supervisor.py tests/unit/test_book_production_composition.py tests/architecture/test_core_functional_loop_boundaries.py -q`

- [ ] **Step 6: Run Book PostgreSQL tests when Docker is available**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_book_to_chapter_authority_vertical_postgres.py tests/integration/test_core_functional_loops_postgres.py -q`

- [ ] **Step 7: Commit**

Commit message: `refactor: enforce book authority query boundaries`

### Task 6: Audit equivalent production SQL bypasses and accidental complexity

**Files:**

- Modify: only production Supervisor/Scheduler/Worker/Composition files with a proven business-state mutation bypass
- Modify: related concrete Authority/query modules and tests
- Modify: `tests/architecture/test_repository_execution_boundaries.py`
- Modify: `architecture/manifests/ruff-legacy-baseline.json` or delete it if the retained tree is Ruff-clean
- Modify/Delete: dead wrappers, registries, protocols, comments, and scripts proven unused after the preceding cutovers

**Interfaces:**

- Consumes: production reachability and searches for `AuthorityUnitOfWork`, SQL mutation verbs, direct repository construction, and pass-through wrappers.
- Produces: a bounded audit result encoded as architecture tests, not a generated session report.

- [ ] **Step 1: Enumerate direct mutation candidates**

Search only production Applications, Supervisors, Schedulers, Workers, and composition roots. Classify SQL inside an Authority implementation as valid; classify mutation from orchestration/process layers as a bypass.

- [ ] **Step 2: Correct confirmed same-pattern bypasses**

Move reads to existing or concrete business queries and mutations to existing Authority commands. Do not broaden into business semantic redesign.

- [ ] **Step 3: Remove proven accidental abstractions**

Delete only zero-caller wrappers/interfaces/registries and obsolete compatibility comments. Preserve comments explaining authority, concurrency, recovery, temporal, or security invariants.

- [ ] **Step 4: Tighten lint debt**

Recompute Ruff findings after Legacy deletion. Prefer a repository-wide Ruff gate if the retained tree can be made clean; otherwise keep a renamed, explicit non-Legacy debt baseline with fewer findings and no deleted paths.

- [ ] **Step 5: Run architecture and retained unit suites**

Run: `make validate && PYTHONPATH=src .venv/bin/python -m pytest tests/unit tests/architecture tests/acceptance`

- [ ] **Step 6: Commit**

Commit message: `refactor: close authority orchestration bypasses`

### Task 7: Reconstruct current documentation

**Files:**

- Rewrite: `README.md`
- Create/Rewrite: `docs/architecture/overview.md`
- Create/Rewrite: `docs/architecture/runtime.md`
- Create/Rewrite: `docs/architecture/authority-model.md`
- Create/Rewrite: `docs/architecture/production-execution.md`
- Create/Rewrite: `docs/architecture/narrative-state.md`
- Create/Rewrite: `docs/product/novel-production-flow.md`
- Create/Rewrite: `docs/product/capability-map.md`
- Create/Rewrite: `docs/operations/local-development.md`
- Create/Rewrite: `docs/operations/configuration.md`
- Create/Rewrite: `docs/operations/database.md`
- Create/Rewrite: `docs/operations/workers.md`
- Create/Rewrite: `docs/operations/troubleshooting.md`
- Create/Rewrite: `docs/development/repository-structure.md`
- Create/Rewrite: `docs/development/testing.md`
- Create/Rewrite: `docs/development/adding-capabilities.md`
- Create/Rewrite: `docs/development/coding-guidelines.md`
- Create/Rewrite: retained ADRs under `docs/adr/`
- Delete: superseded reports, blueprints, prompts, completed plans/specs, duplicated current-state files, generated noise, and invalid architecture documents

**Interfaces:**

- Consumes: final production entrypoints, Compose, migrations, manifests, routes, workers, code-level domain contracts, and current-SHA test evidence.
- Produces: a small stable documentation graph with no session-level completion claims.

- [ ] **Step 1: Classify every tracked document**

Assign CURRENT, SUPERSEDED, DUPLICATED, HISTORICAL_VALUE, GENERATED_NOISE, or INVALID. Only CURRENT and compressed HISTORICAL_VALUE decisions survive.

- [ ] **Step 2: Delete non-current documentation**

Do not bulk-move it to archive. Preserve copyright/license material and binding ADR decisions.

- [ ] **Step 3: Write the new documentation from code**

Answer system identity, production entry, PostgreSQL authority, Book-to-Replan, Agent/Capability/Skill/Pack, narrative state distinctions, Source-to-MKAOS, and proof maturity. Use exact paths and executable commands.

- [ ] **Step 4: Validate links and prohibited maturity claims**

Search for removed paths and unsupported `COMPLETE`, `PRODUCTION_READY`, `FULLY_AUTONOMOUS`, `real_provider_proven=true`, and `production_verified=true` claims.

- [ ] **Step 5: Commit**

Commit message: `docs: rebuild current system documentation`

### Task 8: Complete regression, runtime proof, and delivery

**Files:**

- Modify: only defects found by final validation
- Delete: this implementation plan if final documentation policy classifies session plans as generated noise; retain the durable convergence decision as an ADR

**Interfaces:**

- Consumes: final checkout and locally available infrastructure.
- Produces: clean pushed branch, test evidence in the handoff/PR, and a Draft PR when GitHub permits.

- [ ] **Step 1: Run static validation**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q src tests
ruff check src tests scripts
make architecture-manifests-check
make architecture-fitness-check
make head-integrity-check
git diff --check
```

- [ ] **Step 2: Run all non-infrastructure suites**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit tests/architecture tests/acceptance
npm --prefix web/admin test
docker compose -f compose.yml config --quiet
docker compose -f compose.postgres-test.yml config --quiet
```

- [ ] **Step 3: Start/check Docker and run PostgreSQL validation**

When Docker is available:

```bash
docker compose -f compose.postgres-test.yml up -d --wait authority-postgres-test
make authority-postgres-test
PYTHONPATH=src .venv/bin/python -m pytest tests/integration
PYTHONPATH=src .venv/bin/python -m pytest -v \
  tests/integration/test_authority_migrations_postgres.py \
  tests/integration/test_authority_schema_postgres.py \
  tests/integration/test_authority_legacy_migration_postgres.py
docker compose -f compose.postgres-test.yml down
```

If Docker remains unavailable, record `ENVIRONMENT_BLOCKED` with the Docker socket error and do not weaken the tests.

- [ ] **Step 4: Record scope and size evidence**

Capture starting/final SHA, production/migration reachability, source/test/doc line changes, removed paths, proof levels, and remaining issues. Do not add generated reports solely to claim completion.

- [ ] **Step 5: Commit final validation fixes**

Commit message: `test: validate authority runtime convergence`

- [ ] **Step 6: Push and create Draft PR**

Run:

```bash
git push -u origin refactor/authority-runtime-convergence
gh pr create --draft --base feat/v7-content-intelligence-and-longform-proof --head refactor/authority-runtime-convergence
```

- [ ] **Step 7: Verify clean handoff**

Run: `git status --short --branch`

Expected: clean branch tracking `origin/refactor/authority-runtime-convergence`.
