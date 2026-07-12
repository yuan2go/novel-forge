"""Explicit PostgreSQL transaction boundary for production runtime state."""
from __future__ import annotations

from typing import Any

from novel_forge.storage.production_repositories import (AuditLogRepository, IdempotencyRepository, OutboxRepository, ProductionOperationRepository, StateEventRepository)


class ProductionUnitOfWork:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("production PostgreSQL database_url is required")
        self.database_url = database_url
        self.connection: Any | None = None
        self.cursor: Any | None = None

    def __enter__(self) -> "ProductionUnitOfWork":
        import psycopg
        self.connection = psycopg.connect(self.database_url, autocommit=False)
        self.cursor = self.connection.cursor()
        self.operations = ProductionOperationRepository(self.cursor)
        self.idempotency = IdempotencyRepository(self.cursor)
        self.events = StateEventRepository(self.cursor)
        self.outbox = OutboxRepository(self.cursor)
        self.audit = AuditLogRepository(self.cursor)
        return self

    def commit(self) -> None:
        if not self.connection: raise RuntimeError("unit of work is not open")
        self.connection.commit()

    def create_operation(self, *, operation: dict[str, Any], scope: str, event: dict[str, Any], outbox: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
        """Atomically create the operation authority and its durable evidence."""
        existing = self.idempotency.get(scope, str(operation["idempotency_key"]))
        if existing:
            if str(existing["request_digest"]) != str(operation["request_digest"]):
                raise ValueError("idempotency key belongs to a different request digest")
            return {"operation_id": existing["operation_id"], "idempotent_replay": True}
        self.operations.create(operation)
        self.idempotency.create(scope, str(operation["idempotency_key"]), str(operation["request_digest"]), str(operation["operation_id"]))
        self.events.append(event)
        self.outbox.enqueue(outbox)
        self.audit.append(audit)
        return {"operation_id": operation["operation_id"], "idempotent_replay": False}

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> bool:
        if self.connection:
            if exc_type is not None:
                self.connection.rollback()
            else:
                self.connection.rollback()  # explicit commit is mandatory
            if self.cursor: self.cursor.close()
            self.connection.close()
        return False
