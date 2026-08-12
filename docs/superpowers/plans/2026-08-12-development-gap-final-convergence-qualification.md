# Development Gap Final Convergence Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `tdd` and execute this plan inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qualify current `origin/main` and close the remaining production-runtime gap between Quality required actions and governed revision/re-evaluation without adding another execution plane.

**Architecture:** Preserve PostgreSQL Authority, Command Kernel, Chapter Saga, existing Chapter Operations, ExternalEffect, and the 0084 derived lineage projections as the only owners. The Chapter scheduler may admit one bounded quality-correction generation using the existing Revision, Re-review, Canon, grouped Quality, and aggregate Quality definitions; correction Operations remain children of the existing root but are not extra canonical Saga steps. Narrative measurement continues to derive from frozen inputs and gains explicit receipt/lineage availability states.

**Tech Stack:** Python 3.11+, PostgreSQL/psycopg, pytest, Ruff, Docker Compose, Next.js admin validation.

## Global Constraints

- Baseline is exact `origin/main` SHA `aa6734799c693f1d669a5b3781d69ef5d888e15f`.
- PostgreSQL is the only production Authority; no new Agent, Judge, Provider, Workflow Engine, Authority Plane, retry runtime, or proof framework.
- Existing Operation, Attempt, Lease, Fence, ExternalEffect, receipt, and asset lineage remain canonical.
- Do not modify historical migration 0084; add a forward migration only if a non-derivable fact or schema invariant is required.
- Fixture evidence may reach `FIXTURE_PROVEN` only and must not be promoted to real-provider, longform, multibook, or production proof.
- Do not run 30/100/300-chapter or multibook proof.

---

### Task 1: Re-qualify source methodology identity

**Files:**
- Verify: `src/novel_forge/modules/source_import/analysis_profiles.py`
- Verify: `src/novel_forge/modules/source_import/application.py`
- Test: `tests/unit/test_source_intelligence_routing.py`
- Test: `tests/integration/test_source_import_runtime_postgres.py`

**Interfaces:**
- Consumes: `ResolvedAnalysisStrategy.fingerprint`, Source Import product runtime.
- Produces: exact reuse/invalidation evidence; no new fingerprint or schema.

- [x] Run the focused unit identity matrix and confirm it covers Skill bytes/version, profile, routing, analyzer, capability, provider/aggregation, and abstraction policy.
- [x] Run the PostgreSQL Source Import matrix and confirm unchanged Source/Normalize/Chunk reuse alongside classifier and downstream analysis invalidation.
- [x] Add only a missing behavioral test or code correction discovered by those runs.

### Task 2: Close Quality corrective execution

**Files:**
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/scheduler.py`
- Modify: `src/novel_forge/modules/revision/domain.py`
- Test: `tests/integration/test_chapter_authority_scheduler_postgres.py`

**Interfaces:**
- Consumes: `ChapterAuthorityScheduler.tick()`, governed `revision_task` outputs, existing Chapter node definitions.
- Produces: one bounded correction generation whose Revision consumes the Quality tasks, whose corrected result is re-reviewed/canon-checked/quality-checked, and whose final lineage is visible through `CorrectiveActionQuery`.

- [x] Add a PostgreSQL test where initial aggregate Quality emits a blocking task, correction executes, Quality re-evaluation passes, and `CorrectiveActionQuery` reports `RESOLVED` with execution/result/evaluation identities.
- [x] Implement Quality-task-aware Revision and re-evaluation inputs while preserving the ordinary Review path.
- [x] Extend the existing scheduler to admit and recover the bounded correction generation with existing definitions and root lineage.
- [x] Add a PostgreSQL test where the re-evaluation still requires the same action and the issue becomes `ESCALATED`; replay must not duplicate the logical correction.
- [x] Run Chapter scheduler recovery, retry, stale-fence, and duplicate-prevention tests.

### Task 3: Make measurement availability explicit

**Files:**
- Modify: `src/novel_forge/modules/narrative_state/measurements.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Test: `tests/unit/test_narrative_runtime_convergence.py`
- Test: `tests/integration/test_chapter_model_effects_postgres.py`

**Interfaces:**
- Consumes: exact-context `model_call_log`/`cost_ledger`, Context Manifest selected inputs, Provider ExternalEffect identities.
- Produces: nullable metrics plus `MEASURED`, `NOT_OBSERVED`, `NOT_AVAILABLE`, or `NOT_APPLICABLE` observation states for usage/cost/trace/consumption evidence.

- [x] Add a unit test proving present Provider calls with unavailable receipt/trace evidence are not reported as successful zero evidence.
- [x] Derive MKAOS consumption only when exact-context successful Provider effects are identified; selected-only remains outside consumption.
- [x] Preserve measured zero for an actually observed zero-token/zero-cost fixture call.
- [x] Run the production-composition PostgreSQL measurement and MKAOS selection/consumption tests.

### Task 4: Engineering qualification and delivery evidence

**Files:**
- Create: `docs/qualification/development-gap-final-convergence.md`
- Modify: `docs/product/capability-map.md`

**Interfaces:**
- Consumes: exact final SHA commands and test outputs.
- Produces: Capability Proof Matrix and fail-closed handoff.

- [ ] Validate migration chain, fresh database migration, and 0083-to-0084 upgrade without editing migration history.
- [ ] Run unit, architecture, acceptance, integration, PostgreSQL, lint, type-check equivalent, Skill drift, Capability Pack, package, web test/build, and Compose configuration gates.
- [ ] Run code review, remove dead/duplicate/forwarding artifacts, and rerun affected gates.
- [ ] Record exact commands, counts, evidence ceilings, recovery/idempotency results, and remaining gaps in the qualification report and Capability Proof Matrix.
- [ ] Review diff, commit, push, create a Draft PR, verify exact remote SHA, and confirm a clean worktree.
