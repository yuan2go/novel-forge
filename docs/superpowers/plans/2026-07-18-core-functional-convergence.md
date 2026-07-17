# Novel OS Core Functional Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge the five approved core workstreams onto versioned, project-scoped PostgreSQL Authority contracts while deepening the missing creative and long-form domain capabilities.

**Architecture:** Storage-free domain cores own business rules. PostgreSQL Authority handlers bind frozen input AssetVersions to immutable output AssetVersions and Completion evidence. Existing LocalStorage services remain temporary compatibility adapters and may reuse, but never fork, those rules.

**Tech Stack:** Python 3.11+, stdlib unittest, dataclasses/typed protocols, PostgreSQL/psycopg, existing Command Kernel, Generic ExternalEffect, Next.js only for minimal existing-console exposure.

## Global Constraints

- Current local HEAD is the only code source; no remote access or destructive Git commands.
- PostgreSQL is the target production authority; no new LocalStorage write-through, JSON authority, dual write, or silent fallback.
- Mock/deterministic evidence must remain labelled fixture evidence.
- Do not run real-provider 10/30/100 chapter, multi-book, platform publish, or high-cost evaluation.
- Preserve user changes and commit small reviewable vertical slices without pushing.

---

### Task 1: Restore a reproducible baseline

**Files:**
- Create: `src/novel_forge/workers/tasks.py`
- Modify: `tests/unit/test_schemas.py`
- Modify: `pyproject.toml`
- Regenerate: `docs/reports/postgresql-authority-coverage-baseline.json`
- Regenerate: `docs/reports/postgresql-operation-definition-catalog.json`

**Interfaces:**
- Produces: stable imports from `novel_forge.workers.tasks`; exact schema registry contract; a test extra containing API and PostgreSQL dependencies; HEAD-bound Authority evidence.

- [ ] Add a compatibility module that re-exports the public worker task symbols from `legacy_tasks` without introducing a second implementation.
- [ ] Change the schema registry test from a stale exact count to required-type and lower-bound assertions.
- [ ] Add a `test` optional dependency group that includes API and PostgreSQL extras used during unittest discovery.
- [ ] Regenerate Authority coverage/catalog at current source HEAD and run its architecture test.
- [ ] Run focused worker/schema/authority tests, `git diff --check`, and commit `fix(test): restore reproducible local baseline`.

### Task 2: Add canonical OperationDefinition maturity

**Files:**
- Modify: `src/novel_forge/tools/authority_coverage_manifest.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Test: `tests/unit/test_authority_coverage_operation_mapping.py`
- Test: `tests/unit/test_chapter_authority_definitions.py`

**Interfaces:**
- Produces: `definition_status`, `evidence_status`, `input_contract`, `output_contract`, `projection_consumers`, `migration_owner`, and `legacy_entrypoints` on every catalog definition.

- [ ] Write failing tests for candidate, mapped, handler-bound, enabled, integration-proven, and production-verified states.
- [ ] Derive maturity from concrete handler/integration/provider evidence; retain `migration_status` as compatibility output.
- [ ] Ensure no empty handlers are generated for candidates.
- [ ] Regenerate the catalog, run focused tests, and commit `feat(authority): model operation definition maturity`.

### Task 3: Extract and bind governed Context Domain Core

**Files:**
- Create: `src/novel_forge/modules/context_builder/domain.py`
- Modify: `src/novel_forge/modules/context_builder/service.py`
- Modify: `src/novel_forge/modules/chapter_authority/domain_handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/handlers.py`
- Modify: `src/novel_forge/modules/chapter_authority/definitions.py`
- Test: `tests/unit/test_context_builder_domain.py`
- Test: `tests/unit/test_chapter_authority_domain_handlers.py`
- Test: `tests/integration/test_postgresql_only_chapter_slice.py`

**Interfaces:**
- Consumes: versioned candidate descriptors and `ContextProfile`.
- Produces: `build_authoritative_context(ContextBuildInput) -> ContextBuildResult` containing frozen selected/rejected versions, token accounting, digest, isolation, policies, invalidation keys, and Operation lineage.

- [ ] Characterize existing profile/isolation/budget behavior with pure failing tests.
- [ ] Implement the storage-free selector and make the LocalStorage service adapt candidates into it.
- [ ] Replace the simplified chapter Context handler with the same domain core and require a governed KnowledgePack/source policy in strict definitions.
- [ ] Prove cross-project, revoked, stale, quarantine, review-only, structure-only, and token-budget behavior.
- [ ] Run focused unit/PostgreSQL tests and commit `feat(authority): migrate governed context build`.

### Task 4: Bind review, revision, canon, quality, and internal publishing cores

**Files:**
- Create: `src/novel_forge/modules/review/domain.py`
- Create: `src/novel_forge/modules/revision/domain.py`
- Create: `src/novel_forge/modules/canon_graph/domain.py`
- Create: `src/novel_forge/modules/content_quality_loop/domain.py`
- Create: `src/novel_forge/modules/publishing/domain.py`
- Modify: corresponding existing `service.py` files and `chapter_authority` handlers/definitions.
- Test: focused domain, Authority handler, Completion, qualification, and PostgreSQL slice tests.

**Interfaces:**
- Produces: normalized ReviewIssue decisions, revision resolution, canon candidate/conflict/impact output, quality evidence aggregation, and publish eligibility/release manifest without storage calls.

- [ ] Write behavior-parity tests for existing mature rules and negative Completion cases.
- [ ] Extract one rule source per domain and adapt compatibility services.
- [ ] Bind requested core catalog definitions to typed handlers.
- [ ] Add a publish-gate node before export; require latest effective review/canon/source/originality/quality evidence and verified Blob metadata.
- [ ] Prove revoked qualification, stale versions, idempotent replay, rollback/failure, and project isolation.
- [ ] Commit domain migrations as separate `feat(authority)` slices.

### Task 5: Govern MKAOS selection and source eligibility

**Files:**
- Create: `src/novel_forge/modules/mkaos/selection_domain.py`
- Create: `src/novel_forge/modules/source_intake/eligibility_domain.py`
- Modify: `src/novel_forge/modules/mkaos/service.py`
- Modify: `src/novel_forge/modules/source_intake/service.py`
- Modify: `src/novel_forge/modules/source_intake/diff_repair.py`
- Test: `tests/unit/test_mkaos_authority_selection.py`
- Test: `tests/unit/test_source_eligibility_domain.py`

**Interfaces:**
- Produces: explainable selector decisions and immutable eligibility decisions with use-mode downgrade/fail-closed outcomes.

- [ ] Test relevance/stage/genre/narrative/trust/risk/quality/freshness/history/redundancy/conflict/project scoring.
- [ ] Test license, commercial use, raw/generation permission, privacy, injection, trust, project, stale and quarantine enforcement.
- [ ] Integrate selector/eligibility into the Context domain core.
- [ ] Produce ChangeImpactReport and RegenerationPlan proposals without mutating accepted prose.
- [ ] Commit `feat(mkaos): add governed production knowledge selection` and `feat(source): enforce source eligibility and regeneration planning`.

### Task 6: Add bounded connector contracts

**Files:**
- Modify: `src/novel_forge/modules/source_intake/connector_adapters.py`
- Modify: `src/novel_forge/modules/source_intake/connector_runner.py`
- Test: `tests/unit/test_source_connectors.py`

**Interfaces:**
- Produces: no-default-network Git/RSS/public-domain plans and fixture adapters using Generic ExternalEffect-shaped intents/receipts, limits, checksum, policy, injection and diff evidence.

- [ ] Test allowlist, timeout, rate limit, size/type limit, checksum, license, robots/ToS evidence, injection scanning, receipt, audit, and invalidation recommendations.
- [ ] Implement contracts and deterministic local/test adapters only.
- [ ] Commit `feat(source): add controlled connector lifecycle contracts`.

### Task 7: Implement Creative candidate and proposal core

**Files:**
- Create: `src/novel_forge/modules/creative/domain.py`
- Create: `src/novel_forge/modules/creative/__init__.py`
- Modify: `src/novel_forge/schemas/assets.py`
- Modify: `src/novel_forge/schemas/__init__.py`
- Modify: Authority catalog mappings.
- Test: `tests/unit/test_creative_domain.py`

**Interfaces:**
- Produces: validated CreativeBrief, mechanism fingerprints, clustered candidates, CandidateEvaluation, NoveltyReport, and ProjectProposal.

- [ ] Test missing goals, mechanism differentiation, clustering, similarity risk, long-form capacity, and cross-project rejection.
- [ ] Implement deterministic domain evaluation over caller/provider-supplied candidates; do not add a second model protocol.
- [ ] Bind `creative.*` definitions with typed contracts and fixture-labelled handlers.
- [ ] Commit `feat(creative): add governed candidate and project proposal core`.

### Task 8: Deepen World and Character domain cores

**Files:**
- Create: `src/novel_forge/modules/worldbuilding/domain.py`
- Create: `src/novel_forge/modules/characters/domain.py`
- Modify: existing world/character services to become compatibility adapters.
- Modify: schemas for relationship state and validation reports.
- Test: `tests/unit/test_worldbuilding_domain.py`
- Test: `tests/unit/test_character_domain.py`

**Interfaces:**
- Produces: goal-driven WorldBible rules and conflict reports; deep character profiles, relationship edges/states, and validation reports.

- [ ] Test rule conflict, missing cost, infinite capability, absent character goal/agency/cost/relationship, and project isolation.
- [ ] Implement storage-free builders/validators consuming CreativeBrief, approved proposal, theme, and world inputs.
- [ ] Adapt existing services and bind Authority definitions.
- [ ] Commit separate world and character feature commits.

### Task 9: Implement Meaning, Theme, and Ending cores

**Files:**
- Create: `src/novel_forge/modules/theme/domain.py`
- Create: `src/novel_forge/modules/theme/__init__.py`
- Create: `src/novel_forge/modules/ending/domain.py`
- Create: `src/novel_forge/modules/ending/__init__.py`
- Modify: schemas and Context profiles.
- Test: `tests/unit/test_theme_domain.py`
- Test: `tests/unit/test_ending_domain.py`

**Interfaces:**
- Produces: ThemeQuestion, ValueConflict, ThemeArc, AntiPreachingReport, ClosurePlan, PayoffMatrix, EndingQualityReport and ReviewIssue candidates.

- [ ] Test vague questions, missing value conflict, preaching evidence, costless choice, unpaid promises/foreshadows/arcs, sudden victory, antagonist collapse, and mechanical summary.
- [ ] Implement evidence-locator-based deterministic gates and stage-specific Context selection.
- [ ] Bind `theme.*` and `ending.*` Authority definitions.
- [ ] Commit theme and ending slices separately.

### Task 10: Implement long-form semantic reports and recap consumption

**Files:**
- Create: `src/novel_forge/modules/longform_stability/semantic_domain.py`
- Modify: `src/novel_forge/modules/longform_stability/service.py`
- Modify: `src/novel_forge/modules/longform_recap/service.py`
- Modify: schemas.
- Test: `tests/unit/test_longform_semantic_domain.py`
- Test: `tests/unit/test_longform_recap_agent.py`

**Interfaces:**
- Produces: motivation drift, entity merge proposal, payoff, world rule, power, pattern repetition, arc progress, narrative debt, next-window policy and review-focus outputs.

- [ ] Implement and test every approved positive/negative semantic fixture with evidence and project/version scope.
- [ ] Convert high-impact findings to ReviewIssue candidates and future ChapterPlan constraints.
- [ ] Make 5/10-chapter recap consume semantic reports without mutating accepted chapters.
- [ ] Bind `longform.*` definitions and commit focused feature slices.

### Task 11: Converge projections, architecture guards, and reports

**Files:**
- Modify: ChapterProductionRun projection/query code.
- Modify: architecture tests and Authority coverage evidence.
- Create/update: all reports requested under `docs/reports/` and `docs/project-current-state.md`.

**Interfaces:**
- Produces: rebuildable operator projections and accurate six-state capability evidence.

- [ ] Prove Completion never reads projections and legacy writes cannot masquerade as migrated handlers.
- [ ] Scan for duplicate domain rules, production LocalStorage writes, Context bypasses, and candidate/implemented mislabelling.
- [ ] Run compile, unit, architecture, focused PostgreSQL, schema, skill-drift and web static checks.
- [ ] Record real provider and longform as not run, publish convergence reports, review the complete diff, and commit docs.

