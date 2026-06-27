# System Architecture

## Positioning

Novel Forge V5 is a local-first AI novel production platform. It should not be treated as a one-off AI chapter generator.

The internal long-term architecture vision may be called a Novel Operating System, but the repository, package, CLI, and public product name remain Novel Forge / `novel-forge` in V5.

## Core Architecture

V5 keeps a Python executable core and adds optional industrial services around it.

```text
CLI / FastAPI / Celery / Next.js
  -> workflows
  -> module services
  -> schemas
  -> local JSON assets
  -> optional PostgreSQL index
  -> optional Qdrant retrieval
  -> optional MinIO object copies
  -> optional Neo4j graph projection
```

The local JSON asset remains the auditable interchange format. PostgreSQL, Qdrant, MinIO, Redis/Celery, and Neo4j are supporting infrastructure, not replacements for schema-backed artifacts.

## Architecture Principle

All durable capabilities should be converted into standard production nodes:

```text
input artifacts
  -> context build plan
  -> context bundle
  -> node processor
  -> output artifact version
  -> quality gate
  -> revision / retry / downstream invalidation
  -> run log
```

A module is a capability or asset area. A node is an executable production step. An artifact is the traceable result of a node. A run is an auditable execution record.

## Current Implementation

Implemented or partially implemented:

- Python 3.11+ standard-library core.
- CLI-first workflow with schema-backed JSON assets.
- Local runtime workspace under `.local/workspace/`.
- Product web console backed by FastAPI.
- Project/workspace management.
- Ingestion, cleaning, decomposition, knowledge extraction, material building, topic, world, characters, outline, chapter plan, draft, review, revision, feedback analysis.
- Claude Code / Codex handoff packets for deconstruction and knowledge parsing.
- Local search, local vector search, Qdrant retrieval, MinIO sync, PostgreSQL sync, Celery task execution, and gated Neo4j status.
- Draft workbench, review/revision flow, publish gate, release package, originality report, style/chapter review reports in varying depth.
- Skills system under root `skills/` with generated `.claude/skills/` runtime copies.

## Target Platform Layers

| Layer | Responsibility | Current Status |
|---|---|---|
| Project / Workspace | project lifecycle, series, workspace state, project asset references | partially implemented |
| Asset / Artifact | schema-backed assets, versions, lineage, object copies, index rows | partially implemented |
| Workflow | runs, task status, retries, recovery, future node definitions and invalidation | partially implemented |
| Knowledge / Analysis | deconstruction, craft analysis, classic analysis, conversion to knowledge/material/template/rules | partial; Analysis Center still P0 |
| Context | context build plan, context bundle, token budget, compression preview, actual-context replay | retrieval base exists; visual builder still P0 |
| Production | topic/world/character/outline/chapter-plan/draft/review/revision chain | base chain exists; versioned chain still P0 |
| Evaluation | quality, style, originality, continuity, platform fit, publish gate, model evaluation | first-generation reviews exist; deeper gates still P0/P1 |
| Long-form Stability | continuity bible, timeline, foreshadowing, relationship graph, change impact | shallow schemas exist; workbench still P0 |
| Agent | contracts, runs, checkpoints, budgets, gates, metrics, state machine | handoff exists; industrial runtime still P0 |
| Analytics / Publishing | funnel, blockers, reader feedback, publishing plan/log, release operations | early publish/feedback exists; productized centers still P0/P1 |

## Runtime Flow

```text
Next.js web console
  -> FastAPI product routes
  -> workflow/module services
  -> local JSON asset write
  -> PostgreSQL write-through index when configured
  -> Celery task execution when async
  -> Qdrant retrieval when configured
  -> MinIO object copies when configured
```

## Main Executable Pipeline

```text
ingest
  -> clean
  -> decompose
  -> extract-knowledge
  -> build-materials
  -> generate-topic
  -> generate-world
  -> generate-characters
  -> generate-outline
  -> generate-chapter-plan
  -> draft
  -> init/update workspace
  -> review
  -> review-derived reports
  -> revise
  -> import-feedback
  -> analyze-feedback
```

## Target Production Pipeline

```text
project strategy
  -> platform/genre strategy
  -> analysis center
  -> analysis-to-asset conversion
  -> context build plan
  -> context bundle
  -> topic/world/character planning
  -> outline version
  -> chapter-plan version
  -> generation run
  -> draft version
  -> review pipeline
  -> editor patch / revision task
  -> continuity and platform gates
  -> release package
  -> publishing plan/log
  -> reader feedback analytics
  -> next chapter plan update
```

## Extension Points

- Model adapters for MockModel, LocalRuleEngine, ChatGPT-compatible providers, DeepSeek-compatible providers, and future providers.
- PostgreSQL for primary API index of assets, projects, task statuses, and version records.
- FastAPI for product and workflow endpoints.
- Redis/Celery for async runs, batch ingestion, indexing, retries, and dead letters.
- Qdrant for vector retrieval.
- MinIO for raw/object/artifact/export copies.
- Neo4j as a gated projection for relationship-heavy queries.
- Next.js for local product console.

## Model Adapter Boundary

`MockModelAdapter` and `LocalRuleEngine` are executable locally. ChatGPT and DeepSeek are opt-in OpenAI-compatible JSON chat providers with strict output validation. Claude Code and Codex remain manual/operator adapters unless a future ADR approves in-process provider integration.

Do not call external providers in tests. Do not write malformed or unvalidated provider output into assets.

## Architecture Priority

1. Platform skeleton: workflow/node run, artifact version, context bundle, generation run, quality gate, revision task.
2. Context Builder.
3. Versioned production chain.
4. Analysis Center upgrade.
5. Long-form stability workbench.
6. AI Editor patch system.
7. Agent industrialization.
8. Reader feedback, publishing operations, and model evaluation centers.

This sequence improves actual chapter quality and traceability before expanding automation breadth.
