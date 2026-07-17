"""Chapter adapter over the shared fenced authority-handler runtime."""
from __future__ import annotations

from dataclasses import dataclass

from novel_forge.modules.authority_handler_runtime import (
    AuthorityExecutionResult,
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
    execute_authority_handler,
)
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterInputAsset,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.definitions import chapter_definition_version
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand


ChapterExecutionResult = AuthorityExecutionResult


@dataclass(frozen=True, slots=True)
class _ChapterHandlerAdapter:
    node: ChapterNode
    registry: ChapterHandlerRegistry

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        chapter_request = ChapterHandlerRequest(
            operation_id=request.operation_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            command=request.command,
            inputs=tuple(
                ChapterInputAsset(
                    asset_version_id=item.asset_version_id,
                    asset_type=item.asset_type,
                    content_hash=item.content_hash,
                    content=item.content,
                )
                for item in request.inputs
            ),
        )
        output = self.registry.require(self.node).execute(chapter_request)
        return AuthorityHandlerOutput(
            asset_type=output.asset_type,
            output_key=output.output_key,
            role=output.role,
            content=output.content,
            qualification_policy=output.qualification_policy,
            reference_asset_version_ids=tuple(
                item.asset_version_id for item in request.inputs
            ),
            evidence={"authority_family": "chapter"},
        )


def execute_chapter_handler(
    database_url: str,
    *,
    command: WorkerLeaseCommand,
    node: ChapterNode,
    registry: ChapterHandlerRegistry,
) -> ChapterExecutionResult:
    return execute_authority_handler(
        database_url,
        command=command,
        registration=AuthorityHandlerRegistration(
            definition_name=node.definition_name,
            definition_version=chapter_definition_version(
                registry.model_effects_required
            ),
            handler_key=node.handler_key,
            handler_contract_version="chapter-authority-handler-v2",
            output_asset_type=node.asset_type,
            output_key=node.output_key,
            role="primary",
            completion_topic=node.completion_topic,
            handler=_ChapterHandlerAdapter(node, registry),
        ),
    )


__all__ = ["ChapterExecutionResult", "execute_chapter_handler"]
