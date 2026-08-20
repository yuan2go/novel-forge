"""Content Authority entry point over the shared fenced runtime."""
from __future__ import annotations

from collections.abc import Callable

from novel_forge.modules.authority_handler_runtime import (
    AuthorityExecutionResult,
    AuthorityHandlerRegistry,
    execute_authority_handler,
)
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand


def execute_content_handler(
    database_url: str,
    *,
    command: WorkerLeaseCommand,
    definition_name: str,
    definition_version: str,
    registry: AuthorityHandlerRegistry,
    execution_probe: Callable[[], object] | None = None,
) -> AuthorityExecutionResult:
    return execute_authority_handler(
        database_url,
        command=command,
        registration=registry.registration(definition_name, definition_version),
        execution_probe=execution_probe,
    )


__all__ = ["execute_content_handler"]
