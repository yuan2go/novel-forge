# Database Retry and Reconciliation Matrix

| Failure / SQLSTATE | Authority outcome | Automatic action | Fence or recovery rule |
|---|---|---|---|
| serialization failure `40001` | transaction rolled back | bounded whole-transaction retry for explicitly retry-safe database work | new transaction; same business idempotency key |
| deadlock `40P01` | transaction rolled back | bounded retry with jitter | no side effect may escape the failed transaction |
| lock/query timeout `55P03` / `57014` | failed or retry-wait | policy-bounded retry | checkpoint retained where the execution plane supports it |
| connection loss before a known commit | retry-wait | reconnect and replay only idempotent database command | CAS/idempotency identity resolves duplicates |
| transaction resolution unknown `08007` | `RECONCILIATION_REQUIRED` | never immediately re-execute | query durable business result by identity |
| connection exception `08000`, `08003`, `08006`, `57P01` | `RECONCILIATION_REQUIRED` when commit may be ambiguous | stop and reconcile | fail closed until durable outcome is known |
| Operation Attempt lease expiry | Attempt `EXPIRED`, Operation recoverable | Maintenance Runtime Job schedules recovery | replacement claim requires higher fence |
| Runtime Job lease expiry | Attempt expired, Job retry/dead-letter | replacement Runtime Job claim | stale checkpoint/result rejected |
| Outbox lease expiry | delivery returns to claimable state | Outbox/Maintenance recovery | dedicated Outbox fencing remains authoritative |
| unknown ExternalEffect | query/manual-required | create explicit reconciliation work | no Provider success is inferred |

## Side-effect boundary

Provider calls and object-store transfers are never hidden inside a retried
database transaction. Operation, Outbox and ExternalEffect retain their business
authority. Runtime Job manages execution only; it cannot synthesize a business
success. Ambiguous external effects remain query/manual-required until an actual
adapter returns an authoritative receipt.

## Worker and fleet observation

Worker database status is derived as `UNKNOWN`, `READY`, `DEGRADED` or
`UNAVAILABLE` from the latest successful/failed database interaction and
heartbeat freshness. When PostgreSQL is unwritable, staleness produces
`UNAVAILABLE` without pretending the worker updated its own row.

Operational metrics aggregate pool size/use/waiting, transactions, rollbacks,
retries, timeouts, deadlocks, serialization failures, long transactions, Runtime
Job and Outbox backlog, unknown effects and stale workers across worker-written
projections. Pool reuse is keyed by database identity fingerprint, role, service
and pool-configuration fingerprint; full DSNs are excluded from logs and metrics.
