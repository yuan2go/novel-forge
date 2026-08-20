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

Workers use finite polling, bounded leases, and graceful process shutdown. Restart does not create a new business operation: stable idempotency and existing RuntimeJob/Attempt records drive resume or reconciliation. Dead-letter and reconciliation-required states remain visible to an operator.

## Commands

Compose is the canonical full-fleet launcher:

```bash
make authority-up
make authority-logs
make authority-down
```

Individual console scripts exist for source, import, MKAOS, Book, Book Followup, Agent, outbox, maintenance, and D0 provider workers. The Chapter and content workers are normally launched as Python modules by Compose. Prefer the manifest and Compose definitions over copied command lists in runbooks.
