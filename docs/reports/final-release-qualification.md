# PostgreSQL Authority Backend Final Release Qualification

## Source contract

The candidate is release-qualified only when the exact commit targeted by the
annotated tag satisfies every gate below. This document defines the gate; it does
not cache a changing CI run conclusion.

| Gate | Required exact-SHA evidence |
|---|---|
| Architecture | stable contract validation, deterministic Implementation Tree Identity, zero forbidden reachability |
| Tests | lint/architecture, unit/acceptance, PostgreSQL integration and Web jobs successful |
| Migration | clean 0001→0066 replay, schema integration and 18 core Domain flows |
| Query plan | representative planner qualification with sequential scan enabled |
| Compose | default Authority topology Content smoke and recovery |
| Worker Fleet | all seven independent recovery scenarios and PASS summary |
| Image | BuildKit content-addressed Docker digest |
| Environment | secret-free runner/toolchain/PostgreSQL-image metadata |
| Aggregate | `release-qualification-<SHA>.json` verifies every required artifact class |

The qualification sequence is immutable: push candidate, run all Required Jobs,
obtain artifacts, then create an annotated tag on the same green SHA. No evidence
commit follows the tag.

## Eligible claims after the gate passes

```text
architecture_defined=true
unit_proven=true
postgresql_integration_proven=true
compose_smoke_proven=true
fault_injection_proven=true
domain_migration_core_types_proven=true
worker_fleet_e2e_proven=true
remote_sha_ci_proven=true
postgresql_authority_backend_release_qualified=true
```

## Permanent non-claims for this release

```text
real_provider_proven=false
longform_proven=false
multi_book_proven=false
production_verified=false
backup_pitr_proven=false
autonomous_book_loop_proven=false
```

The annotated tag message records final SHA, CI run id, migration head, artifact
names, evidence grade and these non-claims. GitHub Actions and the tag are the
remote evidence authority.
