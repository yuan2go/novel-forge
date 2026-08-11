# Source Import Production Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution under the repository TDD, PostgreSQL Authority, Command Kernel, PEP, and source-isolation contracts. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a recoverable product Source Import runtime that imports an exact Git repository snapshot once, automatically transforms and analyzes changed content, emits governed MKAOS Candidates, and selectively reprocesses without reimporting bytes.

**Architecture:** Add bounded orchestration Operations to the existing Source worker. Repository/job/file/checkpoint tables coordinate work while existing Blob, Source, Observation, Candidate, Card, and Pack Authorities remain the only business truth. External fetch and object writes use ExternalEffect; model work uses Attempt-bound ProductionExecutionGateway requests with persistent usage/cost evidence.

**Tech Stack:** Python 3.12, PostgreSQL forward-only migration 0076, existing Command Kernel and AuthorityUnitOfWork, Git CLI adapter, MinIO/local fixture object store, FastAPI/Pydantic, pytest/unittest, Docker Compose.

## Global Constraints

- Preserve `IMPORT ONCE / PROCESS MANY / REPROCESS WITHOUT REIMPORT`.
- PostgreSQL is production Authority; no LocalStorage or Markdown production authority.
- Raw/normalized/chunk bytes remain object-store-only and are generation-context forbidden.
- All model execution goes through ExternalEffect-backed PEP with immutable Prompt/Skill/schema/provider identity and usage/cost evidence.
- Unknown rights, encoding, parser, Provider route, or stale fence fail closed.
- Human approval remains required before KnowledgeCard activation.
- Exact replay and partial retry must not duplicate Blob, Source, Transform, Observation, Candidate, or Provider calls.
- Fixture evidence cannot prove real Provider, longform, multi-book, production, or project admission.

---

### Task 1: Repository discovery and deterministic transform domain

**Files:**
- Create: `src/novel_forge/modules/source_import/domain.py`
- Create: `src/novel_forge/modules/source_import/git_adapter.py`
- Create: `src/novel_forge/modules/source_import/object_reader.py`
- Test: `tests/unit/test_source_import_domain.py`
- Test: `tests/unit/test_source_import_git_adapter.py`

**Interfaces:**
- Produces `SourceImportPolicy`, `RepositoryFile`, `RepositorySnapshot`, `ManifestDiff`, `normalize_source_bytes()`, `chunk_normalized_text()`, and `GitRepositoryExternalEffectAdapter`.
- Git adapter returns exact commit and metadata only; `read_blob(oid)` returns bytes from the controlled cache for subsequent verified upload.

- [ ] Write failing tests for GitHub URL normalization, exact SHA pinning, local fixture repository discovery, symlink/submodule/LFS/binary/large-file blocking, encoding, structural chunks, and manifest diff states.
- [ ] Implement bounded non-interactive Git discovery and read-only cached blob access.
- [ ] Implement deterministic decoding/normalization/chunking and SHA-256 policy identities.
- [ ] Run `pytest tests/unit/test_source_import_domain.py tests/unit/test_source_import_git_adapter.py -q` and require all tests pass.

### Task 2: PostgreSQL import and reprocessing execution protocol

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260811_0076_source_import_runtime.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Create: `src/novel_forge/storage/source_import_repositories.py`
- Modify: `src/novel_forge/storage/authority_repositories.py`
- Test: `tests/unit/test_source_import_runtime_migration.py`

**Interfaces:**
- Persists import jobs, immutable repository snapshots/files/diffs, stage checkpoints, analysis work, extraction work, and per-item reprocessing lifecycle.
- Extends SourceTransform with normalized Blob identity and executable reprocessing specifications.

- [ ] Add schema tests for project/workspace scope, immutable snapshot uniqueness, per-stage idempotency, legal statuses, no raw-text columns, and executable reprocessing lifecycle.
- [ ] Add the forward-only migration and register it as head in code and manifest.
- [ ] Add focused repository methods with project-scoped joins and idempotent checkpoint transitions.
- [ ] Run migration and architecture tests to green.

### Task 3: Content-addressed Blob and automatic Source Transform execution

**Files:**
- Modify: `src/novel_forge/modules/command_kernel/asset_runtime.py`
- Modify: `src/novel_forge/modules/source_authority/domain.py`
- Modify: `src/novel_forge/modules/source_authority/application.py`
- Modify: `src/novel_forge/modules/source_authority/definitions.py`
- Modify: `src/novel_forge/api/models.py`
- Create: `src/novel_forge/modules/source_import/application.py`
- Test: `tests/integration/test_source_import_postgres.py`

**Interfaces:**
- Adds deterministic Blob reservation replay, normalized-text Blob binding, automatic chunk Blob upload, and `SourceImportApplication` discovery/file Operations.
- File processing calls `SourceAuthorityApplication` for SourceDocument and SourceTransform commits; it never inserts those business rows directly.

- [ ] Prove same content at two paths creates one SourceDocument and one transform, with immutable per-path manifest lineage.
- [ ] Prove same commit replay creates no new Source/Transform/Blob effects.
- [ ] Prove a new commit processes only added/modified content and marks removed/renamed entries without deleting history.
- [ ] Inject failure after Blob upload and after Source commit; retry must reuse completed work.

### Task 4: ExternalEffect-backed PEP deconstruction and MKAOS extraction

**Files:**
- Create: `src/novel_forge/modules/source_import/execution.py`
- Modify: `src/novel_forge/modules/source_import/application.py`
- Modify: `src/novel_forge/modules/source_authority/deconstruction.py`
- Modify: `src/novel_forge/modules/mkaos_authority/domain.py`
- Test: `tests/integration/test_source_import_intelligence_postgres.py`

**Interfaces:**
- Produces a domain-owned PEP preparer and `DomainExecutionPort` for `deconstruction.observe` and `mkaos.*.extract` using the existing Gateway session/backends/evidence store.
- Materializes execution evidence AssetVersions whose bindings exactly match Observation/Candidate Authority validation.

- [ ] Freeze source-evidence input manifests, Prompt/Skill/schema/policy versions, route snapshot, budget reservation, and ExternalEffect before every model call.
- [ ] Validate structured Observation output, commit it through Source Authority, then freeze an Observation-only abstraction context and commit Candidate through MKAOS Authority.
- [ ] Prove provider retry/restart reuses the prior execution identity and measured usage.
- [ ] Prove raw source fields cannot reach Candidate, KnowledgeCard, Pack, or Context.

### Task 5: Executable reprocessing lifecycle

**Files:**
- Modify: `src/novel_forge/modules/source_authority/deconstruction_application.py`
- Modify: `src/novel_forge/modules/source_authority/query.py`
- Modify: `src/novel_forge/modules/source_import/application.py`
- Test: `tests/integration/test_source_reprocessing_executor_postgres.py`

**Interfaces:**
- Plan items retain `execution_spec`; `SourceImportApplication` applies `REUSE`, recompute, reabstract, regovern, and projection rebuild actions idempotently.

- [ ] Prove Analyzer V1 to V2 schedules only the affected dimension and its descendants.
- [ ] Prove `REUSE` creates no child work or Provider effect.
- [ ] Prove partial progress, duplicate apply, expired lease, failure, and resume retain successful item checkpoints.
- [ ] Keep `REGOVERN` blocked on explicit review and never auto-approve.

### Task 6: Product API, composition, queries, legacy isolation, and admission

**Files:**
- Create: `src/novel_forge/api/routers/source_imports.py`
- Modify: `src/novel_forge/api/models.py`
- Modify: `src/novel_forge/api/authority_app.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: `src/novel_forge/workers/source_authority.py`
- Modify: `architecture/manifests/production-entry-manifest.yaml`
- Modify: `architecture/manifests/worker-manifest.yaml`
- Modify: `architecture/manifests/legacy-surface-manifest.yaml`
- Test: `tests/unit/test_source_import_api.py`

**Interfaces:**
- Adds preview/create/list/detail/files/resume/retry product routes and source/MKAOS/reprocessing status projections.
- Worker composition injects Git, object-store read/write, Source/MKAOS Authorities, and PEP dependencies; controlled runtime fails startup if any required dependency is absent.

- [ ] Prove preview freezes commit/manifest and estimates work without Source/Provider writes.
- [ ] Prove API admission returns an Import Job instead of exposing Blob/Chunk construction.
- [ ] Prove the Authority app does not mount legacy LocalStorage import routes.
- [ ] Extend admission with real import/reprocessing evidence while preserving `CAPABILITY_IMPLEMENTED` versus `PROJECT_QUALIFIED`.

### Task 7: End-to-end validation, review, and evidence report

**Files:**
- Create: `tests/integration/test_source_import_e2e_postgres.py`
- Modify: `architecture/manifests/test-manifest.yaml`
- Create: `docs/reports/source-import-runtime-2026-08-11.md`

**Interfaces:**
- Controlled fixture repository proves Repository -> Blob -> Source -> Transform -> Observation -> Candidate -> Approval -> Card -> Pack lineage and fault recovery.

- [ ] Run focused unit and PostgreSQL integration tests.
- [ ] Run architecture manifests, `make validate`, `make postgres-authority-test`, and `make test` on the final worktree.
- [ ] Inspect credentials without printing secrets; run a real small Provider/GitHub qualification only when configured.
- [ ] Review the full diff for direct SQL Authority bypass, raw-source leakage, silent fallback, dead abstractions, and protected `.idea/modules.xml` state.
- [ ] Commit the completed work atomically and record exact starting/final SHAs plus truthful readiness flags.
