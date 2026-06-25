# Skills System

## Module Goal

`skills/` stores stable, reusable, testable creative capabilities for Novel Forge V5.

Skill is not an Agent, Knowledge asset, Template, Tool, or Review Gate. A Skill defines the repeatable method, required inputs, output shape, quality bar, and forbidden behavior for a creative or review capability.

## Inputs

- `CLAUDE.md`
- `AGENTS.md`
- `docs/`
- `src/novel_forge/schemas/`
- `src/novel_forge/workflows/`
- Assets under `data/`

## Outputs

- Reusable Skill instructions under `skills/*/SKILL.md`.
- Agent-Skill mapping under `docs/09-skills/agent-skill-map.md`.
- Validation coverage through `novel-forge validate` and `make test`.

## File Paths

```text
skills/
├── hot-novel-deconstruction/
├── anti-copy-abstraction/
├── character-design/
├── worldbuilding/
├── long-outline/
├── chapter-outline/
├── prose-generation/
├── quality-review/
├── reader-feedback/
├── project-planning/
├── multidisciplinary-knowledge/
├── topic-development/
├── material-curation/
└── training-exercise/

docs/09-skills/
├── README.md
├── agent-skill-map.md
├── runtime-sync.md
├── external-resource-intake.md
└── github-knowledge-sources.md
```

Root `skills/` is the repository source of truth. `.claude/skills/` is not used as source of truth; if Claude Code runtime mapping is needed later, map it from root `skills/`.

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
- Agents call Skills to perform role-specific work.
- Drafting must pass through `chapter-outline` and `quality-review`.
- Hot novel analysis must pass through `anti-copy-abstraction`.
- Reader feedback, project planning, multidisciplinary knowledge, topic development, material curation, and training exercise are implemented second-stage Skills.

## Acceptance

- `skills/` exists.
- 14 Skills exist.
- Every Skill has frontmatter with `name` and `description`.
- Every Skill has required sections for inputs, workflow, output, quality, forbidden behavior, and module relationships.
- `novel-forge validate` checks core Skills.
- `make sync-skills-dry-run` previews runtime mapping to `.claude/skills/`.
- `.claude/commands/evaluate-claude-resource.md` provides a read-only static review template before importing external Claude Code resources.
- `docs/09-skills/github-knowledge-sources.md` defines GitHub source intake rules for multidisciplinary knowledge handoffs.
- No Skill stores concrete copyrighted text or plot-reconstruction instructions.

## Risks And Boundaries

- Do not turn Skills into a complex multi-agent platform.
- Do not store private source material in Skills.
- Do not let Skills bypass schema validation, workflow status, or review gates.
