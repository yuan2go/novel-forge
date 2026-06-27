# ARCHITECTURE.md

## Decision Summary

Do not rename the repository to Novel Operating System in V5.

Use this naming model:

| Scope | Name |
|---|---|
| Repository/package/CLI | `novel-forge` |
| Product | Novel Forge |
| Product category | local-first AI novel production platform |
| Internal long-term vision | Novel Operating System |

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

V5 currently uses a Python core plus optional industrial services.

```text
CLI / FastAPI / Celery / Next.js
  -> workflow layer
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
- later support `WorkflowDefinition`, `WorkflowNode`, `NodeRun`, invalidation, and chapter queues.

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

Current status: web-fiction decomposition and handoff exist; full Analysis Center schema/service/UI/handoff coverage is still P0.

### 5. Context Layer

Responsibilities:

- context build plan;
- source asset selection;
- ranking and exclusion;
- compression preview;
- token budget;
- final context bundle;
- replay of the actual context sent to a model.

Current status: retrieval foundations exist through local search/vector search/Qdrant; visual Context Builder is still P0.

### 6. Production Layer

Responsibilities:

- topic, world, characters, outline, chapter plan, draft, review, revision;
- versioned outline and chapter-plan chain;
- generation run metadata;
- parameter trace;
- chapter queue;
- invalidation when upstream outline/world/character/continuity changes.

Current status: base generation chain exists; full versioned production chain is still P0.

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

Current status: review, originality, style, chapter audit, publish gate, release package exist in first-generation form. Continuity/platform/model evaluation need deeper implementation.

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

Current status: continuity/foreshadowing/power-rule schemas exist in shallow form; workbench and impact analysis are still P0.

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

Current status: permission profile, tool allowlist, handoff, and acceptance concepts exist. Industrial Agent runtime is still P0/P1.

### 10. Analytics and Publishing Layer

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

## Implementation Priority

Preferred order:

1. Platform skeleton: workflow run/node run/artifact version/context bundle/generation run/quality gate/revision task.
2. Context Builder.
3. Versioned outline/chapter-plan/draft production chain.
4. Analysis Center upgrade.
5. Long-form stability workbench.
6. AI Editor patch system.
7. Agent industrialization.
8. Reader feedback, publishing operations, and model evaluation centers.

This order improves production quality first, then expands source methodology and automation.
