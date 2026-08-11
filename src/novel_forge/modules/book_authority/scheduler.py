from __future__ import annotations

from dataclasses import dataclass
import os

from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    coordinate_saga,
)
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .registry import BookHandlerRegistry


@dataclass(frozen=True, slots=True)
class BookSchedulerTick:
    root_operation_id: str
    saga_id: str
    saga_status: str
    executed_operation_id: str = ""
    recovery_mode: str = "coordinate"


class BookAuthorityScheduler:
    def __init__(
        self, database_url: str, *, worker_id: str = "book-authority-worker"
    ) -> None:
        self.database_url = database_url
        self.worker_id = worker_id
        self.registry = BookHandlerRegistry()
        self.child_scheduler = ContentAuthorityScheduler(
            database_url, registry=self.registry, worker_id=worker_id
        )

    def tick(self, *, project_id: str, root_operation_id: str) -> BookSchedulerTick:
        if os.environ.get("NOVEL_FORGE_ENVIRONMENT", "development").lower() in {
            "production",
            "staging",
            "production_like",
        }:
            raise RuntimeError(
                "LEGACY_BOOK_AUTHORITY_PRODUCTION_DISABLED: "
                "use PostgresBookAuthorityScheduler"
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT saga_id, status FROM authority_saga WHERE project_id=%s AND root_operation_id=%s",
                [project_id, root_operation_id],
            )
            saga = uow.cursor.fetchone()
            if saga is None:
                raise ValueError("Book Saga is missing")
            uow.cursor.execute(
                "SELECT trace_id, correlation_id FROM authority_operation WHERE project_id=%s AND operation_id=%s",
                [project_id, root_operation_id],
            )
            trace_id, correlation_id = uow.cursor.fetchone()
        graph = GraphCommandContext(
            project_id, self.worker_id, str(trace_id), str(correlation_id)
        )
        coordinated = coordinate_saga(self.database_url, graph, str(saga[0]))
        if coordinated["status"] == "WAITING_GATE":
            return BookSchedulerTick(
                root_operation_id,
                str(saga[0]),
                "WAITING_GATE",
                recovery_mode="paused",
            )
        if coordinated["status"] in {
            "SUCCEEDED",
            "CANCELLED",
            "FAILED",
            "MANUAL_INTERVENTION",
        }:
            return BookSchedulerTick(
                root_operation_id, str(saga[0]), str(coordinated["status"])
            )
        pending = self.child_scheduler.pending_operations(limit=1)
        pending = tuple(item for item in pending if item[1] == project_id)
        if not pending:
            coordinated = coordinate_saga(self.database_url, graph, str(saga[0]))
            return BookSchedulerTick(
                root_operation_id, str(saga[0]), str(coordinated["status"])
            )
        operation_id, _ = pending[0]
        result = self.child_scheduler.run_or_recover(
            operation_id=operation_id, project_id=project_id
        )
        coordinated = coordinate_saga(self.database_url, graph, str(saga[0]))
        return BookSchedulerTick(
            root_operation_id,
            str(saga[0]),
            str(coordinated["status"]),
            operation_id,
            result.recovery_mode,
        )


__all__ = ["BookAuthorityScheduler", "BookSchedulerTick"]
