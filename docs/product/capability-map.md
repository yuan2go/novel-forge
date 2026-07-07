# Novel Operating System Capability Map

Updated: 2026-07-08
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`, starting commit `3f68522`

This map describes the product capability surface as verified from current code. "Implemented" means code/tests/routes exist for the capability; it does not always mean complete user-facing product maturity.

## V7 Content Intelligence Capability Delta

| Capability | Status | Evidence | Product Meaning | Remaining Gap |
|---|---|---|---|---|
| Genre OS | Implemented foundation | `modules/genre_os/`, `/product/genre/*`, `tests/unit/test_genre_os.py` | Genre/subgenre strategy packs can produce reader promise, core pleasures, required systems, chapter beats, risks, platform fit, and review rules | More calibrated genre packs and direct draft-policy enforcement |
| Style OS | Implemented foundation | `modules/style_os/`, `/product/style/*`, `tests/unit/test_style_os.py` | Authorized samples produce abstract style fingerprints, profiles, generation policies, review rules, and drift gates without raw sample leakage | Provider-assisted style critique and richer corpus workflows |
| Canon Graph 2.0 | Implemented foundation | `modules/canon_graph/service.py`, `tests/unit/test_canon_graph_plugins.py` | Genre-specific canon checks can turn critical conflicts into ReviewIssue evidence and typed graph reducer snapshots | Graph workbench conflict repair remains shallow |
| Quality Eval 2.0 | Implemented provider-evidence plus golden-set calibration foundation | `modules/quality_eval/`, `modules/evaluation_center/`, `/product/quality/*`, `/product/evaluation/*`, `tests/unit/test_quality_eval_v2.py` | Opening 3, Golden 10, Volume 30, Longform 100, provider judge run reports, human annotations, golden sets, provider judge calibration, and revision evidence exist | Real external provider calibration remains environment-dependent |
| Long-chain Proof Center | Implemented deterministic plus opt-in provider 50 proof | `modules/long_chain_proof/`, integration 50-chapter fixture | Pressure runs record checkpoint, context, quality, canon, style, reader fatigue, cost/quality trend, and provider chapter evidence | Real slow provider run is opt-in, not default |
| Publishing/Feedback Adapter 2.0 | Implemented manual plus generic HTTP adapter, hardened Fanqie/Qidian manual slices, and feedback mutation apply chain | `modules/publishing_feedback_adapters/`, API router, unit tests | Manual upload packages, project-scoped platform rule snapshots, platform-specific checklist/profile sections, platform adapter gate, receipt parser confidence/status normalization, secret redaction, generic API publish receipts, metrics/comments import, clusters, human-gated mutation proposals, patch artifacts, planned AgentTasks, re-review plans, and publish-gate rerun plans exist | Official platform SDK/callback/rate-limit behavior remains future work; AgentTasks are planned, not auto-dispatched |
| V7 UI / OS Cockpit | Implemented artifact workflow and production control foundation | `modules/novel_os_cockpit/service.py`, `web/admin/app/features/content-intelligence/`, `web/admin/app/features/os/` and route pages | Operators can trigger core actions, run provider/platform gates, inspect V1 artifact coverage, load/compare/mark assets needs-review, inspect gate board, feedback approval queue, multi-book cost/quality dashboard, and parallel schedule evidence | Browser route smoke remains optional without Playwright; guided repair stays review-only |
| Portfolio OS | Implemented schema-backed foundation | `modules/portfolio_os/`, `/product/portfolio/*`, `tests/unit/test_portfolio_os.py` | Portfolio projects, book potential scores, cross-book similarity reports, and non-dispatching resource allocation plans preserve per-book memory/context isolation and expose cost-quality/contamination evidence | Scheduler plan approval boundary remains the next slice |

## Capability Groups

| Group | Capability | Status | Evidence | Notes |
|---|---|---|---|---|
| Creative assets | Material system | Implemented | `modules/materials/`, `modules/ingestion/`, `web/admin/app/assets/page.tsx` | Rights, usage, and source-governance caller migration still need consistent production enforcement |
| Creative assets | Source Governance | Implemented foundation | `modules/source_intake/service.py`, `/product/sources/*`, `tests/unit/test_source_intake.py` | SourcePolicy, SourceSyncJob, SourceSnapshot, LicenseCheckResult, SourceRiskReport, R0-R4 eligibility, evidence-only/quarantine, and ApprovalRequest hooks exist; connector sync/diff and full caller migration remain partial |
| Creative assets | Genre/topic system | Implemented | `modules/topics/`, `modules/platform_strategy/`, `skills/topic-development/` | Market feedback integration is partial |
| Creative assets | Genre OS content intelligence | Implemented foundation | `modules/genre_os/`, `web/admin/app/genre-console/page.tsx` | Draft-policy use and calibration depth are partial |
| Creative assets | Worldbuilding | Implemented | `modules/worldbuilding/service.py`, `skills/worldbuilding/` | Advanced contradiction governance depends on Canon/KG |
| Creative assets | Character system | Implemented/partial | `modules/characters/`, `web/admin/app/character-console/page.tsx` | Character cards exist; deep lifecycle UI is partial |
| Creative assets | Templates/style/standards | Partially implemented | `modules/style/`, `modules/standards/`, schemas | Product library depth is partial |
| Creative assets | Style OS | Implemented foundation | `modules/style_os/`, `web/admin/app/style-console/page.tsx` | Raw sample isolation is enforced; provider-backed style judgment remains partial |
| Deconstruction | Web fiction analysis | Implemented | `modules/decomposition/`, `modules/analysis/`, `skills/hot-novel-deconstruction/` | Provider-backed extraction quality remains partial |
| Deconstruction | Hot novel business analysis | Partially implemented | `skills/hot-novel-business-deconstruction/`, `modules/analysis/` | Business analytics loop not fully productized |
| Deconstruction | Published fiction craft analysis | Partially implemented | `skills/published-fiction-craft-analysis/`, `modules/analysis/` | Code paths exist but workflow depth varies |
| Deconstruction | Classic literary depth analysis | Partially implemented | `skills/classic-literary-depth-analysis/`, `modules/analysis/` | Needs stronger source lineage and review workflows |
| Generation | Topic -> world -> character -> outline | Implemented | `modules/topics/`, `worldbuilding/`, `characters/`, `outline/` | Works as schema-backed local chain |
| Generation | Chapter plan | Implemented with embedded blueprint contract | `modules/chapter_plan/`, `tests/unit/test_chapter_blueprint_contract.py`, `skills/chapter-outline/` | Standalone SceneBeat lifecycle can deepen later |
| Generation | Draft prose | Implemented/partial with blueprint, readable-prose gate, and revision-strategy evidence | `modules/drafting/`, `modules/content_quality_loop/`, `modules/review_issue/`, `modules/revision/`, CLI `draft`, blueprint/readability/strategy tests | Production provider evidence must remain guarded; final unified proof is deferred |
| Generation | Image/architecture prompts | Partially implemented | `modules/image_prompts/`, creative asset schemas | Product workflow depth is partial |
| Review | Review report | Implemented | `modules/review/`, `web/admin/app/review/page.tsx` | Semantic quality is still improving |
| Review | ReviewIssue gate | Implemented/partial | `modules/review_issue/`, `skills/review-issue-gate/` | Full release gate coverage continues to harden |
| Review | Editor/revision | Implemented | `modules/editor/`, `modules/revision/`, `web/admin/app/editor/page.tsx` | Versioned rollback UX remains partial |
| Long-form stability | Canon | Partially implemented | `modules/canon_graph/`, `web/admin/app/canon-console/page.tsx` | Merge/conflict handling remains an expansion area |
| Long-form stability | Canon Graph 2.0 plugins and v1 reducer | Implemented foundation plus accepted-chapter reducer evidence | `modules/canon_graph/service.py`, `modules/longform_stability/service.py`, `web/admin/app/canon-graph-v2/page.tsx` | Plugin outputs and v1 reducer snapshots exist; operator repair UX remains partial |
| Long-form stability | Arc | Partially implemented | schemas, `web/admin/app/arc-console/page.tsx` | Service depth is limited |
| Long-form stability | Foreshadowing | Partially implemented with reducer projection | schemas, `modules/longform_stability/service.py`, `web/admin/app/foreshadowing-console/page.tsx` | Payoff SLA/status transition workflows remain limited |
| Long-form stability | Reader Promise Ledger | Implemented foundation | `modules/reader_promise/`, `modules/longform_stability/service.py`, `/product/longform-stability/reader-promise-ledger`, `tests/unit/test_reader_promise_ledger.py` | Promise/payoff lifecycle, broken-promise ReviewIssue, and RevisionTask hook exist; payoff detection remains deterministic and needs calibration/UI repair depth |
| Long-form stability | Chapter Economy / Pleasure Points | Implemented foundation | `modules/chapter_economy/`, `modules/content_quality_loop/service.py`, `modules/longform_stability/service.py`, `/product/quality/chapter-economy`, `tests/unit/test_chapter_economy.py` | PleasurePoint and ChapterEconomyReport assets, water/repetition risk, ReviewIssue/RevisionTask hook, content loop and reducer integration exist; calibration/UI repair depth remains partial |
| Long-form stability | Character Pressure | Implemented foundation | `modules/character_pressure/`, `modules/content_quality_loop/service.py`, `modules/longform_stability/service.py`, `/product/quality/character-pressure`, `tests/unit/test_character_pressure.py` | ProtagonistCharmReport and AntagonistPressureReport assets, weak-agency/weak-pressure ReviewIssue, RevisionTask hook, content loop and reducer integration exist; calibration/UI repair depth remains partial |
| Review | Mobile Reading Gate | Implemented foundation | `modules/mobile_reading/`, `modules/content_quality_loop/service.py`, `/product/quality/mobile-reading`, `tests/unit/test_mobile_reading.py` | MobileReadingReport asset, dense paragraph ReviewIssue, mobile reflow RevisionTask hook, content loop and chapter bus evidence exist; calibration/UI repair depth remains partial |
| Long-form stability | Longform recap | Partially implemented with explicit light/formal cadence | `modules/longform_recap/`, `web/admin/app/longform-recap/page.tsx`, `tests/unit/test_longform_recap_agent.py` | Agent operation exists for slices; operator-configurable cadence UI remains partial |
| Long-form stability | Long-chain acceptance | Partially implemented | `tests/integration/test_novel_os_long_chain_*` | Full-novel production not proven |
| Long-form stability | Long-chain Proof Center | Implemented deterministic plus provider-proof manifest foundation | `modules/long_chain_proof/`, `modules/v7_provider_proof/`, `/product/provider-proof/v7`, `tests/unit/test_v7_provider_proof.py`, `tests/integration/test_long_chain_50_chapter_content_intelligence.py` | State/evidence proof exists; provider-backed slow proof is opt-in and now classifies external/fixture/missing proof |
| Knowledge OS | MKAOS ingestion | Implemented slices | `modules/mkaos_ingestion/`, acceptance tests | Professional book import and quality checks exist; source governance eligibility should be consumed consistently before expanding corpora |
| Knowledge OS | MKAOS selection/quality/lineage | Partially implemented | `modules/mkaos/`, `modules/mkaos_quality/`, `modules/mkaos_lineage/` | Full learning loop remains partial |
| Knowledge OS | Knowledge graph learning | Partially implemented | `modules/novel_kg/`, MKAOS graph tests | Graph backend optional/depth partial |
| Context | Context Builder | Partially implemented with stage profile contract | `modules/context_builder/`, `web/admin/app/context/page.tsx`, `tests/unit/test_context_builder_stage_profiles.py` | Manual and KG-backed context controls need depth; final full-loop profile assertions remain deferred |
| Context | RAG/local search/vector search | Partially implemented | storage indexes, `modules/pgvector_store/`, Qdrant commands | Production retrieval quality needs more evaluation |
| Automation | Workflow runtime | Partially implemented | `modules/workflow_nodes/`, workflow tests | More node coverage and product UI depth needed |
| Automation | Agent registry/scheduler | Partially implemented | `modules/agent_registry/`, `modules/agent_scheduler/`, agent tests | Not a complete autonomous Agent Center |
| Automation | Loop Engineering | Partially implemented | `modules/loop_kernel/`, tests | Feedback/learning loops need product governance |
| Evaluation | Eval Center | Partially implemented with golden sets/calibration | `modules/evaluation_center/`, `web/admin/app/evaluation/page.tsx` | Provider benchmark/routing policy partial |
| Evaluation | Quality Eval 2.0 | Implemented foundation | `modules/quality_eval/`, `web/admin/app/quality-eval-v2/page.tsx` | Human annotations, golden sets, and provider calibration assets exist; real external premium judge calibration remains environment-dependent |
| Evaluation | Runtime ledger/cost | Partially implemented | `modules/runtime_ledger/`, `web/admin/app/cost-dashboard/page.tsx` | Universal evidence coverage remains a key gap |
| Publishing | Platform strategy | Partially implemented | `modules/platform_strategy/`, `skills/platform-strategy-os/` | Real platform adapters are partial |
| Publishing | Publish gate/release package | Partially implemented | `modules/publishing/`, `web/admin/app/publish-gate/page.tsx`, tests | Positive production-ready fixtures and explicit gate checks must continue |
| Publishing | V1 local export package | Implemented development slice | `modules/chapter_production_bus/service.py`, `tests/unit/test_context_and_production_chain.py` | Chapter bus writes generated-draft-only markdown plus export manifest, provenance, source-isolation policy, operator checklist, rollback metadata, and manual handoff; platform auto-publish remains out of scope |
| Publishing | Publishing/Feedback Adapter 2.0 | Implemented manual/generic foundation | `modules/publishing_feedback_adapters/`, `web/admin/app/publishing-feedback-v2/page.tsx` | Fanqie/Qidian manual rule snapshots, platform gates, receipt parser confidence, feedback mutation patch/AgentTask plans, and status normalization exist; official SDK/callback/rate-limit integration pending |
| Operations | Permission/provider policy | Partially implemented with ApprovalRequest foundation | `modules/runtime_policy/`, `modules/permission_center/`, `model_adapters/guarded.py`, `tests/unit/test_permission_center.py` | `approval_request` assets now support approve/reject/expire lifecycle and snapshot aggregation; production hard-stop coverage and caller migration are ongoing |
| Operations | UI console | Implemented OS Cockpit foundation | `modules/novel_os_cockpit/service.py`, `web/admin/app/`, `web/admin/app/features/os/` | Project production board, V1 artifact coverage, reducer/recap/export/approval status, gate status, feedback approvals, multi-book cost/quality dashboard, and parallel schedule evidence exist; guided repair remains review-only |
| Operations | Portfolio OS | Implemented foundation | `modules/portfolio_os/`, API router, tests | Schema-backed portfolio projects, book potential scores, cross-book similarity reports, and allocation plans exist; actual multi-book dispatch remains approval-gated and future |

## Current Completion Estimate

Novel Forge is beyond a prototype CLI and has many OS runtime slices, but it is not yet a complete Novel Operating System product.

Current practical assessment:

- local creative pipeline: high coverage;
- MKAOS and quality gates: medium-high coverage, still hardening;
- Agent runtime: medium coverage;
- production provider/runtime governance: medium coverage, high priority;
- UI productization: medium coverage;
- full long-form autonomous production: partial and not yet proven.

The next maturity step is not adding more isolated features. It is closing the acceptance loop across provider policy, context, KG/Canon, ReviewIssue, publishing gates, Agent scheduling, rollback, tests, and operator UI.
