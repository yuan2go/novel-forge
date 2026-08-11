# Governed Data Import, Deconstruction, And MKAOS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: execute this plan inline under the repository Command Kernel, PostgreSQL Authority, source-isolation, and evidence-bound acceptance rules. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the current Source and MKAOS Authorities into an import-once, versioned-deconstruction, selectively-reprocessable production chain without adding a parallel runtime or knowledge database.

**Architecture:** Keep immutable Blob, SourceDocument, SourceTransform, AssetVersion, Command Kernel, production execution evidence, MKAOS Candidate/Approval/Card/Pack, and the existing Source/MKAOS workers. Add the missing Source Authority subdomain for stable evidence spans, versioned single-dimension observations, immutable dependency edges, deterministic reprocessing plans, and fail-closed data-import admission. Knowledge Packs remain rebuildable projections; raw and normalized source text remain Blob-only evidence and are never Context inputs.

**Tech Stack:** Python 3.12, PostgreSQL forward-only migrations, existing AuthorityUnitOfWork/Command Kernel/AssetVersion repositories, FastAPI/Pydantic contracts, unittest/pytest, Docker Compose.

## Global Constraints

- Preserve `IMPORT ONCE / PROCESS MANY / REPROCESS WITHOUT REIMPORT`.
- PostgreSQL is production Authority; LocalStorage paths remain legacy/development/migration only.
- Every provider-backed observation must bind governed execution evidence; fixtures are denied by production defaults.
- Observation is evidence-layer intelligence and is never a reusable Knowledge Asset.
- MKAOS Candidate/Approval/Card/Pack remains the only canonical reusable knowledge activation path.
- No raw, normalized, quoted, or source-specific protected expression may enter KnowledgePack or ContextBundle.
- Exact replay reuses the prior Operation and AssetVersion; version upgrades retain history and invalidate only descendants.
- Do not claim real-provider, longform, multi-book, or production proof from fixture tests.

---

### Task 1: Source Deconstruction Domain And Prompt Contracts

**Files:**
- Create: `src/novel_forge/modules/source_authority/deconstruction.py`
- Create: `tests/unit/test_source_deconstruction_domain.py`
- Modify: `src/novel_forge/modules/production_execution/capabilities.py`
- Modify: `src/novel_forge/modules/production_execution/capability_registry.py`

**Interfaces:**
- Produces `AnalyzerContract`, `ObservationEvidenceSpan`, `ObservationScope`, `ReprocessingTarget`, `default_analyzer_contracts()`, `validate_observation_payload()`, and stable SHA-256 fingerprint helpers.
- Registers `deconstruction.observe` as a governed Source-domain production-execution capability.

- [ ] Define all required dimensions and scales, including `CROSS_BOOK_PATTERN`.
- [ ] Define analyzer prompt contracts that request one dimension at one scale, evidence references, confidence, and no reusable-knowledge claim.
- [ ] Validate bounded structured observations recursively against raw-source leakage keys.
- [ ] Unit-test stable fingerprints, per-dimension separation, multi-scale rules, and forbidden-source fields.

### Task 2: PostgreSQL Observation, Lineage, Invalidation, And Plan Protocol

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260811_0075_source_deconstruction_intelligence.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Modify: `src/novel_forge/storage/source_authority_repositories.py`

**Interfaces:**
- Persists stable evidence-span addresses, immutable Observation AssetVersions, Observation inputs, generic content dependency edges, immutable invalidation records, and reprocessing-plan items.
- Uses project/workspace/AssetVersion/Operation foreign keys and project-scope guards; no raw source column exists.

- [ ] Add forward-only schema and indexes for observation lookup, current-version selection, lineage traversal, and admission queries.
- [ ] Add repository reads/writes with project-scoped joins and explicit active/superseded projection changes.
- [ ] Add schema tests for uniqueness, cross-project rejection, and no raw-source storage columns.

### Task 3: Command-Kernel Observation Commit And Selective Reprocessing

**Files:**
- Create: `src/novel_forge/modules/source_authority/deconstruction_application.py`
- Modify: `src/novel_forge/modules/source_authority/application.py`
- Modify: `src/novel_forge/modules/source_authority/definitions.py`
- Modify: `src/novel_forge/modules/source_authority/scheduler.py`
- Modify: `src/novel_forge/modules/source_authority/query.py`
- Modify: `src/novel_forge/modules/source_authority/__init__.py`
- Modify: `src/novel_forge/workers/source_authority.py`

**Interfaces:**
- Adds `source.deconstruction.observation.commit` and `source.deconstruction.reprocessing.plan` to the existing Source worker.
- `CommitDeconstructionObservationCommand` consumes governed chunk/Observation AssetVersions plus one analyzer contract and one structured dimension result.
- `PlanSourceReprocessingCommand` compares desired analyzer fingerprints with current observations and emits `REUSE`, `RECOMPUTE`, and `REBUILD_PROJECTION` items.

- [ ] Admit commands with content-derived idempotency and frozen input AssetVersions.
- [ ] Materialize evidence-only Observation and operational Plan AssetVersions under current attempt fences.
- [ ] On analyzer upgrade, preserve old observations, supersede only the matching active analyzer scope, and register selective descendant invalidations.
- [ ] Reuse lower-level observations for aggregate scales and reject whole-book raw-source prompts.
- [ ] Exercise duplicate command, exact replay, retry, worker restart, stale fence, and partial invalidation behavior.

### Task 4: MKAOS Observation Lineage, Rebuildable Packs, And Source Isolation

**Files:**
- Modify: `src/novel_forge/modules/mkaos_authority/application.py`
- Modify: `src/novel_forge/modules/mkaos_authority/domain.py`
- Modify: `src/novel_forge/storage/mkaos_authority_repositories.py`
- Modify: `src/novel_forge/api/models.py`
- Modify: `src/novel_forge/api/routers/mkaos_authority.py`
- Modify: `tests/integration/test_mkaos_authority_postgres.py`

**Interfaces:**
- `CommitKnowledgeCandidateCommand.observation_asset_version_ids` binds Candidate lineage to governed Observations while retaining the existing direct-evidence path as `MIGRATION_ONLY`.
- Candidate, governance decision, card, and pack commits record immutable dependency edges used by selective invalidation.
- Pack rebuild uses explicit versions and supersession rather than silent overwrite.

- [ ] Require Observation lineage on the production API and tag direct SourceChunk candidate commits as migration-only compatibility.
- [ ] Persist Observation-to-Candidate-to-Card-to-Pack dependency edges.
- [ ] Reject stale/superseded/rejected observations and any source-expression field before Candidate admission.
- [ ] Add an explicit Pack supersede/rebuild contract if a target already has an active stale projection.

### Task 5: API, Admission Qualification, Skill Governance, And Cleanup

**Files:**
- Modify: `src/novel_forge/api/models.py`
- Modify: `src/novel_forge/api/routers/source_authority.py`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `architecture/manifests/production-entry-manifest.yaml`
- Modify: `architecture/manifests/test-manifest.yaml`
- Modify: `skills/hot-novel-deconstruction/SKILL.md`
- Modify: `skills/mkaos-knowledge-asset-os/SKILL.md`
- Modify: `skills/anti-copy-abstraction/SKILL.md`
- Create: `docs/reports/data-import-production-chain.md`

**Interfaces:**
- Exposes observation commit/list, reprocessing plan/list, and project-scoped `DataImportAdmissionReport`.
- Admission returns `DATA_IMPORT_READY=false` unless every required capability has current, non-fixture, cross-project-safe, cost-traceable database evidence.

- [ ] Add API schemas/routes and manifest entries for the two Source Authority operations and admission query.
- [ ] Classify old LocalStorage decomposition/MKAOS paths as already isolated compatibility; remove only newly confirmed dead bypasses.
- [ ] Update canonical root Skills with structured Observation-vs-Knowledge, scale routing, prompt splitting, aggregation reuse, and originality gates; sync generated runtime copies.
- [ ] Run focused unit/integration/architecture tests, full test/validation targets, PostgreSQL Authority suite, Compose smoke, skill drift, and diff hygiene.
- [ ] Bind the final report to exact SHA and keep real-provider/longform/multi-book/production claims false unless corresponding evidence is produced.
