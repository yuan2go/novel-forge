# Claude Code Runtime Skill Sync

## Module Goal

This document defines how repository Skills under `skills/` can be mapped into Claude Code runtime Skills without making `.claude/skills/` the source of truth.

## Inputs

- Repository source Skills: `skills/*/SKILL.md`
- Sync script: `scripts/sync_claude_skills.py`
- Optional runtime target: `.claude/skills/`

## Outputs

- A runtime copy of repository Skills for Claude Code.
- A dry-run report before writing.
- A repeatable command that can be tested without external dependencies.

## File Paths

```text
skills/                  # source of truth
.claude/skills/          # runtime copy, git-ignored
scripts/sync_claude_skills.py
```

## Execution Flow

Preview:

```bash
python3 scripts/sync_claude_skills.py --dry-run
make sync-skills-dry-run
```

Sync to default runtime path:

```bash
python3 scripts/sync_claude_skills.py
make sync-skills
```

Sync to a custom target:

```bash
python3 scripts/sync_claude_skills.py --target /path/to/skills
```

Check whether runtime Skills drifted from repository source:

```bash
python3 scripts/sync_claude_skills.py --check
make check-skills
```

## Rules

- Root `skills/` is the source of truth.
- `.claude/skills/` is generated runtime output and is ignored by Git.
- Do not hand-edit `.claude/skills/`; edit root `skills/` and sync when runtime copies need to change.
- Default sync copies or updates Skill directories but does not delete extra target Skills.
- Runtime-only official/tool Skills may coexist in `.claude/skills/`; review them through `docs/skills-audit-report.md` or a fresh audit before pruning.
- Use `--prune` only when you intentionally want to remove target Skill directories that no longer exist in the repository source.
- The script only syncs directories containing `SKILL.md`.
- `--check` exits non-zero when a runtime Skill is missing, modified, or extra target Skill directories would be pruned.

## Acceptance

- `make sync-skills-dry-run` lists planned operations and writes nothing.
- `make sync-skills` creates or updates `.claude/skills/`.
- `make check-skills` fails if `.claude/skills/` drifts from root `skills/`.
- `make validate` continues to validate source Skills under root `skills/`.

## Risks And Boundaries

- Do not edit `.claude/skills/` as the canonical version.
- Do not commit `.claude/skills/`.
- Do not use runtime sync to bypass project validation.
