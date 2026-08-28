# Database

PostgreSQL 16 with pgvector is the sole production business authority. MinIO stores blobs and artifacts; object identity and business bindings remain in PostgreSQL.

## Migrations

The ordered migration chain lives under `src/novel_forge/storage/migrations/versions/`. `architecture/manifests/migration-manifest.yaml` is checked against the code, and startup readiness requires the database to be at the current head.

Apply migrations with:

```bash
NOVEL_FORGE_DATABASE_URL=postgresql://... novel-forge authority-migrate
```

Compose runs the same command as the one-shot `authority-migration` service before starting the API.

## Transaction boundary

`AuthorityUnitOfWork` scopes one transaction and repository set. A business mutation should validate expected version/state, write the authoritative state, bind output/evidence, and append event/outbox records in the same transaction. Provider and object-store network calls must not occur inside it.

Business coordinators use named Authority commands for writes and concrete read projections for joins. Direct `psycopg.connect` is restricted to migration, startup probes, frozen maintenance/import/export, and test infrastructure.

Book Opening recovery admission is one short PostgreSQL unit of work whenever
all required steps are database-local. That unit atomically revalidates the
immutable RecoveryAssessment, creates the RecoveryIntent, reserves any semantic
evaluation replacement generation, admits its Operation, advances the
generation head with CAS, admits the next RuntimeJob, transitions the
BookOpening from `FAILED` to `ADMITTED`, and writes the RecoveryReceipt,
StateEvents and outbox messages. Shared `*_in_uow` primitives are preferred over
nested commits or a database-only recovery saga. Provider execution and durable
result replay remain outside this admission transaction and continue through
the governed worker/ExternalEffect path.

## Concurrency and uncertainty

- Aggregate CAS/version checks reject stale state transitions.
- RuntimeJob and Attempt leases/fences reject stale workers.
- PostgreSQL constraints enforce relational BookOpening execution binding: the
  current generation references the exact RuntimeJob, Attempt, Lease and fencing
  identity. They do not pretend to enforce the temporal statement that a lease
  remains unexpired. Every runtime mutation rechecks expiry against transaction
  time, and the bounded execution-loss scan converges expired claims.
- Book Opening uses `AUTHORITY_CONVERGENCE_REQUIRED`; an expired lease is not
  eligible for generic RuntimeJob takeover.
- Terminal RuntimeJob, Attempt, Lease, Book Opening execution and Command
  Operation history is immutable. Replacement work is append-only and carries
  explicit predecessor/generation lineage.
- Recovery locks use one canonical order: BookOpening, Opening execution,
  RuntimeJob, Attempt, Lease, checkpoint head, evaluation-generation head, then
  ordered Operation/ExternalEffect evidence. Heartbeat paths do not acquire
  those locks in reverse order.
- SQLSTATE `40001` and `40P01` are retryable only inside an explicitly replay-safe transaction executor.
- Connection loss with uncertain commit outcome requires reconciliation.
- External effects are reconciled by receipt rather than repeated blindly.

Recovery classifies external work as `PROVEN_NO_EFFECT`, `PROVEN_SUCCESS`, or
`UNKNOWN_AMBIGUOUS` from authoritative Effect/Dispatch/Receipt evidence.
`UNKNOWN_AMBIGUOUS` fails closed and cannot be overridden by operator approval.
Assessment, loss convergence, checkpoint reconciliation and recovery admission
never call a Provider.

## Migration rollout

Recovery schema changes follow `expand -> migrate/reconcile -> verify ->
contract`. Expand migrations add compatible nullable bindings, append-only
generation/checkpoint/recovery ledgers, indexes, constraints and immutable
guards. Historical terminal rows are not rewritten to manufacture new truth.
Legacy semantic-evaluation operations are deterministically bootstrapped as
generation one; legacy Book Opening progress is reconstructed only by a formal
reconciliation Application from durable Authority evidence. Contract removal of
legacy candidate-once or resume behavior waits until upgraded-state and recovery
proof demonstrate that no supported deployment depends on it.

## Integration validation

`make authority-postgres-test` is intentionally non-skippable once the isolated PostgreSQL service is available. It applies the migration chain to a temporary database and executes the PostgreSQL integration suite. `make authority-query-plan-release` checks representative query plans separately.

Database unavailability is `ENVIRONMENT_BLOCKED`; it is not a reason to lower assertions or report fixture proof as integration proof.
