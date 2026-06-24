# External Claude Code Resource Intake

## Module Goal

This document defines how Novel Forge evaluates external Claude Code ecosystem resources before pulling their ideas, commands, Skills, hooks, agents, scripts, or workflows into the project.

The policy is informed by `hesreallyhim/awesome-claude-code`, which curates Claude Code resources such as Skills, hooks, slash commands, agent orchestrators, applications, plugins, status lines, and developer tooling. That repository also demonstrates a useful static repository-evaluation command and a resource-list maintenance workflow.

Novel Forge should adopt the governance patterns, not blindly copy third-party runtime behavior.

## Source Review Summary

`awesome-claude-code` is useful to Novel Forge as a reference for:

- Categorizing Claude Code resources by capability type.
- Treating hooks, slash commands, scripts, plugins, and persistent state as execution surfaces.
- Using static, evidence-based review before trusting a resource.
- Keeping generated or runtime outputs separate from source-of-truth files.
- Validating resource catalogs and generated docs with tests.

It is not directly useful as a dependency because Novel Forge is a fiction-production system, not a public awesome-list repository.

## Adoption Decision

| Remote Pattern | Novel Forge Decision | Reason |
|---|---|---|
| Curated resource categories | adapt | Useful for deciding whether something is Skill, Agent, Tool, Hook, Workflow, or documentation. |
| Static repository evaluation slash command | adopt as local command template | Directly reduces supply-chain and implicit-execution risk. |
| Hooks and lifecycle automation | defer | Current project should not add implicit execution until explicit ADR and tests exist. |
| CSV-first public resource table | defer | Novel Forge does not need a public awesome-list catalog now. |
| README generation variants | reject for now | Adds maintenance complexity without improving fiction-production flow. |
| Link/license validation for public submissions | defer | Useful only if Novel Forge starts accepting external resource submissions. |
| Badge, ticker, and visual README tooling | reject | Not relevant to production workflow or quality gates. |

## Local Files Added

```text
.claude/commands/evaluate-claude-resource.md
docs/09-skills/external-resource-intake.md
```

## Intake Workflow

1. Identify the candidate resource and its category.
2. Run a static review using `.claude/commands/evaluate-claude-resource.md`.
3. Classify the decision as `adopt`, `adapt`, `defer`, or `reject`.
4. If adopting or adapting, implement the smallest local change.
5. Add or update tests for any executable surface.
6. Run `make lint`, `make test`, and `make validate`.
7. Record the decision in roadmap docs when it changes project behavior.

## Resource Categories

| Category | Novel Forge Target | Default Policy |
|---|---|---|
| Skill | `skills/<name>/SKILL.md` | Allowed if it stores stable method, not source content. |
| Slash command | `.claude/commands/*.md` | Allowed if read-only or explicitly bounded. |
| Agent | `AGENTS.md` or `docs/09-skills/agent-skill-map.md` | Allowed as role mapping, not autonomous runtime. |
| Hook | none yet | Deferred until ADR, tests, and explicit opt-in exist. |
| Script/tool | `scripts/` or CLI module | Allowed only with deterministic local tests. |
| Workflow guide | `docs/02-workflows/` or `docs/09-skills/` | Allowed if it clarifies execution and acceptance. |
| Plugin/MCP | none yet | Deferred until dependency and permission policy exists. |

## Safety Gate

Reject or defer any resource that:

- Executes hooks automatically without clear opt-in.
- Reads secrets or environment variables without documented purpose.
- Writes outside the repository by default.
- Requires network access for core tests.
- Mixes protected fiction text into reusable Skills.
- Bypasses `skills/` as source of truth.
- Encourages direct imitation of copyrighted expression.
- Has documentation that materially differs from observable behavior.

## Fit Criteria

External features are worth pulling into Novel Forge only if they improve one of these capabilities:

- Safer Claude Code runtime governance.
- Better Skill lifecycle and validation.
- Clearer Agent/Skill/workflow boundaries.
- More reliable local CLI or test automation.
- Better audit trails for writing assets.
- More explicit originality, copyright, and review gates.

## Acceptance

- The local slash command exists at `.claude/commands/evaluate-claude-resource.md`.
- The command is read-only by default.
- The command names execution surfaces and import decisions.
- `novel-forge validate` requires this document.
- Unit tests verify the command file contains the required safety and decision sections.

## Risks And Boundaries

- Do not vendor third-party command packs wholesale.
- Do not enable hooks just because they are common in Claude Code resource repositories.
- Do not create a public external-resource marketplace inside Novel Forge yet.
- Do not treat a popular repository as automatically safe.
- Keep all imported ideas subordinate to Novel Forge schemas, tests, Skills, and compliance rules.
