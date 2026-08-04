# Project Current State

Updated: 2026-08-04

Branch: `feat/v7-content-intelligence-and-longform-proof`

Tested implementation SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

Autonomous Novel OS remains the product target. The current engineering verdict
is narrower: the backend production boundary has completed its PostgreSQL
Authority cutover, while real Provider, real long-form and production proof have
not been performed.

```text
status=POSTGRESQL_AUTHORITY_BACKEND_CUTOVER_COMPLETE
architecture_defined=true
fixture_proven=true
postgresql_integration_proven=true
compose_smoke_proven=true
fault_injection_proven=true
real_provider_proven=false
longform_proven=false
multi_book_proven=false
production_verified=false
```

## Runtime fact

The standard development, production-like, CLI, API, Worker and Compose paths use
PostgreSQL Authority. If PostgreSQL is unavailable, they fail closed. Legacy
LocalStorage can only be selected by the explicit compatibility CLI/profile or
used as a frozen migration/import/export source. It is not a fallback and is not
dual-written.

The default backend topology contains PostgreSQL, object storage, a one-shot
migration service, Authority API and Chapter, Content, Source, MKAOS, Book,
Outbox and Maintenance Worker groups. It contains no Web or Legacy service.

## Authority fact table

| Capability | Current fact | Evidence boundary |
|---|---|---|
| Command Kernel | durable Operation/Saga/Attempt, idempotency, lease/fence, recovery | PostgreSQL integration and synthetic fault injection |
| Asset authority | immutable typed AssetVersion, qualification, activation, projection | PostgreSQL integration |
| Legacy migration | 58 typed codecs, checkpoints, quarantine and reconciliation | synthetic frozen snapshot; no real user data |
| Chapter/Content | registered Authority definitions and grouped Workers | fixture proof; no real prose quality proof |
| Project/Book/BookDesign/Planning | PostgreSQL commands and projections | typed integration fixtures |
| Source/MKAOS | Authority commands, object-store boundary and Workers | fixture/source protocol; no real connector proof |
| External effects | planned execution, receipt, callback, query/reconciliation | scripted/fake Provider only |
| Runtime governance | process-local psycopg3 pools, timeouts, bounded retry, metrics, drain | real PostgreSQL and Compose fault injection |
| Compose | clean-volume 11-service backend, migration once, readiness and recovery | local Compose smoke |
| Web | excluded from this task | no Web implementation or browser proof |

## Current limits

- Real Provider qualification is blocked without approved credentials and was not
  attempted.
- Real novel quality, long-form and multi-book behavior were not exercised.
- Public authentication, production secrets, backup/PITR, load/capacity/SLO and
  real publishing platform behavior remain unverified.
- The repository still contains explicit Legacy compatibility source. Architecture
  gates prove it is not backend-production reachable; source deletion is not
  claimed.
- The Admin/Web dependency and browser acceptance surface was outside this task.

## Current evidence

Start with current code and these exact-SHA reports:

- [`reports/current-head-sha-baseline.md`](reports/current-head-sha-baseline.md)
- [`reports/current-engineering-state.md`](reports/current-engineering-state.md)
- [`reports/legacy-postgresql-authority-migration-status.md`](reports/legacy-postgresql-authority-migration-status.md)
- [`architecture/authority-runtime-architecture.md`](architecture/authority-runtime-architecture.md)
- [`06-operations/authority-compose-runbook.md`](06-operations/authority-compose-runbook.md)
- [`adr/0004-database-connection-and-transaction-governance.md`](adr/0004-database-connection-and-transaction-governance.md)

Blueprints and historical reports describe their own target or historical SHA;
they do not supersede current code and exact-HEAD test evidence.
