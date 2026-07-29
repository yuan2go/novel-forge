# Autonomous Novel OS Nine-stage Authority Closure Implementation Plan

> **For agentic workers:** Execute inline in this session. Each task uses one public
> Command/Operation/Query seam, follows red-green TDD, and must pass its focused
> gate before the next task starts.

**Goal:** Close the Book-to-Chapter, long-form state, governed story-design,
hierarchical-planning, plan-change, and Reader Outcome evidence loops on the
existing PostgreSQL Command Kernel and Production Execution Plane.

**Architecture:** PostgreSQL Authority remains the only production write model.
Every model or process effect uses the existing Attempt, fence, ExternalEffect,
RouteSnapshot, and `ProductionExecutionGateway`; new domain services only produce
or validate candidates, while deterministic Authority applications commit
append-only versions and typed orchestration references. Legacy LocalStorage
paths remain fixtures/imports and fail closed in production-like environments.

**Tech Stack:** Python 3.11+, stdlib dataclasses/enums/unittest, psycopg 3,
PostgreSQL 16, existing Novel Forge Command Kernel/Authority Handler Runtime/PEP.

## Global Constraints

- Do not create a second Operation, Saga, Attempt, lease, fence, ExternalEffect,
  receipt, budget, or asset-version authority.
- Do not synchronously execute a complete Chapter Saga from Book dispatch.
- Generators and Recap create candidates/proposals; only an Authority command can
  approve or activate them.
- Story State reducers are deterministic, append-only, idempotent, and never call
  a model.
- Reader Outcome remains `SHADOW`, `UNCALIBRATED`, and `RAW_SCORE` until valid
  human/behavior evidence exists.
- Fake/scripted evidence may prove L4 integration but never real Provider,
  long-form, calibration, or production maturity.

---

### Task 1: HEAD integrity and fail-closed registries

**Files:**
- Create: `src/novel_forge/tools/head_integrity.py`
- Create: `tests/architecture/test_head_integrity.py`
- Modify: `src/novel_forge/tools/authority_parity_manifest.py`
- Modify: `.github/workflows/core-os-ci.yml`
- Modify: `Makefile`
- Modify: `docs/reports/postgresql-authority-coverage-baseline.json`
- Create: `docs/reports/head-integrity-repair-report.md`

**Interfaces:**
- Consumes: repository root and tracked-file manifest from Git.
- Produces: `build_head_integrity_report(root) -> HeadIntegrityReport` and
  `make head-integrity-check`; non-zero exit on missing import/export, migration,
  router, operation definition, handler, test collection, or untracked required
  runtime file.

- [ ] Add a failing architecture test that detects the current clean-HEAD
  `book_authority.production` and migration-0034 failures.
- [ ] Implement AST/import/registry/tracked-file checks without executing business
  mutations.
- [ ] Add the check to `make authority-parity-check` and CI before test jobs.
- [ ] Regenerate HEAD-bound coverage evidence from the complete source tree.
- [ ] Run compile, imports, architecture, unit, integration, acceptance,
  `make authority-parity-check`, `make test`, and `make validate`.
- [ ] Commit the complete Stage-1 file set so a clean archive is importable.

### Task 2: Dynamic Book-to-Chapter delegation and two-chapter proof

**Files:**
- Modify: `src/novel_forge/modules/book_authority/production.py`
- Modify: `src/novel_forge/modules/book_authority/governed_scheduler.py`
- Modify: `src/novel_forge/storage/book_authority_repositories.py`
- Create: `src/novel_forge/storage/migrations/versions/v20260730_0035_longform_authority.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`
- Create: `docs/reports/book-to-chapter-two-chapter-proof.md`

**Interfaces:**
- Consumes: `ChapterAuthorityApplication.admit`, `ChapterAuthorityScheduler.tick`,
  and `ChapterAuthorityQuery.require_run`.
- Produces: Book commands `resolve_plan`, `dispatch`, `reconcile`, `accept`,
  `pause`, `resume`, `cancel`, `recover`, and `query`; persisted
  `authority_child_delegation` rows reference but never duplicate Chapter state.

- [ ] Test two dynamically admitted Chapter roots, one active delegation, stable
  idempotency, response-loss recovery, pause/resume/cancel, and evidence-complete
  single cursor advancement.
- [ ] Register governed Book operation definitions and child Saga steps.
- [ ] Persist delegation before returning `DISPATCHED`; execute Chapter work only
  through the existing Chapter scheduler.
- [ ] Validate root/Saga terminal state, final release, export receipt, quality,
  Canon, ChapterOutcome, Story State, and cost evidence before acceptance.
- [ ] Inject failures before/after admission, delegation persistence, acceptance,
  and cursor advancement; prove replay.

### Task 3: Non-blocking Reader Outcome and Recap sidecars

**Files:**
- Modify: `src/novel_forge/modules/book_followup_authority/contracts.py`
- Modify: `src/novel_forge/modules/book_followup_authority/domain.py`
- Modify: `src/novel_forge/modules/book_followup_authority/handlers.py`
- Modify: `src/novel_forge/modules/book_followup_authority/definitions.py`
- Modify: `src/novel_forge/modules/book_authority/governed_scheduler.py`
- Modify: `tests/integration/test_book_followup_authority_postgres.py`
- Create: `docs/reports/reader-outcome-shadow-recap-sidecar-report.md`

**Interfaces:**
- Produces `ReaderOutcomeEvaluation`, `ReaderStateTransitionCandidate`,
  `ReaderOutcomeIssue`, and `JudgeExecutionEvidence` with fixed
  `SHADOW/UNCALIBRATED/RAW_SCORE` semantics.
- Produces deterministic Recap, plan-vs-actual, deviation, debt, adjustment, and
  optional replan proposal assets; Chapter acceptance is not rolled back by a
  sidecar failure.

- [ ] Test immutable input/evidence contract, PEP usage/cost trace, raw-score
  restrictions, boundary idempotency, accepted-outcome-only Recap, and
  non-mutation of active plans.
- [ ] Persist one sidecar trigger per book/chapter boundary/type.
- [ ] Schedule both sidecars after acceptance without adding a success dependency
  between them.
- [ ] Record zero-cost receipts for deterministic Recap.

### Task 4: ChapterOutcome and deterministic Story State

**Files:**
- Create: `src/novel_forge/modules/chapter_outcome/domain.py`
- Create: `src/novel_forge/modules/chapter_outcome/reducers.py`
- Create: `src/novel_forge/modules/chapter_outcome/application.py`
- Create: `src/novel_forge/storage/chapter_outcome_repositories.py`
- Create: `tests/unit/test_chapter_outcome_story_state.py`
- Create: `tests/integration/test_chapter_outcome_story_state_postgres.py`
- Create: `docs/reports/chapter-outcome-story-state-authority-report.md`

**Interfaces:**
- Produces `chapter_outcome` and `story_state_snapshot` Authority AssetVersions.
- Reducer registry exposes ordered `ReducerDefinition` values and
  `apply(outcome, previous_state) -> reducer delta`; repository uniqueness is
  `(project_id, chapter_outcome_version_id, reducer_key)`.

- [ ] Test acceptance prerequisites and frozen plan binding.
- [ ] Test every reducer is deterministic, append-only, idempotent, model-free,
  recoverable after partial application, and fail-closed on Canon conflict.
- [ ] Add the committed Story State snapshot to next-Chapter context resolution.

### Task 5: Shared Story Design Asset Authority

**Files:**
- Create: `src/novel_forge/modules/story_design_authority/contracts.py`
- Create: `src/novel_forge/modules/story_design_authority/application.py`
- Create: `src/novel_forge/modules/story_design_authority/registry.py`
- Create: `tests/unit/test_story_design_authority.py`
- Create: `tests/integration/test_story_design_authority_postgres.py`
- Create: `docs/reports/story-design-asset-authority-report.md`

**Interfaces:**
- Consumes existing Content Authority and PEP operations.
- Produces orthogonal lifecycle, qualification, approval, freshness, and planning
  scope state for append-only candidate AssetVersions.

- [ ] Register the ten requested generator definitions without duplicating the
  Command Kernel or Provider runtime.
- [ ] Test frozen manifests, bounded repair, approval, activation/supersession,
  multi-candidate mechanism diversity, and non-active legacy imports.

### Task 6: Hierarchical planning contracts and typed relations

**Files:**
- Create: `src/novel_forge/modules/hierarchical_planning/domain.py`
- Create: `src/novel_forge/modules/hierarchical_planning/application.py`
- Create: `src/novel_forge/storage/planning_repositories.py`
- Create: `tests/unit/test_hierarchical_planning.py`
- Create: `tests/integration/test_hierarchical_planning_postgres.py`
- Create: `docs/reports/hierarchical-planning-contract-report.md`

**Interfaces:**
- Produces Book/Volume/Arc/ChapterGroup/Chapter contract AssetVersions plus typed
  hierarchy, binding, dependency, active-version, and horizon rows.

- [ ] Test containment versus cross-volume Arc relations, parent-version binding,
  one active version, frozen/executed immutability, and multi-Arc contributions.
- [ ] Validate ChapterFunctionMatrix repetition, escalation, objective progress,
  Arc contribution, and hook diversity.

### Task 7: ChapterGroup Authority and rolling horizon

**Files:**
- Create: `src/novel_forge/modules/chapter_group_authority/application.py`
- Create: `src/novel_forge/modules/chapter_group_authority/domain.py`
- Create: `tests/integration/test_chapter_group_authority_postgres.py`
- Create: `docs/reports/chapter-group-rolling-horizon-report.md`

**Interfaces:**
- Produces a group root Saga that dynamically delegates one Book/Chapter child at
  a time and advances a versioned `PlanningHorizon`.

- [ ] Prove a three-Chapter group, one active child, function-matrix gate,
  pause/resume/cancel, one Recap, plan-vs-actual proposal, and atomic horizon
  advancement.

### Task 8: Plan Change, semantic impact, approval, and activation

**Files:**
- Create: `src/novel_forge/modules/plan_change_authority/domain.py`
- Create: `src/novel_forge/modules/plan_change_authority/application.py`
- Create: `tests/unit/test_plan_change_authority.py`
- Create: `tests/integration/test_plan_change_authority_postgres.py`
- Create: `docs/reports/plan-change-impact-approval-report.md`

**Interfaces:**
- Produces append-only `PlanChangeProposal`, field-level `SemanticDiff`,
  dependency-edge `ImpactAnalysis`, Authority decision, and activation receipt.

- [ ] Test scope policies for EXECUTED/FROZEN/PLANNED/SPECULATIVE plans.
- [ ] Test high-risk human approval, one active version, stale descendant dispatch
  blocking, recovery around activation/outbox, and revalidation.

### Task 9: Human preference and Reader behavior calibration

**Files:**
- Create: `src/novel_forge/modules/reader_calibration/domain.py`
- Create: `src/novel_forge/modules/reader_calibration/application.py`
- Create: `src/novel_forge/storage/reader_calibration_repositories.py`
- Create: `tests/unit/test_reader_calibration.py`
- Create: `tests/integration/test_reader_calibration_postgres.py`
- Create: `docs/reports/reader-calibration-progress-report.md`

**Interfaces:**
- Produces blind preference pairs/decisions/golden sets/agreement reports,
  exposure-denominated behavior events, and scoped Calibration profiles.

- [ ] Test position reversal/bias, agreement, exposure denominator, profile
  resolution, insufficient-data blocking, OOD/drift shadow downgrade, hard-gate
  precedence, and project/segment isolation.
- [ ] Preserve truthful maturity: flow/pipeline may be integrated, while human
  anchoring, real behavior calibration, causal validation, and production
  autonomy remain false without external evidence.

### Task 10: Regression, evidence, and independent review

**Files:**
- Modify: `README.md`, `ARCHITECTURE.md`, `WORKFLOW.md`, `TESTING.md`,
  `AGENTS.md`, `CLAUDE.md`, `docs/project-current-state.md`,
  `docs/architecture/module-map.md`, `docs/product/capability-map.md`,
  `docs/quality/regression-tests.md`
- Create: `docs/reports/next-phase-independent-audit.md`

**Interfaces:**
- Consumes the starting commit `9101aef459d57c9ca570957fcfff9e7b4214561a`.
- Produces separate Standards and Spec reviews, actual command/count/duration
  evidence, maturity matrix, external blockers, and risk register.

- [ ] Run focused unit/PostgreSQL tests after every vertical slice.
- [ ] Run all requested integration modules, complete `make test`, `make
  postgres-authority-test`, `make authority-parity-check`, `make validate`,
  compileall, diff-check, migration-from-clean, and clean-archive import checks.
- [ ] Inspect real Provider/Codex credentials without logging secrets; run only an
  explicitly configured safe smoke and otherwise mark external credentials
  blocked.
- [ ] Review the final diff twice against repository standards and this plan,
  repair findings, then commit logical stages.
