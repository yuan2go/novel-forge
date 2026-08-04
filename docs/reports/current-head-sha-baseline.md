# Current HEAD SHA Baseline

## Binding

| Field | Value |
|---|---|
| Repository | `https://github.com/yuan2go/novel-forge` |
| Branch | `feat/v7-content-intelligence-and-longform-proof` |
| Tested implementation SHA | `53b10b896bb934298d1ca11571aa01f24f00a812` |
| Subject | `feat: enforce authority fleet connection budget` |
| Generated at | `2026-08-04T04:53:35Z` |
| Working tree before test | clean |

The tested SHA is the clean implementation commit before this evidence-only
documentation commit. The final handoff records the later evidence-commit SHA;
this avoids claiming that a commit tested its own not-yet-created report.

## Runtime facts

| Field | Value |
|---|---|
| Python | 3.12.2 |
| Node | v26.3.1 |
| PostgreSQL | 16.14 |
| Docker | 24.0.7 |
| Docker Compose | 2.23.3-desktop.2 |
| Migration head / count | `20260804_0057_hot_query_governance` / 57 |
| Static operation catalog | 140 definitions |
| Authority module manifest | 17 modules |
| Worker manifest | 11 entries |
| Native migration codecs | 58 |
| Legacy inventory hash | `sha256:11aed5becfdc06f04773e9ba1c29405d9f22f982a8a1375e70f6360eefc75ae4` |
| Legacy blockers / unclassified | 0 / 0 |

The default Compose service manifest is PostgreSQL, object store, one-shot
migration, Authority API, and Chapter, Content, Source, MKAOS, Book, Outbox and
Maintenance Workers. Its tested connection allocation is 29 against application
capacity 83 on a 100-connection PostgreSQL server.

## Test matrix

| Command | Passed | Failed | Skipped | Duration | Evidence level |
|---|---:|---:|---:|---:|---|
| `make lint architecture-manifests-check architecture-fitness-check head-integrity-check check-skills` | 1 | 0 | 0 | 11.63s | CODE_DEFINED |
| Architecture discovery | 71 | 0 | 0 | 24.464s | CODE_DEFINED |
| Unit discovery | 1,191 | 0 | 0 | 408.124s | UNIT_PROVEN |
| Acceptance discovery | 2 | 0 | 0 | 0.350s | UNIT_PROVEN |
| Broad integration discovery | 250 | 0 | 9 | 250.444s | UNIT_PROVEN |
| `make postgres-authority-test` | 147 | 0 | 0 | 50.107s | POSTGRESQL_INTEGRATION_PROVEN |
| Clean-volume Authority Compose smoke | 1 | 0 | 0 | 91.756s | FAULT_INJECTION_PROVEN |
| Admin Node contract test | 11 | 0 | 0 | 0.32s | UNIT_PROVEN |

The Compose run migrated an empty database, reached Ready on all required
services, completed a normal synthetic operation, recovered another operation
after forced Worker restart with fencing token 2, rejected the stale token with
`ATTEMPT_LEASE_LOST`, published two Outbox records per operation, drained all
seven Workers, and ended with zero Worker database connections, active
transactions and idle-in-transaction sessions.

The nine broad-integration skips comprise seven environment-conditional
PostgreSQL cases that passed separately with an explicit DSN, one external
pgvector/ClickHouse case and one long-chain pressure case. Browser smoke was not
run because Web is excluded and was not started. No required test is recorded as
failing.

## Evidence status

```text
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

Final engineering status:
`POSTGRESQL_AUTHORITY_BACKEND_CUTOVER_COMPLETE`.
