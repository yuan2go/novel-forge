"""INVARIANT: Lease/fence recovery scheduler for Source import Operations."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.scheduler import SourceAuthorityScheduler

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

    def run_or_recover(
        self, *, operation_id: str, project_id: str
    ) -> dict[str, Any]:
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
