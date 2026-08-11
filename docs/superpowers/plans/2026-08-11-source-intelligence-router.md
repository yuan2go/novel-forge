# Source Intelligence Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Execute inline under the repository TDD, PostgreSQL Authority, PEP, source-isolation and recovery contracts. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically classify each logical source document, resolve a type-specific versioned methodology plan, and selectively recompute Source Observations and MKAOS outputs without coupling analysis semantics to Source identity.

**Architecture:** Extend Source Authority with immutable Profile and AnalysisPlan assets while Source Import owns profiling/planning orchestration.  PEP performs bounded classification and analysis with exact canonical Skill text; PostgreSQL dependency lineage and current-asset replay decide reuse and invalidation.

**Tech Stack:** Python 3.12, PostgreSQL forward-only migration 0081, Command Kernel, ProductionExecutionGateway, FastAPI/Pydantic, pytest/unittest.

## Global Constraints

- PostgreSQL and AssetVersion remain the only production Authority.
- Raw and normalized Source text remain object-store-only and generation-context forbidden.
- Paths are classification evidence only, never hard-coded classification truth.
- Every model call uses ExternalEffect, PEP, budget/cost evidence and immutable Attempt contracts.
- UNKNOWN, MIXED, low-confidence, missing capability and methodology drift fail closed.
- A governance override requires a reason and decision reference and never changes Source identity.
- Full anthology splitting is deferred; current scope is explicitly `FILE_DOCUMENT`, never implicitly Book.

---

### Task 1: Profiling and methodology domain

**Files:**
- Create: `src/novel_forge/modules/source_import/profiling.py`
- Create: `src/novel_forge/modules/source_import/methodologies.py`
- Replace: `src/novel_forge/modules/source_import/analysis_profiles.py`
- Modify: `src/novel_forge/modules/source_import/domain.py`
- Test: `tests/unit/test_source_intelligence_routing.py`

**Interfaces:**
- Produces `SourceContentType`, `LogicalDocumentScope`, `SourceIntelligencePolicy`, `ClassificationEvidence`, `SourceMethodologyRegistry`, `ResolvedAnalysisStrategy`, and plan tasks bound to `analysis_plan_asset_version_id`.
- `SourceImportPolicy.policy_hash` excludes every analysis field.

- [ ] Write tests for taxonomy validation, deterministic signal extraction, bounded stratified samples, confidence/margin admission, governance override, heterogeneous strategy resolution, exact Skill digest loading and missing/drifted Skill failure.
- [ ] Implement the pure profiling and methodology registry contracts.
- [ ] Run `pytest -q tests/unit/test_source_intelligence_routing.py tests/unit/test_source_import_domain.py` and require PASS.

### Task 2: PostgreSQL Profile and AnalysisPlan Authority

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260811_0081_source_intelligence_router.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `src/novel_forge/storage/migrations/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Create: `src/novel_forge/storage/source_profile_repositories.py`
- Modify: `src/novel_forge/storage/source_import_repositories.py`
- Test: `tests/unit/test_source_intelligence_router_migration.py`

**Interfaces:**
- Persists `authority_source_content_profile`, profile inputs, `authority_source_analysis_plan`, import intelligence policy/override, file Profile/Plan projections and new lineage/invalidation values.
- Renames the old import-job `analysis_profile` projection to `legacy_analysis_profile`; runtime code does not read it.

- [ ] Assert migration head, no raw-text columns, scope triggers, enums, indexes and analysis/source identity separation.
- [ ] Implement and register forward-only migration 0081.
- [ ] Implement project-scoped replay/current/commit repository methods.
- [ ] Run migration-chain and architecture manifest tests.

### Task 3: Source Authority commit boundaries

**Files:**
- Create: `src/novel_forge/modules/source_authority/profiling_application.py`
- Modify: `src/novel_forge/modules/source_authority/application.py`
- Modify: `src/novel_forge/modules/source_authority/definitions.py`
- Modify: `src/novel_forge/modules/source_authority/deconstruction.py`
- Modify: `src/novel_forge/modules/source_authority/deconstruction_application.py`
- Modify: `src/novel_forge/modules/source_authority/__init__.py`
- Test: `tests/integration/test_source_intelligence_router_postgres.py`

**Interfaces:**
- Adds `CommitSourceContentProfileCommand` and `CommitSourceAnalysisPlanCommand`.
- Observation commit requires and records `analysis_plan_asset_version_id`.
- Superseding Profile/Plan invalidates active descendants through existing dependency/invalidation records.

- [ ] Prove Profile and Plan exact replay, immutable supersession, cross-project rejection and no raw content.
- [ ] Prove Profile→Plan→Observation dependency edges and invalidation causes.
- [ ] Run focused Source Authority PostgreSQL tests.

### Task 4: PEP classification and exact methodology materialization

**Files:**
- Modify: `src/novel_forge/modules/production_execution/capabilities.py`
- Modify: `src/novel_forge/modules/production_execution/capability_registry.py`
- Modify: `src/novel_forge/modules/source_import/execution_contracts.py`
- Modify: `src/novel_forge/modules/source_import/execution.py`
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Test: `tests/unit/test_production_execution_capabilities.py`
- Test: `tests/integration/test_source_intelligence_router_postgres.py`

**Interfaces:**
- Registers `source.content.classify` and executes classification through existing PEP.
- `_ExecutionSpec` freezes methodology ID/version/content/digest/contract hash.
- Provider resolver loads only bounded Source sample spans from the object store.

- [ ] Prove classifier schema/output validation and fail-closed malformed output.
- [ ] Prove two analyzer Skills produce different exact materialized text/digests.
- [ ] Prove missing capability and Skill digest mismatch stop before Provider dispatch.
- [ ] Run PEP, capability and Source classifier tests.

### Task 5: Production orchestration, replay and reanalysis

**Files:**
- Modify: `src/novel_forge/modules/source_import/application.py`
- Modify: `src/novel_forge/modules/source_import/definitions.py`
- Modify: `src/novel_forge/modules/source_import/query.py`
- Modify: `src/novel_forge/modules/source_import/scheduler.py`
- Modify: `src/novel_forge/modules/source_import/__init__.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/workers/source_import.py`
- Test: `tests/integration/test_source_intelligence_router_postgres.py`

**Interfaces:**
- Adds durable `PROFILING` and `ANALYSIS_PLANNING` child Operations.
- New and reused transforms both reconcile the current intelligence desired state.
- Pre-dispatch Authority lookups replay exact Profile, Plan, Observation and Candidate contracts across import jobs.

- [ ] Prove heterogeneous repository routing through the real scheduler composition.
- [ ] Prove exact replay creates no new model effects.
- [ ] Prove classifier/routing/methodology change creates no Blob/Source/Transform writes but produces new analysis lineage.
- [ ] Prove low-confidence and UNKNOWN stop without Analyzer Operations.

### Task 6: Product API and audit queries

**Files:**
- Modify: `src/novel_forge/api/models.py`
- Modify: `src/novel_forge/api/routers/source_import.py`
- Modify: `src/novel_forge/api/routers/source_authority.py`
- Modify: `src/novel_forge/modules/source_authority/query.py`
- Modify: `tests/unit/test_authority_api_surface.py`

**Interfaces:**
- Import accepts separate `intelligence_policy` and optional governance override.
- Queries expose Profile evidence/confidence, Plan methodology lineage and status.

- [ ] Prove API no longer accepts repository-wide analysis profile as Source policy.
- [ ] Prove audit queries are project-scoped and expose no Source text.
- [ ] Run API surface and PostgreSQL query tests.

### Task 7: Validation, drift checks and evidence

**Files:**
- Modify: `docs/reports/data-import-production-chain-2026-08-11.md`
- Modify: relevant architecture manifests when required by validation.

**Interfaces:**
- Final evidence records exact start/final SHA and truthful fixture/provider limits.

- [ ] Run focused unit and PostgreSQL integration suites.
- [ ] Run `make validate`, Source/MKAOS/capability regression tests, migration tests and Skill drift checks.
- [ ] Review the diff for Authority bypass, raw-source leakage, silent fallback, stale fixed-profile semantics and unrelated changes.
- [ ] Commit implementation and record the exact final HEAD.
