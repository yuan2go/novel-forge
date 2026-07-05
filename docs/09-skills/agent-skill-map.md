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
| Chief Editor Agent | `project-planning`, `quality-review`, `novel-os-engineering-audit`, `platform-strategy-os` | Converts product goals into executable plans, acceptance decisions, platform priorities, and evidence-backed risk calls. |
| Workflow Agent | `agent-loop-governance`, `project-planning`, `review-issue-gate` | Coordinates workflow definitions, recovery, checkpoints, loop budgets, and acceptance evidence without bypassing runtime policy. |
| Knowledge Agent | `mkaos-knowledge-asset-os`, `multidisciplinary-knowledge`, `anti-copy-abstraction`, `analysis-to-asset-conversion` | Reference-derived analysis and professional knowledge must become evidence-backed, source-isolated MKAOS assets before downstream use. |
| Material Agent | `material-curation`, `mkaos-knowledge-asset-os`, `analysis-to-asset-conversion`, `anti-copy-abstraction` | Converts raw and abstracted assets into reusable production material with lineage, rights, and quality status. |
| Context Agent | `context-builder-source-isolation`, `mkaos-knowledge-asset-os`, `material-curation`, `quality-review` | Selects, ranks, compresses, and replays context bundles through Context Builder and Knowledge Pack contracts. |
| Topic Agent | `topic-development`, `platform-strategy-os`, `anti-copy-abstraction`, `material-curation` | Develops market-positioned and differentiated TopicSeed candidates with platform fit. |
| Worldbuilding Agent | `worldbuilding`, `mkaos-knowledge-asset-os`, `context-builder-source-isolation` | Every setting must create conflict, limits, cost, or hooks and remain source-isolated. |
| Character Agent | `character-design`, `context-builder-source-isolation` | Character actions must serve the main conflict and remain traceable to approved context. |
| Outline Agent | `long-outline`, `platform-strategy-os`, `character-design`, `worldbuilding`, `context-builder-source-isolation` | Outline must integrate character pressure, world rules, reader payoff, platform strategy, and MKAOS context. |
| Chapter Plan Agent | `chapter-outline`, `platform-strategy-os`, `quality-review`, `context-builder-source-isolation` | Every chapter plan must pass commercial unit, platform rhythm, and source isolation checks. |
| Draft Agent | `prose-generation`, `chapter-outline`, `context-builder-source-isolation`, `review-issue-gate` | Drafting must follow approved chapter plan and ContextBundle, then produce reviewable draft candidates rather than final text. |
| Editor Agent | `quality-review`, `review-issue-gate`, `prose-generation`, `chapter-outline` | Applies controlled local revisions through editor patches, draft versions, ReviewIssue resolution, and rollback-capable artifacts. |
| Review Agent | `quality-review`, `review-issue-gate`, `anti-copy-abstraction`, `mkaos-knowledge-asset-os` | Reviews must check originality, source leakage, MKAOS misuse, platform risk, and produce actionable revision tasks. |
| Quality Agent | `quality-review`, `review-issue-gate`, `context-builder-source-isolation`, `novel-os-engineering-audit` | Runs validation, continuity, publish, originality, source isolation, and OS acceptance gates. |
| Feedback Agent | `reader-feedback`, `mkaos-knowledge-asset-os`, `platform-strategy-os`, `quality-review` | Feedback must be classified, attributed to assets/knowledge/platform strategy, and converted into advisory learning before mutation. |
| Publishing Agent | `review-issue-gate`, `platform-strategy-os`, `quality-review`, `context-builder-source-isolation` | Checks release readiness, source isolation, platform fit, and blocking gates before any release package is accepted. |
| Model Evaluation Agent | `quality-review`, `novel-os-engineering-audit`, `project-planning` | Evaluates model quality, latency, cost, routing, and regression only through traceable benchmark assets. |
| Training Agent | `training-exercise`, `quality-review`, `multidisciplinary-knowledge`, `mkaos-knowledge-asset-os` | Builds exercises and rubrics from reusable knowledge, evidence refs, and review standards. |
| Agent Center / Scheduler | `agent-loop-governance`, `context-builder-source-isolation`, `review-issue-gate` | Uses operation coverage, context contracts, hard-stop policy, checkpoints, and dead-letter recovery. |
| Platform Strategy Agent | `platform-strategy-os`, `mkaos-knowledge-asset-os`, `review-issue-gate` | Turns platform rules and feedback into profiles, rhythm gates, retention risks, publish adapters, and backflow recommendations. |
| Engineering Audit Agent | `novel-os-engineering-audit`, `agent-loop-governance`, `context-builder-source-isolation` | Audits implementation against docs, code, UI, tests, gates, and acceptance evidence. |

## Runtime Tool Skills

The following Skills may exist only in Claude Code runtime under `.claude/skills/` or plugin caches. They are useful tools but not repository source Skills unless explicitly vendored after license review.

| Runtime Skill | Recommended Use | Boundary |
|---|---|---|
| `pdf`, `docx`, `xlsx` | Local document analysis or fixture generation. | Must not move protected source text into MKAOS packs, prose, publish, or recap contexts. |
| `mcp-builder`, `claude-api`, `skill-creator` | MCP/API/Skill scaffolding or architecture help. | Must remain opt-in and cannot bypass Runtime Policy, OS Envelope, or tests. |
| `webapp-testing`, `frontend-design` | Admin UI smoke tests, Playwright checks, and design review. | UI changes still require project tests and local-first boundaries. |
| `doc-coauthoring` | Collaborative documentation drafting. | Docs must stay consistent with implemented code and acceptance status. |

## Acceptance

- Every implemented Agent has at least one usable Skill.
- Drafting can be traced to `chapter-outline`.
- Draft outputs can be traced to `quality-review`.
- Reference-work analysis can be traced to `anti-copy-abstraction`.
- Reader feedback, material curation, topic development, training, and multidisciplinary knowledge outputs remain bounded by schema validation and review gates.
- Workflow/Agent-dispatched Skill outputs can be traced to runtime policy evidence when they create model-produced or production-mutating assets.
- MKAOS, Context Builder, ReviewIssue, Agent Loop, Platform Strategy, and Engineering Audit have dedicated Skills.
- Runtime-only tool Skills are separated from root project Skills and require license/source review before vendoring.

## Risks And Boundaries

- Agent permissions still come from `AGENTS.md`; Skills do not expand permissions.
- Skills do not store knowledge assets or source text.
- Skills do not override workflow status, schema validation, runtime policy, trace/cost ledger requirements, or review gates.
