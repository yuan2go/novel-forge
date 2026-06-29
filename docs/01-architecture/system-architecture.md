# System Architecture

## Positioning

Novel Forge v6 is a local-first AI novel production platform and early Novel Operating System runtime. It should not be treated as a one-off AI chapter generator.

The internal architecture target is Novel Operating System, but the repository, package, CLI, and public product name remain Novel Forge / `novel-forge` in v6 until a separate migration task approves any rename.

## Core Architecture

v6 keeps a Python executable core and adds optional industrial services around it.

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
- Workflow runtime first slice: DAG validation, dependency resolution, ready-node queue, processor registry, pre/post gates, runtime control, scheduler tick/loop, resume, invalidation, quarantine/rollback markers, and trace spans.
- Agent Scheduler first slice: Agent contracts/runs, dispatch queue, leases, operation registry, checkpoints, budget/SLA/gate records, retries, dead letters, and Workflow handoff.
- Novel Knowledge Graph first slice: typed ontology collections, snapshots, query/path/impact/conflict APIs, KG gate, continuity preflight integration, and workbench UI.
- Runtime ledger first slice: trace spans, gate results, model call logs, cost ledger, budget policies, cost alerts, project/agent/chapter snapshots, and cost-quality dashboard assets.
- Review rework backend first slice: `review_issue -> revision_task -> editor_patch -> draft_version -> re-review -> publish_gate` service path and workflow processor registration.

## Target Platform Layers

| Layer | Responsibility | Current Status |
|---|---|---|
| Project / Workspace | project lifecycle, series, workspace state, project asset references | partially implemented |
| Asset / Artifact | schema-backed assets, versions, lineage, object copies, index rows | partially implemented |
| Workflow | definitions, DAG parsing, node runs, ready queue, gates, retries, pause/resume/cancel, invalidation, scheduler loop | first production slice implemented; distributed scale and broader processor coverage remain |
| Knowledge / Analysis | deconstruction, craft analysis, classic analysis, conversion to knowledge/material/template/rules | first schema/service/UI/handoff slice implemented; semantic scoring and richer conversion gates remain |
| Context | context build plan, context bundle, token budget, compression preview, actual-context replay | schema/service/API/UI slice implemented; manual curation and invalidation remain |
| Production | topic/world/character/outline/chapter-plan/draft/review/revision chain | base chain plus outline/chapter-plan/draft versions and generation runs implemented |
| Evaluation | quality, style, originality, continuity, KG, platform fit, publish gate, model evaluation | first production gate stack exists; semantic scoring and universal enforcement remain |
| Long-form Stability | continuity bible, canon graph, Novel KG, timeline, foreshadowing, relationship graph, change impact | first production slice implemented; semantic extraction and visualization depth remain |
| Agent | contracts, runs, dispatch queue, checkpoints, budgets, gates, metrics, scheduler loop, recovery | first production slice implemented; complete Agent Center and deeper rollback remain |
| Trace / Cost | trace spans, gate results, model calls, cost ledger, budget policies, cost snapshots, dashboard assets | first production slice implemented; universal model-call coverage and UI depth remain |
| Analytics / Publishing | funnel, blockers, reader feedback, publishing plan/log, release operations | early publish/feedback exists; OS-level operating dashboards remain P0/P1 |

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

## Novel OS Acceptance Chain

The P0 operating-system acceptance chain is a minimal vertical slice, not a requirement to generate a full novel. The acceptance fixture should prove that one project and one chapter-sized production target can move through the operating layer without bypassing durable artifacts:

```text
WorkflowDefinition
  -> execute_workflow
  -> workflow / agent scheduler tick or loop
  -> context bundle
  -> model call through the configured runtime boundary
  -> node_run / agent_run
  -> trace_span / gate_result / model_call_log / cost_ledger
  -> Novel KG gate / continuity preflight
  -> review_issue -> revision_task -> editor_patch -> draft_version
  -> re-review -> publish_gate
  -> downstream invalidation
  -> resume_workflow
  -> cost_quality_dashboard / acceptance report
```

Full-novel generation is a later long-chain acceptance scenario. It tests scale, quality drift, and editorial stamina; it should not be used as the first OS runtime correctness test because it mixes runtime integrity with creative quality and cost variability.

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

`LocalRuleEngine` is executable locally, and Agent model calls default to the Claude Code local Codex worker using the isolated `CODEX_HOME=~/.codex-claude` boundary. `MockModelAdapter` is still available through explicit `NOVEL_FORGE_MODEL_PROVIDER=mock` for tests and deterministic demos. ChatGPT and DeepSeek are opt-in OpenAI-compatible JSON chat providers with strict output validation. The generic Codex worker remains explicit through `NOVEL_FORGE_CODEX_CLI_ENABLED=1`.

Do not call external providers in tests. Do not write malformed or unvalidated provider output into assets.

## Architecture Priority

1. Universal Runtime Policy across model-producing paths: budget policy, provider timeout/cancel, model usage capture, trace spans, model call logs, cost ledger writes, context bundle evidence, and gate results.
2. Provider-level runtime guard and deep checkpoint resume: normalized usage, realtime or postflight token cutoff, exact cost capture, cancellable local/provider calls, OpenAI-compatible SSE/SDK streaming, and resume from internal operation stages.
3. Business rollback: operation transactions, rollback preview/apply, version restoration, physical multi-asset quarantine/restore, rollback-required handling, dirty-index evidence, verification, and compensating ledger records.
4. Semantic quality layer: KG-backed context building, stronger entity/relation extraction, evidence spans, alias merge, continuity conflicts, originality/review gates, and feedback-to-plan learning.
5. Retrieval and Web OS operations: PostgreSQL/pgvector is the internal knowledge/memory retrieval base for Context Builder auto mode, Qdrant is an optional high-performance vector service, fixture-backed browser-smoked OS console routes expose DAG/Agent/KG/Trace/Cost operational views, and multi-chapter continuity/cost/quality/recovery acceptance remains the scale gate.

Detailed closure plan: [Novel OS Remaining Closure Plan](../08-roadmap/novel-os-remaining-closure-plan.md).

This sequence improves actual chapter quality and traceability before expanding automation breadth.
