# Runtime

## Process entry points

`novel-forge serve-api` constructs the full Authority API. `compose.yml` runs migrations first, then the API, then the specialized worker fleet. `novel-forge authority-migrate` is the schema migration command; `novel-forge-migrate` is a separate offline data-import program.

The current worker groups are:

| Worker | Responsibility |
|---|---|
| Agent Authority | Executes admitted Agent candidates through the governed execution plane. |
| Chapter Authority | Coordinates chapter saga jobs and recovery. |
| Content Authority | Materializes non-Chapter authority handler outputs. |
| Source Authority | Commits governed source transformations and deconstruction observations. |
| Source Import | Acquires, normalizes, chunks, and records source repository imports. |
| MKAOS Authority | Commits, approves, and packs abstract knowledge candidates. |
| Book Authority | Advances one deterministic Book coordination action per tick. |
| Outbox | Delivers durable outbox effects and owns only delivery state. |
| Maintenance | Reconciliation and maintenance runtime group. |

The manifest is authoritative for worker identity, queue, health, and recovery class.

## Command path

An API router authenticates a principal, validates a typed request, and calls an Authority application. Admission freezes identity, scope, input assets, idempotency, definition version, trace, and causation. Atomic commands execute in one governed transaction; durable jobs create RuntimeJobs for workers; sagas coordinate child operations without copying child Attempt state.

Workers claim jobs with leases and fences. Provider and object-store work is represented by `ExternalEffect`; receipts are reconciled before retry. A lost lease or late result cannot commit over a newer fence. Successful handler output is materialized as a versioned asset and linked to the operation.

## Book and Chapter coordination

Book coordination is a saga entry (`book.production.coordinate`). The Book supervisor performs one business action per tick. Its reads use `PostgresBookProductionQuery`; mutations call `PostgresBookAuthority`, Planning Authority, ChapterGroup Authority, Followup Authority, or PlanChange Authority. It does not execute direct SQL and does not own Chapter Attempts.

Chapter production is a separate 18-node saga (`chapter.slice.run`). Chapter-specific binders and policies turn frozen inputs into work orders. All provider and object-store execution comes from the shared production execution composition.

## Health and shutdown

- `/liveness` proves the API process is alive.
- `/readiness` requires current migrations, PostgreSQL, MinIO, a buildable provider route, operation definitions, and controlled-environment pack activation.
- `/runtime/readiness` additionally requires worker heartbeats.
- Shutdown closes provider sessions and all database runtimes.

`runtime_ready` only means the configured stack is operational. When the provider route is scripted, readiness is explicitly `fixture_only` and does not prove a real provider or production deployment.

## Recovery invariants

- Stable idempotency keys replay an existing admission instead of duplicating business work.
- CAS/version checks prevent stale business transitions.
- Attempt leases and fences prevent stale worker commits.
- ExternalEffect identity and receipts prevent blind re-execution after uncertain outcomes.
- Outbox records are committed with business state and delivered later.
- Supervisor checkpoints and trace/correlation identities survive process restarts.
