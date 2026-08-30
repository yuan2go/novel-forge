from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any
from uuid import uuid4

from novel_forge.storage.database_runtime import get_database_runtime


_AMBIENT_AUTHORITY_UOW: ContextVar["AuthorityUnitOfWork | None"] = ContextVar(
    "novel_forge_ambient_authority_uow", default=None
)


class AuthorityUnitOfWork:
    def __init__(
        self, database_url: str, *, coordinate_nested: bool = False
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.connection: Any | None = None
        self.cursor: Any | None = None
        self._runtime: Any | None = None
        self._committed = False
        self._coordinate_nested = coordinate_nested
        self._parent: AuthorityUnitOfWork | None = None
        self._savepoint_name = ""
        self._savepoint_active = False
        self._ambient_token: Token[AuthorityUnitOfWork | None] | None = None

    def __enter__(self) -> "AuthorityUnitOfWork":
        from novel_forge.storage.authority_repositories import AuthorityRepositories

        ambient = _AMBIENT_AUTHORITY_UOW.get()
        if (
            ambient is not None
            and ambient.database_url == self.database_url
            and ambient.connection is not None
        ):
            self._parent = ambient
            self._runtime = ambient._runtime
            self.connection = ambient.connection
            self.cursor = self.connection.cursor()
            self._savepoint_name = f"nf_nested_{uuid4().hex}"
            self.cursor.execute(f"SAVEPOINT {self._savepoint_name}")
            self._savepoint_active = True
            self.repositories = AuthorityRepositories(self.cursor)
            return self

        self._runtime = get_database_runtime(self.database_url)
        self.connection = self._runtime.acquire()
        self.cursor = self.connection.cursor()
        self.repositories = AuthorityRepositories(self.cursor)
        if self._coordinate_nested:
            self._ambient_token = _AMBIENT_AUTHORITY_UOW.set(self)
        return self

    def commit(self) -> None:
        if self.connection is None:
            raise RuntimeError("unit of work is not open")
        if self._parent is not None:
            if self._savepoint_active:
                self.cursor.execute(f"RELEASE SAVEPOINT {self._savepoint_name}")
                self._savepoint_active = False
        else:
            self.connection.commit()
        self._committed = True

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> bool:
        if self._parent is not None:
            if self._savepoint_active:
                self.cursor.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint_name}")
                self.cursor.execute(f"RELEASE SAVEPOINT {self._savepoint_name}")
                self._savepoint_active = False
            if self.cursor is not None:
                self.cursor.close()
            self.connection = None
            self.cursor = None
            self._parent = None
            return False
        if self.connection is not None:
            if self._ambient_token is not None:
                _AMBIENT_AUTHORITY_UOW.reset(self._ambient_token)
                self._ambient_token = None
            if exc_type is not None or not self._committed:
                self.connection.rollback()
            if self.cursor is not None:
                self.cursor.close()
            if self._runtime is not None:
                self._runtime.release(self.connection)
            self.connection = None
            self.cursor = None
        return False
