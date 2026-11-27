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

    def _resolve_pack_snapshot(self, **arguments: Any):
        from novel_forge.modules.capability_pack_authority.runtime import CapabilityPackResolutionRequest
        from .prose_sampling import PROSE_SAMPLE_DEFINITION, PROSE_SAMPLE_WORKFLOW

        graph = arguments["graph"]
        if graph["definition_name"] != PROSE_SAMPLE_DEFINITION:
            return super()._resolve_pack_snapshot(**arguments)
        route = arguments["route"]
        if not self.capability_pack_id:
            raise KernelError("PROSE_SAMPLE_PACK_REQUIRED", "samples require the separately approved native sample Pack")
        return self.pack_resolver.freeze_attempt_snapshot(
            CapabilityPackResolutionRequest(project_id=arguments["project_id"], workspace_id=arguments["workspace_id"],
                book_id=arguments["book_id"], workflow_definition_ref=PROSE_SAMPLE_WORKFLOW,
                workflow_node_id=self.stage_name, environment=self.pack_environment, runtime_profile=self.pack_runtime_profile,
                release_channel=self.pack_release_channel, release_sha=route.release_sha,
                operation_definition_ref=graph["definition_name"] + "@" + graph["definition_version"],
                pack_id=self.capability_pack_id + ".samples"),
            operation_id=arguments["operation_id"], attempt_id=arguments["attempt_id"],
            execution_fencing_token=arguments["execution_fencing_token"], worker_id=arguments["worker_id"],
            snapshot_creation_fencing_token=arguments["snapshot_creation_fencing_token"],
            snapshot_creation_worker_id=arguments["snapshot_creation_worker_id"])

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
