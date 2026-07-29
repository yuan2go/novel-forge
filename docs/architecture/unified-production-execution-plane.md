# Unified Production Execution Plane Business Boundary

> Updated: 2026-07-29
> Status: implementation and PostgreSQL fixture integration proven; real Provider
> and sustained production verification are not proven.

## One production authority

PostgreSQL Authority is the only owner of production state. The production call
shape is:

```text
API / CLI / Scheduler / Agent
→ trusted Command port
→ Command Kernel admission
→ root Operation / Saga / child Operation
→ Attempt / Lease / Fence
→ business handler
→ ExternalEffect / ProductionExecutionGateway when uncertain work is needed
→ immutable AssetVersion + evidence + outbox
→ rebuildable Projection
```

The runtime, Provider, Codex process, workspace, local file, and Projection are
never authority. A successful backend exit is only execution evidence; it does
not imply schema acceptance, domain acceptance, AssetVersion creation, or
Authority commit.

## Business integration

| Boundary | Production command path | Authority output |
| --- | --- | --- |
| Chapter chain | `ChapterAuthorityApplication.admit` | Chapter Saga outputs, Canon transition, release evidence |
| Book coordination | `PostgresBookAuthority.start/submit_chapter` | durable Book checkpoint and Chapter Authority references |
| Reader Outcome | `reader_outcome.evaluate` | report, Reader State transition, issue set |
| Long-form checkpoint | `longform.recap` | recap, deviations, adjustment proposal, optional replan request |

Book Authority does not call the Legacy Chapter Bus and does not copy Chapter
Attempt state. It persists only the Chapter request, root Operation/Saga
references, status reference, and book checkpoint. Recovery queries Chapter
Authority before deciding whether to continue.

Reader Outcome uses the same PEP and `ExternalEffect` path as Chapter model
stages. Long-form Recap is deterministic in the V1 slice but still runs as a
fenced Authority Attempt and atomically materializes versioned outputs.

## Mutation boundary

Authority mutations live in repositories called by command/handler runtimes.
Application services and API/Scheduler adapters do not issue `INSERT`, `UPDATE`,
or `DELETE` against Authority tables. Projection views are read-only.

`LocalStorage` declares:

```text
authoritative=false
production_writable=false
rebuildable=true
```

Writes fail with `PRODUCTION_DIRECT_WRITE_FORBIDDEN:
AUTHORITY_COMMAND_REQUIRED` in `production`, `staging`, and
`production_like`. Legacy Chapter, Long-form Recap, and fixture Book Authority
entrypoints have independent fail-closed guards.

## Evidence boundary

```text
architecture_defined=true
fixture_proven=true
integration_proven=true
real_provider_proven=false
production_verified=false
```

The detailed PEP runtime contracts remain in
`docs/architecture/production-execution-plane.md`.
