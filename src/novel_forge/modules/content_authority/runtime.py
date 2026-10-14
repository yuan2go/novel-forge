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
    from novel_forge.modules.book_authority.creation_inputs import require_style_scope_frontier
    from novel_forge.modules.story_planning_runtime.world_preparation import require_world_revalidation_frontier

    return execute_authority_handler(
        database_url,
        command=command,
        registration=registry.registration(definition_name, definition_version),
        execution_probe=execution_probe,
        materialization_guard=require_style_scope_frontier if definition_name == "chapter.style_policy.compile" and definition_version == "2.1.6"
            else require_world_revalidation_frontier if definition_name == "story_planning.generate" else None,
    )


__all__ = ["execute_content_handler"]
