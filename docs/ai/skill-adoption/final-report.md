# Claude Code Skill Adoption Final Report

Date: 2026-07-04

## 1. Goal

Assess Anthropic official Skills from `https://www.skills.sh/anthropics/skills` and `https://github.com/anthropics/skills`, decide which are valuable for Novel Forge v6 / Novel Operating System, install only useful Skills by official plugin or local vendor fallback, and document risks and trigger tests.

## 2. Project Current State

Novel Forge is a local-first AI novel production platform and early Novel Operating System runtime. It already has project-specific novel production Skills under root `skills/`, plus Agent runtime, Context Builder, MKAOS, RAG/source isolation, Agent Registry, Audit Log, Evaluation Center, pgvector PoC, ClickHouse offline analytics, Web Admin, and local deterministic tests.

External Skills should therefore cover generic file/tool workflows, not replace Novel Forge domain Skills.

## 3. Adopted Skills

| skill | why adopted |
| -- | -- |
| `pdf` | PDF analysis, table extraction, OCR planning, and report handling |
| `docx` | Word technical方案/report creation and review |
| `xlsx` | Spreadsheet cleaning, formulas, matrix/report data processing |
| `mcp-builder` | MCP server design and evaluation for Tool Gateway work |
| `claude-api` | Claude API / Agent architecture reference |
| `webapp-testing` | Local Web Admin Playwright testing and debugging |
| `frontend-design` | Better UI design choices for operational consoles |
| `skill-creator` | Create and evaluate project custom Skills |
| `doc-coauthoring` | Structured architecture/spec co-authoring workflow |

## 4. Rejected Skills

| skill | reason |
| -- | -- |
| `algorithmic-art` | No current Novel OS engineering need |
| `brand-guidelines` | Anthropic brand guidance conflicts with Novel Forge identity |
| `internal-comms` | Corporate comms templates are weak fit |
| `slack-gif-creator` | Slack GIF workflow irrelevant and adds media dependencies |

## 5. Candidate / Manual-Review Skills

| skill | decision | reason |
| -- | -- | -- |
| `pptx` | candidate | Useful if roadmap decks become frequent; not needed now |
| `theme-factory` | candidate | Possible report styling utility; may conflict with project UI identity |
| `canvas-design` | candidate | Has large font payload and visual-art scope; review when needed |
| `web-artifacts-builder` | manual-review | Installs global pnpm and many npm packages, includes `rm -rf dist bundle.html`, and creates separate artifact apps outside project architecture |

## 6. Installation Method

Official Claude Code plugin commands were reviewed but could not be executed from this non-interactive Codex shell. Vendor fallback was used:

```text
.claude/skills/pdf
.claude/skills/docx
.claude/skills/xlsx
.claude/skills/mcp-builder
.claude/skills/claude-api
.claude/skills/webapp-testing
.claude/skills/frontend-design
.claude/skills/skill-creator
.claude/skills/doc-coauthoring
```

Source commit: `anthropics/skills@9d2f1ae187231d8199c64b5b762e1bdf2244733d`.

## 7. Risk Points

- `pdf`, `docx`, and `xlsx` are source-available document Skills, not Apache-2.0 open-source Skills.
- `xlsx` recalc flow can write a LibreOffice macro under the user LibreOffice config; run only when spreadsheet recalculation is explicitly needed.
- `webapp-testing` helper uses `shell=True` to start local servers; use only trusted local commands.
- `mcp-builder` references external MCP SDK docs and can connect to MCP servers; keep external access opt-in.
- `claude-api` is Claude-specific and must not be applied to OpenAI/DeepSeek/provider-neutral code paths without an explicit decision.
- `skill-creator` eval scripts can call `claude -p` and create temporary `.claude/commands`; use controlled mode and local workspaces.
- `.claude/skills/` is ignored and normally generated from root `skills/`; these copies are local vendor runtime additions, not Novel Forge source-of-truth Skills.

## 8. Trigger Tests

Trigger tests are defined in `docs/ai/skill-adoption/trigger-test-cases.md` and cover:

- PDF document analysis;
- docx technical方案 generation;
- xlsx data processing;
- MCP Server design;
- Claude API / Agent architecture;
- Web Admin Playwright testing;
- frontend UI design改造;
- custom Skill creation.

Verification run in this pass:

```text
make sync-skills-dry-run
```

Result: command exited 0. It reported existing runtime drift for several root project Skills under `.claude/skills`; that drift was not fixed in this task because the task scope was third-party Skill adoption and the project treats root `skills/` as source of truth.

## 9. Custom Skill Plan

Recommended custom Skill priority:

1. `novel-os-quality-eval`
2. `rag-mcp-agent-architecture`
3. `ai-project-audit`
4. `codex-claude-workflow`
5. `java-industrial-code-review`
6. `ai-comment-governance`

Details are in `docs/ai/skill-adoption/custom-skill-backlog.md`.

## 10. Follow-Up Tasks For Codex / Claude Code

1. Decide whether third-party vendor Skills should remain ignored local runtime files or be force-added with a formal vendor policy.
2. Run prompt-level trigger tests in Claude Code after restarting/reloading runtime Skills.
3. Convert the highest-priority custom backlog item, `novel-os-quality-eval`, into a root `skills/` source-of-truth Skill.
4. Add a lightweight review script under `scripts/ai/` only if repeated Skill inventory or license checks become common.
5. Avoid installing `example-skills` wholesale; continue selective adoption.
