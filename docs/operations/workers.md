# Workers

Workers are thin process entry points around governed schedulers. Their deployment identity, queue, execution class, health protocol, and recovery behavior are declared in `architecture/manifests/worker-manifest.yaml` and instantiated by `compose.yml`.

## Operating model

1. API admission freezes the operation and creates durable work.
2. A specialized worker claims a RuntimeJob with a bounded lease/fence.
3. The worker restores operation inputs from PostgreSQL, not process memory.
4. External effects execute through the shared production execution composition.
5. The worker records checkpoints, receipts, results, and heartbeat state.
6. A Domain Authority accepts or rejects the candidate output.

Book coordination is deliberately different: each worker tick chooses one deterministic supervisor action and persists it through a named Authority. It does not run a private Chapter scheduler or write Book tables directly.

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

Individual console scripts exist for source, import, MKAOS, Book, Agent, outbox, maintenance, and D0 provider workers. The Chapter and content workers are normally launched as Python modules by Compose. Prefer the manifest and Compose definitions over copied command lists in runbooks.
