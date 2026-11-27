from __future__ import annotations

from novel_forge.modules.mkaos_authority.application import MkaosAuthorityApplication
from novel_forge.modules.mkaos_authority.definitions import MKAOS_AUTHORITY_OPERATIONS
from novel_forge.modules.source_authority.scheduler import SourceAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class MkaosAuthorityScheduler(SourceAuthorityScheduler):

    def __init__(
        self,
        application: MkaosAuthorityApplication,
        *,
        worker_id: str = "mkaos-authority-worker",
        lease_seconds: int = 30,
    ) -> None:
        super().__init__(
            application,  # type: ignore[arg-type]
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        self.operation_names = MKAOS_AUTHORITY_OPERATIONS
        self.output_keys = frozenset(
            {
                "mkaos.knowledge.candidate",
                "mkaos.knowledge.decision",
                "mkaos.knowledge.card",
                "mkaos.knowledge.pack",
            }
        )

    def pending_operations(self, *, limit: int = 50) -> tuple[tuple[str, str], ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.operation_id, operation.project_id
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT lease.expires_at
                    FROM authority_attempt AS attempt
                    JOIN authority_lease_acquisition AS lease
                      ON lease.attempt_id = attempt.attempt_id
                    WHERE attempt.operation_id = operation.operation_id
                      AND lease.status = 'HELD'
                    ORDER BY attempt.attempt_number DESC,
                             lease.fencing_token DESC
                    LIMIT 1
                ) AS active_lease ON TRUE
                WHERE operation.definition_name = ANY(%s)
                  AND operation.status IN ('READY', 'FAILED_RETRYABLE', 'EXECUTING')
                  AND (
                      active_lease.expires_at IS NULL
                      OR active_lease.expires_at <= NOW()
                  )
                ORDER BY operation.created_at, operation.operation_id
                LIMIT %s
                """,
                [list(MKAOS_AUTHORITY_OPERATIONS), limit],
            )
            rows = uow.cursor.fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)


__all__ = ["MkaosAuthorityScheduler"]
