# CLAUDE.md

This file defines project-level operating rules for Claude Code, Codex, and other coding agents working in Novel Forge V5.

Novel Forge V5 is no longer documented as a simple AI chapter generator. It is a local-first AI novel production platform. The internal long-term architecture vision may be called a Novel Operating System, but the repository, package, CLI, and public product name remain `novel-forge` / Novel Forge unless a separate migration task explicitly approves a rename.

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

A rename to Novel Operating System is not approved in V5. It is too broad for the current implementation state and would create unnecessary package, CLI, path, and documentation churn.

## Platform Architecture Direction

All new work should move the project toward a workflow-first platform architecture:

```text
Project / Workspace
  -> Workflow Definition
  -> Workflow Node
  -> Context Bundle
  -> Generation / Analysis / Review Run
  -> Artifact Version
  -> Quality Gate
  -> Revision Task
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

Do not overclaim. V5 currently has a strong base but not the complete platform.

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

Known P0 gaps to respect in planning:

1. Context Builder is now schema/API/UI backed for `context_build_plan` and `context_bundle`; remaining work is deeper manual source selection, richer compression controls, and invalidation warnings.
2. Outline/chapter-plan/draft production now records `outline_version`, `chapter_plan_version`, `draft_version`, and `generation_run`; remaining work is chapter queue, parameter trace dashboards, and upstream-change invalidation.
3. Analysis Center first slice is implemented: common/web-fiction/published/classic report schemas, services, UI, handoff packets, and analysis-to-asset conversion exist. Remaining work is stronger provider-backed semantic scoring, richer visualization, and conversion review gates.
4. AI Editor is not yet a full editing workbench: paragraph-level suggestions, single/batch apply, `editor_patch`, operation presets, rollback, and replay are still needed.
5. Long-form stability remains shallow, but `change_impact_report` now exists with downstream reference scanning and Web Admin visibility. Remaining work is timeline workbench, foreshadowing placement/payoff, relationship graph, faction/map/prop systems, and deeper impact visualization.
6. Agent industrialization first slice exists: `agent_contract`, `agent_run`, `agent_checkpoint`, `agent_event`, `agent_budget`, `agent_gate`, `agent_metric`, `agent_failure_report`, state machine validation, handoff synchronization, and Production Control visibility. Remaining work is full executor enforcement, SLA/recovery, rollback, and deeper Agent Center UI.
7. Reader Feedback Center is not fully productized: web import, sentiment distribution, payoff/toxic-point clustering, role heat, retention/drop-off analysis, and feedback-to-plan loops are still needed.
8. Publishing Center is first-generation only: publishing calendar, chapter queue, platform status, title/summary/hook checks, `publishing_plan`, `publishing_log`, and post-release data recovery are still needed.
9. Model Evaluation Center is not built: `model_profile`, `model_benchmark_task`, `model_benchmark_run`, A/B comparison, cost-quality analysis, prompt regression, and model routing are still needed.

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

Future Agent work must be contract-based: `agent_contract`, `agent_run`, `agent_checkpoint`, `agent_budget`, `agent_gate`, and `agent_metric` before autonomous scheduling is trusted.

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

Provider adapters for ChatGPT and DeepSeek are opt-in OpenAI-compatible JSON providers. Claude Code and Codex are manual/operator adapters unless a future ADR approves an in-process provider integration.

- `health_check()` is safe.
- Model output must be strict JSON when a schema-backed asset will be written.
- Invalid model output fails the step instead of writing malformed assets.
- Do not call external APIs in tests.
- Do not hard-code provider-specific logic inside business workflows.
- Do not read secrets except through documented provider settings.

Real provider support requires:

- ADR.
- Dependency policy.
- Secret policy.
- Mocked tests.
- No-network default test behavior.

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
