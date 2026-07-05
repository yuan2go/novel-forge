# AGENTS.md

## Purpose

Agents working on Novel Forge v6 must preserve the platform boundary: Novel Forge is a local-first AI novel production platform and early Novel Operating System runtime, not a one-off prompt generator.

Agents may help with fiction production, analysis, review, implementation, and operations only through traceable inputs, schema-backed outputs, quality gates, and documented storage boundaries.

Reference works are used for abstract structural learning, not copying.

## Current Agent Maturity

v6 currently supports manual/operator Agent roles, Skills, handoff packets, runtime profiles, permission guards, tool allowlists, task statuses, workflow runs, and the first production slice of Agent execution.

The following Agent runtime assets and services now exist as first-slice infrastructure:

- `agent_contract`
- `agent_run`
- `agent_checkpoint`
- `agent_budget`
- `agent_gate`
- `agent_metric`
- `agent_dispatch_queue`
- Agent operation registry
- scheduler tick/loop with queue leasing, retry, and dead-letter behavior
- resumable, rollback-aware, acceptance-gated Agent execution for registered operations

Do not claim a complete autonomous Agent Center exists until UI depth, operation coverage, model usage hard-stop behavior, business rollback, and end-to-end OS acceptance tests are implemented.

## Core Agent Classes

| Agent | Primary Input | Primary Output | Permissions | Forbidden |
|---|---|---|---|---|
| Chief Editor Agent | product docs, roadmap, current implementation, risks | priorities, acceptance decisions, architectural constraints | update docs and plans | claim completion without evidence or tests |
| Workflow Agent | project goal, workflow definition, node state, run logs | workflow plan, node order, recovery instruction | coordinate workflow runs and node contracts | bypass schema, artifact, or quality-gate requirements |
| Engineering Agent | schemas, services, API, UI, tests | code, tests, migrations, docs | edit `src/`, `tests/`, `web/`, docs | break compatibility silently or mix unrelated refactors |
| Analysis Agent | cleaned sources, analysis profile, rights metadata | abstract analysis report | deconstruct structure, rhythm, conflict, craft, emotion, hooks | copy protected expression, characters, settings, or plot combinations |
| Knowledge Agent | cleaned text, decompositions, analysis reports | knowledge cards, rule candidates | abstract and tag reusable knowledge | mix raw sources with generated drafts |
| Material Agent | knowledge/decomposition/analysis assets | reusable material cards, templates | build reusable asset library | copy story-specific protected combinations |
| Context Agent | project goal, asset pool, token budget, generation target | context build plan, context bundle | select, rank, compress, and replay context | hide actual sent context or overfill token budget without warning |
| Topic Agent | platform profile, genre market profile, materials | topic seed, topic fit report | generate differentiated topic options | imitate a specific copyrighted work |
| Worldbuilding Agent | topic, materials, knowledge, platform rules | world bible, continuity seeds | define rules, factions, resources, limits | create rules that contradict existing continuity without impact report |
| Character Agent | topic, world bible, genre logic | character cards, relationship seeds | design motivations, wounds, desires, arcs | create decorative characters without plot function |
| Outline Agent | topic, world, characters, quality standard | long outline, volume outline | structure long-form progression | ignore foreshadowing, pacing, or platform rhythm |
| Chapter Plan Agent | outline, continuity, character arcs | chapter plan | design scene goals, conflicts, reversals, hooks | skip chapter-level conflict and payoff |
| Draft Agent | chapter plan, context bundle, style profile | draft chapter candidate | generate model-backed draft candidates | write final text from raw reference sources or skip review |
| Editor Agent | draft, review issues, style profile | editor patch, revised draft candidate | apply controlled local revisions | overwrite drafts without version, diff, or rollback path |
| Review Agent | draft, rubric, continuity, platform profile | review report, audit reports, revision tasks | produce critique assets and gates | overwrite drafts directly or suppress high-severity issues |
| Quality Agent | all artifacts, schemas, release package | validation report, risk report, gate result | run checks and record failures | suppress warnings or mark unverified outputs as accepted |
| Feedback Agent | reader feedback, chapter metrics, comments | feedback insight, plan adjustment suggestions | cluster emotions, payoff/toxic points, role heat, drop-off signals | change outline/chapter plans without traceable revision task |
| Publishing Agent | final chapter, release package, platform profile | publish gate report, publishing plan, log | check title, summary, hook, schedule, platform status | publish unreviewed or blocked content |
| Model Evaluation Agent | generation runs, benchmark tasks, model profiles | benchmark run, routing recommendation | compare cost, quality, regression, latency | route production work to unverified providers |

## Agent-Skill Map

Agent is a role and permission boundary. Skill is a reusable capability. Use `docs/09-skills/agent-skill-map.md` for detailed runtime selection.

| Agent | Recommended Skills |
|---|---|
| Chief Editor Agent | `project-planning`, `quality-review`, `long-outline`, `novel-os-engineering-audit`, `platform-strategy-os` |
| Workflow Agent | `project-planning`, `quality-review`, `agent-loop-governance`, `review-issue-gate` |
| Analysis Agent | `hot-novel-deconstruction`, `hot-novel-business-deconstruction`, `published-fiction-craft-analysis`, `classic-literary-depth-analysis`, `anti-copy-abstraction`, `analysis-to-asset-conversion` |
| Knowledge Agent | `mkaos-knowledge-asset-os`, `multidisciplinary-knowledge`, `anti-copy-abstraction`, `analysis-to-asset-conversion` |
| Material Agent | `material-curation`, `mkaos-knowledge-asset-os`, `analysis-to-asset-conversion`, `topic-development` |
| Context Agent | `context-builder-source-isolation`, `mkaos-knowledge-asset-os`, `material-curation`, `quality-review` |
| Topic Agent | `topic-development`, `platform-strategy-os`, `material-curation` |
| Worldbuilding Agent | `worldbuilding`, `multidisciplinary-knowledge`, `mkaos-knowledge-asset-os` |
| Character Agent | `character-design`, `worldbuilding`, `context-builder-source-isolation` |
| Outline Agent | `long-outline`, `character-design`, `worldbuilding`, `platform-strategy-os`, `context-builder-source-isolation` |
| Chapter Plan Agent | `chapter-outline`, `quality-review`, `platform-strategy-os`, `context-builder-source-isolation` |
| Draft Agent | `prose-generation`, `chapter-outline`, `context-builder-source-isolation`, `review-issue-gate` |
| Editor Agent | `quality-review`, `review-issue-gate`, `prose-generation`, `chapter-outline` |
| Review Agent | `quality-review`, `review-issue-gate`, `anti-copy-abstraction`, `mkaos-knowledge-asset-os` |
| Feedback Agent | `reader-feedback`, `quality-review`, `mkaos-knowledge-asset-os`, `platform-strategy-os` |
| Publishing Agent | `quality-review`, `review-issue-gate`, `platform-strategy-os`, `context-builder-source-isolation` |
| Model Evaluation Agent | `quality-review`, `project-planning`, `novel-os-engineering-audit` |

## Execution Contract

Every Agent output must be traceable to:

- input files or source task;
- schema type;
- output path;
- project/workspace id when applicable;
- model/provider when a provider is used;
- prompt or Skill version when relevant;
- validation status;
- quality gate status;
- `trace_id` / `span_id` when the output is part of a workflow or agent run;
- `model_call_log` and `cost_ledger` records when a model call is made;
- downstream artifact or revision task.

Agents must not communicate by informal chat memory when a schema-backed artifact is required. Use JSON assets, workflow run records, task status, handoff packets, review reports, revision plans, Agent run records, trace spans, gate results, and ledger records.

## Agent State Model

Until a full state machine is implemented, use this conceptual state model for docs and design:

```text
planned -> ready -> running -> checkpointed -> needs_review -> accepted
                                      |              |
                                      v              v
                                   failed       needs_revision
                                      |              |
                                      v              v
                                  recovered <--- rerun
```

Required state rules:

- A running Agent must have a bounded task and input set.
- A checkpoint must identify completed work and remaining work.
- A failed Agent must produce an error and recovery instruction.
- An accepted Agent output must have an artifact, gate result, or test result.
- A rerun must create a new run/version record instead of mutating the old result silently.

## Copyright And Originality Boundary

Allowed from reference works:

- structure;
- rhythm;
- conflict mechanism;
- character mechanism;
- emotion curve;
- hook pattern;
- commercial readability logic;
- abstract craft technique.

Forbidden:

- original sentences or distinctive expressions;
- protected characters, settings, scenes, and plot combinations;
- raw source text inside generated drafts;
- decomposition/analysis reports treated as draft prose;
- direct imitation of a named work.

Reference-derived assets must preserve lineage and remain abstract.

## Skills Rule

Skills do not permit Agents to bypass schema validation, storage boundaries, copyright boundaries, provider boundaries, or review gates.

Runtime copies under `.claude/skills/` must be generated from root `skills/` using `make sync-skills`; do not edit runtime copies as the source of truth.

## Acceptance Rule

An Agent task is not complete because text was generated. Completion requires the smallest relevant verification:

- docs-only: consistency check against current implementation and roadmap;
- schema/code: tests plus validation;
- Skill changes: skill dry-run or drift check;
- workflow changes: run/task status and recovery behavior checks;
- Agent Scheduler changes: dispatch queue, checkpoint, gate, budget/SLA, retry/dead-letter, and recovery checks;
- UI changes: local smoke or route-level verification when possible;
- production content: review report and quality gate result.

Novel Operating System acceptance is not equivalent to generating a full long novel. The P0 acceptance standard is a minimal vertical slice that proves one project/chapter-sized fixture can pass through workflow execution, agent dispatch, context/model boundary, trace/cost ledger, KG/continuity gate, review rework, publish gate, invalidation, and resume without bypassing schema-backed artifacts.
