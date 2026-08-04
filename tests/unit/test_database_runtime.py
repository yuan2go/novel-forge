from __future__ import annotations

import unittest

from novel_forge.storage.database_runtime import (
    DatabaseRuntimeConfig,
    TransactionExecutor,
    validate_connection_budget,
)


class _SqlStateError(RuntimeError):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Transaction:
    def __init__(self, runtime: "_Runtime") -> None:
        self.runtime = runtime

    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _Metrics:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}

    def increment(self, name: str, value: float = 1.0) -> None:
        self.values[name] = self.values.get(name, 0) + value


class _Runtime:
    def __init__(self) -> None:
        self.metrics = _Metrics()
        self.config = type("Config", (), {"service": "test"})()

    def transaction(self, _name: str) -> _Transaction:
        return _Transaction(self)


class DatabaseRuntimeUnitTests(unittest.TestCase):
    def test_role_budget_and_session_defaults_are_bounded(self) -> None:
        config = DatabaseRuntimeConfig.from_env(
            "postgresql://example/test", role="chapter"
        )
        self.assertEqual(config.min_size, 0)
        self.assertEqual(config.max_size, 4)
        self.assertEqual(config.statement_timeout_ms, 30_000)
        self.assertEqual(config.lock_timeout_ms, 5_000)
        self.assertEqual(config.idle_in_transaction_session_timeout_ms, 30_000)

    def test_connection_budget_fails_fast_when_capacity_is_exceeded(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "exceeds capacity"):
            validate_connection_budget(
                {"api": 10},
                postgres_max_connections=50,
                management_reserve=10,
                migration_reserve=2,
                emergency_reserve=5,
            )

    def test_transient_retry_requires_idempotency_key(self) -> None:
        executor = TransactionExecutor(_Runtime())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "idempotency"):
            executor.execute("command", lambda _connection: None, retry_transient=True)

    def test_serialization_failure_retries_but_business_conflict_does_not(self) -> None:
        runtime = _Runtime()
        executor = TransactionExecutor(
            runtime, max_attempts=3, base_delay=0, max_delay=0, sleep=lambda _: None
        )  # type: ignore[arg-type]
        calls = 0

        def transient(_connection: object) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise _SqlStateError("40001")
            return "ok"

        self.assertEqual(
            executor.execute(
                "command",
                transient,
                idempotency_key="stable-command",
                retry_transient=True,
            ),
            "ok",
        )
        self.assertEqual(calls, 2)
        self.assertEqual(runtime.metrics.values["database_retry_count"], 1)

        with self.assertRaisesRegex(_SqlStateError, "23505"):
            executor.execute(
                "business-conflict",
                lambda _connection: (_ for _ in ()).throw(_SqlStateError("23505")),
                idempotency_key="stable-command",
                retry_transient=True,
            )


if __name__ == "__main__":
    unittest.main()
