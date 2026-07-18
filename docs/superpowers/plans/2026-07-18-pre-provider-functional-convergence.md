# Pre-Provider Functional Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close ChapterPlan fidelity, typed empty state, Provider v2 control, stage-specific Quality context, Canon recovery, calibration, and CI guardrails without running a real Provider.

**Architecture:** Extend the existing PostgreSQL Command Kernel and Chapter Authority only. Storage-free codecs/domain models build typed views and validation reports from frozen AssetVersions; Application Services coordinate state transitions; repositories persist without creative policy; every external call remains an ExternalEffect.

**Tech Stack:** Python 3.12, dataclasses/Protocols, FastAPI, PostgreSQL 16, psycopg 3, unittest, GitHub Actions.

## Global Constraints

- PostgreSQL remains the only production Authority; no LocalStorage first-write or fallback.
- Existing migrations are immutable; new schema changes start after `20260718_0027`.
- Fixture outputs carry `real_model_call=false`, `production_verified=false`, and `fixture_protocol_only=true`.
- No real Provider, credential, chapter generation, network connector, platform publishing, or maturity promotion beyond `integration_proven`.
- All reads/writes are project-scoped and all execution inputs are frozen AssetVersions.

---

### Task 1: ChapterPlan Fidelity

**Files:**
- Create: `src/novel_forge/modules/chapter_authority/chapter_plan_views.py`
- Modify: `src/novel_forge/modules/production_preparation/contracts.py`
- Modify: `src/novel_forge/modules/production_preparation/service.py`
- Modify: `src/novel_forge/modules/chapter_authority/orchestrator.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Test: `tests/unit/test_chapter_plan_fidelity.py`
- Test: `tests/integration/test_chapter_authority_scheduler_postgres.py`

**Interfaces:**
- Consumes: frozen `chapter_plan` AssetVersion and governed Context/Style inputs.
- Produces: `normalize_chapter_plan(...) -> AuthoritativeChapterPlanView`, `build_draft_plan_view(...)`, `ChapterPlanQualificationReport`.

- [ ] Write tests proving rich fields survive normalization, legacy plans produce warnings, semantic minimum failures block, and plan hashes affect Command digest.
- [ ] Add typed compatibility normalization with required semantic minimums and a stable contract version.
- [ ] Add `chapter_plan_asset_version_id` and `chapter_plan_content_hash` to the admitted command and validate them against frozen input.
- [ ] Replace template Plan construction with normalization/materialization of the frozen input.
- [ ] Pass only DraftPlanView, DraftContextView, and DraftStyleView to the model boundary.
- [ ] Run unit and PostgreSQL replay/replacement/project-isolation tests, then commit.

### Task 2: Typed Empty State Snapshots

**Files:**
- Create: `src/novel_forge/modules/production_preparation/empty_state.py`
- Modify: `src/novel_forge/modules/production_preparation/service.py`
- Modify: `src/novel_forge/modules/context_builder/domain.py`
- Modify: `src/novel_forge/modules/canon_graph/domain.py`
- Modify: `src/novel_forge/modules/chapter_quality_authority/domain.py`
- Test: `tests/unit/test_typed_empty_state.py`
- Test: `tests/integration/test_chapter_authority_scheduler_postgres.py`

**Interfaces:**
- Consumes: an eligible `empty_state_declaration` AssetVersion for chapter N-1.
- Produces: a typed input view whose `logical_asset_type` is one of the nine Snapshot kinds while preserving the declaration AssetVersion lineage.

- [ ] Test nine state kinds, wrong chapter/project, non-empty override conflict, replay, and missing-vs-explicit-empty quality semantics.
- [ ] Define `TypedEmptyStateSnapshot` and validate append-only declaration semantics.
- [ ] Resolve declarations into typed frozen candidates without inventing an unpersisted version.
- [ ] Teach Context, Canon, Quality, Recap-facing view builders to distinguish `EXPLICITLY_EMPTY` from `MISSING`.
- [ ] Run focused unit/PostgreSQL tests and commit.

### Task 3: Provider Adapter v2

**Files:**
- Create: `src/novel_forge/modules/provider_runtime_v2/contracts.py`
- Create: `src/novel_forge/modules/provider_runtime_v2/scripted.py`
- Create: `src/novel_forge/modules/provider_runtime_v2/compatibility.py`
- Modify: `src/novel_forge/modules/command_kernel/external_effect_runtime.py`
- Modify: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Test: `tests/unit/test_provider_adapter_v2.py`
- Test: `tests/integration/test_external_effect_runtime_postgres.py`

**Interfaces:**
- Produces: `ProviderCapabilityProfile`, `ProviderInvocationRequest/Handle/Result`, `ProviderQueryRequest`, `ProviderCancellationRequest`, and `ProviderReceipt`.
- Adapter protocol: explicit `capabilities`, `execute_v2`, `query_v2`, `cancel_v2`; no production `hasattr` capability inference.

- [ ] Test execute/query/cancel/callback/timeout/duplicate/conflict/capability-mismatch scenarios with a scripted adapter.
- [ ] Add immutable v2 contracts and a legacy compatibility adapter marked `LEGACY_UNCONTROLLED` and validation-ineligible.
- [ ] Freeze capability/idempotency/query/cancel/callback modes into each ExternalEffect and persist provider request identity.
- [ ] Fail closed when declared capabilities and returned handles disagree.
- [ ] Integrate budget UNKNOWN/settlement behavior and run PostgreSQL tests, then commit.

### Task 4: Stage-Specific Quality Context and Policy Compilation

**Files:**
- Create: `src/novel_forge/modules/chapter_quality_authority/context_views.py`
- Create: `src/novel_forge/modules/chapter_quality_authority/policy_compiler.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Test: `tests/unit/test_quality_context_views.py`

**Interfaces:**
- Produces five immutable context view types plus deterministic `CompiledQualityPolicy` and `CompiledPlatformPolicy` with digest and source version lineage.

- [ ] Test group isolation, commercial promise/reward, nine-state long-form visibility, full platform rules, source-expression exclusion, stale profile rejection, and token compression.
- [ ] Compile versioned policy assets without latest reads or scattered thresholds.
- [ ] Build group-specific minimal context from frozen ChapterPlan/Manifest/Context/Canon/Profile inputs.
- [ ] Bind view/policy digests to Provider request and Quality evidence.
- [ ] Run focused tests and commit.

### Task 5: Canon Approval Recovery

**Files:**
- Create: `src/novel_forge/modules/canon_graph/approval_recovery.py`
- Modify: `src/novel_forge/modules/canon_graph/approval_domain.py`
- Modify: `src/novel_forge/modules/canon_graph/approval_authority.py`
- Modify: `src/novel_forge/api/routers/canon_authority.py`
- Create: `src/novel_forge/storage/migrations/versions/v20260718_0028_canon_approval_recovery.py`
- Test: `tests/unit/test_canon_approval_recovery.py`
- Test: `tests/integration/test_chapter_authority_scheduler_postgres.py`

**Interfaces:**
- Produces: defer/reopen commands, proposal generation/supersession records, re-extraction admission, and `CanonChangeResolution` with edited-payload validation report.

- [ ] Test DEFER/reopen/expiry, stale versions, cancel race, re-extraction generation, supersession, invalidation, edited conflicts, and cross-project denial.
- [ ] Add migration fields/indexes without deleting historical decisions.
- [ ] Implement deferred state transitions and permissioned reopen command.
- [ ] Implement REQUEST_REEXTRACTION generation and invalidate old proposal/request participation.
- [ ] Validate edited payload before resolution materialization and Canon Reduction.
- [ ] Prove WAITING_GATE recovery through PostgreSQL tests and commit.

### Task 6: Quality Calibration Foundation and Worker Health

**Files:**
- Create: `src/novel_forge/modules/quality_calibration/domain.py`
- Create: `src/novel_forge/modules/quality_calibration/__init__.py`
- Create: `src/novel_forge/modules/command_kernel/worker_health.py`
- Modify: `src/novel_forge/modules/command_kernel/worker_execution.py`
- Test: `tests/unit/test_quality_calibration.py`
- Test: `tests/unit/test_authority_worker_execution.py`

**Interfaces:**
- Produces deterministic calibration reports that never upgrade Provider evidence without an eligible human/golden profile, and worker health snapshots containing exit/fatal/restart evidence.

- [ ] Test stale/revoked/wrong-dimension/wrong-target calibration and Provider non-upgrade.
- [ ] Implement typed calibration samples/profiles/runs/reports with version binding.
- [ ] Move deterministic thresholds behind compiled policy versions.
- [ ] Implement worker supervision snapshot and fatal exit contract without swallowing programming defects.
- [ ] Run focused tests and commit.

### Task 7: CI, Architecture, Catalog, and Documentation

**Files:**
- Modify: `.github/workflows/core-os-ci.yml`
- Create: `tests/architecture/test_pre_provider_functional_boundaries.py`
- Modify: `src/novel_forge/tools/authority_coverage_manifest.py`
- Create/update reports required by the task.

**Interfaces:**
- Produces layered CI jobs for architecture/compile, unit, migration, PostgreSQL Authority, and catalog integrity; real Provider remains manual and disabled.

- [ ] Add static guards for Provider fixture leakage, LocalStorage Authority imports/writes, untrusted query identity, and direct domain/API bypass.
- [ ] Split CI into bounded jobs with a PostgreSQL service and explicit migration tests.
- [ ] Run complete unit, architecture, PostgreSQL, migration, compileall, and diff checks.
- [ ] Regenerate Catalog/Coverage and verify source binding.
- [ ] Update maturity/readiness reports with honest flags and commit.

