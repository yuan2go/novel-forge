# Custom Skill Backlog

Date: 2026-07-04

The official Anthropic Skills cover generic file formats, MCP, Claude API, UI design, web testing, and skill creation. The following custom Skills should remain project-specific because they depend on Novel Forge architecture, source isolation, runtime policy, and acceptance gates.

| priority | custom skill | problem solved | trigger scenarios | input files | output files | acceptance standard | scripts needed |
| --: | -- | -- | -- | -- | -- | -- | -- |
| 1 | `novel-os-quality-eval` | Evaluate Novel OS artifacts with project-specific quality, trace, context, source isolation, ReviewIssue, Publish Gate, and feedback rules | "evaluate Novel OS quality", "review draft/review/publish gate", "run quality matrix" | `docs/`, `src/novel_forge/schemas/`, `tests/`, runtime fixture reports | `docs/reports/*quality*`, evaluation matrices, issue candidates | Must cite evidence paths and separate content quality from runtime compliance | Optional script to collect schema/test evidence |
| 2 | `rag-mcp-agent-architecture` | Review and design RAG, Context Builder, MCP, Tool Gateway, Agent Scheduler, and pgvector changes without bypassing source isolation | "design MCP server", "review RAG architecture", "agent context contract" | `docs/architecture/*`, `src/novel_forge/modules/context_builder/`, `tool_gateway/`, `pgvector_store/`, `agent_scheduler/` | Architecture review, risk register, test checklist | Must state source leakage risk, production fail-closed policy, and local-first constraints | Optional grep/report helper |
| 3 | `ai-project-audit` | Perform repo-wide AI/agent project audits with no business-code changes unless explicitly requested | "audit current project", "compare docs to code", "architecture review" | `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/`, `src/`, `tests/`, `web/` | `docs/reports/*audit*.md` | Must include matrix, evidence file paths, severity, recommendations | Useful script for inventory extraction |
| 4 | `codex-claude-workflow` | Standardize collaboration between Codex, Claude Code, local Skills, plugin/vendor installs, and runtime boundaries | "sync Claude Skills", "adopt plugin", "handoff to Claude Code" | `CLAUDE.md`, `AGENTS.md`, `docs/09-skills/`, `.claude/`, `scripts/sync_claude_skills.py` | Handoff packet, install log, sync report | Must respect root `skills/` source of truth and `.claude/skills` runtime boundary | Optional drift-check wrapper around existing script |
| 5 | `java-industrial-code-review` | Reusable audit workflow for Java industrial systems in historical user work | "review Java industrial service", "Spring Boot code audit", "JVM production risk" | `pom.xml`, `build.gradle`, `src/main/java`, `src/test/java`, deployment configs | Code review findings, risk matrix, test recommendations | Must prioritize production correctness, transactions, concurrency, observability | Optional static inventory script |
| 6 | `ai-comment-governance` | Govern AI-generated code comments and docs so comments explain invariants rather than restating code | "audit AI comments", "remove noisy comments", "comment governance" | Source files, docs, style guides | Comment policy report, patch plan | Must distinguish helpful invariants from noise and avoid deleting context blindly | Optional grep helper for suspicious comment patterns |

## Development Order

1. `novel-os-quality-eval`
2. `rag-mcp-agent-architecture`
3. `ai-project-audit`
4. `codex-claude-workflow`
5. `java-industrial-code-review`
6. `ai-comment-governance`

## Creation Guidance

Use the adopted `skill-creator` only in controlled mode:

- Draft each Skill under root `skills/` if it becomes part of Novel Forge source of truth.
- Keep `.claude/skills/` as runtime output unless a future vendor policy explicitly changes this.
- Add two to three trigger prompts and one validation method per Skill.
- Avoid bundling private source text, runtime assets, credentials, or copyrighted examples.
