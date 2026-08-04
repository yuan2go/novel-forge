# Authority Compose Runbook

Evidence binding is recorded in `docs/reports/current-head-sha-baseline.json`.

## Default backend start

The default topology is the complete PostgreSQL Authority backend and contains no
Web or Legacy service.

```bash
make authority-build
make authority-up
make authority-logs
```

Readiness is exposed by the Authority API. It checks database connectivity,
migration head, operation definitions, object store, runtime-group registration,
provider mode and the database connection budget. An unconfigured real Provider
is reported as blocked/fixture-only; it is never promoted to real proof.

## Automated clean-volume smoke

```bash
make authority-smoke
```

The script uses a unique Compose project and empty volumes, migrates once,
requires all services ready, submits a synthetic command, checks Operation,
Attempt, AssetVersion, Audit and Outbox evidence, kills/restarts a Worker, proves
lease/fence recovery, drains all Workers, verifies no active or idle transaction
and removes its isolated resources.

This is specifically a Content Worker domain scenario. It is not seven-worker
domain E2E proof. Consult `docs/reports/authority-worker-fleet-e2e.md` before
making a fleet claim.

## Explicit Legacy compatibility

Legacy is never started by the default files. An operator must opt in:

```bash
make legacy-up
make legacy-logs
make legacy-down
```

Do not combine this profile with production Authority as a fallback or permanent
dual-write topology.

## Failure handling

- Migration failure: API and Workers remain unready; repair with a forward
  migration or restore the documented backup.
- PostgreSQL unavailable: fail closed; do not launch Legacy.
- Object store unavailable: readiness fails for workloads requiring blobs.
- Worker termination: lease expires or is released; a new fencing token prevents
  the old Worker from committing.
- Ambiguous Provider result: mark `RECONCILIATION_REQUIRED`; query by external
  idempotency identity before any further execute call.
- Shutdown: use `docker compose stop`; honor each service's grace period before
  forcing termination.

## Validation and probes

```bash
make authority-compose-config-check
make authority-test
make authority-postgres-test
make authority-query-plan-release
curl -fsS http://127.0.0.1:8000/runtime/database
curl -fsS http://127.0.0.1:8000/runtime/metrics
```

Query-plan release qualification creates representative data inside a rollback
transaction and uses `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` without disabling
sequential scans. It is a release job, not a fast unit test.
