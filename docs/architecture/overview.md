# Architecture Overview

Updated: 2026-07-05
Baseline checked: branch `backup/v6-post-mkaos-industrialization-20260705`, commit `e4f700c`

Novel Forge v6 is organized as a local-first Python runtime with optional industrial services and a Next.js operations console. The architecture target is Novel Operating System: every durable creative action should move through schema-backed artifacts, context/runtime boundaries, gates, traces, and recoverable workflow or Agent execution.

## Runtime Layers

```text
Operator / Claude Code / Web Console / CLI
  -> CLI commands or FastAPI routers
  -> product API services / workflow services
  -> domain modules under src/novel_forge/modules
  -> schemas and local/industrial storage boundaries
  -> model/provider/runtime policy adapters
  -> gate, trace, cost, audit, and release artifacts
```

| Layer | Current Implementation | Evidence | Status |
|---|---|---|---|
| CLI | Large command surface for ingest, clean, decompose, generate, review, revise, feedback, industrial ops, API/worker, validate | `src/novel_forge/cli.py` | Implemented |
| API | FastAPI app with product routers for project, assets, agents, MKAOS, OS runtime, review, publishing, etc. | `src/novel_forge/api/app.py`, `src/novel_forge/api/routers/` | Implemented, product depth varies |
| Web console | Next.js App Router console with operational pages | `web/admin/app/` | Implemented shell, partial workflow depth |
| Application services | Product API facade and use-case seams | `src/novel_forge/api/services/` | Partially implemented |
| Domain modules | Creative, runtime, MKAOS, publishing, Agent, evaluation, storage-adjacent services | `src/novel_forge/modules/` | Broad coverage, some large services remain |
| Schemas | Central schema asset contracts for creative, runtime, Agent, gates, ledger, MKAOS | `src/novel_forge/schemas/assets.py` | Implemented, still evolving |
| Workflows | CLI workflow orchestration, task status, node execution | `src/novel_forge/workflows/`, `modules/workflow_nodes/` | Partially implemented |
| Storage | Local JSON runtime, lock/manifest, optional Postgres/object/vector services | `src/novel_forge/storage/`, `docker-compose.yml` | Implemented local, partial industrial |
| Runtime policy | Provider guard, model route, ledger, runtime policy, budget/gate evidence | `modules/runtime_policy/`, `modules/runtime_ledger/`, `model_adapters/`, `modules/model_router/` | Partially implemented, being hardened |
| Agent runtime | Registry, scheduler, queue, runner seams, checkpoint/recovery/rollback/dead-letter | `modules/agent_registry/`, `modules/agent_scheduler/`, `modules/agent_runs/` | First production slices |
| Quality/publishing | ReviewIssue, evaluation center, MKAOS gates, publish gate, release package | `modules/review_issue/`, `modules/evaluation_center/`, `modules/publishing/` | Partially implemented |

## Core Creative Data Flow

```text
source material
  -> cleaned text
  -> decomposition / analysis
  -> knowledge cards / material cards / templates / review rules
  -> topic seed / platform strategy
  -> world bible
  -> character cards
  -> long outline
  -> chapter plan
  -> context build plan / context bundle
  -> draft chapter
  -> review report / ReviewIssue
  -> revision task / editor patch / draft version
  -> quality and publishing gates
  -> reader feedback / backflow plan
```

Evidence: schemas in `src/novel_forge/schemas/assets.py`, CLI commands in `src/novel_forge/cli.py`, module services under `src/novel_forge/modules/`, and integration tests under `tests/integration/test_pipeline.py` and Novel OS acceptance tests.

## Novel OS Runtime Flow

```text
WorkflowDefinition / Agent operation
  -> dispatch queue / node readiness
  -> lease / scheduler tick
  -> OS Envelope / runtime policy
  -> context bundle / model route
  -> model call or local rule engine
  -> output artifact
  -> gate result / trace span / model call log / cost ledger
  -> checkpoint
  -> retry, recovery, rollback, dead-letter, or release gate
```

Evidence:

- `src/novel_forge/modules/workflow_nodes/`
- `src/novel_forge/modules/agent_scheduler/`
- `src/novel_forge/modules/os_envelope/`
- `src/novel_forge/modules/runtime_policy/`
- `src/novel_forge/modules/runtime_ledger/`
- `tests/unit/test_agent_scheduler.py`
- `tests/integration/test_novel_os_acceptance.py`

## Agent And Skill Relationship

Agent is a role/runtime boundary. Skill is a reusable method or capability.

- Agent operation registration lives in code, mainly `modules/agent_registry/` and `modules/agent_scheduler/`.
- Project Skill source lives in root `skills/`.
- Runtime Skill copies live under `.claude/skills/` and are generated via `make sync-skills`.
- Agent-to-Skill selection policy is documented in `docs/09-skills/agent-skill-map.md`.

Skills must not bypass schema validation, context isolation, provider policy, copyright boundaries, ReviewIssue, Canon/KG, or publishing gates.

## External Dependencies

The default core is dependency-light and can run tests without industrial services. Optional services are configured in `docker-compose.yml` and optional extras in `pyproject.toml`.

| Service | Purpose | Status |
|---|---|---|
| FastAPI | Product API | Optional runtime dependency |
| PostgreSQL | Project/assets/task indexes and production persistence slices | Optional, partially integrated |
| Redis/Celery | Worker and async task execution | Optional |
| Qdrant | Vector retrieval | Optional |
| MinIO | Object artifact copies | Optional |
| ClickHouse | Analytics slice | Optional Compose profile |
| Neo4j | Graph-heavy relationship queries | Optional Compose profile |
| Next.js | Admin console | Implemented frontend |

## Current Bottlenecks

1. Multiple historical docs describe older v5 or design-only states; use current docs first.
2. Some services still carry broad use-case responsibilities and are being split by seam.
3. Agent operation coverage is not complete for every product Agent role.
4. Provider/runtime policy enforcement must continue expanding until all model-producing paths emit evidence.
5. Publishing/release gates are stronger but still require more end-to-end ready fixtures and platform adapter depth.
6. UI route count is high; route existence does not always mean complete operator workflow depth.
7. Local JSON and optional industrial backends need clear environment-policy documentation for production paths.
