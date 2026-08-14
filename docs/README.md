# Novel Forge documentation

This documentation is intentionally small and role-based. Do not add session summaries, one-off implementation plans, exact-SHA reports, or duplicate architecture narratives to `docs/`.

## Documentation authority

Use the following precedence:

1. **Current implementation truth:** source code, migrations, architecture manifests, executable entry points, tests, and pinned-SHA runtime evidence.
2. **Canonical target architecture:** [Canonical overall design](architecture/canonical-overall-design.md).
3. **Current-runtime views:** architecture companion documents below. They explain the reachable implementation and must not silently promote target capabilities to current proof.
4. **ADRs:** durable decisions that still constrain implementation. A new ADR that changes the target architecture must update the Canonical overall design in the same change.
5. **Product, operations, and development guides:** derived views and procedures; they are not competing architecture sources.

When prose disagrees with executable evidence about what exists today, executable evidence wins. When implementation choices are being made about the intended final system, the Canonical overall design is the baseline unless a deliberate design change updates it.

## Canonical target

- [Canonical overall design](architecture/canonical-overall-design.md) — **the single target product/architecture baseline**: Human-AI Creative Studio, long-form narrative model, Domain/Authority boundaries, canonical runtimes, quality, reliability, qualification, gaps, and roadmap.

## Architecture — current runtime and boundaries

- [Overview](architecture/overview.md) — current system shape and proof status
- [Runtime](architecture/runtime.md) — API, worker, Operation, RuntimeJob, and recovery paths
- [Authority model](architecture/authority-model.md) — PostgreSQL ownership and mutation rules
- [Production execution](architecture/production-execution.md) — shared execution composition and provider boundary
- [Narrative state](architecture/narrative-state.md) — Canon, accepted events/outcomes, StoryState, temporal query, and context
- [Source and knowledge](architecture/source-and-knowledge.md) — Source Import, Source Intelligence, and MKAOS

## Product views

- [Novel production flow](product/novel-production-flow.md) — target human-to-publication business flow, with current proof boundaries called out
- [Capability map](product/capability-map.md) — capability/Agent/Skill terminology and proof matrix

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
- [Claude Code canonical implementation prompt](development/claude-code-canonical-implementation-prompt.md) — reusable implementation/qualification handoff; it does not define architecture independently of the Canonical overall design

## Decisions

`adr/` contains only decisions that still constrain the current system. It is not a session log or a record of every implementation phase. Stale build plans, exact-SHA qualification snapshots, and AI session summaries should not be retained as current documentation.

## Evidence vocabulary

The repository uses a specific proof ladder for capability maturity:

```text
MISSING
SKELETON
IMPLEMENTED
WIRED
FIXTURE_PROVEN
REAL_PROVIDER_PROVEN
LONGFORM_PROVEN
MULTIBOOK_PROVEN
PRODUCTION_PROVEN
```

Engineering reports should additionally distinguish these completion dimensions:

| Dimension | Meaning |
|---|---|
| `CODE_IMPLEMENTED` | Code/schema/contracts exist. |
| `CANONICAL_WIRED` | The capability is reachable through the current canonical production composition and owning Authority. |
| `TEST_EXECUTED` | Named tests actually ran against the reported SHA/environment. |
| `RUNTIME_PROVEN` | The relevant runtime/effects were exercised with recorded evidence. |
| `PRODUCTION_QUALIFIED` | Required qualification/admission and operated-environment evidence passed. |

A lower proof class or completion dimension never implies a higher one. Fixture success is not Real Provider, Long-form, Multi-book, or Production proof.
