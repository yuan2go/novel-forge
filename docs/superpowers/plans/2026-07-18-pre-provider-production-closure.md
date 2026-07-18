# Pre-Provider Production Closure Implementation Plan

> **For agentic workers:** Execute inline against the current working tree. Preserve unrelated user files and commit each independently tested vertical slice.

**Goal:** Close the runtime, preparation, quality, and Canon approval gaps required before a paid real-Provider single-chapter proof.

**Architecture:** Extend the existing PostgreSQL Command Kernel instead of creating a parallel runtime. Shared worker/deadline/recovery primitives remain business-agnostic; Preparation, grouped Quality, and Canon approval expose typed domain contracts and materialize immutable Authority evidence. Projection and LocalStorage paths remain outside Completion.

**Tech Stack:** Python 3.11+, FastAPI, psycopg/PostgreSQL, dataclasses, unittest/pytest, existing Authority Unit of Work and migrations.

## Global Constraints

- PostgreSQL remains the only production authority.
- Provider/network/object-store effects execute only through `ExternalEffect`.
- Fixture evidence never becomes `production_verified` or `real_provider_proven`.
- Full Git commit identities are exactly 40 lowercase hexadecimal characters.
- No paid Provider, long-form generation, remote Git, destructive Git, or LocalStorage production write is permitted.
- Preserve `.idea/misc.xml` unchanged and untracked.

---

### Task 1: Shared worker execution boundary and recover command

**Files:**
- Create: `src/novel_forge/modules/command_kernel/worker_execution.py`
- Create: `src/novel_forge/modules/command_kernel/recovery.py`
- Modify: `src/novel_forge/workers/chapter_authority.py`
- Modify: `src/novel_forge/workers/content_authority.py`
- Modify: `src/novel_forge/api/routers/content_authority.py`
- Test: `tests/unit/test_authority_worker_execution.py`
- Test: `tests/integration/test_authority_worker_failure_isolation_postgres.py`

**Interfaces:**
- Produces `WorkerFailureClass`, `WorkerFailureClassifier`, `AuthorityWorkerExecutionBoundary.execute()` and `RecoverOperationCommand`.
- Persists classified failure through fenced Attempt results and kernel StateEvent/Audit/Outbox.

- [ ] Write failure-classification and batch-isolation tests.
- [ ] Implement the shared boundary and make both workers continue after known task failures.
- [ ] Implement versioned/idempotent recovery for retryable, expired execution, external reconciliation, manual gate, and successful replay states.
- [ ] Run focused unit/PostgreSQL/API tests and commit.

### Task 2: Frozen deadlines, cancellation, reconciliation, and budget semantics

**Files:**
- Create: `src/novel_forge/modules/command_kernel/deadline_runtime.py`
- Create: `src/novel_forge/modules/command_kernel/manual_effect_resolution.py`
- Modify: `src/novel_forge/modules/command_kernel/attempt_runtime.py`
- Modify: `src/novel_forge/modules/command_kernel/cancellation.py`
- Modify: `src/novel_forge/modules/command_kernel/external_effect_runtime.py`
- Modify: `src/novel_forge/modules/command_kernel/budget_runtime.py`
- Modify: `src/novel_forge/modules/command_kernel/lease_heartbeat.py`
- Create: `src/novel_forge/storage/migrations/versions/v20260718_0024_pre_provider_runtime_hardening.py`
- Test: `tests/unit/test_authority_deadline_and_budget_policy.py`
- Test: `tests/integration/test_pre_provider_runtime_hardening_postgres.py`

**Interfaces:**
- Produces immutable operation/attempt/effect deadlines, cooperative cancellation probes, reconciliation/manual-resolution commands, and explicit budget scopes.
- Business deadlines never move when a lease heartbeat succeeds; UNKNOWN retains its reservation.

- [ ] Add migration tests for deadlines, manual-resolution evidence, budget aggregates, currency, and indexes.
- [ ] Freeze and enforce deadlines, including before-send retry versus after-send UNKNOWN.
- [ ] Propagate cancellation to adapters and record unsupported/unknown outcomes honestly.
- [ ] Resume fenced attempts after reconciliation or authorized manual resolution.
- [ ] Serialize scoped reservations and test daily timezone/currency/concurrency boundaries.
- [ ] Run focused tests and commit in independently reviewable slices.

### Task 3: Release identity and query permission closure

**Files:**
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/api/routers/chapter_authority.py`
- Modify: `src/novel_forge/api/routers/content_authority.py`
- Modify: catalog validation/generator paths discovered by tests.
- Test: `tests/unit/test_authority_security.py`
- Test: `tests/unit/test_authority_api_contract.py`

**Interfaces:**
- `authority_release_identity()` accepts exactly one full 40-character lowercase hex SHA.
- All strong queries require a trusted Principal and explicit/wildcard project scope.

- [ ] Add failing release-identity and cross-project query tests.
- [ ] Enforce identity and query permission rules.
- [ ] Run focused tests and commit.

### Task 4: Production Preparation v2 manifest and profiles

**Files:**
- Modify: `src/novel_forge/modules/production_preparation/contracts.py`
- Modify: `src/novel_forge/modules/production_preparation/resolver.py`
- Replace/extend: `src/novel_forge/modules/production_preparation/policies.py`
- Modify: `src/novel_forge/modules/production_preparation/service.py`
- Modify: `src/novel_forge/api/routers/chapter_authority.py`
- Modify: Chapter Context handler/Completion definition.
- Test: `tests/unit/test_production_preparation_v2.py`
- Test: `tests/integration/test_production_preparation_v2_postgres.py`

**Interfaces:**
- Produces immutable `ProductionInputManifest`, typed requirements/selections/rejections/risks/repairs, and `ContextManifestConsistencyReport`.
- Resolver supports multiple eligible versions filtered by entity, role, chapter/arc/volume scope and exact profile lineage.

- [ ] Test multi-character/relationship selection, exact versioned profiles, EmptyStateDeclaration, and risk-driven approvals.
- [ ] Implement stage profiles, governed multi-selection, manifest digest, and versioned manifest materialization.
- [ ] Bind quality/platform profiles through Context, Quality, and Publish lineage.
- [ ] Require exact Manifest/frozen-input/Context-segment agreement.
- [ ] Run focused tests and commit.

### Task 5: Five grouped Quality operations and fan-in

**Files:**
- Modify: `src/novel_forge/modules/chapter_quality_authority/domain.py`
- Add focused domain ports under `src/novel_forge/modules/chapter_quality_authority/`.
- Modify: `src/novel_forge/modules/chapter_authority/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/scheduler.py`
- Test: `tests/unit/test_chapter_quality_real_gate.py`
- Test: `tests/integration/test_chapter_quality_fan_in_postgres.py`

**Interfaces:**
- Produces Structural, Commercial, Source/Originality, Long-form, and Platform evidence Operations plus `ChapterQualityAggregate` fan-in.
- Weak/missing semantic evidence returns `UNCALIBRATED`, `INSUFFICIENT_EVIDENCE`, or an explicit review requirement, never fixture PASS.

- [ ] Test five group contracts and blocking status semantics.
- [ ] Reuse existing storage-free evaluators and materialize evidence tied to current Revision and profile versions.
- [ ] Admit quality children after Canon, independently retry them, and execute Aggregate only after all succeed.
- [ ] Tighten Publish Gate release levels and non-waivable blockers.
- [ ] Run focused tests and commit.

### Task 6: Canon proposal, approval gate, and reduction resume

**Files:**
- Create: `src/novel_forge/modules/canon_approval/contracts.py`
- Create: `src/novel_forge/modules/canon_approval/domain.py`
- Create: `src/novel_forge/modules/canon_approval/runtime.py`
- Create: `src/novel_forge/api/routers/canon_authority.py`
- Modify: Canon extraction/reduction handlers and Chapter scheduler.
- Create: `src/novel_forge/storage/migrations/versions/v20260718_0025_canon_approval_authority.py`
- Test: `tests/unit/test_canon_change_approval.py`
- Test: `tests/integration/test_canon_approval_authority_postgres.py`
- Test: `tests/unit/test_canon_authority_api.py`

**Interfaces:**
- Produces versioned change proposals, per-change approval requests/decisions, `WAITING_GATE`, and an approved `CanonReductionPlan`.
- Reduction accepts only approved/edited low-risk changes and records proposal/decision/previous-snapshot lineage.

- [ ] Test confidence/evidence validation and high-impact risk classification.
- [ ] Add append-only approval schema with project scope, expiry, optimistic version, idempotency, Audit and Outbox.
- [ ] Materialize proposals, wait without terminal failure, and resume the same logical chain after decision.
- [ ] Implement list/detail/decision/resume API with trusted Principal.
- [ ] Test APPROVE/REJECT/EDIT_AND_APPROVE/DEFER/REQUEST_REEXTRACTION and cross-project denial.
- [ ] Run focused tests and commit.

### Task 7: Architecture proof, generated evidence, and readiness report

**Files:**
- Modify/add boundary tests under `tests/architecture/` and `tests/acceptance/`.
- Add/update the reports named in the user task.
- Regenerate `docs/reports/postgresql-operation-definition-catalog.json` and coverage evidence.

**Interfaces:**
- Produces current-HEAD catalog/coverage and `READY_FOR_REAL_PROVIDER_SINGLE_CHAPTER` only if every blocking focused proof passes.

- [ ] Run unit, PostgreSQL integration, architecture, TestClient, migration, compileall, and `git diff --check` suites.
- [ ] Review source changes against project and Skill boundaries.
- [ ] Regenerate catalog/coverage and document exact maturity states and deferred high-cost proofs.
- [ ] Commit documentation and report the final readiness verdict without pushing.
