# P0 Production Runtime Convergence Implementation Plan

> Baseline: `79f06c19033d12374ec4fda6f066a46f59bf51a1`
>
> Design: `docs/superpowers/specs/2026-08-10-p0-production-runtime-convergence-design.md`

**Goal:** make existing Book production capabilities reachable through one
PostgreSQL-backed composition shared by the Authority API and Book Worker, with a
truthful Capability Pack/test/readiness gate and formal two-chapter proofs.

**Constraints:** reuse existing Authorities and Command Kernel; no new workflow
framework, scheduler, authority, agent, provider, or narrative capability.

## Task 1: Restore the Capability Pack contract

**Files:**

- Modify `config/capability_packs/chapter_generation_pack.json`
- Modify `src/novel_forge/modules/capability_packs/protocol.py`
- Modify `src/novel_forge/modules/capability_packs/loader.py`
- Modify `src/novel_forge/modules/capability_packs/validator.py`
- Modify `src/novel_forge/modules/capability_packs/compiler.py`
- Modify `src/novel_forge/modules/capability_packs/operation_catalog.py`
- Test `tests/unit/test_capability_pack_validator.py`
- Test `tests/unit/test_capability_pack_resolution_compiler.py`
- Test `tests/unit/test_capability_pack_runtime_resolver.py`

1. Add failing tests proving final `quality` is deterministic, has no execution
   capability, retains the aggregate timeout, and cannot silently lose a required
   capability on provider-backed nodes.
2. Make workflow capability binding optional only where the authoritative
   OperationDefinition has no external effect.
3. Remove the false final-quality mapping and manifest binding.
4. Update stale Runtime Resolver test doubles from Draft `2.2.0` to the governed
   `2.3.1` operation definition; do not change production versions to fit tests.
5. Run the three focused modules and record collected/passed counts.

## Task 2: Make pytest the canonical Python test runner

**Files:**

- Modify `Makefile`
- Modify `.github/workflows/core-os-ci.yml`
- Modify `scripts/run_authority_postgres_tests.py`
- Modify `scripts/check_required_test_manifest.py`
- Modify `tests/unit/test_required_test_manifest.py` or the nearest manifest test
- Modify `docs/05-testing/testing-strategy.md`

1. Add a failing test for a required top-level pytest function that unittest would
   report as zero tests.
2. Change local and CI unit/architecture/acceptance/integration invocations to
   `python -m pytest`, preserving existing unittest classes.
3. Make the required-test check execute pytest collection and fail when a required
   module collects zero tests.
4. Run collect-only for all required domains and assert a positive count.

## Task 3: Introduce the single Book production composition root

**Files:**

- Add `src/novel_forge/modules/book_authority/composition.py`
- Modify `src/novel_forge/modules/book_authority/__init__.py`
- Modify `src/novel_forge/api/authority_dependencies.py`
- Modify `src/novel_forge/api/authority_app.py`
- Modify `src/novel_forge/api/routers/book_authority.py`
- Test `tests/unit/test_book_production_composition.py`
- Modify `tests/unit/test_book_authority_api.py` or nearest API tests

The new object is a composition container/facade, not a stateful runtime. It must
construct and expose the existing `PostgresBookAuthority`,
`PostgresBookProductionSupervisor`, `StoryPlanningGenerationApplication`,
`PostgresChapterGroupAuthority`, `ProductionPreparationService`,
`BookFollowupAuthority`, `PostgresPlanChangeAuthority`, and
`BookReplanCoordinator` from one dependency graph.

1. Write tests that API startup fails when a required dependency cannot build and
   that API tick uses the injected composition directly.
2. Build all services from shared Chapter/PEP dependencies and the same principal.
3. Add the required composition to `AuthorityApiServices`.
4. delete the route's `getattr(...book_production_supervisor...)` fallback.

## Task 4: Close Replan through explicit approval

**Files:**

- Modify `src/novel_forge/modules/book_authority/composition.py`
- Modify `src/novel_forge/modules/book_authority/supervisor.py`
- Modify `src/novel_forge/api/routers/book_authority.py`
- Test `tests/unit/test_book_production_supervisor.py`
- Test `tests/integration/test_core_functional_loops_postgres.py`

1. Add tests for `REPLAN_REQUIRED -> start -> APPROVAL_PENDING`, repeated tick and
   restart idempotency, formal approval, later tick activation/resume, and no
   duplicate candidate/proposal.
2. Derive the existing recap/replan-request and future plan target from Authority
   state; call `BookReplanCoordinator.start` with a stable Book/checkpoint key.
3. Return a normal `WAITING_REPLAN_APPROVAL` tick while pending; never approve from
   Worker code.
4. Add a formal approval endpoint/command that calls the existing coordinator
   decision boundary.
5. On an approved durable replan state, canonical tick calls idempotent `activate`,
   updates the input snapshot, resumes Book, and continues on later ticks.

## Task 5: Put the Book Worker on the same production tick

**Files:**

- Modify `src/novel_forge/workers/book_authority.py`
- Modify `src/novel_forge/modules/book_authority/composition.py`
- Test `tests/unit/test_book_authority_worker.py`
- Test `tests/integration/test_book_authority_postgres.py`

1. Change scheduling eligibility so resolved-input `READY`, replan waiting, and
   post-approval states are driven without busy-looping or omission.
2. Make `execute_book_coordination_claim` accept the canonical composition/ticker,
   not the sidecar-only governed scheduler.
3. Build the same composition factory used by API startup.
4. Verify RuntimeJob retry/restart remains an operational envelope and does not
   copy Chapter Attempt/Lease/Fence/ExternalEffect state.

## Task 6: Make readiness evidence-backed

**Files:**

- Modify `src/novel_forge/api/authority_app.py`
- Modify the existing readiness/runtime-status service used by that route
- Test `tests/unit/test_authority_readiness.py` or nearest readiness tests
- Test the relevant PostgreSQL worker-health integration module

1. Add failing tests for missing required worker kinds, stale workers, invalid Pack,
   unbuildable Provider route, database/migration failure, and MinIO failure.
2. Return distinct `api_ready`, `runtime_ready`, `fixture_only`,
   `real_provider_qualified`, `real_provider_proven`, `longform_proven`, and
   `production_verified` fields.
3. Keep proof fields false unless current-SHA evidence supports them.
4. Ensure `/ready` remains an operational API/dependency check while runtime
   readiness reports the stronger production-runtime contract.

## Task 7: Formal two-chapter vertical proofs

**Files:**

- Modify `tests/integration/test_core_functional_loops_postgres.py`
- Modify `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`
- Modify or add focused Worker integration tests only where necessary
- Modify `scripts/run_short_longform_runtime_proof.py` to consume the composition

1. Replace manual Supervisor/Replan assembly with the production composition
   builder.
2. Prove no-Replan Chapter 1 acceptance/Reader/Recap to Chapter 2 admission and
   execution through formal API/Worker tick semantics.
3. Prove Replan to `APPROVAL_PENDING`, formal approval, activation/resume, then
   Chapter 2 admission/execution.
4. Reuse existing Command Kernel recovery tests for retry, lease/fence, UNKNOWN
   ExternalEffect and add composition-path assertions rather than duplicating that
   machinery.

## Task 8: Verify, document current truth, and publish

**Files:**

- Rewrite only the affected Canonical Runtime/Testing/Current State sections
- Update the relevant ADR if it still declares unittest canonical

Run, in order:

```bash
make validate
PYTHONPATH=src .venv/bin/python -m pytest --collect-only -q tests/unit tests/architecture tests/acceptance
PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit
PYTHONPATH=src .venv/bin/python -m pytest -q tests/architecture
PYTHONPATH=src .venv/bin/python -m pytest -q tests/acceptance
make authority-test
make postgres-authority-test
make authority-compose-config-check
make authority-smoke
npm --prefix web/admin test
```

Also run focused migration, Worker integration, retry/restart, lease/fence, and
UNKNOWN ExternalEffect modules. Mark Docker/PostgreSQL/MinIO/Provider-dependent
commands `NOT_VERIFIED` when the current environment cannot execute them.

Finally review the full diff against the baseline, run `git diff --check`, commit
intentional changes, push `codex/p0-production-runtime-convergence`, and create a
Draft PR with exact collected/passed/failed counts and the evidence ceiling.
