from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from psycopg_pool import PoolTimeout

from novel_forge.storage.database_runtime import (
    DatabaseRuntime,
    DatabaseRuntimeConfig,
    TransactionExecutor,
)
from tests.integration.authority_postgres_support import DATABASE_URL, connect


class DatabaseRuntimePostgresTests(unittest.TestCase):
    def _runtime(
        self,
        *,
        max_size: int = 4,
        statement_timeout_ms: int = 2_000,
        lock_timeout_ms: int = 500,
        idle_timeout_ms: int = 2_000,
    ) -> DatabaseRuntime:
        runtime = DatabaseRuntime(
            DatabaseRuntimeConfig(
                DATABASE_URL,
                role="test",
                service="novel-forge-db-runtime-integration",
                min_size=0,
                max_size=max_size,
                max_waiting=max_size,
                timeout=0.25,
                statement_timeout_ms=statement_timeout_ms,
                lock_timeout_ms=lock_timeout_ms,
                idle_in_transaction_session_timeout_ms=idle_timeout_ms,
            )
        )
        self.addCleanup(runtime.close)
        return runtime

    def test_connection_pool_reuses_connections_and_applies_session_policy(self) -> None:
        runtime = self._runtime(max_size=1)
        first = runtime.acquire()
        first_pid = first.info.backend_pid
        runtime.release(first)
        second = runtime.acquire()
        second_pid = second.info.backend_pid
        with second.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('application_name'), "
                "current_setting('statement_timeout'), "
                "current_setting('lock_timeout'), "
                "current_setting('idle_in_transaction_session_timeout'), "
                "current_setting('timezone'), current_setting('search_path')"
            )
            session = cursor.fetchone()
        runtime.release(second)
        self.assertEqual(first_pid, second_pid)
        self.assertEqual(session[0], "novel-forge-db-runtime-integration")
        self.assertEqual(session[1], "2s")
        self.assertEqual(session[2], "500ms")
        self.assertEqual(session[3], "2s")
        self.assertEqual(session[4], "UTC")
        self.assertEqual(session[5], "public")

    def test_pool_exhaustion_is_bounded_and_leaks_are_detected(self) -> None:
        runtime = self._runtime(max_size=1)
        connection = runtime.acquire()
        with self.assertRaisesRegex(RuntimeError, "connection leak"):
            runtime.assert_no_connection_leaks()
        with self.assertRaises(PoolTimeout):
            runtime.acquire(timeout=0.1)
        runtime.release(connection)
        runtime.assert_no_connection_leaks()

    def test_statement_and_idle_transaction_timeouts_fail_closed(self) -> None:
        runtime = self._runtime(
            max_size=1, statement_timeout_ms=100, idle_timeout_ms=150
        )
        with self.assertRaises(Exception) as statement_error:
            with runtime.transaction("statement-timeout") as connection:
                connection.execute("SELECT pg_sleep(0.3)")
        self.assertEqual(getattr(statement_error.exception, "sqlstate", ""), "57014")
        self.assertEqual(runtime.metrics.statement_timeout_count, 1)

        connection = runtime.acquire()
        connection.execute("SELECT 1")
        time.sleep(0.3)
        with self.assertRaises(Exception):
            connection.execute("SELECT 1")
        runtime.release(connection)

    def test_lock_timeout_does_not_wait_unbounded(self) -> None:
        runtime = self._runtime(max_size=2, lock_timeout_ms=100)
        with connect() as setup, setup.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS nf_database_runtime_lock_probe "
                "(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)"
            )
            cursor.execute(
                "INSERT INTO nf_database_runtime_lock_probe(id,value) VALUES (1,0) "
                "ON CONFLICT (id) DO UPDATE SET value=0"
            )
        holder = runtime.acquire()
        holder.execute(
            "UPDATE nf_database_runtime_lock_probe SET value=value+1 WHERE id=1"
        )
        try:
            with self.assertRaises(Exception) as lock_error:
                with runtime.transaction("lock-timeout") as contender:
                    contender.execute(
                        "UPDATE nf_database_runtime_lock_probe "
                        "SET value=value+1 WHERE id=1"
                    )
            self.assertEqual(getattr(lock_error.exception, "sqlstate", ""), "55P03")
        finally:
            holder.rollback()
            runtime.release(holder)

    def test_deadlock_and_serialization_failures_are_retried(self) -> None:
        runtime = self._runtime(max_size=4, lock_timeout_ms=2_000)
        with connect() as setup, setup.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS nf_database_runtime_retry_probe "
                "(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)"
            )
            cursor.execute(
                "INSERT INTO nf_database_runtime_retry_probe(id,value) VALUES (1,0),(2,0) "
                "ON CONFLICT (id) DO UPDATE SET value=0"
            )

        deadlock_barrier = threading.Barrier(2)
        attempts = {"a": 0, "b": 0}
        lock = threading.Lock()

        def deadlock_worker(name: str, first: int, second: int) -> None:
            executor = TransactionExecutor(
                runtime, max_attempts=3, base_delay=0.01, max_delay=0.02
            )

            def operation(connection: object) -> None:
                with lock:
                    attempts[name] += 1
                    current = attempts[name]
                connection.execute(  # type: ignore[attr-defined]
                    "UPDATE nf_database_runtime_retry_probe "
                    "SET value=value+1 WHERE id=%s",
                    [first],
                )
                if current == 1:
                    deadlock_barrier.wait(timeout=2)
                connection.execute(  # type: ignore[attr-defined]
                    "UPDATE nf_database_runtime_retry_probe "
                    "SET value=value+1 WHERE id=%s",
                    [second],
                )

            executor.execute(
                f"deadlock-{name}",
                operation,
                idempotency_key=f"deadlock-{name}",
                retry_transient=True,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(deadlock_worker, "a", 1, 2),
                executor.submit(deadlock_worker, "b", 2, 1),
            )
            for future in futures:
                future.result(timeout=5)
        self.assertGreaterEqual(runtime.metrics.deadlock_count, 1)
        self.assertGreaterEqual(runtime.metrics.database_retry_count, 1)

        serial_barrier = threading.Barrier(2)
        serial_attempts = {"a": 0, "b": 0}

        def serial_worker(name: str) -> None:
            executor = TransactionExecutor(
                runtime, max_attempts=3, base_delay=0.01, max_delay=0.02
            )

            def operation(connection: object) -> None:
                connection.execute(  # type: ignore[attr-defined]
                    "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
                )
                connection.execute(  # type: ignore[attr-defined]
                    "SELECT value FROM nf_database_runtime_retry_probe WHERE id=1"
                ).fetchone()
                with lock:
                    serial_attempts[name] += 1
                    current = serial_attempts[name]
                if current == 1:
                    serial_barrier.wait(timeout=2)
                connection.execute(  # type: ignore[attr-defined]
                    "UPDATE nf_database_runtime_retry_probe "
                    "SET value=value+1 WHERE id=1"
                )

            executor.execute(
                f"serialization-{name}",
                operation,
                idempotency_key=f"serialization-{name}",
                retry_transient=True,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(serial_worker, "a"),
                executor.submit(serial_worker, "b"),
            )
            for future in futures:
                future.result(timeout=5)
        self.assertGreaterEqual(runtime.metrics.serialization_failure_count, 1)

    def test_pool_discards_terminated_backend_and_recovers(self) -> None:
        runtime = self._runtime(max_size=1)
        connection = runtime.acquire()
        backend_pid = connection.info.backend_pid
        runtime.release(connection)
        with connect() as administrator:
            administrator.execute("SELECT pg_terminate_backend(%s)", [backend_pid])
        deadline = time.monotonic() + 3
        while True:
            try:
                with runtime.connection() as recovered:
                    value = recovered.execute("SELECT 1").fetchone()[0]
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        self.assertEqual(value, 1)
        runtime.assert_no_connection_leaks()


if __name__ == "__main__":
    unittest.main()
