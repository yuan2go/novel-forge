"""Short PostgreSQL transaction boundary for Command Kernel authority writes."""
from __future__ import annotations

from typing import Any


class AuthorityUnitOfWork:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.connection: Any | None = None
        self.cursor: Any | None = None

    def __enter__(self) -> "AuthorityUnitOfWork":
        import psycopg
        from novel_forge.storage.authority_repositories import AuthorityRepositories
        self.connection = psycopg.connect(self.database_url, autocommit=False)
        self.cursor = self.connection.cursor()
        self.repositories = AuthorityRepositories(self.cursor)
        return self

    def commit(self) -> None:
        if self.connection is None:
            raise RuntimeError("unit of work is not open")
        self.connection.commit()

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> bool:
        if self.connection is not None:
            if exc_type is not None:
                self.connection.rollback()
            self.cursor.close()
            self.connection.close()
        return False
