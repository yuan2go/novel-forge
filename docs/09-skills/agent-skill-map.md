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
| Chief Editor Agent | `project-planning`, `quality-review`, `narrative-beat-design`, `multi-scale-pacing`, `novel-os-engineering-audit`, `platform-strategy-os`, `publish-release-gate-os` | Converts product goals into executable plans, acceptance decisions, narrative beat priorities, multi-scale pacing priorities, platform priorities, release readiness, and evidence-backed risk calls. |
| Workflow Agent | `agent-loop-governance`, `project-planning`, `review-issue-gate`, `provider-runtime-policy` | Coordinates workflow definitions, recovery, checkpoints, provider budgets, loop budgets, and acceptance evidence without bypassing runtime policy. |
| Engineering Agent | `project-planning`, `novel-os-engineering-audit`, `skill-governance` | Turns specs and audits into file-level, interface-level, testable implementation plans without letting Skill edits bypass governance. |
| Knowledge Agent | `mkaos-knowledge-asset-os`, `multidisciplinary-knowledge`, `evidence-fact-verification`, `anti-copy-abstraction`, `analysis-to-asset-conversion` | Reference-derived analysis and professional knowledge must become evidence-backed, source-isolated MKAOS assets before downstream use. |
| Material Agent | `material-curation`, `mkaos-knowledge-asset-os`, `analysis-to-asset-conversion`, `anti-copy-abstraction` | Converts raw and abstracted assets into reusable production material with lineage, rights, and quality status. |
| Context Agent | `context-builder-source-isolation`, `mkaos-knowledge-asset-os`, `material-curation`, `quality-review`, `longform-temporal-query`, `canon-continuity-graph` | Selects, ranks, compresses, and replays as-of context bundles through Context Builder, Knowledge Pack, temporal-query, and canon continuity contracts. |
| Topic Agent | `topic-development`, `platform-strategy-os`, `anti-copy-abstraction`, `material-curation` | Develops market-positioned and differentiated TopicSeed candidates with platform fit. |
| Worldbuilding Agent | `worldbuilding`, `world-consequence-modeling`, `mkaos-knowledge-asset-os`, `context-builder-source-isolation`, `canon-continuity-graph` | World rules and their candidate systemic consequences remain distinct, source-isolated, continuity-safe, and subject to Story Design Authority activation. |
| Character Agent | `character-design`, `context-builder-source-isolation`, `canon-continuity-graph` | Character actions must serve the main conflict and remain traceable to approved context and accepted canon. |
| Outline Agent | `long-outline`, `narrative-beat-design`, `multi-scale-pacing`, `world-consequence-modeling`, `platform-strategy-os`, `character-design`, `worldbuilding`, `context-builder-source-isolation`, `longform-temporal-query`, `canon-continuity-graph` | Outline must integrate character pressure, world rules and consequences, reader grounding, beat and pacing progression, platform strategy, as-of canon continuity, and MKAOS context. |
| Chapter Plan Agent | `chapter-outline`, `narrative-beat-design`, `multi-scale-pacing`, `platform-strategy-os`, `quality-review`, `context-builder-source-isolation`, `longform-temporal-query`, `canon-continuity-graph` | Every chapter plan must pass commercial unit, hook/promise, beat grounding, platform rhythm, as-of source isolation, pacing, and continuity checks. |
| Draft Agent | `prose-generation`, `chapter-outline`, `context-builder-source-isolation`, `review-issue-gate`, `provider-runtime-policy` | Drafting must follow approved chapter plan and ContextBundle, record provider evidence, then produce reviewable draft candidates rather than final text. |
| Editor Agent | `quality-review`, `review-issue-gate`, `prose-generation`, `chapter-outline`, `canon-continuity-graph` | Applies controlled local revisions through editor patches, draft versions, ReviewIssue resolution, canon impact checks, and rollback-capable artifacts. |
| Review Agent | `quality-review`, `multi-scale-pacing`, `evidence-fact-verification`, `review-issue-gate`, `anti-copy-abstraction`, `mkaos-knowledge-asset-os`, `longform-temporal-query`, `canon-continuity-graph` | Reviews must check originality, evidence, source leakage, multi-scale pacing, MKAOS misuse, as-of canon conflict, platform risk, and produce actionable revision tasks. |
| Quality Agent | `quality-review`, `multi-scale-pacing`, `evidence-fact-verification`, `review-issue-gate`, `context-builder-source-isolation`, `longform-temporal-query`, `canon-continuity-graph`, `publish-release-gate-os`, `provider-runtime-policy`, `novel-os-engineering-audit` | Runs validation, temporal continuity, pacing, fact, publish, provider, originality, source isolation, and OS acceptance gates. |
| Feedback Agent | `reader-feedback`, `mkaos-knowledge-asset-os`, `platform-strategy-os`, `quality-review` | Feedback must be classified, attributed to assets/knowledge/platform strategy, and converted into advisory learning before mutation. |
| Publishing Agent | `publish-release-gate-os`, `review-issue-gate`, `platform-strategy-os`, `quality-review`, `context-builder-source-isolation`, `canon-continuity-graph` | Checks release readiness, source isolation, platform fit, continuity, rollback/resume evidence, and blocking gates before any release package is accepted. |
| Model Evaluation Agent | `provider-runtime-policy`, `quality-review`, `novel-os-engineering-audit`, `project-planning` | Evaluates model quality, latency, cost, routing, fallback, and regression only through traceable benchmark assets. |
| Training Agent | `training-exercise`, `quality-review`, `multidisciplinary-knowledge`, `mkaos-knowledge-asset-os` | Builds exercises and rubrics from reusable knowledge, evidence refs, and review standards. |
| Agent Center / Scheduler | `agent-loop-governance`, `provider-runtime-policy`, `context-builder-source-isolation`, `review-issue-gate` | Uses operation coverage, provider hard-stops, context contracts, checkpoints, and dead-letter recovery. |
| Platform Strategy Agent | `platform-strategy-os`, `publish-release-gate-os`, `mkaos-knowledge-asset-os`, `review-issue-gate` | Turns platform rules and feedback into profiles, rhythm gates, retention risks, publish adapters, and backflow recommendations. |
| Engineering Audit Agent | `novel-os-engineering-audit`, `agent-loop-governance`, `provider-runtime-policy`, `canon-continuity-graph`, `context-builder-source-isolation` | Audits implementation against docs, code, UI, tests, provider/canon gates, and acceptance evidence. |
| Skill Governance Agent | `skill-governance`, `project-planning`, `novel-os-engineering-audit` | Creates, revises, audits, syncs, and adopts Skills through predictable triggers, single source of truth, progressive disclosure, and runtime boundary checks. |

## Runtime Tool Skills

The following Skills may exist only in Claude Code runtime under `.claude/skills/` or plugin caches. They are useful tools but not repository source Skills unless explicitly vendored after license review.

| Runtime Skill | Recommended Use | Boundary |
|---|---|---|
| `pdf`, `docx`, `xlsx` | Local document analysis or fixture generation. | Proprietary runtime material; use only for explicit file tasks, do not vendor into root `skills/`, do not move protected source text into MKAOS packs, prose, publish, or recap contexts. |
| `claude-api` | Claude/Anthropic SDK, Claude model migration, Managed Agents, or Claude provider work. | Provider-specific and opt-in; never override OpenAI/Codex/provider-neutral tasks, never store secrets, and do not bypass `provider-runtime-policy`. |
| `mcp-builder`, `skill-creator` | MCP server or Skill scaffolding, eval, and architecture help. | Must remain opt-in; network/API/eval runs require task need and cannot bypass Runtime Policy, OS Envelope, or tests. |
| `webapp-testing`, `frontend-design` | Admin UI smoke tests, Playwright checks, and design review. | UI changes still require project tests and local-first boundaries. |
| `doc-coauthoring` | Collaborative documentation drafting. | Docs must stay consistent with implemented code and acceptance status. |

## Acceptance

- Every implemented Agent has at least one usable Skill.
- Drafting can be traced to `chapter-outline`.
- Draft outputs can be traced to `quality-review`.
- Reference-work analysis can be traced to `anti-copy-abstraction`.
- Reader feedback, material curation, topic development, training, and multidisciplinary knowledge outputs remain bounded by schema validation and review gates.
- Workflow/Agent-dispatched Skill outputs can be traced to runtime policy evidence when they create model-produced or production-mutating assets.
- MKAOS, Context Builder, ReviewIssue, Agent Loop, Provider Runtime, Canon Continuity, Temporal Query, Multi-scale Pacing, World Consequence, Evidence Verification, Publish Release Gate, Narrative Beat Design, Skill Governance, Platform Strategy, and Engineering Audit have dedicated Skills.
- Runtime-only tool Skills are separated from root project Skills and require license/source review before vendoring.

## Risks And Boundaries

- Agent permissions still come from `AGENTS.md`; Skills do not expand permissions.
- Skills do not store knowledge assets or source text.
- Skills do not override workflow status, schema validation, runtime policy, trace/cost ledger requirements, or review gates.
- Runtime tool Skills do not authorize provider calls, external network access, office conversion, browser automation, or subprocess execution unless the task explicitly needs them and local policy allows them.
