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

## Concurrency and uncertainty

- Aggregate CAS/version checks reject stale state transitions.
- RuntimeJob and Attempt leases/fences reject stale workers.
- SQLSTATE `40001` and `40P01` are retryable only inside an explicitly replay-safe transaction executor.
- Connection loss with uncertain commit outcome requires reconciliation.
- External effects are reconciled by receipt rather than repeated blindly.

## Integration validation

`make authority-postgres-test` is intentionally non-skippable once the isolated PostgreSQL service is available. It applies the migration chain to a temporary database and executes the PostgreSQL integration suite. `make authority-query-plan-release` checks representative query plans separately.

Database unavailability is `ENVIRONMENT_BLOCKED`; it is not a reason to lower assertions or report fixture proof as integration proof.
