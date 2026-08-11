# ADR 0004: Database Connection and Transaction Governance

Status: Accepted

## Context

Authority repositories and Workers previously opened direct psycopg connections,
which made connection capacity, session settings, leak detection, retries and
shutdown behavior inconsistent.

## Decision

All API, Worker, repository and UnitOfWork access uses a process-local
`DatabaseRuntime` backed by the official psycopg3 `ConnectionPool`. The
`ConnectionPoolRegistry` shares a runtime per DSN/role/service.

Normal `AuthorityUnitOfWork` transactions execute once. `TransactionExecutor`
is an explicit opt-in boundary only for pure-database, replay-idempotent work
with a stable idempotency key. It is not automatically installed around all
production commands.

Direct `psycopg.connect` is allowlisted only for schema migration, very early
startup/bootstrap probes, frozen import/export maintenance and PostgreSQL test
infrastructure. Architecture tests reject new business callers.

Every connection configures `application_name`, `statement_timeout=30s`,
`lock_timeout=5s`, `idle_in_transaction_session_timeout=30s`, `timezone=UTC` and
`search_path=public`. Transactions are short, rollback on failure and always
return the connection. Provider calls and object-store uploads occur outside the
transaction.

Retries are finite, exponential and jittered. Only SQLSTATE `40001` and `40P01`
are `SAFE_RETRY`, and only under the executor preconditions above. `08007` and
connection-loss/administrative-shutdown states with an uncertain outcome are
`RECONCILIATION_REQUIRED`; `08P01`, unknown states, business, version,
qualification and permission conflicts are never automatically retried. An
ExternalEffect that may already have executed is queried/reconciled and is not
executed again because a DB commit was uncertain.

Retry code catches `Exception`, not `BaseException`; process shutdown and
operator interrupts are not transformed into transaction attempts.

The runtime exposes pool size/available/in-use/waiting, acquire latency,
transaction duration/rollback, retry, timeout, deadlock, serialization, idle and
long-transaction counters. Logs carry the service and transaction context while
excluding DSNs, passwords, provider secrets and content payloads.

## Consequences

- Each service has a role-specific maximum and the Authority API fails fast if
  the fleet budget exceeds PostgreSQL capacity after reserves.
- Pool exhaustion fails within a configured bound instead of creating unlimited
  connections.
- Long network work cannot keep an Authority transaction idle.
- Pool shutdown and leak checks are part of Worker/API drain and integration
  tests.
- The API exposes `/runtime/database` and `/runtime/metrics` as a lightweight,
  credential-free snapshot suitable for later metrics adapters.
