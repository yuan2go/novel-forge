from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.chapter_authority.provider_views import (
    project_longform_prose_review_context_input,
)
from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import BOOK_FOLLOWUP_DEFINITION_VERSION
from .execution import PostgresReaderOutcomeExecutionContractBinder


class PostgresLongformProseReviewExecutionContractBinder(
    PostgresReaderOutcomeExecutionContractBinder
):
    workflow_definition_ref = (
        f"book_followup_longform_prose_review@{BOOK_FOLLOWUP_DEFINITION_VERSION}"
    )
    execution_binding_domain = "longform_prose_review"
    stage_name = "longform_prose_review"
    context_schema = "novelos.longform_prose_review_context_bundle.v2"

    def _project_context_input(
        self, asset_type: str, content: Mapping[str, Any]
    ) -> dict[str, Any]:
        return project_longform_prose_review_context_input(asset_type, content)

    def _target_scope(
        self,
        *,
        metadata: Mapping[str, Any],
        project_id: str,
        book_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        windows = [
            item
            for item in metadata.get("input_artifacts", [])
            if item.get("artifact_type") == "longform_prose_review_window"
        ]
        if len(windows) != 1:
            raise KernelError(
                "LONGFORM_PROSE_SCOPE_INVALID",
                "review requires one exact frozen window asset scope",
            )
        version = windows[0]["asset_version_id"]
        return {
            "scope_kind": "asset_version",
            "scope_id": version,
            "project_id": project_id,
            "book_id": book_id,
            "asset_version_id": version,
        }
