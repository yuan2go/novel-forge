# Authority Failure and Recovery Matrix

Evidence code SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

| Failure | Persisted state | Recovery | Duplicate prevention | Evidence |
|---|---|---|---|---|
| PostgreSQL unavailable at startup | no Legacy mutation | fail closed and retry readiness | no alternate authority | Compose and boundary tests |
| Migration interrupted | migration ledger/lock | rerun forward migration | migration registry and lock | clean migration tests |
| Legacy scan/import interrupted | run phase, checkpoint hash, item phase | resume persisted checkpoint | snapshot/record hash and stable identity | PostgreSQL migration fixture |
| Duplicate frozen record | existing migration item/AssetVersion | reconcile existing target | business identity plus content hash | PostgreSQL fixture |
| Same identity, different hash | quarantine evidence | operator conflict review | no overwrite/activation | PostgreSQL fixture |
| Missing/cross-project reference | quarantine source and reason | repair source mapping and rerun version | project-scoped validation | PostgreSQL fixture |
| Unclear Source rights | needs review/quarantine | rights decision before activation | qualification gate | PostgreSQL fixture |
| Oversized inline blob | object reference evidence/quarantine | import verified object key/hash/size | blob identity | PostgreSQL fixture |
| Worker exits with active lease | lease expires or is released | another Worker claims with higher fence | stale fence rejection | Compose fault injection |
| Serialization/deadlock | rolled-back transaction and retry metric | bounded idempotent retry | command idempotency key | PostgreSQL integration |
| Business/version conflict | terminal domain error | caller submits a new valid command | not classed transient | unit/integration |
| Provider may execute, DB receipt uncertain | `RECONCILIATION_REQUIRED` | provider query/callback reconciliation | no second execute request | PostgreSQL fault injection |
| Outbox delivery retry | pending/failed immutable identity | bounded re-claim/delivery | outbox idempotency key | Compose smoke |
| SIGTERM | Worker `DRAINING`/`DRAINED` health | stop claims, finish/checkpoint, close pool | lease/fence and UoW rollback | Compose shutdown check |
| PostgreSQL restart | broken pooled connections | pool reconnect and bounded command recovery | idempotency plus transaction rollback | PostgreSQL integration |

The matrix is engineering evidence with synthetic inputs. It does not prove a
real Provider, real publishing platform, production SLO, backup/PITR, or long-form
story quality.
