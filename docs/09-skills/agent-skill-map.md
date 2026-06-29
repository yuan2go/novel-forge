# Agent Skill Map

## Module Goal

This file maps Novel Forge v6 Agent roles to reusable Skills so responsibilities remain clear and repeatable inside the early Novel Operating System runtime.

## Inputs

- `AGENTS.md`
- `CLAUDE.md`
- `docs/09-skills/README.md`
- `skills/*/SKILL.md`
- Current task and target asset files

## Outputs

- Recommended Agent-Skill mapping.
- Explicit Skill candidates for workflow and Agent operation selection.
- Permission boundaries for Skill use.

## File Paths

```text
docs/09-skills/agent-skill-map.md
skills/*/SKILL.md
```

## Execution Flow

1. Determine the responsible Agent.
2. Select Skills from the mapping below.
3. Check the Skill input requirements.
4. Execute the Skill workflow.
5. Route draft, production-mutating, or high-risk outputs to runtime policy checks and `quality-review`.

## Agent-Skill Mapping

| Agent | Recommended Skills | Notes |
|---|---|---|
| Chief Editor Agent | `project-planning`, `quality-review`, `long-outline` | Converts product goals into executable and testable plans. |
| Workflow Agent | `project-planning`, `quality-review` | Coordinates workflow definitions, recovery, and acceptance evidence without bypassing runtime policy. |
| Knowledge Agent | `hot-novel-deconstruction`, `anti-copy-abstraction`, `multidisciplinary-knowledge` | Reference-derived analysis and professional knowledge must be abstracted before downstream use. |
| Material Agent | `material-curation`, `hot-novel-deconstruction`, `anti-copy-abstraction`, `multidisciplinary-knowledge` | Converts raw and abstracted assets into reusable production material. |
| Context Agent | `material-curation`, `quality-review`, `project-planning` | Selects, ranks, compresses, and replays context bundles with KG-backed context when OS policy requires it. |
| Topic Agent | `topic-development`, `anti-copy-abstraction`, `material-curation` | Develops market-positioned and differentiated TopicSeed candidates. |
| Worldbuilding Agent | `worldbuilding` | Every setting must create conflict, limits, cost, or hooks. |
| Character Agent | `character-design` | Character actions must serve the main conflict. |
| Outline Agent | `long-outline`, `character-design`, `worldbuilding` | Outline must integrate character pressure, world rules, and reader payoff. |
| Chapter Plan Agent | `chapter-outline`, `quality-review` | Every chapter plan must pass the minimum commercial unit check. |
| Draft Agent | `prose-generation`, `chapter-outline` | Drafting must follow the approved chapter plan and cannot directly produce final text. |
| Editor Agent | `quality-review`, `prose-generation`, `chapter-outline` | Applies controlled local revisions through editor patches, draft versions, and rollback-capable artifacts. |
| Review Agent | `quality-review`, `anti-copy-abstraction` | Reviews must check originality risk and produce actionable revision advice. |
| Quality Agent | `quality-review`, `anti-copy-abstraction`, `project-planning` | Runs validation, continuity, publish, originality, and OS acceptance gates. |
| Feedback Agent | `reader-feedback`, `quality-review` | Feedback must be classified before it changes future chapters. |
| Publishing Agent | `quality-review`, `anti-copy-abstraction` | Checks release readiness and publish gates before any release package is accepted. |
| Model Evaluation Agent | `quality-review`, `project-planning` | Evaluates model quality, latency, cost, and routing only through traceable benchmark assets. |
| Training Agent | `training-exercise`, `quality-review`, `multidisciplinary-knowledge` | Builds exercises and rubrics from reusable knowledge and review standards. |

## Acceptance

- Every implemented Agent has at least one usable Skill.
- Drafting can be traced to `chapter-outline`.
- Draft outputs can be traced to `quality-review`.
- Reference-work analysis can be traced to `anti-copy-abstraction`.
- Reader feedback, material curation, topic development, training, and multidisciplinary knowledge outputs remain bounded by schema validation and review gates.
- Workflow/Agent-dispatched Skill outputs can be traced to runtime policy evidence when they create model-produced or production-mutating assets.

## Risks And Boundaries

- Agent permissions still come from `AGENTS.md`; Skills do not expand permissions.
- Skills do not store knowledge assets or source text.
- Skills do not override workflow status, schema validation, runtime policy, trace/cost ledger requirements, or review gates.
