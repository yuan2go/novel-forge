# WORKFLOW.md

## Purpose

This document defines how Novel Forge should operate as a local-first AI novel production platform.

The workflow model replaces ad-hoc prompt execution with traceable production nodes, artifact versions, context bundles, quality gates, and recovery paths.

## Current Executable Pipeline

The current CLI sample pipeline is:

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
  -> init-workspace
  -> update-workspace-draft
  -> review
  -> review-derived reports
  -> update-workspace-review
  -> revise
  -> import-feedback
  -> analyze-feedback
```

A successful run writes a `WorkflowRun` asset under `data/runs/`. Each step writes `TaskStatus` records. Failed runs should write failed status, error message, run log, and recovery instruction.

## Target Platform Workflow

The target platform workflow is:

```text
Project Setup
  -> Platform / Genre Strategy
  -> Analysis Center
  -> Knowledge / Material / Template / Rule Conversion
  -> Context Build Plan
  -> Context Bundle
  -> Topic Development
  -> Worldbuilding
  -> Character System
  -> Long Outline Version
  -> Chapter Plan Version
  -> Generation Run
  -> Draft Version
  -> Review Pipeline
  -> Editor Patch / Revision Task
  -> Continuity / Platform / Originality Gates
  -> Release Package
  -> Publishing Plan / Publishing Log
  -> Reader Feedback Analytics
  -> Next Chapter / Outline Adjustment
```

## Node Standard

Every new workflow step should be expressible as a node.

```text
Node = executable production action
Module = capability or asset area
Artifact = traceable output
Run = auditable execution record
Quality Gate = acceptance or rejection rule
```

Minimum node contract:

| Field | Requirement |
|---|---|
| `node_id` | stable identifier |
| `node_type` | analysis, context, generation, review, revision, publishing, feedback, evaluation, agent |
| `inputs` | artifact paths, project/workspace id, parameters |
| `context_bundle` | exact context when model/retrieval is used |
| `processor` | local service, model adapter, handoff, worker task, or future Agent |
| `outputs` | schema-backed artifact or artifact version |
| `quality_gate` | pass/fail/needs_revision criteria |
| `run_record` | status, timing, provider, prompt/Skill version, errors |
| `recovery` | retry, rollback, invalidation, or manual handoff instruction |

## Artifact Rules

All durable outputs must be schema-backed assets.

Do not use chat history, UI state, or untracked temporary files as the source of truth for:

- project strategy;
- analysis reports;
- context bundles;
- topic/world/character assets;
- outline and chapter-plan versions;
- draft versions;
- review reports;
- revision tasks;
- editor patches;
- publish gate reports;
- release packages;
- feedback insights;
- model benchmark results;
- Agent run/checkpoint records.

## Context Workflow

The Context Builder now has the first schema/service/API/UI slice because it directly affects chapter quality.

Target flow:

```text
production target
  -> candidate asset pool
  -> source selection
  -> ranking and exclusion
  -> compression preview
  -> token budget
  -> context bundle
  -> generation/review run
  -> actual-context replay
```

Implemented first-slice artifacts:

- `context_build_plan`
- `context_bundle`

Remaining work: manual curation, richer compression controls, stale-context warnings, and deeper replay UI.

Context must exclude raw copyrighted source text from draft generation. Reference-derived material may enter context only after abstraction and lineage tracking.

## Versioned Production Chain

The production chain is now version-aware at the core artifact layer.

```text
outline_version
  -> chapter_plan_version
  -> generation_run
  -> draft_version
  -> review_report
  -> revision_task
  -> editor_patch / revised_draft_version
```

When upstream assets change, downstream assets must be marked or reported as potentially stale.

Examples:

- World rule changes can invalidate character abilities, outline beats, chapter plans, and draft scenes.
- Outline changes can invalidate chapter plans, draft versions, foreshadowing placement, and publish queue.
- Character motivation changes can invalidate chapter plans, dialogue, review reports, and revision tasks.

Implemented first-slice artifacts:

- `outline_version`
- `chapter_plan_version`
- `draft_version`
- `generation_run`

Remaining future artifact:

- `change_impact_report`

## Review Pipeline

Review is not one function. It is a pipeline of gates.

Target gates:

```text
basic schema validation
  -> language quality
  -> chapter structure
  -> conflict and hook density
  -> character motivation
  -> world/continuity consistency
  -> style fit
  -> originality and evidence package
  -> platform fit
  -> publishing gate
```

Current reports exist in first-generation form. Future work should add or deepen:

- `style_audit_report`
- `continuity_audit_report`
- `platform_fit_report`
- model-level semantic originality review
- evidence package
- regression comparison against previous drafts

## Revision Workflow

A review should not directly overwrite a draft.

Correct flow:

```text
review_report
  -> revision_task
  -> editor_patch or revision_plan
  -> preview / diff
  -> confirm apply
  -> new draft version
  -> post-revision review
```

Every manual or AI-assisted edit must be reversible through version history or patch record.

## Analysis Center Workflow

The Analysis Center should use a common analysis core with profiles, not isolated one-off modules.

Profiles:

- web fiction business analysis;
- published fiction craft analysis;
- classic literary depth analysis;
- general novel analysis.

Target conversion:

```text
analysis report
  -> analysis-to-asset conversion
  -> knowledge card
  -> material card
  -> writing/craft template
  -> style profile
  -> review rule pack
```

Reference-work analysis must remain abstract and must not become draft prose.

## Agent Workflow

Agents run only after node/artifact/run/context/gate foundations exist. The first persisted runtime slice now exists for contracts, runs, events, checkpoints, budgets, gates, metrics, and failure reports.

Target Agent flow:

```text
agent_contract
  -> agent_run
  -> checkpoint
  -> budget check
  -> agent_gate
  -> artifact output
  -> metric record
  -> accepted / needs_revision / failed / recovered
```

Agent autonomy without artifact contracts is not acceptable.

Current implementation notes:

- Claude Code/Codex handoffs create `waiting_human` Agent runs.
- Handoff output binding marks the related Agent run `succeeded`.
- Handoff failure creates an `agent_failure_report`.
- Handoff retry cancels the superseded Agent run and creates a new handoff/run pair.
- Production Control shows Agent runs alongside task status, node runs, dead letters, failed items, and human gates.

## Publishing and Feedback Workflow

Target publishing loop:

```text
final draft version
  -> publish gate report
  -> release package
  -> publishing plan
  -> publishing log
  -> platform status
  -> post-release metrics
  -> feedback insight
  -> chapter-plan / review-rule adjustment
```

Feedback should identify:

- sentiment distribution;
- payoff and toxic-point clusters;
- role heat;
- retention/drop-off signals;
- chapter-level actionable adjustments.

Feedback must not directly mutate future plans without a traceable revision task or planning artifact.

## Priority Order

1. Workflow skeleton and artifact/version contracts.
2. Context Builder.
3. Versioned production chain.
4. Analysis Center upgrade.
5. Long-form stability workbench.
6. AI Editor patch workflow.
7. Agent industrialization.
8. Reader feedback, publishing operations, and model evaluation centers.

## Acceptance

A workflow change is accepted only when:

- it has a documented node/artifact/run contract;
- it preserves storage and copyright boundaries;
- it writes schema-backed assets;
- it has tests or a documented verification path;
- it does not break `make validate` expectations;
- it updates docs when behavior or scope changes.
