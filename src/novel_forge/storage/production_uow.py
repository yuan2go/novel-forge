"""Explicit PostgreSQL transaction boundary for production runtime state."""
from __future__ import annotations

from typing import Any

from novel_forge.storage.production_repositories import (AuditLogRepository, ConsumerDeliveryRepository, IdempotencyRepository, LifecycleCommandRepository, OperationLeaseRepository, OutboxRepository, ProductionOperationRepository, StateEventRepository)
from novel_forge.storage.database_runtime import get_database_runtime


class ProductionUnitOfWork:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("production PostgreSQL database_url is required")
        self.database_url = database_url
        self.connection: Any | None = None
        self.cursor: Any | None = None
        self._runtime: Any | None = None

    def __enter__(self) -> "ProductionUnitOfWork":
        self._runtime = get_database_runtime(self.database_url)
        self.connection = self._runtime.acquire()
        self.cursor = self.connection.cursor()
        self.operations = ProductionOperationRepository(self.cursor)
        self.idempotency = IdempotencyRepository(self.cursor)
        self.events = StateEventRepository(self.cursor)
        self.outbox = OutboxRepository(self.cursor)
        self.audit = AuditLogRepository(self.cursor)
        self.consumer_deliveries = ConsumerDeliveryRepository(self.cursor)
        self.leases = OperationLeaseRepository(self.cursor)
        self.commands = LifecycleCommandRepository(self.cursor)
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

    def transition(self, *, command: dict[str, Any], new_status: str, event: dict[str, Any], outbox: dict[str, Any], audit: dict[str, Any]) -> int:
        self.commands.record(command)
        version=self.operations.compare_and_set_status(command["operation_id"],command["project_id"],int(command["expected_version"]),command["expected_status"],new_status)
        self.events.append(event);self.outbox.enqueue(outbox);self.audit.append(audit)
        self.commands.mark_applied(command["command_id"],{"status":new_status,"version":version})
        return version

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> bool:
        if self.connection:
            if exc_type is not None:
                self.connection.rollback()
            else:
                self.connection.rollback()  # explicit commit is mandatory
            if self.cursor: self.cursor.close()
            if self._runtime is not None:
                self._runtime.release(self.connection)
            self.connection = None
            self.cursor = None
        return False
