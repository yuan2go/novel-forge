"""Content Authority entry point over the shared fenced runtime."""
from __future__ import annotations

from novel_forge.modules.authority_handler_runtime import AuthorityExecutionResult, execute_authority_handler
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.content_authority.registry import ContentHandlerRegistry


def execute_content_handler(
    database_url: str,
    *,
    command: WorkerLeaseCommand,
    definition_name: str,
    definition_version: str,
    registry: ContentHandlerRegistry,
) -> AuthorityExecutionResult:
    return execute_authority_handler(
        database_url,
        command=command,
        registration=registry.registration(definition_name, definition_version),
    )


__all__ = ["execute_content_handler"]
