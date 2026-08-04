# Current HEAD SHA Baseline

## Binding

| Field | Value |
|---|---|
| Repository | `https://github.com/yuan2go/novel-forge` |
| Branch | `feat/v7-content-intelligence-and-longform-proof` |
| Starting local/remote SHA | `a784a52f174cd13c53846eb59a17132a357c2c45` |
| Implementation SHA | `32e4fd1462509216273cf861c9c4f36a69eb15b4` |
| Full Python/Admin tested code SHA | `0e573fc0a02687ac54e1c1298f914f38dd533305` |
| PostgreSQL tested code SHA | `0e573fc0a02687ac54e1c1298f914f38dd533305` |
| Query/Compose tested implementation SHA | `32e4fd1462509216273cf861c9c4f36a69eb15b4` |
| Remote branch SHA | `a784a52f174cd13c53846eb59a17132a357c2c45` |
| Remote final-SHA CI | `NOT_PROVEN` |

The one-line difference between the full-suite SHA and implementation SHA adds
the missing default local PostgreSQL DSN to
`make authority-query-plan-release`; that exact command and the exact
implementation SHA then passed query-plan and Compose qualification. Evidence
documents are committed after these implementation tests and do not claim to
have tested their own not-yet-created commit. Final handoff records the later
evidence SHA and its final static/test gates.

## Runtime facts

| Field | Value |
|---|---|
| Python / Node | 3.12.2 / v26.3.1 |
| PostgreSQL | 16.14 |
| Docker / Compose | 24.0.7 / 2.23.3-desktop.2 |
| Migration head / count | `20260804_0058_authority_cutover_release_qualification` / 58 |
| Codec mappings | 59 total: 18 `DOMAIN_NATIVE`, 41 `ARCHIVAL_NATIVE` |
| Reachability | 15 entrypoints, 719 modules, 454 reachable files |
| Legacy blockers / unclassified | 0 / 0 |
| Inventory SHA-256 | `47183f59ed1cf80c236a5468711ce493eff101988d9dcb093edea03c979d62e9` |

## Test matrix

| Command | Passed | Failed | Skipped | Duration | Evidence level | Tested SHA |
|---|---:|---:|---:|---:|---|---|
| `make test` Python discovery | 1,457 | 0 | 9 | 710.401s | UNIT_PROVEN plus environment-free integration | `0e573fc` |
| `make test` Admin Node contract | 11 | 0 | 0 | 0.109s | UNIT_PROVEN | `0e573fc` |
| `make authority-postgres-test` | 152 | 0 | 0 | 88.597s | POSTGRESQL_INTEGRATION_PROVEN | `0e573fc` |
| `make authority-query-plan-release` | 5 plans | 0 | 0 | 14.462s | REPRESENTATIVE_PLANNER_PROVEN | `32e4fd1` |
| `make authority-smoke` | 1 Content scenario | 0 | 0 | 110.757s | COMPOSE_SMOKE / FAULT_INJECTION | `32e4fd1` |

The query qualification populated 100,000 rows each for Operation, Outbox,
AssetVersion and migration items, plus 10,000 Books. Without disabling
sequential scans, PostgreSQL selected the expected indexes for Worker poll,
Outbox claim, AssetVersion lookup, Book poll and migration resume; no plan
contained a Sort or rows removed by filter.

The Compose smoke migrated an empty database to 0058, reached Ready for the
11-service Authority plane, completed a synthetic Content operation, recovered
another after forced Worker restart at fencing token 2, rejected the stale token,
published Outbox records, drained all seven Workers, and ended with zero Worker
connections and zero active/idle-in-transaction sessions. This is not seven
independent domain-operation scenarios.

## Evidence status

```text
architecture_defined=true
unit_proven=true
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

Current strict verdicts:

```text
POSTGRESQL_AUTHORITY_BACKEND_HARDENING_PARTIAL
LEGACY_DOMAIN_MIGRATION_PARTIAL
AUTHORITY_WORKER_FLEET_E2E_PARTIAL
REMOTE_SHA_CI_NOT_PROVEN
```
