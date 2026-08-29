from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.integration import conftest as integration_conftest


class _Cursor:
    def __init__(
        self,
        events: list[str],
        database_name: str,
        *,
        read_only: bool,
    ) -> None:
        self._events = events
        self._database_name = database_name
        self._read_only = read_only
        self._last_query = ""

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        rendered = " ".join(str(statement).split())
        if "current_setting('transaction_read_only')" in rendered:
            self._last_query = "preflight"
            self._events.append("select-read-only-identity")
            return
        if "current_database()" in rendered:
            self._last_query = "cleanup-identity"
            self._events.append("select-cleanup-identity")
            return
        if "FROM pg_tables" in rendered:
            self._last_query = "tables"
            self._events.append("list-tables")
            return
        raise AssertionError(f"unexpected SQL in safety preflight: {rendered}")

    def fetchone(self) -> tuple[str, ...]:
        if self._last_query == "preflight":
            return (self._database_name, "on" if self._read_only else "off")
        return (self._database_name,)

    def fetchall(self) -> list[tuple[str]]:
        assert self._last_query == "tables"
        return []


class _Connection:
    def __init__(
        self,
        events: list[str],
        database_name: str,
        *,
        read_only: bool,
    ) -> None:
        self._events = events
        self._database_name = database_name
        self._read_only = read_only

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(
            self._events,
            self._database_name,
            read_only=self._read_only,
        )


def _fixture_generator() -> Iterator[None]:
    fixture = integration_conftest.isolate_postgresql_integration_module
    return fixture.__wrapped__()  # type: ignore[attr-defined, no-any-return]


def test_unsafe_database_is_rejected_before_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setenv("NOVEL_FORGE_DATABASE_URL", "postgresql:///postgres")

    def connect(_database_url: str, **kwargs: Any) -> _Connection:
        read_only = "default_transaction_read_only=on" in str(kwargs.get("options"))
        events.append("connect-read-only" if read_only else "connect-cleanup")
        return _Connection(events, "postgres", read_only=read_only)

    def migrate(_database_url: str) -> dict[str, bool]:
        events.append("migration")
        return {"ok": True}

    monkeypatch.setattr(integration_conftest.psycopg, "connect", connect)
    monkeypatch.setattr(integration_conftest, "run_migrations", migrate)

    with pytest.raises(AssertionError, match="refusing"):
        next(_fixture_generator())

    assert events == ["connect-read-only", "select-read-only-identity"]


@pytest.mark.parametrize(
    "database_name",
    ("postgres", "template0", "template1", "novel_forge", "", None),
)
def test_database_name_validator_fails_closed(database_name: object) -> None:
    with pytest.raises(AssertionError, match="refusing"):
        integration_conftest.require_disposable_test_database(database_name)


def test_database_name_validator_accepts_only_exact_test_suffix() -> None:
    assert (
        integration_conftest.require_disposable_test_database(
            "novel_forge_integration_test"
        )
        == "novel_forge_integration_test"
    )


def test_safe_preflight_is_read_only_and_precedes_migration_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection_kwargs: list[dict[str, Any]] = []
    monkeypatch.setenv(
        "NOVEL_FORGE_DATABASE_URL", "postgresql:///novel_forge_integration_test"
    )

    def connect(_database_url: str, **kwargs: Any) -> _Connection:
        connection_kwargs.append(dict(kwargs))
        read_only = "default_transaction_read_only=on" in str(kwargs.get("options"))
        events.append("connect-read-only" if read_only else "connect-cleanup")
        return _Connection(
            events,
            "novel_forge_integration_test",
            read_only=read_only,
        )

    def migrate(_database_url: str) -> dict[str, bool]:
        events.append("migration")
        return {"ok": True}

    monkeypatch.setattr(integration_conftest.psycopg, "connect", connect)
    monkeypatch.setattr(integration_conftest, "run_migrations", migrate)

    fixture = _fixture_generator()
    next(fixture)
    fixture.close()

    assert events == [
        "connect-read-only",
        "select-read-only-identity",
        "migration",
        "connect-cleanup",
        "select-cleanup-identity",
        "list-tables",
    ]
    assert connection_kwargs[0] == {
        "autocommit": True,
        "application_name": "novel-forge-pytest-safety-preflight",
        "connect_timeout": 5,
        "options": "-c default_transaction_read_only=on",
    }
    assert connection_kwargs[1] == {"autocommit": True}


def test_preflight_fails_closed_when_server_session_is_not_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setenv(
        "NOVEL_FORGE_DATABASE_URL", "postgresql:///novel_forge_integration_test"
    )

    def connect(_database_url: str, **_kwargs: Any) -> _Connection:
        events.append("connect-without-read-only")
        return _Connection(
            events,
            "novel_forge_integration_test",
            read_only=False,
        )

    def migrate(_database_url: str) -> dict[str, bool]:
        events.append("migration")
        return {"ok": True}

    monkeypatch.setattr(integration_conftest.psycopg, "connect", connect)
    monkeypatch.setattr(integration_conftest, "run_migrations", migrate)

    with pytest.raises(AssertionError, match="did not run read-only"):
        next(_fixture_generator())

    assert events == ["connect-without-read-only", "select-read-only-identity"]


def test_cleanup_connection_identity_is_rechecked_before_table_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection_count = 0
    monkeypatch.setenv(
        "NOVEL_FORGE_DATABASE_URL", "postgresql:///novel_forge_integration_test"
    )

    def connect(_database_url: str, **kwargs: Any) -> _Connection:
        nonlocal connection_count
        connection_count += 1
        read_only = "default_transaction_read_only=on" in str(kwargs.get("options"))
        events.append("connect-read-only" if read_only else "connect-cleanup")
        database_name = (
            "novel_forge_integration_test"
            if connection_count == 1
            else "different_integration_test"
        )
        return _Connection(events, database_name, read_only=read_only)

    def migrate(_database_url: str) -> dict[str, bool]:
        events.append("migration")
        return {"ok": True}

    monkeypatch.setattr(integration_conftest.psycopg, "connect", connect)
    monkeypatch.setattr(integration_conftest, "run_migrations", migrate)

    with pytest.raises(AssertionError, match="identity changed"):
        next(_fixture_generator())

    assert events == [
        "connect-read-only",
        "select-read-only-identity",
        "migration",
        "connect-cleanup",
        "select-cleanup-identity",
    ]
