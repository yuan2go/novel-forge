from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.scheduler import SourceAuthorityScheduler

from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .application import SourceImportApplication
from .definitions import SOURCE_IMPORT_OPERATIONS


class SourceImportScheduler(SourceAuthorityScheduler):
    def __init__(
        self,
        application: SourceImportApplication,
        *,
        worker_id: str = "source-import-worker",
        lease_seconds: int = 30,
    ) -> None:
        super().__init__(
            application,  # type: ignore[arg-type]
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        self.operation_names = SOURCE_IMPORT_OPERATIONS
        self.output_keys = frozenset({"source.import.repository_snapshot"})

    def pending_for_job(
        self, *, project_id: str, import_job_id: str, limit: int = 50, excluded: tuple[str, ...] = ()
    ) -> tuple[tuple[str, str], ...]:
        from novel_forge.storage.source_import_repositories import (
            SourceImportRepository,
        )

        if not 1 <= limit <= 1000:
            raise ValueError("limit must be 1..1000")
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            repository.job(project_id=project_id, import_job_id=import_job_id)
            return repository.job_ready_operations(project_id, import_job_id, limit, excluded)

    def _reconcile_waiting_operation(self, worker: WorkerLeaseCommand) -> str:
        return self.application.reconcile_external_state(worker)

    def run_or_recover(self, *, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """SELECT j.status FROM authority_source_import_work w
                JOIN authority_source_import_job j USING(import_job_id,project_id)
                WHERE w.operation_id=%s AND w.project_id=%s AND j.source_type='corpus_content'""",
                [operation_id, project_id],
            )
            job = uow.cursor.fetchone()
        if job and job[0] == "PAUSED":
            raise KernelError(
                "CORPUS_IMPORT_PAUSED",
                "resume the frozen job before starting another stage",
            )
        try:
            return super().run_or_recover(
                operation_id=operation_id, project_id=project_id
            )
        except Exception as exc:
            if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
                self.application.record_execution_failure(
                    operation_id=operation_id,
                    project_id=project_id,
                    error_code=(
                        exc.code if isinstance(exc, KernelError) else "PROGRAMMING_BUG"
                    ),
                    error_message=str(exc),
                )
            raise


__all__ = ["SourceImportScheduler"]
