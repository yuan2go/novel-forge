# Project Current State

Updated: 2026-07-07
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`, commit `75bb3e3`

Autonomous Novel OS is the product target: a local-first operating system for long-term, low-manual-intervention, quality-gated premium web-novel production.

The current code/runtime baseline is Novel Forge v6. The repository/package/CLI name remains `novel-forge`; do not rename code paths without a dedicated migration.

Current priority: v1 single-book production closure before broader multi-book, SaaS, or platform automation.

This document describes the current state as observed from code, tests, configuration, routes, and skills. It does not treat historical docs as truth unless code evidence exists.

## Evidence Base

- Product blueprints: `docs/blueprint/autonomous-novel-os-full-blueprint.md`, `docs/blueprint/novel-os-project-blueprint.md`
- Current blueprint control reports: `docs/reports/blueprint-gap-audit.md`, `docs/reports/module-maturity-matrix.md`, `docs/reports/data-model-gap-matrix.md`, `docs/reports/v1-v7-roadmap.md`, `docs/reports/next-production-slices.md`
- CLI: `src/novel_forge/cli.py`
- API: `src/novel_forge/api/app.py`, `src/novel_forge/api/routers/`
- Product services: `src/novel_forge/api/services/`
- Domain/runtime modules: `src/novel_forge/modules/`
- Schemas: `src/novel_forge/schemas/assets.py`
- UI: `web/admin/app/`
- Tests: `tests/unit/`, `tests/integration/`, `tests/acceptance/`
- Commands: `Makefile`, `pyproject.toml`, `web/admin/package.json`, `docker-compose.yml`
- Skills: `skills/`, `.claude/skills/`, `scripts/sync_claude_skills.py`

## V7 Content Intelligence Foundation State

The current branch has implemented the first V7 content intelligence foundation as schema-backed assets, services, API routes, Agent operations, workflow processors, tests, and basic Web Admin consoles. This is a foundation slice, not proof of full autonomous long-novel production.

| Capability | Current Status | Evidence | Remaining Gap |
|---|---|---|---|
| Genre OS | Implemented foundation | `modules/genre_os/`, `api/routers/genre_os.py`, `tests/unit/test_genre_os.py` | More calibrated packs per platform/genre and deeper draft-policy use |
| Style OS | Implemented foundation | `modules/style_os/`, `api/routers/style_os.py`, `tests/unit/test_style_os.py` | Provider-assisted style review and richer corpus comparison |
| Canon Graph 2.0 plugins | Implemented foundation plus typed graph reducer | `modules/canon_graph/service.py`, `tests/unit/test_canon_graph_plugins.py` | Human-grade conflict resolution and graph UI depth |
| Quality Eval 2.0 | Implemented provider-evidence, provider run report, and golden-set calibration foundation | `modules/quality_eval/`, `modules/evaluation_center/`, `modules/model_router/`, `tests/unit/test_quality_eval_v2.py` | Real external provider calibration still requires credentials and operator approval |
| Long-chain Proof Center | Implemented deterministic plus opt-in provider 50 proof and V7 provider proof manifest | `modules/long_chain_proof/`, `modules/v7_provider_proof/`, `/product/provider-proof/v7`, `tests/unit/test_long_chain_proof.py`, `tests/unit/test_v7_provider_proof.py` | Real credentialed provider proof is not a default local test |
| Publishing/Feedback Adapter 2.0 | Implemented manual plus generic HTTP API adapter, Fanqie/Qidian project-scoped rules, adapter gate, receipt parser confidence, approved feedback patch/AgentTask application chain | `modules/publishing_feedback_adapters/`, API router, unit tests | Commercial platform SDK/callback/rate-limit behavior remains future work; feedback AgentTasks are planned, not auto-dispatched |
| Agent/Workflow coverage | Implemented foundation plus provider/platform/V7 proof operations | `modules/agent_scheduler/service.py`, `modules/workflow_nodes/service.py` | Production provider adapters still require explicit environment configuration |
| Web Admin V7/OS consoles | Implemented foundation plus Artifact Inspector, provider judge controls, platform gate controls, and project production Cockpit | `web/admin/app/features/content-intelligence/`, `web/admin/app/features/os/`, route pages | Browser smoke remains optional without Playwright; guided repair remains review-only |

## Capability Fact Table

| Capability | Current Status | Evidence | Main Gap | Docs Update Needed | Expansion Risk |
|---|---|---|---|---|---|
| Project management | Implemented | `api/routers/projects.py`, `modules/project_operations/service.py`, `web/admin/app/projects/page.tsx`, `tests/unit/test_project_operations.py` | Product UX depth and multi-user semantics remain partial | Yes | Medium |
| Genre/topic library | Implemented | `modules/topics/service.py`, `modules/platform_strategy/service.py`, `schemas/assets.py`, `skills/topic-development/` | Market feedback loop is partial | Yes | Medium |
| Genre OS content intelligence | Implemented foundation | `modules/genre_os/service.py`, `api/routers/genre_os.py`, `tests/unit/test_genre_os.py` | Deeper platform-calibrated strategy packs and generation-policy use | Yes | Medium |
| Material library | Implemented | `modules/materials/service.py`, `modules/ingestion/service.py`, `web/admin/app/assets/page.tsx` | Usage lifecycle and source-governance caller migration vary by path | Yes | Medium |
| Source Governance | Implemented foundation | `modules/source_intake/service.py`, `api/routers/handoffs.py`, `schemas/assets.py`, `tests/unit/test_source_intake.py` | Connector sync/diff, material usage feedback, and Context Builder/MKAOS caller migration remain partial | Yes | High |
| Knowledge library | Implemented | `modules/knowledge/service.py`, `modules/mkaos/`, `schemas/assets.py` | Production selection quality still improving | Yes | Medium |
| MKAOS | Partially implemented, broad coverage | `modules/mkaos*`, `tests/unit/test_mkaos_*.py`, `tests/integration/test_mkaos_*.py` | Full production learning loop and graph depth are still partial | Yes | High |
| Web-fiction deconstruction | Implemented | `modules/decomposition/service.py`, `modules/analysis/service.py`, `skills/hot-novel-deconstruction/` | Provider-backed high-quality extraction is partial | Yes | Medium |
| Published/classic fiction analysis | Partially implemented | `modules/analysis/service.py`, `skills/published-fiction-craft-analysis/`, `skills/classic-literary-depth-analysis/` | Product workflow depth and corpus-scale evaluation are partial | Yes | Medium |
| Hot novel business deconstruction | Partially implemented | `skills/hot-novel-business-deconstruction/`, `modules/analysis/service.py` | Business analytics integration is partial | Yes | Medium |
| Outline generation | Implemented | `modules/outline/service.py`, `skills/long-outline/`, tests under `test_module_services.py` | Agent operation and platform feedback coupling are partial | Yes | Medium |
| Chapter plan / detailed outline | Implemented with embedded blueprint contract | `modules/chapter_plan/service.py`, `tests/unit/test_chapter_blueprint_contract.py`, `skills/chapter-outline/` | Standalone scene-beat lifecycle and final full-loop proof remain pending | Yes | Medium |
| Draft generation | Implemented for local/runtime slices with blueprint, readable-gate, mobile-reading, chapter-economy, and character-pressure evidence | `modules/drafting/service.py`, `modules/content_quality_loop/service.py`, `modules/mobile_reading/service.py`, CLI `draft`, `tests/unit/test_chapter_blueprint_contract.py`, `tests/unit/test_content_quality_loop.py`, `tests/unit/test_mobile_reading.py` | Production provider hard-stop coverage and final unified full-loop proof remain pending | Yes | High |
| Style OS | Implemented foundation | `modules/style_os/service.py`, `api/routers/style_os.py`, `tests/unit/test_style_os.py` | Provider-backed style judge and richer style library workflows | Yes | Medium |
| Review center | Implemented, still deepening | `modules/review/service.py`, `modules/review_issue/service.py`, `web/admin/app/review/page.tsx`, tests | Semantic/model-assisted review quality is partial | Yes | High |
| Revision/editor | Implemented with issue strategy contract | `modules/review_issue/service.py`, `modules/editor/service.py`, `modules/revision/service.py`, `modules/loop_kernel/service.py`, `web/admin/app/editor/page.tsx` | Multi-version UX, rollback depth, and real improvement metrics are partial | Yes | Medium |
| Long-form stability | Partially implemented with reducer and recap cadence evidence | `modules/longform_stability/`, `modules/longform_recap/`, `tests/unit/test_longform_stability.py`, `tests/unit/test_longform_recap_agent.py`, `tests/integration/test_novel_os_long_chain_*` | Promise lifecycle, operator cadence configuration, and full novel-scale autonomous stability are not proven | Yes | High |
| Long-chain proof | Implemented deterministic plus opt-in provider 50 proof and provider-proof manifest | `modules/long_chain_proof/service.py`, `modules/v7_provider_proof/service.py`, `tests/unit/test_long_chain_proof.py`, `tests/unit/test_v7_provider_proof.py`, `tests/integration/test_long_chain_50_chapter_content_intelligence.py` | Real provider-backed chapter generation proof is not default local test | Yes | High |
| Canon | Partially implemented | `modules/canon_graph/service.py`, `web/admin/app/canon-console/page.tsx`, `tests/unit/test_canon_graph*.py` | Human-grade conflict resolution and merge workflows are partial | Yes | High |
| Canon Graph 2.0 plugins | Implemented foundation plus shared reducer target | `modules/canon_graph/service.py`, `modules/longform_stability/service.py`, `tests/unit/test_canon_graph_plugins.py`, `tests/unit/test_longform_stability.py` | Genre-specific conflict fix UX remains partial | Yes | High |
| Arc / foreshadowing | Partially implemented with reducer projection | schemas `ArcPlan`, `ForeshadowingGraph`, UI routes `arc-console`, `foreshadowing-console`, `modules/longform_stability/service.py` | Payoff SLA/status transitions remain shallow | Yes | Medium |
| Character / villain | Partially implemented with character-pressure gate foundation | `modules/characters/service.py`, `modules/character_pressure/service.py`, schemas `CharacterCard`, `VillainOperationPlan`, `ProtagonistCharmReport`, `AntagonistPressureReport`, UI `character-console`, `tests/unit/test_character_pressure.py` | Character pressure scoring is deterministic and needs calibration plus guided repair UI depth | Yes | Medium |
| Context Builder | Partially implemented with stage profile contract | `modules/context_builder/service.py`, `api/routers/context_builder.py`, `web/admin/app/context/page.tsx`, `tests/unit/test_context_builder_stage_profiles.py` | Manual controls, KG-backed context, invalidation warnings, and final full-loop profile assertions still need depth | Yes | High |
| RAG / memory | Partially implemented | `storage/retrieval_index.py`, `modules/pgvector_store/service.py`, `modules/long_memory/service.py`, Qdrant commands | Production-scale retrieval quality and external service coverage are partial | Yes | High |
| OS Envelope | Partially implemented | `modules/os_envelope/service.py`, MKAOS envelope tests | Universal enforcement across all paths is incomplete | Yes | High |
| Agent Center | Partially implemented | `modules/agent_registry/`, `modules/agent_scheduler/`, `web/admin/app/agent-*`, tests | Operation coverage and production UI depth remain partial | Yes | High |
| Approval / permission gates | Implemented foundation | `modules/permission_center/service.py`, `/product/permission-center/*`, `tests/unit/test_permission_center.py` | High-risk callers still need staged migration to `approval_request` refs | Yes | High |
| Feedback loop | Partially implemented | `modules/feedback/`, `modules/feedback_backflow/`, `web/admin/app/feedback*`, tests | Real reader cohort analytics and plan mutation governance need depth | Yes | Medium |
| Publishing/feedback adapters | Implemented manual plus generic HTTP adapter, Fanqie/Qidian parser/status/gate/rule-snapshot slices, and feedback mutation apply chain | `modules/publishing_feedback_adapters/service.py`, API router, `tests/unit/test_publishing_feedback_adapters.py` | Specific platform SDKs, callbacks, real platform rate limits, and automatic feedback-task dispatch are not integrated | Yes | Medium |
| Quality gate | Partially implemented | `modules/evaluation_center/`, `modules/mkaos_quality/`, `modules/mkaos_production_gate/`, tests | Unified gate semantics across all releases are still being hardened | Yes | High |
| Quality Eval 2.0 | Implemented provider-evidence, provider run report, and golden-set calibration foundation | `modules/quality_eval/service.py`, `modules/evaluation_center/service.py`, API routers, `tests/unit/test_quality_eval_v2.py` | Real external provider calibration remains environment-dependent | Yes | High |
| Release package / publishing | Partially implemented | `modules/publishing/`, `api/routers/audit.py`, `web/admin/app/publish-gate/page.tsx`, tests | Platform adapters/calendar and explicit gate checks need more production coverage | Yes | High |
| UI console / Project Cockpit | Implemented shell plus project production Cockpit, provider/platform controls, multi-book schedule depth, and V1 artifact coverage data | `modules/novel_os_cockpit/service.py`, `web/admin/app/`, `web/admin/app/features/os/`, `web/admin/app/features/content-intelligence/`, `tests/unit/test_novel_os_cockpit.py` | Guided repair workflows remain review-only; dashboard does not replace final acceptance proof | Yes | Medium |
| Database | Partially implemented | local JSON storage, `docker-compose.yml`, Postgres migrations/tests, `modules/pgvector_store/` | Postgres/local fallback strategy is still being hardened | Yes | High |
| Tests | Implemented broad suite | `tests/unit`, `tests/integration`, `tests/acceptance`, `Makefile` | Browser smoke is optional; full provider tests need secrets/fixtures | Yes | Medium |
| Export | Partially implemented with v1 local handoff | `modules/chapter_production_bus/service.py`, release package/publishing assets, local markdown export manifest/provenance/checklist paths | Platform-specific export adapters and final unified multi-chapter publish handoff coverage are partial | Yes | Medium |
| Platform adaptation | Partially implemented | `modules/platform_strategy/service.py`, `skills/platform-strategy-os/` | Real platform policy/API integration is partial | Yes | Medium |
| Skills | Implemented | root `skills/`, `.claude/skills/`, `scripts/sync_claude_skills.py`, tests | Runtime drift must stay checked; external runtime skills are not project source | Yes | Medium |
| CLI / scripts | Implemented | `src/novel_forge/cli.py`, `scripts/`, `Makefile` | README commands must prefer module invocation unless package installed | Yes | Low |
| Eval Center | Partially implemented with golden set and calibration assets | `modules/evaluation_center/service.py`, `api/routers/evaluation.py`, `web/admin/app/evaluation/page.tsx`, tests | Full provider benchmarking/routing governance is partial | Yes | High |
| Loop Engineering | Partially implemented | `modules/loop_kernel/service.py`, `web/admin/app/loop-runs/page.tsx`, tests | Productized planning/retry/learning loops need depth | Yes | Medium |
| Longform Recap Agent | Partially implemented with explicit cadence | `modules/longform_recap/service.py`, `api/routers/longform_recap.py`, `tests/unit/test_longform_recap_agent.py`, scheduler tests | End-to-end production Agent coverage is not complete for all related roles | Yes | High |

## Current Risks

1. Historical docs still contain v5 wording and can mislead implementation decisions.
2. Several features have schemas, routes, and UI pages but are not complete product workflows.
3. Agent runtime and provider policy have strong slices, but universal production hard-stop coverage must continue to be verified.
4. Local JSON plus optional Postgres/Qdrant/MinIO/Celery creates two operational modes that need clear environment policy.
5. MKAOS, Context Builder, Canon/KG, ReviewIssue, Eval, and publishing must stay unified; new features should not create parallel paths.
6. The current implementation has broad V6/V7 runtime foundations, but the v1 single-book production loop is not yet proven as a 10-30 chapter closed workflow.

## Next Priorities

See [reports/v1-v7-roadmap.md](reports/v1-v7-roadmap.md) and [reports/next-production-slices.md](reports/next-production-slices.md). The most important next work is to close the v1 single-book production loop, then continue runtime hardening: portfolio project boundary, approval caller migration, provider evidence, release/publish gates, scheduler operation coverage, context/KG consistency, calibrated reader-promise/chapter-economy/character-pressure/mobile-reading detection, and productized UI verification.
