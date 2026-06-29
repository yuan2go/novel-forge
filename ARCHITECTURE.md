# ARCHITECTURE.md

## Decision Summary

Do not rename the repository to Novel Operating System in v6.

Use this naming model:

| Scope | Name |
|---|---|
| Repository/package/CLI | `novel-forge` |
| Product | Novel Forge |
| Product category | local-first AI novel production platform |
| Architecture target | Novel Operating System |

The system should now be designed as a platform, but migrated incrementally. Do not pause feature work until every platform concept exists; also do not keep adding isolated feature pages without platform contracts.

## Architecture Principle

Novel Forge is workflow-first, artifact-backed, context-replayable, quality-gated, and locally auditable.

The architecture should convert every major capability into a standard production node:

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

## Current Runtime Architecture

v6 currently uses a Python core plus optional industrial services and an early Novel OS runtime layer.

```text
CLI / FastAPI / Celery / Next.js
  -> workflow layer
  -> agent scheduler
  -> runtime ledger
  -> Novel KG
  -> module services
  -> schema-backed JSON assets
  -> local storage
  -> optional PostgreSQL index
  -> optional Qdrant retrieval
  -> optional MinIO object copies
  -> optional Neo4j graph projection
```

The local JSON asset remains the auditable interchange format. PostgreSQL, Qdrant, MinIO, Redis/Celery, and Neo4j are supporting infrastructure, not replacements for schema-backed artifacts.

## Platform Layers

### 1. Project and Workspace Layer

Responsibilities:

- project creation, duplication, archive, pause, restore, and soft deletion;
- workspace state;
- series and multi-book memory;
- project-scoped asset references;
- project configuration for platform, genre, quality, style, and continuity profiles.

Current status: partially implemented through project/workspace assets and product API routes.

### 2. Asset and Artifact Layer

Responsibilities:

- raw, cleaned, decomposition, analysis, knowledge, material, topic, world, character, continuity, style, quality, template, outline, chapter plan, draft, review, publishing, feedback, training, image prompt, workspace, and run assets;
- append-only versions for generated and edited content;
- lineage and source references;
- object copies where MinIO is configured;
- PostgreSQL index where configured.

Rule: every production output should become a schema-backed artifact or artifact version. Do not pass critical project state only through chat, temporary memory, or UI state.

### 3. Workflow Layer

Responsibilities:

- define production flows;
- run node chains;
- record `WorkflowRun` and `TaskStatus`;
- support recovery, retry, dead letters, and run logs;
- support `WorkflowDefinition`, `WorkflowNode`, and `NodeRun`;
- support ready-node queue, processor registry, gate pipeline, scheduler tick/loop, resume, invalidation, trace spans, and quarantine/rollback markers.

Current implemented pipeline:

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

Target production pipeline:

```text
project strategy
  -> platform/genre strategy
  -> analysis center
  -> knowledge/material/template conversion
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

### 4. Knowledge and Analysis Layer

Responsibilities:

- web fiction business analysis;
- published fiction craft analysis;
- classic literary depth analysis;
- common novel analysis core;
- conversion of analysis results into materials, knowledge cards, templates, style profiles, and review rules;
- abstract mechanisms only, never protected expression.

Current status: first Analysis Center slice is implemented with common, web-fiction, published-fiction, classic-literary report schemas, services, UI, handoff packets, and conversion to abstract assets. Remaining work is provider-backed semantic scoring, richer visualization, and conversion review gates.

### 5. Context Layer

Responsibilities:

- context build plan;
- source asset selection;
- ranking and exclusion;
- compression preview;
- token budget;
- final context bundle;
- replay of the actual context sent to a model.

Current status: retrieval foundations exist through local search/vector search/Qdrant, and `context_build_plan` / `context_bundle` now have schema, service, API, UI, token budget, ranking metadata, compression preview, and actual-context replay. Remaining work is manual source curation and invalidation warning UI.

### 6. Production Layer

Responsibilities:

- topic, world, characters, outline, chapter plan, draft, review, revision;
- versioned outline and chapter-plan chain;
- generation run metadata;
- parameter trace;
- chapter queue;
- invalidation when upstream outline/world/character/continuity changes.

Current status: base generation chain exists, and outline, chapter plan, draft, and generation-run artifacts now produce versioned records. Remaining work is chapter queue, richer parameter trace dashboard, and stronger UI around upstream-change invalidation.

### 7. Evaluation Layer

Responsibilities:

- quality score report;
- style audit;
- originality evidence package;
- chapter audit;
- continuity audit;
- platform fit audit;
- publish gate;
- release package;
- model benchmarks and prompt regression.

Current status: review, originality, style, chapter audit, continuity/KG gates, publish gate, release package, model profile, benchmark, routing, and cost-quality assets exist in first-generation form. Semantic scoring and universal runtime enforcement need deeper implementation.

### 8. Long-Form Stability Layer

Responsibilities:

- continuity bible;
- timeline;
- foreshadowing placement and payoff;
- power scale rules;
- character relationship graph;
- factions, organizations, map, and prop systems;
- change impact report;
- invalidation visualization.

Current status: continuity graph, canon graph, Novel KG ontology, KG snapshots, query/path/impact/conflict APIs, KG gate, continuity preflight, and `change_impact_report` exist in first-slice form. Remaining P0/P1 work is semantic extraction depth, evidence spans, richer continuity workbenches, and invalidation visualization.

### 9. Agent Layer

Responsibilities:

- agent contracts;
- agent runs;
- checkpoints;
- budgets;
- gates;
- metrics;
- state machine;
- resumable and rollback-capable execution;
- Agent Center UI.

Current status: permission profiles, tool allowlists, handoff, persisted agent contracts/runs/events/checkpoints/budgets/gates/metrics/failure reports, Agent Operation Registry, dispatch queue, scheduler tick/loop, retries, dead letters, API routes, and Production Control visibility exist. Remaining P0/P1 work is broader operation coverage, business rollback actions, universal model budget enforcement, and deeper Agent Center timelines.

### 10. Runtime Ledger Layer

Responsibilities:

- trace spans across workflow, node, agent, gate, model, cost, context, and feedback operations;
- gate results;
- model call logs;
- cost ledgers;
- budget policies and alerts;
- project, agent, and chapter cost snapshots;
- cost-quality dashboards.

Current status: first production slice exists. Remaining P0/P1 work is universal model-call coverage, provider usage capture across all adapters, budget hard-stop behavior on every production path, and richer dashboard UI.

### 11. Analytics and Publishing Layer

Responsibilities:

- production funnel;
- blocking points;
- next-action suggestions;
- reader sentiment, payoff/toxic-point clusters, role heat, retention/drop-off;
- publishing calendar;
- chapter queue;
- platform status;
- title/summary/hook checks;
- publishing plan/log;
- post-release feedback recovery.

Current status: first-generation feedback and publish gate exist; full productized centers are still P0/P1.

## Data Boundary

Keep asset stages separate. Do not merge raw, cleaned, decomposition, analysis, knowledge, material, draft, review, publishing, feedback, workspace, and run assets.

Reference material can flow downstream only as abstracted mechanisms or source-linked reusable assets. Raw source text must never be injected into generated draft context.

## Dependency Boundary

Default local validation must remain fast and low-dependency.

- Tests use deterministic mock/local rule behavior.
- External providers are opt-in.
- Provider output must be strict JSON when writing schema-backed assets.
- Industrial services are optional adapters and must fail closed when unavailable.

## Novel OS Acceptance Chain

The OS end-to-end acceptance chain is not a full-novel generation test. The P0 correctness target is a minimal vertical slice using one project and one chapter-sized fixture:

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

Full-novel generation should be a later long-chain acceptance scenario for scale, continuity, quality drift, and cost control.

## Implementation Priority

Preferred order:

1. OS acceptance harness covering workflow execute/resume, Agent dispatch, KG/preflight gate, trace/cost ledger, review rework, publish gate, invalidation, and cost-quality output.
2. Universal runtime policy enforcement for all model-producing paths.
3. OS console completion for workflow, Agent, KG, trace, cost, invalidation, and review rework operations.
4. Semantic quality layer: KG-backed context, extraction, evidence spans, conflict analysis, originality/review gates, and feedback-to-plan learning.
5. Documentation/version alignment across product, architecture, testing, operations, API, and UI surfaces.

This order improves production quality first, then expands source methodology and automation.
