"""Short PostgreSQL transaction boundary for Command Kernel authority writes."""
from __future__ import annotations

from typing import Any

from novel_forge.storage.database_runtime import get_database_runtime


class AuthorityUnitOfWork:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.connection: Any | None = None
        self.cursor: Any | None = None
        self._runtime: Any | None = None
        self._committed = False

    def __enter__(self) -> "AuthorityUnitOfWork":
        from novel_forge.storage.authority_repositories import AuthorityRepositories
        self._runtime = get_database_runtime(self.database_url)
        self.connection = self._runtime.acquire()
        self.cursor = self.connection.cursor()
        self.repositories = AuthorityRepositories(self.cursor)
        return self

    def commit(self) -> None:
        if self.connection is None:
            raise RuntimeError("unit of work is not open")
        self.connection.commit()
        self._committed = True

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> bool:
        if self.connection is not None:
            if exc_type is not None or not self._committed:
                self.connection.rollback()
            if self.cursor is not None:
                self.cursor.close()
            if self._runtime is not None:
                self._runtime.release(self.connection)
            self.connection = None
            self.cursor = None
        return False
