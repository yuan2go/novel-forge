from __future__ import annotations

import unittest

from novel_forge.storage.database_runtime import (
    DatabaseReconciliationRequired,
    DatabaseRetryClass,
    DatabaseRuntimeConfig,
    TransactionExecutor,
    authority_role_instances_from_env,
    classify_sqlstate,
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

    def test_registry_identity_separates_service_and_pool_config_without_dsn(self) -> None:
        first = DatabaseRuntimeConfig(
            database_url="postgresql://secret:password@db.internal:5432/novel",
            role="book",
            service="book-worker-a",
            max_size=3,
        )
        second = DatabaseRuntimeConfig(
            database_url=first.database_url,
            role="book",
            service="book-worker-b",
            max_size=3,
        )
        resized = DatabaseRuntimeConfig(
            database_url=first.database_url,
            role="book",
            service="book-worker-a",
            max_size=4,
        )
        self.assertNotEqual(first.registry_key, second.registry_key)
        self.assertNotEqual(first.registry_key, resized.registry_key)
        rendered = repr(first.registry_key)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("password", rendered)
        self.assertNotIn(first.database_url, rendered)

    def test_database_identity_excludes_password_but_keeps_database_identity(self) -> None:
        first = DatabaseRuntimeConfig(
            database_url="postgresql://authority:secret-a@db.internal:5432/novel?sslmode=require",
            role="book",
        )
        rotated = DatabaseRuntimeConfig(
            database_url="postgresql://authority:secret-b@db.internal:5432/novel?sslmode=require",
            role="book",
        )
        other_database = DatabaseRuntimeConfig(
            database_url="postgresql://authority:secret-b@db.internal:5432/other?sslmode=require",
            role="book",
        )
        self.assertEqual(
            first.database_identity_fingerprint,
            rotated.database_identity_fingerprint,
        )
        self.assertNotEqual(first.registry_key, rotated.registry_key)
        self.assertNotEqual(
            first.database_identity_fingerprint,
            other_database.database_identity_fingerprint,
        )

    def test_connection_budget_fails_fast_when_capacity_is_exceeded(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "exceeds capacity"):
            validate_connection_budget(
                {"api": 10},
                postgres_max_connections=50,
                management_reserve=10,
                migration_reserve=2,
                emergency_reserve=5,
            )

    def test_authority_fleet_instance_budget_is_explicit_and_bounded(self) -> None:
        instances = authority_role_instances_from_env({})
        result = validate_connection_budget(
            instances,
            postgres_max_connections=100,
        )
        self.assertEqual(
            result["application_max_connections"],
            sum(result["allocations"].values()),
        )
        self.assertIn("book_followup", result["allocations"])
        self.assertEqual(result["application_capacity"], 83)
        self.assertTrue(result["within_budget"])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            authority_role_instances_from_env(
                {"NOVEL_FORGE_DB_CHAPTER_INSTANCES": "-1"}
            )

    def test_transient_retry_requires_idempotency_key(self) -> None:
        executor = TransactionExecutor(_Runtime())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "idempotency"):
            executor.execute("command", lambda _connection: None, retry_transient=True)

    def test_sqlstate_classification_is_fail_closed(self) -> None:
        self.assertIs(
            classify_sqlstate("40001"), DatabaseRetryClass.SAFE_RETRY
        )
        self.assertIs(
            classify_sqlstate("40P01"), DatabaseRetryClass.SAFE_RETRY
        )
        self.assertIs(
            classify_sqlstate("08007"),
            DatabaseRetryClass.RECONCILIATION_REQUIRED,
        )
        self.assertIs(
            classify_sqlstate("08P01"),
            DatabaseRetryClass.NEVER_AUTOMATIC_RETRY,
        )
        self.assertIs(
            classify_sqlstate("23505"),
            DatabaseRetryClass.NEVER_AUTOMATIC_RETRY,
        )

    def test_unknown_commit_outcome_emits_reconciliation_and_is_not_replayed(
        self,
    ) -> None:
        runtime = _Runtime()
        executor = TransactionExecutor(runtime)  # type: ignore[arg-type]
        calls = 0
        evidence: list[dict[str, str]] = []

        def ambiguous(_connection: object) -> None:
            nonlocal calls
            calls += 1
            raise _SqlStateError("08007")

        with self.assertRaises(DatabaseReconciliationRequired) as caught:
            executor.execute(
                "ambiguous-command",
                ambiguous,
                idempotency_key="stable-command",
                retry_transient=True,
                pure_database=True,
                idempotent=True,
                reconciliation_handler=evidence.append,
            )
        self.assertEqual(calls, 1)
        self.assertEqual(caught.exception.sqlstate, "08007")
        self.assertEqual(
            evidence[0]["classification"], "RECONCILIATION_REQUIRED"
        )

    def test_external_effect_cannot_be_wrapped_in_transaction_retry(self) -> None:
        executor = TransactionExecutor(_Runtime())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "external effects"):
            executor.execute(
                "provider-command",
                lambda _connection: None,
                idempotency_key="stable-command",
                retry_transient=True,
                pure_database=True,
                idempotent=True,
                external_effects=True,
            )

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
                pure_database=True,
                idempotent=True,
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
                pure_database=True,
                idempotent=True,
            )


if __name__ == "__main__":
    unittest.main()
