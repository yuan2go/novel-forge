# Skills System Architecture

## Module Goal

The Skills system adds a reusable capability layer to V5 without changing the CLI-first architecture.

V5 already has executable workflows, schemas, model adapters, storage, and evaluation rules. Skills define the repeatable human/AI creative methods that should guide those workflows.

## Inputs

- `CLAUDE.md`
- `AGENTS.md`
- `docs/09-skills/`
- `skills/*/SKILL.md`
- Schema-backed assets in `data/`

## Outputs

- Repository-level Skill source directory.
- Validated Skill documentation.
- Agent-to-Skill routing.

## File Paths

```text
skills/
docs/09-skills/
docs/01-architecture/skills-system.md
docs/02-workflows/skill-usage.md
scripts/sync_claude_skills.py
```

## Execution Flow

```text
Task
  -> Agent
  -> Skill
  -> Schema-backed input assets
  -> Workflow / model adapter / local rule engine
  -> Output asset
  -> Review gate
```

## Architecture Boundary

| Layer | Responsibility | Current Location |
|---|---|---|
| Project rules | global collaboration and safety | `CLAUDE.md` |
| Agent | role and permission boundary | `AGENTS.md` |
| Skill | reusable capability method | `skills/` |
| Knowledge | reusable content assets | `data/knowledge/`, `data/materials/` |
| Schema | data structure | `src/novel_forge/schemas/` |
| Workflow | executable pipeline | `src/novel_forge/workflows/` |
| Tool / Script | execution entry | `novel-forge`, `Makefile` |
| Review Gate | acceptance and quality | `quality-review`, `src/novel_forge/evaluation/` |

## Root Skills Vs `.claude/skills`

Root `skills/` is the source of truth because it is versioned, validated, and shared with the project.

`.claude/skills/` is generated runtime output, not source. Use `scripts/sync_claude_skills.py` or `make sync-skills` to map root Skills into Claude Code runtime when needed.

## Acceptance

- `novel-forge validate` checks core Skill files.
- `make sync-skills-dry-run` previews runtime mapping without writing.
- `make test` checks Skill structure.
- No external dependency is required.
- No protected text or concrete plot reconstruction appears in Skills.

## Risks And Boundaries

- Skills must remain concise and procedural.
- Skills must not replace schemas or workflows.
- Skills must not authorize final publishing.
- Skills must not bypass copyright and compliance boundaries.
