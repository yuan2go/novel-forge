# Novel Operating System Capability Map

Updated: 2026-07-06
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
| Publishing/Feedback Adapter 2.0 | Implemented manual plus generic HTTP adapter and Fanqie/Qidian manual slices | `modules/publishing_feedback_adapters/`, API router, unit tests | Manual upload packages, platform-specific rule/checklist profiles, platform adapter gate, receipt parser/status normalization, generic API publish receipts, metrics/comments import, clusters, and human-gated mutation proposals exist | Official platform SDK/callback behavior remains future work |
| V7 UI / OS Cockpit | Implemented artifact workflow and production control foundation | `web/admin/app/features/content-intelligence/`, `web/admin/app/features/os/` and route pages | Operators can trigger core actions, run provider/platform gates, load/compare/mark assets needs-review, inspect gate board, feedback approval queue, multi-book cost/quality dashboard, and parallel schedule evidence | Browser route smoke remains optional without Playwright; guided repair stays review-only |

## Capability Groups

| Group | Capability | Status | Evidence | Notes |
|---|---|---|---|---|
| Creative assets | Material system | Implemented | `modules/materials/`, `modules/ingestion/`, `web/admin/app/assets/page.tsx` | Rights and lineage still need consistent production enforcement |
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
| Generation | Chapter plan | Implemented | `modules/chapter_plan/`, `skills/chapter-outline/` | Continuity/KG hooks need ongoing depth |
| Generation | Draft prose | Implemented/partial | `modules/drafting/`, CLI `draft` | Production provider evidence must remain guarded |
| Generation | Image/architecture prompts | Partially implemented | `modules/image_prompts/`, creative asset schemas | Product workflow depth is partial |
| Review | Review report | Implemented | `modules/review/`, `web/admin/app/review/page.tsx` | Semantic quality is still improving |
| Review | ReviewIssue gate | Implemented/partial | `modules/review_issue/`, `skills/review-issue-gate/` | Full release gate coverage continues to harden |
| Review | Editor/revision | Implemented | `modules/editor/`, `modules/revision/`, `web/admin/app/editor/page.tsx` | Versioned rollback UX remains partial |
| Long-form stability | Canon | Partially implemented | `modules/canon_graph/`, `web/admin/app/canon-console/page.tsx` | Merge/conflict handling remains an expansion area |
| Long-form stability | Canon Graph 2.0 plugins | Implemented foundation | `modules/canon_graph/service.py`, `web/admin/app/canon-graph-v2/page.tsx` | Plugin outputs exist; operator repair UX remains partial |
| Long-form stability | Arc | Partially implemented | schemas, `web/admin/app/arc-console/page.tsx` | Service depth is limited |
| Long-form stability | Foreshadowing | Partially implemented | schemas, `web/admin/app/foreshadowing-console/page.tsx` | Service depth is limited |
| Long-form stability | Longform recap | Partially implemented | `modules/longform_recap/`, `web/admin/app/longform-recap/page.tsx` | Agent operation exists for slices, not all related roles |
| Long-form stability | Long-chain acceptance | Partially implemented | `tests/integration/test_novel_os_long_chain_*` | Full-novel production not proven |
| Long-form stability | Long-chain Proof Center | Implemented deterministic foundation | `modules/long_chain_proof/`, `tests/integration/test_long_chain_50_chapter_content_intelligence.py` | State/evidence proof exists; provider-backed slow proof is opt-in |
| Knowledge OS | MKAOS ingestion | Implemented slices | `modules/mkaos_ingestion/`, acceptance tests | Professional book import and quality checks exist |
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
| Publishing | Publishing/Feedback Adapter 2.0 | Implemented manual/generic foundation | `modules/publishing_feedback_adapters/`, `web/admin/app/publishing-feedback-v2/page.tsx` | Fanqie/Qidian manual rule profiles, platform gates, and receipt parsing exist; official SDK/callback/rate-limit integration pending |
| Operations | Permission/provider policy | Partially implemented | `modules/runtime_policy/`, `modules/permission_center/`, `model_adapters/guarded.py` | Production hard-stop coverage is ongoing |
| Operations | UI console | Implemented OS Cockpit foundation | `web/admin/app/`, `web/admin/app/features/os/` | Project production board, gate status, feedback approvals, multi-book cost/quality dashboard, and parallel schedule evidence exist; guided repair remains review-only |

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
