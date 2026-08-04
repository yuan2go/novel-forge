"""Bounded PostgreSQL connection, transaction, retry, and health runtime.

Authority services share this entry point. Migration and bootstrap probes remain
explicit exceptions because they must work before the application pool exists.
"""
from __future__ import annotations

import logging
import os
import random
import re
import hashlib
import json
import shlex
import threading
import time
from urllib.parse import parse_qsl, unquote, urlsplit
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any, Callable, Iterator, Mapping, TypeVar


LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class DatabaseRetryClass(StrEnum):
    SAFE_RETRY = "SAFE_RETRY"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    NEVER_AUTOMATIC_RETRY = "NEVER_AUTOMATIC_RETRY"


SAFE_RETRY_SQLSTATES = frozenset({"40001", "40P01"})
RECONCILIATION_REQUIRED_SQLSTATES = frozenset(
    {
        "08000",  # connection_exception after transaction start is ambiguous
        "08003",  # connection_does_not_exist
        "08006",  # connection_failure
        "08007",  # transaction_resolution_unknown
        "57P01",  # admin_shutdown can interrupt commit acknowledgement
    }
)
# Compatibility export now means exactly the SQLSTATEs that are safe for an
# explicitly idempotent, pure-database transaction replay.
TRANSIENT_SQLSTATES = SAFE_RETRY_SQLSTATES


def classify_sqlstate(sqlstate: str) -> DatabaseRetryClass:
    normalized = str(sqlstate or "").upper()
    if normalized in SAFE_RETRY_SQLSTATES:
        return DatabaseRetryClass.SAFE_RETRY
    if normalized in RECONCILIATION_REQUIRED_SQLSTATES:
        return DatabaseRetryClass.RECONCILIATION_REQUIRED
    return DatabaseRetryClass.NEVER_AUTOMATIC_RETRY


class DatabaseReconciliationRequired(RuntimeError):
    def __init__(
        self, *, transaction_name: str, idempotency_key: str, sqlstate: str
    ) -> None:
        super().__init__(
            f"database outcome requires reconciliation: {transaction_name} "
            f"sqlstate={sqlstate or 'unknown'}"
        )
        self.transaction_name = transaction_name
        self.idempotency_key = idempotency_key
        self.sqlstate = sqlstate


DEFAULT_ROLE_BUDGETS: dict[str, tuple[int, int]] = {
    "api": (1, 8),
    "chapter": (0, 4),
    "content": (0, 4),
    "source": (0, 3),
    "mkaos": (0, 3),
    "book": (0, 3),
    "callback": (0, 2),
    "dispatch": (0, 3),
    "outbox": (0, 2),
    "maintenance": (0, 2),
    "migration": (0, 1),
    "test": (0, 4),
}

DEFAULT_AUTHORITY_ROLE_INSTANCES: dict[str, int] = {
    "api": 1,
    "chapter": 1,
    "content": 1,
    "source": 1,
    "mkaos": 1,
    "book": 1,
    "outbox": 1,
    "maintenance": 1,
}

_SECRET_DSN_KEYS = frozenset(
    {"password", "passfile", "sslpassword", "sslkey", "sslcert"}
)


def _password_free_database_identity(database_url: str) -> dict[str, Any]:
    """Return connection identity without reusable authentication material."""
    if "://" in database_url:
        parsed = urlsplit(database_url)
        query = sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _SECRET_DSN_KEYS
        )
        return {
            "scheme": parsed.scheme.lower(),
            "host": (parsed.hostname or "").lower(),
            "port": parsed.port,
            "database": unquote(parsed.path.lstrip("/")),
            "user": unquote(parsed.username or ""),
            "query": query,
        }
    fields: dict[str, str] = {}
    for token in shlex.split(database_url):
        key, separator, value = token.partition("=")
        if separator and key.lower() not in _SECRET_DSN_KEYS:
            fields[key.lower()] = value
    return {"keyword_dsn": dict(sorted(fields.items()))}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw is None or raw == "" else int(raw)


def _milliseconds(value: str) -> int:
    raw = value.strip().lower()
    if raw.endswith("ms"):
        return int(raw[:-2])
    if raw.endswith("s"):
        return int(float(raw[:-1]) * 1000)
    return int(raw)


@dataclass(frozen=True, slots=True)
class DatabaseRuntimeConfig:
    database_url: str
    role: str = "api"
    service: str = "novel-forge"
    min_size: int = 1
    max_size: int = 8
    max_waiting: int = 16
    timeout: float = 5.0
    max_lifetime: float = 3600.0
    max_idle: float = 300.0
    reconnect_timeout: float = 30.0
    num_workers: int = 3
    statement_timeout_ms: int = 30_000
    lock_timeout_ms: int = 5_000
    idle_in_transaction_session_timeout_ms: int = 30_000
    timezone: str = "UTC"
    search_path: str = "public"
    long_transaction_ms: int = 5_000

    def __post_init__(self) -> None:
        if not self.database_url:
            raise ValueError("PostgreSQL database_url is required")
        if self.min_size < 0 or self.max_size <= 0 or self.min_size > self.max_size:
            raise ValueError("database pool size is invalid")
        if self.max_waiting <= 0 or self.timeout <= 0:
            raise ValueError("database pool waiting bounds must be positive")
        if self.role not in DEFAULT_ROLE_BUDGETS:
            raise ValueError(f"unsupported database role: {self.role}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(,[A-Za-z_][A-Za-z0-9_]*)*", self.search_path):
            raise ValueError("database search_path contains an unsafe identifier")

    @property
    def database_identity_fingerprint(self) -> str:
        identity = _password_free_database_identity(self.database_url)
        return "sha256:" + hashlib.sha256(
            json.dumps(
                identity,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()

    @property
    def pool_config_fingerprint(self) -> str:
        payload = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name not in {"database_url", "role", "service"}
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @property
    def registry_key(self) -> tuple[str, str, str, str]:
        return (
            self.database_identity_fingerprint,
            self.role,
            self.service,
            self.pool_config_fingerprint,
        )

    @classmethod
    def from_env(
        cls, database_url: str, *, role: str | None = None
    ) -> "DatabaseRuntimeConfig":
        resolved_role = str(
            role or os.environ.get("NOVEL_FORGE_DATABASE_ROLE") or "api"
        ).strip().lower()
        default_min, default_max = DEFAULT_ROLE_BUDGETS.get(resolved_role, (-1, -1))
        if default_min < 0:
            raise ValueError(f"unsupported database role: {resolved_role}")
        prefix = f"NOVEL_FORGE_DB_{resolved_role.upper()}_POOL_"
        return cls(
            database_url=database_url,
            role=resolved_role,
            service=str(
                os.environ.get("NOVEL_FORGE_SERVICE_NAME")
                or f"novel-forge-{resolved_role}"
            ).strip(),
            min_size=_env_int(f"{prefix}MIN_SIZE", default_min),
            max_size=_env_int(f"{prefix}MAX_SIZE", default_max),
            max_waiting=_env_int(f"{prefix}MAX_WAITING", default_max * 2),
            timeout=float(os.environ.get("NOVEL_FORGE_DB_POOL_TIMEOUT") or "5"),
            max_lifetime=float(
                os.environ.get("NOVEL_FORGE_DB_POOL_MAX_LIFETIME") or "3600"
            ),
            max_idle=float(os.environ.get("NOVEL_FORGE_DB_POOL_MAX_IDLE") or "300"),
            reconnect_timeout=float(
                os.environ.get("NOVEL_FORGE_DB_POOL_RECONNECT_TIMEOUT") or "30"
            ),
            num_workers=_env_int("NOVEL_FORGE_DB_POOL_WORKERS", 3),
            statement_timeout_ms=_milliseconds(
                os.environ.get("NOVEL_FORGE_DB_STATEMENT_TIMEOUT") or "30000"
            ),
            lock_timeout_ms=_milliseconds(
                os.environ.get("NOVEL_FORGE_DB_LOCK_TIMEOUT") or "5000"
            ),
            idle_in_transaction_session_timeout_ms=_milliseconds(
                os.environ.get("NOVEL_FORGE_DB_IDLE_TRANSACTION_TIMEOUT") or "30000"
            ),
            timezone=str(os.environ.get("NOVEL_FORGE_DB_TIMEZONE") or "UTC"),
            search_path=str(os.environ.get("NOVEL_FORGE_DB_SEARCH_PATH") or "public"),
            long_transaction_ms=_env_int("NOVEL_FORGE_DB_LONG_TRANSACTION_MS", 5000),
        )


@dataclass(slots=True)
class DatabaseRuntimeMetrics:
    connection_acquire_count: int = 0
    connection_acquire_latency_ms: float = 0.0
    transaction_count: int = 0
    transaction_duration_ms: float = 0.0
    transaction_rollback_count: int = 0
    database_retry_count: int = 0
    statement_timeout_count: int = 0
    deadlock_count: int = 0
    serialization_failure_count: int = 0
    idle_in_transaction_detected: int = 0
    long_transaction_count: int = 0
    query_failure_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def increment(self, field_name: str, value: float = 1.0) -> None:
        with self._lock:
            setattr(self, field_name, getattr(self, field_name) + value)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            values = {
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "_lock"
            }
            values.update(
                {
                    "rollback_count": values["transaction_rollback_count"],
                    "retry_count": values["database_retry_count"],
                    "timeout_count": values["statement_timeout_count"],
                }
            )
            return values


class DatabaseRuntime:
    """One process-local pool and the observable transaction boundary around it."""

    def __init__(self, config: DatabaseRuntimeConfig) -> None:
        try:
            from psycopg_pool import ConnectionPool
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError(
                "PostgreSQL runtime requires the optional dependency: psycopg_pool"
            ) from exc
        self.config = config
        self.metrics = DatabaseRuntimeMetrics()
        self._checked_out = 0
        self._checkout_lock = threading.Lock()
        self._pool = ConnectionPool(
            conninfo=config.database_url,
            min_size=config.min_size,
            max_size=config.max_size,
            max_waiting=config.max_waiting,
            timeout=config.timeout,
            max_lifetime=config.max_lifetime,
            max_idle=config.max_idle,
            reconnect_timeout=config.reconnect_timeout,
            num_workers=config.num_workers,
            kwargs={"autocommit": False},
            configure=self._configure,
            reset=self._reset,
            check=ConnectionPool.check_connection,
            open=False,
            name=f"novel-forge-{config.role}",
        )
        self._pool.open(wait=config.min_size > 0, timeout=config.timeout)

    def _configure(self, connection: Any) -> None:
        values = {
            "application_name": self.config.service,
            "statement_timeout": str(self.config.statement_timeout_ms),
            "lock_timeout": str(self.config.lock_timeout_ms),
            "idle_in_transaction_session_timeout": str(
                self.config.idle_in_transaction_session_timeout_ms
            ),
            "timezone": self.config.timezone,
            "search_path": self.config.search_path,
        }
        with connection.cursor() as cursor:
            for name, value in values.items():
                cursor.execute("SELECT set_config(%s, %s, false)", [name, value])
        connection.commit()

    @staticmethod
    def _reset(connection: Any) -> None:
        if not connection.closed:
            connection.rollback()

    def acquire(self, *, timeout: float | None = None) -> Any:
        started = time.monotonic()
        connection = self._pool.getconn(timeout=timeout)
        self.metrics.increment("connection_acquire_count")
        self.metrics.increment(
            "connection_acquire_latency_ms", (time.monotonic() - started) * 1000
        )
        with self._checkout_lock:
            self._checked_out += 1
        return connection

    def release(self, connection: Any) -> None:
        try:
            self._pool.putconn(connection)
        finally:
            with self._checkout_lock:
                self._checked_out = max(0, self._checked_out - 1)

    @contextmanager
    def connection(self, *, timeout: float | None = None) -> Iterator[Any]:
        connection = self.acquire(timeout=timeout)
        try:
            yield connection
        finally:
            if not connection.closed:
                connection.rollback()
            self.release(connection)

    @contextmanager
    def transaction(self, name: str) -> Iterator[Any]:
        started = time.monotonic()
        self.metrics.increment("transaction_count")
        with self.connection() as connection:
            try:
                yield connection
                connection.commit()
            except Exception as exc:
                connection.rollback()
                self.metrics.increment("transaction_rollback_count")
                self._record_database_error(exc)
                raise
            finally:
                duration = (time.monotonic() - started) * 1000
                self.metrics.increment("transaction_duration_ms", duration)
                if duration >= self.config.long_transaction_ms:
                    self.metrics.increment("long_transaction_count")
                    LOGGER.warning(
                        "long database transaction",
                        extra={
                            "service": self.config.service,
                            "transaction_name": name,
                            "duration_ms": round(duration, 3),
                        },
                    )

    def _record_database_error(self, error: Exception) -> None:
        sqlstate = str(getattr(error, "sqlstate", "") or "")
        self.metrics.increment("query_failure_count")
        if sqlstate == "57014":
            self.metrics.increment("statement_timeout_count")
        elif sqlstate == "40P01":
            self.metrics.increment("deadlock_count")
        elif sqlstate == "40001":
            self.metrics.increment("serialization_failure_count")

    def health(self) -> dict[str, Any]:
        started = time.monotonic()
        with self.connection(timeout=self.config.timeout) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('application_name'), "
                    "current_setting('statement_timeout'), "
                    "current_setting('lock_timeout'), "
                    "current_setting('idle_in_transaction_session_timeout')"
                )
                session = cursor.fetchone()
        stats = self._pool.get_stats()
        pool_size = int(stats.get("pool_size", 0))
        available = int(stats.get("pool_available", 0))
        waiting = int(stats.get("requests_waiting", 0))
        with self._checkout_lock:
            checked_out = self._checked_out
        return {
            "status": "ready",
            "role": self.config.role,
            "service": self.config.service,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "pool_size": pool_size,
            "pool_available": available,
            "pool_in_use": checked_out,
            "pool_waiting": waiting,
            "pool_max_size": self.config.max_size,
            "session": {
                "application_name": session[0],
                "statement_timeout": session[1],
                "lock_timeout": session[2],
                "idle_in_transaction_session_timeout": session[3],
            },
            "metrics": self.metrics.snapshot(),
        }

    def close(self, *, timeout: float = 10.0) -> None:
        with self._checkout_lock:
            checked_out = self._checked_out
        if checked_out:
            self.metrics.increment("idle_in_transaction_detected", checked_out)
            raise RuntimeError(
                f"database pool cannot close with {checked_out} checked-out connection(s)"
            )
        self._pool.close(timeout=timeout)

    def assert_no_connection_leaks(self) -> None:
        with self._checkout_lock:
            checked_out = self._checked_out
        if checked_out:
            raise RuntimeError(
                f"database connection leak detected: {checked_out} checked-out connection(s)"
            )


class ConnectionPoolRegistry:
    """Process-local registry so all repositories share one bounded role pool."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runtimes: dict[tuple[str, str, str, str], DatabaseRuntime] = {}

    def get(self, database_url: str, *, role: str | None = None) -> DatabaseRuntime:
        config = DatabaseRuntimeConfig.from_env(database_url, role=role)
        key = config.registry_key
        with self._lock:
            runtime = self._runtimes.get(key)
            if runtime is None:
                runtime = DatabaseRuntime(config)
                self._runtimes[key] = runtime
            return runtime

    def close_all(self) -> None:
        with self._lock:
            runtimes = tuple(self._runtimes.values())
            self._runtimes.clear()
        for runtime in runtimes:
            runtime.close()

    def snapshots(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            runtimes = tuple(self._runtimes.values())
        return tuple(runtime.health() for runtime in runtimes)


class TransactionExecutor:
    """Explicit retry boundary for short, idempotent, pure-database work.

    Authority transactions do not opt into whole-transaction retry by default.
    Unknown commit/connection outcomes are surfaced as reconciliation work and
    are never blindly replayed.
    """

    def __init__(
        self,
        runtime: DatabaseRuntime,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.05,
        max_delay: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1 or base_delay < 0 or max_delay < base_delay:
            raise ValueError("database retry bounds are invalid")
        self.runtime = runtime
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.sleep = sleep

    def execute(
        self,
        transaction_name: str,
        operation: Callable[[Any], T],
        *,
        idempotency_key: str = "",
        retry_transient: bool = False,
        pure_database: bool = False,
        idempotent: bool = False,
        external_effects: bool = False,
        reconciliation_handler: Callable[[dict[str, str]], None] | None = None,
    ) -> T:
        if retry_transient and (
            not idempotency_key or not pure_database or not idempotent
        ):
            raise ValueError(
                "database retry requires a stable idempotency key and an "
                "explicit pure-database idempotent transaction"
            )
        if retry_transient and external_effects:
            raise ValueError(
                "database retry cannot wrap Provider, object-store, publish, "
                "webhook, callback, or other external effects"
            )
        attempt = 0
        while True:
            attempt += 1
            try:
                with self.runtime.transaction(transaction_name) as connection:
                    return operation(connection)
            except Exception as exc:
                sqlstate = str(getattr(exc, "sqlstate", "") or "")
                retry_class = classify_sqlstate(sqlstate)
                if retry_class is DatabaseRetryClass.RECONCILIATION_REQUIRED:
                    evidence = {
                        "transaction_name": transaction_name,
                        "idempotency_key": idempotency_key,
                        "sqlstate": sqlstate,
                        "classification": retry_class.value,
                    }
                    if reconciliation_handler is not None:
                        reconciliation_handler(evidence)
                    raise DatabaseReconciliationRequired(
                        transaction_name=transaction_name,
                        idempotency_key=idempotency_key,
                        sqlstate=sqlstate,
                    ) from exc
                should_retry = (
                    retry_transient
                    and retry_class is DatabaseRetryClass.SAFE_RETRY
                    and attempt < self.max_attempts
                )
                if not should_retry:
                    raise
                self.runtime.metrics.increment("database_retry_count")
                delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                delay *= random.uniform(0.5, 1.5)
                LOGGER.warning(
                    "retrying transient database transaction",
                    extra={
                        "service": self.runtime.config.service,
                        "transaction_name": transaction_name,
                        "sqlstate": sqlstate,
                        "retry_count": attempt,
                    },
                )
                self.sleep(delay)


REGISTRY = ConnectionPoolRegistry()


def get_database_runtime(
    database_url: str, *, role: str | None = None
) -> DatabaseRuntime:
    return REGISTRY.get(database_url, role=role)


def close_all_database_runtimes() -> None:
    REGISTRY.close_all()


def database_runtime_report(
    database_url: str, *, role: str = "api"
) -> dict[str, Any]:
    """Return a lightweight extensible pool and transaction metrics contract."""

    runtime = get_database_runtime(database_url, role=role)
    health = runtime.health()
    return {
        "type": "DatabaseRuntimeReport",
        "contract_version": "database-runtime-report-v1",
        "database_status": "READY",
        "role": health["role"],
        "service": health["service"],
        "database_identity_fingerprint": runtime.config.database_identity_fingerprint,
        "pool_config_fingerprint": runtime.config.pool_config_fingerprint,
        "pool_size": health["pool_size"],
        "pool_available": health["pool_available"],
        "pool_in_use": health["pool_in_use"],
        "pool_waiting": health["pool_waiting"],
        "pool_max_size": health["pool_max_size"],
        "connection_acquire_latency": health["metrics"][
            "connection_acquire_latency_ms"
        ],
        **health["metrics"],
    }


def validate_connection_budget(
    role_instances: dict[str, int],
    *,
    postgres_max_connections: int,
    management_reserve: int = 10,
    migration_reserve: int = 2,
    emergency_reserve: int = 5,
) -> dict[str, Any]:
    allocations: dict[str, int] = {}
    for role, count in role_instances.items():
        if role not in DEFAULT_ROLE_BUDGETS or count < 0:
            raise ValueError(f"invalid database budget role: {role}")
        allocations[role] = DEFAULT_ROLE_BUDGETS[role][1] * count
    reserved = management_reserve + migration_reserve + emergency_reserve
    allocated = sum(allocations.values())
    capacity = postgres_max_connections - reserved
    result = {
        "postgres_max_connections": postgres_max_connections,
        "management_reserve": management_reserve,
        "migration_reserve": migration_reserve,
        "emergency_reserve": emergency_reserve,
        "application_capacity": capacity,
        "allocations": allocations,
        "application_max_connections": allocated,
        "within_budget": allocated <= capacity,
    }
    if not result["within_budget"]:
        raise RuntimeError(
            f"database connection budget {allocated} exceeds capacity {capacity}"
        )
    return result


def authority_role_instances_from_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, int]:
    values = os.environ if env is None else env
    instances: dict[str, int] = {}
    for role, default in DEFAULT_AUTHORITY_ROLE_INSTANCES.items():
        raw = str(
            values.get(f"NOVEL_FORGE_DB_{role.upper()}_INSTANCES") or default
        )
        count = int(raw)
        if count < 0:
            raise ValueError(f"database role instance count must be nonnegative: {role}")
        instances[role] = count
    return instances


__all__ = [
    "ConnectionPoolRegistry",
    "DatabaseRuntime",
    "DatabaseRuntimeConfig",
    "DatabaseRuntimeMetrics",
    "DatabaseReconciliationRequired",
    "DatabaseRetryClass",
    "DEFAULT_AUTHORITY_ROLE_INSTANCES",
    "DEFAULT_ROLE_BUDGETS",
    "TRANSIENT_SQLSTATES",
    "TransactionExecutor",
    "authority_role_instances_from_env",
    "classify_sqlstate",
    "close_all_database_runtimes",
    "database_runtime_report",
    "get_database_runtime",
    "validate_connection_budget",
]
