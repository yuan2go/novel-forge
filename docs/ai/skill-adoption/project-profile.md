# Project Profile

Date: 2026-07-04

## Project Type

Novel Forge v6 is a local-first AI novel production platform and early Novel Operating System runtime. It is not a one-off prompt generator. The system uses schema-backed assets, workflow runs, Agent runs, Context Builder, MKAOS, ReviewIssue, Loop Kernel, Publish Gate, feedback backflow, Audit Log, Evaluation Center, and optional retrieval/analytics infrastructure.

## Main Languages And Stack

| Area | Current stack |
| -- | -- |
| Backend core | Python 3.11+, standard-library-first core, `unittest` |
| API | FastAPI optional dependency |
| Frontend | Next.js 16, React 19, TypeScript, lucide-react |
| Local runtime | `.local/workspace/` runtime asset boundary |
| Optional services | PostgreSQL, Redis/Celery, Qdrant, MinIO, Neo4j, pgvector, ClickHouse offline/online PoC |
| Tests | Python `unittest`, Node `node --test`, optional Playwright smoke |
| Skill runtime | Repository `skills/` as source of truth; `.claude/skills/` as Claude Code runtime copy |

## Existing AI Configuration

| File | Role |
| -- | -- |
| `CLAUDE.md` | Project rules for Claude Code, Codex, and coding agents |
| `AGENTS.md` | Agent classes, execution contract, copyright boundary, acceptance rules |
| `docs/09-skills/README.md` | Skill system definition and boundaries |
| `docs/09-skills/agent-skill-map.md` | Agent-to-Skill mapping |
| `docs/09-skills/runtime-sync.md` | Sync from root `skills/` to `.claude/skills/` |
| `.claude/commands/evaluate-claude-resource.md` | Existing read-only review command for external Claude resources |

Important boundary: root `skills/` is the project source of truth for Novel Forge domain Skills. `.claude/skills/` is normally generated runtime output. This adoption pass vendors selected third-party Anthropic Skills into `.claude/skills/` only because the task explicitly allowed project-local vendor fallback.

## Existing Test Commands

| Command | Purpose |
| -- | -- |
| `make test` | Python unittest discovery and web admin node tests |
| `make lint` | Python compileall |
| `make validate` | Novel Forge validation against `.local/workspace` |
| `make sync-skills-dry-run` | Preview repository Skill runtime sync |
| `make sync-skills` | Sync root Skills into `.claude/skills/` |
| `make check-skills` | Detect `.claude/skills` drift from root Skills |
| `npm --prefix web/admin test` | Admin architecture and route tests |
| `npm --prefix web/admin run lint` | TypeScript type check |

## Documentation Types

- Product and architecture docs: `docs/00-product/`, `docs/01-architecture/`, `docs/architecture/`.
- Workflow docs: `WORKFLOW.md`, `docs/02-workflows/`.
- Testing docs: `TESTING.md`, `docs/05-testing/`.
- Roadmap and audit reports: `docs/08-roadmap/`, `docs/reports/`.
- Skill docs: `docs/09-skills/`, root `skills/*/SKILL.md`.
- Novel OS design and phase reports: `docs/design/`, `docs/reports/phase-*`.

## Relevant Modules

| Capability | Evidence paths |
| -- | -- |
| Agent runtime | `src/novel_forge/agents/runtime.py`, `src/novel_forge/modules/agent_scheduler/`, `src/novel_forge/modules/agent_runs/` |
| Agent Registry | `src/novel_forge/modules/agent_registry/` |
| Context Builder | `src/novel_forge/modules/context_builder/service.py` |
| MKAOS / Knowledge | `src/novel_forge/modules/mkaos/service.py` |
| RAG / retrieval | `src/novel_forge/storage/rag_context.py`, `src/novel_forge/modules/pgvector_store/service.py` |
| MCP / Tool Gateway | `src/novel_forge/modules/tool_gateway/service.py` |
| Evaluation Center | `src/novel_forge/modules/evaluation_center/service.py` |
| Audit Log | `src/novel_forge/modules/audit_log/service.py` |
| Web admin | `web/admin/app/` |
| Playwright optional smoke | `web/admin/tests/playwright-smoke.test.mjs` |

## Skill Adoption Implication

The project already has strong domain-specific novel production Skills under root `skills/`. External Anthropic Skills should not replace these. The valuable gap is generic office-file handling, MCP design, Claude API reference, Web UI testing, frontend design critique, and custom Skill creation discipline.
