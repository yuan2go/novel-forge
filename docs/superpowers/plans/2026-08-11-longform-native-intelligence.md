# Long-form Native Intelligence Implementation Plan

> **For agentic workers:** Execute inline against the named public seams. Do not create a second scheduler, workflow engine, provider runtime, Canon store, knowledge store, or Agent identity.

**Goal:** Add PostgreSQL as-of temporal reads and evidence-backed long-form intelligence to the existing Chapter/Book Authority production plane while consolidating overlapping fiction Skills.

**Architecture:** The accepted Chapter boundary remains the temporal authority. A PostgreSQL projection view exposes accepted state-snapshot changes without copying Canon ownership; `TemporalQueryService` reduces those immutable events as of an inclusive chapter boundary. Deterministic continuity executes inside the existing Canon node, while semantic hook/pacing observations execute inside existing commercial/longform quality nodes and remain qualified Provider evidence. World-consequence and fact-verification outputs remain candidates until existing Story Design/MKAOS/Gate authorities accept them.

**Tech Stack:** Python 3.11+, psycopg 3, PostgreSQL JSONB/views, existing Command Kernel/Chapter Authority/Capability Pack, unittest/pytest.

## Global Constraints

- Root `skills/` is the Skill source of truth; runtime copies are generated only by `make sync-skills`.
- Accepted Canon, Chapter acceptance, AssetVersion, ReviewIssue/Gate, trace and evidence stay authoritative.
- Missing evidence and missing temporal state fail closed; no keyword/regex pacing or fact-quality judge is added.
- Provider candidates never mutate accepted Canon directly.
- `.idea/modules.xml` is never modified or staged.

---

### Task 1: PostgreSQL temporal projection and query service

**Files:**
- Create: `src/novel_forge/storage/migrations/versions/v20260811_0074_longform_native_intelligence.py`
- Create: `src/novel_forge/modules/temporal_query/__init__.py`
- Create: `src/novel_forge/modules/temporal_query/service.py`
- Modify: `src/novel_forge/storage/migrations/versions/__init__.py`
- Modify: `architecture/manifests/migration-manifest.yaml`
- Test: `tests/unit/test_temporal_query_domain.py`
- Test: `tests/integration/test_book_to_chapter_authority_vertical_postgres.py`

**Interfaces:**
- Produces: `TemporalQueryService.character_state_at`, `character_knows_at`, `relationship_at`, `world_state_at`, `power_state_at`, `plot_thread_at`, `foreshadow_state_at`, `pending_promises_at`, and `changes_between`.
- Boundary: queries only `COMMITTED` Book chapter acceptances and ACTIVE/ELIGIBLE/CLEAR snapshot AssetVersions from the requested project; as-of chapter is inclusive and change ranges are `(chapter_from, chapter_to]`.

- [x] Add failing unit tests for explicit entity keys, last-valid-transition reduction, supersession, missing-state status, and future-event exclusion.
- [x] Add migration 0074 with a read-only `authority_temporal_state_event_projection` view joining Chapter acceptance, delegation, Operation output, AssetVersion and snapshot JSON changes.
- [x] Implement `TemporalQueryService` with parameterized project-scoped SQL and deterministic reducers; return `NOT_FOUND` rather than inferred defaults.
- [x] Add PostgreSQL tests for two accepted chapter boundaries, future exclusion, project isolation and deterministic rebuild/rollback semantics.
- [x] Run the focused temporal unit and Book-to-Chapter PostgreSQL tests and require all cases to pass.

### Task 2: Deterministic Canon and continuity validation

**Files:**
- Modify: `src/novel_forge/modules/canon_graph/domain.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Test: `tests/unit/test_stateful_canon_domain.py`
- Test: `tests/integration/test_chapter_authority_scheduler_postgres.py`

**Interfaces:**
- Produces: `validate_deterministic_continuity(...) -> DeterministicContinuityReport` and a `deterministic_continuity_report` auxiliary AssetVersion on `chapter.canon.update`.
- Consumes: accepted historical snapshots and typed candidate changes only; motivation/OOC/emotional plausibility is emitted as `semantic_judgment_required`, never guessed.

- [x] Add red tests for timeline ordering, invalid state transition, identity, dead-character usage, knowledge boundary, relationship transition, promise/foreshadow lifecycle, resource balance, world rule, power transition and graph integrity.
- [x] Implement explicit transition checks and evidence requirements without semantic heuristics.
- [x] Make Canon conflicts derive from the deterministic report and materialize the report as completion evidence.
- [x] Run the focused Canon and Chapter tests and require pass.

### Task 3: Hook and multi-scale pacing intelligence

**Files:**
- Create: `src/novel_forge/modules/content_intelligence/__init__.py`
- Create: `src/novel_forge/modules/content_intelligence/domain.py`
- Create: `src/novel_forge/modules/content_intelligence/service.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Test: `tests/unit/test_content_intelligence_domain.py`

**Interfaces:**
- Produces: schema-backed `HookAnalysis`, `PacingObservation`, `PacingWindowAggregate`, and `PacingDiagnosis` auxiliary outputs from existing commercial/longform quality nodes.
- Semantic inputs must carry Provider evidence spans and qualification; deterministic aggregation computes only counts, ratios, windows and debt from structured observations.

- [x] Add red tests for hook horizons, promise binding, evidence lineage, window boundaries, no-future aggregation and deterministic/semantic separation.
- [x] Normalize Provider commercial evidence into `HookAnalysis`; no universal 1-3 chapter payoff limit.
- [x] Normalize qualified semantic pacing observations and aggregate only structured numeric observations over Scene/Chapter/3/10/Group/Arc/Volume/Book windows.
- [x] Wire auxiliary outputs and completion selectors into the existing Commercial Quality operation, then run focused tests.

### Task 4: World consequence and fact verification candidates

**Files:**
- Extend: `src/novel_forge/modules/content_intelligence/domain.py`
- Extend: `src/novel_forge/modules/content_authority/codecs.py`
- Test: `tests/unit/test_content_intelligence_domain.py`
- Test: `tests/integration/test_content_authority_runtime_postgres.py`

**Interfaces:**
- Produces: `WorldConsequenceGraph` candidate only and immutable Claim/Verification AssetVersions bound to existing SourceDocument/MKAOS evidence spans.
- Fact decisions are `VERIFIED`, `DISPUTED`, `UNSUPPORTED`, `OUTDATED`, or `INSUFFICIENT_EVIDENCE`; no evidence can never produce `VERIFIED`.

- [x] Add red tests for affected-group graph integrity, no Canon mutation, evidence lineage, freshness, conflicting sources and project isolation.
- [x] Reuse AssetVersion and Content Authority rather than adding duplicate claim/verification tables.
- [x] Implement candidate graph validation and fail-closed verification decisions without common-knowledge inference.
- [x] Run focused unit and PostgreSQL tests.

### Task 5: Governed capability catalog

**Files:**
- Modify: `src/novel_forge/modules/production_execution/capabilities.py`
- Modify: `src/novel_forge/modules/production_execution/capability_registry.py`
- Modify: `config/capability_packs/chapter_generation_pack.json`
- Test: `tests/unit/test_production_execution_capabilities.py`
- Test: `tests/unit/test_capability_pack_resolution_compiler.py`

**Interfaces:**
- Registers: `temporal.query`, `canon.validate`, `continuity.validate`, `hook.analyze`, `pacing.analyze`, `pacing.aggregate`, `world.consequence.analyze`, `fact.verify`.
- In-process deterministic capabilities use Authority runtime backends; semantic capabilities use the existing Provider runtime. Capability registration alone is reported as `CODE_EXISTS`, not `PRODUCTION_WIRED`.

- [x] Add red catalog tests for all eight identifiers and correct deterministic/semantic runtime classes.
- [x] Register capability contracts without adding AgentDefinitions.
- [x] Bind only concrete Chapter outputs into the existing Chapter Pack and regenerate exact hashes through the existing compiler workflow.
- [x] Run catalog, validator and compiler tests.

### Task 6: Skill consolidation and governance

**Files:**
- Modify: `skills/canon-continuity-graph/SKILL.md`
- Modify: `skills/narrative-beat-design/SKILL.md`
- Modify: `skills/chapter-outline/SKILL.md`
- Modify: `skills/long-outline/SKILL.md`
- Modify: `skills/quality-review/SKILL.md`
- Create: `skills/longform-temporal-query/SKILL.md`
- Create: `skills/multi-scale-pacing/SKILL.md`
- Create: `skills/world-consequence-modeling/SKILL.md`
- Create: `skills/evidence-fact-verification/SKILL.md`
- Modify: `docs/09-skills/agent-skill-map.md`

**Interfaces:**
- The three prohibited duplicate Skills remain absent. New Skills describe method and runtime boundaries only and map to the concrete services above.

- [x] Merge temporal consistency and deterministic validation method into `canon-continuity-graph`.
- [x] Merge hook horizon/promise/evidence method into the four existing outline/beat/review Skills.
- [x] Add the four genuinely distinct method Skills with concise trigger, input/output, boundary and gate contracts.
- [x] Run `make sync-skills-dry-run`, `make sync-skills`, `make check-skills`, and require no runtime drift.

### Task 7: Production composition and evidence status

**Files:**
- Modify only existing API/Book/Chapter composition files proven necessary by call-chain tests.
- Modify: `docs/product/capability-map.md`

**Interfaces:**
- Exposes temporal reads through PostgreSQL Authority composition; Chapter Canon/Quality auxiliary assets flow through existing Operation/Attempt/Fence/AssetVersion completion and Book acceptance.

- [x] Add the minimal API/composition entry for TemporalQueryService without LocalStorage fallback.
- [x] Trace each capability across Story Planning, Book Planning, Chapter Group, Chapter Plan, Context, Draft, Review, Revision, Re-review, Canon, Quality, Recap, Replan, Reader Outcome and Publish.
- [x] Mark each capability independently as `CODE_EXISTS`, `SKILL_DEFINED`, `FIXTURE_TESTED`, `POSTGRES_TESTED`, `PRODUCTION_WIRED`, `REAL_PROVIDER_PROVEN`, and `LONGFORM_PROVEN`.
- [x] Update only the current capability map; remove no historical report unless current callers prove it dead.

### Task 8: Consolidated verification, review and commit

**Files:** all changed files except `.idea/modules.xml`.

- [x] Run focused unit and PostgreSQL suites after each vertical slice.
- [x] Run `make validate`, the relevant authority PostgreSQL gate, `make check-skills`, architecture manifests, and `git diff --check`.
- [x] Review `git diff 68d4e0021dcc20a209908130687f2da03a9398cf...HEAD` for standards and requirement coverage; fix critical findings.
- [x] Verify `.idea/modules.xml` is unchanged, commit the scoped implementation on `feat/v7-content-intelligence-and-longform-proof`, and report final SHA plus exact test outcomes.
