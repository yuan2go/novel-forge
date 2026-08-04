# Project Current State

Updated: 2026-08-04

Branch: `feat/v7-content-intelligence-and-longform-proof`

Implementation SHA: `8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`

Autonomous Novel OS remains the product target. The current engineering verdict
is narrower: the backend production boundary has completed its PostgreSQL
Authority cutover, while real Provider, real long-form and production proof have
not been performed.

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

transaction_command_atomicity_proven=true
inflight_command_recovery_semantics_proven=true
execution_classification_consistent=true
architecture_fitness_scope_hardened=true
asset_scope_database_constraints_proven=true
book_design_planning_convergence_adr_accepted=true
real_provider_auth_proven=false
provider_request_receipt_proven=false
provider_usage_proven=false
provider_cost_proven=false
provider_timeout_query_cancel_behavior_recorded=false
unknown_reconciliation_proven=false
provider_restart_recovery_proven=false
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
| Legacy migration | 59 mappings: 18 domain-native and 41 archival; durable phases, references, approval and reconciliation | synthetic frozen snapshot; no real user data |
| Chapter/Content | registered Authority definitions and grouped Workers | fixture proof; no real prose quality proof |
| Project/Book/BookDesign/Planning | PostgreSQL commands and projections | typed integration fixtures |
| Transaction Commands | admission, domain/business mutation, audit/outbox and Operation completion in one UoW; zero Attempt/Lease | precise PostgreSQL fault injection and replay |
| D0 qualification | Authority-persisted fixture harness, six scenario rows, object evidence and report AssetVersion | no real Provider call; all real Gates false |
| Source/MKAOS | Authority commands, object-store boundary and Workers | fixture/source protocol; no real connector proof |
| External effects | planned execution, receipt, callback, query/reconciliation | scripted/fake Provider only |
| Runtime governance | process-local psycopg3 pools, timeouts, bounded retry, metrics, drain | real PostgreSQL and Compose fault injection |
| Compose | clean-volume 11-service backend, migration once, Content execution and recovery | local smoke; not seven domain E2Es |
| Web | excluded from this task | no Web implementation or browser proof |

## Current limits

- Real Provider qualification is blocked without approved credentials and was not
  attempted.
- Real novel quality, long-form and multi-book behavior were not exercised.
- Public authentication, production secrets, backup/PITR, load/capacity/SLO and
  real publishing platform behavior remain unverified.
- The repository still contains explicit Legacy compatibility source. Architecture
  gates use a recursive 15-entrypoint graph to prove guarded reachability; source
  deletion is not claimed.
- MKAOS material/rule/template and remaining historical domains have no
  domain-native migration adapters yet.
- Final-SHA GitHub Actions have not run because this work has not been pushed.
- Admin production dependencies report zero known production vulnerabilities;
  unit tests, TypeScript/build and a Playwright smoke passed locally. This is not
  public-authentication or production-deployment proof.

## Current evidence

Start with current code and these exact-SHA reports:

- [`reports/current-head-sha-baseline.md`](reports/current-head-sha-baseline.md)
- [`reports/current-engineering-state.md`](reports/current-engineering-state.md)
- [`reports/legacy-postgresql-authority-migration-status.md`](reports/legacy-postgresql-authority-migration-status.md)
- [`architecture/authority-runtime-architecture.md`](architecture/authority-runtime-architecture.md)
- [`06-operations/authority-compose-runbook.md`](06-operations/authority-compose-runbook.md)
- [`adr/0004-database-connection-and-transaction-governance.md`](adr/0004-database-connection-and-transaction-governance.md)
- [`reports/track-b-execution-semantics-hardening.md`](reports/track-b-execution-semantics-hardening.md)
- [`reports/d0-authority-provider-qualification.md`](reports/d0-authority-provider-qualification.md)
- [`reports/track-c-convergence-review.md`](reports/track-c-convergence-review.md)
- [`adr/0003-book-design-and-planning-convergence.md`](adr/0003-book-design-and-planning-convergence.md)

Blueprints and historical reports describe their own target or historical SHA;
they do not supersede current code and exact-HEAD test evidence.
