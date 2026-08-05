# Autonomous Novel OS Architecture Closure Implementation Plan

> **For agentic workers:** Follow this plan in order. Preserve the existing Command Kernel, PostgreSQL authority, Production Execution Gateway, and domain-authority boundaries. Do not introduce another operation, attempt, lease, fence, pack-run, or agent-run state machine.

**Goal:** Close the production execution path from a versioned PostgreSQL Agent Definition and compiled Capability Pack through the existing Command Kernel and PEP to a validated domain candidate and authoritative AssetVersion, then reuse that path for supervised book production, Reader Outcome proposals, and calibrated quality decisions.

**Architecture:** Agent Run is a query projection over immutable Agent Definition/Capability snapshots, Agent Work Order, existing Operation/Attempt/Lease/Fence, PEP evidence, candidate/decision records, and domain commits. Chapter workflows retain their existing handler and completion contracts; versioned Agent Bindings are resolved at admission for model-backed nodes, while deterministic nodes stay ordinary handlers. Capability Packs freeze configuration only and never own runtime state.

**Tech stack:** Python 3.12, FastAPI, PostgreSQL authority repositories, SQL migrations, pytest, Pydantic/dataclasses, existing Novel Forge Command Kernel and Production Execution modules.

## Implemented scope ledger

This ledger records the actual scope delivered by this change; later task
sections retain the original execution order and verification intent.

| Phase | Actual status | Implemented boundary |
|---|---|---|
| Agent Definition Authority / Run query / Scheduler / API / Worker | RUNTIME_INTEGRATED | PostgreSQL version activation, immutable runtime binding over existing Operation/Attempt/Lease/Fence, combined query, Authority API, pending-query worker, Compose and health manifest |
| Chapter model Agent Binding | RUNTIME_INTEGRATED | Draft-first bridge reused by Draft, Review, Revision, Re-review, Canon Extraction, and five Quality model nodes; controlled execution requires activated bindings and REAL_RUNTIME-qualified capabilities |
| Capability Pack runtime binding | RUNTIME_INTEGRATED | Compiled payload hash is authenticated and compared with the active OperationDefinition inside Chapter binding registration; no Pack Run state exists |
| Prompt / Skill / Context / Tool snapshots | IMPLEMENTED | Attempt-specific AssetVersion evidence is frozen into AgentRuntimeBinding; direct Agent tool access is denied. The old LocalStorage Tool Gateway remains REPLACE_PENDING rather than being promoted to production authority |
| Legacy convergence | IMPLEMENTED | Default CLI/Make targets fail closed to Authority paths, retained surfaces are explicitly classified, and Chapter compatibility use emits AssetVersion audit evidence |
| Book Production Supervisor | VALIDATION_PENDING | Existing durable Book scheduler, Chapter acceptance, Reader Shadow, recap cadence, pause/resume/cancel and restart query paths are retained. Automatic next-ChapterPlan Agent generation and Planning Authority activation are not implemented in this change |
| Reader Outcome consumption | FIXTURE_READY | Explicit qualification lifecycle and bounded trend/cooldown/bias/OOD/drift policy feed Longform Recap proposals; default remains SHADOW and cannot mutate plans |
| Quality calibration | FIXTURE_READY | Existing calibration flow now reports Kappa, rank correlation, calibration error, false decisions and segment diagnostics; uncalibrated fixture passes remain explicitly non-production |

No PostgreSQL integration suite, real Provider, real long-form, Docker Compose
E2E, multi-book, Playwright, backup/PITR, performance, or capacity validation is
claimed by this ledger.

## Actual affected surfaces

- Agent Runtime: `src/novel_forge/modules/agent_runtime/`, Authority API
  dependencies/router, worker, Compose, permissions, console entrypoint, and
  database connection-budget registry.
- Authority persistence: migration `20260805_0068`, migration registry, Agent
  Collaboration candidate handling, Authority repository bundle, and combined
  Agent/asset-lineage queries.
- Chapter vertical slice: the existing Chapter model ExternalEffect port and
  PEP contract binder, with active bindings for Draft, Review, Revision,
  Re-review, Canon Extraction, and five Quality stages.
- Capability Pack: workflow-node Agent references, compiler/protocol/validator,
  and admission-time compiled-pack authentication.
- Legacy: CLI/Make defaults, explicit usage evidence, and the classified legacy
  surface manifest. No destructive Legacy migration is included.
- Book/Reader/Quality: conservative Reader Shadow consumption in the existing
  durable Book scheduler and recap, Reader qualification policy, calibration
  diagnostics, and fixture-promotion rejection. No new Book state machine was
  added.
- Verification: focused unit/architecture tests, PostgreSQL integration test
  definitions, and module/migration/worker/test/entrypoint manifests.

## Non-negotiable constraints

- PostgreSQL is the production authority. In-memory and LocalStorage implementations remain explicit fixtures or compatibility adapters only.
- Existing `authority_operation`, `authority_attempt`, lease, fence, external-effect, and worker primitives are reused without parallel state.
- Agent output is a candidate. The current Chapter/Planning/Canon/Reader/Quality domain authorities validate and commit formal assets.
- OperationDefinition remains authoritative for retry, timeout, approval, compensation, and completion contracts; a Capability Pack cannot override it.
- Runtime inputs bind immutable AssetVersions and content hashes for context, prompt, skill, route, input manifest, policies, and release SHA.
- Disabled definitions, missing hashes, drift, missing permissions, and unknown external effects fail closed.
- Fixture calibration remains fixture evidence and must not become production-qualified.
- Full test, Docker, real-provider, real-longform, multi-book, Playwright, backup/PITR, performance, and capacity validation stay `NOT_EXECUTED` in this round.

## Task 1: Establish the authoritative Agent Definition schema

**Files:**

- Create: `src/novel_forge/storage/migrations/versions/v20260805_0068_unified_agent_runtime.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `src/novel_forge/modules/agent_collaboration/domain.py`
- Modify: `src/novel_forge/storage/agent_collaboration_repositories.py`
- Create: `src/novel_forge/modules/agent_runtime/__init__.py`
- Create: `src/novel_forge/modules/agent_runtime/contracts.py`
- Create: `src/novel_forge/modules/agent_runtime/repository.py`
- Create: `src/novel_forge/modules/agent_runtime/bootstrap.py`
- Test: `tests/unit/test_agent_runtime_contracts.py`
- Test: `tests/integration/test_unified_agent_runtime_postgres.py`

**Implementation:**

1. Extend the existing versioned Agent Capability with its explicit PEP execution-capability mapping and content hash.
2. Extend the existing versioned Agent Definition with Capability Pack, prompt, skill, tool, context, approval, quality, and execution policy references/hashes.
3. Add a small CAS activation pointer for definition versions; never update immutable definition rows and never rewrite historical runs.
4. Add immutable versioned Chapter Agent Bindings plus an activation pointer.
5. Add immutable Agent Runtime Bindings that reference real operations, attempts, fencing tokens, work orders, and frozen contracts. Do not add a status column or a second attempt table.
6. Implement an explicit bootstrap/legacy adapter that may import static profiles into PostgreSQL but is never a production registry or fallback.

**Focused verification:**

```bash
uv run pytest -q tests/unit/test_agent_runtime_contracts.py
uv run pytest -q tests/integration/test_unified_agent_runtime_postgres.py
uv run python -m compileall -q src/novel_forge/modules/agent_runtime
```

## Task 2: Build the Agent Run projection and production API

**Files:**

- Create: `src/novel_forge/modules/agent_runtime/queries.py`
- Create: `src/novel_forge/modules/agent_runtime/application.py`
- Create: `src/novel_forge/api/routers/agent_runtime.py`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/api/models.py`
- Modify: `src/novel_forge/modules/authority_security/service.py`
- Test: `tests/unit/test_agent_run_projection.py`
- Test: `tests/api/test_agent_runtime_authority_api.py`

**Implementation:**

1. Derive run status from the existing operation/attempt/external-effect facts; do not persist duplicate status.
2. Return Agent Definition/Capability, work order, operation, attempt, worker/lease/fence, route/context/prompt/skill/tool/provider evidence, candidate/decision/commit, trace, usage/cost, failure/retry/cancel/recovery in one projection.
3. Add authority routes for create/list/detail/cancel/retry, Agent Definition queries, and collaboration-session query using current API path conventions.
4. Apply project/workspace scope and worker/API principal permissions. All mutations require idempotency keys.

**Focused verification:**

```bash
uv run pytest -q tests/unit/test_agent_run_projection.py tests/api/test_agent_runtime_authority_api.py
```

## Task 3: Add the persistent Agent Scheduler and worker entry

**Files:**

- Create: `src/novel_forge/modules/agent_runtime/scheduler.py`
- Create: `src/novel_forge/workers/agent_authority.py`
- Modify: `pyproject.toml`
- Modify: `compose.yml`
- Modify: `architecture/manifests/worker-manifest.yaml`
- Modify: `architecture/manifests/production-entry-manifest.yaml`
- Test: `tests/unit/test_agent_authority_scheduler.py`
- Test: `tests/integration/test_agent_authority_scheduler_postgres.py`

**Implementation:**

1. Resolve only active PostgreSQL Agent Definition versions and frozen bindings.
2. Admit work through the existing Command Kernel and create/queue/acquire/start/complete existing Authority Attempts.
3. Use stable idempotency and project/book/agent concurrency keys, existing budget/timeout/cancel/retry rules, lease takeover, fences, and UNKNOWN external-effect reconciliation.
4. Poll PostgreSQL pending work; never create an in-process authoritative queue.
5. Add worker manifest, Compose service, principal, health/readiness, shutdown, and restart recovery.

**Focused verification:**

```bash
uv run pytest -q tests/unit/test_agent_authority_scheduler.py tests/integration/test_agent_authority_scheduler_postgres.py
```

## Task 4: Close the Chapter Draft Agent vertical slice

**Files:**

- Modify: `src/novel_forge/modules/chapter_authority/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/application.py`
- Modify: `src/novel_forge/modules/chapter_authority/scheduler.py`
- Modify: `src/novel_forge/modules/chapter_authority/runtime.py`
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/config/capability_packs/chapter_generation_pack.json`
- Test: `tests/unit/test_chapter_draft_agent_binding.py`
- Test: `tests/integration/test_chapter_draft_agent_authority_postgres.py`

**Implementation:**

1. Resolve the active Draft Agent Binding before the Draft node is admitted.
2. Freeze definition/capability/pack/context/prompt/skill/tool/route/input/release identities into the work order and runtime binding.
3. Run the current Draft handler through PEP under the real attempt fence.
4. Capture the normalized output as candidate evidence; let the existing Draft Domain Handler validate and materialize the formal Draft AssetVersion.
5. Keep old Handler + ModelPort only behind explicit development compatibility mode; production fails if the Agent Binding is absent.

**Focused verification:**

```bash
uv run pytest -q tests/unit/test_chapter_draft_agent_binding.py tests/integration/test_chapter_draft_agent_authority_postgres.py
```

## Task 5: Reuse the binding for Review, Revision, quality, and canon nodes

**Files:**

- Modify: `src/novel_forge/modules/agent_runtime/bootstrap.py`
- Modify: `src/novel_forge/config/capability_packs/chapter_generation_pack.json`
- Modify: `src/novel_forge/modules/chapter_authority/scheduler.py`
- Test: `tests/unit/test_chapter_model_agent_bindings.py`

**Implementation:**

1. Add Review, Revision, Re-review, five Quality Judges, and Canon Extraction bindings using the proven Draft path. Reader Outcome remains a Book Follow-up stage until its own Authority binding is implemented.
2. Leave deterministic nodes unbound and ordinary.
3. Preserve each domain handler's schema, candidate acceptance, completion contract, and commit authority.

## Task 6: Enforce Capability Pack runtime binding and external-tool boundary

**Files:**

- Modify: `src/novel_forge/modules/capability_packs/schema.py`
- Modify: `src/novel_forge/modules/capability_packs/compiler.py`
- Create: `src/novel_forge/modules/capability_packs/runtime_binding.py`
- Modify: `src/novel_forge/modules/production_execution/contracts.py`
- Modify: `src/novel_forge/modules/production_execution/tool_gateway.py`
- Test: `tests/unit/test_capability_pack_runtime_binding.py`
- Test: `tests/architecture/test_agent_external_execution_boundary.py`

**Implementation:**

1. Compile/freeze the Agent Definition reference with each model-backed workflow node.
2. At Authority admission, compare the compiled pack against the active OperationDefinition and Agent/Capability versions; reject policy conflict or hash drift.
3. Persist compilation hash in the immutable runtime binding, not a Pack Run.
4. Route Agent-callable HTTP/files/commands/MCP through the PEP-governed Tool Gateway with stable tool/action/schema/risk identity, frozen permission snapshots, attempt/fence binding, validation, traces, audit, timeout/cancel/retry, and external-effect semantics.
5. Keep ordinary PostgreSQL repositories outside MCP/tool wrapping.

## Task 7: Isolate Legacy defaults and record compatibility usage

**Files:**

- Create: `architecture/manifests/legacy-classification.yaml`
- Modify: `Makefile`
- Modify: `src/novel_forge/agents/runtime.py`
- Modify: `src/novel_forge/modules/agent_registry/service.py`
- Modify: `src/novel_forge/modules/agent_runs/service.py`
- Modify: `src/novel_forge/modules/agent_scheduler/service.py`
- Test: `tests/architecture/test_legacy_production_reachability.py`
- Test: `tests/architecture/test_legacy_classification_manifest.py`

**Implementation:**

1. Classify every retained legacy entry as migration-only, read-only archive, development fixture, compatibility adapter, replace-pending, or dead code.
2. Make Authority demo/validation the defaults and rename legacy commands explicitly.
3. Ensure production API/workers never import LocalStorage or old workflow/agent services.
4. Record every compatibility-adapter use as a Legacy Usage Event; prohibit silent fallback.
5. Delete only call-graph-proven unreachable code.

## Task 8: Add the persistent Book Production Supervisor

**Files:**

- Create: `src/novel_forge/modules/book_authority/supervisor.py`
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/modules/book_authority/governed_scheduler.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/`
- Modify: `src/novel_forge/modules/plan_change_authority/`
- Modify: `src/novel_forge/workers/book_authority.py`
- Test: `tests/unit/test_book_production_supervisor.py`
- Test: `tests/integration/test_book_supervisor_recovery_postgres.py`

**Implementation:**

1. Poll resumable PostgreSQL Book Runs and coordinate existing Authority commands; do not build an in-process loop.
2. Dispatch Chapter Plan candidates through Agent Runtime, activate through Planning Authority, delegate through existing Book-to-Chapter authority, and observe completion.
3. Maintain a versioned rolling ChapterPlan horizon and use PlanChange impact analysis for stale/superseded future work.
4. Support pause/resume/cancel/retry/approval and preserve operator control.

## Task 9: Connect Reader Outcome to governed PlanChange proposals

**Files:**

- Modify: `src/novel_forge/modules/reader_calibration/domain.py`
- Modify: `src/novel_forge/modules/reader_calibration/application.py`
- Modify: `src/novel_forge/storage/reader_calibration_repositories.py`
- Modify: `src/novel_forge/modules/plan_change_authority/`
- Add migration only if existing reader tables cannot carry immutable report/profile/decision facts.
- Test: `tests/unit/test_reader_outcome_plan_change_policy.py`
- Test: `tests/integration/test_reader_outcome_authority_postgres.py`

**Implementation:**

1. Preserve SHADOW/UNCALIBRATED defaults and implement the qualification lifecycle without auto-promotion.
2. Convert qualified, sufficiently sampled, confidence-checked, segment-aware trend evidence into Reader Issues and bounded Plan Adjustment candidates.
3. Require cooldown, maximum scope, disagreement/bias/OOD/drift checks, impact analysis, and PlanChange Authority approval before future-plan activation.
4. Never mutate prose, Canon, Story State, published chapters, or active plans directly.

## Task 10: Persist quality calibration and targeted revision closure

**Files:**

- Modify: `src/novel_forge/modules/chapter_quality_authority/calibration.py`
- Create: `src/novel_forge/modules/chapter_quality_authority/calibration_application.py`
- Create: `src/novel_forge/storage/chapter_quality_calibration_repositories.py`
- Add migration only for currently missing immutable Golden Set, label, run, metric, qualification, and drift facts.
- Modify: `src/novel_forge/modules/content_quality_loop/`
- Test: `tests/unit/test_quality_calibration_pipeline.py`
- Test: `tests/integration/test_quality_calibration_postgres.py`

**Implementation:**

1. Persist versioned Judge Profiles, golden samples/human labels, evaluations, agreement/bias/calibration metrics, qualification decisions, monitoring, and drift.
2. Require QUALIFIED profiles for blocking production gates; retain explicitly marked `PASSED_WITH_UNCALIBRATED` only for development/fixtures and prohibit formal publish verification.
3. Turn evidence into targeted Revision Tasks with target AssetVersion, required change, must-preserve constraints, acceptance criteria, revision candidate, and re-evaluation.

## Task 11: Update manifests, review, verify the focused surface, and commit

**Files:**

- Modify: `architecture/manifests/module-manifest.yaml`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Modify: `architecture/manifests/test-manifest.yaml`
- Modify: `architecture/manifests/worker-manifest.yaml`
- Modify: `architecture/manifests/production-entry-manifest.yaml`
- Modify: relevant architecture documentation only where required to describe implemented code and explicit non-claims.

**Verification sequence:**

```bash
uv run python -m compileall -q src/novel_forge
uv run pytest -q <new focused unit tests>
uv run pytest -q <new focused PostgreSQL integration tests when the configured authority database is available>
uv run pytest -q tests/architecture/test_legacy_production_reachability.py <new architecture tests>
uv run ruff check <changed Python files>
uv run mypy <changed typed modules where supported>
git diff --check
git diff --cached --check
```

Record unavailable or intentionally deferred suites as `NOT_EXECUTED`; do not infer production readiness. Review the complete diff against the fixed starting SHA `a3c59277d05a00cec79dfccd9d39236e88809f19`, then commit the intentional implementation and evidence.
