# CLAUDE.md

This file defines project-level operating rules for Claude Code, Codex, and other coding agents working in Novel Forge v6.

Novel Forge v6 is a local-first AI novel production platform and early Novel Operating System runtime. The repository, package, CLI, and public product name remain `novel-forge` / Novel Forge unless a separate migration task explicitly approves a rename.

## Product Identity

Novel Forge is a local-first AI novel production platform for industrialized long-form fiction work.

It coordinates:

- project and workspace management;
- source ingestion, rights metadata, cleaning, and abstract analysis;
- knowledge, material, template, style, and quality-standard assets;
- context construction and retrieval;
- topic, world, character, outline, chapter-plan, draft, review, revision, feedback, publishing, and export workflows;
- workflow runs, task status, handoff packets, validation, release packages, and audit trails.

Do not describe the system as a one-off AI writing prompt tool. Its durable value is workflow control, asset accumulation, quality gates, versioned production, and recoverable Agent execution.

## Naming Rule

Use these names consistently:

| Context | Correct Name |
|---|---|
| Repository/package/CLI | `novel-forge` |
| Product name | Novel Forge |
| Product category | local-first AI novel production platform |
| Internal architecture vision | Novel Operating System |
| Avoid as current public rename | `Novel Operating System` as repository/package name |

A rename to Novel Operating System is not approved in v6. Novel Operating System is the architecture target, not the repository/package/CLI name.

## Platform Architecture Direction

All new work should move the project toward a workflow-first platform architecture:

```text
Project / Workspace
  -> Workflow Definition
  -> Workflow Node
  -> Context Bundle
  -> Generation / Analysis / Review Run
  -> Agent Dispatch / Processor Contract
  -> Artifact Version
  -> Quality / KG / Publish Gate
  -> Trace Span / Model Call Log / Cost Ledger
  -> Revision Task
  -> Invalidation / Resume
  -> Publish / Feedback / Analytics Loop
```

Target platform layers:

| Layer | Responsibility |
|---|---|
| Workflow | define node chains, runs, queues, retries, recovery, and invalidation |
| Knowledge | manage source-derived abstract knowledge, material cards, templates, styles, standards, and graphs |
| Context | select, rank, compress, budget, and replay the actual model context |
| Production | generate and version topics, worlds, characters, outlines, chapter plans, drafts, reviews, and revisions |
| Evaluation | run originality, style, chapter, continuity, platform-fit, and publishing gates |
| Agent | execute bounded node work through contracts, checkpoints, budgets, gates, and metrics |
| Analytics | show production funnel, blocking points, quality trends, feedback, and next-action recommendations |
| Publishing | manage release package, publishing plan, platform status, chapter queue, and post-release data |

## Current Implementation Truth

Do not overclaim. v6 currently has an early OS runtime, but not the complete Novel Operating System product.

Implemented or partially implemented:

- Python 3.11+ standard-library core.
- CLI-first workflow with schema-backed JSON assets.
- Local runtime workspace under `.local/workspace/`.
- Source ingestion, cleaning, decomposition, knowledge extraction, materials, topic, world, characters, outline, chapter plan, draft, review, revision, and feedback analysis.
- Handoff packets for Claude Code / Codex-assisted deconstruction and knowledge parsing.
- RAG/retrieval foundations: local search, local vector search, Qdrant integration.
- Optional industrial stack: FastAPI, PostgreSQL, Redis/Celery, Qdrant, MinIO, Next.js admin console, gated Neo4j.
- Draft/review/revision workbench, release package, publish gate report, originality report, chapter audit, style and quality profiles in varying depth.
- Skills system under root `skills/` with `.claude/skills/` as generated runtime output only.
- Workflow runtime first slice: DAG validation, ready-node queue, state machine, processor registry, gate pipeline, scheduler tick/loop, resume, invalidation, trace, quarantine, and rollback markers.
- Agent Scheduler first slice: contracts, runs, dispatch queue, leases, operation registry, checkpoints, budget/SLA/gate records, retry, dead letter, and recovery.
- Novel KG first slice: typed ontology collections, snapshots, query/path/impact/conflict APIs, KG gate, continuity preflight, and workbench.
- Runtime ledger first slice: trace spans, gate results, model call logs, cost ledgers, budget policies, alerts, snapshots, and cost-quality dashboard assets.
- Review rework backend first slice: review issue, revision task, editor patch, draft version, re-review, and publish gate.

Known P0 gaps to respect in planning:

1. OS acceptance harness is still needed: one project/chapter-sized fixture must prove workflow execute/resume, Agent dispatch, KG/preflight gate, trace/cost ledger, review rework, publish gate, invalidation, and cost-quality output.
2. Universal runtime policy enforcement is incomplete until every model-producing path writes trace/model-call/cost evidence and respects budget/provider timeout/cancel policy.
3. OS console depth remains uneven: Workflow Runtime Console, Agent Dispatch Center, Novel KG Workbench, Trace Timeline, Cost Dashboard, Invalidation Map, and Review Rework Board need route-level smoke coverage and operator-ready views.
4. Context Builder still needs deeper manual source selection, richer compression controls, KG-backed context, and invalidation warnings.
5. Semantic quality remains P1/P0 edge work: stronger provider-backed review, Novel KG extraction, alias merge, evidence spans, continuity conflict analysis, and feedback-to-plan learning.
6. Business rollback remains conservative: many operations can quarantine, mark, or supersede assets, but multi-asset rollback needs stronger guarantees.
7. Reader Feedback and Publishing Centers are not fully productized: feedback-to-plan loops, publishing calendar, platform status, and post-release data recovery still need depth.

## Operating Discipline

These rules bias toward clarity, traceability, and verification over speed.

### 1. Think Before Coding

Do not assume. Do not hide uncertainty. Surface tradeoffs early.

Before implementing:

- State important assumptions if they affect design, safety, data, or tests.
- If multiple interpretations exist, choose the safest reasonable one and explain the tradeoff.
- If a simpler approach exists, prefer it and avoid speculative architecture.
- If a wrong assumption could damage data or architecture, stop and ask.

### 2. Platform-First, Not Prompt-First

Do not solve durable system problems by only adding a bigger prompt.

For every AI capability, identify:

- node/stage;
- input schema;
- context bundle;
- output artifact;
- version behavior;
- quality gate;
- retry/revision path;
- audit log.

Prompts are execution parameters inside workflow nodes. They are not the product architecture.

### 3. Simplicity First

Use the minimum code that solves the current verified problem.

- Do not add features beyond the task.
- Do not create abstractions for single-use code.
- Do not add configurability that is not needed now.
- Do not add external dependencies unless an ADR or explicit user instruction requires it.
- If a small local function is enough, do not introduce a framework.

### 4. Surgical Changes

Touch only what the task requires.

- Do not refactor unrelated files.
- Do not reformat unrelated code.
- Match existing style and naming.
- Clean up imports, variables, and helper functions made unused by your own changes.
- If you notice unrelated dead code or risk, mention it instead of deleting it.

Every changed line should trace to the current task, a failing test, a validation rule, or a documented acceptance criterion.

### 5. Goal-Driven Execution

Transform tasks into verifiable goals:

- "Add validation" means add a failing or meaningful test, implement validation, then make tests pass.
- "Fix a bug" means reproduce the bug or identify concrete evidence, fix it, then verify it.
- "Refactor" means preserve behavior, keep public contracts stable, and run tests before claiming completion.

For multi-step work, use a short plan:

```text
1. Step -> verify: check
2. Step -> verify: check
3. Step -> verify: check
```

Do not treat "code written" as "task complete". Completion requires verification.

## Agent Responsibilities

- Claude Code: product owner, project editor, workflow controller, audit owner.
- Codex: engineering editor, code implementation, tests, CLI/API/UI glue, schema consistency.
- ChatGPT: advanced reviewer, multidisciplinary synthesis, commercial logic review, design critique.
- DeepSeek: future long-form draft producer behind a model adapter.
- MockModel: deterministic test adapter only.
- LocalRuleEngine: schema and quality rule checks.

Agents are roles and permission boundaries. Skills are reusable capabilities. Model adapters are execution interfaces.

Agent work must remain contract-based: `agent_contract`, `agent_run`, `agent_dispatch_queue`, `agent_checkpoint`, `agent_budget`, `agent_gate`, `agent_metric`, trace spans, and ledger records must be present before autonomous scheduling is trusted.

## Skills Rules

Skills are reusable capabilities, not Agent roles, knowledge assets, templates, executable tools, or storage locations.

- Root `skills/` is the project source of truth.
- `.claude/skills/` is runtime output only and must be generated from root `skills/`.
- Use `make sync-skills-dry-run` before `make sync-skills`.
- Use `docs/09-skills/agent-skill-map.md` to select Skills by Agent role.
- Popular novel analysis must use `hot-novel-deconstruction` or `hot-novel-business-deconstruction`, then `anti-copy-abstraction`.
- Published fiction analysis must use `published-fiction-craft-analysis`.
- Classic literary analysis must use `classic-literary-depth-analysis`.
- Analysis outputs must use `analysis-to-asset-conversion` before entering materials, knowledge, templates, or review rules.
- Drafting must use `chapter-outline` before `prose-generation`.
- Draft outputs must pass `quality-review` before revision or final decisions.
- Reader feedback must use `reader-feedback` before it changes chapter plans or revisions.
- Professional knowledge must use `multidisciplinary-knowledge` before entering KnowledgeCard or review rules.
- Skills must not store source text, protected expression, concrete copyable plots, private material, or real secrets.
- Skills do not expand Agent permissions and do not replace schemas, workflows, or review gates.

## Copyright And Originality Boundary

Reference works may be used only for structural learning and abstract mechanism extraction.

Allowed:

- Structure.
- Rhythm.
- Conflict mechanism.
- Character mechanism.
- Emotion curve.
- Hook pattern.
- Commercial readability logic.
- Craft technique stated as reusable abstraction.

Forbidden:

- Copying original sentences or distinctive expressions.
- Reusing protected characters, settings, or plot combinations.
- Mixing raw source text with generated drafts.
- Treating decomposition or analysis reports as draft prose.
- Encouraging direct imitation of a specific work.

Reference-derived assets must remain abstract and must preserve source lineage.

## Data Boundary

Keep asset stages separate:

- Raw source: `data/raw/`.
- Cleaned source: `data/cleaned/`.
- Decomposition: `data/decompositions/`.
- Analysis: `data/analysis/`.
- Knowledge: `data/knowledge/`.
- Materials: `data/materials/`.
- Platform/genre/topic/world/character/continuity/style/quality/template assets: dedicated generated asset directories.
- Outlines and chapter plans: `data/outlines/`, `data/chapter_plans/`.
- Drafts: `data/drafts/`.
- Reviews and revisions: `data/reviews/`.
- Publishing assets: `data/publishing/`.
- Feedback: `data/feedback/`.
- Workspaces: `data/workspaces/`.
- Runs, task status, handoff, and dead letters: `data/runs/`.

Do not move or merge these directories without updating docs, tests, and validation.

## Model Adapter Boundary

Runnable local workflows use:

- `MockModelAdapter`.
- `LocalRuleEngine`.
- Claude Code Codex worker through `CODEX_HOME=~/.codex-claude codex` for production agent model calls.

Provider adapters for ChatGPT and DeepSeek are opt-in OpenAI-compatible JSON providers. Generic Codex remains explicit unless selected through provider settings.

- `health_check()` is safe.
- Model output must be strict JSON when a schema-backed asset will be written.
- Invalid model output fails the step instead of writing malformed assets.
- Do not call external APIs in tests.
- Do not hard-code provider-specific logic inside business workflows.
- Do not read secrets except through documented provider settings.

Real provider support requires:

- Dependency policy.
- Secret policy.
- Mocked tests.
- No-network default test behavior.
- Trace, model-call, and cost-ledger evidence for production paths.

## Required Commands

Use these commands for verification:

```bash
make lint
make test
make validate
make sync-skills-dry-run
```

Use `make demo` only when demo asset generation is relevant to the task.

For local production-style stack changes, also use the smallest relevant Docker command:

```bash
make local-smoke
```

## Testing Standard

Before claiming completion:

- Run the smallest relevant test first when possible.
- Run `make lint`, `make test`, and `make validate` for code or schema changes.
- Run `make sync-skills-dry-run` or `make check-skills` for Skill changes.
- Record test results in roadmap docs when the task changes project status.
- If you cannot run tests because the execution environment lacks the repository or dependencies, state that explicitly and do not claim tests passed.
