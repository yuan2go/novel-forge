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
| Book Followup Authority | Admits and executes Reader/Recap sidecars from frozen acceptance snapshots without consuming Book coordination capacity. |
| Outbox | Delivers durable outbox effects and owns only delivery state. |
| Maintenance | Reconciliation and maintenance runtime group. |

The manifest is authoritative for worker identity, queue, health, and recovery class.

## Command path

An API router authenticates a principal, validates a typed request, and calls an Authority application. Admission freezes identity, scope, input assets, idempotency, definition version, trace, and causation. Atomic commands execute in one governed transaction; durable jobs create RuntimeJobs for workers; sagas coordinate child operations without copying child Attempt state.

Workers claim jobs with leases and fences. Provider and object-store work is represented by `ExternalEffect`; receipts are reconciled before retry. A lost lease or late result cannot commit over a newer fence. Successful handler output is materialized as a versioned asset and linked to the operation.

## Book and Chapter coordination

Book coordination is a saga entry (`book.production.coordinate`). The Book supervisor performs one production-critical business action per tick. Its reads use `PostgresBookProductionQuery`; mutations call `PostgresBookAuthority`, Planning Authority, ChapterGroup Authority, or PlanChange Authority. It does not execute direct SQL, own Chapter Attempts, or execute Reader/Recap provider work.

After Chapter acceptance atomically commits AcceptedOutcome, Story State, Canon, and the accepted cursor, a separate `book_followup` RuntimeJob group admits Reader Outcome and Longform Recap Operations from the immutable snapshot stored with that acceptance. The Book Followup worker uses the same Command Kernel Attempt/lease/fence and shared Production Execution Composition as other provider work, but has an isolated deployment process and database pool. Followup completion cannot mutate the Book cursor or active future plan; any Replan output remains an Authority-pending proposal.

Acceptance always returns the Book to `READY`, including the final Chapter. This lets any mandatory ChapterGroup production closure commit before the supervisor moves the Book to terminal `COMPLETED` and coordinates the root Saga.

`GET /product/production/book-authority/runs/{book_run_id}/progress` is a PostgreSQL read projection. It separates the last accepted narrative progress timestamp and production blocker from non-blocking sidecar admission/Operation backlog.

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
