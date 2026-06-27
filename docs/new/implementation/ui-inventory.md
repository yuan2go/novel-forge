# Novel Forge V6/V7 UI Inventory

Status update 2026-06-27:

- The Web Admin now uses the V6 grouped navigation shell.
- Topic, material, knowledge, setting bible, style, and quality standard pages are backed by schema-aware creative asset libraries.
- Originality Protection and Publishing Center have first-class workbench panels for originality report, chapter audit, publish gate, and release package generation.
- Project creation/binding UI includes platform, genre market, quality standard, style, and continuity profile references.
- Analysis Center, Web Fiction Business Analysis, Published Fiction Craft Analysis, Classic Literary Analysis, and Asset Converter now share a real analysis workbench backed by `/product/analysis/*`.
- Analysis report assets have typed detail rendering and conversion output tracing.
- Context Builder now has a real workbench backed by `/product/context/*`, with target selection, query/backend/top-k/token budget controls, build-plan creation, bundle freezing, source counts, token estimate, and typed asset replay.
- Outline Generation and Chapter Plan pages now share a versioned production-chain workbench backed by `/product/production/*`, with outline/chapter-plan/draft version creation and generation-run records.
- Production Control now has a real observability panel for task state, worker/queue health, `node_run`, `agent_run`, failed batch items, dead letters, and human gates.
- Change Impact now has a real workbench backed by `/product/impact/*`, with changed-asset selection, impact report creation, severity summary, recommendation, and asset drill-down.
- This inventory remains the design reference for deeper page-specific editors, publishing calendar/logs, feedback analytics, model evaluation, and deeper Agent center work.

Source of truth: `docs/new/` and `docs/new/ui/`.

This inventory treats the new UI images as product intent for a personal local novel factory console. Older docs are historical references only.

## Latest Design Document Index

| File | Role | Main conclusions |
|---|---|---|
| `docs/new/deep-research-report.md` | Product and system research baseline | V5 is already a local production platform prototype; V6/V7 should become a factory console organized by operation, creative assets, analysis, production, quality, publishing, feedback, model evaluation, and Agent industrialization. |
| `docs/new/novel-forge-v6-gap-design-for-codex.md` | V6 gap design and implementation guide | Keep local single-user positioning; split Product API first; add platform/topic, quality standards, style system, audit center, originality, continuity, feedback, publishing, stats, and model/Agent evaluation. |
| `docs/new/novel-forge-v6-complete-design-with-literary-analysis.md` | Consolidated V6 + V6.1 design | Same V6 design plus the literary analysis appendix. It should be read as the complete version when details differ. |
| `docs/new/novel-forge-v6-1-literary-analysis-design-for-codex.md` | V6.1 analysis center extension | Analysis must separate common novel analysis, web-fiction business analysis, published-fiction craft analysis, classic literary deep analysis, and asset conversion. |

## Global UI Shell Pattern

The images consistently describe a local factory console:

- Left navigation is grouped by work area, creative assets, production management, AI tools, and management tools.
- Top status bar shows local/project mode, data sync or backup state, model status, autosave, global search, notifications, and profile.
- Pages use operational cards, risk tags, status badges, progress bars, tables, and action buttons.
- The UI does not contain SaaS concepts such as login, subscription, teams, invitations, payment, or membership upgrades.

Required V6/V7 shell groups should converge to:

```text
Workspace
- Workbench
- Projects

Creative Assets
- Topic Library
- Material Library
- Knowledge Library
- Setting Bible
- Style Center
- Writing Templates
- Quality Standards

Analysis
- Analysis Center
- Web Fiction Business Analysis
- Published Fiction Craft Analysis
- Classic Literary Analysis
- Asset Converter

Production
- Outline
- Chapter Plan
- Context Builder
- Chapter Production
- AI Editor
- Review Center
- Originality Center
- Publishing Center
- Reader Feedback

Management
- Production Control
- Change Impact Analysis
- Model Evaluation
- Data Statistics
- Settings
- Task Center
- Health
```

## UI Image Inventory

| Image | Page classification | Page name | Left navigation | Top status bar | Core cards and panels | Tables or fields | Main buttons | Status labels and risk hints | Data sources | Backend module/API mapping | Schema mapping | Current code ability |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_50 (1).png` | Workspace | Workbench | Workspace, project management, creative assets, production flow, management tools | Local mode, database unsaved, model normal, autosave on, search, notifications | Project cards, today completion, word count, average status, production flow, today tasks, task queue, resource overview, recent outputs, alerts, quick actions | Project/task/status summaries | Continue production, import material, run review, open project | Running, warning, blocked, local status | Projects, tasks, assets, health, recent drafts/reviews | `api.product` project/task/health/assets endpoints today; future `routers/projects.py`, `tasks.py`, `health.py`, `assets.py` | `project_workspace_state`, `task_status`, `draft_chapter`, `review_report`, future `project_metric_snapshot` | Partial. Current Web has Studio panel with production/source/agent visibility, but not this IA or factory dashboard depth. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_50 (2).png` | Workspace | Project Management | Workspace and project entry highlighted | Local/data/model/autosave/search | Project lifecycle stats, filters, project list, local sync, local index, archive, quick actions | Project name, type, status, phase, progress, written/target words, update time, operations | Create project, archive, duplicate, open, sync, index | Active, archived, paused, draft | Project workspace assets and project config | `list_projects`, `transition_project_status`, `duplicate_project`, `update_project_config` | `project_workspace_state` plus future platform/style/quality bindings | Strong partial. Lifecycle, duplicate, archive, delete and config exist; UI needs V6 bindings and richer project phases. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (3).png` | Creative Assets | Setting Bible Center | Creation, content library, tools, management | Project/data/model/autosave/search | World rules, character archives, forces, timeline, foreshadowing, rule detail, relationship graph, consistency score, impact chain | Rule tree, impacted assets, conflict list | Add rule, edit, run consistency check, open impact | Conflict risk, consistency score, pending confirm | World bible, characters, outlines, chapter plans, drafts | Current `worldbuilding`, `characters`, asset graph; future `modules/continuity`, `modules/impact` | `world_bible`, `character_card`, future `continuity_bible`, `foreshadowing_thread`, `power_scale_rule`, `change_impact_report` | Partial. World/character assets exist; no dedicated setting bible editor, impact graph, timeline, power scale, or foreshadowing manager. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (4).png` | Production | Outline Generation | Creation assets and production | Project/data/model/autosave/search | Version selector, outline structure, chapter distribution, AI suggestions, consistency prompts, generation status, quick actions | Volume/arc/chapter tree, version metadata | Generate, create version, compare, apply suggestion | Consistency warning, version tags | Project config, topics, world, characters, templates | `modules/outline`, `modules/production_chain`, `/product/production/*` | `outline`, `outline_version`, `quality_standard_profile`, `genre_market_profile` | First version-chain slice implemented. UI can create/open outline versions and view production records; comparison and platform-aware outline editor remain. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (5).png` | Creative Assets | Knowledge Library | Creative asset library | Project/data/model/autosave/search | Knowledge collection overview, taxonomy tree, knowledge cards, relationship graph, tag cloud, stats, quick actions | Entry title, source, credibility, tags, related nodes | Import, create card, rebuild graph, search | Credibility, citation, stale warnings | Knowledge cards, GitHub policies, uploaded sources | Current `knowledge`, `source_intake`, `assets`, RAG; future `libraries` router | `knowledge_card`, `asset_collection`, future `knowledge_collection`, `source_policy_ref` | Partial. Knowledge card and GitHub source policy exist; no collection taxonomy, citation graph, or deep knowledge editor. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (6).png` | Analysis | Web Fiction Deconstruction | Analysis/deconstruction entry | Project/data/model/autosave/search | Analyzed works, report tabs, metrics, structure analysis, core setting extraction, task progress | Work list, metrics, analysis sections | Upload/select work, run analysis, convert asset | Progress, risk, report status | Source documents, cleaned texts, handoffs, decomposition reports | `routers/analysis.py`, `modules/analysis/service.py`, `modules/handoff/service.py` | `common_novel_analysis_report`, `web_fiction_business_analysis_report`, `published_fiction_analysis_report`, `classic_literary_analysis_report`, `analysis_conversion_report` | First V6.1 slice implemented. UI supports source selection, local analysis, Claude Code handoff, report list, conversion, and typed report rendering. Remaining depth: provider-backed semantic analysis and richer visualization. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (7).png` | Creative Assets | Topic Library | Creative assets | Project/data/model/autosave/search | Genre tabs, stats, audience positioning, selling point extraction, risk evaluation, topic plan table | Title, genre, audience, heat, risk, status, owner, created time | Create topic, evaluate, apply to project | Hot, risk, active, archived | Topic seed, platform profile, market notes | Current `topics` module; future `libraries.py` and `platform.py` services | `topic_seed`, future `platform_profile`, `genre_market_profile`, `topic_fit_report` | Weak partial. Topic seed exists, but no platform/topic fit, market profile, risk score, or topic library UI. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (8).png` | Creative Assets | Material Library | Creative assets | Project/data/model/autosave/search | Filter bar, category cards, material table, detail side panel with related materials | Type, category, tags, source, difficulty, status, rating | Add, import, edit, search, relate | Copyright risk, availability, rating | Material cards, source rights, handoff outputs | Current `materials`, assets typed panel; future `libraries.py` | `material_card`, `asset_collection`, future enhanced material metadata | Partial. Material cards exist; V6 needs taxonomy, filtering, relation graph, and deeper editor. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (9).png` | Production | Detailed Outline / Chapter Plan | Production flow | Project/data/model/autosave/search | Current chapter plan, scene/rhythm table, chapter goals, conflict design, information points, foreshadowing, risks, generation status | Scene, beat, conflict, information point, hook, word budget | Generate, edit, apply, validate | Risk, pending, completed | Outline, world, characters, material cards | `modules/chapter_plan`, `modules/production_chain`, `/product/production/*` | `chapter_plan`, `chapter_plan_version`, `foreshadowing_thread` | First version-chain slice implemented. UI can create/open chapter-plan versions and generation-run records; deep structured editor and continuity risk panel remain. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_42_51 (10).png` | Production | Context Builder | Production flow | Project/data/model/autosave/search | Source list with toggles, assembly flow, context preview, token budget, risk reminders, quality evaluation | Asset source, priority, token count, selected state | Build context, preview, send to chapter production | Token overrun, conflict, source risk | RAG context, Qdrant/local search, assets | `storage/rag_context.py`, `modules/context_builder`, `/product/context/*` | `context_build_plan`, `context_bundle`; retrieval metadata on draft/review/knowledge | First workbench slice implemented. UI can create/open context plans and bundles with backend/top-k/token budget and replay. Remaining depth: manual source toggles, conflict warnings, send-to-generation shortcut. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (1).png` | Management | Model Evaluation Center | AI evaluation and management tools | Local/data/model/autosave/search | Score metrics, model-task matrix, benchmark ranking, cost vs quality, prompt version management, A/B tests, routing rules, dataset distribution, recent runs, failure analysis | Model/task/score/cost/latency/prompt version/routing rule/result | Run benchmark, create rule, open report | Running, completed, failed, activated | Model adapters, prompt versions, task outputs, review scores | Current model adapters and metadata; future `evaluation.py` router | Future `model_profile`, `model_benchmark_task`, `model_benchmark_run`, `model_comparison_report`, `prompt_version` | Weak partial. Provider health and metadata exist; no benchmark center or prompt regression assets. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (2).png` | Production and publishing | Publishing Center, variant A | Publishing tools | Project/data/model/autosave/search | Calendar, chapter queue, platform status, package info, title suggestions, risk detection, hook check, publishing log, publishing actions | Chapter, title, status, planned time, platform sync, risk row | Publish now, schedule, batch publish, emergency publish, export report | Pending publish, draft, synced, platform abnormal, high/mid/low risk | Drafts, review/audit reports, platform profiles, exports | Current draft export/publish record; future `publishing.py` router | `draft_chapter`, future `publishing_plan`, `publish_gate_report`, `release_package`, `publishing_log` | Partial. Export and publish record exist; no publishing calendar, platform checks, or publish gate. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (3).png` | Management | Production Control Center | Global control, content management, production scheduling, analysis, system management | Data unbacked/model/autosave/search | Production pipeline, dependency graph, current blockers, human confirmation nodes, quality gates, recovery/retry, runtime log, quick actions | Pipeline phase, dependency node, quality score, run log | Push next step, handle blocker, recover failed task, retry failed node, export report | Completed, running, blocked, waiting confirmation, not started | Tasks, batch items, handoffs, reviews, health, audit | Current tasks/recovery/health/project audit; future `control.py`/`agents.py` | `task_status`, `batch_task_item`, `task_dead_letter`, future `agent_run`, `agent_gate`, `project_metric_snapshot` | Partial. Task center and recovery exist; not yet a unified production control graph. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (4).png` | Production and publishing | Publishing Center, variant B | Publishing tools | Project/data/model/autosave/search | Similar to variant A, with different platform/status labels | Similar to variant A | Similar to variant A | Pending publish, draft, synced, abnormal | Same as variant A | Same as variant A | Same as variant A | Duplicate/variant. Use as alternate layout reference, not separate feature. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (5).png` | Production | Chapter Production, variant A | Chapter production, review center, publishing, feedback, AI editor | Project/model/autosave/search | Chapter queue, current chapter, generation settings, preflight checklist, generation progress, recent generations, start generation card | Chapter, status, words, quality, time | Batch manage, edit setting, start generation, open record | High risk, passed, warning, queued, running | Chapter plans, context bundles, style/quality profiles, models, audits | Current draft generation/workbench plus `modules/context_builder` and `modules/production_chain` | `chapter_plan`, `draft_chapter`, `generation_run`, `context_bundle`, `style_profile`, `quality_standard_profile` | Partial. Draft generation now records context bundle, draft version, and generation run; production queue with progress/preflight UI depth remains. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (6).png` | Feedback | Reader Feedback Center image with title conflict | Left nav highlights AI Editor, but content is feedback analytics | Project/data/model/autosave/search | Data source import, date filter, data overview, sentiment distribution, selling/poison point analysis, retention curve, character popularity, conversion funnel, latest comments, risk warning | Platform source, comment count, sentiment, risk count, character heat | Add source, import settings, refresh, apply to plot | Positive/neutral/negative, high/mid/low risk | Reader feedback imports, feedback insight, publishing logs | Current feedback import/analyze CLI and schema; future `feedback.py` router/UI | `reader_feedback`, `feedback_insight`, future `feedback_import_batch`, `reader_sentiment_report` | Partial backend, weak UI. Also a UI naming conflict: title says AI Editor while content is feedback center. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (7).png` | Production | Chapter Production, variant B | Chapter production | Project/data/model/autosave/search | Similar to variant A with slightly different layout and labels | Similar to variant A | Start generation, settings, record | Running, waiting, high risk | Same as variant A | Same as variant A | Same as variant A | Duplicate/variant. Use as layout option. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (8).png` | Production and publishing | Publishing Center, variant C | Publishing tools | Project/data/model/autosave/search | Publishing calendar, queue, platform status, package info, title suggestions, risk detection, hook score, publishing log, actions | Platform status, chapter queue, risk rows, log rows | Publish, schedule, batch, emergency, export | Synced, pending sync, abnormal, published | Same as variant A | Same as variant A | Same as variant A | Duplicate/variant. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (9).png` | Production | Chapter Production, variant C | Chapter production | Project/model/autosave/search | Similar to variants A/B | Similar to variants A/B | Start generation, settings, record | Running, queued, high risk | Same as variant A | Same as variant A | Same as variant A | Duplicate/variant. |
| `docs/new/ui/ChatGPT Image 2026年6月26日 22_43_12 (10).png` | Production | AI Editor | Production, AI tools | Project/data/model/autosave/saved time/search | Rich text editor, toolbar, AI suggestions, writing assistant tabs, related documents, bottom action bar | Chapter title, text, word count, lines, related material cards | Apply suggestion, insert suggestion, regenerate suggestions, continue writing, polish, expand, shorten, summarize outline, version history, export | Saved, autosave, suggestion cards | Draft chapter, context, related assets, review issues, versions | Current draft editor/save/diff/export; future `editor.py` or `drafts.py` service | `draft_chapter`, `revision_plan`, future `editor_patch`, `draft_diff_report`, `generation_run` | Partial. Current editor can read/edit/save/export but is not rich text and lacks paragraph-level suggestions/apply/rollback UI. |

## Missing or Ambiguous UI Coverage

The image set does not contain a clear dedicated page for:

- Review Center, though it is present in navigation and is central in docs.
- Originality Protection Center.
- Change Impact Analysis Center, except related concepts in production control and setting bible.
- Settings Center.
- Published Fiction Craft Analysis and Classic Literary Analysis now have shared real workbench coverage; deeper per-mode visualization is still pending.
- Asset Converter now exists as a real conversion workbench; batch conversion policies and review gates can still deepen.
- Quality Standards Center and Style Center.

One image has a title/content conflict: `22_43_12 (6)` is titled `AI 编辑器`, but the content is reader feedback analytics. Treat it as Reader Feedback Center intent until the design is clarified.

## Current UI Implementation Summary

Current frontend files are concentrated in:

```text
web/admin/app/layout.tsx
web/admin/app/page.tsx
web/admin/app/globals.css
```

Observed scale:

- `web/admin/app/page.tsx`: about 6.8k lines, all tabs, types, state, fetch calls, panels, typed asset workbench, handoff workbench, analysis/context/production-chain workbenches, tasks, drafts, reviews, and helpers in one file.
- `web/admin/app/globals.css`: about 1.5k lines.
- `web/admin/package.json` uses `next lint`, which is not a valid lint entry for the installed Next version.

Current tab set follows the V6/V7 grouped IA in one page. Phase 2 shell semantics are present, but component extraction and routed feature modules are still needed before adding much more UI depth.

## UI Implementation Update 2026-06-28

The frontend is no longer a single-page-only implementation. V6 feature pages now exist under `web/admin/app/features/*`, and the P2 UI gaps have been upgraded as follows:

| Area | Current status |
|---|---|
| Publishing Center | Implemented inside the quality/publishing feature flow with release package version registry, publishing calendar summary, platform rule snapshots, publishing log table, rollback evidence, and configurable local channel/cadence/start date. |
| Publishing Adapters | Implemented `local_file`, `manual_web`, and guarded `external_webhook` adapter boundaries. UI can prepare platform payloads; real external execution is fail-closed unless explicitly configured. |
| Asset Workbench | Asset detail now includes typed deep editor fields plus layered reference graph visualization from `/product/assets/graph`. |
| Change Impact Analysis | Reports now display severity summary, impacted nodes, impact edges, and recommended actions, not only tabular counts. |
| Frontend Tests | `web/admin/tests/feature-architecture.test.mjs` verifies the V6/V7 navigation groups, routed feature modules, publishing/graph/impact affordances, and API client endpoints. `web/admin/tests/playwright-smoke.test.mjs` provides optional browser-level smoke coverage when Playwright is installed. |
| Documentation Status | `v6-v7-gap-analysis.md`, `v6-v7-implementation-plan.md`, and this inventory have been updated to reflect current implementation rather than Phase 0 state. |

Remaining UI depth is mostly refinement, not missing existence: graph zoom/search/minimap and named external platform panels can be added after local workflows stabilize.
