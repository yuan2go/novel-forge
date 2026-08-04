# Database Retry and Reconciliation Matrix

Authority chooses the explicit opt-in strategy: normal `AuthorityUnitOfWork`
transactions execute once. `TransactionExecutor` may only be used by a caller
that declares a stable idempotency key, a pure-database boundary and idempotent
replay. It is not a transparent wrapper around all production transactions.

| Condition | Classification | Automatic action | Required proof |
|---|---|---|---|
| `40001` serialization failure | `SAFE_RETRY` | bounded retry allowed | pure DB, stable idempotency, no external effect |
| `40P01` deadlock | `SAFE_RETRY` | bounded retry allowed | same as `40001` |
| `08007` transaction resolution unknown | `RECONCILIATION_REQUIRED` | never replay immediately | query business result by idempotency identity |
| `08000`, `08003`, `08006`, `57P01` | `RECONCILIATION_REQUIRED` | stop and reconcile | commit outcome may be uncertain |
| `08P01` protocol violation | `NEVER_AUTOMATIC_RETRY` | fail | repair protocol/client defect |
| business, permission, schema, validation or expected-version conflict | `NEVER_AUTOMATIC_RETRY` | fail | caller must issue a new valid command |
| unknown SQLSTATE | `NEVER_AUTOMATIC_RETRY` | fail | classify explicitly before adoption |

`KeyboardInterrupt`, `SystemExit` and shutdown signals are not caught as
database work. Production retry boundaries catch `Exception`, not
`BaseException`.

## Side-effect boundary

The executor refuses work declared non-database, non-idempotent or without a
stable key. The following must never be repeated by a database retry:

- Provider execute;
- object-store put;
- publishing submit;
- webhook or callback side effect.

Ambiguous external effects remain `QUERY_OR_MANUAL_REQUIRED`. Maintenance may
surface and reconcile them but never converts uncertainty into another execute
call.

## Observability

`/runtime/database` and `/runtime/metrics` expose the process-local pool and
transaction snapshot: pool size/available/in-use/waiting, acquisition latency,
transaction duration/count, rollback, retry, timeout, deadlock, serialization
failure and long-transaction counts. DSNs, credentials and payloads are not
returned.
