# Project Current State

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

Novel Forge v6 is a local-first AI novel production platform and early Novel Operating System runtime. The repository/package/CLI name remains `novel-forge`; Novel Operating System is the architecture target.

This document describes the current state as observed from code, tests, configuration, routes, and skills. It does not treat historical docs as truth unless code evidence exists.

## Evidence Base

- CLI: `src/novel_forge/cli.py`
- API: `src/novel_forge/api/app.py`, `src/novel_forge/api/routers/`
- Product services: `src/novel_forge/api/services/`
- Domain/runtime modules: `src/novel_forge/modules/`
- Schemas: `src/novel_forge/schemas/assets.py`
- UI: `web/admin/app/`
- Tests: `tests/unit/`, `tests/integration/`, `tests/acceptance/`
- Commands: `Makefile`, `pyproject.toml`, `web/admin/package.json`, `docker-compose.yml`
- Skills: `skills/`, `.claude/skills/`, `scripts/sync_claude_skills.py`

## Capability Fact Table

| Capability | Current Status | Evidence | Main Gap | Docs Update Needed | Expansion Risk |
|---|---|---|---|---|---|
| Project management | Implemented | `api/routers/projects.py`, `modules/project_operations/service.py`, `web/admin/app/projects/page.tsx`, `tests/unit/test_project_operations.py` | Product UX depth and multi-user semantics remain partial | Yes | Medium |
| Genre/topic library | Implemented | `modules/topics/service.py`, `modules/platform_strategy/service.py`, `schemas/assets.py`, `skills/topic-development/` | Market feedback loop is partial | Yes | Medium |
| Material library | Implemented | `modules/materials/service.py`, `modules/ingestion/service.py`, `web/admin/app/assets/page.tsx` | Rights/lineage enforcement varies by path | Yes | Medium |
| Knowledge library | Implemented | `modules/knowledge/service.py`, `modules/mkaos/`, `schemas/assets.py` | Production selection quality still improving | Yes | Medium |
| MKAOS | Partially implemented, broad coverage | `modules/mkaos*`, `tests/unit/test_mkaos_*.py`, `tests/integration/test_mkaos_*.py` | Full production learning loop and graph depth are still partial | Yes | High |
| Web-fiction deconstruction | Implemented | `modules/decomposition/service.py`, `modules/analysis/service.py`, `skills/hot-novel-deconstruction/` | Provider-backed high-quality extraction is partial | Yes | Medium |
| Published/classic fiction analysis | Partially implemented | `modules/analysis/service.py`, `skills/published-fiction-craft-analysis/`, `skills/classic-literary-depth-analysis/` | Product workflow depth and corpus-scale evaluation are partial | Yes | Medium |
| Hot novel business deconstruction | Partially implemented | `skills/hot-novel-business-deconstruction/`, `modules/analysis/service.py` | Business analytics integration is partial | Yes | Medium |
| Outline generation | Implemented | `modules/outline/service.py`, `skills/long-outline/`, tests under `test_module_services.py` | Agent operation and platform feedback coupling are partial | Yes | Medium |
| Chapter plan / detailed outline | Implemented | `modules/chapter_plan/service.py`, `skills/chapter-outline/` | Long-form continuity coverage needs more acceptance depth | Yes | Medium |
| Draft generation | Implemented for local/runtime slices | `modules/drafting/service.py`, `schemas/assets.py`, CLI `draft` | Production provider hard-stop coverage must remain enforced | Yes | High |
| Review center | Implemented, still deepening | `modules/review/service.py`, `modules/review_issue/service.py`, `web/admin/app/review/page.tsx`, tests | Semantic/model-assisted review quality is partial | Yes | High |
| Revision/editor | Implemented | `modules/editor/service.py`, `modules/revision/service.py`, `web/admin/app/editor/page.tsx` | Multi-version UX and rollback depth are partial | Yes | Medium |
| Long-form stability | Partially implemented | `modules/longform_stability/`, `modules/longform_recap/`, `tests/integration/test_novel_os_long_chain_*` | Full novel-scale autonomous stability is not proven | Yes | High |
| Canon | Partially implemented | `modules/canon_graph/service.py`, `web/admin/app/canon-console/page.tsx`, `tests/unit/test_canon_graph*.py` | Human-grade conflict resolution and merge workflows are partial | Yes | High |
| Arc / foreshadowing | Partially implemented | schemas `ArcPlan`, `ForeshadowingGraph`, UI routes `arc-console`, `foreshadowing-console` | Service/API depth is uneven | Yes | Medium |
| Character / villain | Partially implemented | `modules/characters/service.py`, schemas `CharacterCard`, `VillainOperationPlan`, UI `character-console` | Villain operations are mostly schema/UI-level | Yes | Medium |
| Context Builder | Partially implemented | `modules/context_builder/service.py`, `api/routers/context_builder.py`, `web/admin/app/context/page.tsx`, tests | Manual controls, KG-backed context, and invalidation warnings still need depth | Yes | High |
| RAG / memory | Partially implemented | `storage/retrieval_index.py`, `modules/pgvector_store/service.py`, `modules/long_memory/service.py`, Qdrant commands | Production-scale retrieval quality and external service coverage are partial | Yes | High |
| OS Envelope | Partially implemented | `modules/os_envelope/service.py`, MKAOS envelope tests | Universal enforcement across all paths is incomplete | Yes | High |
| Agent Center | Partially implemented | `modules/agent_registry/`, `modules/agent_scheduler/`, `web/admin/app/agent-*`, tests | Operation coverage and production UI depth remain partial | Yes | High |
| Feedback loop | Partially implemented | `modules/feedback/`, `modules/feedback_backflow/`, `web/admin/app/feedback*`, tests | Real reader cohort analytics and plan mutation governance need depth | Yes | Medium |
| Quality gate | Partially implemented | `modules/evaluation_center/`, `modules/mkaos_quality/`, `modules/mkaos_production_gate/`, tests | Unified gate semantics across all releases are still being hardened | Yes | High |
| Release package / publishing | Partially implemented | `modules/publishing/`, `api/routers/audit.py`, `web/admin/app/publish-gate/page.tsx`, tests | Platform adapters/calendar and explicit gate checks need more production coverage | Yes | High |
| UI console | Implemented shell, partial product depth | `web/admin/app/`, `web/admin/app/features/` | Some routes are reporting/console slices rather than full workflows | Yes | Medium |
| Database | Partially implemented | local JSON storage, `docker-compose.yml`, Postgres migrations/tests, `modules/pgvector_store/` | Postgres/local fallback strategy is still being hardened | Yes | High |
| Tests | Implemented broad suite | `tests/unit`, `tests/integration`, `tests/acceptance`, `Makefile` | Browser smoke is optional; full provider tests need secrets/fixtures | Yes | Medium |
| Export | Partially implemented | release package/publishing assets and storage/export paths | Platform-specific export adapters are partial | Yes | Medium |
| Platform adaptation | Partially implemented | `modules/platform_strategy/service.py`, `skills/platform-strategy-os/` | Real platform policy/API integration is partial | Yes | Medium |
| Skills | Implemented | root `skills/`, `.claude/skills/`, `scripts/sync_claude_skills.py`, tests | Runtime drift must stay checked; external runtime skills are not project source | Yes | Medium |
| CLI / scripts | Implemented | `src/novel_forge/cli.py`, `scripts/`, `Makefile` | README commands must prefer module invocation unless package installed | Yes | Low |
| Eval Center | Partially implemented | `modules/evaluation_center/service.py`, `web/admin/app/evaluation/page.tsx`, tests | Full provider benchmarking/routing governance is partial | Yes | High |
| Loop Engineering | Partially implemented | `modules/loop_kernel/service.py`, `web/admin/app/loop-runs/page.tsx`, tests | Productized planning/retry/learning loops need depth | Yes | Medium |
| Longform Recap Agent | Partially implemented | `modules/longform_recap/service.py`, `api/routers/longform_recap.py`, tests | End-to-end production Agent coverage is not complete for all related roles | Yes | High |

## Current Risks

1. Historical docs still contain v5 wording and can mislead implementation decisions.
2. Several features have schemas, routes, and UI pages but are not complete product workflows.
3. Agent runtime and provider policy have strong slices, but universal production hard-stop coverage must continue to be verified.
4. Local JSON plus optional Postgres/Qdrant/MinIO/Celery creates two operational modes that need clear environment policy.
5. MKAOS, Context Builder, Canon/KG, ReviewIssue, Eval, and publishing must stay unified; new features should not create parallel paths.

## Next Priorities

See [roadmap/current-roadmap.md](roadmap/current-roadmap.md). The most important next work is to keep closing production runtime gaps: provider evidence, release/publish gates, scheduler operation coverage, context/KG consistency, and productized UI verification.
