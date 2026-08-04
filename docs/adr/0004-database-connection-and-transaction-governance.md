# ADR 0004: Database Connection and Transaction Governance

Status: Accepted

Evidence code SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

## Context

Authority repositories and Workers previously opened direct psycopg connections,
which made connection capacity, session settings, leak detection, retries and
shutdown behavior inconsistent.

## Decision

All API, Worker, repository and UnitOfWork access uses a process-local
`DatabaseRuntime` backed by the official psycopg3 `ConnectionPool`. The
`ConnectionPoolRegistry` shares a runtime per DSN/role/service, and
`TransactionExecutor` provides the only bounded SQLSTATE retry boundary.

Direct `psycopg.connect` is allowlisted only for schema migration, very early
startup/bootstrap probes, frozen import/export maintenance and PostgreSQL test
infrastructure. Architecture tests reject new business callers.

Every connection configures `application_name`, `statement_timeout=30s`,
`lock_timeout=5s`, `idle_in_transaction_session_timeout=30s`, `timezone=UTC` and
`search_path=public`. Transactions are short, rollback on failure and always
return the connection. Provider calls and object-store uploads occur outside the
transaction.

Retries are finite, exponential and jittered and apply only to SQLSTATE `40001`,
`40P01`, class `08` connection failures represented in the allowlist, `57P01` and
`57P03`. Retried commands require an idempotency key. Business, version,
qualification and permission conflicts are not retried. An ExternalEffect that
may already have executed is reconciled and is not executed again because a DB
commit was uncertain.

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
