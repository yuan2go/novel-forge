# Skills System

## Module Goal

`skills/` stores stable, reusable, testable creative capabilities for Novel Forge v6 and the early Novel Operating System runtime.

Skill is not an Agent, Knowledge asset, Template, Tool, Runtime Policy, or Review Gate. A Skill defines the repeatable method, required inputs, output shape, quality bar, and forbidden behavior for a creative or review capability.

## Inputs

- `CLAUDE.md`
- `AGENTS.md`
- `docs/`
- `src/novel_forge/schemas/`
- `src/novel_forge/workflows/`
- Runtime assets under `.local/workspace/` or the configured `NOVEL_FORGE_ROOT`

## Outputs

- Reusable Skill instructions under `skills/*/SKILL.md`.
- Agent-Skill mapping under `docs/09-skills/agent-skill-map.md`.
- Validation coverage through `novel-forge validate`, `make test`, and OS runtime acceptance tests when a Skill participates in workflow or Agent execution.

## File Paths

```text
skills/
├── hot-novel-deconstruction/
├── anti-copy-abstraction/
├── character-design/
├── worldbuilding/
├── long-outline/
├── chapter-outline/
├── narrative-beat-design/
├── prose-generation/
├── quality-review/
├── reader-feedback/
├── project-planning/
├── multidisciplinary-knowledge/
├── topic-development/
├── material-curation/
├── analysis-to-asset-conversion/
├── hot-novel-business-deconstruction/
├── published-fiction-craft-analysis/
├── classic-literary-depth-analysis/
├── training-exercise/
├── mkaos-knowledge-asset-os/
├── context-builder-source-isolation/
├── review-issue-gate/
├── agent-loop-governance/
├── platform-strategy-os/
├── provider-runtime-policy/
├── canon-continuity-graph/
├── publish-release-gate-os/
├── skill-governance/
└── novel-os-engineering-audit/

docs/09-skills/
├── README.md
├── agent-skill-map.md
├── runtime-sync.md
├── usage-policy.md
├── external-resource-intake.md
└── github-knowledge-sources.md
```

Root `skills/` is the repository source of truth. `.claude/skills/` is generated runtime output and must not be hand-edited; if Claude Code runtime mapping is needed, sync it from root `skills/`.

## Execution Flow

1. Read the task, target asset type, and responsible Agent.
2. Select the required Skill from `docs/09-skills/agent-skill-map.md`.
3. Read `skills/<name>/SKILL.md`.
4. Check required inputs.
5. Follow the Skill workflow.
6. Write output to the schema-backed asset or documented target path.
7. Run validation or review gate before downstream use.

## Layering Rule

```text
CLAUDE.md = project rules
Agent = role and permissions
Skill = reusable capability
Knowledge = material and knowledge assets
Template = output format
Tool / MCP / Script = execution action
Review Gate = acceptance standard
```

Rules:

- Skills do not replace Agents.
- Skills do not replace the knowledge base.
- Skills do not store copyrighted content.
- Skills store stable methods, output rules, and quality standards.
- Agents call Skills to perform role-specific work, but workflow/Agent execution still runs through schema-backed artifacts, runtime policy, trace spans, cost ledgers, and gates when the output affects production state.
- Project Skills must be schema-backed, gate-aware, and source-isolated when their outputs affect production state.
- Every production-relevant Skill must include a Novel OS Runtime Contract covering schema output, Context Builder / Knowledge Pack / ReviewIssue / GateResult boundaries, source isolation, and traceability.
- Drafting must pass through `chapter-outline` and `quality-review`.
- Hot novel analysis must pass through `anti-copy-abstraction`.
- Reader feedback, project planning, multidisciplinary knowledge, topic development, material curation, analysis conversion, published-fiction analysis, classic-literary analysis, and training exercise are implemented Skills.
- MKAOS, Context Builder, ReviewIssue, Agent Loop, Provider Runtime, Canon Continuity, Publish Release Gate, Narrative Beat Design, Skill Governance, Platform Strategy, and Novel OS engineering audit now have dedicated Skills.

## Usage And License Policy

Use `docs/09-skills/usage-policy.md` as the detailed policy. The short version:

- Root project Skills are local-first internal project instructions.
- Runtime copies under `.claude/skills/` may include official or tool Skills with their own licenses and maintenance cadence.
- Do not vendor external Skill content into root `skills/` unless the license permits repository use and the source is recorded.
- External provider, network, browser, office-document, MCP, or platform operations must remain opt-in and must not bypass Runtime Policy.
- Skills do not authorize copying protected expression or moving raw sources into generation contexts.

## Acceptance

- `skills/` exists.
- 29 root project Skills exist.
- Every Skill has frontmatter with `name` and `description`.
- Every Skill has required sections for inputs, workflow, output, quality, forbidden behavior, and module relationships.
- Every project Skill that can influence production state contains a Novel OS Runtime Contract.
- `novel-forge validate` checks core Skills.
- `make sync-skills-dry-run` previews runtime mapping to `.claude/skills/`.
- `.claude/commands/evaluate-claude-resource.md` provides a read-only static review template before importing external Claude Code resources.
- `docs/09-skills/github-knowledge-sources.md` defines GitHub source intake rules for multidisciplinary knowledge handoffs.
- No Skill stores concrete copyrighted text or plot-reconstruction instructions.

## Risks And Boundaries

- Do not turn Skills into a parallel runtime or complex multi-agent platform.
- Do not store private source material in Skills.
- Do not let Skills bypass schema validation, workflow status, runtime policy, trace/cost recording, or review gates.
