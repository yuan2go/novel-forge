# Novel Operating System Capability Map

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

This map describes the product capability surface as verified from current code. "Implemented" means code/tests/routes exist for the capability; it does not always mean complete user-facing product maturity.

## Capability Groups

| Group | Capability | Status | Evidence | Notes |
|---|---|---|---|---|
| Creative assets | Material system | Implemented | `modules/materials/`, `modules/ingestion/`, `web/admin/app/assets/page.tsx` | Rights and lineage still need consistent production enforcement |
| Creative assets | Genre/topic system | Implemented | `modules/topics/`, `modules/platform_strategy/`, `skills/topic-development/` | Market feedback integration is partial |
| Creative assets | Worldbuilding | Implemented | `modules/worldbuilding/service.py`, `skills/worldbuilding/` | Advanced contradiction governance depends on Canon/KG |
| Creative assets | Character system | Implemented/partial | `modules/characters/`, `web/admin/app/character-console/page.tsx` | Character cards exist; deep lifecycle UI is partial |
| Creative assets | Templates/style/standards | Partially implemented | `modules/style/`, `modules/standards/`, schemas | Product library depth is partial |
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
| Long-form stability | Arc | Partially implemented | schemas, `web/admin/app/arc-console/page.tsx` | Service depth is limited |
| Long-form stability | Foreshadowing | Partially implemented | schemas, `web/admin/app/foreshadowing-console/page.tsx` | Service depth is limited |
| Long-form stability | Longform recap | Partially implemented | `modules/longform_recap/`, `web/admin/app/longform-recap/page.tsx` | Agent operation exists for slices, not all related roles |
| Long-form stability | Long-chain acceptance | Partially implemented | `tests/integration/test_novel_os_long_chain_*` | Full-novel production not proven |
| Knowledge OS | MKAOS ingestion | Implemented slices | `modules/mkaos_ingestion/`, acceptance tests | Professional book import and quality checks exist |
| Knowledge OS | MKAOS selection/quality/lineage | Partially implemented | `modules/mkaos/`, `modules/mkaos_quality/`, `modules/mkaos_lineage/` | Full learning loop remains partial |
| Knowledge OS | Knowledge graph learning | Partially implemented | `modules/novel_kg/`, MKAOS graph tests | Graph backend optional/depth partial |
| Context | Context Builder | Partially implemented | `modules/context_builder/`, `web/admin/app/context/page.tsx` | Manual and KG-backed context controls need depth |
| Context | RAG/local search/vector search | Partially implemented | storage indexes, `modules/pgvector_store/`, Qdrant commands | Production retrieval quality needs more evaluation |
| Automation | Workflow runtime | Partially implemented | `modules/workflow_nodes/`, workflow tests | More node coverage and product UI depth needed |
| Automation | Agent registry/scheduler | Partially implemented | `modules/agent_registry/`, `modules/agent_scheduler/`, agent tests | Not a complete autonomous Agent Center |
| Automation | Loop Engineering | Partially implemented | `modules/loop_kernel/`, tests | Feedback/learning loops need product governance |
| Evaluation | Eval Center | Partially implemented | `modules/evaluation_center/`, `web/admin/app/evaluation/page.tsx` | Provider benchmark/routing policy partial |
| Evaluation | Runtime ledger/cost | Partially implemented | `modules/runtime_ledger/`, `web/admin/app/cost-dashboard/page.tsx` | Universal evidence coverage remains a key gap |
| Publishing | Platform strategy | Partially implemented | `modules/platform_strategy/`, `skills/platform-strategy-os/` | Real platform adapters are partial |
| Publishing | Publish gate/release package | Partially implemented | `modules/publishing/`, `web/admin/app/publish-gate/page.tsx`, tests | Positive production-ready fixtures and explicit gate checks must continue |
| Operations | Permission/provider policy | Partially implemented | `modules/runtime_policy/`, `modules/permission_center/`, `model_adapters/guarded.py` | Production hard-stop coverage is ongoing |
| Operations | UI console | Implemented shell | `web/admin/app/` | Route existence does not imply full workflow maturity |

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
