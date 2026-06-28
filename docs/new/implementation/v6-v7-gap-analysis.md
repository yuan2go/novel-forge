# Novel Forge V6/V7 Gap Analysis

Phase 0 audit date: 2026-06-26.

Implementation status update: 2026-06-27.

Implementation status update: 2026-06-28.

- Added `/product/system/module-completion` and `/product/system/module-completion/snapshot` to expose a V6/V7 module completion matrix. The report combines code evidence, runtime asset evidence, remaining gaps, and acceptance status for Analysis Center, Context Builder, Versioned Production Chain, AI Editor, Long-form Stability, Agent Industrialization, Feedback Center, and Model Evaluation Center.
- Analysis conversion now has an explicit human gate. Converted assets are created as abstract assets, but default to `asset_status=needs_human_gate` and `use_in_generation_rag=false` until a human approves the abstraction boundary. Review-rule and production-RAG use is therefore blocked by default.
- Context Builder now records a `context_profile` on build plans and supports `/product/context/diff`, producing a schema-backed context bundle diff snapshot with added/removed sources, token delta, stale warning delta, and recommendation.
- Production chain now has `/product/production/invalidate-downstream`, which creates a change-impact report and can mark high/medium/blocking downstream assets as `stale` with invalidation metadata.
- Agent runtime now exposes `/product/agents/executor/run-once`. It enforces tool allowlist, output type, checkpoint recording, hard token budget, budget assets, SLA assets, and fail-closed failure reports.
- Model Evaluation Center now supports `/product/evaluation/benchmark-from-generation-run`, binding benchmark tasks directly to real `generation_run` production traces.
- Web Admin Health Center now displays the V6/V7 module completion matrix. Analysis, Context Builder, and Model Evaluation pages expose the new human gate, context profile/diff, and generation-run benchmark workflow.

The Phase 1-3 baseline has moved beyond the original audit:

- Product API route registration has been split under `src/novel_forge/api/routers/`, with `product.py` kept as a compatibility facade for workers and tests.
- The Web Admin shell now uses the V6 grouped navigation and local-factory top status bar.
- Creative asset libraries are schema-backed for topic/platform, material, knowledge, setting bible, style, and quality standards.
- Project creation now creates or binds `platform_profile`, `genre_market_profile`, `quality_standard_profile`, `style_profile`, and `continuity_bible`; production context also backfills missing required bindings for old project entry points when a project can be resolved.
- Chapter draft and review flows record production context and profile IDs for platform, genre, quality standard, style, style blend, and continuity.
- Style center has style decomposition, style review/scoring, and style drift trend APIs/UI.
- Quality standards have score reports and review flow integration.
- `continuity_bible`, `foreshadowing_thread`, and `power_scale_rule` now map to `data/continuity`; legacy `data/worlds` assets remain readable for compatibility.
- Publishing/quality gate assets now exist for `chapter_audit_report`, `originality_report`, `publish_gate_report`, and `release_package`, with schema validation, service APIs, router tests, and dedicated UI workbench panels.
- Phase 4 analysis center is now schema-backed: `common_novel_analysis_report`, `web_fiction_business_analysis_report`, `published_fiction_analysis_report`, `classic_literary_analysis_report`, and `analysis_conversion_report` write to `data/analysis`.
- `/product/analysis/reports`, `/product/analysis/run`, `/product/analysis/convert`, and `/product/analysis/handoff` are registered, tested, and shown in the Web Admin analysis workbench.
- Analysis reports are explicitly blocked from generation RAG (`metadata.use_in_generation_rag=false`); only converted abstract creative assets can flow into production.
- Claude Code/Codex handoff skills now cover web-fiction business analysis, published-fiction craft analysis, classic literary depth analysis, and analysis-to-asset conversion.
- Context Builder now has schema-backed `context_build_plan` and `context_bundle` assets in `data/contexts`, with service/API/UI coverage for target selection, backend/top-k/token budget, candidate ranking metadata, compression preview, and actual-context replay.
- Versioned production chain now records `outline_version`, `chapter_plan_version`, `draft_version`, and `generation_run` assets through `modules/production_chain`, `/product/production/*` routes, draft generation integration, and Web Admin production panels.
- Workflow/node run contract now has schema-backed `workflow_definition`, `workflow_node`, and `node_run` assets, `/product/workflow/*` APIs, automatic `node_run` records from workflow task execution, and sample pipeline sidecar handling.
- Agent runtime first slice is persisted: `agent_contract`, `agent_run`, `agent_event`, `agent_checkpoint`, `agent_budget`, `agent_gate`, `agent_metric`, and `agent_failure_report` schemas exist; `/product/agents/*` routes are registered; Claude Code/Codex handoffs create waiting-human Agent runs and synchronize success/failure/retry state.
- Long-form change impact first slice exists: `change_impact_report` scans project-scoped downstream references, records severity and recommendations, exposes `/product/impact/*`, and is visible in the Web Admin Change Impact page.
- Production Control now has a real Web Admin panel for task state, worker/queue status, node runs, Agent runs, failed items, dead letters, and human gates.

Remaining gaps should be read against this updated baseline, not the initial Phase 0 state.

This document compares the current Novel Forge V5 implementation with the latest `docs/new` V6/V7 design. It does not use older docs as the source of truth when they disagree with `docs/new`.

## Current System Real Structure

### Backend

```text
src/novel_forge/
  agents/
    runtime.py
  api/
    app.py
    health.py
    models.py
    product.py
    routers/
  cli/
  core/
  evaluation/
  infrastructure/
  model_adapters/
  modules/
    chapter_plan/
    context_builder/
    characters/
    cleaning/
    decomposition/
    drafting/
    feedback/
    handoff/
    image_prompts/
    ingestion/
    knowledge/
    materials/
    outline/
    production_chain/
    review/
    revision/
    source_intake/
    topics/
    training/
    workspace/
    worldbuilding/
  schemas/
    base.py
    assets.py
  storage/
    asset_manifest.py
    graph.py
    local.py
    object_store.py
    postgres.py
    qdrant_index.py
    rag_context.py
    retrieval_index.py
    search.py
    vector_index.py
  workers/
  workflows/
```

Key backend concentration:

- `src/novel_forge/api/product.py` is now a small compatibility facade.
- Product routes are registered through `src/novel_forge/api/routers/`, including projects, tasks, assets, handoffs, batch, drafts, reviews/audit, system, libraries, analysis, context builder, and production chain.
- Some domain orchestration remains in compatibility services imported by routers/workers. Future cleanup should continue moving API-owned helpers into `modules/*` services without breaking public paths.

### Frontend

```text
web/admin/
  app/
    layout.tsx
    page.tsx
    globals.css
  package.json
  tsconfig.json
  next.config.mjs
```

Key frontend concentration:

- `web/admin/app/page.tsx`: about 6.8k lines after V6 shell, creative asset workbenches, analysis center, context builder, production chain, quality gates, tasks, handoffs, batch, drafts, and reviews were added.
- It still contains type declarations, API client calls, all page state, all tabs, task controls, asset detail panels, typed asset editor, and feature panels in one file.
- Current tab set follows the V6 grouped IA, but feature components have not yet been extracted into `components/*`.

### Tests

```text
tests/
  unit/
    test_claude_handoff.py
    test_cli.py
    test_industrial_integration.py
    test_model_adapter.py
    test_module_services.py
    test_product_api.py
    test_schemas.py
    test_skill_sync.py
    test_skills.py
    test_source_intake.py
    test_storage.py
    test_task_status.py
  integration/
    test_pipeline.py
    test_workflow_steps.py
```

Observed test scale:

- 3237 lines of tests.
- Strongest coverage is around Product API internals, storage, task status, source intake, model adapters, CLI, and V5 workflow services.
- There are no frontend tests.
- Publishing calendar/logs, feedback analytics, and model evaluation assets do not yet have full tests. Analysis center, context builder, versioned production chain, workflow/node runs, Agent run persistence, change impact reports, and first-slice publishing/originality gate assets now have backend/API tests.

## Current V5 Capabilities to Preserve

The current implementation already provides a strong local production base:

1. Project workspace lifecycle: create, list, update config, duplicate, archive, pause, restore, soft delete, series grouping.
2. Project scope audit and write guard: detects unscoped assets and rejects cross-project writes by reference.
3. Schema-backed local JSON assets with common validation.
4. Local workspace boundary and ignored runtime workspace convention.
5. Source intake rights metadata and compliance gates.
6. Batch ingest/deconstruct item model, including Claude Code analysis mode.
7. Claude Code/Codex handoff assets, acceptance status, bind output, retry/fail/supersede, output type validation.
8. Task center, latest/timeline split, retry, cancel, dead-letter, worker/queue status, task control, recovery workbench.
9. Draft workbench: generate, edit, save, diff, export Markdown/DOCX/EPUB, publish record.
10. Review/revision flow: review, issue status, revision plan, revision application preview/result.
11. RAG context builder with project-scoped buckets for characters, worldbuilding, previous summaries, knowledge, foreshadowing, and materials.
12. Schema/API/UI backed Context Builder assets with replayable `context_build_plan` and `context_bundle`.
13. Versioned production chain records for outline, chapter plan, draft, and generation runs.
14. Qdrant indexing/search with semantic embedding requirement, collection dimension/model checks, vector cache, batch embedding, and backend metadata.
15. MinIO object sync/status and local backup/restore.
16. Postgres write-through and strict local-prod checks.
17. OpenAI-compatible model adapters, output validation, deterministic mock adapters, and embedding adapters.
18. Health report with task, scope, Postgres, embedding, Celery, queue trend, failures, handoffs, backups.

These are not to be removed during V6/V7.

## Latest Design Summary

`docs/new` requires the system to become a personal local novel factory console, not a SaaS product and not a generic AI writing website. The target chain is:

```text
platform/topic/quality/style setup
  -> compliant source intake
  -> web/published/classic/professional analysis
  -> abstract reusable assets
  -> world/character/continuity
  -> outline
  -> chapter plan
  -> context bundle
  -> chapter production
  -> AI editing
  -> review/originality/publish gate
  -> publishing log
  -> reader feedback
  -> project strategy adjustment
  -> model/Agent evaluation
```

The target architecture is four main layers:

1. Work and operation layer.
2. Creative asset layer.
3. Analysis and deconstruction layer.
4. Production, quality, publishing, and feedback layer.

The target also adds Agent industrialization as a cross-cutting runtime layer.

## UI Gap Summary

| Area | Current implementation | V6/V7 requirement | Gap |
|---|---|---|---|
| Information architecture | Single-page tabs around V5 operations | Factory console navigation grouped by workspace, assets, analysis, production, management | P0 |
| Page shell | One large page file | Reusable layout shell, left grouped nav, top local status bar, page states | P0 |
| Workbench | Studio has mixed project/source/RAG/agent observations | Daily operation dashboard with production flow, tasks, risks, recent outputs | P0 |
| Projects | Lifecycle exists | Add platform/topic/quality/style initialization and health summary | P0 |
| Topic library | Only `topic_seed` and service basics | Platform-aware genre market profiles and topic fit reports | P0 |
| Material library | `material_card` and typed panel | Category taxonomy, filters, rating, related materials, source risk | P1 |
| Knowledge library | `knowledge_card`, GitHub policy, RAG | Collections, taxonomy, citation graph, credibility, staleness | P1 |
| Setting bible | World and character assets exist | Bible center with rules, characters, forces, timeline, foreshadowing, impact graph | P1 |
| Outline | Outline asset exists | Versioned outline editor and comparison | P1 |
| Chapter plan | Chapter plan asset exists | Deep detailed outline editor with scene, conflict, information, hook, token/word budget | P1 |
| Context builder | RAG builder plus `context_build_plan`/`context_bundle` service/API/UI exists | Manual source curation, richer token controls, invalidation warnings | P1 |
| Chapter production | Draft generation records context plan, context bundle, draft version, and generation run | Queue, preflight checklist UI depth, generation settings, progress history | P1 |
| AI editor | Basic draft editor exists | Rich editor, paragraph suggestions, selective apply, rollback, related docs | P1 |
| Review center | V5 review/revision page exists | Multi-dimensional audit center, not a single review action | P0/P1 |
| Originality center | Source compliance and overlap checks exist | Dedicated originality reports for text/plot/role/setting/style similarity | P0 |
| Publishing center | Export/publish record exists | Calendar, queue, platform checks, titles, hooks, publish gate, logs | P1 |
| Reader feedback | Schema and CLI exist | Feedback center with import, sentiment, poison/selling points, retention, strategy feedback | P1 |
| Production control | Task center exists | Pipeline dependency graph, blockers, gates, recovery and log in one command center | P1 |
| Model evaluation | Provider health exists | Benchmark tasks, A/B tests, prompt versions, routing rules, cost/quality/latency | P2 |

## Backend/API Gap Summary

| Area | Current state | Required state | Priority |
|---|---|---|---|
| API modularity | `product.py` contains routes and most business helpers | `api/routers/*` with clear responsibility; product entry only registers routers and compatibility | P0 |
| API/service boundary | Workers and tests import service-like functions from `api.product` | Domain services under `modules/*` or `api/services/*`; API only adapts HTTP | P0 |
| Request models | Product request models are defined inside `create_app()` and passed into route registration | Stable request/response models per router or shared API model module | P0/P1 |
| Project configuration | Basic genre/platform/word count/cadence/threshold | Bind platform profile, genre market profile, quality standard, style profile | P0 |
| Analysis routes | `/product/analysis/*` exists for reports, local runs, conversion, and Claude Code handoffs | Deeper provider-backed semantic analysis and report visualization | P1/P2 |
| Context routes | RAG is backend helper and metadata | `/product/context/build`, `/product/context/bundles`, preview and send to generation | P1 |
| Publishing routes | Export and publish record | publish plan, publish gate, package, logs, platform checks | P1 |
| Feedback routes | Feedback CLI/services | import batches, insights, sentiment, risk, strategy suggestions | P1 |
| Agent routes | `/product/agents/*` exists for contracts, runs, events, and status updates | metrics dashboards, rollback actions, worker/model execution enforcement everywhere | P1/P7 |
| Evaluation routes | Provider health only | models, benchmark tasks/runs, comparisons, prompt versions, regression reports | P2/P8 |

## Schema Gap Summary

Existing schema classes are all in `src/novel_forge/schemas/assets.py`, backed by generic dataclasses and `CONTENT_REQUIRED_FIELDS` in `schemas/base.py`.

### Existing asset types

```text
source_document, cleaned_text, decomposition_report, analysis reports,
knowledge_card, material_card, asset_collection, platform/topic/style/quality
profiles, continuity assets, outline/chapter-plan/context/version/generation
assets, draft/review/revision/quality/publishing gate assets, reader feedback,
training_exercise, image_prompt, claude_code_handoff, workflow_run,
workflow_definition, workflow_node, node_run, task_status, task_dead_letter,
batch_task_item, project_workspace_state, change_impact_report,
agent_contract, agent_run, agent_checkpoint, agent_event, agent_budget,
agent_gate, agent_metric, agent_failure_report
```

### Missing or incomplete V6/V7 asset types

| Domain | Needed asset types |
|---|---|
| Platform/topic | First slice exists: `platform_profile`, `genre_market_profile`, `topic_fit_report`; remaining depth is market scoring and trend import. |
| Style | First slice exists: `style_profile`, `style_decomposition_report`, `style_blend_preset`, `style_review_report`; remaining depth is richer drift analytics. |
| Quality standards | First slice exists: `quality_standard_profile`, `quality_score_report`, `review_rule_pack`; remaining depth is provider-backed rubric scoring. |
| Long-novel continuity | First slice exists: `continuity_bible`, `foreshadowing_thread`, `power_scale_rule`, `change_impact_report`; missing `chapter_continuity_report` and graph UI depth. |
| Analysis | Implemented first slice: `common_novel_analysis_report`, `web_fiction_business_analysis_report`, `published_fiction_analysis_report`, `classic_literary_analysis_report`, `analysis_conversion_report`. |
| Planning/context | Implemented first slice: `outline_version`, `chapter_plan_version`, `context_build_plan`, `context_bundle`. |
| Generation/editor | Implemented first slice: `generation_run`, `draft_version`; missing `editor_patch`, `draft_diff_report`. |
| Quality/publishing | First slice exists: `chapter_audit_report`, `originality_report`, `publish_gate_report`, `release_package`; missing `style_audit_report`, `continuity_audit_report`, `platform_fit_report`, `publishing_plan`, `publishing_log`. |
| Feedback/stats | `feedback_import_batch`, `reader_sentiment_report`, `project_metric_snapshot` |
| Agent runtime | Implemented first slice: `agent_contract`, `agent_run`, `agent_checkpoint`, `agent_event`, `agent_budget`, `agent_gate`, `agent_metric`, `agent_failure_report`; remaining depth is pervasive execution enforcement and rollback. |
| Model evaluation | `model_profile`, `model_benchmark_task`, `model_benchmark_run`, `model_comparison_report`, `prompt_version`, `prompt_regression_report` |

### Directory mapping gap

`src/novel_forge/core/constants.py` only maps current V5 asset types to these data directories:

```text
raw, cleaned, decompositions, knowledge, materials, topics, worlds,
characters, outlines, chapter_plans, drafts, reviews, feedback, training,
image_prompts, workspaces, runs
```

V6/V7 needs either more directories or careful reuse:

```text
platforms, styles, standards, analysis, contexts, publishing, metrics,
evaluation, agents
```

## Agent Industrialization Gap

Current:

- `AGENTS.md` defines seven agent classes: Chief Editor, Engineering, Draft, Review, Knowledge, Material, Quality.
- `src/novel_forge/agents/runtime.py` has permission profiles, tool allowlists, allowed write types, skill-to-agent mapping, and enforcement helpers.
- Handoff binding calls `enforce_agent_action()` for output type policy.
- `modules/agent_runs` persists Agent contracts, runs, events, checkpoints, budgets, gates, metrics, and failure reports.
- `/product/agents/runs`, `/product/agents/events`, `/product/agents/contracts`, and `/product/agents/runs/status` are registered.
- Claude Code/Codex handoff creation starts a `waiting_human` Agent run; bind/fail/retry operations synchronize Agent run status and failure evidence.

Remaining for full V6/V7:

1. Permission allowlists are not yet uniformly enforced at every worker/model/service execution boundary.
2. Agent rollback policy is recorded conceptually but not yet implemented as one-click rollback actions.
3. SLA/timeout and rate-limit controls are not yet enforced across all workers.
4. Model/Agent benchmark feedback loop remains Phase 8 work.
5. Agent Center can be deeper than the current Production Control panel: metrics, timelines, retries, rollback, and gate details need richer UI.

## Stability and Performance Risks

1. `product.py` is too large and mixes routes, service logic, storage helpers, system operations, and workflow orchestration.
2. Frontend single page will become unmaintainable if V6/V7 pages are added directly.
3. Current tests depend heavily on internal functions in `api.product`; refactor must preserve import shims or update tests in small steps.
4. Worker imports from API layer make service extraction risky.
5. Frontend lint script is currently stale for installed Next version.
6. No frontend tests or Playwright smoke tests.
7. New UI images include duplicate/variant pages and one title/content conflict.
8. Schema system is simple dataclass-based; adding many asset types into one file will become another concentration point unless split into domain schema modules.
9. Some modules have placeholder `__init__.py` labels from V5; actual service depth varies.
10. Postgres is still an index/write-through path in code architecture, not a single domain repository abstraction.

## Current Most Important Refactor Targets

1. Split Product API route registration while keeping endpoint compatibility.
2. Untangle worker/service logic from `api.product`.
3. Introduce domain schema modules while preserving `asset_from_dict()` compatibility.
4. Create a V6 frontend shell with grouped navigation and feature component folders.
5. Create API client layer in frontend instead of in-page fetch helpers.
6. Convert existing Studio concepts into workbench, production observation, source lineage, and Agent observation panels.
7. Build context bundle and generation run assets before deep production UI.
8. Promote review into audit center with specialized report types.
9. Promote Agent runtime into persisted runs and events.
10. Add smoke tests for API routes and frontend build/lint baseline.

## Design Choices Worth Keeping

1. Local-first single-user model.
2. Schema-backed JSON assets as portable evidence and backups.
3. Project scope metadata and cross-project write guard.
4. Source compliance fields and downstream generation gate.
5. Claude Code/Codex handoff as explicit manual bounded runtime.
6. Task latest/timeline dual view and dead-letter recovery.
7. RAG retrieval metadata persisted on outputs.
8. Qdrant semantic embedding fail-closed behavior.
9. Deterministic mock adapters for fast tests.
10. Docker/local production stack with Postgres, Redis, Qdrant, and MinIO optional but supported.

## File-Level Upgrade Suggestions

| File or area | Issue | Recommendation |
|---|---|---|
| `src/novel_forge/api/product.py` | 6024-line mixed API/service module | Phase 1 split route registration into `api/routers/*`; then progressively move helper functions to domain services. |
| `src/novel_forge/api/app.py` | Request models are local inner classes | Move Product API request/response models into `api/models.py` or router-local modules. |
| `src/novel_forge/workers/tasks.py` | Imports task orchestration from API layer | Move batch/retry orchestration to `modules/tasks` or `modules/batch`. |
| `src/novel_forge/schemas/assets.py` | One growing schema registry | Add domain schema modules and aggregate in `schemas/__init__.py` / `assets.py`. |
| `src/novel_forge/core/constants.py` | Directory and schema mapping lacks V6 assets | Add V6 directories and asset type map gradually with tests. |
| `web/admin/app/page.tsx` | 4361-line all-in-one UI | Introduce app shell, API client, feature components, then split pages. |
| `web/admin/app/globals.css` | One large CSS file | Move toward shared utility classes and feature-local class naming, without overengineering CSS framework. |
| `web/admin/package.json` | `next lint` invalid for Next 16 | Replace with supported TypeScript/ESLint baseline in a later implementation phase. |
| `tests/unit/test_product_api.py` | Tests import API internals | Preserve compatibility shims during Phase 1, then migrate tests to service modules. |
| `docs/new/ui/*` | UI images include variants and missing pages | Treat variants as intent; request design clarification only before implementing conflicting pages. |

## First Minimum Viable Implementation Track

The next implementation should not add new product features first. It should create stable expansion points:

1. Phase 1.1: introduce `src/novel_forge/api/routers/` and move route registration groups out of `product.py` with no behavior changes.
2. Phase 1.2: keep existing service/helper functions in `product.py` as compatibility shims while tests remain green.
3. Phase 1.3: extract batch/task/handoff/project service helpers to domain modules only after router split is stable.
4. Phase 2.1: introduce a V6 frontend shell and navigation data model without deleting existing panels.
5. Phase 2.2: map old panels into new groups, then add empty/loading/error states for V6 pages.
6. Phase 3+: add new schemas in small domain batches with validation tests before UI depth.

## Phase 0 Conclusion

Current V5 is a working local production platform prototype. The biggest immediate risk is not missing isolated features; it is continued growth inside two monoliths:

- `src/novel_forge/api/product.py`
- `web/admin/app/page.tsx`

Therefore V6/V7 should start with modularization and an information architecture shell, then add new schema-backed domains.

## Implementation Status Update 2026-06-28

The earlier P0/P1 gaps have been largely converted into schema-backed services, feature pages, and tests. The current P2 status is:

1. Database migration: upgraded from a single schema-init statement list to Alembic-style ordered migration modules under `src/novel_forge/storage/migrations/versions/`. `PostgresAssetStore.initialize()` now applies missing migrations and `migration_status()` reports current, available, missing, and extra revisions.
2. Frontend tests: `web/admin` now has a dependency-free Node test baseline under `web/admin/tests/`, and `make test` runs both Python unit tests and frontend architecture tests.
3. Publishing Center: release packages now record `release_version`, `version_key`, and `platform_rules`; publishing plans expose local calendars, platform rule snapshots, queue status, and gate policy; publishing logs expose rollback evidence and external URL fields in the Web Admin.
4. Asset graph and impact analysis: asset detail workbench consumes `/product/assets/graph`; change impact reports expose `impacted_assets` and `impact_edges`; the Web Admin displays graph nodes, severity summaries, and recommended actions.
5. Documentation drift: this section, `v6-v7-implementation-plan.md`, and `ui-inventory.md` now describe the implemented state rather than the initial Phase 0 baseline.

Remaining P2 work is no longer basic existence, but depth:

- Browser-level smoke exists as an optional Playwright test. It skips when Playwright is not installed and becomes strict through `npm --prefix web/admin run smoke:browser` with `NOVEL_FORGE_WEB_BASE_URL`.
- Migration downgrade exists as a dry-run-first CLI/library path. Destructive downgrade requires explicit `--execute`.
- Asset graph layout now returns deterministic BFS-layered coordinates and UI renders layered graph nodes.
- Publishing platform adapters now exist for `local_file`, `manual_web`, and guarded `external_webhook`. External execution remains fail-closed unless the local operator explicitly configures endpoint and permission environment variables.
- Workbench and project management now have an operating dashboard model: `/product/projects/operating-dashboard` ranks projects by investment score, risk score, momentum, daily priority, and bottleneck. The Dashboard page surfaces daily production priorities and project investment/risk ordering; the Projects page uses a guided creation flow with selectable platform, genre, quality, style, and continuity profile bindings.
- Creative asset libraries now expose richer row content and the Web Admin asset workbench has domain panels for topic strategy, material operations, knowledge governance, and setting-bible continuity. These panels show scoring, classification tags, credibility/staleness, foreshadowing status, and setting impact entry points.

Remaining optional depth:

- Install and run Playwright in CI/local production smoke when browser automation dependencies are available.
- Add advanced graph interaction such as zoom, node search, and large-project minimap.
- Add adapter implementations for named external platforms only after their platform rules and copyright gates are explicitly approved.
- Continue deepening domain editors into full canvases: topic market trend import, material relation editor, knowledge citation taxonomy editor, and setting timeline/map editors.

## Industrial Depth Update 2026-06-28

The latest implementation closes another layer of V6/V7 depth gaps:

1. Analysis Center: local analysis reports now include provider-backed or provider-attempted semantic rubric scoring, per-mode visualization payloads, evidence, and provider/model status. Web Admin shows semantic score, mode panels, provider summary, and rubric rows for web fiction, published fiction, and classic literary analysis.
2. Chapter Factory UI: the production chain page now exposes chapter queue, generation mode, Celery async toggle, strict preflight checklist, progress timeline, pause/cancel/recover controls, and failed-step recovery affordances over the existing chapter production bus.
3. Context Builder: bundle creation now accepts manual selected/disabled/priority source paths and final confirmation. Bundles record manual selection, stale context warnings, actual context, and budget score; the UI shows source toggles, priority controls, warnings, and final send preview.
4. AI Editor: the editor is now a three-panel workbench with related-source sidebar, rich text style draft textarea, version/patch sidebar, and command presets for continue, expand, shorten, polish, and risk revision. Patch/diff/rollback remains schema-backed.
5. Originality Protection: reports now include structure similarity matrix, risk explanations, and remediation plan. Quality UI surfaces risk reasons, matched structure dimensions, and rewrite instructions.
6. Model Evaluation: Web Admin now separates real provider batch benchmark runs, A/B comparison, routing policy, cost, latency, and route-effect regression visibility. Non-mock providers still fail closed unless configured through local env/model adapters.
7. Agent Industrialization: `/product/agents/boundary-audit` creates a schema-backed `agent_metric` report scanning worker/model/service boundaries for unguarded writes/model calls and can run a negative runtime guard probe. Production Control displays boundary findings and guard proof.
8. Publishing Center: release packages now include title/synopsis/tag optimization, cover asset requirements, and platform review feedback placeholders. Publishing logs record platform feedback strategy backwrite targets.

Remaining depth after this update:

- Run the local production failure matrix with real Docker services and installed Playwright on the operator machine.
- Add named external platform rule packs only after explicit platform/API approval.
- Continue turning domain pages into specialized canvases where useful, especially setting timeline/map and large graph navigation.
