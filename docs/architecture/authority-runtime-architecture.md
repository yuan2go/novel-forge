# PostgreSQL Authority Runtime Architecture

Evidence code SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

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
