# Install Log

Date: 2026-07-04

## Source

| Field | Value |
| -- | -- |
| Catalog | `https://www.skills.sh/anthropics/skills` |
| Repository | `https://github.com/anthropics/skills` |
| Commit | `9d2f1ae187231d8199c64b5b762e1bdf2244733d` |
| Temporary audit clone | `/tmp/anthropic-skills-audit` |
| Install timestamp | `2026-07-04T05:13:12Z` |

## Installation Method

Official Claude Code plugin commands were reviewed in the Anthropic repository README:

```text
/plugin marketplace add anthropics/skills
/plugin install document-skills@anthropic-agent-skills
/plugin install example-skills@anthropic-agent-skills
```

This execution was running in a non-interactive Codex shell, not an interactive Claude Code slash-command session, so plugin installation could not be executed directly. The task allowed project-local vendor fallback. Adopted Skills were copied from the audited clone to `.claude/skills/<skill-name>/`.

## Installed Skills

| skill | source path | install path | result | notes |
| -- | -- | -- | -- | -- |
| `pdf` | `/tmp/anthropic-skills-audit/skills/pdf` | `.claude/skills/pdf` | installed | Source-available document Skill |
| `docx` | `/tmp/anthropic-skills-audit/skills/docx` | `.claude/skills/docx` | installed | Source-available document Skill |
| `xlsx` | `/tmp/anthropic-skills-audit/skills/xlsx` | `.claude/skills/xlsx` | installed | Source-available document Skill |
| `mcp-builder` | `/tmp/anthropic-skills-audit/skills/mcp-builder` | `.claude/skills/mcp-builder` | installed | Apache-style license, controlled network references |
| `claude-api` | `/tmp/anthropic-skills-audit/skills/claude-api` | `.claude/skills/claude-api` | installed | Large reference Skill, no runtime calls by default |
| `webapp-testing` | `/tmp/anthropic-skills-audit/skills/webapp-testing` | `.claude/skills/webapp-testing` | installed | Playwright local testing helper |
| `frontend-design` | `/tmp/anthropic-skills-audit/skills/frontend-design` | `.claude/skills/frontend-design` | installed | Instructions-only design guidance |
| `skill-creator` | `/tmp/anthropic-skills-audit/skills/skill-creator` | `.claude/skills/skill-creator` | installed | Controlled use; eval scripts can invoke Claude CLI |
| `doc-coauthoring` | `/tmp/anthropic-skills-audit/skills/doc-coauthoring` | `.claude/skills/doc-coauthoring` | installed | Instructions-only documentation workflow |

## Installed Size

| skill | size |
| -- | --: |
| `pdf` | 80K |
| `docx` | 1.2M |
| `xlsx` | 1.2M |
| `mcp-builder` | 144K |
| `claude-api` | 920K |
| `webapp-testing` | 32K |
| `frontend-design` | 24K |
| `skill-creator` | 248K |
| `doc-coauthoring` | 16K |

## Important Repository Boundary

`.claude/skills/` is ignored by `.gitignore` and is normally generated from root `skills/`. These vendor copies are local runtime additions for Claude Code adoption testing. Do not treat them as Novel Forge domain Skill source of truth. If the team wants versioned third-party vendor Skills, add an explicit policy before force-adding ignored files.
