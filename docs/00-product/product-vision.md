# Product Vision

## Product Positioning

Novel Forge v6 is a local-first AI novel production platform and early Novel Operating System runtime.

It is not an AI chapter generator and should not be designed around one-off prompt output. Its value comes from durable assets, controlled workflows, context replay, versioned production, quality gates, review/revision loops, Agent scheduling, trace/cost ledgers, and recoverable operating state.

The internal product target is Novel Operating System. This is an architecture target, not an approved repository/package rename in v6.

## Product Goal

Novel Forge turns source materials, abstracted reference analysis, multidisciplinary knowledge, reusable material cards, style profiles, quality standards, and reader feedback into controlled long-form fiction outputs.

The system should support:

- project and workspace management;
- asset accumulation and reuse;
- reference analysis without copying;
- context construction;
- versioned outline/chapter-plan/draft production;
- chapter review and revision;
- long-form continuity control;
- publishing gates and release packages;
- reader feedback analytics;
- Agent execution with contracts, checkpoints, budgets, gates, metrics, dispatch queues, and recovery.
- runtime observability through trace spans, gate results, model call logs, cost ledgers, budget policies, and cost-quality dashboards.
- Novel KG backed continuity, review, context, and impact analysis.

## Current Inputs

- Source documents and comments.
- Rights metadata.
- Cleaned text.
- Abstracted decomposition reports.
- Knowledge cards and material cards.
- Platform/genre/style/quality profiles.
- Model outputs through adapters.
- Reader feedback.

## Current Outputs

- Topics.
- Worlds.
- Characters.
- Outlines.
- Chapter plans.
- Drafts.
- Review reports.
- Revision plans.
- Originality, style, quality, chapter, publish, and release artifacts in first-generation form.
- Analysis reports for web fiction, published fiction, classic literature, and analysis conversion in first-generation form.
- Context build plans, context bundles, outline versions, chapter-plan versions, draft versions, and generation runs in first-generation form.
- Feedback insights.
- Workflow runs, node runs, task status records, Agent runs, checkpoints, trace spans, gate results, model call logs, cost ledgers, budget policies, and cost snapshots.
- Novel KG snapshots, queries, impact/conflict reports, and gate/preflight reports.

## Target Outputs

Platform work should deepen:

- semantic review for analysis reports and conversion gates;
- manual context curation, stale-context warnings, and richer context replay;
- chapter queues, parameter trace dashboards, and upstream invalidation for versioned production;
- editor patches and rollback evidence;
- revision tasks and issue-to-patch-to-version lineage;
- continuity audits and change impact reports;
- publishing plans and publishing logs;
- model benchmark runs;
- Agent Center UI, operation coverage, hard budget enforcement, and deeper rollback.

## Product Boundary

Novel Forge may learn from reference works only at the level of abstract reusable mechanisms:

- structure;
- rhythm;
- conflict design;
- character mechanism;
- emotion curve;
- chapter hook;
- commercial readability logic;
- craft technique.

It must not copy protected expression, distinctive characters, settings, scenes, or plot combinations.

## Novel OS Priority

The next development direction should be:

1. Universal Runtime Policy: every model-producing path must write trace, model-call, cost, budget, context, and provider-guard evidence.
2. Provider runtime guard: normalize usage, token cutoff, timeout, cancellation, and exact cost capture across local Codex/Claude Code and OpenAI-compatible providers.
3. Deep checkpoint resume and business rollback: support internal-stage resume, operation transactions, rollback preview, rollback apply, version restoration, and compensating ledgers.
4. Semantic quality layer: KG-backed context, stronger entity/relation extraction, evidence spans, alias merge, continuity conflict analysis, review/originality gates, and feedback-to-plan learning.
5. Web OS operations and long-chain acceptance: harden the OS console with browser smoke and prove multi-chapter continuity, cost drift, quality drift, recovery, and feedback backflow.

Detailed closure plan: [Novel OS Remaining Closure Plan](../08-roadmap/novel-os-remaining-closure-plan.md).

## Acceptance

The sample pipeline must run without external APIs and preserve copyright boundaries.

The Novel OS acceptance chain is not required to generate a complete long novel. P0 acceptance is a minimal vertical slice proving that the operating layer can execute, observe, gate, recover, revise, and publish-gate one chapter-sized target through durable artifacts. Full-novel generation is a later long-chain acceptance scenario for scale, continuity, quality drift, and cost control.

New features must make their current implementation state explicit: implemented, partial, target, or deferred. Do not describe target platform capabilities as completed product features until schema, service, UI, tests, and documentation exist.
