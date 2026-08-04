# Authority Compose Runbook

Evidence code SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

## Default backend start

The default topology is the complete PostgreSQL Authority backend and contains no
Web or Legacy service.

```bash
docker compose -f compose.yml -f compose.override.yml up -d --build
docker compose -f compose.yml -f compose.override.yml ps
```

Readiness is exposed by the Authority API. It checks database connectivity,
migration head, operation definitions, object store, runtime-group registration,
provider mode and the database connection budget. An unconfigured real Provider
is reported as blocked/fixture-only; it is never promoted to real proof.

## Automated clean-volume smoke

```bash
PYTHONPATH=src .venv/bin/python scripts/verify_authority_compose.py
```

The script uses a unique Compose project and empty volumes, migrates once,
requires all services ready, submits a synthetic command, checks Operation,
Attempt, AssetVersion, Audit and Outbox evidence, kills/restarts a Worker, proves
lease/fence recovery, drains all Workers, verifies no active or idle transaction
and removes its isolated resources.

## Explicit Legacy compatibility

Legacy is never started by the default files. An operator must opt in:

```bash
docker compose -f compose.legacy.yml --profile legacy up legacy-api
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
