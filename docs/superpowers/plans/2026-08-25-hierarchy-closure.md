# WP-HIERARCHY-CLOSURE-01 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `implement` and execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This task is being executed inline because the user explicitly authorized continuous implementation and the current environment forbids sub-agent delegation.

**Goal:** Build a durable, fail-closed Creative Foundation hierarchy and an independently typed causal Narrative Realization contract that gates Chapter planning, records accepted consumption, and drives future-only replan.

**Architecture:** Existing StoryDesign and BookDesign Authorities own versioned design truth, Hierarchical Planning owns plans and Narrative Realization, and Book Acceptance alone commits actual state. `StoryFormationApplication` is a persisted Command/Operation-backed process manager; Narrative Realization reuses current artifact/lifecycle/evidence infrastructure without becoming a `PlanContractType` or another Authority.

**Tech Stack:** Python 3.12, Pydantic v2 typed contracts, PostgreSQL/psycopg, FastAPI command/query surfaces, immutable AssetVersion, Command Kernel/Operation/Attempt/ExternalEffect, pytest, Ruff, Alembic-style registered SQL migrations.

## Global Constraints

- Accepted actual and future intent remain strictly separate.
- Scene/Beat remain Chapter-internal typed structures.
- No parallel Agent Runtime, Workflow Engine, Story Authority, Planning Authority, or fixture-only production path.
- No `NARRATIVE_REALIZATION` PlanContractType and no `AcceptedNarrativeRealization` naming.
- Technical retry is not semantic revision; executed history is immutable and replan is future-only.
- New provider work is worker-owned and may not run inside an HTTP request lifecycle.
- All activation and production admission checks fail closed on missing, stale, mixed-lineage, or hash-drifted bindings.
- Full engineering regression is required; 30/100/300-Chapter campaigns are prohibited.

---

### Task 1: Converge canonical documentation and decisions

**Files:**
- Modify: `docs/architecture/canonical-overall-design.md`
- Modify: `docs/architecture/overview.md`
- Modify: `docs/product/novel-production-flow.md`
- Modify: `docs/adr/0003-book-design-and-planning-convergence.md`
- Create: `docs/adr/0007-foundation-and-narrative-realization-authority.md`

**Interfaces:**
- Consumes: audited current runtime and the approved design specification.
- Produces: one precise target hierarchy and an ADR that constrains all code tasks.

- [ ] Replace BookDesign-v4-as-root language with the six-contract Foundation Set and BookDesign v5 synthesis/reference semantics.
- [ ] Specify Narrative Realization as a Hierarchical Planning-owned typed correctness contract, not a Plan level or accepted actual.
- [ ] Specify event/slice coverage and atomic ChapterPlan execution at acceptance.
- [ ] Mark ADR 0003 superseded where its design-root decision conflicts and record the replacement decision in ADR 0007.
- [ ] Run `make architecture-manifests-check architecture-fitness-check` and expect both architecture checks to pass.
- [ ] Commit the design convergence independently.

### Task 2: Add Foundation Set and v5 domain contracts test-first

**Files:**
- Modify: `src/novel_forge/modules/story_design_authority/domain.py`
- Modify: `src/novel_forge/modules/story_design_authority/qualification.py`
- Modify: `src/novel_forge/modules/story_design_authority/validators.py`
- Modify: `src/novel_forge/modules/book_design_authority/domain.py`
- Modify: `src/novel_forge/modules/book_design_authority/application.py`
- Test: `tests/unit/test_story_design_authority.py`
- Test: `tests/unit/test_story_design_validators.py`
- Test: `tests/unit/test_book_design_authority_domain.py`
- Test: `tests/unit/test_narrative_evolution_book_design.py`

**Interfaces:**
- Consumes: exact `AssetVersion` IDs/content hashes and current StoryDesign lifecycle primitives.
- Produces: `FoundationBinding`, `QualifiedFoundationSet`, layer validation results, and `book-design.v5` synthesis/reference payload validation.

- [ ] Write failing domain tests for complete/exact Foundation Set binding, missing role, duplicate role, content-hash drift, and v5 prohibition on copied world/character bodies.
- [ ] Run the four focused unit files and verify the new cases fail for missing contracts.
- [ ] Add typed Foundation roles/bindings and layer-specific structural/cross-layer validators; retain independent semantic evaluation evidence.
- [ ] Add v5 parsing/validation and compatibility-only v4 reads; block new v4 production activation.
- [ ] Run the focused tests and expect all to pass.
- [ ] Commit Foundation domain semantics.

### Task 3: Implement durable Story Formation and command API

**Files:**
- Create: `src/novel_forge/modules/book_design_authority/formation.py`
- Modify: `src/novel_forge/modules/book_design_authority/definitions.py`
- Modify: `src/novel_forge/modules/book_authority/composition.py`
- Modify: `src/novel_forge/workers/book_authority.py`
- Modify: `src/novel_forge/api/routers/book_design_authority.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Test: `tests/unit/test_story_formation.py`
- Test: `tests/integration/test_story_formation_postgres.py`
- Test: `tests/unit/test_authority_api.py`

**Interfaces:**
- Consumes: `StoryFormationCommand`, Command Kernel Operation, exact activated StoryDesign/BookDesign output refs.
- Produces: persisted `StoryFormationRun`, immutable checkpoint/output bindings, query/approve/resume/abort commands, and an active complete Foundation Set.

- [ ] Write failing tests proving duplicate admission is idempotent, provider work is not run by the API, resume uses persisted checkpoints, and every stage fails closed without current parent bindings.
- [ ] Register formation operations and worker dispatch through the existing RuntimeJob/Operation plane.
- [ ] Implement checkpointed layer advancement and thin Creative Search selection without a Planning scope.
- [ ] Implement command-only API admission, query, approve, resume, and abort endpoints.
- [ ] Run focused unit/PostgreSQL tests and verify restart/replay behavior.
- [ ] Commit the durable formation slice.

### Task 4: Persist Foundation and Narrative Realization lineage

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260825_0100_hierarchy_closure.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: migration manifests used by repository validation.
- Test: `tests/integration/test_hierarchy_closure_migration_postgres.py`

**Interfaces:**
- Consumes: existing Project/Book/AssetVersion/Operation/StoryDesign/plan foreign keys.
- Produces: formation-run/checkpoint rows, exact Foundation bindings, realization contract/current/event/consumption/deviation rows, unique idempotency and fencing constraints.

- [ ] Write failing migration/head tests for the new single migration head and required constraints/indexes.
- [ ] Add forward-safe tables without altering the `story_plan_binding.plan_type` check or accepted-history tables.
- [ ] Register migration 0100 and its manifest hashes.
- [ ] Run migration static checks and targeted fresh/upgrade PostgreSQL tests.
- [ ] Commit persistence independently.

### Task 5: Add Narrative Realization contract and Authority application

**Files:**
- Create: `src/novel_forge/modules/hierarchical_planning/realization_domain.py`
- Create: `src/novel_forge/modules/hierarchical_planning/realization_application.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/__init__.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/definitions.py`
- Test: `tests/unit/test_narrative_realization.py`
- Test: `tests/integration/test_narrative_realization_postgres.py`

**Interfaces:**
- Consumes: exact Foundation/Book/Volume/Arc/ChapterGroup bindings, accepted boundary, Working Set digest, immutable realization content and proof assets.
- Produces: `NarrativeRealizationContract`, `NarrativeRealizationEvent`, `NarrativeRealizationProof`, lifecycle commands, frozen current binding, and replayable contract digest.

- [ ] Write failing tests for causal-chain integrity, dangling cause/next references, illegal knowledge/world/state deltas, missing upper-plan coverage, mixed lineage, and proof drift.
- [ ] Implement typed event/proof schemas and deterministic structural/cross-layer validators.
- [ ] Implement propose/qualify/approve/freeze/stale/supersede lifecycle using existing application/repository conventions.
- [ ] Verify no new PlanContractType or Authority root exists.
- [ ] Run focused unit/PostgreSQL tests and commit.

### Task 6: Gate Chapter planning and production through realization

**Files:**
- Modify: `src/novel_forge/modules/book_authority/supervisor.py`
- Modify: `src/novel_forge/modules/book_authority/queries.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/application.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/domain.py`
- Modify: `src/novel_forge/modules/book_production/domain.py`
- Test: `tests/unit/test_book_production_supervisor.py`
- Test: `tests/unit/test_hierarchical_planning.py`
- Test: `tests/unit/test_book_production_admission.py`

**Interfaces:**
- Consumes: current frozen realization contract/slice and exact event IDs.
- Produces: ChapterPlan frozen-input realization binding, validated event/scene/beat coverage, and dispatch admission that recomputes all digests.

- [ ] Write failing tests for no realization, wrong group, stale proof, mixed Foundation/parent lineage, uncovered event, and tampered digest.
- [ ] Insert realization generation/qualification/freeze between ChapterGroup freeze and ChapterPlan generation in Book Supervisor.
- [ ] Require exact realization slice/event coverage in ChapterPlan generation while retaining ChapterGroup as parent.
- [ ] Recompute all realization and Foundation inputs during production admission and fail closed before dispatch.
- [ ] Run focused tests and commit.

### Task 7: Consume realization only from accepted outcomes

**Files:**
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/modules/book_authority/longform_projection.py`
- Modify: `src/novel_forge/modules/book_authority/queries.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/realization_application.py`
- Modify: `src/novel_forge/modules/hierarchical_planning/application.py`
- Test: `tests/unit/test_book_acceptance.py`
- Test: `tests/integration/test_hierarchy_acceptance_postgres.py`

**Interfaces:**
- Consumes: accepted ChapterOutcome observation evidence and the exact ChapterPlan/realization slice binding.
- Produces: atomic ChapterPlan `EXECUTED`, planned-to-observed accepted consumption rows, partial/complete realization coverage, deviation evidence, and future-only stale/replan requests.

- [ ] Write failing tests proving Plan declarations alone do not consume events, partial group coverage stays frozen, complete coverage executes once, and deviations do not mutate accepted reality.
- [ ] Extend the short Book Acceptance transaction with deterministic plan-execution and realization-consumption writes.
- [ ] Record immutable deviation evidence and trigger existing future-only PlanChange/Replan without editing history.
- [ ] Prove duplicate acceptance/replay is idempotent and live/rebuilt projections agree.
- [ ] Run focused unit/PostgreSQL tests and commit.

### Task 8: Close durable opening admission and recovery

**Files:**
- Modify: `src/novel_forge/modules/book_authority/opening.py`
- Modify: `src/novel_forge/modules/book_authority/input_resolver.py`
- Modify: `src/novel_forge/api/routers/book_authority.py`
- Modify: `src/novel_forge/workers/book_authority.py`
- Test: `tests/unit/test_book_opening.py`
- Test: `tests/integration/test_book_opening_postgres.py`
- Test: `tests/integration/test_hierarchy_recovery_postgres.py`

**Interfaces:**
- Consumes: complete current Qualified Foundation Set and active BookDesign v5.
- Produces: durable open Operation/status/recovery API and immutable Book Production input snapshot with exact Foundation hashes.

- [ ] Write failing tests for incomplete/stale Foundation, direct HTTP provider execution, crash/resume, duplicate delivery, lease takeover, and stale fence.
- [ ] Move opening execution behind the existing worker Operation registry; API only admits and queries.
- [ ] Make input resolution bind exact Foundation/BookDesign versions and reject any drift.
- [ ] Run focused recovery/replay/concurrency tests and commit.

### Task 9: Qualify the complete hierarchy

**Files:**
- Add/modify only directly necessary tests and exact-SHA qualification evidence after all runtime code is final.
- Create: `docs/qualification/2026-08-25-hierarchy-closure.md`
- Remove: active `docs/superpowers/specs/2026-08-25-hierarchy-closure-design.md` and `docs/superpowers/plans/2026-08-25-hierarchy-closure.md` once durable decisions/evidence have converged.

**Interfaces:**
- Consumes: final committed code and migration head.
- Produces: exact-SHA command/result evidence and a clean feature branch.

- [ ] Run focused static/unit/contract tests after each seam.
- [ ] Run `make authority-test`, then the repository full regression targets, recording exact pass/fail counts.
- [ ] Run fresh and upgrade PostgreSQL migrations and targeted Authority/integration tests.
- [ ] Run retry/recovery/replay/resume/concurrency/failure-injection tests and one bounded one-to-three-Chapter deterministic vertical smoke if required.
- [ ] Fix every real regression without weakening invariants, then rerun affected and full suites.
- [ ] Record Code Exists/Wired/Integration Proven/Runtime Proven/NOT_PROVEN evidence at the exact final SHA; explicitly keep long-form/reader/production claims unproven.
- [ ] Run code review, commit final docs, push `codex/hierarchy-closure-01`, open a Draft PR, and verify the worktree is clean.
