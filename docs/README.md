# Novel Forge documentation

This documentation describes the runtime reachable from the current code. Architecture manifests, migrations, entry points, and tests take precedence over prose.

## Architecture

- [Canonical overall design](architecture/canonical-overall-design.md) — authoritative product progression and runtime boundaries
- [Overview](architecture/overview.md) — system shape, boundaries, and proof status
- [Runtime](architecture/runtime.md) — API, worker, operation, and recovery paths
- [Authority model](architecture/authority-model.md) — PostgreSQL ownership and mutation rules
- [Production execution](architecture/production-execution.md) — shared execution composition and provider boundary
- [Narrative state](architecture/narrative-state.md) — Canon, outcomes, StoryState, temporal query, and context
- [Source and knowledge](architecture/source-and-knowledge.md) — Source Import, Intelligence, and MKAOS

## Product

- [Novel production flow](product/novel-production-flow.md)
- [Capability map](product/capability-map.md)

## Operations

- [Local development](operations/local-development.md)
- [Configuration](operations/configuration.md)
- [Database](operations/database.md)
- [Workers](operations/workers.md)
- [Legacy migration](operations/legacy-migration.md)
- [Troubleshooting](operations/troubleshooting.md)

## Development

- [Repository structure](development/repository-structure.md)
- [Testing and evidence](development/testing.md)
- [Adding capabilities](development/adding-capabilities.md)
- [Coding guidelines](development/coding-guidelines.md)
- [Skills](development/skills.md)

## Decisions

`adr/` contains only decisions that still constrain the current system. It is
not a session log or a record of every implementation phase. Stale build plans,
exact-SHA qualification snapshots, and AI session summaries are intentionally
not retained as current documentation.

## Evidence vocabulary

Every maturity statement uses one of these levels:

| Level | Meaning |
|---|---|
| `implemented` | Code and schema exist. |
| `runtime-wired` | A current API, CLI, worker, or composition root reaches it. |
| `fixture-proven` | Deterministic local tests or the scripted provider exercise it. |
| `integration-proven` | A non-skippable test exercises real PostgreSQL or another named dependency. |
| `real-provider-proven` | A recorded run uses a real external model provider. |
| `production-verified` | Deployment evidence proves the complete operated system. |
| `not-proven` | The repository contains no sufficient evidence for the claim. |

Existence at one level does not imply any later level.
