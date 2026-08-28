# Workers

Workers are thin process entry points around governed schedulers. Their deployment identity, queue, execution class, health protocol, and recovery behavior are declared in `architecture/manifests/worker-manifest.yaml` and instantiated by `compose.yml`.

## Operating model

1. API admission freezes the operation and creates durable work.
2. A specialized worker claims a RuntimeJob with a bounded lease/fence.
3. The worker restores operation inputs from PostgreSQL, not process memory.
4. External effects execute through the shared production execution composition.
5. The worker records checkpoints, receipts, results, and heartbeat state.
6. A Domain Authority accepts or rejects the candidate output.

Book coordination is deliberately different: each worker tick chooses one deterministic production-critical supervisor action and persists it through a named Authority. It does not run a private Chapter scheduler, execute Reader/Recap providers, or write Book tables directly.

Book Followup is a separate deployment executor with runtime group `book_followup`. It first claims a fenced `BOOK_FOLLOWUP_ADMISSION` RuntimeJob derived from immutable Chapter acceptance evidence, then executes the admitted `reader_outcome.evaluate` or `longform.recap` Operation with the shared Attempt scheduler and Production Execution Composition. Its process, database role, heartbeat, and claim capacity are isolated from Book coordination, so a slow Provider or retry backlog cannot consume the Book worker's single progression lane.

## Health

The fleet publishes PostgreSQL-backed heartbeats. `/runtime/readiness` requires all configured runtime groups to be registered and healthy in addition to API dependency readiness. A live API with absent workers is degraded.

## Shutdown and recovery

Workers use finite polling, bounded leases, and graceful process shutdown.
Restart behavior is selected by the owning business Authority; a RuntimeJob is
an operational execution record and cannot decide business recovery by itself.
Stable idempotency, exact Attempt/Lease/fence binding, durable outputs and
receipts drive replay or reconciliation. Dead-letter and
reconciliation-required states remain visible to an operator.

Book Opening uses Authority convergence rather than ordinary expired-lease
takeover. A Book Opening `RUNNING` claim is valid only when its current execution
generation is bound to the exact RuntimeJob, Attempt, Lease and fencing token.
The database protects those relational bindings. Because lease validity changes
with time, claim, heartbeat, checkpoint, complete, fail, abort, loss and
recovery paths must also recheck `lease_expires_at` at transaction time.

When an Opening executor disappears or its lease/fence is lost, the generic
RuntimeJob claimer must not continue that job. The bounded maintenance/loss scan
calls the Book Opening Recovery Application, which rechecks the authoritative
state and converges the old Attempt, Lease, RuntimeJob, Opening execution and
Book Opening to immutable terminal `LOST`/`FAILED` evidence. Loss convergence
does not authorize another execution, create a RecoveryIntent, reconcile an
ambiguous ExternalEffect, or call a Provider.

Only a later, explicitly admitted `recover` command may create the
RecoveryIntent and the next execution generation. It must use a fresh immutable
assessment, preserve predecessor lineage, and fail closed on input, checkpoint,
generation, policy, Authority-version or ExternalEffect drift. The deprecated
legacy `BookOpening.resume()` behavior is not a recovery mutation surface; it
must be blocked or routed through this same assessment/recovery contract.

HTTP, worker, maintenance and any operator CLI adapter all call the same
Recovery Application. No adapter owns status-update SQL, force-recovery logic or
a Provider execution path. Recovery and reconciliation only commit durable
Authority work; any newly admitted semantic evaluation runs later through the
normal governed worker and ExternalEffect path.

## Commands

Compose is the canonical full-fleet launcher:

```bash
make authority-up
make authority-logs
make authority-down
```

Individual console scripts exist for source, import, MKAOS, Book, Book Followup, Agent, outbox, maintenance, and D0 provider workers. The Chapter and content workers are normally launched as Python modules by Compose. Prefer the manifest and Compose definitions over copied command lists in runbooks.
