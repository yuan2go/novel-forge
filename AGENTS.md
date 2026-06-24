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

## Execution Rule

Every agent output must be traceable to input files, schema type, output path, and validation status.
