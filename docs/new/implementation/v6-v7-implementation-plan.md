# Novel Forge V6/V7 Implementation Plan

This plan follows the user-required Loop mode: small scope, explicit plan, implement, test, fix, report, then continue. Phase changes require confirmation when they introduce broad architecture changes.

## Execution Rules

- `docs/new` is the latest design source.
- Preserve all V5 capabilities.
- Do not add SaaS features: login, members, payment, invitations, multitenancy.
- Do not allow protected text copying or specific author style imitation.
- All new assets must be schema-backed and project-scoped.
- All new APIs must have tests.
- Every phase should run:

```bash
make test
make lint
make validate
```

For Web work, also run at least:

```bash
npm --prefix web/admin run build
```

The current `npm --prefix web/admin run lint` script is stale because it uses `next lint`; fix this before treating Web lint as a required gate.

## Phase 0: Audit and Planning

Status: this document set is the Phase 0 output.

### Goals

- Read `CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/new`, `docs/new/ui`, backend, frontend, and tests.
- Build UI inventory.
- Build V6/V7 gap analysis.
- Build Agent industrialization design.
- Do not modify core code.

### Deliverables

- `docs/new/implementation/ui-inventory.md`
- `docs/new/implementation/v6-v7-gap-analysis.md`
- `docs/new/implementation/v6-v7-implementation-plan.md`
- `docs/new/implementation/agent-industrialization-design.md`

### Acceptance

- Documents include UI mapping, code mapping, gap analysis, risks, API split advice, schema advice, Agent runtime gaps, and next loop plan.
- No backend/frontend behavior changes.

## Phase 1: API Modularization

Goal: reduce extension risk before adding V6/V7 domains.

### Target Structure

```text
src/novel_forge/api/
  app.py
  health.py
  product.py
  models.py
  deps.py
  routers/
    __init__.py
    projects.py
    assets.py
    tasks.py
    handoffs.py
    batch.py
    drafts.py
    reviews.py
    health.py
    system.py
    analysis.py
    libraries.py
    planning.py
    context.py
    originality.py
    publishing.py
    feedback.py
    evaluation.py
    agents.py
    settings.py
```

### Router Responsibility Boundaries

| Router | Existing endpoints | Future endpoints |
|---|---|---|
| `projects.py` | `/product/projects`, series, lifecycle, config, project assets, scope audit | platform/style/quality binding |
| `tasks.py` | `/product/tasks`, timeline, events, recovery, control, dead letters, cancel/retry | Agent run visibility and queue pressure trend |
| `assets.py` | asset detail, edit, content edit, typed edit, versions, graph, collections | typed V6 editors and document management |
| `handoffs.py` | handoff list/create/validate/bind/accept/fail/retry/source policies/github | V6.1 analysis handoff types |
| `batch.py` | batch items, retry, bulk retry, review, continue, handoff regenerate/void, deconstruct | item/step analysis modes |
| `drafts.py` | drafts, editor, generate, save, diff, export, publish record | generation run and editor patch APIs |
| `reviews.py` | review run, revision plan, issue patch, revision apply | review quality upgrades and revision loop |
| `health.py` | product health and Postgres strict check | project health page metrics |
| `system.py` | backups, restore, event archive, Qdrant, MinIO | local production diagnostics |
| `analysis.py` | analysis modes, web/published/classic run, conversion, reports, handoffs | provider/rubric-backed scoring and richer report visualization |
| `libraries.py` | topic/material/knowledge/style/standard library operations, style trend/scoring, quality score | deeper editors and graph views |
| `production_chain.py` | outline versions, chapter-plan versions, draft versions, generation runs | chapter queue, invalidation, parameter dashboards |
| `context_builder.py` | context build plans and bundles | manual curation, stale-context warnings, richer compression controls |
| `audit.py` | chapter audit, originality report, publish gate, release package | future split into `originality.py` and `publishing.py` only if the shared quality-gate module grows too large |
| `originality.py` | deferred | deeper originality similarity engines |
| `publishing.py` | deferred; publish record today in drafts | publishing plan, calendar, publishing log |
| `feedback.py` | feedback service exists but no Product UI router | import batches, insights, sentiment |
| `evaluation.py` | none yet | model benchmark tasks/runs/comparison/prompt versions |
| `agents.py` | runtime profile only | contracts, runs, checkpoints, events, gates |
| `settings.py` | scattered health/settings | local settings read/validate/write |

### Loop 1: Route Registration Scaffolding

Goal: create router package and split registration groups without behavior change.

Involved files:

- `src/novel_forge/api/product.py`
- `src/novel_forge/api/routers/__init__.py`
- `src/novel_forge/api/routers/projects.py`
- `src/novel_forge/api/routers/tasks.py`
- `src/novel_forge/api/routers/assets.py`
- `src/novel_forge/api/routers/handoffs.py`
- `src/novel_forge/api/routers/batch.py`
- `src/novel_forge/api/routers/drafts.py`
- `src/novel_forge/api/routers/reviews.py`
- `src/novel_forge/api/routers/system.py`
- `tests/unit/test_product_api.py`

Plan:

1. Introduce a lightweight dependency object that carries `app`, `app_settings`, `models`, `LocalStorage`, and helper function references.
2. Move endpoint registration blocks to router modules.
3. Keep existing service/helper functions in `product.py` for compatibility.
4. Keep endpoint paths unchanged.
5. Do not move worker-imported functions in this loop.

Risk:

- Request models are currently inner classes in `create_app()`, passed as `models`. Router modules must keep using this pattern initially to avoid a large model migration.
- Tests import many functions from `api.product`; do not break those imports.

Rollback:

- Restore `register_product_routes()` route blocks inside `product.py`.
- Remove router imports.

Acceptance:

- Existing Product API tests pass.
- `product.py` loses route registration bulk but service imports remain stable.

### Loop 2: Request Model Extraction

Goal: move Product API request models from `api/app.py` to `api/models.py`.

Involved files:

- `src/novel_forge/api/app.py`
- `src/novel_forge/api/models.py`
- Router modules
- Tests that instantiate `create_app()`

Risk:

- Optional FastAPI/Pydantic dependency path must remain dependency-gated.

Acceptance:

- `create_app()` is shorter.
- Router request annotations are explicit.
- Tests pass.

### Loop 3: Service Extraction Start

Goal: move non-HTTP orchestration out of API into domain services.

First candidates:

- project lifecycle -> `modules/projects/service.py`
- task center/recovery -> `modules/tasks/service.py`
- handoff binding/acceptance -> `modules/handoff/service.py`
- batch item orchestration -> `modules/batch/service.py`

Risk:

- Worker imports from `api.product` must be updated only when replacement services are ready.

Acceptance:

- `api.product` keeps compatibility wrappers but no longer owns the domain logic.

## Phase 2: New UI Information Architecture

Goal: turn the single V5 admin page into a V6 local factory console shell.

### Target Frontend Structure

```text
web/admin/app/
  components/
    layout/
    dashboard/
    project/
    libraries/
    analysis/
    planning/
    context/
    drafting/
    editor/
    review/
    originality/
    publishing/
    feedback/
    control/
    evaluation/
    settings/
  lib/
    api.ts
    navigation.ts
    format.ts
  page.tsx
  globals.css
```

### Loop 1: Navigation and Shell

Goal:

- Add grouped V6 navigation.
- Keep existing panels reachable.
- Add top status bar with local mode, data sync, model status, autosave, search, notifications.

Involved files:

- `web/admin/app/page.tsx`
- `web/admin/app/globals.css`
- optionally `web/admin/app/lib/navigation.ts`

Acceptance:

- All current V5 panels remain reachable.
- New page names exist.
- Empty/loading/error states exist for new placeholder pages.
- No SaaS language appears.

### Loop 2: Feature Component Extraction

Goal:

- Extract layout and common cards/tables from `page.tsx`.
- Move API helpers into `lib/api.ts`.

Acceptance:

- `page.tsx` begins shrinking.
- Build passes.

### Loop 3: V6 Page Skeletons

Goal:

- Implement page skeletons matching UI images for workbench, projects, topic/material/knowledge libraries, setting bible, outline, chapter plan, context builder, chapter production, AI editor, review, originality, publishing, feedback, production control, model evaluation, settings.

Acceptance:

- Every first-level page is navigable.
- Pages show real current data where possible and explicit mock placeholders where APIs do not exist yet.

## Phase 3: Creative Asset Layer

Goal: add platform/topic, style, quality standards, continuity base, and enhanced libraries.

Status update 2026-06-27: the schema-backed creative asset baseline is implemented. Project creation and production context now bind/backfill platform, genre, quality, style, and continuity profiles. Draft/review flows read those profiles, style decomposition/scoring/trend exists, quality scoring exists, and review emits quality score, style review, originality, and chapter-audit evidence. Originality and publishing gate workbench APIs/UI have also been added as the first Phase 6-compatible quality gate slice.

### Schema Batches

Batch A:

- `platform_profile`
- `genre_market_profile`
- `topic_fit_report`
- `quality_standard_profile`
- `quality_score_report`

Batch B:

- `style_profile`
- `style_decomposition_report`
- `style_blend_preset`
- `style_review_report`

Batch C:

- `continuity_bible`
- `foreshadowing_thread`
- `power_scale_rule`
- `review_rule_pack`
- `writing_template`
- `craft_template`

### Acceptance

- Each type has dataclass, content validation, directory mapping, tests, and asset list/detail visibility.
- All writes include project_id/workspace_path where relevant.
- No style asset can request specific author imitation.
- Project config references platform, genre market, quality standard, style, and continuity assets.
- Review output can create quality/style/originality/chapter audit reports.
- `chapter_audit_report`, `originality_report`, `publish_gate_report`, and `release_package` are available as schema-backed V6 quality/publishing gate assets.

Known remaining depth:

- Asset workbench editors are type-aware and actionable, but relationship graph editing, timeline canvas, and platform-specific quality-rule designers remain later UI depth work.
- Publishing calendar, publishing log, reader feedback loop, and model evaluation remain later phases.

## Phase 4: Analysis Center Upgrade

Status: first industrial slice implemented on 2026-06-27.

Goal: implement V6.1 analysis separation.

### Backend Modules

```text
src/novel_forge/modules/analysis/
  service.py
```

Current implementation keeps the first slice in `service.py` to avoid premature file fragmentation. Split into `common.py`, `web_commercial.py`, `published_fiction.py`, `classic_literary.py`, `asset_converter.py`, `rubrics.py`, and `validators.py` when provider-backed analysis and richer rubrics grow large enough.

### New Schemas

- `common_novel_analysis_report`
- `web_fiction_business_analysis_report`
- `published_fiction_analysis_report`
- `classic_literary_analysis_report`
- `analysis_conversion_report`

All five are registered in `SCHEMA_CLASSES`, mapped to `data/analysis`, and validated in `schemas/base.py`.

### Handoff Skills

- `hot-novel-business-deconstruction`
- `published-fiction-craft-analysis`
- `classic-literary-depth-analysis`
- `analysis-to-asset-conversion`

All four root `skills/*/SKILL.md` files exist and map to the Analysis Agent runtime profile.

### Implemented APIs

- `GET /product/analysis/reports`
- `POST /product/analysis/run`
- `POST /product/analysis/convert`
- `POST /product/analysis/handoff`

### Implemented UI

- `AnalysisPanel` backs Analysis Center, Web Fiction Business Analysis, Published Fiction Craft Analysis, Classic Literary Analysis, and Asset Converter.
- The panel supports source selection, local deterministic analysis, Claude Code handoff creation, conversion target selection, report table, conversion table actions, and analysis handoff visibility.
- Asset detail workbench has typed rendering/edit fields for all analysis report types.

### Acceptance

- The three analysis modes cannot be mixed accidentally.
- Deconstruction reports cannot directly enter draft RAG unless converted to abstract reusable assets.
- Converted assets include `reuse_scope`, `copyright_risk`, and `abstraction_level`.

Current acceptance status:

- Passed in unit/API tests for report creation, conversion, handoff expected output type, OpenAPI registration, and schema validation.
- Remaining deepening work: provider/rubric-backed semantic scoring, richer report visualizations, per-mode submodule split, and conversion quality gates beyond deterministic rules.

## Phase 5: Production Flow Upgrade

Goal: make outline -> chapter plan -> context -> generation -> editor traceable.

Status update 2026-06-27: the first traceability slice is implemented. Context Builder has schema-backed `context_build_plan` and `context_bundle` assets, service/API/UI coverage, token budget and retrieval metadata, compression preview, and actual-context replay. Production Chain has `outline_version`, `chapter_plan_version`, `draft_version`, and `generation_run` assets plus `/product/production/*` APIs and Web Admin panels. Draft generation now creates a context plan, freezes a context bundle, writes a draft version, and records a generation run. Workflow/node run contract now has `workflow_definition`, `workflow_node`, and `node_run` assets, `/product/workflow/*` APIs, and automatic NodeRun recording from workflow task execution. Change impact first slice has `change_impact_report`, `/product/impact/*`, downstream reference scanning, severity summaries, recommendations, and a Web Admin Change Impact page.

### New Schemas

- `outline_version`
- `chapter_plan_version`
- `context_build_plan`
- `context_bundle`
- `generation_run`
- `draft_version`
- `editor_patch`
- `draft_diff_report`

### Acceptance

- Context builder records actual selected assets, token budget, priority, compression result, risks, and sent context.
- Chapter generation records provider/model, prompt version, context bundle, style profile, quality standard, latency, token, error.
- Editor suggestions can be applied individually and rollback creates version record.

Current acceptance status:

- Passed in unit/API tests for context build plan creation, context bundle creation, production version creation, generation-run creation, draft integration, workflow/node run recording, change impact report creation, OpenAPI registration, and schema validation.
- Remaining work: manual source toggles/priorities in UI, stale-context invalidation warnings wired into generation preflight, chapter queue, parameter dashboards, `editor_patch`, and `draft_diff_report`.

## Phase 6: Quality, Originality, Publishing, Feedback

Goal: turn review into release gate.

### New Schemas

- `chapter_audit_report`
- `style_audit_report`
- `continuity_audit_report`
- `platform_fit_report`
- `originality_report`
- `publish_gate_report`
- `release_package`
- `publishing_plan`
- `publishing_log`
- `feedback_import_batch`
- `feedback_insight` enhancements
- `reader_sentiment_report`
- `project_metric_snapshot`

### Acceptance

- Publishing requires review, originality, and publish gate pass.
- Feedback insights can create constraints for later chapter plans and reviews.
- High-risk release packages cannot become publish-ready by default.

## Phase 7: Agent Industrialization

Goal: make Agent runs persisted, observable, recoverable, and permission-enforced.

Status update 2026-06-27: the first persisted Agent runtime slice is implemented. The schema registry validates `agent_contract`, `agent_run`, `agent_checkpoint`, `agent_event`, `agent_budget`, `agent_gate`, `agent_metric`, and `agent_failure_report`. `modules/agent_runs` creates/reuses contracts, starts runs, records events/checkpoints/budgets/gates/failures, updates run status, and lists runs/events. `/product/agents/*` routes are registered and tested. Claude Code/Codex handoffs create `waiting_human` Agent runs, bind-output marks them `succeeded`, failed handoffs create failure reports, and retries cancel superseded runs. The Web Admin Production Control Center now shows Agent runs, NodeRuns, failures, dead letters, and human gates.

### New Schemas

- `agent_contract`
- `agent_run`
- `agent_checkpoint`
- `agent_event`
- `agent_budget`
- `agent_gate`
- `agent_metric`
- `agent_failure_report`

### Acceptance

- Any Agent run appears in Production Control/Agent views.
- Any Agent output is schema-validated.
- Any high-risk output supports human gate.
- Tool allowlist and output type allowlist are enforced at execution boundaries.

Current acceptance status:

- Passed in schema/service/API tests for Agent contract/run/event persistence, Handoff integration, OpenAPI registration, and status updates.
- Remaining work: enforce allowlists inside every worker/model/service executor, one-click rollback actions, SLA/timeout enforcement, metrics aggregation, and deeper Agent timeline UI.

## Phase 8: Model Evaluation Center

Goal: make model routing empirical.

### New Schemas

- `model_profile`
- `model_benchmark_task`
- `model_benchmark_run`
- `model_comparison_report`
- `prompt_version`
- `prompt_regression_report`

### Acceptance

- Draft/review/outline/context/originality tasks can be benchmarked across providers.
- Quality, latency, cost, failure rate, and regression history are visible.
- Model routing can be updated based on benchmark reports.

## First Implementation Loop to Enter After Phase 0

### Loop 1 Goal

Start Phase 1 with the smallest safe API modularization step.

### Files to scan again before editing

- `src/novel_forge/api/app.py`
- `src/novel_forge/api/product.py`
- `src/novel_forge/workers/tasks.py`
- `tests/unit/test_product_api.py`
- `tests/unit/test_industrial_integration.py`

### Planned edits

- Add `src/novel_forge/api/routers/`.
- Add grouped route registration modules for current endpoints.
- Keep service functions in `product.py`.
- Keep all `/product/...` paths unchanged.

### Tests

Run local relevant tests first:

```bash
make test
make lint
make validate
```

If failures are unrelated baseline failures, document them and fix only if they block the loop.

### Risks

- Circular imports if router modules import too much from `product.py`.
- Route registration order conflicts.
- Tests depending on internal route closure details.
- FastAPI optional dependency path must stay dependency-gated.

### Rollback

- Remove router imports.
- Restore all route decorators inside `register_product_routes()`.
- Keep service function compatibility unchanged.

## P2 Hardening Update 2026-06-28

### Completed

1. PostgreSQL migrations now use an Alembic-style migration chain:
   - `src/novel_forge/storage/migrations/runner.py`
   - `src/novel_forge/storage/migrations/versions/v20260625_0001_initial_industrial_schema.py`
   - `src/novel_forge/storage/migrations/versions/v20260628_0002_query_and_release_indexes.py`
   - `tests/unit/test_postgres_migrations.py`

2. Frontend systematic tests now exist:
   - `web/admin/package.json` has `npm test`.
   - `web/admin/tests/feature-architecture.test.mjs` verifies navigation, routed feature modules, P2 page affordances, and API client contracts.
   - `make test` runs both Python tests and frontend tests.

3. Publishing Center is upgraded from release buttons to a local publishing workbench:
   - release package version registry (`release_version`, `version_key`);
   - publishing calendar and queue summaries;
   - platform rule snapshots;
   - publishing logs with rollback evidence and external URL support.

4. Asset visibility is upgraded:
   - asset detail pages load reference graph data;
   - change impact reports expose impacted nodes and edges;
   - Web Admin displays severity strips, graph nodes, edge tables, and recommended actions.

5. Documentation was updated to match the implemented state.

### Next Optional Depth

1. Add Playwright smoke tests for critical routed pages after UI copy/layout churn slows down.
2. Add a real graph layout renderer if project graphs exceed simple chip grids.
3. Add migration downgrade scripts only when the project starts needing reversible destructive migrations.
4. Add platform-specific publishing adapters only after platform policy and local automation boundaries are approved.
