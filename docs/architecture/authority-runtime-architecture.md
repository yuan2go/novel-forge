# PostgreSQL Authority Runtime Architecture

Evidence binding is recorded in `docs/reports/current-head-sha-baseline.json`.

## Production boundary

```text
API / CLI
  -> Application Service
  -> PostgreSQL Command Kernel
  -> Operation / Saga / Attempt / Lease / Fence
  -> runtime-group Worker
  -> domain handler or planned ExternalEffect
  -> AssetVersion + Projection + Audit + Outbox
  -> query API
  -> recovery / reconciliation
```

PostgreSQL is authoritative for commands and projections. Object storage holds
large immutable payloads. Provider and publishing calls are ExternalEffects and
do not occur inside a database transaction. Legacy LocalStorage is absent from
this path and cannot be selected as a failure fallback.

## Default Compose plane

| Service | Runtime group / responsibility | Pool max | Health |
|---|---|---:|---|
| `postgresql` | authority database | 100 server connections | PostgreSQL health |
| `object-store` | hash-addressed blobs | n/a | MinIO live probe |
| `authority-migration` | one-shot migration with advisory lock | 1 reserve | successful exit |
| `authority-api` | API, callback admission, readiness | 8 | startup/liveness/readiness |
| `chapter-authority-worker` | Chapter plus effect dispatch | 4 | PostgreSQL heartbeat |
| `content-authority-worker` | typed content definitions | 4 | PostgreSQL heartbeat |
| `source-authority-worker` | Source and object-store effects | 3 | PostgreSQL heartbeat |
| `mkaos-authority-worker` | MKAOS operations | 3 | PostgreSQL heartbeat |
| `book-authority-worker` | Book saga coordination | 3 | PostgreSQL heartbeat |
| `outbox-worker` | idempotent Outbox delivery | 2 | PostgreSQL heartbeat |
| `maintenance-worker` | recovery/reconciliation/lease maintenance | 2 | PostgreSQL heartbeat |

Provider callback admission is hosted by the Authority API; Provider effect
dispatch is owned by the Chapter group. These are explicit merged duties, not
missing services. The seven Worker runtime groups are `chapter`, `content`,
`source`, `mkaos`, `book`, `outbox`, and `maintenance`.

## Startup and shutdown

Startup is ordered: PostgreSQL and object store healthy, one-shot migration
succeeds, API becomes ready, then Workers register and poll. Services do not race
to migrate the schema.

SIGTERM stops admission/polling, marks a Worker draining, completes or safely
checkpoints its current bounded transaction, releases or lets the lease expire,
returns connections, closes the process-local pool, and exits. API shutdown stops
new commands, lets active requests finish, rolls back incomplete transactions and
closes its pool.

## Evidence boundary

The current clean-volume Compose smoke proves fixture-based command execution,
outbox delivery, forced Worker restart, lease/fence recovery and graceful drain.
Provider readiness is `FIXTURE_ONLY`; this is not real-provider or production
proof.

The smoke's executed domain operation belongs to the Content Worker. The other
six runtime groups are started, heartbeat-checked and drained, while their
domain execution is covered by PostgreSQL integration tests rather than isolated
Compose scenarios. Therefore the fleet remains
`AUTHORITY_WORKER_FLEET_E2E_PARTIAL`.

## Migration boundary

The frozen importer first creates an archival AssetVersion and then, only for a
registry type with a real adapter, performs domain validation, explicit approval,
typed activation and domain reconciliation. Its two-pass reference table binds
Legacy keys to target items, AssetVersions and projections. All phase advancement
is expected-version guarded and resumable.

No source status or metadata flag is an Authority decision. Missing Source blob
receipts, unsafe rights, missing/cross-scope/ambiguous references and unknown
types fail closed.

## Operational observation

Worker health derives current operation/attempt/lease counts from PostgreSQL and
keeps batch completion distinct from operation completion. Database status is
`READY` only after successful database work, otherwise `DEGRADED` or
`UNAVAILABLE`. Runtime database metrics are available at `/runtime/database` and
`/runtime/metrics`.
