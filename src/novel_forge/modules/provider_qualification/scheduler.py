from __future__ import annotations

from typing import Any

from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .authority import D0QualificationAuthority, D0QualificationCommand
from .definitions import D0_OPERATION
from .domain import D0ProbeConfig


class D0QualificationScheduler:
    def __init__(self, application: D0QualificationAuthority) -> None:
        self.application = application
        self.database_url = application.database_url

    def pending_operations(self, *, limit: int = 20) -> tuple[tuple[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, project_id
                FROM authority_operation
                WHERE definition_name=%s AND status IN ('READY', 'FAILED_RETRYABLE')
                ORDER BY created_at, operation_id LIMIT %s
                """,
                [D0_OPERATION, limit],
            )
            return tuple((str(row[0]), str(row[1])) for row in uow.cursor.fetchall())

    def run_or_recover(self, *, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT workspace_id, actor_id, idempotency_key, trace_id,
                       correlation_id, command_payload
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s AND definition_name=%s
                """,
                [operation_id, project_id, D0_OPERATION],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise ValueError("D0 Operation does not exist")
        payload = dict(row[5])
        command = D0QualificationCommand(
            project_id=project_id,
            workspace_id=str(row[0]),
            actor_id=str(row[1]),
            idempotency_key=str(row[2]),
            trace_id=str(row[3]),
            correlation_id=str(row[4]),
            config=D0ProbeConfig.from_mapping(dict(payload["config"])),
        )
        return self.application.execute_fixture(command)


__all__ = ["D0QualificationScheduler"]
