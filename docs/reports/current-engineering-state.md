# Current Engineering State

Updated: 2026-08-04

Branch: `feat/v7-content-intelligence-and-longform-proof`

Implementation SHA: `32e4fd1462509216273cf861c9c4f36a69eb15b4`

## Current verdict

The backend production boundary has completed the PostgreSQL Authority cutover.
Default development, API, CLI, Worker and Compose entrypoints use PostgreSQL and
fail closed. Legacy LocalStorage remains only behind an explicit compatibility
profile or frozen import/export tooling. It is not a fallback and no permanent
dual write is approved.

```text
status=POSTGRESQL_AUTHORITY_BACKEND_HARDENING_PARTIAL
architecture_defined=true
fixture_proven=true
postgresql_integration_proven=true
compose_smoke_proven=true
fault_injection_proven=true
domain_migration_core_types_proven=false
worker_fleet_e2e_proven=false
remote_sha_ci_proven=false
real_provider_proven=false
longform_proven=false
multi_book_proven=false
production_verified=false
backup_pitr_proven=false
```

This verdict is limited to the backend Authority and migration/runtime governance
requested in this slice. Web UI development, public authentication, real Provider
qualification, real story quality, long-form/multi-book operation, production
load/SLO and backup/PITR remain outside the proof boundary.

## Authority runtime

The default Compose plane contains PostgreSQL, object storage, a one-shot
migration job, Authority API and seven Worker runtime groups. Provider callback
admission is hosted by the API and effect dispatch by Chapter; no Web or Legacy
service is in the default topology.

The clean-volume smoke at the tested SHA proved migration head 0058, API and
Worker readiness, a synthetic Authority command, immutable output, Audit/Outbox,
forced Worker restart, expired lease recovery, fencing-token rejection, graceful
drain and zero remaining Worker connections or active/idle transactions.

The executed domain scenario is Content. Other workers have PostgreSQL
integration evidence, but not seven isolated Compose domain-operation scenarios.

## Legacy migration

The current generated inventory contains 450 rows, zero production blockers and
zero unclassified rows. The closed registry has 59 typed mappings: 18 core types
have real domain adapters and 41 remain explicitly archival. Unsafe scope,
references, rights, identity conflicts and blobs quarantine with source evidence.
Durable phases, expected-version CAS and hashes make resume/replay duplicate-safe.

Explicit compatibility source remains present and is guarded by the recursive
15-entrypoint reachability graph. Backend default cutover remains true, while
release qualification and optional code retirement are not claimed.

## Database governance

All Authority business access uses the shared psycopg3 pool runtime. Role budgets
allocate at most 29 application connections against capacity 83 after reserves on
a 100-connection PostgreSQL server. Readiness validates this against the actual
server value. Whole-transaction retry is opt-in for pure-database idempotent work;
uncertain outcomes reconcile and protocol violations do not retry. Metrics,
Worker drain and pool shutdown are covered by PostgreSQL integration tests.

Provider calls and object-store uploads do not hold database transactions. An
uncertain external execution enters reconciliation instead of being executed
again after a database retry.

## Current evidence entrypoints

- [`current-head-sha-baseline.md`](current-head-sha-baseline.md)
- [`legacy-postgresql-authority-migration-status.md`](legacy-postgresql-authority-migration-status.md)
- [`legacy-authority-migration-inventory.md`](legacy-authority-migration-inventory.md)
- [`native-migration-codec-registry.md`](native-migration-codec-registry.md)
- [`database-connection-budget.md`](database-connection-budget.md)
- [`authority-failure-and-recovery-matrix.md`](authority-failure-and-recovery-matrix.md)
- [`authority-cutover-hardening-findings.md`](authority-cutover-hardening-findings.md)
- [`domain-native-migration-matrix.md`](domain-native-migration-matrix.md)
- [`authority-worker-fleet-e2e.md`](authority-worker-fleet-e2e.md)
- [`database-retry-and-reconciliation-matrix.md`](database-retry-and-reconciliation-matrix.md)
- [`../architecture/authority-runtime-architecture.md`](../architecture/authority-runtime-architecture.md)
- [`../06-operations/authority-compose-runbook.md`](../06-operations/authority-compose-runbook.md)

Historical reports retain the evidence boundary of their own SHA and must not be
used as current-code proof.
