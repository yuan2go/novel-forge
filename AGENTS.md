# AGENTS.md

## Purpose

Agents working on Novel Forge V5 must preserve the writing-system boundary: reference works are used for abstract structural learning, not copying.

## Agent Classes

| Agent | Input | Output | Permissions | Forbidden |
|---|---|---|---|---|
| Chief Editor Agent | product docs, status, risks | task priorities, acceptance decisions | update docs and plans | claim completion without tests |
| Engineering Agent | schemas, CLI, tests | code, tests, workflow glue | edit `src/`, `tests/`, docs | break schema compatibility silently |
| Draft Agent | chapter plans, style rules | draft chapter candidates | use model adapters only | copy protected text |
| Review Agent | drafts, rubric | review report, revision plan | produce critique assets | overwrite drafts directly |
| Knowledge Agent | cleaned text, decompositions | knowledge cards | abstract and tag knowledge | mix raw sources with generated assets |
| Material Agent | knowledge/decomposition assets | reusable material cards | build reusable asset library | copy story-specific characters/settings |
| Quality Agent | all outputs | validation and risk reports | run checks, record failures | suppress warnings |

## Agent-Skill Map

Agent is a role and permission boundary. Skill is a reusable capability. Use `docs/09-skills/agent-skill-map.md` for details.

| Agent | Recommended Skills |
|---|---|
| Chief Editor Agent | `quality-review`, `long-outline` |
| Knowledge Agent | `hot-novel-deconstruction`, `anti-copy-abstraction` |
| Material Agent | `hot-novel-deconstruction`, `anti-copy-abstraction`, `multidisciplinary-knowledge`, `long-outline` |
| Worldbuilding Agent | `worldbuilding` |
| Character Agent | `character-design` |
| Outline Agent | `long-outline`, `character-design`, `worldbuilding` |
| Chapter Plan Agent | `chapter-outline`, `quality-review` |
| Draft Agent | `prose-generation`, `chapter-outline` |
| Review Agent | `quality-review`, `anti-copy-abstraction` |
| Feedback Agent | `reader-feedback`, `quality-review` |

## Execution Rule

Every agent output must be traceable to input files, schema type, output path, and validation status.

Skills do not permit Agents to bypass schema validation, storage boundaries, copyright boundaries, or review gates.

Runtime copies under `.claude/skills/` must be generated from root `skills/` using `make sync-skills`; do not edit runtime copies as the source of truth.
